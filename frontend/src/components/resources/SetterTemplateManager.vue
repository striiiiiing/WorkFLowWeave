<script setup lang="ts">
import { computed, ref, toRaw } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import { generatedResourceId } from '@/domain/resources'
import { idRule } from '@/domain/forms'
import ParameterField from '@/components/common/ParameterField.vue'
import type { JsonObject, SetterTemplate } from '@/types'

const props = withDefaults(
  defineProps<{
    collector: string
    modelValue: string | null
    schema?: JsonObject | null
    anonymous?: boolean
  }>(),
  { anonymous: true },
)
const emit = defineEmits<{ 'update:modelValue': [value: string | null]; changed: [] }>()
const templates = ref<SetterTemplate[]>([])
const error = ref('')
const dialog = ref(false)
const editing = ref<SetterTemplate | undefined>()
const draft = ref<SetterTemplate>({ id: '', collector: props.collector, setters: {} })
const form = ref<FormInstance>()
const selected = computed(() => templates.value.find((item) => item.id === props.modelValue))

async function load() {
  try {
    templates.value = await resourcesApi.list('setters')
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
void load()
function openCreate() {
  editing.value = undefined
  draft.value = {
    id: generatedResourceId(`${props.collector || 'template'}_template`),
    collector: props.collector,
    setters: {},
  }
  dialog.value = true
}
function openEdit() {
  if (!selected.value) return
  editing.value = selected.value
  draft.value = structuredClone(toRaw(selected.value))
  dialog.value = true
}
async function save() {
  if (!(await form.value?.validate(() => {}))) return
  const value = structuredClone(toRaw(draft.value))
  try {
    const result = editing.value
      ? await resourcesApi.replace('setters', editing.value.id, value)
      : await resourcesApi.create('setters', value)
    await load()
    emit('update:modelValue', result.id)
    emit('changed')
    dialog.value = false
    ElMessage.success('处理模板已保存')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
async function remove() {
  if (!selected.value) return
  try {
    await resourcesApi.delete('setters', selected.value.id)
    emit('update:modelValue', null)
    await load()
    emit('changed')
    ElMessage.success('处理模板已删除')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
</script>
<template>
  <el-form-item label="处理模板">
    <div class="flex flex-wrap gap-2 w-full">
      <el-select
        :model-value="modelValue"
        clearable
        filterable
        class="flex-1"
        placeholder="选择处理模板"
        @update:model-value="$emit('update:modelValue', $event || null)"
      >
        <el-option v-if="anonymous" value="" label="匿名处理模板（仅本次使用）" />
        <el-option
          v-for="item in templates.filter((item) => item.collector === collector)"
          :key="item.id"
          :value="item.id"
          :label="item.id"
        />
      </el-select>
      <el-button @click="openCreate">添加</el-button>
      <el-button :disabled="!selected" @click="openEdit">编辑</el-button>
      <el-popconfirm v-if="selected" title="确认删除此处理模板？" @confirm="remove">
        <template #reference><el-button type="danger" plain>删除</el-button></template>
      </el-popconfirm>
    </div>
    <p class="muted text-sm mt-1">
      留空则使用数据源默认处理模板；需要临时规则时可直接编辑下方匿名处理规则。
    </p>
    <p v-if="error" class="text-red-500 text-sm mt-1">{{ error }}</p>
  </el-form-item>
  <el-dialog
    v-model="dialog"
    :title="editing ? '编辑处理模板' : '添加处理模板'"
    width="620px"
    append-to-body
  >
    <el-form ref="form" :model="draft" label-position="top" @submit.prevent="save">
      <el-form-item label="模板编号" prop="id" :rules="idRule">
        <el-input v-model="draft.id" :disabled="!!editing" />
      </el-form-item>
      <ParameterField
        v-model="draft.setters"
        prop="setters"
        label="处理规则"
        :schema="schema ?? undefined"
      />
      <div class="flex justify-end gap-2">
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存模板</el-button>
      </div>
    </el-form>
  </el-dialog>
</template>
