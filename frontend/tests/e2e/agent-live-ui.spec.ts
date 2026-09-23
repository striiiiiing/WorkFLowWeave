import { expect, test } from '@playwright/test'

const sessionId = process.env.AGENT_QA_SESSION

test.skip(!sessionId, 'Set AGENT_QA_SESSION to an existing mock-model QA session.')

test('real mock session supports streamed continuation, branch, stop, model menu and drawers', async ({
  page,
}) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/agents', { waitUntil: 'domcontentloaded' })
  const sessionItem = page
    .locator('.sidebar-session-item')
    .filter({ hasText: sessionId!.slice(0, 14) })
  await expect(sessionItem).toHaveCount(1)
  await sessionItem.click()
  await expect(page).toHaveURL(`/agents/${sessionId!}`)
  await expect(page.getByRole('textbox', { name: 'Agent 消息' })).toBeEnabled()
  await expect(page.getByLabel('切换供应商渠道模型')).toContainText('diagnose-provider-old / mock')

  const prompt = `Browser QA second turn ${Date.now()}. Reply with a short confirmation.`
  const previousResponses = await page.locator('.assistant-content').count()
  const streamResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/agents/sessions/${sessionId}/events`) &&
      response.status() === 200,
  )
  await page.getByRole('textbox', { name: 'Agent 消息' }).fill(prompt)
  await page.getByRole('button', { name: '发送' }).click()
  const liveStream = await streamResponse
  expect(liveStream.headers()['content-type']).toContain('text/event-stream')
  await expect(page.locator('.connection-badge.connected')).toBeVisible()
  await expect(page.getByText(prompt)).toBeVisible()
  await expect
    .poll(() => page.locator('.assistant-content').count(), { timeout: 60_000 })
    .toBeGreaterThan(previousResponses)
  await expect(page.locator('.status-banner').last()).toContainText('completed', {
    timeout: 60_000,
  })

  const assistantAnswer = (await page.locator('.assistant-content').last().innerText()).trim()
  expect(assistantAnswer.length).toBeGreaterThan(0)
  const answerBranchCount = page.getByRole('button', { name: '创建分支' })
  await expect(answerBranchCount.last()).toBeEnabled()
  await answerBranchCount.last().click()
  await page.waitForURL((url) => url.pathname !== `/agents/${sessionId}`)
  await expect(page).toHaveURL(/\/agents\/agent_[\da-f]+$/)
  const branchId = new URL(page.url()).pathname.split('/').at(-1)!
  expect(branchId).not.toBe(sessionId)
  await expect(page.getByRole('textbox', { name: 'Agent 消息' })).toBeEnabled()

  await page.getByRole('button', { name: '切换供应商渠道模型' }).click()
  await expect(page.getByRole('menu')).toContainText('diagnose-provider-old')
  await expect(page.getByRole('menu')).toContainText('mock')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: '工作区文件' }).click()
  await expect(page.getByRole('heading', { name: 'Agent 工作区文件' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '文件路径' })).toHaveValue('AGENTS.md')
  await expect(page.getByRole('button', { name: '读取' })).toBeEnabled()
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: '全局设置' }).last().click()
  const settingsDialog = page.getByRole('dialog', { name: 'Agent 全局设置与运行环境' })
  await expect(settingsDialog).toBeVisible()
  for (const tab of ['工具插件与调度', '沙箱与安全隔离', '基础设置']) {
    await settingsDialog.getByRole('tab', { name: tab }).click()
    await expect(settingsDialog.getByRole('tab', { name: tab })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  }
  await settingsDialog.getByRole('button', { name: '取消' }).click()

  await page.getByRole('button', { name: 'Workflow 来源' }).click()
  await expect(page.getByText(/^Workflow session：/)).toBeVisible()
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Workflow 历史' }).click()
  await expect(page.getByRole('button', { name: '刷新历史' })).toBeVisible()
  await expect(
    page.getByText('暂无 Workflow 运行记录').or(page.locator('.workflow-history-card').first()),
  ).toBeVisible()
  await page.keyboard.press('Escape')

  await page.locator('button[title="查看分支执行图谱"]').click()
  await expect(page.getByRole('heading', { name: '会话分支与执行图谱' })).toBeVisible()
  await page.keyboard.press('Escape')

  const stopPrompt = `Browser QA stop check ${Date.now()}. Do one brief tool-assisted check.`
  await page.getByRole('textbox', { name: 'Agent 消息' }).fill(stopPrompt)
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.locator('.running-capsule')).toBeVisible({ timeout: 10_000 })
  const cancelResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/agents/sessions/${branchId}/cancel`) &&
      response.request().method() === 'POST',
  )
  await page.locator('.capsule-stop-btn').click()
  expect((await cancelResponse).ok()).toBe(true)
  await expect(page.locator('.running-capsule')).toBeHidden({ timeout: 20_000 })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('button', { name: '全局设置' }).first()).toBeVisible()
  await page.getByRole('button', { name: '全局设置' }).first().click()
  await expect(page.getByRole('dialog', { name: 'Agent 全局设置与运行环境' })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: '取消' }).click()

  expect(pageErrors).toEqual([])
  test.info().annotations.push({
    type: 'qa-sessions',
    description: `parent=${sessionId!}; branch=${branchId}; model=diagnose-provider-old:mock`,
  })
})
