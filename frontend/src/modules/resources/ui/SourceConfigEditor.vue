<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ParameterField from '@/shared/schema/ParameterField.vue'
import { useResourcesApi } from '../api/dependencies'
import type { MCPServerConfig, SourceCall, SourceConfig, SourceSaveTarget } from '../model/types'
import type { MCPToolCatalog, MCPToolDescription } from '../api/resourcesApi'
import type { SourceEditorController } from '../composables/useSourceEditor'
import SourceAdvancedFields from './SourceAdvancedFields.vue'

const props = defineProps<{
  editor: SourceEditorController
  target: SourceSaveTarget
  initial: boolean
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
const api = useResourcesApi()
const value = computed(() => props.editor.value.value)
const servers = ref<MCPServerConfig[]>([])
const catalog = ref<MCPToolCatalog>()
const description = ref<MCPToolDescription>()
const catalogError = ref('')
const loading = ref(false)
const argvText = ref('')
const selectedState = computed(() =>
  catalog.value?.servers.find(
    (item) => item.server === (value.value?.call.kind === 'mcp' ? value.value.call.server : ''),
  ),
)

async function loadServers() {
  try {
    servers.value = await api.list('mcp_servers')
  } catch (error) {
    catalogError.value = String(error)
  }
}
async function loadCatalog(server: string, refresh = false) {
  if (!server) return
  loading.value = true
  catalogError.value = ''
  try {
    if (refresh) await api.loadMcpCatalog(server, true)
    let page = await api.mcpCatalog(server)
    const entries = [...page.entries]
    while (page.next_cursor !== null) {
      page = await api.mcpCatalog(server, '', page.next_cursor)
      entries.push(...page.entries)
    }
    catalog.value = { ...page, entries }
  } catch (error) {
    catalogError.value = String(error)
  } finally {
    loading.value = false
  }
}
async function describe(server: string, tool: string) {
  description.value = undefined
  if (!server || !tool) return
  try {
    description.value = await api.describeMcpTool(server, tool)
    if (catalog.value?.load_servers.includes(server)) await loadCatalog(server)
  } catch (error) {
    catalogError.value = String(error)
  }
}
watch(
  () => value.value?.call,
  (call) => {
    if (!call) return
    if (call.kind === 'cli' && call.mode === 'argv') argvText.value = call.argv.join('\n')
  },
  { immediate: true },
)
watch(
  () => (value.value?.call?.kind === 'mcp' ? value.value.call.server : ''),
  (server) => {
    catalog.value = undefined
    description.value = undefined
    if (server) void loadCatalog(server)
  },
  { immediate: true },
)
watch(
  () =>
    value.value?.call?.kind === 'mcp' ? `${value.value.call.server}\0${value.value.call.tool}` : '',
  () => {
    const call = value.value?.call
    if (call?.kind === 'mcp' && call.tool) void describe(call.server, call.tool)
  },
  { immediate: true },
)
void loadServers()

function setCall(change: Partial<SourceCall>) {
  if (!value.value) return
  props.editor.updateCall({ ...value.value.call, ...change } as SourceCall)
}
function switchKind(kind: 'mcp' | 'cli') {
  props.editor.updateCall(
    kind === 'mcp'
      ? { kind: 'mcp', server: '', tool: '', arguments: {} }
      : { kind: 'cli', mode: 'argv', executable: '', argv: [], cwd: null },
  )
}
function switchMode(mode: 'argv' | 'shell') {
  const cwd = value.value?.call.kind === 'cli' ? value.value.call.cwd : null
  props.editor.updateCall(
    mode === 'argv'
      ? { kind: 'cli', mode, executable: '', argv: [], cwd }
      : { kind: 'cli', mode, command: '', cwd },
  )
}
function updateArgvText(text: string) {
  argvText.value = text
  setCall({ argv: text ? text.split('\n') : [] })
}
async function submit() {
  const result = await props.editor.submit(async () => {
    const source = value.value
    if (!source) return false
    if (source.call.kind === 'mcp') return !!source.call.server && !!source.call.tool
    return source.call.mode === 'argv' ? !!source.call.executable : !!source.call.command
  })
  if (result.status === 'success') emit('saved', result.value)
}
</script>
<template>
  <el-form v-if="value" novalidate :model="value" label-position="top" @submit.prevent="submit">
    <el-alert
      v-if="editor.save.error.value"
      :title="editor.save.error.value"
      type="error"
      :closable="false"
    />
    <div class="form-grid">
      <el-form-item label="数据源名称">
        <el-input
          :model-value="value.display_name"
          @update:model-value="editor.updateBasic({ display_name: $event })"
        />
      </el-form-item>
      <el-form-item label="资源编号">
        <el-input
          :model-value="value.id"
          :disabled="initial"
          @update:model-value="editor.updateId($event)"
        />
      </el-form-item>
    </div>
    <el-form-item label="用途说明">
      <el-input
        :model-value="value.description"
        @update:model-value="editor.updateBasic({ description: $event })"
      />
    </el-form-item>
    <el-form-item label="来源方式">
      <el-radio-group
        :model-value="value.call.kind"
        @update:model-value="switchKind($event as 'mcp' | 'cli')"
      >
        <el-radio-button value="mcp">MCP</el-radio-button>
        <el-radio-button value="cli">CLI</el-radio-button>
      </el-radio-group>
    </el-form-item>
    <template v-if="value.call.kind === 'mcp'">
      <div class="form-grid">
        <el-form-item label="MCP 服务">
          <el-select
            :model-value="value.call.server"
            filterable
            @update:model-value="setCall({ server: $event, tool: '', arguments: {} })"
          >
            <el-option
              v-for="server in servers"
              :key="server.id"
              :label="server.id"
              :value="server.id"
              :disabled="!server.enabled"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="工具">
          <el-select
            :model-value="value.call.tool"
            filterable
            @update:model-value="setCall({ tool: $event, arguments: {} })"
          >
            <el-option
              v-for="tool in catalog?.entries ?? []"
              :key="tool.tool"
              :label="tool.tool"
              :value="tool.tool"
            />
          </el-select>
        </el-form-item>
      </div>
      <el-alert
        v-if="catalogError || selectedState?.state === 'failed'"
        :title="catalogError || selectedState?.error || '目录加载失败'"
        type="error"
        :closable="false"
      />
      <p v-else-if="catalog?.load_servers.includes(value.call.server)" class="muted">
        目录尚未加载。
      </p>
      <p v-else-if="catalog && !catalog.entries.length" class="muted">该服务没有可用工具。</p>
      <el-button
        v-if="value.call.server"
        :loading="loading"
        @click="loadCatalog(value.call.server, true)"
      >
        加载/刷新目录
      </el-button>
      <ParameterField
        v-if="description"
        :model-value="value.call.arguments"
        prop="arguments"
        label="工具参数"
        :schema="description.inputSchema"
        @update:model-value="setCall({ arguments: $event })"
      />
      <p v-else-if="value.call.tool" class="muted text-sm">
        工具 schema 尚未加载；已保存参数保持不变。
      </p>
    </template>
    <template v-else>
      <el-form-item label="执行方式">
        <el-radio-group
          :model-value="value.call.mode"
          @update:model-value="switchMode($event as 'argv' | 'shell')"
        >
          <el-radio-button value="argv">参数数组</el-radio-button>
          <el-radio-button value="shell">Shell 命令</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <template v-if="value.call.mode === 'argv'">
        <el-form-item label="可执行文件">
          <el-input
            :model-value="value.call.executable"
            @update:model-value="setCall({ executable: $event })"
          />
        </el-form-item>
        <el-form-item label="参数（每行一项）">
          <el-input
            :model-value="argvText"
            type="textarea"
            :rows="4"
            @update:model-value="updateArgvText"
          />
        </el-form-item>
      </template>
      <el-form-item v-else label="命令">
        <el-input
          :model-value="value.call.command"
          type="textarea"
          :rows="3"
          @update:model-value="setCall({ command: $event })"
        />
      </el-form-item>
      <el-form-item label="工作目录">
        <el-input
          :model-value="value.call.cwd ?? ''"
          @update:model-value="setCall({ cwd: $event || null })"
        />
      </el-form-item>
    </template>
    <SourceAdvancedFields :value="value" @change="editor.updateAdvanced" />
    <div class="flex justify-between mt-6">
      <el-switch
        :model-value="value.enabled"
        active-text="启用数据源"
        @update:model-value="editor.updateBasic({ enabled: Boolean($event) })"
      />
      <div>
        <el-button @click="emit('cancel')">取消</el-button>
        <el-button
          type="primary"
          native-type="submit"
          formnovalidate
          :loading="editor.save.pending.value"
        >
          {{ target.kind === 'workflow-draft' ? '应用到当前工作流' : '保存资源' }}
        </el-button>
      </div>
    </div>
  </el-form>
</template>
