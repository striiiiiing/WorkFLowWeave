import type { JsonObject, JsonValue } from '@/shared/types'

export type Credential =
  | { kind: 'env'; name: string }
  | { kind: 'encrypted'; format_version: number; key_id: string; ciphertext: string }

export type CredentialProtector = (
  plaintext: string,
) => Promise<Extract<Credential, { kind: 'encrypted' }>>

export function credentialPropertyNames(schema: JsonObject | undefined): string[] {
  const properties = (schema?.properties ?? {}) as Record<string, JsonObject>
  return Object.keys(properties).filter(
    (name) => properties[name]['x-workflowweave-credential'] === true,
  )
}

export function requiredCredentialPropertyNames(schema: JsonObject | undefined): string[] {
  const required = new Set(Array.isArray(schema?.required) ? (schema.required as string[]) : [])
  return credentialPropertyNames(schema).filter((name) => required.has(name))
}

/** Accept plaintext in editor drafts; preserve reference validation and cross-field rules. */
export function credentialDraftSchema(schema: JsonObject | undefined): JsonObject | undefined {
  if (!schema) return undefined
  const names = credentialPropertyNames(schema)
  function visit(node: JsonValue): JsonValue {
    if (!node || typeof node !== 'object' || Array.isArray(node)) return node
    const result = { ...node }
    for (const keyword of ['allOf', 'anyOf', 'oneOf']) {
      const branches = node[keyword]
      if (Array.isArray(branches)) result[keyword] = branches.map(visit)
    }
    for (const keyword of ['if', 'then', 'else', 'not']) {
      const branch = node[keyword]
      if (branch && typeof branch === 'object' && !Array.isArray(branch))
        result[keyword] = visit(branch)
    }
    if (node.properties) {
      result.properties = Object.fromEntries(
        Object.entries(node.properties as JsonObject).map(([name, definition]) => {
          if (
            !names.includes(name) ||
            typeof definition !== 'object' ||
            definition === null ||
            Array.isArray(definition)
          )
            return [name, definition]
          // Conditional object requirements (e.g. SMTP authentication) also accept draft strings.
          if (definition['x-workflowweave-credential'] === true || definition.type === 'object') {
            const { title, description, default: defaultValue } = definition
            const property: JsonObject = {
              anyOf: [{ type: 'string', minLength: 1 }, definition],
              'x-workflowweave-credential': true,
            }
            if (title !== undefined) property.title = title
            if (description !== undefined) property.description = description
            if (defaultValue !== undefined) property.default = defaultValue
            return [name, property]
          }
          return [name, definition as JsonValue]
        }),
      )
    }
    return result
  }
  return visit(schema) as JsonObject
}
