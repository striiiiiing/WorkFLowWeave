import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('../frontend/node_modules/playwright')
const root = path.dirname(fileURLToPath(import.meta.url))
const baseUrl = 'http://127.0.0.1:3018'
const artifactDir = root
const browserPath = '/home/user/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'
const runId = new Date().toISOString().replace(/\D/g, '').slice(0, 14)
const results = []
const events = { apiRequests: [], consoleErrors: [], pageErrors: [], requestFailures: [], httpErrors: [] }
const responseTimeout = 12000

mkdirSync(artifactDir, { recursive: true })

function record(name, status, detail = '') {
  results.push({ name, status, detail })
}

function formItem(container, label) {
  return container.getByText(label, { exact: true }).locator(
    'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " el-form-item ")][1]',
  )
}

async function fillItem(container, label, value) {
  await formItem(container, label).locator('input, textarea').first().fill(value)
}

function apiResponse(page, resource, method) {
  return page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/${resource}` &&
      response.request().method() === method,
    { timeout: responseTimeout },
  )
}

async function listReadback(page, resource, id) {
  const response = await apiResponse(page, resource, 'GET')
  assert.equal(response.status(), 200, `读取 ${resource} 列表失败: HTTP ${response.status()}`)
  const items = await response.json()
  const item = items.find((entry) => entry.id === id)
  assert.ok(item, `${resource} 列表未回读 ${id}`)
  return item
}

async function submitEvidence(page, buttonName) {
  const button = page.getByRole('button', { name: buttonName, exact: true })
  return button.evaluate((element) => {
    const form = element.form ?? element.closest('form')
    return {
      buttonOuterHTML: element.outerHTML,
      buttonFormNoValidate: element.formNoValidate,
      formNoValidate: form?.noValidate ?? null,
      formOuterHTMLStart: form?.outerHTML.slice(0, 1600) ?? null,
    }
  })
}

async function closeSourceDrawer(page) {
  const dialog = page.getByRole('dialog', { name: '新增数据源' })
  if (!(await dialog.count())) return
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await dialog.waitFor({ state: 'hidden', timeout: 5000 })
}

async function createCliSource(page, mode) {
  const id = `pw-${mode}-${runId}`
  const name = `Playwright CLI ${mode} ${runId}`
  await page.getByRole('button', { name: '添加数据源' }).click()
  const dialog = page.getByRole('dialog', { name: '新增数据源' })
  await dialog.waitFor({ state: 'visible' })
  await fillItem(dialog, '数据源名称', name)
  await fillItem(dialog, '资源编号', id)
  await dialog.getByText('CLI', { exact: true }).click()
  if (mode === 'argv') {
    await fillItem(dialog, '可执行文件', 'printf')
    await fillItem(dialog, '参数（每行一项）', 'hello from Playwright argv')
  } else {
    await dialog.getByText('Shell 命令', { exact: true }).click()
    await fillItem(dialog, '命令', 'printf "hello from Playwright shell"')
  }

  const details = await submitEvidence(page, '保存资源')
  const postPromise = apiResponse(page, 'sources', 'POST')
  const listPromise = apiResponse(page, 'sources', 'GET')
  await dialog.getByRole('button', { name: '保存资源', exact: true }).click()
  const response = await postPromise
  const body = await response.json()
  assert.equal(response.status(), 201, `保存 CLI ${mode} 来源失败: HTTP ${response.status()}`)
  const listed = await listPromise
  const items = await listed.json()
  const saved = items.find((item) => item.id === id)
  assert.ok(saved, `来源列表未回读 CLI ${mode} ${id}`)
  assert.equal(body.call.kind, 'cli')
  assert.equal(body.call.mode, mode)
  if (mode === 'argv') assert.deepEqual(body.call.argv, ['hello from Playwright argv'])
  if (mode === 'shell') assert.equal(body.call.command, 'printf "hello from Playwright shell"')
  await page.getByText(name, { exact: true }).waitFor({ timeout: 10000 })
  return { id, name, mode, postStatus: response.status(), posted: body, listed: saved, submit: details }
}

async function createMcpSource(page, serverId) {
  const id = `pw-mcp-${runId}`
  const name = `Playwright MCP echo ${runId}`
  await page.getByRole('button', { name: '添加数据源' }).click()
  const dialog = page.getByRole('dialog', { name: '新增数据源' })
  await dialog.waitFor({ state: 'visible' })
  await fillItem(dialog, '数据源名称', name)
  await fillItem(dialog, '资源编号', id)

  const serverField = formItem(dialog, 'MCP 服务')
  await serverField.locator('.el-select').click()
  await page.getByRole('option', { name: serverId, exact: true }).click()
  const toolField = formItem(dialog, '工具')
  await toolField.locator('.el-select').click()
  await page.getByRole('option', { name: 'echo', exact: true }).click()

  const args = dialog.locator('section[aria-label="工具参数"]')
  const valueSwitchInput = args.getByRole('switch', { name: '设置 value' })
  await valueSwitchInput.waitFor({ state: 'attached', timeout: 10000 })
  const valueSwitch = valueSwitchInput.locator(
    'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " el-switch ")][1]',
  )
  const valueRow = valueSwitchInput.locator(
    'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " border ")][1]',
  )
  await valueSwitch.click()
  await valueRow.locator('input[type="text"]').fill('hello from Playwright')

  const details = await submitEvidence(page, '保存资源')
  const postPromise = apiResponse(page, 'sources', 'POST')
  const listPromise = apiResponse(page, 'sources', 'GET')
  await dialog.getByRole('button', { name: '保存资源', exact: true }).click()
  const response = await postPromise
  const body = await response.json()
  assert.equal(response.status(), 201, `保存 MCP echo 来源失败: HTTP ${response.status()}`)
  const listed = await listPromise
  const items = await listed.json()
  const saved = items.find((item) => item.id === id)
  assert.ok(saved, `来源列表未回读 MCP echo ${id}`)
  assert.deepEqual(body.call.arguments, { value: 'hello from Playwright' })
  await page.getByText(name, { exact: true }).waitFor({ timeout: 10000 })
  return { id, name, serverId, tool: 'echo', postStatus: response.status(), posted: body, listed: saved, submit: details }
}

async function createMcpServer(page) {
  const id = `pw-server-${runId}`
  await page.getByRole('tab', { name: 'MCP 服务' }).click()
  await page.getByRole('button', { name: '添加MCP 服务' }).click()
  const dialog = page.getByRole('dialog', { name: '添加 MCP 服务' })
  await dialog.waitFor({ state: 'visible' })
  await fillItem(dialog, '服务 ID', id)
  await fillItem(dialog, '可执行文件', `${process.cwd()}/.venv/bin/python`)
  await fillItem(dialog, '参数（每行一项）', 'tests/mcp/stdio_server.py')
  await fillItem(dialog, '工作目录', process.cwd())

  const details = await submitEvidence(page, '保存')
  const postPromise = apiResponse(page, 'mcp_servers', 'POST')
  const listPromise = apiResponse(page, 'mcp_servers', 'GET')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  const response = await postPromise
  const body = await response.json()
  assert.equal(response.status(), 201, `保存 MCP 服务失败: HTTP ${response.status()}`)
  const listed = await listPromise
  const items = await listed.json()
  const saved = items.find((item) => item.id === id)
  assert.ok(saved, `MCP 服务列表未回读 ${id}`)
  assert.equal(body.transport, 'stdio')
  await page.getByText(id, { exact: true }).waitFor({ timeout: 10000 })
  return { id, postStatus: response.status(), posted: body, listed: saved, submit: details }
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: browserPath,
    args: ['--no-sandbox'],
  })
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      locale: 'zh-CN',
      reducedMotion: 'reduce',
    })
    const page = await context.newPage()
    page.setDefaultTimeout(8000)
    page.on('console', (message) => {
      if (message.type() === 'error') events.consoleErrors.push(message.text())
    })
    page.on('pageerror', (error) => events.pageErrors.push(String(error)))
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (!url.pathname.startsWith('/api/')) return
      events.apiRequests.push({ method: request.method(), url: request.url(), body: request.postData() })
    })
    page.on('requestfailed', (request) =>
      events.requestFailures.push({ url: request.url(), method: request.method(), error: request.failure()?.errorText }),
    )
    page.on('response', async (response) => {
      if (response.status() < 400) return
      let body = ''
      try {
        body = (await response.text()).slice(0, 2000)
      } catch {}
      events.httpErrors.push({
        url: response.url(),
        method: response.request().method(),
        status: response.status(),
        body,
      })
    })

    try {
      await page.goto(`${baseUrl}/resources`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: '添加数据源', exact: true }).waitFor({ timeout: 15000 })
      await page.screenshot({ path: path.join(artifactDir, 'collect-from-mcp-cli-resources-desktop.png'), fullPage: true })
      record('资源页加载与桌面截图', 'passed', page.url())
      await page.setViewportSize({ width: 390, height: 844 })
      await page.screenshot({ path: path.join(artifactDir, 'collect-from-mcp-cli-resources-mobile.png'), fullPage: true })
      const resourcesLayout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }))
      record('资源页移动端截图与溢出检查', resourcesLayout.document <= resourcesLayout.viewport ? 'passed' : 'failed', JSON.stringify(resourcesLayout))
      await page.setViewportSize({ width: 1440, height: 1000 })
    } catch (error) {
      record('资源页加载与桌面/移动截图', 'failed', String(error))
    }

    let fixtureId
    try {
      const servers = await page.evaluate(async () => {
        const response = await fetch('/api/mcp_servers')
        if (!response.ok) throw new Error(`MCP server list HTTP ${response.status}`)
        return response.json()
      })
      const server = servers.find((item) => item.enabled)
      assert.ok(server, '没有可用的 MCP fixture 服务')
      fixtureId = server.id
      const data = await page.evaluate(async (serverId) => {
        const [catalog, schema] = await Promise.all([
          fetch(`/api/mcp/catalog?server=${encodeURIComponent(serverId)}`).then((response) => response.json()),
          fetch(`/api/mcp/catalog/${encodeURIComponent(serverId)}/tools/echo`).then((response) => response.json()),
        ])
        return { catalog, schema }
      }, server.id)
      assert.ok(data.catalog.entries.some((entry) => entry.tool === 'echo'), 'MCP 目录缺少 echo')
      assert.ok(data.schema.inputSchema.properties.value, 'echo schema 缺少 value 字段')
      record('MCP fixture 目录与 echo schema', 'passed', JSON.stringify({ server: server.id, schema: data.schema.inputSchema }))
    } catch (error) {
      record('MCP fixture 目录与 echo schema', 'failed', String(error))
    }

    for (const mode of ['argv', 'shell']) {
      try {
        const saved = await createCliSource(page, mode)
        record(`创建并列表回读 CLI ${mode}`, 'passed', JSON.stringify(saved))
      } catch (error) {
        record(`创建并列表回读 CLI ${mode}`, 'failed', String(error))
        await closeSourceDrawer(page).catch(() => {})
      }
    }

    if (fixtureId) {
      try {
        const saved = await createMcpSource(page, fixtureId)
        record('创建并列表回读 MCP echo schema 来源', 'passed', JSON.stringify(saved))
      } catch (error) {
        record('创建并列表回读 MCP echo schema 来源', 'failed', String(error))
        await closeSourceDrawer(page).catch(() => {})
      }
    }
    try {
      const saved = await createMcpServer(page)
      record('新建并列表回读 MCP stdio 服务', 'passed', JSON.stringify(saved))
    } catch (error) {
      record('新建并列表回读 MCP stdio 服务', 'failed', String(error))
    }
    await page.screenshot({ path: path.join(artifactDir, 'collect-from-mcp-cli-resources-saved.png'), fullPage: true })

    try {
      await page.goto(`${baseUrl}/workflows/new`, { waitUntil: 'domcontentloaded' })
      await page.getByText('新建工作流', { exact: true }).waitFor({ timeout: 15000 })
      const advanced = page.locator('.el-switch').filter({ has: page.getByText('高级模式', { exact: true }) })
      await advanced.click()
      await formItem(page, '输入格式').waitFor({ timeout: 10000 })
      const formatSelect = formItem(page, '输入格式').locator('.el-select')
      await formatSelect.click()
      const optionLocator = page.getByRole('option')
      await page.getByRole('option', { name: '原始表示', exact: true }).waitFor({ timeout: 5000 })
      const formats = (await optionLocator.allTextContents()).map((value) => value.trim())
      const expectedFormats = ['原始表示', 'ISON', 'TOON', 'ZON', 'MD', 'CSV']
      assert.deepEqual(formats, expectedFormats)
      await page.screenshot({ path: path.join(artifactDir, 'collect-from-mcp-cli-workflow-formats.png'), fullPage: true })
      await page.keyboard.press('Escape')
      const limits = ['总输入 token', '单项 token', '字段 token']
      const limitControls = {}
      for (const label of limits) {
        const item = formItem(page, label)
        await item.waitFor()
        limitControls[label] = await item.locator('.el-input-number input').count()
        assert.equal(limitControls[label], 1, `${label} 缺少输入控件`)
      }
      await page.screenshot({ path: path.join(artifactDir, 'collect-from-mcp-cli-workflow-desktop.png'), fullPage: true })
      record('Workflow 六格式及总/单项/字段限额', 'passed', JSON.stringify({ formats, limitControls }))

      await page.setViewportSize({ width: 390, height: 844 })
      await page.screenshot({ path: path.join(artifactDir, 'collect-from-mcp-cli-workflow-mobile.png'), fullPage: true })
      const layout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }))
      record('Workflow 移动端截图与溢出检查', layout.document <= layout.viewport ? 'passed' : 'failed', JSON.stringify(layout))
    } catch (error) {
      record('Workflow 新建表单验收', 'failed', String(error))
      try {
        await page.screenshot({ path: path.join(artifactDir, 'collect-from-mcp-cli-workflow-failure.png'), fullPage: true })
      } catch {}
    }

    const summary = { baseUrl, browser: 'Chromium', runId, results, events }
    writeFileSync(path.join(artifactDir, 'collect-from-mcp-cli-browser-results.json'), `${JSON.stringify(summary, null, 2)}\n`)
    console.log(JSON.stringify(summary, null, 2))
    await context.close()
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
