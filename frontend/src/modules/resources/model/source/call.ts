import type { SourceParameters } from './parameters'

export type SourceCall =
  | { kind: 'mcp'; server: string; tool: string; arguments: SourceParameters }
  | { kind: 'cli'; mode: 'argv'; executable: string; argv: string[]; cwd: string | null }
  | { kind: 'cli'; mode: 'shell'; command: string; cwd: string | null }
