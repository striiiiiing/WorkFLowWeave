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

function session(id: string, status: string = 'completed', extra: Record<string, unknown> = {}) {
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

function event(
  id: number,
  type: string,
  data: Record<string, unknown>,
  sessionId = 'qa-session',
  turnId: string | null = 'turn-done',
) {
  return {
    id,
    session_id: sessionId,
    turn_id: turnId,
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
  const sessions = new Map(
    (options.sessions ?? []).map((item) => [item.session_id, structuredClone(item)]),
  )
  const events = new Map<string, ReturnType<typeof event>[]>()
  if (options.history?.length) events.set('qa-session', structuredClone(options.history))

  function remember(item: ReturnType<typeof session>) {
    sessions.set(item.session_id, item)
    if (!events.has(item.session_id)) events.set(item.session_id, [])
    return item
  }

  function appendEvent(
    sessionId: string,
    type: string,
    data: Record<string, unknown>,
    turnId: string | null,
  ) {
    const log = events.get(sessionId) ?? []
    const item = event(
      Math.max(0, ...log.map((entry) => entry.id)) + 1,
      type,
      data,
      sessionId,
      turnId,
    )
    events.set(sessionId, [...log, item])
    return item
  }

  function acceptTurn(sessionId: string, text: string) {
    const current = remember(sessions.get(sessionId) ?? session(sessionId))
    const turnId = `turn-${sessionId}-${events.get(sessionId)?.length ?? 0}`
    current.status = 'running'
    current.turn_id = turnId
    appendEvent(sessionId, 'turn.started', {}, turnId)
    appendEvent(sessionId, 'message.user', { message_id: `message-${turnId}`, text }, turnId)
    appendEvent(
      sessionId,
      'message.completed',
      { message_id: `assistant-${turnId}`, incremental: false, text: `受控 Agent 回复：${text}` },
      turnId,
    )
    appendEvent(sessionId, 'turn.completed', { checkpoint_id: `checkpoint-${turnId}` }, turnId)
    current.status = 'completed'
    return { session_id: sessionId, turn_id: turnId, deduplicated: false }
  }

  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname.replace(/^\/api/, '')
      const method = request.method()
      const body = request.postDataJSON?.() as Record<string, unknown> | undefined
      calls.push({ method, path, body })

      if (path === '/agents/sessions' && method === 'GET')
        return json(route, [...sessions.values()])
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
      if (/^\/agents\/sessions\/[^/]+$/.test(path) && method === 'GET') {
        const id = path.split('/').at(-1)!
        return json(route, sessions.get(id) ?? remember(session(id)))
      }
      if (/^\/agents\/sessions\/[^/]+\/history$/.test(path)) {
        const id = path.split('/').at(-2)!
        return json(route, events.get(id) ?? [])
      }
      if (/\/channels\/web\/sessions\/[^/]+\/events$/.test(path)) {
        const id = decodeURIComponent(path.split('/').at(-2)!)
        const after = Number(new URL(request.url()).searchParams.get('after') ?? 0)
        const body = (events.get(id) ?? [])
          .filter((item) => item.id > after)
          .map((item) => `id: ${item.id}\ndata: ${JSON.stringify(item)}\n\n`)
          .join('')
        return route.fulfill({
          status: 200,
          headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
          body: body || ': connected\n\n',
        })
      }

      if (path === '/channels/web/commands' && method === 'POST') {
        const text = String(body?.text ?? '')
        const action = String(
          body?.action ??
            (text.startsWith('/append')
              ? 'append'
              : text.startsWith('/stop')
                ? 'stop'
                : text.startsWith('/fork')
                  ? 'fork'
                  : text.trim()
                    ? 'message'
                    : 'new'),
        )
        const requestId = String(body?.request_id ?? 'request')
        const sessionId = body?.session ? String(body.session) : undefined

        if (action === 'new' || action === 'workflow') {
          const created = remember(
            structuredClone(options.createdSession ?? session('created-session')),
          )
          created.workflow_session_id =
            action === 'workflow' ? String(body?.workflow_session_id ?? 'workflow-result') : null
          return json(route, {
            channel: 'web',
            session: sessionId ?? null,
            priority: 'command',
            kind: 'session',
            result: created,
          })
        }
        if (action === 'fork') {
          const child = remember(session('qa-child', 'completed', { branch_id: 'branch-qa' }))
          return json(route, {
            channel: 'web',
            session: sessionId ?? null,
            priority: 'command',
            kind: 'session',
            result: child,
          })
        }
        if (!sessionId) return json(route, { error: 'session is required' }, 400)
        if (action === 'message') {
          if (messageFailures > 0) {
            messageFailures -= 1
            return json(route, { error: 'temporary test failure' }, 503)
          }
          const result = acceptTurn(sessionId, text)
          return json(route, {
            channel: 'web',
            session: sessionId,
            priority: 'conversation',
            kind: 'turn',
            result,
          })
        }
        if (action === 'append') {
          const current = remember(sessions.get(sessionId) ?? session(sessionId, 'running'))
          const appendText = text.replace(/^\/append\s*/, '')
          const turnId = current.turn_id ?? `turn-${sessionId}`
          const queued = appendEvent(
            sessionId,
            'command.queued',
            { command: 'append', request_id: requestId, text: appendText },
            turnId,
          )
          return json(route, {
            channel: 'web',
            session: sessionId,
            priority: 'command',
            kind: 'turn',
            result: {
              session_id: sessionId,
              turn_id: turnId,
              deduplicated: false,
              status: 'queued',
              event_id: queued.id,
            },
          })
        }
        if (action === 'stop') {
          const current = remember(sessions.get(sessionId) ?? session(sessionId, 'running'))
          current.status = 'cancelled'
          appendEvent(sessionId, 'turn.cancelled', {}, current.turn_id)
          return json(route, {
            channel: 'web',
            session: sessionId,
            priority: 'stop',
            kind: 'session',
            result: current,
          })
        }
      }

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
    .poll(() => page.evaluate(() => localStorage.getItem('workflowweave.agent.default-model')))
    .toBe('channel-a:alpha')

  await page.reload()
  await page.getByRole('button', { name: '新会话' }).last().click()
  await expect(page).toHaveURL(/\/agents\/created-session$/)
  await expect(page.getByRole('dialog', { name: '创建 Agent 分析会话' })).toHaveCount(0)
  expect(
    calls.find((call) => call.method === 'POST' && call.path === '/channels/web/commands')?.body,
  ).toMatchObject({ action: 'new', model: 'channel-a:alpha' })
})

test('未设置默认模型时新会话保留模型选择步骤', async ({ page }) => {
  const calls = await installApi(page)
  await page.goto('/agents')
  await page.getByRole('button', { name: '新会话' }).first().click()

  const dialog = page.getByRole('dialog', { name: '创建 Agent 分析会话' })
  await expect(dialog).toBeVisible()
  const model = dialog.getByRole('combobox', { name: '新会话模型' })
  await expect(model).toBeEnabled()
  await dialog.locator('.el-select__wrapper').click()
  await page.locator('.el-select-dropdown__item:visible').first().click()
  await dialog.getByRole('button', { name: '确认创建' }).click()

  await expect(page).toHaveURL(/\/agents\/created-session$/)
  expect(
    calls.find((call) => call.method === 'POST' && call.path === '/channels/web/commands')?.body,
  ).toMatchObject({ action: 'new', model: 'channel-a:alpha' })
})

test('长会话只滚动消息区，输入器留在聊天窗口底部', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const history = Array.from({ length: 40 }, (_, index) => {
    const id = index + 1
    return index % 2 === 0
      ? event(id, 'message.user', {
          message_id: `user-${id}`,
          text: `第 ${(index + 2) / 2} 条用户消息`,
        })
      : event(id, 'message.completed', {
          message_id: `assistant-${id}`,
          incremental: false,
          text: `这是第 ${(index + 1) / 2} 段较长的分析内容。`.repeat(8),
        })
  })
  history.push(
    event(41, 'turn.resources', { model: 'channel-a:alpha', tools_generation: 1 }),
    event(42, 'turn.completed', { checkpoint_id: 'checkpoint-long' }),
  )
  await installApi(page, { sessions: [session('qa-session')], history })
  await page.goto('/agents/qa-session')

  const transcript = page.getByRole('region', { name: 'Agent 对话历史' })
  const composer = page.getByRole('form', { name: 'Agent 输入' })
  await expect(page.getByText('第 20 条用户消息', { exact: true })).toBeVisible()
  await expect(transcript).toContainText('本轮分析已完成')
  await expect(page.getByText('turn.resources', { exact: true })).toHaveCount(0)

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 375, height: 812 },
  ]) {
    await page.setViewportSize(viewport)
    const layout = await page.evaluate(() => {
      const transcript = document.querySelector('.transcript-viewport')!
      const main = document.querySelector('.agent-main')!
      const composer = document.querySelector('.composer-container')!
      const rect = (element: Element) => {
        const { top, bottom } = element.getBoundingClientRect()
        return { top, bottom }
      }
      return {
        documentHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
        transcriptHeight: transcript.scrollHeight,
        transcriptViewportHeight: transcript.clientHeight,
        main: rect(main),
        composer: rect(composer),
      }
    })
    expect(layout.documentHeight).toBeLessThanOrEqual(layout.viewportHeight)
    expect(layout.transcriptHeight).toBeGreaterThan(layout.transcriptViewportHeight)
    expect(layout.composer.top).toBeGreaterThanOrEqual(layout.main.top)
    expect(layout.composer.bottom).toBeLessThanOrEqual(layout.main.bottom + 1)
    expect(layout.composer.bottom).toBeLessThanOrEqual(layout.viewportHeight + 1)

    await transcript.evaluate((element) => {
      element.scrollTop = 0
    })
    const composerAfterScroll = await composer.boundingBox()
    expect(composerAfterScroll?.y).toBeCloseTo(layout.composer.top, 0)
    expect(await page.evaluate(() => window.scrollY)).toBe(0)
  }
})

