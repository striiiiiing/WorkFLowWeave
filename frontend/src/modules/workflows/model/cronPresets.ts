export const weekdays = [
  { value: 'MON', label: '周一' },
  { value: 'TUE', label: '周二' },
  { value: 'WED', label: '周三' },
  { value: 'THU', label: '周四' },
  { value: 'FRI', label: '周五' },
  { value: 'SAT', label: '周六' },
  { value: 'SUN', label: '周日' },
] as const

export type Weekday = (typeof weekdays)[number]['value']
export type CronPreset =
  | { mode: 'hourly'; minute: number }
  | { mode: 'daily'; hour: number; minute: number }
  | { mode: 'weekly'; day: Weekday; hour: number; minute: number }
  | { mode: 'custom' }

export function parseCronPreset(expression: string): CronPreset {
  const [minuteText, hourText, dayOfMonth, month, dayOfWeek, extra] = expression.trim().split(/\s+/)
  if (extra !== undefined || dayOfMonth !== '*' || month !== '*') return { mode: 'custom' }
  if (!/^\d{1,2}$/.test(minuteText ?? '')) return { mode: 'custom' }
  const minute = Number(minuteText)
  if (minute > 59) return { mode: 'custom' }
  if (hourText === '*' && dayOfWeek === '*') return { mode: 'hourly', minute }
  if (!/^\d{1,2}$/.test(hourText ?? '')) return { mode: 'custom' }
  const hour = Number(hourText)
  if (hour > 23) return { mode: 'custom' }
  if (dayOfWeek === '*') return { mode: 'daily', hour, minute }
  const day = weekdays.find(({ value }) => value === dayOfWeek?.toUpperCase())?.value
  return day ? { mode: 'weekly', day, hour, minute } : { mode: 'custom' }
}

export function hourlyCron(minute: number): string {
  return `${minute} * * * *`
}

export function dailyCron(hour: number, minute: number): string {
  return `${minute} ${hour} * * *`
}

export const DEFAULT_DAILY_CRON = dailyCron(9, 0)

export function weeklyCron(day: Weekday, hour: number, minute: number): string {
  return `${minute} ${hour} * * ${day}`
}
