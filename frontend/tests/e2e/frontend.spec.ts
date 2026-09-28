/**
 * 前端完整流程浏览器测试：通过页面操作与真实 API 验证资源 JSON 校验、创建编辑，以及 Workflow 保存、触发和版本化正文查询。使用 Playwright 配置启动的临时后端与本地预览服务；同时检查浏览器运行错误。
 */
import { test, expect } from '@playwright/test'

test('run history displays frozen workflow names and searches selected fields', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  for (const [kind, data] of Object.entries({
    sources: {
      id: 'search_source',
      collector: 'mock',
      options: { mode: 'empty' },
      on_empty: 'skip',
    },
    ai: {
      id: 'search_ai',
      provider: 'openai_compatible_api',
      base_url: 'http://127.0.0.1:1/v1',
      models: { offline: {} },
      retries: 0,
    },
  })) {
    const response = await request.post(`/api/${kind}`, { data })
    expect(response.ok(), await response.text()).toBe(true)
  }
  const sessions: Record<string, string> = {}
  for (const [id, name, on_all_empty] of [
    ['search_daily', '运行记录 Daily 日报', 'stop'],
    ['search_weekly', '运行记录 Weekly 周报', 'skip'],
  ]) {
    const created = await request.post('/api/workflows', {
      data: {
        id,
        name,
        sources: ['search_source'],
        analyses: [{ id: 'analysis', ai: 'search_ai', model: 'offline' }],
        on_all_empty,
        backup: { enabled: false },
      },
    })
    expect(created.ok(), await created.text()).toBe(true)
    const triggered = await request.post(`/api/workflows/${id}/run`)
    expect(triggered.ok(), await triggered.text()).toBe(true)
    sessions[id] = (await triggered.json()).session_id
    await expect
      .poll(async () => (await (await request.get(`/api/sessions/${sessions[id]}`)).json()).status)
      .toBe(on_all_empty === 'stop' ? 'failed' : 'completed')
  }
  const daily = await (await request.get('/api/workflows/search_daily')).json()
  expect(
    (
      await request.put('/api/workflows/search_daily', { data: { ...daily, name: '修改后的名称' } })
    ).ok(),
  ).toBe(true)
  expect((await request.delete('/api/workflows/search_daily')).ok()).toBe(true)

  await page.goto('/runs')
  await expect(page.getByRole('columnheader', { name: '工作流名称', exact: true })).toBeVisible()
  const dailyRow = page.getByRole('row').filter({ hasText: sessions.search_daily })
  const weeklyRow = page.getByRole('row').filter({ hasText: sessions.search_weekly })
  await expect(dailyRow).toContainText('运行记录 Daily 日报')
  await expect(weeklyRow).toContainText('运行记录 Weekly 周报')
  await expect(dailyRow.getByText('失败', { exact: true })).toBeVisible()
  await expect(weeklyRow.getByText('已完成', { exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '工作流名称', exact: true }).fill('daily')
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await expect(weeklyRow).toHaveCount(0)
  await expect(dailyRow).toBeVisible()

  for (const [field, value] of [
    ['工作流 ID', 'search_weekly'],
    ['Session ID', sessions.search_daily],
  ]) {
    await page
      .locator('.el-select')
      .filter({ has: page.getByRole('combobox', { name: '筛选字段', exact: true }) })
      .click()
    await page.getByRole('option', { name: field, exact: true }).click()
    const input = page.getByRole('textbox', { name: field, exact: true })
    await expect(input).toHaveValue('')
    await input.fill(value)
    await page.getByRole('button', { name: '筛选', exact: true }).click()
    await expect(page.getByRole('row').filter({ hasText: sessions.search_weekly })).toHaveCount(
      field === '工作流 ID' ? 1 : 0,
    )
    await expect(page.getByRole('row').filter({ hasText: sessions.search_daily })).toHaveCount(
      field === 'Session ID' ? 1 : 0,
    )
  }
  await page
    .locator('.el-select')
    .filter({ has: page.getByRole('combobox', { name: '筛选字段', exact: true }) })
    .click()
  await page.getByRole('option', { name: '运行状态', exact: true }).click()
  await page
    .locator('.el-select')
    .filter({ has: page.getByRole('combobox', { name: '运行状态', exact: true }) })
    .click()
  await page.getByRole('option', { name: '失败', exact: true }).click()
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await expect(dailyRow).toBeVisible()
  await expect(weeklyRow).toHaveCount(0)
  await page.getByRole('button', { name: '重置', exact: true }).click()
  await expect(weeklyRow).toBeVisible()
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(
    false,
  )
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.screenshot({
    path: 'test-results/run-history-fields.png',
    fullPage: true,
    animations: 'disabled',
  })
  await dailyRow.getByRole('button', { name: sessions.search_daily }).click()
  await expect(
    page.getByRole('heading', { name: '运行记录 Daily 日报', exact: true }),
  ).toBeVisible()
  expect((await request.delete('/api/workflows/search_weekly')).ok()).toBe(true)
  expect((await request.delete('/api/sources/search_source')).ok()).toBe(true)
  expect((await request.delete('/api/ai/search_ai')).ok()).toBe(true)
  expect(errors).toEqual([])
})

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
  await page.locator('summary').filter({ hasText: '高级配置' }).click()
  await page.getByLabel('资源编号', { exact: true }).fill('browser_source')
  await page.getByLabel('采集器', { exact: true }).click()
  await page.getByRole('option', { name: 'mock', exact: true }).click()
  await page
    .getByRole('region', { name: '数据源共用配置 (options)', exact: true })
    .getByRole('button', { name: '编辑 JSON', exact: true })
    .click()
  const setters = page.getByRole('region', { name: '处理规则 (setters)', exact: true })
  await setters.getByRole('switch', { name: '设置 sort_by', exact: true }).locator('..').click()
  await setters.getByRole('textbox', { name: 'sort_by', exact: true }).fill('message')
  await setters.getByRole('switch', { name: '设置 descending', exact: true }).locator('..').click()
  await setters.getByRole('switch', { name: 'descending', exact: true }).locator('..').click()
  const options = page.getByRole('textbox', { name: '数据源共用配置 (options)', exact: true })
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
  await page.locator('summary').filter({ hasText: '高级配置' }).click()
  await expect(page.getByLabel('资源编号', { exact: true })).toHaveValue('browser_source')
  await expect(page.getByLabel('资源编号', { exact: true })).toBeDisabled()
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
  await page.getByLabel('工作流 ID', { exact: true }).fill('browser_workflow')
  await page.getByLabel('显示名称', { exact: true }).fill('浏览器验证工作流')
  await expect(
    page.locator('.el-form-item').filter({ hasText: '运行计划' }).locator('.el-select'),
  ).toContainText('每天')
  await expect(page.getByLabel('运行时间（运行机器本地时区）')).toHaveValue('09:00')
  await expect(page.getByLabel('Cron 表达式（分 时 日 月 周）')).toHaveCount(0)
  await expect(page.getByText('运行机器本地时区（不指定）')).toBeVisible()
  await expect(page.getByText('计划时区（IANA）')).toHaveCount(0)
  await expect(page.getByText('实际采用时区：', { exact: false })).toBeVisible()
  await expect(page.getByText('下一次运行：', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '加载已有数据源', exact: true }).click()
  await page.getByText('选择数据源', { exact: true }).click()
  await page.getByRole('option', { name: 'offline_source', exact: true }).click()
  await page.getByRole('option', { name: 'second_source', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('heading', { name: '加载已有数据源', exact: true })
    .click()
  await page.getByRole('button', { name: '加入当前工作流', exact: true }).click()
  await page
    .getByRole('article', { name: '数据源 second_source' })
    .getByRole('button', { name: '上移', exact: true })
    .click()
  await page.getByRole('button', { name: '添加任务' }).click()
  await page.getByRole('combobox', { name: '模型', exact: true }).click()
  await page.getByRole('option', { name: 'offline_ai / offline_model', exact: true }).click()
  await page.screenshot({ path: 'test-results/workflow-editor.png', fullPage: true })
  await page.getByRole('button', { name: '保存工作流' }).click()
  await expect(page).toHaveURL(/\/workflows$/)
  const saved = await (await request.get('/api/workflows/browser_workflow')).json()
  expect(saved.sources).toEqual(['second_source', 'offline_source'])
  expect(saved.analyses).toEqual([
    {
      id: 'task_1',
      ai: 'offline_ai',
      model: 'offline_model',
      system_prompt: null,
      input_prompt: null,
      user_prompt: '',
    },
  ])
  expect(saved.backup.enabled).toBe(true)
  expect(saved.include_counts).toBe(true)
  expect(saved.schedule).toEqual({
    type: 'cron',
    expression: '0 9 * * *',
    timezone: null,
  })
  expect(saved.interval_seconds).toBeUndefined()
  expect(saved.cron).toBeUndefined()
  expect(saved.cron_timezone).toBeUndefined()
  expect(saved.description).toBeUndefined()
  // The built-in offline collector exits before AI, so this smoke test never calls a model service.
  saved.source_overrides = {
    offline_source: { source: null, options: { mode: 'empty' }, setters: {}, template: null },
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
  await expect(page.getByRole('heading', { name: '最终报告', exact: true })).toBeVisible()
  await expect(page.getByText('通知状态', { exact: true })).toBeVisible()
  await page.locator('summary').filter({ hasText: '数据采集与共享输入' }).click()
  await expect(page.getByText('没有采集到内容', { exact: false }).first()).toBeVisible()
  await expect(page.getByText('原始 JSON', { exact: false })).toHaveCount(0)
  await page.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
  await page.getByText('原始 JSON', { exact: false }).first().click()
  await expect(page.locator('pre').first()).toContainText('collection')
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
  await expect(page.getByLabel('资源编号')).toBeVisible()
  await expect(page.getByRole('button', { name: '测试连接', exact: true })).toHaveCount(0)
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
  await page.locator('summary').filter({ hasText: '高级配置' }).click()
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
  await models.getByRole('textbox', { name: '模型名称', exact: true }).click()
  expect((await healthResponse).ok()).toBe(false)
  await expect(
    page.getByRole('region', { name: '渠道模型发现' }).locator('.el-alert--error'),
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
  await page.getByRole('button', { name: '加载已有数据源', exact: true }).click()
  await page.getByText('选择数据源', { exact: true }).click()
  await page.getByRole('option', { name: 'model_flow_source', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('heading', { name: '加载已有数据源', exact: true })
    .click()
  await page.getByRole('button', { name: '加入当前工作流', exact: true }).click()
  await page.getByRole('button', { name: '添加任务', exact: true }).click()
  await expect(page.getByRole('button', { name: '刷新模型列表', exact: true })).toHaveCount(0)
  const providerPage = await page.context().newPage()
  await providerPage.goto('/resources?kind=ai')
  await providerPage.bringToFront()
  await providerPage
    .locator('.el-card .el-card')
    .filter({ has: providerPage.getByRole('heading', { name: saved.id }) })
    .getByRole('button', { name: '编辑', exact: true })
    .click()
  const providerModels = providerPage.getByRole('region', { name: '渠道模型', exact: true })
  await providerModels.getByRole('textbox', { name: '模型名称', exact: true }).fill('openai/new.v3')
  await providerModels.getByRole('button', { name: '添加模型', exact: true }).click()
  const addedModelResponse = providerPage.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/ai/${saved.id}`) && response.request().method() === 'PUT',
  )
  await providerPage.getByRole('button', { name: '保存渠道', exact: true }).click()
  expect((await addedModelResponse).ok()).toBe(true)
  const modelsResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/ai') && response.request().method() === 'GET',
  )
  await page.bringToFront()
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  expect((await modelsResponse).ok()).toBe(true)
  await providerPage.close()
  await expect(page.getByLabel('显示名称', { exact: true })).toHaveValue('模型配置流程')
  await expect(page.getByRole('heading', { name: '分析任务 1', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '模型', exact: true }).click()
  await page.getByRole('option', { name: `${saved.id} / openai/new.v3`, exact: true }).click()
  const workflowResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/workflows') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '保存工作流', exact: true }).click()
  const workflowResult = await workflowResponse
  expect(workflowResult.ok(), await workflowResult.text()).toBe(true)
  const workflow = await workflowResult.json()
  expect(workflow.analyses[0]).toMatchObject({ ai: saved.id, model: 'openai/new.v3' })
  expect(workflow.sources).toEqual(['model_flow_source'])
  expect((await request.delete(`/api/workflows/${workflow.id}`)).ok()).toBe(true)
  expect((await request.delete(`/api/ai/${saved.id}`)).ok()).toBe(true)
  expect((await request.delete('/api/sources/model_flow_source')).ok()).toBe(true)
  expect(errors).toEqual([])
})

test('readable report, plugin sections, advanced data and mobile layout', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const record = {
    session_id: 'report_preview',
    workflow_id: 'daily',
    workflow_name: '每日巡检报告',
    version: 12,
    status: 'partial',
    stage: 'finish',
    created_at: '2026-09-21T01:00:00Z',
    updated_at: '2026-09-21T01:02:00Z',
    finished_at: '2026-09-21T01:02:00Z',
    error: null,
    execution_epoch: null,
    progress: [],
    artifacts: ['collect', 'analyze', 'aggregate', 'notify', 'finish'].map((stage) => ({
      stage,
      content_version: 12,
      availability: 'available',
      size_bytes: null,
      error: null,
    })),
    snapshot_availability: 'available',
  }
  const content: Record<string, object> = {
    aggregate: {
      outputs: {
        final:
          '# 巡检结论\n\n服务运行正常，发现 **2 项需要关注的问题**。\n\n- 磁盘使用率达到 82%，建议清理过期日志。\n- 有 3 次网络请求超时，请检查网络连接。\n\n## 后续处理\n\n优先清理磁盘，再观察网络情况。',
      },
      errors: [],
    },
    collect: {
      collection: [
        {
          source_id: '系统日志',
          status: 'success',
          text: '本次采集记录',
          count: 128,
          report: {
            sections: [
              {
                kind: 'metrics',
                title: '采集概况',
                items: [
                  { label: '记录数量', value: 128, unit: '条' },
                  { label: '告警数量', value: 2, unit: '项' },
                ],
              },
              {
                kind: 'table',
                title: '告警明细',
                columns: ['类别', '情况'],
                rows: [
                  ['磁盘', '使用率 82%'],
                  ['网络', '3 次请求超时'],
                ],
              },
            ],
          },
        },
      ],
    },
    analyze: {
      analyses: [
        { task_id: '运行分析', status: 'success', text: '已核对日志，建议优先处理磁盘空间。' },
      ],
    },
    notify: {
      deliveries: [
        { channel_id: '工作邮箱', output_id: 'final', status: 'success' },
        {
          channel_id: '备用邮箱',
          output_id: 'final',
          status: 'failed',
          error: { code: 'delivery_uncertain', message: '没有获得可靠回执，请先核对收件箱。' },
        },
      ],
    },
    finish: { status: 'partial' },
  }
  await page.route('**/api/sessions/report_preview**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/events')) {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `event: snapshot\ndata: ${JSON.stringify(record)}\n\n`,
      })
      return
    }
    const stage = url.pathname.split('/phases/')[1]
    if (stage) {
      expect(url.searchParams.get('version')).toBe('12')
      await route.fulfill({
        json: {
          session_id: record.session_id,
          version: 12,
          stage,
          availability: 'available',
          error: null,
          size_bytes: null,
          content: content[stage],
        },
      })
    } else if (url.pathname.endsWith('/recovery')) {
      await route.fulfill({ json: { available: true, reason: null } })
    } else await route.fulfill({ json: record })
  })
  await page.goto('/runs/report_preview')
  await expect(page.getByRole('heading', { name: '巡检结论', exact: true })).toBeVisible()
  await page.locator('summary').filter({ hasText: '通知状态' }).click()
  await expect(page.getByText('投递结果不确定', { exact: true })).toBeVisible()
  await expect(page.getByText('已送达', { exact: true })).toBeVisible()
  await page.locator('summary').filter({ hasText: '通知状态' }).click()
  await expect(page.getByText('原始 JSON', { exact: false })).toHaveCount(0)
  async function checkProcessTargets() {
    for (const label of ['数据采集与共享输入', '并行 AI 分析', '通知状态', '执行完成']) {
      const summary = page.locator('summary').filter({ hasText: label })
      const details = summary.locator('..')
      await summary.scrollIntoViewIfNeeded()
      const box = (await summary.boundingBox())!
      expect(box.height).toBeGreaterThanOrEqual(44)
      // The padded right edge must toggle too, away from the label and marker.
      await summary.click({ position: { x: box.width - 4, y: box.height - 4 } })
      await expect(details).toHaveAttribute('open', '')
      await summary.focus()
      await page.keyboard.press('Enter')
      await expect(details).not.toHaveAttribute('open', '')
      await page.keyboard.press('Space')
      await expect(details).toHaveAttribute('open', '')
      await summary.click({ position: { x: box.width - 4, y: 4 } })
      await expect(details).not.toHaveAttribute('open', '')
    }
  }
  await checkProcessTargets()
  await page.locator('summary').filter({ hasText: '数据采集与共享输入' }).click()
  await expect(page.getByRole('table', { name: '告警明细' })).toBeVisible()
  await page.screenshot({
    path: 'test-results/readable-report-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.locator('summary').filter({ hasText: '数据采集与共享输入' }).click()
  await page.setViewportSize({ width: 375, height: 812 })
  await checkProcessTargets()
  await page.locator('summary').filter({ hasText: '数据采集与共享输入' }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(
    false,
  )
  await page.screenshot({
    path: 'test-results/readable-report-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
  await page.getByText('原始 JSON', { exact: false }).first().click()
  await expect(page.locator('pre').first()).toContainText('outputs')
  expect(errors).toEqual([])
})

test('workflow designer persists independent sources and the resource center only updates shared bindings', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const sourceId = 'designer_source'
  const aiId = 'designer_ai'
  const workflowIds = ['designer_first', 'designer_second']
  try {
    for (const [kind, data] of Object.entries({
      sources: {
        id: sourceId,
        display_name: '共享巡检数据',
        description: '用于设计器验收',
        collector: 'mock',
        timeout: 60,
      },
      ai: {
        id: aiId,
        provider: 'openai_compatible_api',
        base_url: 'http://127.0.0.1:1/v1',
        models: { offline: {} },
        retries: 0,
      },
    })) {
      const response = await request.post(`/api/${kind}`, { data })
      expect(response.ok(), await response.text()).toBe(true)
    }
    for (const id of workflowIds) {
      const response = await request.post('/api/workflows', {
        data: {
          id,
          name: id === workflowIds[0] ? '独立巡检工作流' : '共享巡检工作流',
          sources: [sourceId],
          analyses: [
            {
              id: 'analysis',
              ai: aiId,
              model: 'offline',
              system_prompt: null,
              input_prompt: null,
              user_prompt: '',
            },
          ],
        },
      })
      expect(response.ok(), await response.text()).toBe(true)
    }
    await page.goto(`/workflows/${workflowIds[0]}/edit`)
    await expect(page.getByRole('link', { name: '数据源配置演示', exact: true })).toHaveCount(0)
    await expect(page.getByRole('complementary', { name: '工作流列表' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: '＋ 新建工作流', exact: true })).toHaveCount(0)
    const card = page.getByRole('article', { name: `数据源 ${sourceId}` })
    await expect(card).toContainText('全局同步 (2)')
    await expect(card.getByRole('button', { name: '编辑配置', exact: true })).toBeDisabled()
    await card.getByRole('button', { name: '脱离共用配置', exact: true }).click()
    await expect(card).toContainText('独立配置')
    await card.getByRole('button', { name: '编辑配置', exact: true }).click()
    const drawer = page.getByRole('dialog', { name: '编辑独立配置' })
    await drawer.getByLabel('数据源名称', { exact: true }).fill('本流专用巡检数据')
    await drawer.locator('summary').filter({ hasText: '高级配置' }).click()
    await drawer.getByRole('spinbutton', { name: '超时 / 秒' }).fill('25')
    await drawer.getByRole('button', { name: '应用到当前工作流', exact: true }).click()
    await expect(drawer).toBeHidden()
    await expect(card).toContainText('本流专用巡检数据')
    await page.getByLabel('提示词', { exact: true }).fill('保留这个未保存草稿 {input}')
    await expect(card).toBeVisible()
    await expect(page.getByLabel('提示词', { exact: true })).toHaveValue(
      '保留这个未保存草稿 {input}',
    )
    await page.getByRole('button', { name: '保存工作流', exact: true }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    const saved = await (await request.get(`/api/workflows/${workflowIds[0]}`)).json()
    expect(saved.source_overrides[sourceId].source).toMatchObject({
      display_name: '本流专用巡检数据',
      timeout: 25,
      template: null,
    })
    expect(saved.analyses[0].user_prompt).toBe('保留这个未保存草稿 {input}')

    await page.goto('/resources?kind=sources')
    await expect(page.getByRole('tab', { name: '处理模板', exact: true })).toHaveCount(0)
    const centralCard = page
      .locator('.el-card .el-card')
      .filter({ has: page.getByRole('heading', { name: '共享巡检数据', exact: true }) })
    await expect(centralCard).toContainText('同步到 1 个工作流')
    await centralCard.getByRole('button', { name: '编辑', exact: true }).click()
    const sharedDrawer = page.getByRole('dialog', { name: '编辑共用数据源' })
    await sharedDrawer.getByLabel('数据源名称', { exact: true }).fill('共用配置已更新')
    await sharedDrawer.locator('summary').filter({ hasText: '高级配置' }).click()
    await sharedDrawer.getByRole('spinbutton', { name: '超时 / 秒' }).fill('90')
    await sharedDrawer.getByRole('button', { name: '保存资源', exact: true }).click()
    await expect(sharedDrawer).toBeHidden()
    const shared = await request.post(`/api/sources/${sourceId}/resolve`, { data: {} })
    expect(shared.ok(), await shared.text()).toBe(true)
    expect(await shared.json()).toMatchObject({ display_name: '共用配置已更新', timeout: 90 })
    await page.goto(`/workflows/${workflowIds[0]}/edit`)
    await expect(card).toContainText('本流专用巡检数据')
    await expect(card).toContainText('25 秒')
    await page.setViewportSize({ width: 390, height: 844 })
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.screenshot({ path: 'test-results/workflow-designer-production.png', fullPage: true })
    await card.getByRole('button', { name: '恢复共用配置', exact: true }).click()
    await page.getByRole('button', { name: '确定', exact: true }).click()
    await expect(card).toContainText('共用配置已更新')
    await expect(card).toContainText('90 秒')
    await page.getByRole('button', { name: '保存工作流', exact: true }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    expect(
      (await (await request.get(`/api/workflows/${workflowIds[0]}`)).json()).source_overrides,
    ).toEqual({})
    expect(errors).toEqual([])
  } finally {
    for (const id of workflowIds) await request.delete(`/api/workflows/${id}`)
    await request.delete(`/api/sources/${sourceId}`)
    await request.delete(`/api/ai/${aiId}`)
  }
})
