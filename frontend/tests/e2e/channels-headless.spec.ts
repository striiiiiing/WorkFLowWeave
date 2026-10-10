import { expect, test, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { once } from 'node:events'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

type HttpEntry = {
  method: string
  path: string
  status?: number
  failed?: string
}

type Traffic = {
  http: HttpEntry[]
  console: { type: string; text: string }[]
  pageErrors: string[]
}

const trafficByPage = new WeakMap<Page, Traffic>()
const artifactRoot = join(process.cwd(), 'test-results', 'headless-channels-evidence')
const testSecretReference = { kind: 'env', name: 'QA_NO_SEND_SECRET' }

function contentText(content: unknown) {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .map((part) => (part && typeof part === 'object' && 'text' in part ? part.text : ''))
    .filter((part): part is string => typeof part === 'string')
    .join('')
}

function waitForRequestClose(request: IncomingMessage, response: ServerResponse) {
  return new Promise<void>((resolve) => {
    const finish = () => {
      clearTimeout(timer)
      request.off('aborted', finish)
      response.off('close', finish)
      resolve()
    }
    const timer = setTimeout(finish, 120_000)
    request.once('aborted', finish)
    response.once('close', finish)
    if (request.aborted || response.destroyed) finish()
  })
}

function createLocalModelServer() {
  let requests = 0
  const server = createServer(async (incoming, outgoing) => {
    requests += 1
    const chunks: Buffer[] = []
    for await (const chunk of incoming) chunks.push(Buffer.from(chunk))
    const payload = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
      messages?: { role?: string; content?: unknown }[]
      stream?: boolean
    }
    const userMessages = (payload.messages ?? []).filter((message) => message.role === 'user')
    const prompt = contentText(userMessages[userMessages.length - 1]?.content)

    if (payload.stream) {
      outgoing.writeHead(200, {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      })
      if (prompt.includes('slow')) await waitForRequestClose(incoming, outgoing)
      if (outgoing.destroyed) return
      const created = Math.floor(Date.now() / 1000)
      const chunk = (delta: Record<string, unknown>, finishReason: string | null) =>
        `data: ${JSON.stringify({
          id: 'chatcmpl-headless-qa',
          object: 'chat.completion.chunk',
          created,
          model: 'qa-model',
          choices: [{ index: 0, delta, finish_reason: finishReason }],
        })}\n\n`
      outgoing.write(chunk({ role: 'assistant', content: `已完成：${prompt}` }, null))
      outgoing.write(chunk({}, 'stop'))
      outgoing.end('data: [DONE]\n\n')
      return
    }

    outgoing.writeHead(200, { 'content-type': 'application/json' })
    outgoing.end(
      JSON.stringify({
        id: 'chatcmpl-headless-qa',
        object: 'chat.completion',
        created: Math.floor(Date.now() / 1000),
        model: 'qa-model',
        choices: [
          {
            index: 0,
            message: { role: 'assistant', content: 'LOCAL_QA_FILE_DELIVERY_SUCCESS' },
            finish_reason: 'stop',
          },
        ],
        usage: { prompt_tokens: 3, completion_tokens: 4, total_tokens: 7 },
      }),
    )
  })
  return { server, requests: () => requests }
}

