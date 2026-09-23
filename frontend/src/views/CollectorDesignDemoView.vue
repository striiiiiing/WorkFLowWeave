<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/icons/AppIcon.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { JsonObject } from '@/types'

type CollectorKey = 'logs' | 'rss' | 'history'
type ResourceStatus = 'enabled' | 'paused'
type EditorMode = 'form' | 'json'

interface CollectorCatalogItem {
  key: CollectorKey
  label: string
  description: string
  fields: string
  icon: 'database' | 'workflow' | 'settings'
  tone: string
}

interface RuleForm {
  fields: string
  filter: string
  sortBy: string
  groupBy: string
  format: string
  descending: boolean
}

interface ProcessingTemplate {
  id: string
  name: string
  collector: CollectorKey
  description: string
  updatedAt: string
  rules: JsonObject
}

interface CollectorInstance {
  id: string
  name: string
  collector: CollectorKey
  status: ResourceStatus
  summary: string
  options: {
    path: string
    apiKey: string
    maxLines: number
  }
  templateId: string | null
  localRules: JsonObject
  timeout: number
}

const collectorCatalog: CollectorCatalogItem[] = [
  {
    key: 'logs',
    label: '运行日志',
    description: '读取 LogAgent 诊断日志，适合监控错误、告警和运行状态。',
    fields: 'message · level · module · session',
    icon: 'database',
    tone: '#2563eb',
  },
  {
    key: 'rss',
    label: 'RSS 订阅',
    description: '读取订阅源的新内容，适合定时跟踪固定信息源。',
    fields: 'title · link · published · summary',
    icon: 'workflow',
    tone: '#0f766e',
  },
  {
    key: 'history',
    label: '历史运行',
    description: '读取历史工作流结果，用于对比、复盘和二次分析。',
    fields: 'workflow · status · created_at · content',
    icon: 'settings',
    tone: '#c2410c',
  },
]

const instances = ref<CollectorInstance[]>([
  {
    id: 'logs_daily',
    name: '每日运行日志',
    collector: 'logs',
    status: 'enabled',
    summary: '最近 24 小时 · 过滤 error / warning',
    options: { path: '/var/log/logagent/app.jsonl', apiKey: '', maxLines: 500 },
    templateId: 'tpl-log-alerts',
    localRules: { descending: true },
    timeout: 60,
  },
  {
    id: 'rss_product',
    name: '产品更新订阅',
    collector: 'rss',
    status: 'enabled',
    summary: '3 个订阅源 · 只保留最近 7 天',
    options: { path: 'https://example.com/feed.xml', apiKey: '', maxLines: 100 },
    templateId: 'tpl-rss-brief',
    localRules: {},
    timeout: 45,
  },
  {
    id: 'history_weekly',
    name: '每周结果复盘',
    collector: 'history',
    status: 'paused',
    summary: '最近 10 次运行 · 保留最终报告',
    options: { path: 'weekly-report', apiKey: '', maxLines: 10 },
    templateId: null,
    localRules: { fields: ['workflow_name', 'status', 'content'] },
    timeout: 90,
  },
])

const templates = ref<ProcessingTemplate[]>([
  {
    id: 'tpl-log-alerts',
    name: '错误与告警摘要',
    collector: 'logs',
    description: '保留错误上下文，并按时间倒序排列。',
    updatedAt: '今天 09:42',
    rules: {
      fields: ['level', 'module', 'message', 'session'],
      filter: { level: ['error', 'warning'] },
      sort_by: 'created_at',
      descending: true,
      format: 'markdown',
    },
  },
  {
    id: 'tpl-rss-brief',
    name: '简报输入',
    collector: 'rss',
    description: '只把标题、时间和摘要交给后续分析。',
    updatedAt: '昨天 18:10',
    rules: {
      fields: ['title', 'published', 'summary', 'link'],
      filter: { published_within_days: 7 },
      sort_by: 'published',
      descending: true,
      format: 'markdown',
    },
  },
  {
    id: 'tpl-history-diff',
    name: '复盘对比',
    collector: 'history',
    description: '提取运行状态和最终正文，便于周期性比较。',
    updatedAt: '2026-09-21',
    rules: {
      fields: ['workflow_name', 'status', 'created_at', 'content'],
      filter: { status: ['completed', 'partial'] },
      sort_by: 'created_at',
      descending: false,
      format: 'markdown',
    },
  },
])

const search = ref('')
const collectorFilter = ref<'all' | CollectorKey>('all')
const selectedInstanceId = ref('logs_daily')
const templateManagerOpen = ref(false)
const templateTypeFilter = ref<'all' | CollectorKey>('all')
const selectedTemplateId = ref('tpl-log-alerts')
const templateDraft = ref<ProcessingTemplate | null>(null)
const templateMode = ref<EditorMode>('form')
const templateJson = ref('')
const templateRuleForm = ref<RuleForm>(emptyRuleForm())
const instanceDrawerOpen = ref(false)
const instanceDraft = ref<CollectorInstance | null>(null)
const instanceMode = ref<EditorMode>('form')
const instanceJson = ref('')
const instanceRuleForm = ref<RuleForm>(emptyRuleForm())
const workflowOverrideEnabled = ref(false)
const workflowTemplateId = ref('')
const workflowMode = ref<EditorMode>('form')
const workflowJson = ref('')
const workflowRuleForm = ref<RuleForm>(emptyRuleForm())

