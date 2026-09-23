<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/icons/AppIcon.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { JsonObject } from '@/types'

type CollectorKey = 'logs' | 'rss' | 'history'
type ViewMode = 'collection' | 'resources'
type EditorMode = 'form' | 'json'
type ResourceFilter = 'all' | 'shared' | 'single'

interface CollectorCatalogItem {
  key: CollectorKey
  label: string
  description: string
  fields: string
  icon: 'database' | 'workflow' | 'history'
  tone: string
  locationLabel: string
  locationPlaceholder: string
  fieldOptions: { key: string; label: string }[]
  filterOptions: { value: string; label: string }[]
}

interface RuleForm {
  fields: string[]
  filter: string
  sortBy: string
  format: string
  descending: boolean
}

interface SourceOptions {
  location: string
  apiKey: string
  limit: number
}

interface SourceResource {
  id: string
  name: string
  collector: CollectorKey
  enabled: boolean
  options: SourceOptions
  rules: JsonObject
  updatedAt: string
}

interface Workflow {
  id: string
  name: string
  sourceIds: string[]
}

interface SourceDraft {
  id: string
  name: string
  collector: CollectorKey
  enabled: boolean
  options: SourceOptions
  rules: JsonObject
}

interface LocalOverride {
  detached: boolean
  draft: SourceDraft
}

const collectorCatalog: CollectorCatalogItem[] = [
  {
    key: 'logs',
    label: '运行日志',
    description: '从 LogAgent 日志中读取错误、告警和运行信息。',
    fields: '时间 · 级别 · 模块 · 内容',
    icon: 'database',
    tone: '#2563eb',
    locationLabel: '日志文件或接口地址',
    locationPlaceholder: '/var/log/logagent/app.jsonl',
    fieldOptions: [
      { key: 'created_at', label: '发生时间' },
      { key: 'level', label: '错误级别' },
      { key: 'module', label: '来源模块' },
      { key: 'message', label: '日志内容' },
      { key: 'session', label: '运行会话' },
    ],
    filterOptions: [
      { value: 'all', label: '不筛选' },
      { value: 'alerts', label: '只看错误和告警' },
    ],
  },
  {
    key: 'rss',
    label: 'RSS 订阅',
    description: '从固定订阅地址读取最近发布的内容。',
    fields: '标题 · 链接 · 发布时间 · 摘要',
    icon: 'workflow',
    tone: '#0f766e',
    locationLabel: '订阅地址',
    locationPlaceholder: 'https://example.com/feed.xml',
    fieldOptions: [
      { key: 'title', label: '标题' },
      { key: 'published', label: '发布时间' },
      { key: 'summary', label: '内容摘要' },
      { key: 'link', label: '原文链接' },
    ],
    filterOptions: [
      { value: 'all', label: '不筛选' },
      { value: 'recent', label: '只看最近 7 天' },
    ],
  },
  {
    key: 'history',
    label: '历史运行结果',
    description: '从过去的工作流结果中读取内容，方便复盘比较。',
    fields: '工作流 · 状态 · 时间 · 正文',
    icon: 'history',
    tone: '#c2410c',
    locationLabel: '结果来源名称',
    locationPlaceholder: 'weekly-report',
    fieldOptions: [
      { key: 'workflow_name', label: '工作流名称' },
      { key: 'status', label: '运行状态' },
      { key: 'created_at', label: '运行时间' },
      { key: 'content', label: '运行结果' },
    ],
    filterOptions: [
      { value: 'all', label: '不筛选' },
      { value: 'complete', label: '只看已完成的结果' },
    ],
  },
]

const resources = ref<SourceResource[]>([
  {
    id: 'logs_daily',
    name: '每日运行日志',
    collector: 'logs',
    enabled: true,
    options: { location: '/var/log/logagent/app.jsonl', apiKey: '', limit: 500 },
    rules: {
      fields: ['level', 'module', 'message', 'session'],
      filter: { level: ['error', 'warning'] },
      sort_by: 'created_at',
      descending: true,
      format: 'markdown',
    },
    updatedAt: '今天 09:42',
  },
  {
    id: 'rss_product',
    name: '产品更新订阅',
    collector: 'rss',
    enabled: true,
    options: { location: 'https://example.com/feed.xml', apiKey: '', limit: 100 },
    rules: {
      fields: ['title', 'published', 'summary', 'link'],
      filter: { published_within_days: 7 },
      sort_by: 'published',
      descending: true,
      format: 'markdown',
    },
    updatedAt: '昨天 18:10',
  },
  {
    id: 'history_weekly',
    name: '每周结果复盘',
    collector: 'history',
    enabled: false,
    options: { location: 'weekly-report', apiKey: '', limit: 10 },
    rules: {
      fields: ['workflow_name', 'status', 'created_at', 'content'],
      filter: { status: ['completed', 'partial'] },
      sort_by: 'created_at',
      format: 'markdown',
    },
    updatedAt: '2026-09-21',
  },
])

const workflows = ref<Workflow[]>([
  { id: 'daily-brief', name: '每日科技简报', sourceIds: ['logs_daily', 'rss_product'] },
  { id: 'incident-alert', name: '异常告警', sourceIds: ['logs_daily'] },
  { id: 'weekly-review', name: '每周结果复盘', sourceIds: ['history_weekly'] },
])

const localOverrides = ref<Record<string, Record<string, LocalOverride>>>({})
const activeView = ref<ViewMode>('collection')
const selectedWorkflowId = ref('daily-brief')
const selectedWorkflowSourceId = ref('logs_daily')
const selectedResourceId = ref('logs_daily')
const collectionSearch = ref('')
const resourceSearch = ref('')
const resourceFilter = ref<ResourceFilter>('all')

const workflowDraft = ref<SourceDraft | null>(null)
const workflowDetached = ref(false)
const workflowRuleMode = ref<EditorMode>('form')
const workflowRuleForm = ref<RuleForm>(emptyRuleForm())
const workflowRulesJson = ref('{}')

const addCollectorOpen = ref(false)
const loadCollectorOpen = ref(false)
const newCollectorDraft = ref<SourceDraft>(emptySourceDraft('logs'))
const newCollectorRuleMode = ref<EditorMode>('form')
const newCollectorRuleForm = ref<RuleForm>(emptyRuleForm())
const newCollectorRulesJson = ref('{}')
const loadSearch = ref('')

const resourceEditorOpen = ref(false)
const attachNewCollectorToWorkflow = ref(true)
const resourceDraft = ref<SourceDraft | null>(null)
const resourceRuleMode = ref<EditorMode>('form')
const resourceRuleForm = ref<RuleForm>(emptyRuleForm())
const resourceRulesJson = ref('{}')

function emptyRuleForm(): RuleForm {
  return { fields: [], filter: 'all', sortBy: '', format: 'markdown', descending: false }
}

