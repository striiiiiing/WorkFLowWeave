import { chromium } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const outputDir = path.resolve(__dirname, '..')

async function capture() {
  console.log('正在连接 Tabbit CDP (http://127.0.0.1:9222)...')
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222')
  const context = browser.contexts()[0]

  // 优先复用当前已有 agent-demo 标签页，如果没有则新建
  let page = context.pages().find((p) => p.url().includes('/agent-demo'))
  if (!page) {
    page = await context.newPage()
    console.log('正在打开 http://localhost:3000/agent-demo ...')
    await page.goto('http://localhost:3000/agent-demo')
  } else {
    console.log('已复用 Tabbit 中打开的标签页:', page.url())
    await page.bringToFront()
  }

  // 等待渲染完成
  await page.waitForTimeout(2000)

  // 1. 截取主界面全景
  const mainScreenshotPath = path.join(outputDir, 'tabbit-agent-demo-main.png')
  await page.screenshot({ path: mainScreenshotPath, fullPage: true })
  console.log(`[1/3] 主界面全屏截图已保存: ${mainScreenshotPath}`)

  // 2. 模拟输入 '/' 唤起快捷指令并截图
  try {
    const textarea = page.locator('textarea')
    if (await textarea.isVisible()) {
      await textarea.fill('/')
      await page.waitForTimeout(600)
      const slashScreenshotPath = path.join(outputDir, 'tabbit-agent-demo-slash.png')
      await page.screenshot({ path: slashScreenshotPath })
      console.log(`[2/3] 斜杠快捷菜单截图已保存: ${slashScreenshotPath}`)
      await textarea.fill('')
    }
  } catch (err) {
    console.warn('捕获斜杠菜单截图失败:', err.message)
  }

  // 3. 打开全局设置弹窗并截图
  try {
    const settingsBtn = page.locator('button:has-text("全局设置")').first()
    if (await settingsBtn.isVisible()) {
      await settingsBtn.click()
      await page.waitForTimeout(600)
      const settingsScreenshotPath = path.join(outputDir, 'tabbit-agent-demo-settings.png')
      await page.screenshot({ path: settingsScreenshotPath })
      console.log(`[3/3] 全局设置弹窗截图已保存: ${settingsScreenshotPath}`)
    }
  } catch (err) {
    console.warn('捕获全局设置截图失败:', err.message)
  }

  console.log('\n全部截图完成！')
}

capture().catch((err) => {
  console.error('连接或截图失败:', err)
  process.exit(1)
})
