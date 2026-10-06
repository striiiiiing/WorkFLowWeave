<script setup lang="ts">
import { ref } from 'vue'
import { useResourceTransport } from '../composables/useResourceTransport'
import type { Credential, MCPServerConfig } from '../model/public'
import { createResource } from '../model/public'
import {
  mcpExample,
  parseMcpConfig,
  resourceToMcpConfig,
  serverToResource,
} from '../model/mcp/import'

const props = defineProps<{ initial?: MCPServerConfig }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()
const api = useResourceTransport()
const draft = ref<MCPServerConfig>(
  structuredClone(props.initial ?? (createResource('mcp_servers') as MCPServerConfig)),
)
const argsText = ref(draft.value.args.join('\n'))
const envText = ref(JSON.stringify(draft.value.env, null, 2))
const headersText = ref(JSON.stringify(draft.value.headers, null, 2))
const jsonMode = ref(false)
const jsonText = ref(
  JSON.stringify(props.initial ? resourceToMcpConfig(draft.value) : mcpExample(), null, 2),
)
const error = ref('')
const pending = ref(false)
function syncFieldDraft(value: MCPServerConfig) {
  draft.value = value
  argsText.value = value.args.join('\n')
  envText.value = JSON.stringify(value.env, null, 2)
  headersText.value = JSON.stringify(value.headers, null, 2)
}
function toggleJsonMode() {
  error.value = ''
  if (jsonMode.value) {
    try {
      const config = parseMcpConfig(jsonText.value)
      const entries = Object.entries(config.servers)
      if (entries.length === 1) {
        syncFieldDraft(serverToResource(entries[0][0], entries[0][1], draft.value))
      }
      jsonMode.value = false
    } catch (cause) {
      error.value = String(cause)
    }
    return
  }
  jsonText.value = JSON.stringify(
    props.initial ? resourceToMcpConfig(draft.value) : mcpExample(),
    null,
    2,
  )
  jsonMode.value = true
}
async function save() {
  error.value = ''
  pending.value = true
  try {
    if (jsonMode.value) {
      const config = parseMcpConfig(jsonText.value)
      const entries = Object.entries(config.servers)
      if (props.initial) {
        if (entries.length !== 1 || entries[0][0] !== props.initial.id) {
          throw new Error('编辑已有 MCP 服务时，JSON 必须只包含当前服务名称。')
        }
        await api.replace(
          'mcp_servers',
          props.initial.id,
          serverToResource(entries[0][0], entries[0][1], draft.value),
        )
      } else {
        await api.importMcpServers(config)
      }
      emit('saved')
      return
    }
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
    <div class="flex justify-end mb-4">
      <el-button native-type="button" @click="toggleJsonMode">
        {{ jsonMode ? '填写参数' : '编辑 JSON' }}
      </el-button>
    </div>
    <template v-if="jsonMode">
      <el-form-item label="MCP 配置 JSON">
        <el-input v-model="jsonText" type="textarea" :rows="14" />
      </el-form-item>
    </template>
    <template v-else>
      <el-form-item label="服务名称">
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
    </template>
    <el-form-item label="连接超时 / 秒">
      <el-input-number v-model="draft.timeout" :min="0.001" :step="0.001" />
    </el-form-item>
    <el-form-item label="自动探测">
      <el-switch
        v-model="draft.health_check_enabled"
        active-text="开启"
        inactive-text="关闭"
      />
    </el-form-item>
    <el-form-item v-if="draft.health_check_enabled" label="探测间隔 / 分钟">
      <el-input-number
        v-model="draft.health_check_interval_minutes"
        :min="1"
        :step="1"
        controls-position="right"
      />
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
