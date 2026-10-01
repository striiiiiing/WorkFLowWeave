import type { JsonObject } from '@/shared/types'

/** Match the backend's top-level x-logagent-workflow scope declaration. */
export function optionSchema(schema: JsonObject | undefined, scope: 'resource' | 'workflow') {
  if (!schema) return undefined
  const properties = (schema.properties ?? {}) as Record<string, JsonObject>
  const callNames = Object.keys(properties).filter(
    (name) => properties[name]['x-logagent-workflow'] === true,
  )
  if (scope === 'resource') {
    return {
      ...schema,
      required: ((schema.required ?? []) as string[]).filter((name) => !callNames.includes(name)),
    }
  }
  return {
    ...schema,
    properties: Object.fromEntries(callNames.map((name) => [name, properties[name]])),
    required: [],
    additionalProperties: false,
  }
}

/** Overrides and reusable templates may intentionally leave required values to the source. */
export function partialSchema(schema: JsonObject | null | undefined) {
  return schema ? { ...schema, required: [] } : undefined
}
