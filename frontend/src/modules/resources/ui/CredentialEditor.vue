<script setup lang="ts">
import type { Credential } from '../model/public'
import type { CredentialProtector } from '../model/public'
import { useCredentialEditor } from '../composables/useCredentialEditor'
const props = withDefaults(
  defineProps<{ modelValue: Credential | null; label?: string; protect: CredentialProtector }>(),
  { label: '凭据' },
)
const emit = defineEmits<{ 'update:modelValue': [value: Credential | null] }>()
const { mode, plaintext, environmentName, error, prepare } = useCredentialEditor(
  props,
  emit,
  props.protect,
)
defineExpose({ prepare })
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
