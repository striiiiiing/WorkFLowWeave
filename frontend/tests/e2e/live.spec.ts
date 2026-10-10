/**
 * 已有前后端服务的浏览器烟测：读取真实健康与资源 API，通过界面保存带唯一 ID 的 CLI 数据源，并在 finally 删除测试资源。使用现有服务数据，不启动隔离后端，也不触发模型分析或通知。
 */
import { test, expect } from '@playwright/test'

test('existing frontend receives real API data and saves a resource', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const healthResponse = await request.get('/api/health')
  expect(healthResponse.status(), await healthResponse.text()).toBe(200)
  const health = await healthResponse.json()
  expect(['ready', 'degraded']).toContain(health.status)
  expect(health.accepting_runs).toBe(true)

  await page.goto('/')
  await expect(page.getByText('系统状态', { exact: true })).toBeVisible()
  await expect(page.locator('.el-alert--error')).toHaveCount(0)
  for (const kind of ['sources', 'mcp_servers', 'ai', 'channels', 'workflows', 'sessions', 'plugins']) {
    const response = await request.get(`/api/${kind}`)
    expect(response.status(), `${kind}: ${await response.text()}`).toBe(200)
    expect(Array.isArray(await response.json())).toBe(true)
  }

  const id = `live_smoke_${Date.now()}`
  try {
    await page.goto('/resources')
    await page.getByRole('button', { name: '添加数据源' }).click()
    await page.getByLabel('资源编号', { exact: true }).fill(id)
    await page.locator('.el-radio-button__inner').filter({ hasText: /^CLI$/ }).click()
    await page.locator('.el-radio-button__inner').filter({ hasText: /^Shell 命令$/ }).click()
    await page.getByLabel('命令', { exact: true }).fill('true')
    await page.getByRole('button', { name: '保存资源' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(page.getByRole('heading', { name: id, exact: true })).toBeVisible()
    const saved = await request.get(`/api/sources/${id}`)
    expect(saved.status()).toBe(200)
    expect((await saved.json()).id).toBe(id)
    expect(errors).toEqual([])
  } finally {
    const resource = await request.get(`/api/sources/${id}`)
    if (resource.status() === 200) {
      expect((await request.delete(`/api/sources/${id}`)).status()).toBe(204)
    } else {
      expect(resource.status()).toBe(409)
      expect((await resource.json()).error.code).toBe('not_found')
    }
  }
})
