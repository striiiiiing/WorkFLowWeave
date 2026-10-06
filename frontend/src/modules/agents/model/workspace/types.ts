export interface AgentFile {
  path: string
  kind: 'file' | 'directory'
  content?: string
  hash?: string
  readonly: boolean
  offset: number
  next_offset: number | null
  total_lines?: number
  entries?: Array<{ name: string; kind: 'file' | 'directory'; readonly: boolean; symlink: boolean }>
}
