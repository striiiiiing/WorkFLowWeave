import type { JsonObject } from '@/shared/types'

export type Credential =
  | { kind: 'env'; name: string }
  | { kind: 'encrypted'; format_version: number; key_id: string; ciphertext: string }

export type CredentialProtector = (
  plaintext: string,
) => Promise<Extract<Credential, { kind: 'encrypted' }>>

export function credentialPropertyNames(schema: JsonObject | undefined): string[] {
  const properties = (schema?.properties ?? {}) as Record<string, JsonObject>
  return Object.keys(properties).filter(
    (name) => properties[name]['x-logagent-credential'] === true,
  )
}
