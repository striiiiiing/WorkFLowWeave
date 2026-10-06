import type { AIConfig } from './types'

export function createAIProvider(): AIConfig {
  return {
    id: crypto.randomUUID(),
    provider: 'openai_compatible_api',
    base_url: null,
    api_key: null,
    system_prompt: '',
    models: {},
    timeout: 600,
    retries: 5,
  }
}
