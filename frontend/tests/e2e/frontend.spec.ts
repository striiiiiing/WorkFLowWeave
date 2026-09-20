/**
 * 前端完整流程浏览器测试：通过页面操作与真实 API 验证资源 JSON 校验、创建编辑，以及 Workflow 保存、触发和版本化正文查询。使用 Playwright 配置启动的临时后端与本地预览服务；同时检查浏览器运行错误。
 */
import { test, expect } from '@playwright/test'

test('resource JSON validation, create and edit use the real API', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/resources')
  await page.getByRole('button', { name: '新建资源' }).click()
  await page.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
  await page.getByLabel('资源 ID（留空自动生成）', { exact: true }).fill('browser_source')
  await page.getByLabel('采集器', { exact: true }).click()
  await page.getByRole('option', { name: 'mock', exact: true }).click()
  await page
    .getByRole('region', { name: '插件参数 (options)', exact: true })
    .getByRole('button', { name: '编辑 JSON', exact: true })
    .click()
  const setters = page.getByRole('region', { name: '处理规则 (setters)', exact: true })
  await setters.getByRole('switch', { name: '设置 sort_by', exact: true }).locator('..').click()
  await setters.getByRole('textbox', { name: 'sort_by', exact: true }).fill('message')
  await setters.getByRole('switch', { name: '设置 descending', exact: true }).locator('..').click()
  await setters.getByRole('switch', { name: 'descending', exact: true }).locator('..').click()
  const options = page.getByRole('textbox', { name: '插件参数 (options)', exact: true })
  await options.fill('{invalid')
  await page.getByRole('button', { name: '保存资源' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.locator('.el-form-item__error')).toBeVisible()
  expect((await request.get('/api/sources/browser_source')).status()).toBe(409)
  await options.fill('{}')
  await page.getByRole('button', { name: '保存资源' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(page.getByRole('heading', { name: 'browser_source' })).toBeVisible()
  expect((await (await request.get('/api/sources/browser_source')).json()).setters).toEqual({
    sort_by: 'message',
    descending: true,
  })
  await page
    .locator('.el-card .el-card')
    .filter({ has: page.getByRole('heading', { name: 'browser_source' }) })
    .getByRole('button', { name: '编辑', exact: true })
    .click()
  await page.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
  await expect(page.getByLabel('资源 ID（留空自动生成）', { exact: true })).toHaveValue(
    'browser_source',
  )
  await expect(page.getByLabel('资源 ID（留空自动生成）', { exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '保存资源' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  expect(errors).toEqual([])
})

test('workflow create, reload, run, and versioned phase reading', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  for (const [kind, value] of Object.entries({
    sources: { id: 'offline_source', collector: 'mock', options: {}, on_empty: 'stop' },
    ai: {
      id: 'offline_ai',
      provider: 'http',
      base_url: 'http://127.0.0.1:1/v1',
      models: { offline_model: {} },
      retries: 0,
    },
  })) {
    const response = await request.post(`/api/${kind}`, { data: value })
    expect(response.ok(), await response.text()).toBe(true)
  }
  expect(
    (
      await request.post('/api/sources', {
        data: {
          id: 'second_source',
          collector: 'mock',
          options: { mode: 'empty' },
          on_empty: 'stop',
        },
      })
    ).ok(),
  ).toBe(true)
  await page.goto('/workflows/new')
  await expect(page.getByText('采集并发数', { exact: true })).toHaveCount(0)
  await expect(page.getByText('允许发送部分成功的结果', { exact: true })).toHaveCount(0)
  await page.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
  await expect(page.getByText('包含采集数量', { exact: true })).toBeVisible()
  await page.getByLabel('工作流 ID（留空自动生成）', { exact: true }).fill('browser_workflow')
  await page.getByLabel('显示名称', { exact: true }).fill('浏览器验证工作流')
  await page.getByText('选择数据源', { exact: true }).click()
  await page.getByRole('option', { name: 'offline_source', exact: true }).click()
  await page.getByRole('option', { name: 'second_source', exact: true }).click()
  await page.getByRole('heading', { name: '1. 数据采集' }).click()
  await page.getByRole('button', { name: '上移 second_source', exact: true }).click()
  await page.getByRole('button', { name: '添加任务' }).click()
  await page.getByText('选择 AI 配置', { exact: true }).click()
  await page.getByRole('option', { name: 'offline_ai', exact: true }).click()
  await page.getByText('选择模型', { exact: true }).click()
  await page.getByRole('option', { name: 'offline_model', exact: true }).click()
  await page.screenshot({ path: 'test-results/workflow-editor.png', fullPage: true })
  await page.getByRole('button', { name: '保存工作流' }).click()
  await expect(page).toHaveURL(/\/workflows$/)
  const saved = await (await request.get('/api/workflows/browser_workflow')).json()
  expect(saved.sources).toEqual(['second_source', 'offline_source'])
  expect(saved.analyses).toEqual([
    { id: 'task_1', ai: 'offline_ai', model: 'offline_model', prompt: '{input}' },
  ])
  expect(saved.backup.enabled).toBe(true)
  expect(saved.include_counts).toBe(true)
  expect(saved.interval_seconds).toBeNull()
  expect(saved.description).toBeUndefined()
  // The built-in offline collector exits before AI, so this smoke test never calls a model service.
  saved.source_overrides = {
    offline_source: { options: { mode: 'empty' }, setters: {}, template: null },
  }
  expect((await request.put('/api/workflows/browser_workflow', { data: saved })).ok()).toBe(true)
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(page.getByLabel('显示名称', { exact: true })).toHaveValue('浏览器验证工作流')
  await page.getByRole('button', { name: '保存工作流' }).click()
  await expect(page).toHaveURL(/\/workflows$/)
  const reloaded = await (await request.get('/api/workflows/browser_workflow')).json()
  expect(reloaded.source_overrides).toEqual(saved.source_overrides)
  await page.getByRole('button', { name: '立即运行' }).click()
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  await expect(page.getByRole('heading', { name: '阶段执行流程与只读产物' })).toBeVisible()
  const phaseRequest = page.waitForRequest((request) =>
    /\/phases\/collect\?version=\d+$/.test(request.url()),
  )
  await page.getByRole('button', { name: '查看正文' }).first().click()
  await phaseRequest
  await expect(page.getByRole('dialog')).toContainText('业务版本 v')
  await page.goto('/workflows')
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await expect(page.getByRole('heading', { name: '浏览器验证工作流' })).toHaveCount(0)
  expect((await request.get('/api/workflows')).ok()).toBe(true)
  expect(await (await request.get('/api/workflows')).json()).toEqual([])
  expect(errors).toEqual([])
})

test('mobile navigation, theme and all primary routes render without overflow', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  await page.getByRole('button', { name: '打开导航' }).click()
  await page.getByRole('dialog').getByRole('link', { name: '插件与能力' }).click()
  await expect(page.getByRole('heading', { name: '插件与能力' })).toBeVisible()
  await expect(page.getByRole('dialog')).toBeHidden()
  await page.getByRole('button', { name: '切换深色模式' }).click()
  await page.reload()
  await expect(page.locator('html')).toHaveClass('dark')
  for (const path of ['/', '/workflows', '/workflows/new', '/runs', '/resources', '/plugins']) {
    await page.goto(path)
    await expect(page.locator('main h1')).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    )
    expect(overflow, `horizontal overflow on ${path}`).toBe(false)
  }
  await page.screenshot({ path: 'test-results/mobile-dark.png', fullPage: true })
  expect(errors).toEqual([])
})

test('AI keys are masked on entry and saved as encrypted credentials with an automatic ID', async ({
  page,
  request,
}) => {
  await page.goto('/resources')
  await page.getByRole('tab', { name: 'AI 配置', exact: true }).click()
  await page.getByRole('button', { name: '新建资源' }).click()
  await expect(page.getByLabel('资源 ID（留空自动生成）')).toHaveCount(0)
  await page.getByLabel('AI 提供商', { exact: true }).fill('http')
  await page.getByLabel('服务地址', { exact: true }).fill('http://127.0.0.1:1/v1')
  const key = page.getByLabel('API 密钥', { exact: true })
  await key.fill('browser-test-key')
  await expect(key).toHaveAttribute('type', 'password')
  await page.locator('.el-input__password').click()
  await expect(key).toHaveAttribute('type', 'text')
  await page.locator('.el-input__password').click()
  const models = page.getByRole('region', { name: '模型配置（模型名 → 参数对象）', exact: true })
  await models
    .getByRole('textbox', { name: '模型配置（模型名 → 参数对象） 新字段名', exact: true })
    .fill('test-model')
  await models.getByRole('button', { name: '添加字段', exact: true }).click()
  const savedResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/ai') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '保存资源' }).click()
  const response = await savedResponse
  expect(response.ok(), await response.text()).toBe(true)
  const saved = await response.json()
  expect(saved.id).toMatch(/^[0-9a-f-]{36}$/)
  expect(saved.api_key.kind).toBe('encrypted')
  expect(JSON.stringify(saved)).not.toContain('browser-test-key')
  await expect(page.getByRole('dialog')).toBeHidden()
  expect((await request.delete(`/api/ai/${saved.id}`)).ok()).toBe(true)
})
