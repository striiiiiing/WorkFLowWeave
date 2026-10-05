import { expect, test } from '@playwright/test'
import { createServer } from 'node:http'
import { once } from 'node:events'

test('discovered models appear asynchronously and can be selected and saved in bulk', async ({
  page,
  request,
}) => {
  // Only a disposable backend and a local provider fixture are used by this test.
  const models = Array.from({ length: 35 }, (_, index) => `vendor/model-${index + 1}`)
  let releaseCatalog!: () => void
  const catalogReady = new Promise<void>((resolve) => {
    releaseCatalog = resolve
  })
  const requests: { path: string | undefined; authorization: string | undefined }[] = []
  const upstream = createServer(async (req, response) => {
    requests.push({ path: req.url, authorization: req.headers.authorization })
    await catalogReady
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: models.map((id) => ({ id })) }))
  })
  upstream.listen(0, '127.0.0.1')
  await once(upstream, 'listening')
  const address = upstream.address()
  if (!address || typeof address === 'string') throw new Error('Missing fixture address')
  let savedId: string | undefined
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    await page.goto('/resources?kind=ai')
    await page.getByRole('button', { name: '添加供应商渠道' }).click()
    await page.getByLabel('服务地址', { exact: true }).fill(`http://127.0.0.1:${address.port}/v1`)
    await page.getByLabel('API 密钥', { exact: true }).fill('discovery-test-key')
    const region = page.getByRole('region', { name: '渠道模型', exact: true })
    const select = region.locator('.el-select').first()
    await select.click()
    await expect(page.getByRole('status').filter({ hasText: '正在读取模型列表' })).toBeVisible()
    releaseCatalog()
    await expect(page.getByText('发现 35 个模型', { exact: true })).toBeVisible()
    const options = page.getByRole('listbox').getByRole('option')
    await expect(options).toHaveCount(35)
    await page.getByRole('option', { name: 'vendor/model-1', exact: true }).click()
    await page.getByRole('option', { name: 'vendor/model-2', exact: true }).click()
    await expect(page.getByRole('option', { name: 'vendor/model-1', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await expect(page.getByRole('option', { name: 'vendor/model-2', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await region.getByRole('button', { name: '添加模型', exact: true }).click()
    await expect(
      region.getByRole('button', { name: '移除模型 vendor/model-1', exact: true }),
    ).toBeVisible()
    await expect(
      region.getByRole('button', { name: '移除模型 vendor/model-2', exact: true }),
    ).toBeVisible()
    const savedResponse = page.waitForResponse(
      (response) => response.url().endsWith('/api/ai') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '保存渠道', exact: true }).click()
    const response = await savedResponse
    expect(response.ok(), await response.text()).toBe(true)
    const saved = await response.json()
    savedId = saved.id
    expect(saved.models).toEqual({ 'vendor/model-1': {}, 'vendor/model-2': {} })
    expect((await (await request.get(`/api/ai/${savedId}`)).json()).models).toEqual(saved.models)
    expect(requests).toEqual([{ path: '/v1/models', authorization: 'Bearer discovery-test-key' }])
    expect(errors).toEqual([])
  } finally {
    releaseCatalog()
    if (savedId) await request.delete(`/api/ai/${savedId}`)
    upstream.closeAllConnections()
    await new Promise<void>((resolve, reject) =>
      upstream.close((error) => (error ? reject(error) : resolve())),
    )
  }
})

test('resource editor shares catalogs and saves a retained draft at 375px', async ({
  page,
  request,
}) => {
  const id = 'p2_mobile_source'
  const errors: string[] = []
  const reads: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('request', (request) => {
    if (request.method() === 'GET') reads.push(new URL(request.url()).pathname)
  })
  const response = await request.post('/api/sources', {
    data: {
      id,
      call: { kind: 'cli', mode: 'shell', command: 'true', cwd: null },
      display_name: '窄屏数据源',
      enabled: false,
    },
  })
  expect(response.ok(), await response.text()).toBe(true)
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/resources')
  const card = page
    .locator('.el-card .el-card')
    .filter({ has: page.getByRole('heading', { name: '窄屏数据源', exact: true }) })
  await card.getByRole('button', { name: '编辑', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '编辑共用数据源' })
  await expect(drawer.getByLabel('数据源名称', { exact: true })).toHaveValue('窄屏数据源')
  for (const path of ['/api/sources', '/api/plugins', '/api/workflows'])
    expect(
      reads.filter((value) => value === path),
      path,
    ).toHaveLength(1)
  await drawer.getByLabel('数据源名称', { exact: true }).fill('保留本次草稿')
  // Update the real catalog externally; editor input stays in its own controller.
  const current = await (await request.get(`/api/sources/${id}`)).json()
  expect(
    (
      await request.put(`/api/sources/${id}`, { data: { ...current, display_name: '外部更新' } })
    ).ok(),
  ).toBe(true)
  await page
    .getByRole('button', { name: '刷新', exact: true })
    .evaluate((button: HTMLButtonElement) => button.click())
  await expect(card).toHaveCount(0)
  await expect(drawer.getByLabel('数据源名称', { exact: true })).toHaveValue('保留本次草稿')
  await drawer.locator('summary').filter({ hasText: '高级配置' }).click()
  await drawer.getByRole('spinbutton', { name: '超时 / 秒' }).fill('25')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  const save = drawer.getByRole('button', { name: '保存资源', exact: true })
  await save.scrollIntoViewIfNeeded()
  const bounds = await save.boundingBox()
  expect(bounds!.height).toBeGreaterThanOrEqual(44)
  await page.screenshot({ path: 'test-results/p2-resource-mobile.png', fullPage: true })
  await save.click()
  await expect(drawer).toBeHidden()
  expect(await (await request.get(`/api/sources/${id}`)).json()).toMatchObject({
    display_name: '保留本次草稿',
    enabled: false,
    timeout: 25,
  })
  for (const tab of ['供应商渠道', '通知渠道', '数据源']) {
    await page.getByRole('tab', { name: tab, exact: true }).click()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
  }
  expect((await request.delete(`/api/sources/${id}`)).ok()).toBe(true)
  expect(errors).toEqual([])
})
