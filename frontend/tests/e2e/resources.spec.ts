import { expect, test } from '@playwright/test'

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
      collector: 'mock',
      display_name: '窄屏数据源',
      enabled: false,
      options: { mode: 'empty' },
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
  await drawer.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
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
