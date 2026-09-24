import { hasInjectionContext, inject, type InjectionKey } from 'vue'
import { errorMessage } from '@/shared/api/errors'
export type ErrorFormatter = (cause: unknown) => string
export const errorFormatterKey: InjectionKey<ErrorFormatter> = Symbol('errorFormatter')
export function useErrorFormatter(): ErrorFormatter {
  return hasInjectionContext() ? inject(errorFormatterKey, errorMessage) : errorMessage
}