test('Workflow 续接自动选择默认模型并提交固定来源', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('workflowweave.agent.default-model', 'channel-a:alpha')
  })
  const calls = await installApi(page, { sessions: [session('qa-session')] })
  await page.goto('/agents/qa-session')
  await page.getByRole('button', { name: 'Workflow 历史' }).click()
  await expect(page.getByText('qa-workflow / workflow-result')).toBeVisible()
  await page.getByRole('button', { name: '继续讨论' }).click()
  await expect(page.getByRole('dialog', { name: '从 Workflow 结果创建 Agent 会话' })).toHaveCount(0)
  await expect
    .poll(
      () =>
        calls.find((call) => call.method === 'POST' && call.path === '/channels/web/commands')
          ?.body,
    )
    .toMatchObject({
      action: 'workflow',
      workflow_session_id: 'workflow-result',
      model: 'channel-a:alpha',
    })
})

test('运行中发送补充走追加命令，停止按钮另发取消请求', async ({ page }) => {
  const calls = await installApi(page, { sessions: [session('qa-session', 'running')] })
  await page.goto('/agents/qa-session')
  const composer = page.getByRole('textbox', { name: 'Agent 消息' })
  await expect(composer).toBeEnabled()
  await composer.fill('继续检查失败原因')
  await page.getByRole('button', { name: '追加到队列' }).click()
  await expect
    .poll(() => calls.find((call) => call.path === '/channels/web/commands')?.body)
    .toMatchObject({ session: 'qa-session', text: '/append 继续检查失败原因' })

  await page.locator('.capsule-stop-btn').click()
  await expect
    .poll(() =>
      calls.some(
        (call) =>
          call.method === 'POST' &&
          call.path === '/channels/web/commands' &&
          call.body?.action === 'stop',
      ),
    )
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
  const forks = calls.filter(
    (call) => call.path === '/channels/web/commands' && call.body?.action === 'fork',
  )
  const messages = calls.filter(
    (call) => call.path === '/channels/web/commands' && call.body?.action === 'message',
  )
  expect(forks).toHaveLength(1)
  expect(forks[0].body).toMatchObject({ action: 'fork', message_id: 'message-qa' })
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
