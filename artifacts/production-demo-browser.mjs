import assert from 'node:assert/strict'
import { writeFileSync } from 'node:fs'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import { expect } from '../frontend/node_modules/@playwright/test/index.mjs'

const baseUrl = process.env.DEMO_BASE_URL || 'http://127.0.0.1:3000'
const session = '83c74cef296e4352b3a76989b01441c2'
const browser = await chromium.launch({ headless: true })
const checks = []
const errors = []
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1080 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    reducedMotion: 'reduce',
  })
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('response', (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`)
  })
  const artifact = (name) => new URL(name, import.meta.url).pathname

  await page.goto(`${baseUrl}/workflows/axonhub_inspection/edit`)
  await expect(page.getByRole('button', { name: '保存工作流', exact: true })).toBeEnabled({ timeout: 45000 })
  await expect(page.getByText('AxonHub：近期错误（优先）', { exact: true })).toBeVisible()
  await expect(page.getByText('AxonHub：近期成功与失败统计（后置）', { exact: true })).toBeVisible()
  const text = await page.locator('body').innerText()
  assert.ok(text.indexOf('近期错误（优先）') < text.indexOf('近期成功与失败统计（后置）'))
  assert.ok(text.includes('inspection_ai / gpt-5.6-luna'))
  assert.ok(text.includes('inspection_ai / gpt-5.6-sol'))
  await page.locator('.el-switch').filter({
    has: page.getByRole('switch', { name: '高级模式', exact: true }),
  }).click()
  await expect(page.getByText('总输入 token', { exact: true })).toBeVisible()
  await page.screenshot({ path: artifact('production-inspection-config.png'), fullPage: true })
  await page.getByText('2. 并行 AI 分析', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: artifact('production-inspection-models.png') })
  checks.push({ page: 'inspection configuration', status: 'passed', errorsFirst: true, models: ['gpt-5.6-luna', 'gpt-5.6-sol'] })

  await page.goto(`${baseUrl}/runs/${session}`)
  const report = page.locator('section[aria-labelledby="report-title"] .report-prose').first()
  await expect(report).toBeVisible({ timeout: 45000 })
  await expect(report).toContainText('失败')
  await expect(report).toContainText('成功')
  assert.ok((await report.innerText()).length > 4000)
  await expect(page.getByText('已完成', { exact: true }).first()).toBeVisible()
  await page.screenshot({ path: artifact('production-inspection-result-full.png'), fullPage: true })
  await page.locator('section[aria-labelledby="report-title"]').scrollIntoViewIfNeeded()
  await page.screenshot({ path: artifact('production-inspection-result.png') })
  checks.push({ page: 'inspection report', status: 'passed', session, reportCharacters: (await report.innerText()).length })

  await page.goto(`${baseUrl}/workflows/hermes_github_updates/edit`)
  await expect(page.getByRole('button', { name: '保存工作流', exact: true })).toBeEnabled({ timeout: 45000 })
  const githubText = await page.locator('body').innerText()
  assert.ok(githubText.includes('inspection_ai / gpt-5.6-sol'))
  assert.ok(!githubText.includes('inspection_ai / gpt-5.6-luna'))
  await page.screenshot({ path: artifact('production-github-config.png'), fullPage: true })
  checks.push({ page: 'GitHub configuration', status: 'passed', successfulRun: false, reason: 'gh authentication required' })
  assert.equal(await page.locator('vite-error-overlay').count(), 0)
  assert.deepEqual(errors, [])
} finally {
  await browser.close()
  const result = { baseUrl, verifiedAt: new Date().toISOString(), checks, errors }
  writeFileSync(new URL('production-demo-browser-results.json', import.meta.url), `${JSON.stringify(result, null, 2)}\n`)
  console.log(JSON.stringify(result))
}