function emptyRuleForm(): RuleForm {
  return { fields: '', filter: '', sortBy: '', groupBy: '', format: 'markdown', descending: false }
}

function catalogItem(key: CollectorKey) {
  return collectorCatalog.find((item) => item.key === key) ?? collectorCatalog[0]
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function displayRules(rules: JsonObject) {
  return JSON.stringify(rules, null, 2)
}

function formFromRules(rules: JsonObject): RuleForm {
  const filter = rules.filter
  return {
    fields: Array.isArray(rules.fields) ? rules.fields.join(', ') : '',
    filter: filter && typeof filter === 'object' ? JSON.stringify(filter) : '',
    sortBy: typeof rules.sort_by === 'string' ? rules.sort_by : '',
    groupBy: typeof rules.group_by === 'string' ? rules.group_by : '',
    format: typeof rules.format === 'string' ? rules.format : 'markdown',
    descending: rules.descending === true,
  }
}

function rulesFromForm(form: RuleForm): JsonObject {
  const rules: JsonObject = {}
  const fields = form.fields
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  if (fields.length) rules.fields = fields
  if (form.filter.trim()) {
    try {
      rules.filter = JSON.parse(form.filter)
    } catch {
      rules.filter = form.filter
    }
  }
  if (form.sortBy.trim()) rules.sort_by = form.sortBy.trim()
  if (form.groupBy.trim()) rules.group_by = form.groupBy.trim()
  if (form.format) rules.format = form.format
  if (form.descending) rules.descending = true
  return rules
}

const selectedInstance = computed(
  () => instances.value.find((item) => item.id === selectedInstanceId.value) ?? instances.value[0],
)
const selectedCatalog = computed(() => catalogItem(selectedInstance.value?.collector ?? 'logs'))
const filteredInstances = computed(() => {
  const query = search.value.trim().toLowerCase()
  return instances.value.filter((instance) => {
    const matchesType = collectorFilter.value === 'all' || instance.collector === collectorFilter.value
    const matchesSearch =
      !query || `${instance.name} ${instance.id} ${catalogItem(instance.collector).label}`.toLowerCase().includes(query)
    return matchesType && matchesSearch
  })
})
const visibleTemplates = computed(() =>
  templates.value.filter(
    (template) => templateTypeFilter.value === 'all' || template.collector === templateTypeFilter.value,
  ),
)
const instanceTemplates = computed(() =>
  templates.value.filter((template) => template.collector === instanceDraft.value?.collector),
)
const instanceTemplate = computed(() =>
  templates.value.find(
    (template) =>
      template.id === instanceDraft.value?.templateId && template.collector === instanceDraft.value?.collector,
  ),
)
const templateUsage = computed(() =>
  instances.value.filter((instance) => instance.templateId === templateDraft.value?.id),
)
const workflowTemplate = computed(() =>
  templates.value.find((template) => template.id === workflowTemplateId.value),
)
const effectivePreviewRules = computed(() => {
  const base = selectedInstance.value?.templateId
    ? templates.value.find(
        (template) =>
          template.id === selectedInstance.value?.templateId &&
          template.collector === selectedInstance.value?.collector,
      )?.rules ?? {}
    : {}
  return { ...base, ...(selectedInstance.value?.localRules ?? {}) }
})

function openInstance(instance?: CollectorInstance) {
  const defaultCollector = collectorFilter.value === 'all' ? 'logs' : collectorFilter.value
  instanceDraft.value = clone(
    instance ?? {
      id: `collector_${Date.now()}`,
      name: '新的采集器实例',
      collector: defaultCollector,
      status: 'enabled',
      summary: '尚未配置处理规则',
      options: { path: '', apiKey: '', maxLines: 200 },
      templateId: null,
      localRules: {},
      timeout: 60,
    },
  )
  instanceRuleForm.value = formFromRules(instanceDraft.value.localRules)
  instanceJson.value = displayRules(instanceDraft.value.localRules)
  instanceMode.value = 'form'
  instanceDrawerOpen.value = true
}

function saveInstance() {
  if (!instanceDraft.value) return
  const localRules = readRules(instanceMode.value, instanceJson.value, instanceRuleForm.value)
  if (!localRules) return
  instanceDraft.value.localRules = localRules
  instanceDraft.value.summary = instanceTemplate.value
    ? `${instanceTemplate.value.name} · ${instanceDraft.value.options.maxLines} 条以内`
    : '尚未加载处理模板 · 可继续编辑本地规则'
  const index = instances.value.findIndex((item) => item.id === instanceDraft.value?.id)
  if (index === -1) instances.value.push(clone(instanceDraft.value))
  else instances.value[index] = clone(instanceDraft.value)
  selectedInstanceId.value = instanceDraft.value.id
  instanceDrawerOpen.value = false
  ElMessage.success('采集器实例已保存（演示数据）')
}

function readRules(mode: EditorMode, json: string, form: RuleForm): JsonObject | null {
  if (mode === 'form') return rulesFromForm(form)
  try {
    const parsed = JSON.parse(json)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    return parsed
  } catch {
    ElMessage.error('高级 JSON 必须是一个有效对象')
    return null
  }
}

function loadInstanceTemplate(templateId: string | null) {
  if (!instanceDraft.value) return
  instanceDraft.value.templateId = templateId || null
  const template = templates.value.find((item) => item.id === templateId)
  if (template) ElMessage.info(`已加载“${template.name}”，局部调整仍只属于当前实例`)
}

function openTemplateManager() {
  templateManagerOpen.value = true
  const first = visibleTemplates.value[0] ?? templates.value[0]
  if (first) selectTemplate(first.id)
}

function selectTemplate(id: string) {
  selectedTemplateId.value = id
  const template = templates.value.find((item) => item.id === id)
  if (!template) return
  templateDraft.value = clone(template)
  templateRuleForm.value = formFromRules(template.rules)
  templateJson.value = displayRules(template.rules)
  templateMode.value = 'form'
}

function createTemplate() {
  const collector = templateTypeFilter.value === 'all' ? 'logs' : templateTypeFilter.value
  const draft: ProcessingTemplate = {
    id: `template_${Date.now()}`,
    name: '新的处理模板',
    collector,
    description: '描述这份规则会保留哪些字段。',
    updatedAt: '刚刚',
    rules: {},
  }
  templates.value.push(draft)
  selectTemplate(draft.id)
  ElMessage.info('已创建模板草稿')
}

function saveTemplate() {
  if (!templateDraft.value) return
  const rules = readRules(templateMode.value, templateJson.value, templateRuleForm.value)
  if (!rules) return
  const usedBy = instances.value.filter((item) => item.templateId === templateDraft.value?.id)
  if (usedBy.some((item) => item.collector !== templateDraft.value?.collector)) {
    ElMessage.warning('该模板仍被其他采集器使用，不能更改为当前类型')
    return
  }
  templateDraft.value.rules = rules
  templateDraft.value.updatedAt = '刚刚'
  const index = templates.value.findIndex((item) => item.id === templateDraft.value?.id)
  if (index === -1) templates.value.push(clone(templateDraft.value))
  else templates.value[index] = clone(templateDraft.value)
  if (instanceDraft.value?.templateId === templateDraft.value.id) {
    instanceJson.value = displayRules(rules)
  }
  ElMessage.success('处理模板已保存（演示数据）')
}

async function changeInstanceCollector(collector: CollectorKey) {
  if (!instanceDraft.value) return
  const currentTemplate = templates.value.find((template) => template.id === instanceDraft.value?.templateId)
  if (currentTemplate && currentTemplate.collector !== collector) {
    try {
      await ElMessageBox.confirm(
        `当前实例使用“${currentTemplate.name}”，它仅适用于${catalogItem(currentTemplate.collector).label}。切换后将移除模板引用。`,
        '切换采集器类型',
        { confirmButtonText: '继续切换', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
    instanceDraft.value.templateId = null
    ElMessage.warning('采集器类型已切换，已移除不适用的处理模板')
  }
  instanceDraft.value.collector = collector
}

function removeTemplate() {
  if (!templateDraft.value) return
  const usedBy = instances.value.filter((item) => item.templateId === templateDraft.value?.id)
  if (usedBy.length) {
    ElMessage.warning(`该模板仍被 ${usedBy.length} 个采集器实例使用，演示中不允许删除`)
    return
  }
  templates.value = templates.value.filter((item) => item.id !== templateDraft.value?.id)
  const next = visibleTemplates.value[0] ?? templates.value[0]
  if (next) selectTemplate(next.id)
  else templateDraft.value = null
  ElMessage.success('处理模板已删除（演示数据）')
}

function openWorkflowOverride() {
  workflowOverrideEnabled.value = !workflowOverrideEnabled.value
  if (workflowOverrideEnabled.value) {
    workflowTemplateId.value = selectedInstance.value?.templateId ?? ''
    const rules = workflowTemplate.value?.rules ?? effectivePreviewRules.value
    workflowRuleForm.value = formFromRules(rules)
    workflowJson.value = displayRules(rules)
    workflowMode.value = 'form'
  }
}

function updateWorkflowTemplate(templateId: string) {
  workflowTemplateId.value = templateId
  const template = templates.value.find((item) => item.id === templateId)
  if (template) {
    workflowRuleForm.value = formFromRules(template.rules)
    workflowJson.value = displayRules(template.rules)
  }
}

function applyWorkflowOverride() {
  const rules = readRules(workflowMode.value, workflowJson.value, workflowRuleForm.value)
  if (!rules) return
  ElMessage.success('工作流本次覆盖已更新（演示数据）')
}

function statusLabel(status: ResourceStatus) {
  return status === 'enabled' ? '已启用' : '已停用'
}

function copyJson(value: JsonObject) {
  void navigator.clipboard?.writeText(displayRules(value))
  ElMessage.success('JSON 已复制')
}
</script>

<template>
  <PageHeader title="采集器配置" description="以采集器实例为主体，统一管理可复用的处理模板">
    <el-tag type="info" effect="plain" class="demo-tag">前端演示 · 本地状态</el-tag>
    <el-button @click="openTemplateManager">
      <AppIcon name="settings" size="sm" />
      <span>处理模板</span>
    </el-button>
    <el-button type="primary" @click="openInstance()">
      <AppIcon name="plus" size="sm" />
      <span>新增实例</span>
    </el-button>
  </PageHeader>

  <div class="demo-alert">
    <div class="alert-mark"><AppIcon name="settings" size="sm" /></div>
    <div>
      <strong>把连接配置和处理规则分开管理</strong>
      <p>实例保存“从哪里采集”，模板决定“采集后保留什么”。模板只能用于对应的采集器类型。</p>
    </div>
  </div>

  <div class="demo-layout">
    <section class="surface-panel instance-panel">
      <div class="panel-heading">
        <div>
          <div class="eyebrow">COLLECTOR INSTANCES</div>
          <h2>采集器实例 <span>{{ instances.length }}</span></h2>
        </div>
        <el-button text aria-label="刷新演示数据" @click="ElMessage.info('演示数据已是最新')">
          <AppIcon name="workflow" size="sm" />
        </el-button>
      </div>
      <div class="instance-toolbar">
        <el-input v-model="search" clearable placeholder="搜索实例名称或类型" class="search-input">
          <template #prefix><AppIcon name="database" size="sm" /></template>
        </el-input>
        <el-select v-model="collectorFilter" class="type-filter" aria-label="按采集器类型筛选">
          <el-option value="all" label="全部类型" />
          <el-option v-for="item in collectorCatalog" :key="item.key" :value="item.key" :label="item.label" />
        </el-select>
      </div>
      <div class="instance-list">
        <button
          v-for="instance in filteredInstances"
          :key="instance.id"
          type="button"
          class="instance-row"
          :class="{ selected: selectedInstance?.id === instance.id }"
          @click="selectedInstanceId = instance.id"
        >
          <span class="instance-icon" :style="{ color: catalogItem(instance.collector).tone }">
            <AppIcon :name="catalogItem(instance.collector).icon" />
          </span>
          <span class="instance-content">
            <span class="instance-title">
              <strong>{{ instance.name }}</strong>
              <el-tag v-if="instance.status === 'paused'" size="small" type="warning">已停用</el-tag>
            </span>
            <span class="instance-meta">{{ catalogItem(instance.collector).label }} · {{ instance.summary }}</span>
          </span>
          <span class="instance-chevron">›</span>
        </button>
        <el-empty v-if="!filteredInstances.length" description="没有匹配的采集器实例" :image-size="72" />
      </div>
      <div class="panel-footnote">
        <span class="status-dot success"></span>
        {{ instances.filter((item) => item.status === 'enabled').length }} 个实例将在后续工作流中可用
      </div>
    </section>

    <section class="surface-panel detail-panel" v-if="selectedInstance">
      <div class="detail-heading">
        <div class="detail-identity">
          <span class="large-instance-icon" :style="{ color: selectedCatalog.tone }">
            <AppIcon :name="selectedCatalog.icon" size="lg" />
          </span>
          <div>
            <div class="eyebrow">{{ selectedCatalog.label }}</div>
            <h2>{{ selectedInstance.name }}</h2>
            <p class="muted">{{ selectedCatalog.description }}</p>
          </div>
        </div>
        <div class="detail-actions">
          <el-tag :type="selectedInstance.status === 'enabled' ? 'success' : 'warning'" effect="plain">
            {{ statusLabel(selectedInstance.status) }}
          </el-tag>
          <el-button @click="openInstance(selectedInstance)">
            <AppIcon name="settings" size="sm" />
            <span>编辑实例</span>
          </el-button>
        </div>
      </div>

      <div class="metric-strip">
        <div><span>实例 ID</span><strong class="mono">{{ selectedInstance.id }}</strong></div>
        <div><span>默认处理模板</span><strong>{{ templates.find((item) => item.id === selectedInstance.templateId)?.name ?? '未设置' }}</strong></div>
        <div><span>采集字段</span><strong>{{ selectedCatalog.fields }}</strong></div>
      </div>

      <div class="detail-section">
        <div class="section-title-row">
          <div><h3>处理规则</h3><p>规则属于 {{ selectedCatalog.label }}，可以被同类型实例复用。</p></div>
          <el-button text @click="openTemplateManager">
            <AppIcon name="settings" size="sm" />
            <span>管理模板</span>
          </el-button>
        </div>
        <div class="template-highlight" :class="{ empty: !selectedInstance.templateId }">
          <span class="template-symbol"><AppIcon name="settings" size="sm" /></span>
          <div class="template-highlight-main">
            <strong>{{ templates.find((item) => item.id === selectedInstance.templateId)?.name ?? '未加载模板' }}</strong>
            <p>{{ selectedInstance.templateId ? '实例继承模板，并保留自己的局部调整。' : '当前实例直接使用局部规则。' }}</p>
          </div>
          <el-button @click="openInstance(selectedInstance)">{{ selectedInstance.templateId ? '调整规则' : '配置规则' }}</el-button>
        </div>
        <pre class="json-preview">{{ displayRules(effectivePreviewRules) }}</pre>
        <div class="json-actions">
          <span class="muted text-xs">只读预览 · 最终规则由实例模板和局部调整合并得到</span>
          <el-button text size="small" @click="copyJson(effectivePreviewRules)">复制 JSON</el-button>
        </div>
      </div>

      <div class="detail-section workflow-section">
        <div class="section-title-row">
          <div><h3>工作流本次覆盖</h3><p>演示当前实例在“每日科技简报”中的一次性调整。</p></div>
          <el-switch :model-value="workflowOverrideEnabled" @update:model-value="openWorkflowOverride" />
        </div>
        <div class="workflow-context">
          <span class="workflow-mark"><AppIcon name="workflow" size="sm" /></span>
          <div><strong>每日科技简报</strong><span>下次运行 · 今天 10:00</span></div>
          <el-tag v-if="workflowOverrideEnabled" type="warning" effect="plain">本次覆盖</el-tag>
          <el-tag v-else type="info" effect="plain">继承实例默认值</el-tag>
        </div>
        <div v-if="workflowOverrideEnabled" class="override-editor">
          <el-form label-position="top">
            <el-form-item label="本次使用的处理模板">
              <el-select :model-value="workflowTemplateId" class="full-control" @update:model-value="updateWorkflowTemplate">
                <el-option value="" label="不使用模板，仅保留本次规则" />
                <el-option v-for="template in templates.filter((item) => item.collector === selectedInstance.collector)" :key="template.id" :value="template.id" :label="template.name" />
              </el-select>
            </el-form-item>
            <el-tabs v-model="workflowMode" class="compact-tabs">
              <el-tab-pane label="快速调整" name="form">
                <div class="rule-grid compact-rule-grid">
                  <el-form-item label="保留字段"><el-input v-model="workflowRuleForm.fields" placeholder="message, level" /></el-form-item>
                  <el-form-item label="排序字段"><el-input v-model="workflowRuleForm.sortBy" placeholder="created_at" /></el-form-item>
                  <el-form-item label="格式"><el-select v-model="workflowRuleForm.format"><el-option label="Markdown" value="markdown" /><el-option label="纯文本" value="text" /></el-select></el-form-item>
                  <el-form-item label="倒序"><el-switch v-model="workflowRuleForm.descending" /></el-form-item>
                </div>
              </el-tab-pane>
              <el-tab-pane label="高级 JSON" name="json"><el-input v-model="workflowJson" type="textarea" :rows="7" class="code-input" /></el-tab-pane>
            </el-tabs>
            <div class="override-footer"><span class="muted text-xs">只影响当前工作流，不会修改实例或共享模板</span><el-button type="primary" size="small" @click="applyWorkflowOverride">应用本次调整</el-button></div>
          </el-form>
        </div>
      </div>
    </section>
  </div>

  <el-dialog v-model="templateManagerOpen" width="1080px" top="6vh" class="template-dialog" destroy-on-close>
    <template #header>
      <div class="dialog-heading">
        <span class="dialog-icon"><AppIcon name="settings" /></span>
        <div><strong>处理模板</strong><span>统一管理可复用的 JSON 处理规则</span></div>
      </div>
    </template>
    <div class="template-manager">
      <aside class="template-sidebar">
        <div class="manager-toolbar">
          <el-select v-model="templateTypeFilter" size="small" aria-label="按采集器筛选模板">
            <el-option value="all" label="全部采集器" />
            <el-option v-for="item in collectorCatalog" :key="item.key" :value="item.key" :label="item.label" />
          </el-select>
          <el-button type="primary" size="small" @click="createTemplate"><AppIcon name="plus" size="sm" />新增</el-button>
        </div>
        <button v-for="template in visibleTemplates" :key="template.id" type="button" class="template-row" :class="{ selected: selectedTemplateId === template.id }" @click="selectTemplate(template.id)">
          <span class="template-row-icon"><AppIcon :name="catalogItem(template.collector).icon" size="sm" /></span>
          <span><strong>{{ template.name }}</strong><small>{{ catalogItem(template.collector).label }} · {{ template.updatedAt }}</small></span>
          <span class="row-arrow">›</span>
        </button>
        <el-empty v-if="!visibleTemplates.length" description="暂无模板" :image-size="60" />
      </aside>
      <section v-if="templateDraft" class="template-editor">
        <div class="editor-heading">
          <div><div class="eyebrow">PROCESSING TEMPLATE</div><h2>{{ templateDraft.name }}</h2><p>仅适用于 <strong>{{ catalogItem(templateDraft.collector).label }}</strong> 采集器</p></div>
          <el-tag type="info" effect="plain">{{ templateDraft.id }}</el-tag>
        </div>
        <el-form label-position="top" class="template-form">
          <div class="form-grid">
            <el-form-item label="模板名称"><el-input v-model="templateDraft.name" /></el-form-item>
            <el-form-item label="指定采集器"><el-select v-model="templateDraft.collector" class="full-control" :disabled="templateUsage.length > 0"><el-option v-for="item in collectorCatalog" :key="item.key" :value="item.key" :label="item.label" /></el-select><p v-if="templateUsage.length" class="field-note">已被 {{ templateUsage.length }} 个实例使用，采集器类型已锁定。</p></el-form-item>
          </div>
          <el-form-item label="用途说明"><el-input v-model="templateDraft.description" placeholder="例如：只保留错误日志并按时间倒序" /></el-form-item>
          <el-tabs v-model="templateMode" class="editor-tabs">
            <el-tab-pane label="快速配置" name="form">
              <div class="rule-grid">
                <el-form-item label="保留字段"><el-input v-model="templateRuleForm.fields" placeholder="message, level, module" /></el-form-item>
                <el-form-item label="过滤条件"><el-input v-model="templateRuleForm.filter" placeholder='{"level":["error"]}' /></el-form-item>
                <el-form-item label="排序字段"><el-input v-model="templateRuleForm.sortBy" placeholder="created_at" /></el-form-item>
                <el-form-item label="分组字段"><el-input v-model="templateRuleForm.groupBy" placeholder="module" /></el-form-item>
                <el-form-item label="输出格式"><el-select v-model="templateRuleForm.format" class="full-control"><el-option label="Markdown" value="markdown" /><el-option label="纯文本" value="text" /><el-option label="JSON 行" value="jsonl" /></el-select></el-form-item>
                <el-form-item label="按时间倒序"><el-switch v-model="templateRuleForm.descending" /></el-form-item>
              </div>
              <div class="schema-hint"><AppIcon name="settings" size="sm" /><span>可用字段由 {{ catalogItem(templateDraft.collector).label }} 采集器提供：{{ catalogItem(templateDraft.collector).fields }}</span></div>
            </el-tab-pane>
            <el-tab-pane label="高级 JSON" name="json">
              <el-input v-model="templateJson" type="textarea" :rows="15" class="code-input" />
              <p class="muted text-xs mt-2">保存时校验 JSON 对象，并交给采集器 Schema 做最终校验。</p>
            </el-tab-pane>
          </el-tabs>
        </el-form>
        <div class="template-editor-footer">
          <el-button type="danger" text @click="removeTemplate">删除模板</el-button>
          <div class="footer-actions"><el-button @click="templateManagerOpen = false">取消</el-button><el-button type="primary" @click="saveTemplate">保存模板</el-button></div>
        </div>
      </section>
      <el-empty v-else description="选择或新建一个模板" />
    </div>
  </el-dialog>

  <el-drawer v-model="instanceDrawerOpen" size="min(720px, 100%)" direction="rtl" destroy-on-close>
    <template #header>
      <div class="drawer-heading"><span class="dialog-icon"><AppIcon name="database" /></span><div><strong>{{ instanceDraft?.id.startsWith('collector_') ? '新增采集器实例' : '编辑采集器实例' }}</strong><span>实例配置与默认处理规则</span></div></div>
    </template>
    <el-form v-if="instanceDraft" label-position="top" class="instance-editor-form">
      <div class="editor-section"><div class="section-kicker">01 · 实例信息</div><div class="form-grid"><el-form-item label="实例名称"><el-input v-model="instanceDraft.name" /></el-form-item><el-form-item label="采集器类型"><el-select :model-value="instanceDraft.collector" class="full-control" @update:model-value="changeInstanceCollector"><el-option v-for="item in collectorCatalog" :key="item.key" :value="item.key" :label="item.label" /></el-select></el-form-item></div><el-form-item label="启用实例"><el-switch v-model="instanceDraft.status" active-value="enabled" inactive-value="paused" /></el-form-item></div>
      <div class="editor-section"><div class="section-kicker">02 · 连接与采集设置</div><p class="muted text-sm">这些字段属于实例本身，工作流只覆盖查询范围等调用级参数。</p><el-form-item label="来源地址 / 文件路径"><el-input v-model="instanceDraft.options.path" placeholder="/var/log/logagent/app.jsonl" /></el-form-item><el-form-item label="访问 Key（可选）"><el-input v-model="instanceDraft.options.apiKey" type="password" show-password placeholder="演示字段，不会提交后端" /></el-form-item><div class="form-grid"><el-form-item label="最大读取条数"><el-input-number v-model="instanceDraft.options.maxLines" :min="1" class="full-control" /></el-form-item><el-form-item label="超时 / 秒"><el-input-number v-model="instanceDraft.timeout" :min="1" class="full-control" /></el-form-item></div></div>
      <div class="editor-section"><div class="section-kicker">03 · 默认处理规则</div><el-form-item label="加载处理模板"><el-select :model-value="instanceDraft.templateId ?? ''" class="full-control" clearable placeholder="不使用共享模板" @update:model-value="loadInstanceTemplate"><el-option v-for="template in instanceTemplates" :key="template.id" :value="template.id" :label="template.name" /></el-select><p class="field-note">只显示适用于 {{ catalogItem(instanceDraft.collector).label }} 的模板。</p></el-form-item><div v-if="instanceTemplate" class="loaded-template"><span class="template-symbol"><AppIcon name="settings" size="sm" /></span><div><strong>{{ instanceTemplate.name }}</strong><span>已加载共享模板 · 修改下方内容只影响本实例</span></div></div><el-tabs v-model="instanceMode" class="editor-tabs"><el-tab-pane label="快速调整" name="form"><div class="rule-grid"><el-form-item label="保留字段"><el-input v-model="instanceRuleForm.fields" placeholder="message, level" /></el-form-item><el-form-item label="过滤条件"><el-input v-model="instanceRuleForm.filter" placeholder='{"level":["error"]}' /></el-form-item><el-form-item label="排序字段"><el-input v-model="instanceRuleForm.sortBy" placeholder="created_at" /></el-form-item><el-form-item label="倒序"><el-switch v-model="instanceRuleForm.descending" /></el-form-item></div></el-tab-pane><el-tab-pane label="高级 JSON" name="json"><el-input v-model="instanceJson" type="textarea" :rows="12" class="code-input" /></el-tab-pane></el-tabs></div>
      <div class="drawer-footer"><el-button @click="instanceDrawerOpen = false">取消</el-button><el-button type="primary" @click="saveInstance">保存实例</el-button></div>
    </el-form>
  </el-drawer>
</template>

<style scoped>
.demo-alert {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 16px 18px;
  margin-bottom: 20px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
  color: #1e3a8a;
}
.demo-alert p { margin: 4px 0 0; color: #475569; }
.alert-mark, .dialog-icon, .workflow-mark, .template-symbol {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #dbeafe;
  color: #2563eb;
}
.demo-layout { display: grid; grid-template-columns: minmax(320px, 0.9fr) minmax(0, 1.55fr); gap: 20px; align-items: start; }
.surface-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
.instance-panel { min-height: 710px; }
.panel-heading, .detail-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 22px 22px 16px; border-bottom: 1px solid var(--border); }
.eyebrow, .section-kicker { color: var(--muted); font-size: 11px; letter-spacing: .08em; font-weight: 700; }
.panel-heading h2, .detail-heading h2 { margin: 4px 0 0; font-size: 20px; }
.panel-heading h2 span { color: var(--muted); font-size: 13px; font-weight: 500; }
.instance-toolbar { display: flex; gap: 10px; padding: 16px 22px; border-bottom: 1px solid var(--border); }
.search-input { flex: 1; min-width: 0; }
.type-filter { width: 132px; }
.instance-list { padding: 8px 10px; }
.instance-row { display: flex; width: 100%; gap: 12px; align-items: center; padding: 14px 12px; margin: 2px 0; border: 1px solid transparent; border-radius: 7px; background: transparent; color: inherit; text-align: left; cursor: pointer; transition: background .15s ease, border-color .15s ease; }
.instance-row:hover { background: #f8fafc; border-color: var(--border); }
.instance-row.selected { background: #eff6ff; border-color: #93c5fd; }
.instance-icon { display: grid; flex: 0 0 auto; place-items: center; width: 36px; height: 36px; border-radius: 8px; background: #f1f5f9; }
.instance-content { display: grid; min-width: 0; gap: 4px; flex: 1; }
.instance-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.instance-title strong, .instance-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.instance-meta { color: var(--muted); font-size: 12px; }
.instance-chevron, .row-arrow { color: #94a3b8; font-size: 22px; line-height: 1; }
.panel-footnote { display: flex; gap: 8px; align-items: center; padding: 14px 22px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #22c55e; }
.detail-panel { overflow: hidden; }
.detail-identity { display: flex; gap: 12px; min-width: 0; align-items: center; }
.large-instance-icon { display: grid; place-items: center; width: 46px; height: 46px; flex: 0 0 auto; border-radius: 10px; background: #f1f5f9; }
.detail-heading p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.metric-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-bottom: 1px solid var(--border); }
.metric-strip div { display: grid; gap: 5px; min-width: 0; padding: 16px 20px; border-right: 1px solid var(--border); }
.metric-strip div:last-child { border-right: 0; }
.metric-strip span { color: var(--muted); font-size: 12px; }
.metric-strip strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.detail-section { padding: 22px; border-bottom: 1px solid var(--border); }
.detail-section:last-child { border-bottom: 0; }
.section-title-row { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.section-title-row h3 { margin: 0; font-size: 16px; }
.section-title-row p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.template-highlight { display: flex; gap: 12px; align-items: center; margin-top: 16px; padding: 14px; border: 1px solid #bfdbfe; border-radius: 7px; background: #f8fbff; }
.template-highlight.empty { border-color: var(--border); background: transparent; }
.template-highlight-main { min-width: 0; flex: 1; }
.template-highlight-main strong, .template-highlight-main p { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.template-highlight-main p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.json-preview { max-height: 180px; margin: 12px 0 0; padding: 14px; overflow: auto; border: 1px solid var(--border); border-radius: 6px; background: #f8fafc; color: #334155; font-size: 12px; line-height: 1.55; }
.json-actions { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: 4px; }
.workflow-context { display: flex; gap: 10px; align-items: center; margin-top: 16px; padding: 12px; border: 1px solid var(--border); border-radius: 7px; }
.workflow-context > div { display: grid; gap: 3px; flex: 1; }
.workflow-context span:not(.workflow-mark) { color: var(--muted); font-size: 12px; }
.override-editor { margin-top: 12px; padding: 14px; border-left: 3px solid #f59e0b; background: #fffbeb; }
.full-control { width: 100%; }
.rule-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.compact-rule-grid { gap: 0 12px; }
.code-input :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; line-height: 1.55; }
.override-footer, .template-editor-footer, .drawer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.template-manager { display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: 600px; margin: -8px -20px -20px; border-top: 1px solid var(--border); }
.template-sidebar { padding: 16px; border-right: 1px solid var(--border); background: #f8fafc; }
.manager-toolbar { display: flex; gap: 8px; margin-bottom: 12px; }
.manager-toolbar .el-select { min-width: 0; flex: 1; }
.template-row { display: flex; width: 100%; gap: 10px; align-items: center; padding: 12px 10px; margin-bottom: 5px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.template-row:hover { background: var(--surface); border-color: var(--border); }
.template-row.selected { background: var(--surface); border-color: #93c5fd; box-shadow: 0 1px 3px rgba(15, 23, 42, .05); }
.template-row > span:nth-child(2) { display: grid; min-width: 0; flex: 1; gap: 3px; }
.template-row strong, .template-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.template-row small { color: var(--muted); font-size: 11px; }
.template-row-icon { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 6px; background: #e0f2fe; color: #0369a1; }
.template-editor { display: flex; min-width: 0; flex-direction: column; padding: 24px 28px 20px; }
.editor-heading { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
.editor-heading h2 { margin: 4px 0; font-size: 20px; }
.editor-heading p { margin: 0; color: var(--muted); font-size: 13px; }
.template-form { flex: 1; }
.editor-tabs { margin-top: 6px; }
.schema-hint { display: flex; gap: 8px; align-items: center; padding: 10px 12px; border-radius: 6px; background: #f8fafc; color: var(--muted); font-size: 12px; }
.template-editor-footer { padding-top: 18px; margin-top: 16px; border-top: 1px solid var(--border); }
.footer-actions { display: flex; gap: 8px; }
.drawer-heading, .dialog-heading { display: flex; gap: 10px; align-items: center; }
.drawer-heading > div, .dialog-heading > div { display: grid; gap: 3px; }
.drawer-heading span, .dialog-heading span { color: var(--muted); font-size: 12px; }
.instance-editor-form { padding-bottom: 70px; }
.editor-section { padding: 0 0 22px; margin-bottom: 22px; border-bottom: 1px solid var(--border); }
.editor-section:last-of-type { border-bottom: 0; }
.editor-section > p { margin: 6px 0 16px; }
.field-note { margin: 6px 0 0; color: var(--muted); font-size: 12px; }
.loaded-template { display: flex; gap: 10px; align-items: center; padding: 12px; margin-bottom: 14px; border: 1px solid #bfdbfe; border-radius: 6px; background: #f8fbff; }
.loaded-template > div { display: grid; gap: 3px; }
.loaded-template span:last-child { color: var(--muted); font-size: 12px; }
.drawer-footer { position: fixed; right: 0; bottom: 0; left: auto; width: min(720px, 100%); padding: 14px 24px; border-top: 1px solid var(--border); background: var(--surface); }
:global(.dark) .demo-alert { border-color: #1d4ed8; background: #172554; color: #dbeafe; }
:global(.dark) .demo-alert p { color: #cbd5e1; }
:global(.dark) .instance-row:hover, :global(.dark) .instance-row.selected, :global(.dark) .template-row.selected { background: #172554; }
:global(.dark) .instance-icon, :global(.dark) .large-instance-icon { background: #1e293b; }
:global(.dark) .template-highlight, :global(.dark) .loaded-template { border-color: #1d4ed8; background: #172554; }
:global(.dark) .json-preview, :global(.dark) .schema-hint, :global(.dark) .template-sidebar { background: #0f172a; }
:global(.dark) .json-preview { color: #cbd5e1; }
:global(.dark) .override-editor { background: #422006; }
@media (max-width: 1100px) {
  .demo-layout { grid-template-columns: 1fr; }
  .instance-panel { min-height: 0; }
  .instance-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .panel-footnote { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .demo-alert { padding: 14px; }
  .demo-layout { gap: 14px; }
  .panel-heading, .detail-heading { padding: 16px; flex-direction: column; }
  .detail-actions { width: 100%; }
  .instance-toolbar { padding: 12px 16px; flex-direction: column; }
  .type-filter { width: 100%; }
  .instance-list { grid-template-columns: 1fr; }
  .metric-strip { grid-template-columns: 1fr; }
  .metric-strip div { border-right: 0; border-bottom: 1px solid var(--border); }
  .metric-strip div:last-child { border-bottom: 0; }
  .detail-section { padding: 16px; }
  .template-highlight { align-items: flex-start; flex-wrap: wrap; }
  .template-highlight > .el-button { margin-left: 44px; }
  .rule-grid { grid-template-columns: 1fr; }
  .template-manager { grid-template-columns: 1fr; margin: -8px -20px -20px; }
  .template-sidebar { border-right: 0; border-bottom: 1px solid var(--border); max-height: 230px; overflow: auto; }
  .template-editor { padding: 18px 16px 16px; }
  .editor-heading { flex-direction: column; }
  .template-editor-footer { align-items: stretch; flex-direction: column-reverse; }
  .footer-actions { justify-content: flex-end; }
  .drawer-footer { width: 100%; padding: 12px 16px; }
}
</style>
