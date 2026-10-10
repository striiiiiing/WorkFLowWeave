const pad = (value: number) => String(value).padStart(2, '0')

export function referenceFilename(now = new Date(), random = crypto.randomUUID()): string {
  const offset = -now.getTimezoneOffset()
  const timezone = `UTC${offset >= 0 ? '+' : '-'}${pad(Math.floor(Math.abs(offset) / 60))}-${pad(Math.abs(offset) % 60)}`
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  const time = `${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`
  return `${date}_${time}_${timezone}_${random.slice(0, 8)}.txt`
}
