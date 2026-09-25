<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { FormInstance } from 'element-plus'
import type { SchemaCapability } from '@/shared/schema/types'
import type { SourceConfig, SourceSaveTarget } from '../model/types'
import type { SourceEditorController } from '../composables/useSourceEditor'
import type { CredentialProtector } from '../model/types'
import SourceBasicFields from './SourceBasicFields.vue'
import SourceCollectionFields from './SourceCollectionFields.vue'
import SourceProcessingFields from './SourceProcessingFields.vue'
import SourceAdvancedFields from './SourceAdvancedFields.vue'
const props = defineProps<{
  editor: SourceEditorController
  target: SourceSaveTarget
  initial: boolean
  capabilities: readonly SchemaCapability[]
  protect: CredentialProtector
}>()
const emit = defineEmits<{ saved: [value: SourceConfig]; cancel: [] }>()
const form = ref<FormInstance>()
const collection = ref<InstanceType<typeof SourceCollectionFields>>()
const value = computed(() => props.editor.value.value)
const capability = computed(() =>
  props.capabilities.find((item) => item.name === value.value?.collector),
)
async function submit() {
  const result = await props.editor.submit(async () => {
    await collection.value?.prepare()
    await nextTick()
    return (await form.value?.validate(() => {})) ?? false
  })
  if (result.status === 'success') emit('saved', result.value)
}
</script>
<template>
  <el-alert
    v-if="editor.save.error.value"
    :title="editor.save.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-form
    v-if="value"
    ref="form"
    novalidate
    :model="value"
    :disabled="editor.save.pending.value"
    label-position="top"
    @submit.prevent.stop="submit"
  >
    <SourceBasicFields
      :value="value"
      :initial="initial"
      :independent="target.kind === 'workflow-draft'"
      :capabilities="capabilities"
      @basic="editor.updateBasic"
      @id="editor.updateId"
      @collector="
        editor.selectCollector(
          $event,
          capabilities.find((item) => item.name === $event),
        )
      "
    />
    <SourceCollectionFields
      :key="value.collector"
      ref="collection"
      :value="value.options"
      :capability="capability"
      :independent="target.kind === 'workflow-draft'"
      :protect="protect"
      @change="editor.updateOptions"
    />
    <SourceProcessingFields
      :key="'setters-' + value.collector"
      :value="value.setters"
      :schema="capability?.setters_schema ?? undefined"
      @change="editor.updateSetters"
    />
    <SourceAdvancedFields :value="value" @change="editor.updateAdvanced" />
    <div class="flex justify-end gap-3">
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" native-type="submit" :loading="editor.save.pending.value">
        {{ target.kind === 'workflow-draft' ? '应用到当前工作流' : '保存资源' }}
      </el-button>
    </div>
  </el-form>
</template>
