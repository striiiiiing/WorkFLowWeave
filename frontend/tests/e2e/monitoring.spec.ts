import { expect, test } from '@playwright/test'

test('dashboard reads health once and keeps prior counts when workflow refresh fails', async ({
  page,
}) => {
  const errors: string[] = []
  const reads = { health: 0, plugins: 0, sessions: 0, workflows: 0 }
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (request.method() !== 'GET') return
    for (const key of Object.keys(reads) as (keyof typeof reads)[])
      if (path === `/api/${key}`) reads[key]++
  })
  await page.goto('/')
  const workflowMetric = page
    .locator('.el-card')
    .filter({ has: page.getByText('已保存工作流', { exact: true }) })
    .first()
  await expect(workflowMetric).toContainText('上次成功读取')
  const priorCount = await workflowMetric.locator('.text-3xl').innerText()
  expect(priorCount).not.toBe('—')
  expect(reads).toEqual({ health: 1, plugins: 0, sessions: 1, workflows: 1 })
  await expect(page.getByRole('switch', { name: '高级模式', exact: true })).toHaveCount(0)
  await page.route('**/api/workflows', (route) => route.abort('failed'))
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(workflowMetric).toContainText('以下内容来自上次成功读取')
  await expect(workflowMetric.locator('.text-3xl')).toHaveText(priorCount)
  await expect(page.getByRole('heading', { name: '最近执行历史' })).toBeVisible()
  expect(reads.health).toBe(2)
  expect(reads.plugins).toBe(0)
  await page.screenshot({ path: 'test-results/dashboard-partial-failure.png', fullPage: true })
  expect(errors).toEqual([])
})
