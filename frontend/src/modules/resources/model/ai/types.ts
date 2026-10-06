import type { JsonObject } from '@/shared/types'
import type { Credential } from '../credential'

export interface AIConfig {
  id: string
  provider: string
  base_url: string | null
  api_key: Credential | null
  system_prompt: string
  models: Record<string, JsonObject>
  timeout: number
  retries: number
}