function slug(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

function pathOf(url: string) {
  const parsed = new URL(url)
  return `${parsed.pathname}${parsed.search}`
}

test.beforeEach(async ({ page }) => {
  const traffic: Traffic = { http: [], console: [], pageErrors: [] }
  trafficByPage.set(page, traffic)
  page.on('requestfinished', async (request) => {
    const response = await request.response()
    traffic.http.push({
      method: request.method(),
      path: pathOf(request.url()),
      status: response?.status(),
    })
  })
  page.on('requestfailed', (request) => {
    traffic.http.push({
      method: request.method(),
      path: pathOf(request.url()),
      failed: request.failure()?.errorText ?? 'request failed',
    })
  })
  page.on('console', (message) => {
    traffic.console.push({ type: message.type(), text: message.text() })
  })
  page.on('pageerror', (error) => traffic.pageErrors.push(error.message))
})

test.afterEach(async ({ page }, testInfo) => {
  const traffic = trafficByPage.get(page)
  if (!traffic) return
  const directory = join(artifactRoot, slug(testInfo.title))
  await mkdir(directory, { recursive: true })
  await writeFile(join(directory, 'http.json'), JSON.stringify(traffic.http, null, 2))
  await writeFile(join(directory, 'console.json'), JSON.stringify(traffic.console, null, 2))
  await writeFile(join(directory, 'pageerror.json'), JSON.stringify(traffic.pageErrors, null, 2))
  await writeFile(
    join(directory, 'result.json'),
    JSON.stringify({ status: testInfo.status, expectedStatus: testInfo.expectedStatus }, null, 2),
  )
  if (!page.isClosed()) {
    await page.screenshot({ path: join(directory, 'final.png'), fullPage: true })
  }
  await testInfo.attach('headless-channel-http', {
    path: join(directory, 'http.json'),
    contentType: 'application/json',
  })
  await testInfo.attach('headless-channel-console', {
    path: join(directory, 'console.json'),
    contentType: 'application/json',
  })
  await testInfo.attach('headless-channel-pageerror', {
    path: join(directory, 'pageerror.json'),
    contentType: 'application/json',
  })
})

async function api(
  request: APIRequestContext,
  page: Page,
  method: string,
  path: string,
  data?: unknown,
) {
  const response = await request.fetch(path, { method, data })
  trafficByPage.get(page)?.http.push({ method, path, status: response.status() })
  return response
}

async function pageScreenshot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(name)
  await mkdir(dirname(path), { recursive: true })
  await page.screenshot({ path, fullPage: true })
  await testInfo.attach(name, { path, contentType: 'image/png' })
}

async function poll<T>(read: () => Promise<T>, accept: (value: T) => boolean, label: string) {
  const deadline = Date.now() + 15_000
  let latest: T | undefined
  while (Date.now() < deadline) {
    latest = await read()
    if (accept(latest)) return latest
    await new Promise((resolve) => setTimeout(resolve, 150))
  }
  throw new Error(`${label} did not reach the expected state; last=${JSON.stringify(latest)}`)
}

function assertNoPageErrors(page: Page) {
  expect(trafficByPage.get(page)?.pageErrors ?? []).toEqual([])
}

