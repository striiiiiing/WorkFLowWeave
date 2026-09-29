<script setup lang="ts">
import { ref } from 'vue'
import { useResourceTransport } from '../composables/useResourceTransport'
import type { Credential, MCPServerConfig } from '../model/types'
import { createResource } from '../model/resources'

const props = defineProps<{ initial?: MCPServerConfig }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()
const api = useResourceTransport()
const draft = ref<MCPServerConfig>(
  structuredClone(props.initial ?? (createResource('mcp_servers') as MCPServerConfig)),
)
const argsText = ref(draft.value.args.join('\n'))
const envText = ref(JSON.stringify(draft.value.env, null, 2))
const headersText = ref(JSON.stringify(draft.value.headers, null, 2))
const error = ref('')
const pending = ref(false)
async function save() {
  error.value = ''
  pending.value = true
  try {
    draft.value.args = argsText.value ? argsText.value.split('\n') : []
    draft.value.env = JSON.parse(envText.value) as Record<string, Credential>
    draft.value.headers = JSON.parse(headersText.value) as Record<string, Credential>
    const value = draft.value
    if (value.transport === 'stdio') {
      value.url = null
      value.headers = {}
    } else {
      value.command = null
      value.args = []
      value.cwd = null
      value.env = {}
    }
    if (props.initial) await api.replace('mcp_servers', props.initial.id, value)
    else await api.create('mcp_servers', value)
    emit('saved')
  } catch (cause) {
    error.value = String(cause)
  } finally {
    pending.value = false
  }
}
</script>
<template>
  <el-form novalidate label-position="top" @submit.prevent="save">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form-item label="服务 ID">
      <el-input v-model="draft.id" :disabled="!!initial" />
    </el-form-item>
    <el-form-item label="传输方式">
      <el-select v-model="draft.transport">
        <el-option value="stdio" label="stdio" />
        <el-option value="streamable_http" label="Streamable HTTP" />
        <el-option value="sse" label="SSE" />
      </el-select>
    </el-form-item>
    <template v-if="draft.transport === 'stdio'">
      <el-form-item label="可执行文件"><el-input v-model="draft.command" /></el-form-item>
      <el-form-item label="参数（每行一项）">
        <el-input v-model="argsText" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="工作目录"><el-input v-model="draft.cwd" /></el-form-item>
      <el-form-item label="环境凭据引用（JSON 对象）">
        <el-input v-model="envText" type="textarea" :rows="3" />
      </el-form-item>
    </template>
    <template v-else>
      <el-form-item label="服务 URL"><el-input v-model="draft.url" /></el-form-item>
      <el-form-item label="Header 凭据引用（JSON 对象）">
        <el-input v-model="headersText" type="textarea" :rows="3" />
      </el-form-item>
    </template>
    <el-form-item label="连接超时 / 秒">
      <el-input-number v-model="draft.timeout" :min="0.001" :step="0.001" />
    </el-form-item>
    <el-switch v-model="draft.enabled" active-text="启用服务" />
    <div class="flex justify-end gap-2 mt-5">
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" native-type="submit" formnovalidate :loading="pending">
        保存
      </el-button>
    </div>
  </el-form>
</template>