function emptySourceDraft(collector: CollectorKey): SourceDraft {
  return {
    id: `source_${Date.now()}`,
    name: '新的数据源',
    collector,
    enabled: true,
    options: { location: '', apiKey: '', limit: 200 },
    rules: {},
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function catalogItem(key: CollectorKey) {
  return collectorCatalog.find((item) => item.key === key) ?? collectorCatalog[0]
}

function sourceById(id: string) {
  return resources.value.find((source) => source.id === id)
}

function draftFromResource(source: SourceResource): SourceDraft {
  return {
    id: source.id,
    name: source.name,
    collector: source.collector,
    enabled: source.enabled,
    options: clone(source.options),
    rules: clone(source.rules),
  }
}

function rulesToJson(rules: JsonObject) {
  return JSON.stringify(rules, null, 2)
}

function filterPreset(value: unknown, collector: CollectorKey) {
  if (!value || typeof value !== 'object') return 'all'
  const serialized = JSON.stringify(value)
  if (collector === 'logs' && serialized === JSON.stringify({ level: ['error', 'warning'] }))
    return 'alerts'
  if (collector === 'rss' && serialized === JSON.stringify({ published_within_days: 7 }))
    return 'recent'
  if (
    collector === 'history' &&
    serialized === JSON.stringify({ status: ['completed', 'partial'] })
  )
    return 'complete'
  return 'custom'
}

function formFromRules(rules: JsonObject, collector: CollectorKey): RuleForm {
  return {
    fields: Array.isArray(rules.fields)
      ? rules.fields.filter((field): field is string => typeof field === 'string')
      : [],
    filter: filterPreset(rules.filter, collector),
    sortBy: typeof rules.sort_by === 'string' ? rules.sort_by : '',
    format: typeof rules.format === 'string' ? rules.format : 'markdown',
    descending: rules.descending === true,
  }
}

function supportsBasicRuleEditor(rules: JsonObject, collector: CollectorKey) {
  const supportedKeys = new Set(['fields', 'filter', 'sort_by', 'descending', 'format'])
  if (Object.keys(rules).some((key) => !supportedKeys.has(key))) return false
  if (Array.isArray(rules.fields)) {
    const fields = new Set(catalogItem(collector).fieldOptions.map((field) => field.key))
    if (rules.fields.some((field) => typeof field !== 'string' || !fields.has(field))) return false
  } else if (rules.fields !== undefined) {
    return false
  }
  if (
    typeof rules.sort_by === 'string' &&
    !catalogItem(collector).fieldOptions.some((field) => field.key === rules.sort_by)
  ) {
    return false
  }
  if (rules.sort_by !== undefined && typeof rules.sort_by !== 'string') return false
  if (filterPreset(rules.filter, collector) === 'custom') return false
  if (rules.format !== undefined && !['markdown', 'json', 'text'].includes(String(rules.format)))
    return false
  return rules.descending === undefined || typeof rules.descending === 'boolean'
}

function rulesFromForm(form: RuleForm, collector: CollectorKey): JsonObject {
  const rules: JsonObject = {}
  if (form.fields.length) rules.fields = [...form.fields]
  const filterSelection = form.filter
  if (collector === 'logs' && filterSelection === 'alerts')
    rules.filter = { level: ['error', 'warning'] }
  if (collector === 'rss' && filterSelection === 'recent')
    rules.filter = { published_within_days: 7 }
  if (collector === 'history' && filterSelection === 'complete')
    rules.filter = { status: ['completed', 'partial'] }
  if (form.sortBy.trim()) rules.sort_by = form.sortBy.trim()
  if (form.format) rules.format = form.format
  if (form.descending) rules.descending = true
  return rules
}

function parseRules(
  mode: EditorMode,
  json: string,
  form: RuleForm,
  collector: CollectorKey,
): JsonObject | null {
  if (mode === 'form') {
    if (form.filter === 'custom') {
      ElMessage.error('这份数据源包含高级筛选规则，请切换到高级 JSON 后保存')
      return null
    }
    return rulesFromForm(form, collector)
  }
  try {
    const parsed = JSON.parse(json)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object')
      throw new Error('object required')
    return parsed as JsonObject
  } catch {
    ElMessage.error('高级 JSON 必须是一个有效的对象')
    return null
  }
}

function setRuleMode(
  nextMode: EditorMode,
  currentMode: EditorMode,
  json: string,
  form: { value: RuleForm },
  collector: CollectorKey,
  updateJson: (value: string) => void,
) {
  if (nextMode === currentMode) return true
  if (nextMode === 'json') {
    if (form.value.filter === 'custom') {
      ElMessage.error('请在高级 JSON 中保留这份数据源已有的筛选条件')
      return false
    }
    updateJson(rulesToJson(rulesFromForm(form.value, collector)))
    return true
  }
  try {
    const parsed = JSON.parse(json)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    const rules = parsed as JsonObject
    if (!supportsBasicRuleEditor(rules, collector)) {
      ElMessage.error('当前规则包含普通设置未覆盖的内容，请继续使用高级 JSON')
      return false
    }
    form.value = formFromRules(rules, collector)
    return true
  } catch {
    ElMessage.error('当前 JSON 无法转换为普通表单，请先修正它')
    return false
  }
}

const selectedWorkflow = computed(
  () =>
    workflows.value.find((workflow) => workflow.id === selectedWorkflowId.value) ??
    workflows.value[0],
)
const selectedWorkflowSource = computed(() => sourceById(selectedWorkflowSourceId.value))
const selectedResource = computed(() => sourceById(selectedResourceId.value))
const filteredCollectionSources = computed(() => {
  const query = collectionSearch.value.trim().toLowerCase()
  return (selectedWorkflow.value?.sourceIds ?? [])
    .map((id) => sourceById(id))
    .filter((source): source is SourceResource => Boolean(source))
    .filter((source) => {
      if (!query) return true
      return `${source.name} ${source.id} ${catalogItem(source.collector).label}`
        .toLowerCase()
        .includes(query)
    })
})
const filteredResources = computed(() => {
  const query = resourceSearch.value.trim().toLowerCase()
  return resources.value.filter((source) => {
    const count = workflows.value.filter((workflow) =>
      workflow.sourceIds.includes(source.id),
    ).length
    const matchesFilter =
      resourceFilter.value === 'all' ||
      (resourceFilter.value === 'shared' && count > 1) ||
      (resourceFilter.value === 'single' && count <= 1)
    const matchesSearch =
      !query ||
      `${source.name} ${source.id} ${catalogItem(source.collector).label}`
        .toLowerCase()
        .includes(query)
    return matchesFilter && matchesSearch
  })
})
const filteredLoadResources = computed(() => {
  const query = loadSearch.value.trim().toLowerCase()
  return resources.value.filter(
    (source) =>
      !query ||
      `${source.name} ${source.id} ${catalogItem(source.collector).label}`
        .toLowerCase()
        .includes(query),
  )
})
const selectedSharedUsageCount = computed(() =>
  selectedWorkflowSource.value ? sharedUsageCount(selectedWorkflowSource.value.id) : 0,
)
const selectedResourceUsage = computed(() =>
  selectedResource.value
    ? workflows.value.filter((workflow) => workflow.sourceIds.includes(selectedResource.value!.id))
    : [],
)
const workflowCanSave = computed(
  () =>
    Boolean(workflowDraft.value) && (workflowDetached.value || selectedSharedUsageCount.value <= 1),
)
const workflowRuleSummary = computed(() =>
  summarizeRules(workflowDraft.value?.rules ?? {}, workflowDraft.value?.collector ?? 'logs'),
)
const resourceRuleSummary = computed(() =>
  summarizeRules(selectedResource.value?.rules ?? {}, selectedResource.value?.collector ?? 'logs'),
)

function usageCount(sourceId: string) {
  return workflows.value.filter((workflow) => workflow.sourceIds.includes(sourceId)).length
}

function sharedUsageCount(sourceId: string) {
  return workflows.value.filter(
    (workflow) => workflow.sourceIds.includes(sourceId) && !hasLocalOverride(workflow.id, sourceId),
  ).length
}

function hasLocalOverride(workflowId: string, sourceId: string) {
  return Boolean(localOverrides.value[workflowId]?.[sourceId]?.detached)
}

function isSharedInWorkflow(sourceId: string) {
  return sharedUsageCount(sourceId) > 1 && !hasLocalOverride(selectedWorkflowId.value, sourceId)
}

function localOverride(workflowId: string, sourceId: string) {
  return localOverrides.value[workflowId]?.[sourceId]
}

function loadWorkflowDraft() {
  const source = selectedWorkflowSource.value
  if (!source) {
    workflowDraft.value = null
    return
  }
  const override = localOverride(selectedWorkflowId.value, source.id)
  workflowDetached.value = Boolean(override?.detached)
  workflowDraft.value = clone(override?.detached ? override.draft : draftFromResource(source))
  workflowRuleForm.value = formFromRules(workflowDraft.value.rules, workflowDraft.value.collector)
  workflowRulesJson.value = rulesToJson(workflowDraft.value.rules)
  workflowRuleMode.value = supportsBasicRuleEditor(
    workflowDraft.value.rules,
    workflowDraft.value.collector,
  )
    ? 'form'
    : 'json'
}

watch(selectedWorkflowSourceId, loadWorkflowDraft, { immediate: true })
watch(selectedWorkflowId, () => {
  const ids = selectedWorkflow.value?.sourceIds ?? []
  selectedWorkflowSourceId.value = ids[0] ?? ''
  loadWorkflowDraft()
})

function chooseWorkflowSource(sourceId: string) {
  selectedWorkflowSourceId.value = sourceId
}

function openAddCollector(attachToWorkflow = true) {
  attachNewCollectorToWorkflow.value = attachToWorkflow
  newCollectorDraft.value = emptySourceDraft('logs')
  newCollectorRuleForm.value = emptyRuleForm()
  newCollectorRulesJson.value = '{}'
  newCollectorRuleMode.value = 'form'
  addCollectorOpen.value = true
}

function setNewCollectorType(collector: CollectorKey) {
  newCollectorDraft.value.collector = collector
  newCollectorRuleForm.value = emptyRuleForm()
  newCollectorRulesJson.value = '{}'
  newCollectorRuleMode.value = 'form'
}

function saveNewCollector() {
  const draft = clone(newCollectorDraft.value)
  const rules = parseRules(
    newCollectorRuleMode.value,
    newCollectorRulesJson.value,
    newCollectorRuleForm.value,
    draft.collector,
  )
  if (!rules) return
  if (!draft.name.trim() || !draft.options.location.trim()) {
    ElMessage.warning('请先填写数据源名称和来源地址')
    return
  }
  draft.rules = rules
  draft.id = `source_${Date.now()}`
  resources.value.push({ ...draft, updatedAt: '刚刚' })
  if (
    attachNewCollectorToWorkflow.value &&
    selectedWorkflow.value &&
    !selectedWorkflow.value.sourceIds.includes(draft.id)
  ) {
    selectedWorkflow.value.sourceIds.push(draft.id)
  }
  if (attachNewCollectorToWorkflow.value) selectedWorkflowSourceId.value = draft.id
  selectedResourceId.value = draft.id
  addCollectorOpen.value = false
  ElMessage.success(
    attachNewCollectorToWorkflow.value
      ? '数据源已新增，并加载到当前工作流'
      : '数据源已新增到资源配置中心',
  )
}

function openLoadCollector() {
  loadSearch.value = ''
  loadCollectorOpen.value = true
}

function loadCollector(sourceId: string) {
  if (!selectedWorkflow.value) return
  if (selectedWorkflow.value.sourceIds.includes(sourceId)) {
    selectedWorkflowSourceId.value = sourceId
    loadCollectorOpen.value = false
    ElMessage.info('这个数据源已经在当前工作流中')
    return
  }
  selectedWorkflow.value.sourceIds.push(sourceId)
  selectedWorkflowSourceId.value = sourceId
  loadCollectorOpen.value = false
  ElMessage.success('数据源已加载到当前工作流')
}

async function detachWorkflowSource() {
  const source = selectedWorkflowSource.value
  if (!source || !workflowDraft.value) return
  if (!isSharedInWorkflow(source.id)) {
    ElMessage.info('这个数据源没有被其他工作流共用，可以直接保存')
    return
  }
  try {
    await ElMessageBox.confirm(
      `脱离后，${selectedWorkflow.value?.name} 的调整只会保存在这里，不会影响另外 ${selectedSharedUsageCount.value - 1} 个工作流。`,
      '只修改当前工作流？',
      { confirmButtonText: '脱离并继续', cancelButtonText: '先不修改', type: 'warning' },
    )
  } catch {
    return
  }
  const workflowId = selectedWorkflowId.value
  localOverrides.value[workflowId] = {
    ...(localOverrides.value[workflowId] ?? {}),
    [source.id]: { detached: true, draft: clone(workflowDraft.value) },
  }
  workflowDetached.value = true
  ElMessage.success('已脱离共同设置，现在可以只修改当前工作流')
}

function restoreSharedSource() {
  const source = selectedWorkflowSource.value
  if (!source) return
  const overrides = { ...(localOverrides.value[selectedWorkflowId.value] ?? {}) }
  delete overrides[source.id]
  localOverrides.value = { ...localOverrides.value, [selectedWorkflowId.value]: overrides }
  loadWorkflowDraft()
  ElMessage.success('已恢复共同设置，当前工作流会跟随资源配置中心')
}

function saveWorkflowSource() {
  const source = selectedWorkflowSource.value
  const draft = workflowDraft.value
  if (!source || !draft) return
  if (selectedSharedUsageCount.value > 1 && !workflowDetached.value) {
    ElMessage.warning('这份数据源正在被多个工作流使用。若只改当前工作流，请先点击“脱离共享设置”。')
    return
  }
  const rules = parseRules(
    workflowRuleMode.value,
    workflowRulesJson.value,
    workflowRuleForm.value,
    draft.collector,
  )
  if (!rules) return
  draft.rules = rules
  if (workflowDetached.value) {
    localOverrides.value[selectedWorkflowId.value] = {
      ...(localOverrides.value[selectedWorkflowId.value] ?? {}),
      [source.id]: { detached: true, draft: clone(draft) },
    }
    ElMessage.success('本次调整已保存，只影响当前工作流')
    return
  }
  const index = resources.value.findIndex((item) => item.id === source.id)
  if (index !== -1) {
    resources.value[index] = { ...resources.value[index], ...clone(draft), updatedAt: '刚刚' }
  }
  loadWorkflowDraft()
  ElMessage.success('数据源已保存')
}

function openResourceEditor(source: SourceResource) {
  resourceDraft.value = draftFromResource(source)
  resourceRuleForm.value = formFromRules(source.rules, source.collector)
  resourceRulesJson.value = rulesToJson(source.rules)
  resourceRuleMode.value = supportsBasicRuleEditor(source.rules, source.collector) ? 'form' : 'json'
  resourceEditorOpen.value = true
}

function saveResource() {
  const draft = resourceDraft.value
  if (!draft) return
  const rules = parseRules(
    resourceRuleMode.value,
    resourceRulesJson.value,
    resourceRuleForm.value,
    draft.collector,
  )
  if (!rules) return
  if (!draft.name.trim() || !draft.options.location.trim()) {
    ElMessage.warning('请先填写数据源名称和来源地址')
    return
  }
  const index = resources.value.findIndex((item) => item.id === draft.id)
  if (index === -1) return
  resources.value[index] = { ...clone(draft), rules, updatedAt: '刚刚' }
  selectedResourceId.value = draft.id
  if (selectedWorkflowSourceId.value === draft.id && !workflowDetached.value) loadWorkflowDraft()
  resourceEditorOpen.value = false
  const count = sharedUsageCount(draft.id)
  ElMessage.success(
    count > 0 ? `已保存，并同步到 ${count} 个工作流` : '数据源已保存，暂未同步到工作流',
  )
}

function switchWorkflowRuleMode(value: string | number | boolean | undefined) {
  if (value !== 'form' && value !== 'json') return
  const nextMode = value
  if (
    workflowDraft.value &&
    setRuleMode(
      nextMode,
      workflowRuleMode.value,
      workflowRulesJson.value,
      workflowRuleForm,
      workflowDraft.value.collector,
      (value) => (workflowRulesJson.value = value),
    )
  ) {
    workflowRuleMode.value = nextMode
  }
}

function switchNewCollectorRuleMode(value: string | number | boolean | undefined) {
  if (value !== 'form' && value !== 'json') return
  const nextMode = value
  if (
    setRuleMode(
      nextMode,
      newCollectorRuleMode.value,
      newCollectorRulesJson.value,
      newCollectorRuleForm,
      newCollectorDraft.value.collector,
      (value) => (newCollectorRulesJson.value = value),
    )
  ) {
    newCollectorRuleMode.value = nextMode
  }
}

function switchResourceRuleMode(value: string | number | boolean | undefined) {
  if (value !== 'form' && value !== 'json') return
  const nextMode = value
  if (
    resourceDraft.value &&
    setRuleMode(
      nextMode,
      resourceRuleMode.value,
      resourceRulesJson.value,
      resourceRuleForm,
      resourceDraft.value.collector,
      (value) => (resourceRulesJson.value = value),
    )
  ) {
    resourceRuleMode.value = nextMode
  }
}

function summarizeRules(rules: JsonObject, collector: CollectorKey) {
  const fields = Array.isArray(rules.fields) ? rules.fields.length : 0
  const filter = rules.filter && typeof rules.filter === 'object' ? '有筛选条件' : '不过滤'
  const sortField = catalogItem(collector).fieldOptions.find(
    (field) => field.key === rules.sort_by,
  )?.label
  const sort = sortField ? `按${sortField}排序` : '按来源顺序'
  return `${fields ? `保留 ${fields} 个字段` : '保留来源字段'} · ${filter} · ${sort}`
}

function resourceImpact(sourceId: string) {
  const count = sharedUsageCount(sourceId)
  return count > 0 ? `保存会同步到 ${count} 个工作流` : '这个数据源暂未被工作流使用'
}

function sourceUsageLabel(sourceId: string) {
  const count = usageCount(sourceId)
  if (count > 1) return `${count} 个工作流共用`
  return count === 1 ? '仅 1 个工作流使用' : '暂未使用'
}

function copyJson(rules: JsonObject) {
  void navigator.clipboard?.writeText(rulesToJson(rules))
  ElMessage.success('JSON 已复制')
}

function statusLabel(source: SourceResource | SourceDraft) {
  return source.enabled ? '已启用' : '已停用'
}

function iconName(source: SourceResource | SourceDraft) {
  return catalogItem(source.collector).icon
}
</script>

<template>
  <PageHeader title="数据源配置演示" description="用“从哪里取数据”和“取到后怎么整理”完成一次采集">
    <el-tag type="info" effect="plain" class="demo-tag">前端演示 · 本地状态</el-tag>
    <el-radio-group
      v-model="activeView"
      size="small"
      class="view-switcher"
      aria-label="切换数据源视图"
    >
      <el-radio-button label="collection">数据采集</el-radio-button>
      <el-radio-button label="resources">资源配置中心</el-radio-button>
    </el-radio-group>
  </PageHeader>

  <div class="demo-alert">
    <span class="alert-mark"><AppIcon name="info" size="sm" /></span>
    <div>
      <strong>数据源是一份可以重复使用的采集设置</strong>
      <p>
        在“数据采集”里只改当前工作流时，先脱离共享设置；在“资源配置中心”保存，会同步到所有使用它的工作流。
      </p>
    </div>
  </div>

  <template v-if="activeView === 'collection'">
    <div class="workflow-bar surface-panel">
      <div class="workflow-picker">
        <span class="eyebrow">当前工作流</span>
        <el-select v-model="selectedWorkflowId" aria-label="选择当前工作流" class="workflow-select">
          <el-option
            v-for="workflow in workflows"
            :key="workflow.id"
            :value="workflow.id"
            :label="workflow.name"
          />
        </el-select>
      </div>
      <div class="workflow-stats">
        <span>{{ selectedWorkflow?.sourceIds.length ?? 0 }} 个数据源</span>
        <span>修改会在保存时明确提示影响范围</span>
      </div>
    </div>

    <div class="collection-layout">
      <section class="surface-panel source-list-panel">
        <div class="panel-heading">
          <div>
            <div class="eyebrow">DATA SOURCES</div>
            <h2>
              本次要取哪些数据
              <span>{{ selectedWorkflow?.sourceIds.length ?? 0 }}</span>
            </h2>
          </div>
          <el-button text aria-label="刷新数据源" @click="ElMessage.info('演示数据已是最新')">
            <AppIcon name="rotate" size="sm" />
          </el-button>
        </div>
        <div class="source-actions">
          <el-button type="primary" @click="openAddCollector()">
            <AppIcon name="plus" size="sm" />
            <span>新增采集器</span>
          </el-button>
          <el-button @click="openLoadCollector">
            <AppIcon name="archive" size="sm" />
            <span>加载采集器</span>
          </el-button>
        </div>
        <el-input
          v-model="collectionSearch"
          clearable
          placeholder="搜索当前工作流的数据源"
          class="source-search"
        >
          <template #prefix><AppIcon name="search" size="sm" /></template>
        </el-input>
        <div class="source-list">
          <button
            v-for="source in filteredCollectionSources"
            :key="source.id"
            type="button"
            class="source-row"
            :class="{ selected: selectedWorkflowSourceId === source.id }"
            @click="chooseWorkflowSource(source.id)"
          >
            <span class="source-icon" :style="{ color: catalogItem(source.collector).tone }">
              <AppIcon :name="iconName(source)" />
            </span>
            <span class="source-row-main">
              <span class="source-row-title">
                <strong>{{ source.name }}</strong>
                <el-tag v-if="!source.enabled" size="small" type="warning">已停用</el-tag>
              </span>
              <span class="source-row-meta">
                {{ catalogItem(source.collector).label }} · {{ sourceUsageLabel(source.id) }}
              </span>
              <span v-if="hasLocalOverride(selectedWorkflowId, source.id)" class="local-mark">
                当前工作流有单独设置
              </span>
            </span>
            <AppIcon name="chevronRight" size="sm" />
          </button>
          <el-empty
            v-if="!filteredCollectionSources.length"
            description="当前工作流还没有数据源"
            :image-size="64"
          />
        </div>
        <p class="panel-footnote">
          <span class="status-dot success"></span>
          数据源可以在多个工作流中重复使用
        </p>
      </section>

      <section
        v-if="workflowDraft && selectedWorkflowSource"
        class="surface-panel source-editor-panel"
      >
        <div class="detail-heading">
          <div class="detail-identity">
            <span
              class="large-source-icon"
              :style="{ color: catalogItem(workflowDraft.collector).tone }"
            >
              <AppIcon :name="iconName(workflowDraft)" size="lg" />
            </span>
            <div>
              <div class="eyebrow">{{ catalogItem(workflowDraft.collector).label }}</div>
              <h2>{{ workflowDraft.name }}</h2>
              <p class="muted">{{ catalogItem(workflowDraft.collector).description }}</p>
            </div>
          </div>
          <div class="detail-actions">
            <el-tag :type="workflowDraft.enabled ? 'success' : 'warning'" effect="plain">
              {{ statusLabel(workflowDraft) }}
            </el-tag>
            <el-button :disabled="!workflowCanSave" @click="saveWorkflowSource">
              <AppIcon name="check" size="sm" />
              <span>保存</span>
            </el-button>
          </div>
        </div>

        <div class="sharing-banner" :class="{ detached: workflowDetached }">
          <span class="sharing-icon">
            <AppIcon :name="workflowDetached ? 'sliders' : 'layers'" size="sm" />
          </span>
          <div>
            <strong v-if="workflowDetached">当前工作流正在使用单独设置</strong>
            <strong v-else-if="selectedSharedUsageCount > 1">
              这份数据源正在被 {{ selectedSharedUsageCount }} 个工作流共同使用
            </strong>
            <strong v-else>这份共享设置只有当前工作流使用</strong>
            <p v-if="workflowDetached">
              保存只影响“{{ selectedWorkflow?.name }}”，资源配置中心的修改不会覆盖这里。
            </p>
            <p v-else-if="selectedSharedUsageCount > 1">
              想只改这一次，请先脱离共享设置；资源配置中心的保存会同步到所有仍使用共同设置的位置。
            </p>
            <p v-else>当前没有其他工作流跟随这份共享设置，可以直接保存本次修改。</p>
          </div>
          <el-button v-if="workflowDetached" text @click="restoreSharedSource">
            恢复共同设置
          </el-button>
          <el-button
            v-else-if="selectedSharedUsageCount > 1"
            type="warning"
            plain
            @click="detachWorkflowSource"
          >
            脱离共享设置
          </el-button>
        </div>

        <div class="editor-section">
          <div class="section-title-row">
            <div>
              <h3>从哪里取数据</h3>
              <p>这些是数据源本身的设置，包含地址、密钥和读取数量。</p>
            </div>
          </div>
          <div class="form-grid">
            <el-form-item label="数据源名称">
              <el-input v-model="workflowDraft.name" />
            </el-form-item>
            <el-form-item label="采集器类型">
              <el-select v-model="workflowDraft.collector" disabled>
                <el-option
                  v-for="item in collectorCatalog"
                  :key="item.key"
                  :value="item.key"
                  :label="item.label"
                />
              </el-select>
            </el-form-item>
            <el-form-item
              :label="catalogItem(workflowDraft.collector).locationLabel"
              class="span-2"
            >
              <el-input
                v-model="workflowDraft.options.location"
                :placeholder="catalogItem(workflowDraft.collector).locationPlaceholder"
              />
            </el-form-item>
            <el-form-item label="接口密钥（可选）">
              <el-input
                v-model="workflowDraft.options.apiKey"
                type="password"
                show-password
                placeholder="暂时没有也可以留空"
              />
            </el-form-item>
            <el-form-item label="最多读取条数">
              <el-input-number
                v-model="workflowDraft.options.limit"
                :min="1"
                :max="10000"
                controls-position="right"
              />
            </el-form-item>
          </div>
          <div class="inline-setting">
            <el-switch v-model="workflowDraft.enabled" />
            <div>
              <strong>启用这个数据源</strong>
              <span>停用后，工作流会跳过它，但保留原来的设置。</span>
            </div>
          </div>
        </div>

        <div class="editor-section rules-section">
          <div class="section-title-row">
            <div>
              <h3>取到后怎么整理</h3>
              <p>
                {{
                  catalogItem(workflowDraft.collector).fields
                }}。这些规则保存在数据源里，也可以按需脱离后只改当前工作流。
              </p>
            </div>
            <el-radio-group
              :model-value="workflowRuleMode"
              size="small"
              @update:model-value="switchWorkflowRuleMode"
            >
              <el-radio-button label="form">普通设置</el-radio-button>
              <el-radio-button label="json">高级 JSON</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="workflowRuleMode === 'form'" class="rule-form-grid">
            <el-form-item label="保留哪些内容" class="span-2">
              <el-checkbox-group v-model="workflowRuleForm.fields" class="field-options">
                <el-checkbox
                  v-for="field in catalogItem(workflowDraft.collector).fieldOptions"
                  :key="field.key"
                  :label="field.key"
                >
                  {{ field.label }}
                </el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="筛选内容">
              <el-select v-model="workflowRuleForm.filter">
                <el-option
                  v-for="filter in catalogItem(workflowDraft.collector).filterOptions"
                  :key="filter.value"
                  :value="filter.value"
                  :label="filter.label"
                />
                <el-option
                  v-if="workflowRuleForm.filter === 'custom'"
                  value="custom"
                  label="已有高级筛选"
                  disabled
                />
              </el-select>
            </el-form-item>
            <el-form-item label="排序方式">
              <el-select v-model="workflowRuleForm.sortBy" clearable placeholder="保持来源顺序">
                <el-option
                  v-for="field in catalogItem(workflowDraft.collector).fieldOptions"
                  :key="field.key"
                  :value="field.key"
                  :label="field.label"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="输出格式">
              <el-select v-model="workflowRuleForm.format">
                <el-option value="markdown" label="Markdown" />
                <el-option value="json" label="JSON" />
                <el-option value="text" label="纯文本" />
              </el-select>
            </el-form-item>
            <el-form-item class="span-2">
              <el-checkbox v-model="workflowRuleForm.descending">排序从新到旧</el-checkbox>
            </el-form-item>
          </div>
          <div v-else class="advanced-editor">
            <el-input
              v-model="workflowRulesJson"
              type="textarea"
              :rows="11"
              class="json-input"
              spellcheck="false"
            />
            <div class="advanced-footer">
              <span>高级模式编辑的是同一份处理规则 JSON，保存前会检查格式。</span>
              <el-button text @click="copyJson(workflowDraft.rules)">
                <AppIcon name="copy" size="sm" />
                复制示例
              </el-button>
            </div>
          </div>
          <div class="rule-summary">
            <AppIcon name="sliders" size="sm" />
            {{ workflowRuleSummary }}
          </div>
        </div>

        <div class="editor-footer">
          <span v-if="!workflowCanSave && selectedSharedUsageCount > 1" class="save-hint">
            这份数据源被多个工作流使用，先脱离共享设置后才能保存单独修改。
          </span>
          <span v-else class="save-hint">保存后只会改变当前允许的范围，页面会显示同步结果。</span>
          <el-button type="primary" :disabled="!workflowCanSave" @click="saveWorkflowSource">
            <AppIcon name="check" size="sm" />
            保存本次设置
          </el-button>
        </div>
      </section>
      <el-empty v-else description="选择一个数据源开始配置" />
    </div>

    <div class="collection-note surface-panel">
      <span class="note-icon"><AppIcon name="info" size="sm" /></span>
      <div>
        <strong>这次演示先解决“看得懂、改得对”</strong>
        <p>
          模板版本、批量迁移和真实采集预览留给后续版本；高级 JSON 入口保留给需要精细控制的用户。
        </p>
      </div>
    </div>
  </template>

  <template v-else>
    <div class="resource-toolbar surface-panel">
      <div>
        <div class="eyebrow">SHARED RESOURCES</div>
        <h2>资源配置中心</h2>
        <p class="muted">
          从这里修改会同步到所有使用位置；只想改一处，请回到数据采集并先脱离共享设置。
        </p>
      </div>
      <div class="resource-toolbar-actions">
        <el-input
          v-model="resourceSearch"
          clearable
          placeholder="搜索数据源"
          class="resource-search"
        >
          <template #prefix><AppIcon name="search" size="sm" /></template>
        </el-input>
        <el-select v-model="resourceFilter" aria-label="筛选数据源使用范围" class="resource-filter">
          <el-option value="all" label="全部数据源" />
          <el-option value="shared" label="多人共用" />
          <el-option value="single" label="单独使用" />
        </el-select>
        <el-button type="primary" @click="openAddCollector(false)">
          <AppIcon name="plus" size="sm" />
          新增数据源
        </el-button>
      </div>
    </div>

    <div class="resource-layout">
      <section class="surface-panel resource-list-panel">
        <div class="panel-heading compact-heading">
          <div>
            <h2>
              数据源
              <span>{{ filteredResources.length }}</span>
            </h2>
          </div>
        </div>
        <div class="resource-list">
          <button
            v-for="source in filteredResources"
            :key="source.id"
            type="button"
            class="resource-row"
            :class="{ selected: selectedResourceId === source.id }"
            @click="selectedResourceId = source.id"
          >
            <span class="source-icon" :style="{ color: catalogItem(source.collector).tone }">
              <AppIcon :name="iconName(source)" />
            </span>
            <span class="resource-row-main">
              <span class="source-row-title">
                <strong>{{ source.name }}</strong>
                <el-tag v-if="!source.enabled" size="small" type="warning">已停用</el-tag>
              </span>
              <span class="source-row-meta">
                {{ catalogItem(source.collector).label }} · {{ sourceUsageLabel(source.id) }}
              </span>
            </span>
            <AppIcon name="chevronRight" size="sm" />
          </button>
          <el-empty
            v-if="!filteredResources.length"
            description="没有匹配的数据源"
            :image-size="64"
          />
        </div>
      </section>

      <section v-if="selectedResource" class="surface-panel resource-detail-panel">
        <div class="detail-heading">
          <div class="detail-identity">
            <span
              class="large-source-icon"
              :style="{ color: catalogItem(selectedResource.collector).tone }"
            >
              <AppIcon :name="iconName(selectedResource)" size="lg" />
            </span>
            <div>
              <div class="eyebrow">{{ catalogItem(selectedResource.collector).label }}</div>
              <h2>{{ selectedResource.name }}</h2>
              <p class="muted">{{ catalogItem(selectedResource.collector).description }}</p>
            </div>
          </div>
          <div class="detail-actions">
            <el-tag :type="selectedResource.enabled ? 'success' : 'warning'" effect="plain">
              {{ statusLabel(selectedResource) }}
            </el-tag>
            <el-button type="primary" @click="openResourceEditor(selectedResource)">
              <AppIcon name="settings" size="sm" />
              编辑数据源
            </el-button>
          </div>
        </div>

        <div class="sync-callout">
          <span class="sharing-icon"><AppIcon name="layers" size="sm" /></span>
          <div>
            <strong>{{ resourceImpact(selectedResource.id) }}</strong>
            <p>
              这是共享数据源的统一配置。需要只改一处时，请到“数据采集”选择对应工作流，再脱离共享设置。
            </p>
          </div>
        </div>

        <div class="metric-strip">
          <div>
            <span>来源地址</span>
            <strong class="mono">{{ selectedResource.options.location }}</strong>
          </div>
          <div>
            <span>最多读取</span>
            <strong>{{ selectedResource.options.limit }} 条</strong>
          </div>
          <div>
            <span>最近保存</span>
            <strong>{{ selectedResource.updatedAt }}</strong>
          </div>
        </div>

        <div class="detail-section">
          <div class="section-title-row">
            <div>
              <h3>从哪里取数据</h3>
              <p>数据源级设置会被所有使用位置继承。</p>
            </div>
          </div>
          <div class="resource-facts">
            <div>
              <span>采集器</span>
              <strong>{{ catalogItem(selectedResource.collector).label }}</strong>
            </div>
            <div>
              <span>密钥</span>
              <strong>{{ selectedResource.options.apiKey ? '已配置' : '未配置' }}</strong>
            </div>
            <div>
              <span>使用位置</span>
              <strong>{{ selectedResourceUsage.length }} 个工作流</strong>
            </div>
          </div>
          <div class="usage-list">
            <span v-for="workflow in selectedResourceUsage" :key="workflow.id" class="usage-chip">
              <AppIcon name="workflow" size="sm" />
              {{ workflow.name }}
            </span>
            <span v-if="!selectedResourceUsage.length" class="muted">暂未被工作流使用</span>
          </div>
        </div>

        <div class="detail-section">
          <div class="section-title-row">
            <div>
              <h3>取到后怎么整理</h3>
              <p>规则仍然是这份数据源里的 JSON，不再单独拆成另一类资源。</p>
            </div>
            <el-button text @click="copyJson(selectedResource.rules)">
              <AppIcon name="copy" size="sm" />
              复制 JSON
            </el-button>
          </div>
          <pre class="json-preview">{{ rulesToJson(selectedResource.rules) }}</pre>
          <div class="rule-summary">
            <AppIcon name="sliders" size="sm" />
            {{ resourceRuleSummary }}
          </div>
        </div>
      </section>
      <el-empty v-else description="选择一个数据源查看配置" />
    </div>
  </template>

  <el-dialog
    v-model="addCollectorOpen"
    :title="attachNewCollectorToWorkflow ? '新增采集器' : '新增数据源'"
    width="720px"
    destroy-on-close
  >
    <div class="dialog-intro">
      <span class="note-icon"><AppIcon name="plus" size="sm" /></span>
      <p>
        先告诉我从哪里取数据，处理规则可以稍后再细调。{{
          attachNewCollectorToWorkflow
            ? '保存后会加载到当前工作流，也会出现在资源配置中心。'
            : '保存后会出现在资源配置中心。'
        }}
      </p>
    </div>
    <div class="form-grid dialog-form">
      <el-form-item label="数据源名称">
        <el-input v-model="newCollectorDraft.name" placeholder="例如：客户反馈订阅" />
      </el-form-item>
      <el-form-item label="采集器类型">
        <el-select
          :model-value="newCollectorDraft.collector"
          @update:model-value="setNewCollectorType"
        >
          <el-option
            v-for="item in collectorCatalog"
            :key="item.key"
            :value="item.key"
            :label="item.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="catalogItem(newCollectorDraft.collector).locationLabel" class="span-2">
        <el-input
          v-model="newCollectorDraft.options.location"
          :placeholder="catalogItem(newCollectorDraft.collector).locationPlaceholder"
        />
      </el-form-item>
      <el-form-item label="接口密钥（可选）">
        <el-input v-model="newCollectorDraft.options.apiKey" type="password" show-password />
      </el-form-item>
      <el-form-item label="最多读取条数">
        <el-input-number
          v-model="newCollectorDraft.options.limit"
          :min="1"
          :max="10000"
          controls-position="right"
        />
      </el-form-item>
    </div>
    <div class="dialog-rule-header">
      <div>
        <h3>取到后怎么整理</h3>
        <p class="muted">可以先使用默认设置，之后在数据采集处继续调整。</p>
      </div>
      <el-radio-group
        :model-value="newCollectorRuleMode"
        size="small"
        @update:model-value="switchNewCollectorRuleMode"
      >
        <el-radio-button label="form">普通设置</el-radio-button>
        <el-radio-button label="json">高级 JSON</el-radio-button>
      </el-radio-group>
    </div>
    <div v-if="newCollectorRuleMode === 'form'" class="rule-form-grid dialog-rules">
      <el-form-item label="保留哪些内容" class="span-2">
        <el-checkbox-group v-model="newCollectorRuleForm.fields" class="field-options">
          <el-checkbox
            v-for="field in catalogItem(newCollectorDraft.collector).fieldOptions"
            :key="field.key"
            :label="field.key"
          >
            {{ field.label }}
          </el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="筛选内容">
        <el-select v-model="newCollectorRuleForm.filter">
          <el-option
            v-for="filter in catalogItem(newCollectorDraft.collector).filterOptions"
            :key="filter.value"
            :value="filter.value"
            :label="filter.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="排序方式">
        <el-select v-model="newCollectorRuleForm.sortBy" clearable placeholder="保持来源顺序">
          <el-option
            v-for="field in catalogItem(newCollectorDraft.collector).fieldOptions"
            :key="field.key"
            :value="field.key"
            :label="field.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="输出格式">
        <el-select v-model="newCollectorRuleForm.format">
          <el-option value="markdown" label="Markdown" />
          <el-option value="json" label="JSON" />
          <el-option value="text" label="纯文本" />
        </el-select>
      </el-form-item>
      <el-form-item class="span-2">
        <el-checkbox v-model="newCollectorRuleForm.descending">由新到旧排列</el-checkbox>
      </el-form-item>
    </div>
    <el-input
      v-else
      v-model="newCollectorRulesJson"
      type="textarea"
      :rows="10"
      class="json-input"
      spellcheck="false"
    />
    <template #footer>
      <el-button @click="addCollectorOpen = false">取消</el-button>
      <el-button type="primary" @click="saveNewCollector">
        <AppIcon name="check" size="sm" />
        {{ attachNewCollectorToWorkflow ? '保存并加载' : '保存数据源' }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="loadCollectorOpen" title="加载已有采集器" width="640px" destroy-on-close>
    <p class="muted dialog-description">
      选择一个已经配置好的数据源，加载到“{{
        selectedWorkflow?.name
      }}”。它仍然会和其他工作流共享同一份设置。
    </p>
    <el-input v-model="loadSearch" clearable placeholder="搜索数据源" class="dialog-search">
      <template #prefix><AppIcon name="search" size="sm" /></template>
    </el-input>
    <div class="load-list">
      <button
        v-for="source in filteredLoadResources"
        :key="source.id"
        type="button"
        class="load-row"
        @click="loadCollector(source.id)"
      >
        <span class="source-icon" :style="{ color: catalogItem(source.collector).tone }">
          <AppIcon :name="iconName(source)" />
        </span>
        <span class="source-row-main">
          <span class="source-row-title">
            <strong>{{ source.name }}</strong>
            <el-tag v-if="selectedWorkflow?.sourceIds.includes(source.id)" size="small" type="info">
              已加载
            </el-tag>
          </span>
          <span class="source-row-meta">
            {{ catalogItem(source.collector).label }} · {{ sourceUsageLabel(source.id) }}
          </span>
        </span>
        <AppIcon name="chevronRight" size="sm" />
      </button>
      <el-empty
        v-if="!filteredLoadResources.length"
        description="没有匹配的数据源"
        :image-size="64"
      />
    </div>
  </el-dialog>

  <el-dialog
    v-model="resourceEditorOpen"
    :title="`编辑数据源：${resourceDraft?.name ?? ''}`"
    width="720px"
    destroy-on-close
  >
    <template v-if="resourceDraft">
      <div class="sync-callout compact-callout">
        <span class="sharing-icon"><AppIcon name="layers" size="sm" /></span>
        <div>
          <strong>{{ resourceImpact(resourceDraft.id) }}</strong>
          <p>只改一个工作流，请关闭窗口回到“数据采集”操作。</p>
        </div>
      </div>
      <div class="form-grid dialog-form">
        <el-form-item label="数据源名称"><el-input v-model="resourceDraft.name" /></el-form-item>
        <el-form-item label="采集器类型">
          <el-select v-model="resourceDraft.collector" disabled>
            <el-option
              v-for="item in collectorCatalog"
              :key="item.key"
              :value="item.key"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="catalogItem(resourceDraft.collector).locationLabel" class="span-2">
          <el-input v-model="resourceDraft.options.location" />
        </el-form-item>
        <el-form-item label="接口密钥（可选）">
          <el-input v-model="resourceDraft.options.apiKey" type="password" show-password />
        </el-form-item>
        <el-form-item label="最多读取条数">
          <el-input-number
            v-model="resourceDraft.options.limit"
            :min="1"
            :max="10000"
            controls-position="right"
          />
        </el-form-item>
      </div>
      <div class="inline-setting">
        <el-switch v-model="resourceDraft.enabled" />
        <div>
          <strong>启用这个数据源</strong>
          <span>停用只影响后续运行，不会删除使用位置。</span>
        </div>
      </div>
      <div class="dialog-rule-header">
        <div>
          <h3>取到后怎么整理</h3>
          <p class="muted">处理规则随数据源一起保存。</p>
        </div>
        <el-radio-group
          :model-value="resourceRuleMode"
          size="small"
          @update:model-value="switchResourceRuleMode"
        >
          <el-radio-button label="form">普通设置</el-radio-button>
          <el-radio-button label="json">高级 JSON</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="resourceRuleMode === 'form'" class="rule-form-grid dialog-rules">
        <el-form-item label="保留哪些内容" class="span-2">
          <el-checkbox-group v-model="resourceRuleForm.fields" class="field-options">
            <el-checkbox
              v-for="field in catalogItem(resourceDraft.collector).fieldOptions"
              :key="field.key"
              :label="field.key"
            >
              {{ field.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="筛选内容">
          <el-select v-model="resourceRuleForm.filter">
            <el-option
              v-for="filter in catalogItem(resourceDraft.collector).filterOptions"
              :key="filter.value"
              :value="filter.value"
              :label="filter.label"
            />
            <el-option
              v-if="resourceRuleForm.filter === 'custom'"
              value="custom"
              label="已有高级筛选"
              disabled
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排序方式">
          <el-select v-model="resourceRuleForm.sortBy" clearable placeholder="保持来源顺序">
            <el-option
              v-for="field in catalogItem(resourceDraft.collector).fieldOptions"
              :key="field.key"
              :value="field.key"
              :label="field.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="输出格式">
          <el-select v-model="resourceRuleForm.format">
            <el-option value="markdown" label="Markdown" />
            <el-option value="json" label="JSON" />
            <el-option value="text" label="纯文本" />
          </el-select>
        </el-form-item>
        <el-form-item class="span-2">
          <el-checkbox v-model="resourceRuleForm.descending">由新到旧排列</el-checkbox>
        </el-form-item>
      </div>
      <el-input
        v-else
        v-model="resourceRulesJson"
        type="textarea"
        :rows="10"
        class="json-input"
        spellcheck="false"
      />
    </template>
    <template #footer>
      <el-button @click="resourceEditorOpen = false">取消</el-button>
      <el-button type="primary" @click="saveResource">
        <AppIcon name="check" size="sm" />
        保存并同步
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.demo-tag {
  margin-right: 4px;
}
.view-switcher {
  flex-shrink: 0;
}
.demo-alert,
.collection-note,
.sync-callout,
.sharing-banner {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #f8fbff;
  color: #1e3a8a;
}
.demo-alert {
  padding: 14px 16px;
  margin-bottom: 18px;
}
.demo-alert strong,
.collection-note strong,
.sync-callout strong,
.sharing-banner strong {
  display: block;
  font-size: 13px;
}
.demo-alert p,
.collection-note p,
.sync-callout p,
.sharing-banner p {
  margin: 4px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}
.alert-mark,
.note-icon,
.sharing-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  border-radius: 6px;
  background: #dbeafe;
  color: #2563eb;
}
.surface-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}
.workflow-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  margin-bottom: 18px;
}
.workflow-picker {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 260px;
}
.workflow-select {
  width: 220px;
}
.workflow-stats {
  display: flex;
  gap: 16px;
  color: var(--muted);
  font-size: 12px;
}
.collection-layout,
.resource-layout {
  display: grid;
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}
.source-list-panel,
.resource-list-panel {
  min-height: 680px;
  overflow: hidden;
}
.panel-heading,
.detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px;
  border-bottom: 1px solid var(--border);
}
.panel-heading h2,
.resource-toolbar h2 {
  margin: 4px 0 0;
  font-size: 18px;
}
.panel-heading h2 span,
.compact-heading h2 span {
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
}
.eyebrow {
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.source-actions {
  display: flex;
  gap: 8px;
  padding: 16px 20px 4px;
}
.source-search,
.resource-search,
.dialog-search {
  margin: 12px 20px;
  width: calc(100% - 40px);
}
.source-list,
.resource-list {
  padding: 4px 10px 10px;
}
.source-row,
.resource-row,
.load-row {
  display: flex;
  width: 100%;
  gap: 10px;
  align-items: center;
  padding: 12px 10px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.source-row:hover,
.resource-row:hover,
.load-row:hover {
  background: #f8fafc;
  border-color: var(--border);
}
.source-row.selected,
.resource-row.selected {
  background: #eff6ff;
  border-color: #93c5fd;
}
.source-icon,
.large-source-icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 7px;
  background: #f1f5f9;
}
.source-icon {
  width: 30px;
  height: 30px;
}
.large-source-icon {
  width: 42px;
  height: 42px;
  background: #eff6ff;
}
.source-row-main,
.resource-row-main {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 3px;
}
.source-row-title {
  display: flex;
  gap: 6px;
  align-items: center;
  min-width: 0;
}
.source-row-title strong,
.source-row-meta,
.local-mark {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-row-title strong {
  font-size: 13px;
}
.source-row-meta,
.local-mark {
  color: var(--muted);
  font-size: 11px;
}
.local-mark {
  color: #b45309;
}
.panel-footnote {
  padding: 12px 20px;
  margin: 0;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
}
.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 5px;
  border-radius: 50%;
  background: #22c55e;
}
.detail-heading {
  padding: 24px;
}
.detail-identity {
  display: flex;
  gap: 12px;
  min-width: 0;
  align-items: center;
}
.detail-identity h2 {
  margin: 3px 0 0;
  font-size: 20px;
  overflow-wrap: anywhere;
}
.detail-identity p {
  margin: 4px 0 0;
  font-size: 12px;
}
.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}
.sharing-banner,
.sync-callout {
  padding: 13px 16px;
  margin: 18px 22px 0;
}
.sharing-banner.detached {
  border-color: #f6c453;
  background: #fffbeb;
  color: #92400e;
}
.sharing-banner.detached .sharing-icon {
  background: #fef3c7;
  color: #b45309;
}
.sharing-banner .el-button {
  margin-left: auto;
  flex-shrink: 0;
}
.editor-section,
.detail-section {
  padding: 22px;
  border-bottom: 1px solid var(--border);
}
.section-title-row,
.dialog-rule-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.section-title-row h3,
.dialog-rule-header h3 {
  margin: 0;
  font-size: 15px;
}
.section-title-row p,
.dialog-rule-header p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.55;
}
.form-grid,
.rule-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
  margin-top: 16px;
}
.field-options {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 16px;
}
.span-2 {
  grid-column: 1 / -1;
}
.el-form-item {
  margin-bottom: 16px;
}
.inline-setting {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 7px;
}
.inline-setting > div {
  display: grid;
  gap: 3px;
}
.inline-setting span {
  color: var(--muted);
  font-size: 12px;
}
.rules-section {
  border-bottom: 0;
}
.advanced-editor {
  margin-top: 16px;
}
.json-input :deep(textarea),
.json-preview {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
}
.advanced-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 6px;
  color: var(--muted);
  font-size: 12px;
}
.rule-summary {
  display: flex;
  gap: 7px;
  align-items: center;
  padding: 10px 12px;
  margin-top: 14px;
  border-radius: 6px;
  background: #f8fafc;
  color: var(--muted);
  font-size: 12px;
}
.editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 22px;
  border-top: 1px solid var(--border);
}
.save-hint {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}
.collection-note {
  padding: 14px 16px;
  margin-top: 18px;
  border-color: var(--border);
  background: var(--surface);
  color: inherit;
}
.collection-note p {
  color: var(--muted);
}
.resource-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 20px;
  margin-bottom: 18px;
}
.resource-toolbar p {
  max-width: 640px;
  margin: 5px 0 0;
  font-size: 12px;
}
.resource-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.resource-toolbar-actions .resource-search {
  width: 190px;
  margin: 0;
}
.resource-filter {
  width: 130px;
}
.resource-list-panel {
  min-height: 620px;
}
.compact-heading {
  padding: 18px 20px;
}
.resource-detail-panel {
  overflow: hidden;
}
.sync-callout {
  margin-top: 20px;
}
.compact-callout {
  margin: 0 0 18px;
}
.metric-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 20px;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.metric-strip > div {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 14px 22px;
  border-right: 1px solid var(--border);
}
.metric-strip > div:last-child {
  border-right: 0;
}
.metric-strip span,
.resource-facts span {
  color: var(--muted);
  font-size: 12px;
}
.metric-strip strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.resource-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.resource-facts > div {
  display: grid;
  gap: 5px;
  min-width: 0;
}
.resource-facts strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.usage-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}
.usage-chip {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  padding: 6px 9px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: #334155;
  font-size: 12px;
}
.json-preview {
  max-height: 230px;
  margin: 16px 0 0;
  padding: 14px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #f8fafc;
  color: #334155;
}
.dialog-intro {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px;
  margin-bottom: 16px;
  border-radius: 6px;
  background: #f8fafc;
}
.dialog-intro p,
.dialog-description {
  margin: 2px 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
.dialog-form {
  margin-top: 0;
}
.dialog-rule-header {
  align-items: center;
  padding-top: 12px;
  margin: 2px 0 8px;
  border-top: 1px solid var(--border);
}
.dialog-rules {
  margin-top: 8px;
}
.load-list {
  max-height: 390px;
  padding: 4px 8px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 7px;
}
.load-row {
  border-bottom: 1px solid var(--border);
  border-radius: 0;
}
.load-row:last-child {
  border-bottom: 0;
}
@media (max-width: 1100px) {
  .collection-layout,
  .resource-layout {
    grid-template-columns: 1fr;
  }
  .source-list-panel,
  .resource-list-panel {
    min-height: 0;
  }
  .source-list,
  .resource-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .panel-footnote {
    grid-column: 1 / -1;
  }
}
@media (max-width: 720px) {
  .view-switcher {
    width: 100%;
  }
  .view-switcher :deep(.el-radio-button) {
    flex: 1;
  }
  .workflow-bar,
  .resource-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .workflow-picker {
    align-items: stretch;
    flex-direction: column;
    gap: 7px;
  }
  .workflow-select {
    width: 100%;
  }
  .workflow-stats {
    flex-wrap: wrap;
    gap: 8px 14px;
  }
  .source-list,
  .resource-list {
    grid-template-columns: 1fr;
  }
  .panel-heading,
  .detail-heading {
    padding: 16px;
    flex-direction: column;
  }
  .detail-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .sharing-banner,
  .sync-callout {
    margin-right: 16px;
    margin-left: 16px;
  }
  .sharing-banner {
    flex-wrap: wrap;
  }
  .sharing-banner .el-button {
    margin-left: 40px;
  }
  .editor-section,
  .detail-section {
    padding: 16px;
  }
  .section-title-row,
  .dialog-rule-header {
    align-items: stretch;
    flex-direction: column;
  }
  .form-grid,
  .rule-form-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }
  .span-2 {
    grid-column: auto;
  }
  .metric-strip,
  .resource-facts {
    grid-template-columns: 1fr;
  }
  .metric-strip > div {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }
  .metric-strip > div:last-child {
    border-bottom: 0;
  }
  .resource-toolbar-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .resource-toolbar-actions .resource-search,
  .resource-filter {
    width: 100%;
  }
  .editor-footer {
    align-items: stretch;
    flex-direction: column;
  }
  .advanced-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
:global(.dark) .demo-alert,
:global(.dark) .sync-callout,
:global(.dark) .sharing-banner {
  border-color: #1d4ed8;
  background: #172554;
  color: #dbeafe;
}
:global(.dark) .demo-alert p,
:global(.dark) .sync-callout p,
:global(.dark) .sharing-banner p {
  color: #cbd5e1;
}
:global(.dark) .sharing-banner.detached {
  border-color: #92400e;
  background: #422006;
  color: #fde68a;
}
:global(.dark) .source-row:hover,
:global(.dark) .resource-row:hover,
:global(.dark) .load-row:hover,
:global(.dark) .source-row.selected,
:global(.dark) .resource-row.selected {
  background: #172554;
}
:global(.dark) .source-icon,
:global(.dark) .large-source-icon,
:global(.dark) .dialog-intro,
:global(.dark) .rule-summary,
:global(.dark) .json-preview {
  background: #0f172a;
}
:global(.dark) .json-preview {
  color: #cbd5e1;
}
</style>
