import { expect, test, type Page, type Route } from '@playwright/test'

const models = [
  {
    reference: 'channel-b:zeta',
    provider: 'openai_compatible_api',
    ai: 'channel-b',
    model: 'zeta',
  },
  {
    reference: 'channel-a:zeta',
    provider: 'openai_compatible_api',
    ai: 'channel-a',
    model: 'zeta',
  },
  {
    reference: 'channel-a:alpha',
    provider: 'openai_compatible_api',
    ai: 'channel-a',
    model: 'alpha',
  },
]

const config = {
  context_window: 200_000,
  output_tokens: 4096,
  trigger_tokens: 180_000,
  keep_tokens: 40_000,
  summary_ai: null,
  summary_context_window: null,
  summary_max_tokens: 4096,
  summary_prompt: 'summary',
  timezone: 'Asia/Shanghai',
  idle_timeout: 300,
  read_concurrency: 4,
  sandbox: { enabled: false, network: false },
}

function session(
  id: string,
  status: 'completed' | 'running' = 'completed',
  extra: Record<string, unknown> = {},
) {
  return {
    session_id: id,
    branch_id: 'main',
    model: 'channel-a:alpha',
    workflow_session_id: null,
    created_at: '2026-09-23T00:00:00Z',
    updated_at: '2026-09-23T00:00:00Z',
    status,
    turn_id: status === 'running' ? 'turn-running' : 'turn-done',
    context_budget: null,
    continuable: true,
    history_path: `Runtime/History/${id}/events.jsonl`,
    last_checkpoint_at: '2026-09-23T00:00:00Z',
    ...extra,
  }
}

function event(id: number, type: string, data: Record<string, unknown>) {
  return {
    id,
    session_id: 'qa-session',
    turn_id: 'turn-done',
    type,
    at: '2026-09-23T00:00:00Z',
    data,
  }
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installApi(
  page: Page,
  options: {
    sessions?: ReturnType<typeof session>[]
    history?: ReturnType<typeof event>[]
    createdSession?: ReturnType<typeof session>
    failFirstMessage?: boolean
  } = {},
) {
  const calls: Array<{ method: string; path: string; body?: Record<string, unknown> }> = []
  let messageFailures = options.failFirstMessage ? 1 : 0

  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname.replace(/^\/api/, '')
      const method = request.method()
      const body = request.postDataJSON?.() as Record<string, unknown> | undefined
      calls.push({ method, path, body })

      if (path === '/agents/sessions' && method === 'GET')
        return json(route, options.sessions ?? [])
      if (path === '/agents/config' && method === 'GET')
        return json(route, {
          config,
          models,
          tools: [],
          scheduler: {},
          sandbox: { enabled: false, network: false, available: true, status: 'ready' },
          readonly_paths: [],
        })
      if (path === '/agents/models') return json(route, models)
      if (path === '/agents/config' && method === 'PUT') return json(route, config)
      if (path === '/agents/sessions' && method === 'POST')
        return json(route, options.createdSession ?? session('created-session'))
      if (/^\/agents\/sessions\/[^/]+$/.test(path) && method === 'GET') {
        const id = path.split('/').at(-1)!
        return json(route, options.sessions?.find((item) => item.session_id === id) ?? session(id))
      }
      if (/^\/agents\/sessions\/[^/]+\/history$/.test(path))
        return json(route, options.history ?? [])
      if (/\/agents\/sessions\/[^/]+\/events$/.test(path)) {
        return route.fulfill({
          status: 200,
          headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
          body: ': connected\n\n',
        })
      }
      if (/\/agents\/sessions\/[^/]+\/fork$/.test(path))
        return json(route, session('qa-child', 'completed', { branch_id: 'branch-qa' }))
      if (/\/agents\/sessions\/[^/]+\/messages$/.test(path)) {
        if (messageFailures > 0) {
          messageFailures -= 1
          return json(route, { error: 'temporary test failure' }, 503)
        }
        return json(route, {
          session_id: 'qa-child',
          turn_id: 'turn-child',
          deduplicated: false,
        })
      }
      if (path === '/agents/commands')
        return json(route, {
          kind: 'turn',
          priority: 'command',
          result: {
            session_id: 'qa-session',
            turn_id: 'turn-running',
            deduplicated: false,
            status: 'queued',
          },
        })
      if (/\/agents\/sessions\/[^/]+\/append$/.test(path))
        return json(route, {
          session_id: 'qa-session',
          turn_id: 'turn-running',
          deduplicated: false,
        })
      if (/\/agents\/sessions\/[^/]+\/cancel$/.test(path))
        return json(route, session('qa-session', 'completed'))
      if (path === '/sessions') {
        return json(route, [
          {
            session_id: 'workflow-result',
            workflow_id: 'qa-workflow',
            workflow_name: 'QA Workflow',
            version: 1,
            status: 'completed',
            stage: 'finish',
            created_at: '2026-09-23T00:00:00Z',
            updated_at: '2026-09-23T00:00:00Z',
            finished_at: '2026-09-23T00:00:00Z',
            error: null,
            artifacts: [],
            snapshot_availability: 'available',
          },
        ])
      }
      if (path === '/sessions/workflow-result') {
        return json(route, {
          session_id: 'workflow-result',
          workflow_id: 'qa-workflow',
          status: 'completed',
          finished_at: '2026-09-23T00:00:00Z',
          updated_at: '2026-09-23T00:00:00Z',
        })
      }
      return json(route, { error: `Unhandled test API: ${method} ${path}` }, 501)
    },
  )

  return calls
}

