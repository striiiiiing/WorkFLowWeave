export function formatUpdated(readAt: number | undefined) {
  return readAt === undefined ? '' : `上次成功读取：${new Date(readAt).toLocaleString('zh-CN')}`
}
export function staleMessage(error: string, hasData: boolean, readAt: number | undefined) {
  if (!error) return ''
  return hasData
    ? `${error}；以下内容来自上次成功读取（${readAt === undefined ? '时间未记录' : new Date(readAt).toLocaleString('zh-CN')}）`
    : error
}
