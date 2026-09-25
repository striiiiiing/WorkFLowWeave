import { ref } from 'vue'
import type { CredentialProtector } from '../model/types'
import type { Credential } from '../model/types'

type CredentialMode = 'keep' | 'input' | 'env' | 'none'

export function useCredentialEditor(
  props: { modelValue: Credential | null },
  emit: (event: 'update:modelValue', value: Credential | null) => void,
  protect: CredentialProtector,
) {
  const mode = ref<CredentialMode>(props.modelValue?.kind === 'env' ? 'env' : 'keep')
  const plaintext = ref('')
  const environmentName = ref(props.modelValue?.kind === 'env' ? props.modelValue.name : '')
  const error = ref('')

  function validateEnvironment(value: string): boolean {
    return /^[A-Za-z_][A-Za-z0-9_]*$/.test(value)
  }

  async function prepare(): Promise<Credential | null> {
    error.value = ''
    if (mode.value === 'keep') return props.modelValue
    if (mode.value === 'none') {
      emit('update:modelValue', null)
      return null
    }
    if (mode.value === 'env') {
      if (!validateEnvironment(environmentName.value)) {
        error.value = '请输入有效环境变量名称'
        throw new Error(error.value)
      }
      const value = { kind: 'env' as const, name: environmentName.value }
      emit('update:modelValue', value)
      return value
    }
    if (!plaintext.value) {
      error.value = '请输入凭据，或选择保留、环境变量或清除'
      throw new Error(error.value)
    }
    const value = await protect(plaintext.value)
    emit('update:modelValue', value)
    plaintext.value = ''
    mode.value = 'keep'
    return value
  }

  return { mode, plaintext, environmentName, error, prepare }
}
