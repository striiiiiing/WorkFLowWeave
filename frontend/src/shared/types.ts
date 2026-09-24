export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject
export interface JsonObject {
  [key: string]: JsonValue
}
export interface ErrorInfo {
  code: string
  message: string
  details: JsonObject
}
