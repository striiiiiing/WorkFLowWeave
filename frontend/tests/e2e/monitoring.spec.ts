import { expect, test } from '@playwright/test'

test('dashboard shares health reads and keeps successful panels when plugin refresh fails', async ({
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
  const pluginMetric = page
    .locator('.el-card')
    .filter({ has: page.getByText('已注册插件能力', { exact: true }) })
    .first()
  await expect(pluginMetric).toContainText('上次成功读取')
  const priorCount = await pluginMetric.locator('.text-3xl').innerText()
  expect(priorCount).not.toBe('—')
  expect(reads).toEqual({ health: 1, plugins: 1, sessions: 1, workflows: 1 })
  await page.getByRole('switch', { name: '高级模式', exact: true }).locator('..').click()
  await expect(page.getByRole('heading', { name: '组件健康状态' })).toBeVisible()
  expect(reads.health).toBe(1)
  await page.route('**/api/plugins', (route) => route.abort('failed'))
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(pluginMetric).toContainText('以下内容来自上次成功读取')
  await expect(pluginMetric.locator('.text-3xl')).toHaveText(priorCount)
  await expect(page.getByRole('heading', { name: '最近执行历史' })).toBeVisible()
  expect(reads.health).toBe(2)
  await page.screenshot({ path: 'test-results/dashboard-partial-failure.png', fullPage: true })
  expect(errors).toEqual([])
})