test('web/email/file schemas, invalid settings, and file channel CRUD', async ({
  page,
  request,
}, testInfo) => {
  const created: { kind: string; id: string }[] = []
  const unique = Date.now().toString(36)
  const fileId = `qa_file_${unique}`
  const emailId = `qa_email_${unique}`

  try {
    const pluginResponse = await api(request, page, 'GET', '/api/plugins')
    expect(pluginResponse.status()).toBe(200)
    const capabilities = (await pluginResponse.json()) as {
      kind: string
      name: string
      capabilities: string[]
      options_schema: Record<string, any>
    }[]
    const channels = capabilities.filter((item) => item.kind === 'channel')
    const schema = (name: string) => {
      const item = channels.find((candidate) => candidate.name === name)
      expect(item, `missing ${name} channel capability`).toBeTruthy()
      return item!
    }
    expect(schema('web').options_schema).toMatchObject({
      type: 'object',
      additionalProperties: false,
      properties: {},
    })
    expect(schema('email').options_schema.required).toEqual(
      expect.arrayContaining(['host', 'port', 'sender', 'recipient']),
    )
    expect(schema('email').options_schema.properties.tls.enum).toEqual([
      'none',
      'starttls',
      'implicit',
    ])
    expect(schema('email').options_schema.properties.recipient['x-workflowweave-workflow']).toBe(
      true,
    )
    expect(schema('file').options_schema.required).toContain('path')
    expect(schema('file').options_schema.properties.path).toMatchObject({
      type: 'string',
      minLength: 1,
      'x-workflowweave-path': true,
    })

    await page.goto('/resources?kind=channels')
    await page.getByRole('button', { name: '添加通知渠道' }).click()
    const dialog = page.getByRole('dialog', { name: '添加通知渠道' })
    await dialog.getByLabel('渠道能力名称').click()
    await page.getByRole('option', { name: 'email', exact: true }).click()
    const emailOptions = dialog.getByRole('region', { name: '插件参数 (options)' })
    for (const name of ['host', 'port', 'sender', 'recipient']) {
      await emailOptions.getByRole('switch', { name: `设置 ${name}` }).locator('..').click()
      await expect(emailOptions.getByRole('textbox', { name, exact: true })).toBeVisible()
    }
    await emailOptions.getByRole('switch', { name: '设置 tls' }).locator('..').click()
    await expect(emailOptions.getByRole('combobox', { name: 'tls' })).toBeVisible()
    await pageScreenshot(page, testInfo, 'email-schema.png')
    await dialog.getByRole('button', { name: '保存资源' }).click()
    await expect(dialog).toBeVisible()
    expect(
      trafficByPage
        .get(page)
        ?.http.some((entry) => entry.method === 'POST' && entry.path === '/api/channels'),
    ).toBe(false)

    await dialog.getByRole('button', { name: '取消' }).click()
    await page.getByRole('button', { name: '添加通知渠道' }).click()
    const fileDialog = page.getByRole('dialog', { name: '添加通知渠道' })
    await fileDialog.getByLabel('资源编号').fill(fileId)
    await fileDialog.getByLabel('渠道能力名称').click()
    await page.getByRole('option', { name: 'file', exact: true }).click()
    const fileOptions = fileDialog.getByRole('region', { name: '插件参数 (options)' })
    await fileOptions.getByRole('switch', { name: '设置 path' }).locator('..').click()
    await expect(fileOptions.getByRole('textbox', { name: 'path', exact: true })).toBeVisible()
    await fileDialog.getByRole('button', { name: '保存资源' }).click()
    await expect(fileDialog).toBeVisible()
    expect(
      trafficByPage
        .get(page)
        ?.http.some((entry) => entry.method === 'POST' && entry.path === '/api/channels'),
    ).toBe(false)

    const filePath = join(tmpdir(), `workflowweave-${fileId}.log`)
    await fileOptions.getByRole('textbox', { name: 'path', exact: true }).fill(filePath)
    await fileDialog.getByRole('button', { name: '保存资源' }).click()
    await expect(fileDialog).toBeHidden()
    created.push({ kind: 'channels', id: fileId })
    const persisted = await api(request, page, 'GET', `/api/channels/${fileId}`)
    expect(persisted.status()).toBe(200)
    expect((await persisted.json()).options.path).toBe(filePath)
    const card = page
      .locator('.el-card')
      .filter({ has: page.getByRole('heading', { name: fileId }) })
      .last()
    await card.getByRole('button', { name: '编辑' }).click()
    const editDialog = page.getByRole('dialog', { name: '编辑通知渠道' })
    const updatedPath = `${filePath}.updated`
    const editOptions = editDialog.getByRole('region', { name: '插件参数 (options)' })
    await editOptions.getByRole('textbox', { name: 'path', exact: true }).fill(updatedPath)
    await editDialog.getByRole('button', { name: '保存资源' }).click()
    await expect(editDialog).toBeHidden()
    const updated = await api(request, page, 'GET', `/api/channels/${fileId}`)
    expect((await updated.json()).options.path).toBe(updatedPath)
    await pageScreenshot(page, testInfo, 'file-channel-crud.png')

    const email = await api(request, page, 'POST', '/api/channels', {
      id: emailId,
      channel: 'email',
      enabled: false,
      options: {
        host: 'smtp.example.invalid',
        port: 587,
        sender: 'qa@example.invalid',
        recipient: 'recipient@example.invalid',
      },
    })
    expect(email.status(), await email.text()).toBe(201)
    created.push({ kind: 'channels', id: emailId })
    const emailSaved = await api(request, page, 'GET', `/api/channels/${emailId}`)
    expect(emailSaved.status()).toBe(200)
    expect((await emailSaved.json()).enabled).toBe(false)

    const invalidFile = await api(request, page, 'POST', '/api/channels', {
      id: `qa_invalid_file_${unique}`,
      channel: 'file',
      options: { path: '' },
    })
    expect(invalidFile.status()).toBe(422)
      expect((await invalidFile.json()).error.code).toBe('invalid_config')

    const validExternalOptions: Record<string, Record<string, unknown>> = {
      qq: { app_id: 'qa-placeholder', client_secret: testSecretReference },
      feishu: { app_id: 'qa-placeholder', app_secret: testSecretReference },
      telegram: { token: testSecretReference },
      wechat_openclaw: { account_id: 'qa-placeholder' },
    }
    for (const [platform, options] of Object.entries(validExternalOptions)) {
      const id = `qa_${platform}_${unique}`
      const invalid = await api(request, page, 'POST', '/api/channels', {
        id: `qa_invalid_${platform}_${unique}`,
        channel: platform,
        enabled: false,
        options: {},
      })
      expect(invalid.status(), `${platform} invalid config`).toBe(422)
      expect((await invalid.json()).error.code).toBe('invalid_config')

      const valid = await api(request, page, 'POST', '/api/channels', {
        id,
        channel: platform,
        enabled: false,
        agent_enabled: false,
        options,
      })
      const validBody = await valid.json()
      expect(valid.status(), `${platform} valid config`).toBe(201)
      created.push({ kind: 'channels', id })
      expect(validBody.enabled).toBe(false)
    }

    const cardAfterUpdate = page
      .locator('.el-card')
      .filter({ has: page.getByRole('heading', { name: fileId }) })
      .last()
    await cardAfterUpdate.getByRole('button', { name: '删除' }).click()
    await expect(page.getByText('确认删除此资源？')).toBeVisible()
    await page.getByRole('button', { name: '确定' }).click()
    await expect(page.getByRole('heading', { name: fileId })).toHaveCount(0)
    const deleted = await api(request, page, 'GET', `/api/channels/${fileId}`)
    expect(deleted.status()).toBe(409)
    expect((await deleted.json()).error.code).toBe('not_found')
    const fileIndex = created.findIndex((item) => item.id === fileId)
    expect(fileIndex).toBeGreaterThanOrEqual(0)
    created.splice(fileIndex, 1)
    await pageScreenshot(page, testInfo, 'file-channel-deleted.png')
  } finally {
    for (const item of created.reverse()) {
      const response = await api(request, page, 'DELETE', `/api/${item.kind}/${item.id}`)
      if (![204, 404].includes(response.status())) {
        throw new Error(`Cleanup failed for ${item.kind}/${item.id}: ${response.status()}`)
      }
    }
  }
  assertNoPageErrors(page)
})