test('正式 Agent 入口不含 demo；默认模型持久化并用于新会话，渠道模型有序', async ({ page }) => {
  const calls = await installApi(page, {
    createdSession: session('created-session'),
  })
  await page.goto('/agents')

  await expect(page.getByRole('heading', { name: '开启 Agent 智能会话' })).toBeVisible()
  await expect(page.getByRole('link', { name: /agent-demo/i })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Agent 会话' })).toHaveAttribute('href', '/agents')

  await page.getByRole('button', { name: '全局设置' }).first().click()
  await page.getByRole('dialog', { name: 'Agent 全局设置与运行环境' }).waitFor()
  const defaultModel = page.getByRole('combobox', { name: '默认模型' })
  await page.locator('.el-select').filter({ has: defaultModel }).click()
  const options = page.locator('.el-select-dropdown__item:visible')
  await expect(options).toHaveText([
    'channel-a / alpha · openai_compatible_api',
    'channel-a / zeta · openai_compatible_api',
    'channel-b / zeta · openai_compatible_api',
  ])
  await options.nth(0).click()
  await page.getByRole('button', { name: '保存全局设置' }).click()
  await expect(page.getByRole('dialog', { name: 'Agent 全局设置与运行环境' })).toBeHidden()
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('logagent.agent.default-model')))
    .toBe('channel-a:alpha')

  await page.reload()
  await page.getByRole('button', { name: '新建会话' }).click()
  await expect(page.getByRole('dialog').locator('.el-select__placeholder')).toContainText(
    'channel-a / alpha',
  )
  await page.getByRole('button', { name: '确认创建' }).click()
  await expect(page).toHaveURL(/\/agents\/created-session$/)
  expect(
    calls.find((call) => call.method === 'POST' && call.path === '/agents/sessions')?.body,
  ).toEqual({ model: 'channel-a:alpha' })
})

test('Workflow 续接自动选择默认模型并提交固定来源', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('logagent.agent.default-model', 'channel-a:alpha')
  })
  const calls = await installApi(page, { sessions: [session('qa-session')] })
  await page.goto('/agents/qa-session')
  await page.getByRole('button', { name: 'Workflow 历史' }).click()
  await expect(page.getByText('qa-workflow / workflow-result')).toBeVisible()
  await page.getByRole('button', { name: '继续讨论' }).click()
  await expect(
    page
      .getByRole('dialog', { name: '从 Workflow 结果创建 Agent 会话' })
      .locator('.el-select__placeholder'),
  ).toContainText('channel-a / alpha')
  await page.getByRole('button', { name: '创建并继续' }).click()
  await expect
    .poll(
      () => calls.find((call) => call.method === 'POST' && call.path === '/agents/sessions')?.body,
    )
    .toEqual({ workflow_session_id: 'workflow-result', model: 'channel-a:alpha' })
})

test('运行中发送补充走追加命令，停止按钮另发取消请求', async ({ page }) => {
  const calls = await installApi(page, { sessions: [session('qa-session', 'running')] })
  await page.goto('/agents/qa-session')
  const composer = page.getByRole('textbox', { name: 'Agent 消息' })
  await expect(composer).toBeEnabled()
  await composer.fill('继续检查失败原因')
  await page.getByRole('button', { name: '追加到队列' }).click()
  await expect
    .poll(() => calls.find((call) => call.path === '/agents/commands')?.body)
    .toMatchObject({ session: 'qa-session', text: '/append 继续检查失败原因' })

  await page.locator('.capsule-stop-btn').click()
  await expect
    .poll(() => calls.some((call) => call.method === 'POST' && call.path.endsWith('/cancel')))
    .toBe(true)
})

test('编辑分支首次发送失败后保留分支与请求编号供重试', async ({ page }) => {
  const calls = await installApi(page, {
    sessions: [session('qa-session')],
    history: [
      event(1, 'message.user', { message_id: 'message-qa', text: '原始 QA 指令' }),
      event(2, 'turn.completed', { checkpoint_id: 'checkpoint-qa' }),
    ],
    failFirstMessage: true,
  })
  await page.goto('/agents/qa-session')
  await page.getByRole('button', { name: '编辑并创建分支' }).click()
  await page.getByRole('textbox', { name: '分支消息' }).fill('修订后的 QA 指令')
  await page.getByRole('button', { name: '确认创建分支并发送' }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('HTTP 503')
  await expect(page.getByText(/分支 branch-qa 已创建/)).toBeVisible()

  await page.getByRole('button', { name: '确认创建分支并发送' }).click()
  await expect(page).toHaveURL(/\/agents\/qa-child$/)
  const forks = calls.filter((call) => call.path.endsWith('/fork'))
  const messages = calls.filter((call) => call.path.endsWith('/messages'))
  expect(forks).toHaveLength(1)
  expect(forks[0].body).toEqual({ message_id: 'message-qa' })
  expect(messages).toHaveLength(2)
  expect(messages[0].body).toEqual(messages[1].body)
})

test('窄屏仍能打开全局设置', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await installApi(page)
  await page.goto('/agents')
  await expect(page.getByRole('button', { name: '全局设置' }).first()).toBeVisible()
  await page.getByRole('button', { name: '全局设置' }).first().click()
  await expect(page.getByRole('dialog', { name: 'Agent 全局设置与运行环境' })).toBeVisible()
})
