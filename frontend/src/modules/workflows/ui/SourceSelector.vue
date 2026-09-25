<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SourceConfig } from '@/modules/resources/public'

const props = defineProps<{
  open: boolean
  sources: readonly SourceConfig[]
  currentIds: readonly string[]
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  add: [ids: readonly string[]]
}>()
const selected = ref<string[]>([])

watch(
  () => props.open,
  (open) => {
    if (open) selected.value = []
  },
)
function close() {
  emit('update:open', false)
}
function confirm() {
  emit('add', selected.value)
  close()
}
</script>

<template>
  <el-dialog
    :model-value="open"
    title="加载已有数据源"
    width="min(94vw, 640px)"
    append-to-body
    @update:model-value="emit('update:open', $event)"
  >
    <p class="muted mb-4">加载后跟随资源配置中心；已有数据源不会重复添加。</p>
    <el-select
      v-model="selected"
      multiple
      filterable
      placeholder="选择数据源"
      aria-label="选择数据源"
    >
      <el-option
        v-for="source in sources"
        :key="source.id"
        :value="source.id"
        :label="source.display_name || source.id"
        :disabled="!source.enabled || currentIds.includes(source.id)"
      />
    </el-select>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :disabled="!selected.length" @click="confirm">
        加入当前工作流
      </el-button>
    </template>
  </el-dialog>
</template>
