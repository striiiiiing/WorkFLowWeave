import { expect, test } from '@playwright/test'

test('channel remarks and WeChat web login render on desktop and mobile', async ({
  page,
}, info) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/resources?kind=channels')
  await page.getByRole('button', { name: '添加通知渠道' }).click()
  const dialog = page.getByRole('dialog', { name: '添加通知渠道' })

  async function select(name: string) {
    await dialog.getByLabel('渠道能力名称').click()
    await page.getByRole('option', { name, exact: true }).click()
  }

  await select('email')
  await expect(dialog.getByText('授权码', { exact: true })).toBeVisible()
  const options = dialog.getByRole('region', { name: '插件参数 (options)' })
  expect(await options.getByText(/Gmail 示例/).count()).toBe(7)
  await expect(options).toContainText('POP3/IMAP/SMTP/Exchange/CardDAV')
  await expect(options).toContainText('smtp.gmail.com')
  await select('qq')
  await expect(dialog).toContainText('首次互动需由用户完成')
  await select('file')
  await expect(dialog).toContainText('logs/notifications.log')

  await select('wechat_openclaw')
  await expect(dialog).toContainText('最多只能回复 10 条消息')
  await expect(dialog.getByRole('button', { name: '扫码登录', exact: true })).toBeVisible()
  await expect(dialog).toContainText('网页扫码登录微信')
  await expect(options).toContainText('state_dir')
  await expect(options).toContainText('Node.js')
  await expect(options).not.toContainText('api_token')

  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await dialog.getByText('网页扫码登录微信').scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`wechat-${viewport.width}.png`) })
  }
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  expect(errors).toEqual([])
})
