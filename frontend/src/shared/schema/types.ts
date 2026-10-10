import type { JsonObject } from '@/shared/types'

/** Schema-driven editor input; pages select the relevant catalog entries. */
export interface SchemaCapability {
  readonly name: string
  readonly description: string
  readonly id_prefix?: string | null
  readonly capabilities: readonly string[]
  readonly options_schema: JsonObject
}
