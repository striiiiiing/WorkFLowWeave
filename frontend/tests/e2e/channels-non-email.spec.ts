import { expect, test } from '@playwright/test'

const secret = { kind: 'env', name: 'QA_NON_EMAIL_NO_SEND' }
const options: Record<string, Record<string, unknown>> = {
  file: { path: 'logs/non-email-test.log' },
  qq: { app_id: 'qa-placeholder', client_secret: secret },
  feishu: { app_id: 'qa-placeholder', app_secret: secret },
  telegram: { token: secret },
  wechat_openclaw: { account_id: 'qa-placeholder' },
}

for (const [platform, configuration] of Object.entries(options)) {
  test(`${platform} configuration UI, validation and resource CRUD`, async ({
    page,
    request,
  }, info) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    const id = `qa_non_email_${platform}_${Date.now()}`
    await page.goto('/resources?kind=channels')
    await page.getByRole('button', { name: '添加通知渠道' }).click()
    const dialog = page.getByRole('dialog', { name: '添加通知渠道' })
    await dialog.getByLabel('渠道能力名称').click()
    await page.getByRole('option', { name: platform, exact: true }).click()
    const parameters = dialog.getByRole('region', { name: '插件参数 (options)' })
    const visibleKeys =
      platform === 'wechat_openclaw'
        ? ['state_dir', 'command', 'target_id']
        : Object.keys(configuration)
    for (const key of visibleKeys) {
      await expect(
        parameters.getByRole('switch', { name: `设置 ${key}`, exact: true }).locator('..'),
      ).toBeVisible()
    }
    if (platform === 'qq') await expect(dialog).toContainText('首次互动需由用户完成')
    if (platform === 'wechat_openclaw') {
      await expect(dialog.getByRole('button', { name: '扫码登录', exact: true })).toBeVisible()
      await expect(dialog).toContainText('最多只能回复 10 条消息')
    }
    const saves: string[] = []
    page.on('request', (r) => {
      if (r.method() === 'POST' && new URL(r.url()).pathname === '/api/channels') {
        saves.push(r.url())
      }
    })
    await dialog.getByRole('button', { name: '保存资源' }).click()
    await expect(dialog).toBeVisible()
    expect(saves).toEqual([])
    for (const viewport of [
      { width: 1440, height: 1000 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({ path: info.outputPath(`${platform}-${viewport.width}.png`) })
    }
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    const invalid = await request.post('/api/channels', {
      data: { id, channel: platform, enabled: false, options: {} },
    })
    expect(invalid.status()).toBe(422)
    expect((await invalid.json()).error.code).toBe('invalid_config')
    const created = await request.post('/api/channels', {
      data: { id, channel: platform, enabled: false, agent_enabled: false, options: configuration },
    })
    expect(created.status(), await created.text()).toBe(201)
    try {
      const saved = await request.get(`/api/channels/${id}`)
      expect(saved.status()).toBe(200)
      const resource = await saved.json()
      expect(resource).toMatchObject({ id, channel: platform, enabled: false })
      const edited = await request.put(`/api/channels/${id}`, {
        data: { ...resource, timeout: 17 },
      })
      expect(edited.status(), await edited.text()).toBe(200)
      const reread = await request.get(`/api/channels/${id}`)
      expect((await reread.json()).timeout).toBe(17)
    } finally {
      const deleted = await request.delete(`/api/channels/${id}`)
      expect(deleted.status()).toBe(204)
    }
    const missing = await request.get(`/api/channels/${id}`)
    expect(missing.status()).toBe(409)
    expect((await missing.json()).error.code).toBe('not_found')
    expect(errors).toEqual([])
  })
}