test('file channel delivers a real Workflow notification to a readable temp file', async ({
  page,
  request,
}, testInfo) => {
  const created: { kind: string; id: string }[] = []
  const scratch = await mkdtemp(join(tmpdir(), 'workflowweave-headless-channel-'))
  const outputPath = join(scratch, 'delivery.log')
  let model: ReturnType<typeof createLocalModelServer> | undefined
  const unique = Date.now().toString(36)
  const aiId = `qa_ai_${unique}`
  const sourceId = `qa_source_${unique}`
  const fileId = `qa_delivery_file_${unique}`
  const workflowId = `qa_file_workflow_${unique}`

  try {
    model = createLocalModelServer()
    model.server.listen(0, '127.0.0.1')
    await once(model.server, 'listening')
    const address = model.server.address()
    if (!address || typeof address === 'string') throw new Error('Local AI test server has no port')

    const ai = await api(request, page, 'POST', '/api/ai', {
      id: aiId,
      provider: 'openai_compatible_api',
      base_url: `http://127.0.0.1:${address.port}/v1`,
      api_key: null,
      models: { 'qa-model': {} },
      timeout: 10,
      retries: 0,
    })
    expect(ai.status(), await ai.text()).toBe(201)
    created.push({ kind: 'ai', id: aiId })

    const source = await api(request, page, 'POST', '/api/sources', {
      id: sourceId,
      call: { kind: 'cli', mode: 'argv', executable: 'printf', argv: ['headless QA input'] },
      timeout: 5,
    })
    expect(source.status(), await source.text()).toBe(201)
    created.push({ kind: 'sources', id: sourceId })

    const channel = await api(request, page, 'POST', '/api/channels', {
      id: fileId,
      channel: 'file',
      options: { path: outputPath },
    })
    expect(channel.status(), await channel.text()).toBe(201)
    created.push({ kind: 'channels', id: fileId })

    const workflow = await api(request, page, 'POST', '/api/workflows', {
      id: workflowId,
      name: 'Headless file delivery QA',
      sources: [sourceId],
      analyses: [
        {
          id: 'analysis',
          ai: aiId,
          model: 'qa-model',
          user_prompt: 'Return a brief completion for this isolated delivery check.',
        },
      ],
      channels: [fileId],
    })
    expect(workflow.status(), await workflow.text()).toBe(201)
    created.push({ kind: 'workflows', id: workflowId })

    const started = await api(request, page, 'POST', `/api/workflows/${workflowId}/run`)
    expect(started.status(), await started.text()).toBe(202)
    const sessionId = (await started.json()).session_id as string
    const completed = await poll(
      async () => {
        const response = await api(request, page, 'GET', `/api/sessions/${sessionId}`)
        expect(response.status()).toBe(200)
        return response.json()
      },
      (session) => ['completed', 'partial', 'failed', 'cancelled'].includes(session.status),
      'Workflow run',
    )
    expect(completed.status).toBe('completed')
    expect(model.requests()).toBeGreaterThan(0)
    const delivered = await readFile(outputPath, 'utf8')
    expect(delivered).toContain('LOCAL_QA_FILE_DELIVERY_SUCCESS')
    expect(delivered).toContain(`channel=${fileId}`)
    await writeFile(testInfo.outputPath('file-delivery-readback.log'), delivered)
    await testInfo.attach('file-delivery-readback', {
      path: testInfo.outputPath('file-delivery-readback.log'),
      contentType: 'text/plain',
    })

    await page.goto('/resources?kind=channels')
    await expect(page.getByRole('heading', { name: fileId })).toBeVisible()
    await pageScreenshot(page, testInfo, 'file-delivery-resource.png')
  } finally {
    if (model?.server.listening) {
      model.server.close()
      await once(model.server, 'close')
    }
    for (const item of created.reverse()) {
      const response = await api(request, page, 'DELETE', `/api/${item.kind}/${item.id}`)
      if (![204, 404].includes(response.status())) {
        throw new Error(`Cleanup failed for ${item.kind}/${item.id}: ${response.status()}`)
      }
    }
    await rm(scratch, { recursive: true, force: true })
  }
  assertNoPageErrors(page)
})

