import type { ChannelOverride } from '@/modules/resources/model/public'

export interface NotificationConfig {
  channels: string[]
  channel_overrides: Record<string, ChannelOverride>
  send_partial: boolean
}

export function createNotificationDefaults(): NotificationConfig {
  return { channels: [], channel_overrides: {}, send_partial: true }
}
