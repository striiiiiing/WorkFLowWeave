const EXPAND_REASONING_KEY = 'logagent.agent.expand-reasoning'

export function readExpandReasoning(): boolean {
  return localStorage.getItem(EXPAND_REASONING_KEY) === 'true'
}

export function saveExpandReasoning(expand: boolean): void {
  localStorage.setItem(EXPAND_REASONING_KEY, String(expand))
}
