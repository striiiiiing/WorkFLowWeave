<script setup lang="ts">
import { ref } from 'vue'
import { resourcesApi } from '@/api/resources'
import type { Credential } from '@/types'

type CredentialMode = 'keep' | 'input' | 'env' | 'none'

const props = withDefaults(
  defineProps<{
    modelValue: Credential | null
    label?: string
  }>(),
  { label: '凭据' },
)
const emit = defineEmits<{ 'update:modelValue': [value: Credential | null] }>()

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
  const value = await resourcesApi.protectCredential(plaintext.value)
  emit('update:modelValue', value)
  plaintext.value = ''
  mode.value = 'keep'
  return value
}

defineExpose<{ prepare: () => Promise<Credential | null> }>({ prepare })
</script>

<template>
  <section class="mb-5" :aria-label="label">
    <el-form-item :label="label">
      <el-select v-model="mode">
        <el-option value="keep" :label="modelValue ? '保留现有凭据' : '暂不配置'" />
        <el-option value="input" label="输入新凭据（加密保存）" />
        <el-option value="env" label="使用环境变量引用" />
        <el-option value="none" label="清除凭据" />
      </el-select>
    </el-form-item>
    <el-form-item v-if="mode === 'input'" label="新凭据">
      <el-input
        v-model="plaintext"
        type="password"
        show-password
        autocomplete="new-password"
        placeholder="只在本次保存时使用"
      />
    </el-form-item>
    <el-form-item v-if="mode === 'env'" label="环境变量名称">
      <el-input v-model="environmentName" placeholder="SMTP_PASSWORD" />
    </el-form-item>
    <p v-if="error" class="text-red-700 mt-1">{{ error }}</p>
  </section>
</template>
