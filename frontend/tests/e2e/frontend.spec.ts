/**
 * 前端完整流程浏览器测试：通过页面操作与真实 API 验证资源 JSON 校验、创建编辑，以及 Workflow 保存、触发和版本化正文查询。使用 Playwright 配置启动的临时后端与本地预览服务；同时检查浏览器运行错误。
 */
import { test, expect } from '@playwright/test'

test('resource arrays keep repeated entries and ordered selections after saving', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const record = { message: 'repeatable record', level: 'INFO' }
  const created = await request.post('/api/sources', {
    data: { id: 'array_editor_source', collector: 'mock', options: { records: [record] } },
  })
  expect(created.ok(), await created.text()).toBe(true)
  await page.goto('/resources')
  const card = page
    .locator('.el-card .el-card')
    .filter({ has: page.getByRole('heading', { name: 'array_editor_source' }) })
  await card.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(page.locator('textarea[aria-label="records"]')).toHaveCount(0)
  await page.getByRole('button', { name: '重复添加 records 第 1 项', exact: true }).click()
  await page.getByRole('button', { name: '保存资源', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  expect(
    (await (await request.get('/api/sources/array_editor_source')).json()).options.records,
  ).toEqual([record, record])
  await card.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(
    page.getByRole('region', { name: 'records 列表', exact: true }).getByRole('textbox'),
  ).toHaveCount(2)
  await page.getByRole('button', { name: '删除 records 第 1 项', exact: true }).click()
  await page.getByRole('button', { name: '保存资源', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  expect(
    (await (await request.get('/api/sources/array_editor_source')).json()).options.records,
  ).toEqual([record])

  await page.getByRole('button', { name: '添加数据源', exact: true }).click()
  await page.getByLabel('采集器', { exact: true }).click()
  await page.getByRole('option', { name: 'history', exact: true }).click()
  await page.getByRole('switch', { name: '设置 limit', exact: true }).locator('..').click()
  await expect(page.getByText('limit（数字）', { exact: true })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'limit 类型', exact: true })).toHaveCount(0)
  const limit = page.getByRole('textbox', { name: 'limit', exact: true })
  await limit.fill('12a')
  await page.getByRole('button', { name: '保存资源', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(limit).toHaveValue('12a')
  await expect(page.getByRole('dialog')).toContainText('请输入有效整数，例如 10，不能混入文字。')
  await expect(page.getByRole('dialog')).not.toContainText('Unexpected')
  await limit.fill('3')
  await page.getByRole('switch', { name: '设置 stages', exact: true }).locator('..').click()
  const stages = page.getByRole('region', { name: 'stages 列表', exact: true })
  await page.getByRole('button', { name: '添加 stages 项目', exact: true }).click()
  await stages.locator('.el-select').nth(1).click()
  await page.getByRole('option', { name: 'aggregate', exact: true }).click()
  await page.getByRole('button', { name: '上移 stages 第 2 项', exact: true }).click()
  const savedResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/sources') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '保存资源', exact: true }).click()
  const response = await savedResponse
  expect(response.ok(), await response.text()).toBe(true)
  const saved = await response.json()
  expect(response.request().postDataJSON().options).toEqual({
    limit: 3,
    stages: ['aggregate', 'collect'],
  })
  expect(saved.options).toMatchObject({ limit: 3, stages: ['aggregate', 'collect'] })
  await expect(page.getByRole('dialog')).toBeHidden()
  await page
    .locator('.el-card .el-card')
    .filter({ has: page.getByRole('heading', { name: saved.id }) })
    .getByRole('button', { name: '编辑', exact: true })
    .click()
  await expect(stages.locator('.el-select').nth(0)).toContainText('aggregate')
  await expect(stages.locator('.el-select').nth(1)).toContainText('collect')
  await stages.screenshot({
    path: 'test-results/resource-array-editor.png',
    animations: 'disabled',
  })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  expect((await request.delete(`/api/sources/${saved.id}`)).ok()).toBe(true)
  expect((await request.delete('/api/sources/array_editor_source')).ok()).toBe(true)
  expect(errors).toEqual([])
})

test('resource JSON validation, create and edit use the real API', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/resources')
  await page.getByRole('button', { name: '添加数据源' }).click()
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
  await page.getByText('选择供应商渠道', { exact: true }).click()
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

test('provider models are configured in the channel and selected by workflows', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  const healthRequests: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('request', (request) => {
    if (request.url().endsWith('/check-connection')) healthRequests.push(request.url())
  })
  await page.goto('/resources?kind=ai')
  await page.getByRole('button', { name: '添加供应商渠道' }).click()
  await expect(page.getByLabel('资源 ID（留空自动生成）')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '检查健康', exact: true })).toBeDisabled()
  await page.getByLabel('服务地址', { exact: true }).fill('http://127.0.0.1:1/v1')
  const key = page.getByLabel('API 密钥', { exact: true })
  await key.fill('browser-test-key')
  await expect(key).toHaveAttribute('type', 'password')
  await page.locator('.el-input__password').click()
  await expect(key).toHaveAttribute('type', 'text')
  await page.locator('.el-input__password').click()
  const models = page.getByRole('region', { name: '渠道模型', exact: true })
  await models.getByRole('textbox', { name: '模型名称', exact: true }).fill('openai/test.v1')
  await models.getByRole('button', { name: '添加模型', exact: true }).click()
  await expect(models.getByText('openai/test.v1', { exact: true })).toBeVisible()
  await models.getByRole('textbox', { name: '模型名称', exact: true }).fill('openai/backup.v2')
  await models.getByRole('button', { name: '添加模型', exact: true }).click()
  await page.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
  await page.getByLabel('超时 / 秒', { exact: true }).fill('1')
  await page.getByLabel('重试次数', { exact: true }).fill('0')
  const savedResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/ai') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '保存渠道', exact: true }).click()
  const response = await savedResponse
  expect(response.ok(), await response.text()).toBe(true)
  const saved = await response.json()
  expect(saved.id).toMatch(/^[0-9a-f-]{36}$/)
  expect(saved.api_key.kind).toBe('encrypted')
  expect(JSON.stringify(saved)).not.toContain('browser-test-key')
  expect(saved.models).toEqual({ 'openai/test.v1': {}, 'openai/backup.v2': {} })
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.screenshot({ path: 'test-results/provider-editor.png', fullPage: true })
  expect(healthRequests).toEqual([])
  const healthResponse = page.waitForResponse((response) =>
    response.url().endsWith('/check-connection'),
  )
  await page.getByRole('button', { name: '检查健康', exact: true }).click()
  expect((await healthResponse).ok()).toBe(false)
  await expect(
    page.getByRole('region', { name: '渠道健康检查' }).locator('.el-alert--error'),
  ).toBeVisible()
  expect(healthRequests).toHaveLength(1)
  await expect(models.getByText('openai/test.v1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  const card = page
    .locator('.el-card .el-card')
    .filter({ has: page.getByRole('heading', { name: saved.id }) })
  await expect(card).toContainText('2 个已配置模型')
  await expect(card.getByRole('button', { name: '检查健康' })).toHaveCount(0)
  await card.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(
    page.getByRole('region', { name: '渠道模型' }).getByText('openai/test.v1', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '配置参数', exact: true }).first().click()
  const parameters = page
    .getByRole('region', { name: '额外请求参数（extra_body）', exact: true })
    .first()
  await parameters
    .getByRole('switch', { name: '设置 enable_thinking', exact: true })
    .locator('..')
    .click()
  await parameters
    .getByRole('switch', { name: 'enable_thinking', exact: true })
    .locator('..')
    .click()
  const updatedResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/ai/${saved.id}`) && response.request().method() === 'PUT',
  )
  await page.getByRole('button', { name: '保存渠道', exact: true }).click()
  const updated = await updatedResponse
  expect(updated.ok(), await updated.text()).toBe(true)
  expect((await updated.json()).models).toEqual({
    'openai/test.v1': { enable_thinking: true },
    'openai/backup.v2': {},
  })
  await page.getByRole('button', { name: '关闭', exact: true }).click()

  const source = await request.post('/api/sources', {
    data: { id: 'model_flow_source', collector: 'mock', options: {} },
  })
  expect(source.ok(), await source.text()).toBe(true)
  await page.goto('/workflows/new')
  await page.getByLabel('显示名称', { exact: true }).fill('模型配置流程')
  await page.getByText('选择数据源', { exact: true }).click()
  await page.getByRole('option', { name: 'model_flow_source', exact: true }).click()
  await page.getByRole('heading', { name: '1. 数据采集' }).click()
  await page.getByRole('button', { name: '添加任务', exact: true }).click()
  const modelsResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/ai') && response.request().method() === 'GET',
  )
  await page.getByRole('button', { name: '刷新模型列表', exact: true }).click()
  expect((await modelsResponse).ok()).toBe(true)
  await expect(page.getByLabel('显示名称', { exact: true })).toHaveValue('模型配置流程')
  await expect(page.getByRole('heading', { name: '分析任务 1', exact: true })).toBeVisible()
  await page.getByText('选择供应商渠道', { exact: true }).click()
  await page.getByRole('option', { name: saved.id, exact: true }).click()
  await page.getByText('选择模型', { exact: true }).click()
  await page.getByRole('option', { name: 'openai/test.v1', exact: true }).click()
  const workflowResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/workflows') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '保存工作流', exact: true }).click()
  const workflowResult = await workflowResponse
  expect(workflowResult.ok(), await workflowResult.text()).toBe(true)
  const workflow = await workflowResult.json()
  expect(workflow.analyses[0]).toMatchObject({ ai: saved.id, model: 'openai/test.v1' })
  expect((await request.delete(`/api/workflows/${workflow.id}`)).ok()).toBe(true)
  expect((await request.delete(`/api/ai/${saved.id}`)).ok()).toBe(true)
  expect((await request.delete('/api/sources/model_flow_source')).ok()).toBe(true)
  expect(errors).toEqual([])
})
