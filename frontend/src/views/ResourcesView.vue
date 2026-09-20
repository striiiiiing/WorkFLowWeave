<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { resourcesApi } from '@/api/resources'
import {
  resourceKinds,
  resourceNames,
  type EditableKind,
  type EditableResource,
} from '@/domain/resources'
import { useQuery } from '@/composables/useQuery'
import { useAsyncTask } from '@/composables/useAsyncTask'
import PageHeader from '@/components/common/PageHeader.vue'
import AppIcon from '@/components/icons/AppIcon.vue'
import ResourceEditor from '@/components/resources/ResourceEditor.vue'
const kind = ref<EditableKind>('sources')
const { data, pending, error, refresh } = useQuery(
  (signal) => resourcesApi.list(kind.value, signal),
  [kind],
)
const action = useAsyncTask()
const connection = useAsyncTask()
function checkConnection(id: string) {
  void connection.run(async () => {
    const models = await resourcesApi.checkAIConnection(id)
    ElMessage.success(`连接成功，发现 ${models.length} 个模型`)
  })
}
const editor = ref<{ kind: EditableKind; initial?: EditableResource }>()
const dialog = ref(false)
function open(initial?: EditableResource) {
  editor.value = { kind: kind.value, initial }
  dialog.value = true
}
function remove(id: string) {
  const target = kind.value
  void action.run(async () => {
    await resourcesApi.delete(target, id)
    await refresh()
  })
}
function saved() {
  dialog.value = false
  void refresh()
}
</script>
<template>
  <PageHeader title="资源配置中心" description="管理可复用的数据源、处理模板、AI 模型与通知渠道">
    <el-button :loading="pending" @click="refresh">刷新</el-button>
    <el-button type="primary" @click="open()">添加{{ resourceNames[kind] }}</el-button>
  </PageHeader>
  <el-alert
    v-if="error || action.error.value || connection.error.value"
    :title="error || action.error.value || connection.error.value"
    type="error"
    :closable="false"
    show-icon
  />
  <el-card shadow="never">
    <el-tabs v-model="kind">
      <el-tab-pane
        v-for="category in resourceKinds"
        :key="category.key"
        :name="category.key"
        :label="category.label"
      />
    </el-tabs>
    <div v-loading="pending" class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <el-card v-for="resource in data" :key="resource.id" shadow="never">
        <div class="flex items-start gap-3">
          <AppIcon :name="resourceKinds.find((item) => item.key === kind)!.icon" />
          <div class="min-w-0">
            <h2 class="font-semibold mono break-all">{{ resource.id }}</h2>
            <p class="muted text-sm mt-2">
              {{
                'collector' in resource
                  ? resource.collector
                  : 'provider' in resource
                    ? resource.provider
                    : resource.channel
              }}
            </p>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <el-button
            v-if="kind === 'ai'"
            :loading="connection.pending.value"
            @click="checkConnection(resource.id)"
          >
            检查连接
          </el-button>
          <el-button @click="open(resource)">编辑</el-button>
          <el-popconfirm title="确认删除此资源？" @confirm="remove(resource.id)">
            <template #reference>
              <el-button type="danger" plain :disabled="action.pending.value">删除</el-button>
            </template>
          </el-popconfirm>
        </div>
      </el-card>
    </div>
    <el-empty v-if="!pending && !error && !data?.length" description="此分类暂无资源" />
  </el-card>
  <el-dialog
    v-model="dialog"
    :title="(editor?.initial ? '编辑' : '添加') + resourceNames[editor?.kind ?? kind]"
    width="680px"
    destroy-on-close
  >
    <ResourceEditor
      v-if="editor && dialog"
      :kind="editor.kind"
      :initial="editor.initial"
      @saved="saved"
      @cancel="dialog = false"
    />
  </el-dialog>
</template>
