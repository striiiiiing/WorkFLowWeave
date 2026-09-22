import { test, expect } from '@playwright/test'

async function readSse(page: import('@playwright/test').Page, path: string, lastEventId?: number) {
  return page.evaluate(async ({ path, lastEventId }) => {
    const response = await fetch(path, {
      headers: lastEventId === undefined ? {} : { 'Last-Event-ID': String(lastEventId) },
    })
    if (!response.ok || !response.body) throw new Error(`SSE HTTP ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    const ids: number[] = []
    let buffer = ''
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      const records = buffer.split('\n\n')
      buffer = records.pop() ?? ''
      for (const record of records) {
        const match = record.match(/^id: (\d+)$/m)
        if (match) ids.push(Number(match[1]))
      }
    }
    return ids
  }, { path, lastEventId })
}

test('Agent uses the real SSE and file API on desktop and narrow screens', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/agents')
  await expect(page.getByRole('heading', { name: 'Agent 会话', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /新会话/ }).click()
  await expect(page.getByText(/发送第一条消息开始/)).toBeVisible()

  const input = page.getByRole('textbox', { name: 'Agent 消息', exact: true })
  await input.fill('hello smoke')
  await page.getByRole('button', { name: /发送/ }).click()
  await expect(page.getByText('已完成：hello smoke', { exact: true })).toBeVisible()
  await expect(page.getByText(/completed · turn.completed/)).toBeVisible()

  const sessionId = await page.locator('.agent-toolbar strong').textContent()
  expect(sessionId).toBeTruthy()
  const eventPath = `/api/agents/sessions/${encodeURIComponent(sessionId!)}/events?after=0`
  const allIds = await readSse(page, eventPath)
  expect(allIds.length).toBeGreaterThan(3)
  expect(allIds).toEqual([...allIds].sort((a, b) => a - b))
  const split = allIds[0]
  const replayIds = await readSse(page, eventPath, split)
  expect(replayIds.length).toBeGreaterThan(0)
  expect(replayIds.every((id) => id > split)).toBe(true)

  await page.getByRole('button', { name: '文件', exact: true }).click()
  const filePath = page.locator('.agent-file-toolbar input')
  await filePath.fill('Memory/smoke.md')
  const initial = await request.put(`/api/agents/file?session_id=${encodeURIComponent(sessionId!)}`
    + '&path=Memory%2Fsmoke.md', {
    data: { mode: 'overwrite', content: 'one' },
  })
  expect(initial.status(), await initial.text()).toBe(200)
  const etag = initial.headers().etag
  expect(etag).toBeTruthy()
  await page.getByRole('button', { name: '读取', exact: true }).click()
  const editor = page.getByRole('textbox', { name: '文件内容', exact: true })
  await expect(editor).toHaveValue('one')
  const external = await request.put(`/api/agents/file?session_id=${encodeURIComponent(sessionId!)}`
    + '&path=Memory%2Fsmoke.md', {
    data: { mode: 'overwrite', content: 'two' },
  })
  expect(external.status(), await external.text()).toBe(200)
  await editor.fill('three')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText(/文件版本冲突|冲突/)).toBeVisible()
  await expect(editor).toHaveValue('three')

  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

test('Agent stop cancels a slow local model turn and releases the browser stream', async ({ page }) => {
  await page.goto('/agents')
  await page.getByRole('button', { name: /新会话/ }).click()
  const input = page.getByRole('textbox', { name: 'Agent 消息', exact: true })
  await input.fill('slow response')
  await page.getByRole('button', { name: /发送/ }).click()
  const stop = page.getByRole('button', { name: /停止/ })
  await expect(stop).toBeEnabled()
  await stop.click()
  await expect(page.getByText(/cancelled · turn.cancelled/)).toBeVisible()
  await expect(stop).toBeDisabled()
})
