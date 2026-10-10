import { expect, test } from '@playwright/test'

for (const platform of ['qq', 'feishu', 'telegram']) {
  test(`${platform} first-message onboarding waits for a message and confirms success`, async ({
    page,
  }) => {
    const channelId = `qa-first-message-${platform}`
    let connectionReads = 0
    let persisted = {
      id: channelId,
      channel: platform,
      enabled: true,
      agent_enabled: false,
      timeout: 30,
      options: { app_id: 'qa-app' },
    }

    await page.route('**/api/plugins', async (route) => {
      await route.fulfill({
        json: [
          {
            kind: 'channel',
            name: platform,
            plugin: platform,
            description: `${platform} 首次消息连接`,
            capabilities: ['notification', 'conversation'],
            options_schema: {
              type: 'object',
              properties: { app_id: { type: 'string' } },
              'x-workflowweave-first-message': true,
            },
          },
        ],
      })
    })
    await page.route('**/api/channels', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ json: [persisted] })
        return
      }
      const body = route.request().postDataJSON() as typeof persisted
      persisted = { ...body, id: body.id || channelId }
      await route.fulfill({ status: 201, json: persisted })
    })
    await page.route('**/api/channels/**', async (route) => {
      const pathname = new URL(route.request().url()).pathname
      const method = route.request().method()
      if (!pathname.endsWith('/connection')) {
        if (method === 'GET') {
          await route.fulfill({ json: persisted })
          return
        }
        if (method === 'PUT') {
          persisted = route.request().postDataJSON() as typeof persisted
          await route.fulfill({ json: persisted })
          return
        }
        await route.fulfill({ status: 204, body: '' })
        return
      }
      const activeId = persisted.id
      if (method === 'POST') {
        await route.fulfill({
          json: {
            channel_id: activeId,
            state: 'waiting_message',
            message: '请发送首条私聊消息',
            error: null,
            target_options: {},
          },
        })
        return
      }
      if (method === 'GET') {
        connectionReads += 1
        await route.fulfill({
          json: {
            channel_id: activeId,
            state: connectionReads === 1 ? 'waiting_message' : 'connected',
            message: connectionReads === 1 ? '请发送首条私聊消息' : '成功连接',
            error: null,
            target_options:
              connectionReads === 1 ? {} : { target_kind: 'c2c', target_id: 'qa-open-id' },
          },
        })
        return
      }
      await route.fulfill({
        json: {
          channel_id: activeId,
          state: 'cancelled',
          message: '连接已取消',
          error: null,
          target_options: {},
        },
      })
    })

    await page.goto('/resources?kind=channels')
    await page.getByRole('button', { name: '添加通知渠道' }).click()
    const dialog = page.getByRole('dialog', { name: '添加通知渠道' })
    await dialog.getByLabel('渠道能力名称').click()
    await page.getByRole('option', { name: platform, exact: true }).click()
    await expect(dialog.getByText('首次连接需要一条私聊消息')).toBeVisible()
    await dialog.getByRole('button', { name: '保存并连接', exact: true }).click()
    await expect(dialog.getByText('等待首条私聊消息')).toBeVisible()
    await expect(dialog.getByText('成功连接')).toBeVisible({ timeout: 5_000 })
    await expect(dialog.getByRole('button', { name: '完成', exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: '完成', exact: true }).click()
    await expect(dialog).toBeHidden()
  })
}
