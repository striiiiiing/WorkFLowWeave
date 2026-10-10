<script setup lang="ts">
import { ref, shallowRef } from 'vue'
import type { FileCall } from '../model/public'
import { useResourceTransport } from '../composables/useResourceTransport'

const props = defineProps<{ call: FileCall; existing: boolean; disabled?: boolean }>()
const emit = defineEmits<{ change: [value: FileCall] }>()
const api = useResourceTransport()
const fileType = ref<'text' | undefined>(props.existing ? props.call.file_type : undefined)
const inputText = ref(false)
const text = ref('')
const file = shallowRef<File>()
let created: { path: string; content: string | File } | undefined

function selectFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0]
}

async function prepare(): Promise<FileCall> {
  if (fileType.value !== 'text') throw new Error('请选择文件类型')
  if (!props.call.path) throw new Error('请填写相对保存位置')
  const content = inputText.value ? text.value : file.value
  if (content === undefined) return props.call
  if (created?.path === props.call.path && created.content === content) return props.call
  const reference =
    typeof content === 'string'
      ? await api.createTextReference(props.call.path, content)
      : await api.importTextReference(props.call.path, content)
  created = { path: reference.path, content }
  return reference
}

defineExpose({ prepare })
</script>

<template>
  <el-form-item label="文件类型" required>
    <el-select v-model="fileType" aria-label="文件类型" placeholder="选择文件类型">
      <el-option label="文本" value="text" />
    </el-select>
  </el-form-item>
  <el-form-item label="相对保存位置" required>
    <el-input
      :model-value="call.path"
      aria-label="相对保存位置"
      @update:model-value="emit('change', { ...call, path: $event })"
    />
  </el-form-item>
  <el-form-item>
    <el-checkbox v-model="inputText">输入文本</el-checkbox>
  </el-form-item>
  <el-form-item v-if="inputText" label="文本正文">
    <el-input v-model="text" type="textarea" :rows="8" aria-label="文本正文" />
  </el-form-item>
  <el-form-item v-else label="添加文件">
    <input
      type="file"
      :disabled="disabled"
      accept="text/*,.txt,.md,.log,.json,.csv,.yaml,.yml,.xml"
      aria-label="导入文本文件"
      class="reference-file-input"
      @change="selectFile"
    />
  </el-form-item>
</template>

<style scoped>
.reference-file-input {
  width: 100%;
  min-width: 0;
  font: inherit;
}
</style>