test('test_channel routes duplex input through binding, queue, stop, and outbox', async ({
  page,
  request,
}, testInfo) => {
  const unique = Date.now().toString(36)
  const channelId = `qa_test_channel_${unique}`
  const aiId = `qa_agent_ai_${unique}`
  const created: { kind: string; id: string }[] = []
  let localModel: ReturnType<typeof createLocalModelServer> | undefined

  async function createSession(requestId: string) {
    const response = await api(request, page, 'POST', '/api/channels/web/commands', {
      channel: 'web',
      request_id: requestId,
      action: 'new',
      model: `${aiId}:qa-model`,
    })
    expect(response.status(), await response.text()).toBe(202)
    const body = await response.json()
    expect(body.kind).toBe('session')
    return body.result.session_id as string
  }

  const message = (requestId: string, text: string) => ({
    request_id: requestId,
    text,
    address: {
      kind: 'test',
      target: 'qa-room',
      sender: 'qa-sender',
      message_id: `message-${requestId}`,
    },
  })

  async function getOutcome(requestId: string, text: string) {
    const response = await api(
      request,
      page,
      'POST',
      `/api/channels/${channelId}/test/outcome`,
      message(requestId, text),
    )
    expect(response.status(), await response.text()).toBe(200)
    return response.json()
  }

  async function inject(requestId: string, text: string) {
    const response = await api(
      request,
      page,
      'POST',
      `/api/channels/${channelId}/test/messages`,
      message(requestId, text),
    )
    expect(response.status(), await response.text()).toBe(202)
    return response.json()
  }

  try {
    localModel = createLocalModelServer()
    localModel.server.listen(0, '127.0.0.1')
    await once(localModel.server, 'listening')
    const modelAddress = localModel.server.address()
    if (!modelAddress || typeof modelAddress === 'string') {
      throw new Error('Local Agent model server has no port')
    }
    const ai = await api(request, page, 'POST', '/api/ai', {
      id: aiId,
      provider: 'openai_compatible_api',
      base_url: `http://127.0.0.1:${modelAddress.port}/v1`,
      api_key: null,
      models: { 'qa-model': {} },
      timeout: 10,
      retries: 0,
    })
    expect(ai.status(), await ai.text()).toBe(201)
    created.push({ kind: 'ai', id: aiId })

    const channel = await api(request, page, 'POST', '/api/channels', {
      id: channelId,
      channel: 'test',
      enabled: true,
      agent_enabled: true,
      options: { target: 'qa-room' },
    })
    expect(channel.status(), await channel.text()).toBe(201)
    created.push({ kind: 'channels', id: channelId })

    const firstSession = await createSession(`qa-new-first-${unique}`)
    const secondSession = await createSession(`qa-new-second-${unique}`)
    const unbound = await api(request, page, 'GET', `/api/channels/${channelId}/conversation`)
    expect((await unbound.json()).session_id).toBeNull()

    await page.goto('/resources?kind=channels')
    const channelCard = page
      .locator('.el-card')
      .filter({ has: page.getByRole('heading', { name: channelId }) })
    await channelCard.getByRole('button', { name: '编辑' }).click()
    const editor = page.getByRole('dialog', { name: '编辑通知渠道' })
    const sessionSelect = editor.getByLabel('选择绑定对话')
    await sessionSelect.click()
    await page.getByRole('option', { name: new RegExp(firstSession) }).click()
    await editor.getByRole('button', { name: '保存绑定' }).click()
    await expect(editor.getByText(`当前：${firstSession}`)).toBeVisible()
    await pageScreenshot(page, testInfo, 'test-channel-binding-first.png')

    const bound = await api(request, page, 'GET', `/api/channels/${channelId}/conversation`)
    expect((await bound.json()).session_id).toBe(firstSession)

    const ordinaryText = `ordinary duplex queue ${unique}`
    await inject(`qa-message-first-${unique}`, ordinaryText)
    const firstOutcome = await poll(
      () => getOutcome(`qa-message-first-${unique}`, ordinaryText),
      (outcome) => outcome.delivery?.status === 'success',
      'first test_channel response',
    )
    expect(firstOutcome.response.result.session_id).toBe(firstSession)
    let outboxResponse = await api(request, page, 'GET', `/api/channels/${channelId}/test/messages`)
    expect(outboxResponse.status()).toBe(200)
    let outbox = await outboxResponse.json()
    expect(outbox).toHaveLength(1)
    expect(outbox[0].notification.text).toContain(`已完成：${ordinaryText}`)

    await sessionSelect.click()
    await page.getByRole('option', { name: new RegExp(secondSession) }).click()
    await editor.getByRole('button', { name: '保存绑定' }).click()
    await expect(editor.getByText(`当前：${secondSession}`)).toBeVisible()
    const rebound = await api(request, page, 'GET', `/api/channels/${channelId}/conversation`)
    expect((await rebound.json()).session_id).toBe(secondSession)

    const secondText = `rebound conversation ${unique}`
    await inject(`qa-message-second-${unique}`, secondText)
    const secondOutcome = await poll(
      () => getOutcome(`qa-message-second-${unique}`, secondText),
      (outcome) => outcome.delivery?.status === 'success',
      'rebound test_channel response',
    )
    expect(secondOutcome.response.result.session_id).toBe(secondSession)

    const slowText = `slow stop active request ${unique}`
    const queuedText = `must remain queued after stop ${unique}`
    await inject(`qa-message-slow-${unique}`, slowText)
    await poll(
      async () => {
        const response = await api(request, page, 'GET', `/api/agents/sessions/${secondSession}`)
        expect(response.status()).toBe(200)
        return response.json()
      },
      (session) => session.status === 'running',
      'slow test_channel Agent turn',
    )
    await inject(`qa-message-queued-${unique}`, queuedText)
    const queuedOutcome = await getOutcome(`qa-message-queued-${unique}`, queuedText)
    expect(queuedOutcome.delivery?.status).not.toBe('success')

    await inject(`qa-stop-${unique}`, '/stop')
    const stopped = await poll(
      () => getOutcome(`qa-stop-${unique}`, '/stop'),
      (outcome) => outcome.response?.result?.status === 'cancelled',
      'high-priority test_channel stop',
    )
    expect(stopped.response.kind).toBe('session')
    const session = await api(request, page, 'GET', `/api/agents/sessions/${secondSession}`)
    expect((await session.json()).status).toBe('cancelled')
    const interrupted = await poll(
      () => getOutcome(`qa-message-queued-${unique}`, queuedText),
      (outcome) => outcome.status === 'interrupted' || outcome.response?.kind === 'error',
      'queued request interruption after stop',
    )
    expect(interrupted.delivery?.status).not.toBe('success')

    outboxResponse = await api(request, page, 'GET', `/api/channels/${channelId}/test/messages`)
    outbox = await outboxResponse.json()
    const outboxTexts = outbox.map(
      (item: { notification: { text: string } }) => item.notification.text,
    )
    expect(outboxTexts.slice(0, 2)).toEqual([`已完成：${ordinaryText}`, `已完成：${secondText}`])
    expect(outboxTexts.slice(2)).toEqual(
      expect.arrayContaining(['本轮已停止。', expect.stringContaining('（cancelled）')]),
    )
    await pageScreenshot(page, testInfo, 'test-channel-queue-stop-outbox.png')
  } finally {
    // The local server is scoped to this test and never contacts an external model provider.
    // The backend API has no session deletion route; channel and AI resources are removed below.
    if (localModel?.server.listening) {
      localModel.server.close()
      await once(localModel.server, 'close')
    }
    for (const item of created.reverse()) {
      const response = await api(request, page, 'DELETE', `/api/${item.kind}/${item.id}`)
      if (![204, 404].includes(response.status())) {
        throw new Error(`Cleanup failed for ${item.kind}/${item.id}: ${response.status()}`)
      }
    }
  }
  assertNoPageErrors(page)
})
