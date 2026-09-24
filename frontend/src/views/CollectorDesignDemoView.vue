<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/shared/ui/icons/AppIcon.vue'
import PageHeader from '@/shared/ui/PageHeader.vue'

// ==========================================
// 1. 类型定义
// ==========================================
type CollectorType = 'logs' | 'history' | 'mock'
type SourcePolicy = 'stop' | 'notice' | 'skip'

// 不规则字段抽取规则定义
interface FieldExtractionRule {
  id: string
  targetField: string
  sourceType: 'json_path' | 'regex' | 'default_value'
  expression: string // e.g. "$.meta.trace_id" 或 "client=(?P<client_ip>\d+\.\d+\.\d+\.\d+)"
  fallbackValue?: string
  description?: string
}

// 采集器高级扩展设置 (对齐真实系统 SourceConfig 与不规则字段抽取)
interface SourceAdvancedSettings {
  extractions: FieldExtractionRule[]
  filterExpr: string // 原始布尔表达式，如: status >= 500 or latency_ms > 1000
  excludeFields: string[] // 脱敏/排除字段
  timeout: number // 采集超时 (秒)
  onError: SourcePolicy // 报错时策略
  onMissing: SourcePolicy // 目标不存在时策略
  onEmpty: SourcePolicy // 采集结果为空时策略
  onFilteredEmpty: SourcePolicy // 过滤后为空时策略
  rawOptionsJson?: string // 原始底层 Options JSON
  rawSettersJson?: string // 原始底层 Setters JSON
}

interface CentralDataSource {
  id: string
  name: string
  collector: CollectorType
  status: 'enabled' | 'paused'
  description: string
  options: {
    path: string
    maxLines: number
    apiKey?: string
  }
  rules: {
    fields: string[]
    filterLevel?: string[]
    sortBy: string
    descending: boolean
    format: 'markdown' | 'text' | 'jsonl'
  }
  // 高级设置 (不规则字段抽取、异常策略与原始Setters)
  advanced: SourceAdvancedSettings
  updatedAt: string
}

interface WorkflowSourceBinding {
  bindingId: string
  sourceId: string
  mode: 'linked' | 'detached' // linked: 跟随全局模板 | detached: 独立专属配置
  expandedAdvanced?: boolean // UI卡片是否展开不规则字段预览
  customConfig?: {
    name: string
    collector?: CollectorType
    description?: string
    options: {
      path: string
      maxLines: number
    }
    rules: {
      fields: string[]
      filterLevel?: string[]
      sortBy: string
      descending: boolean
      format: 'markdown' | 'text' | 'jsonl'
    }
    advanced: SourceAdvancedSettings
  }
}

interface AnalysisTask {
  id: string
  name: string
  model: string
  prompt: string
}

interface FanInConfig {
  enabled: boolean
  order: string[]
  model: string
  prompt: string
  separator?: string
}

interface ChannelItem {
  id: string
  name: string
  type: 'email' | 'webhook' | 'file'
  target: string
}

interface WorkflowDefinitionDemo {
  id: string
  name: string
  description: string
  cron: string
  // 1. 数据采集
  sources: WorkflowSourceBinding[]
  // 工作流级采集高级运行参数 (来自真实系统 WorkflowDefinition)
  collectionConcurrency: number
  onAllEmpty: SourcePolicy
  inputSeparator: string
  includeCounts: boolean
  // 2. 并行 AI 分析
  analyses: AnalysisTask[]
  // 3. 汇聚汇总
  fanIn: FanInConfig
  // 4. 渠道分发
  channels: string[]
}

// ==========================================
// 2. 模拟数据：资源配置中心 (全局数据源、模型与渠道)
// ==========================================
const centralDataSources = ref<CentralDataSource[]>([
  {
    id: 'src_cluster_logs',
    name: '应用集群运行日志',
    collector: 'logs',
    status: 'enabled',
    description: '采集生产业务集群的标准应用日志，包含不规则嵌套字段抽取与异常策略。',
    options: { path: '/var/log/logagent/app.jsonl', maxLines: 500 },
    rules: {
      fields: ['time', 'level', 'module', 'message'],
      filterLevel: ['error', 'warning'],
      sortBy: 'time',
      descending: true,
      format: 'markdown',
    },
    advanced: {
      extractions: [
        {
          id: 'ex_1',
          targetField: 'trace_id',
          sourceType: 'json_path',
          expression: '$.meta.trace.id',
          fallbackValue: 'none',
          description: '从深层嵌套对象抽取链路追踪 ID',
        },
        {
          id: 'ex_2',
          targetField: 'client_ip',
          sourceType: 'regex',
          expression: 'client=(?P<client_ip>\\d+\\.\\d+\\.\\d+\\.\\d+)',
          fallbackValue: '127.0.0.1',
          description: '从半结构化原始正文捕获 Client IP',
        },
        {
          id: 'ex_3',
          targetField: 'cluster_env',
          sourceType: 'default_value',
          expression: 'prod-shanghai-01',
          fallbackValue: 'prod-shanghai-01',
          description: '附加环境变量标签',
        },
      ],
      filterExpr: "status_code >= 500 or level == 'error'",
      excludeFields: ['authorization', 'user_password'],
      timeout: 45,
      onError: 'notice',
      onMissing: 'notice',
      onEmpty: 'notice',
      onFilteredEmpty: 'skip',
    },
    updatedAt: '今天 15:30',
  },
  {
    id: 'src_gateway_access',
    name: 'API 网关访问日志 (半结构化 Nginx)',
    collector: 'logs',
    status: 'enabled',
    description: '入口网关 Nginx 流量日志，配置复杂正则提取与慢查过滤。',
    options: { path: '/var/log/nginx/access.log', maxLines: 1000 },
    rules: {
      fields: ['time', 'client_ip', 'method', 'uri', 'status', 'latency_ms'],
      filterLevel: [],
      sortBy: 'latency_ms',
      descending: true,
      format: 'markdown',
    },
    advanced: {
      extractions: [
        {
          id: 'ex_4',
          targetField: 'user_agent_device',
          sourceType: 'regex',
          expression: '(?P<user_agent_device>Mobile|Tablet|PC|Bot)',
          fallbackValue: 'PC',
          description: '从 User-Agent 提取终端设备类别',
        },
        {
          id: 'ex_5',
          targetField: 'upstream_service',
          sourceType: 'json_path',
          expression: '$.upstream.target_svc',
          fallbackValue: 'gateway-core',
          description: '提取网关目标微服务路由标识',
        },
      ],
      filterExpr: 'latency_ms > 1500 or status >= 500',
      excludeFields: ['cookie', 'bearer_token'],
      timeout: 60,
      onError: 'skip',
      onMissing: 'notice',
      onEmpty: 'skip',
      onFilteredEmpty: 'skip',
    },
    updatedAt: '2026-09-21',
  },
  {
    id: 'src_workflow_history',
    name: '历史巡检归档记录',
    collector: 'history',
    status: 'enabled',
    description: '读取过往工作流分析结论与诊断摘要，用于趋势对比与复盘。',
    options: { path: 'daily-inspection', maxLines: 15 },
    rules: {
      fields: ['session_id', 'status', 'created_at', 'content'],
      filterLevel: [],
      sortBy: 'created_at',
      descending: true,
      format: 'markdown',
    },
    advanced: {
      extractions: [
        {
          id: 'ex_6',
          targetField: 'ai_root_cause_tag',
          sourceType: 'json_path',
          expression: '$.diagnosis.tags[0]',
          fallbackValue: '未标注',
          description: '提取上期巡检标记的第一根因',
        },
      ],
      filterExpr: "status in ('failed', 'partial')",
      excludeFields: [],
      timeout: 30,
      onError: 'notice',
      onMissing: 'skip',
      onEmpty: 'notice',
      onFilteredEmpty: 'notice',
    },
    updatedAt: '昨天 18:20',
  },
  {
    id: 'src_mock_orders',
    name: '离线订单测试样例 (深层业务对象)',
    collector: 'mock',
    status: 'enabled',
    description: '用于测试与离线演示的静态订单流水桩数据，演示深层字段解析。',
    options: { path: 'samples/order-mock.jsonl', maxLines: 100 },
    rules: {
      fields: ['order_id', 'user_id', 'amount', 'status'],
      filterLevel: [],
      sortBy: 'order_id',
      descending: false,
      format: 'jsonl',
    },
    advanced: {
      extractions: [
        {
          id: 'ex_7',
          targetField: 'pay_channel',
          sourceType: 'json_path',
          expression: '$.payment.channel_name',
          fallbackValue: 'wechat_pay',
          description: '抽取支付渠道名称',
        },
        {
          id: 'ex_8',
          targetField: 'item_count',
          sourceType: 'json_path',
          expression: '$.cart.items.length',
          fallbackValue: '1',
          description: '计算购物车购买商品条目数',
        },
      ],
      filterExpr: 'amount >= 500',
      excludeFields: ['card_cvv'],
      timeout: 20,
      onError: 'stop',
      onMissing: 'stop',
      onEmpty: 'stop',
      onFilteredEmpty: 'stop',
    },
    updatedAt: '2026-09-18',
  },
])

const availableModels = [
  { id: 'deepseek-r1', name: 'DeepSeek-R1 (推理思维链)' },
  { id: 'qwen-2.5-72b', name: 'Qwen 2.5 72B (日志与结构化分析)' },
  { id: 'claude-3-5-sonnet', name: 'Claude 3.5 Sonnet (综合报告撰写)' },
  { id: 'gpt-4o', name: 'GPT-4o (通用分析)' },
]

const centralChannels = ref<ChannelItem[]>([
  { id: 'chan_ops_email', name: '运维专家团队邮件', type: 'email', target: 'ops-team@company.com' },
  { id: 'chan_dingtalk_webhook', name: '大促值班钉钉群 Webhook', type: 'webhook', target: 'https://oapi.dingtalk.com/robot/send?...' },
  { id: 'chan_archive_file', name: '本地报告文件归档', type: 'file', target: 'data/notifications/daily-summary.txt' },
])

// ==========================================
// 3. 模拟数据：工作流列表 (完整 4 阶段配置)
// ==========================================
const workflows = ref<WorkflowDefinitionDemo[]>([
  {
    id: 'wf_daily_health',
    name: '每日集群运行体检与告警归因',
    description: '每天上午 9 点自动采集应用错误日志与历史基线，由 AI 并行分析后汇总通知',
    cron: '0 9 * * *',
    // 1. 数据采集
    sources: [
      {
        bindingId: 'b_1',
        sourceId: 'src_cluster_logs',
        mode: 'linked',
        expandedAdvanced: false,
      },
      {
        bindingId: 'b_2',
        sourceId: 'src_workflow_history',
        mode: 'detached',
        expandedAdvanced: false,
        customConfig: {
          name: '历史巡检归档 (本流专属只读最近3次)',
          options: { path: 'daily-inspection', maxLines: 3 },
          rules: {
            fields: ['session_id', 'status', 'content'],
            filterLevel: [],
            sortBy: 'created_at',
            descending: true,
            format: 'markdown',
          },
          advanced: {
            extractions: [
              {
                id: 'ex_6_custom',
                targetField: 'ai_root_cause_tag',
                sourceType: 'json_path',
                expression: '$.diagnosis.tags[0]',
                fallbackValue: '未标注',
                description: '提取上期巡检标记的第一根因',
              },
            ],
            filterExpr: "status == 'failed'",
            excludeFields: [],
            timeout: 20,
            onError: 'notice',
            onMissing: 'skip',
            onEmpty: 'notice',
            onFilteredEmpty: 'notice',
          },
        },
      },
    ],
    // 工作流级采集高级运行参数 (对齐真实系统参数)
    collectionConcurrency: 2,
    onAllEmpty: 'notice',
    inputSeparator: '\n\n',
    includeCounts: true,
    // 2. 并行 AI 分析
    analyses: [
      {
        id: 'task_root_cause',
        name: '错误根因与故障定位',
        model: 'qwen-2.5-72b',
        prompt: '仔细分析日志中的异常堆栈和错误频次，列出最核心的 3 个潜在根因与影响面。',
      },
      {
        id: 'task_perf_bottleneck',
        name: '性能与长事务诊断',
        model: 'deepseek-r1',
        prompt: '识别耗时突增的事务与数据库调用，指出潜在的连接池或慢查瓶颈。',
      },
    ],
    // 3. 汇聚汇总
    fanIn: {
      enabled: true,
      order: ['$input', 'task_root_cause', 'task_perf_bottleneck'],
      model: 'claude-3-5-sonnet',
      prompt: '将输入背景和两个 AI 专家的分析结论综合提炼为一份高层易读的系统健康体检简报，列出紧急程度和行动建议。',
    },
    // 4. 渠道分发
    channels: ['chan_ops_email', 'chan_dingtalk_webhook'],
  },
  {
    id: 'wf_security_audit',
    name: '安全访问与越权审计',
    description: '持续扫描高危接口调用与异常 IP 行为',
    cron: '0 * * * *',
    sources: [
      {
        bindingId: 'b_3',
        sourceId: 'src_cluster_logs',
        mode: 'linked',
        expandedAdvanced: false,
      },
      {
        bindingId: 'b_4',
        sourceId: 'src_gateway_access',
        mode: 'linked',
        expandedAdvanced: false,
      },
    ],
    collectionConcurrency: 3,
    onAllEmpty: 'skip',
    inputSeparator: '\n---\n',
    includeCounts: false,
    analyses: [
      {
        id: 'task_threat_detection',
        name: '未授权与越权访问检测',
        model: 'deepseek-r1',
        prompt: '检查 URI 中是否存在越权注入行为，标记涉嫌恶意的 Client IP 列表。',
      },
    ],
    fanIn: {
      enabled: false,
      order: [],
      model: '',
      prompt: '',
    },
    channels: ['chan_dingtalk_webhook'],
  },
])

const route = useRoute()
const router = useRouter()

// 导航当前活动标签：'workflows' (工作流管理) VS 'resources' (资源配置中心)
const activeNav = ref<'workflows' | 'resources'>('workflows')
const selectedWorkflowId = ref('wf_daily_health')

// 流程阶段分步查看：'sources' (1.采集) | 'analyses' (2.分析) | 'fanin' (3.汇总) | 'channels' (4.分发) | 'all' (全览)
const activeStage = ref<'sources' | 'analyses' | 'fanin' | 'channels' | 'all'>('sources')

// 同步更新 Vue Router query，实现点击选择、前进后退及刷新状态保持
function syncRouteQuery() {
  router.replace({
    query: {
      ...route.query,
      tab: activeNav.value,
      wf: selectedWorkflowId.value,
      stage: activeStage.value,
    },
  })
}

function selectNav(nav: 'workflows' | 'resources') {
  activeNav.value = nav
  syncRouteQuery()
}

function selectWorkflow(id: string) {
  selectedWorkflowId.value = id
  syncRouteQuery()
}

function selectStage(stage: 'sources' | 'analyses' | 'fanin' | 'channels' | 'all') {
  activeStage.value = stage
  syncRouteQuery()
}

// 采集源顺序调整 (真实反映采集流水线先后排序)
function moveSourceUp(index: number) {
  if (index <= 0) return
  const list = activeWorkflow.value.sources
  const [item] = list.splice(index, 1)
  list.splice(index - 1, 0, item)
  ElMessage.success('已调整采集源顺序')
}

function moveSourceDown(index: number) {
  const list = activeWorkflow.value.sources
  if (index >= list.length - 1) return
  const [item] = list.splice(index, 1)
  list.splice(index + 1, 0, item)
  ElMessage.success('已调整采集源顺序')
}

// 并行 AI 分析任务顺序调整 (直接决定聚合汇总与报告各段结论的输入排序)
function moveAnalysisUp(index: number) {
  if (index <= 0) return
  const list = activeWorkflow.value.analyses
  const [item] = list.splice(index, 1)
  list.splice(index - 1, 0, item)
  ElMessage.success(`已调整分析任务顺序`)
}

function moveAnalysisDown(index: number) {
  const list = activeWorkflow.value.analyses
  if (index >= list.length - 1) return
  const [item] = list.splice(index, 1)
  list.splice(index + 1, 0, item)
  ElMessage.success(`已调整分析任务顺序`)
}

onMounted(() => {
  const q = route.query
  if (q.tab === 'workflows' || q.tab === 'resources') {
    activeNav.value = q.tab
  }
  if (typeof q.wf === 'string' && workflows.value.some((w) => w.id === q.wf)) {
    selectedWorkflowId.value = q.wf
  }
  if (typeof q.stage === 'string' && ['sources', 'analyses', 'fanin', 'channels', 'all'].includes(q.stage)) {
    activeStage.value = q.stage as any
  }
})

watch(
  () => route.query,
  (q) => {
    if (q.tab === 'workflows' || q.tab === 'resources') {
      activeNav.value = q.tab
    }
    if (typeof q.wf === 'string' && workflows.value.some((w) => w.id === q.wf)) {
      selectedWorkflowId.value = q.wf
    }
    if (typeof q.stage === 'string' && ['sources', 'analyses', 'fanin', 'channels', 'all'].includes(q.stage)) {
      activeStage.value = q.stage as any
    }
  },
)

// 工作流级高级运行参数是否展开
const isWorkflowAdvancedExpanded = ref(false)

const activeWorkflow = computed(
  () => workflows.value.find((w) => w.id === selectedWorkflowId.value) ?? workflows.value[0],
)

// 引用关系辅助计算
function getLinkedWorkflows(sourceId: string): WorkflowDefinitionDemo[] {
  return workflows.value.filter((w) =>
    w.sources.some((s) => s.sourceId === sourceId && s.mode === 'linked'),
  )
}

function getLinkedCount(sourceId: string): number {
  return getLinkedWorkflows(sourceId).length
}

function getCentralSource(id: string): CentralDataSource | undefined {
  return centralDataSources.value.find((s) => s.id === id)
}

// 辅助方法：获取当前绑定生效的完整配置 (如果是 detached 则取 customConfig，否则取 central)
function getEffectiveSourceConfig(binding: WorkflowSourceBinding) {
  if (binding.mode === 'detached' && binding.customConfig) {
    const central = getCentralSource(binding.sourceId)
    return {
      collector: central?.collector || 'logs',
      ...binding.customConfig,
    }
  }
  return getCentralSource(binding.sourceId)
}

// ==========================================
// 4. 阶段 1：数据采集处的交互操作 (加载已有数据源、新增采集器、保存数据源、脱离独立)
// ==========================================
const loadSourceModal = ref(false)

function openLoadSourceModal() {
  loadSourceModal.value = true
}

function isSourceAlreadyLoaded(sourceId: string): boolean {
  return activeWorkflow.value.sources.some((s) => s.sourceId === sourceId)
}

function loadSourceIntoWorkflow(src: CentralDataSource) {
  if (isSourceAlreadyLoaded(src.id)) {
    ElMessage.warning(`数据源「${src.name}」已存在于当前工作流中！`)
    return
  }
  activeWorkflow.value.sources.push({
    bindingId: `b_${Date.now()}`,
    sourceId: src.id,
    mode: 'linked',
    expandedAdvanced: false,
  })
  ElMessage.success(`已加载数据源「${src.name}」！将与全局资源配置中心保持同步。`)
  loadSourceModal.value = false
}

const sourceDrawer = ref(false)
const isNewSourceMode = ref(false)
const drawerTab = ref<'basic' | 'advanced'>('basic')
const showRawJsonEditor = ref(false)
const activeEditingBinding = ref<WorkflowSourceBinding | null>(null)
const activeEditingCentral = ref<CentralDataSource | null>(null)

// 采集器表单草稿 (包含常规与高级设置)
const sourceForm = ref({
  id: '',
  name: '',
  collector: 'logs' as CollectorType,
  description: '',
  options: { path: '', maxLines: 200, apiKey: '' },
  rules: {
    fieldsStr: '',
    filterLevel: [] as string[],
    sortBy: '',
    descending: true,
    format: 'markdown' as 'markdown' | 'text' | 'jsonl',
  },
  advanced: {
    extractions: [] as FieldExtractionRule[],
    filterExpr: '',
    excludeFieldsStr: '',
    timeout: 60,
    onError: 'notice' as SourcePolicy,
    onMissing: 'notice' as SourcePolicy,
    onEmpty: 'notice' as SourcePolicy,
    onFilteredEmpty: 'skip' as SourcePolicy,
    rawOptionsJson: '',
    rawSettersJson: '',
  },
})

// [2. 新增采集器]
function openCreateSource() {
  isNewSourceMode.value = true
  drawerTab.value = 'basic'
  showRawJsonEditor.value = false
  activeEditingBinding.value = null
  activeEditingCentral.value = null
  sourceForm.value = {
    id: `src_${Date.now().toString().slice(-4)}`,
    name: '新建采集源',
    collector: 'logs',
    description: '在当前工作流中新建的数据源',
    options: { path: '/var/log/service.log', maxLines: 200, apiKey: '' },
    rules: {
      fieldsStr: 'time, level, message',
      filterLevel: ['error'],
      sortBy: 'time',
      descending: true,
      format: 'markdown',
    },
    advanced: {
      extractions: [
        {
          id: `ex_${Date.now()}`,
          targetField: 'trace_id',
          sourceType: 'json_path',
          expression: '$.meta.trace.id',
          fallbackValue: 'none',
          description: '从 JSON 嵌套对象抽取链路追踪 ID',
        },
      ],
      filterExpr: '',
      excludeFieldsStr: '',
      timeout: 60,
      onError: 'notice',
      onMissing: 'notice',
      onEmpty: 'notice',
      onFilteredEmpty: 'skip',
      rawOptionsJson: '',
      rawSettersJson: '',
    },
  }
  syncRawJson()
  sourceDrawer.value = true
}

// [3. 编辑采集器]
function openEditBinding(binding: WorkflowSourceBinding) {
  isNewSourceMode.value = false
  drawerTab.value = 'basic'
  showRawJsonEditor.value = false
  activeEditingBinding.value = binding
  activeEditingCentral.value = null

  const isDetached = binding.mode === 'detached'
  const central = getCentralSource(binding.sourceId)
  const cfg = isDetached && binding.customConfig ? binding.customConfig : central
  if (!cfg) return

  const adv = cfg.advanced || {
    extractions: [],
    filterExpr: '',
    excludeFields: [],
    timeout: 60,
    onError: 'notice',
    onMissing: 'notice',
    onEmpty: 'notice',
    onFilteredEmpty: 'skip',
  }

  sourceForm.value = {
    id: binding.sourceId,
    name: cfg.name,
    collector: (cfg as CentralDataSource).collector ?? 'logs',
    description: (cfg as CentralDataSource).description ?? '',
    options: { ...cfg.options, apiKey: '' },
    rules: {
      fieldsStr: cfg.rules.fields.join(', '),
      filterLevel: cfg.rules.filterLevel ? [...cfg.rules.filterLevel] : [],
      sortBy: cfg.rules.sortBy,
      descending: cfg.rules.descending,
      format: cfg.rules.format,
    },
    advanced: {
      extractions: adv.extractions ? adv.extractions.map((e) => ({ ...e })) : [],
      filterExpr: adv.filterExpr || '',
      excludeFieldsStr: adv.excludeFields ? adv.excludeFields.join(', ') : '',
      timeout: adv.timeout ?? 60,
      onError: adv.onError ?? 'notice',
      onMissing: adv.onMissing ?? 'notice',
      onEmpty: adv.onEmpty ?? 'notice',
      onFilteredEmpty: adv.onFilteredEmpty ?? 'skip',
      rawOptionsJson: '',
      rawSettersJson: '',
    },
  }
  syncRawJson()
  sourceDrawer.value = true
}

// 抽取规则快捷预设
function addExtractionPreset(preset: 'trace_id' | 'client_ip' | 'header') {
  if (preset === 'trace_id') {
    sourceForm.value.advanced.extractions.push({
      id: `ex_${Date.now()}`,
      targetField: 'trace_id',
      sourceType: 'json_path',
      expression: '$.meta.trace.id',
      fallbackValue: 'none',
      description: '从 JSON 嵌套对象抽取链路追踪 ID',
    })
  } else if (preset === 'client_ip') {
    sourceForm.value.advanced.extractions.push({
      id: `ex_${Date.now()}`,
      targetField: 'client_ip',
      sourceType: 'regex',
      expression: 'client=(?P<client_ip>\\d+\\.\\d+\\.\\d+\\.\\d+)',
      fallbackValue: '127.0.0.1',
      description: '从非结构化日志抽取 Client IP',
    })
  } else if (preset === 'header') {
    sourceForm.value.advanced.extractions.push({
      id: `ex_${Date.now()}`,
      targetField: 'req_id',
      sourceType: 'json_path',
      expression: '$.headers["x-request-id"]',
      fallbackValue: '',
      description: '从请求头中抽取 x-request-id',
    })
  }
  syncRawJson()
  ElMessage.success('已添加抽取规则预设')
}

function addCustomExtraction() {
  sourceForm.value.advanced.extractions.push({
    id: `ex_${Date.now()}`,
    targetField: `field_${sourceForm.value.advanced.extractions.length + 1}`,
    sourceType: 'json_path',
    expression: '$.detail.custom_path',
    fallbackValue: '',
    description: '自定义不规则字段抽取规则',
  })
  syncRawJson()
}

function removeExtraction(idx: number) {
  sourceForm.value.advanced.extractions.splice(idx, 1)
  syncRawJson()
}

function syncRawJson() {
  const optionsObj = {
    path: sourceForm.value.options.path,
    max_lines: sourceForm.value.options.maxLines,
    timeout: sourceForm.value.advanced.timeout,
    on_error: sourceForm.value.advanced.onError,
    on_missing: sourceForm.value.advanced.onMissing,
    on_empty: sourceForm.value.advanced.onEmpty,
    on_filtered_empty: sourceForm.value.advanced.onFilteredEmpty,
  }
  const settersObj = {
    fields: sourceForm.value.rules.fieldsStr.split(',').map((s) => s.trim()).filter(Boolean),
    filter_level: sourceForm.value.rules.filterLevel,
    sort_by: sourceForm.value.rules.sortBy,
    descending: sourceForm.value.rules.descending,
    format: sourceForm.value.rules.format,
    extractions: sourceForm.value.advanced.extractions,
    filter_expr: sourceForm.value.advanced.filterExpr,
    exclude_fields: sourceForm.value.advanced.excludeFieldsStr.split(',').map((s) => s.trim()).filter(Boolean),
  }
  sourceForm.value.advanced.rawOptionsJson = JSON.stringify(optionsObj, null, 2)
  sourceForm.value.advanced.rawSettersJson = JSON.stringify(settersObj, null, 2)
}

// [4. 脱离模板 (独立定制)]
async function detachSource(binding: WorkflowSourceBinding) {
  const central = getCentralSource(binding.sourceId)
  if (!central) return

  try {
    await ElMessageBox.confirm(
      `确定将「${central.name}」脱离全局模板吗？脱离后此工作流拥有独立定制参数（包含不规则字段规则），资源配置中心后续更新将不再同步此处。`,
      '脱离模板提示',
      { confirmButtonText: '确认脱离', cancelButtonText: '取消', type: 'info' },
    )
  } catch {
    return
  }

  binding.mode = 'detached'
  binding.customConfig = {
    name: `${central.name} (专属独立定制)`,
    options: { ...central.options },
    rules: {
      fields: [...central.rules.fields],
      filterLevel: central.rules.filterLevel ? [...central.rules.filterLevel] : [],
      sortBy: central.rules.sortBy,
      descending: central.rules.descending,
      format: central.rules.format,
    },
    advanced: {
      extractions: central.advanced.extractions.map((e) => ({ ...e })),
      filterExpr: central.advanced.filterExpr,
      excludeFields: [...central.advanced.excludeFields],
      timeout: central.advanced.timeout,
      onError: central.advanced.onError,
      onMissing: central.advanced.onMissing,
      onEmpty: central.advanced.onEmpty,
      onFilteredEmpty: central.advanced.onFilteredEmpty,
    },
  }
  ElMessage.success('已脱离全局模板！后续修改仅影响本工作流。')
}

// [5. 保存数据源 (发布/同步至资源配置中心，免弹窗确认)]
function saveSourceToCentral(binding: WorkflowSourceBinding) {
  const currentConfig = getEffectiveSourceConfig(binding)
  if (!currentConfig) return

  const existingCentral = getCentralSource(binding.sourceId)
  if (existingCentral) {
    existingCentral.name = currentConfig.name
    existingCentral.description = currentConfig.description || existingCentral.description
    existingCentral.options = { ...currentConfig.options }
    existingCentral.rules = {
      fields: [...currentConfig.rules.fields],
      filterLevel: currentConfig.rules.filterLevel ? [...currentConfig.rules.filterLevel] : [],
      sortBy: currentConfig.rules.sortBy,
      descending: currentConfig.rules.descending,
      format: currentConfig.rules.format,
    }
    existingCentral.advanced = {
      extractions: currentConfig.advanced.extractions.map((e) => ({ ...e })),
      filterExpr: currentConfig.advanced.filterExpr,
      excludeFields: [...currentConfig.advanced.excludeFields],
      timeout: currentConfig.advanced.timeout,
      onError: currentConfig.advanced.onError,
      onMissing: currentConfig.advanced.onMissing,
      onEmpty: currentConfig.advanced.onEmpty,
      onFilteredEmpty: currentConfig.advanced.onFilteredEmpty,
    }
    existingCentral.updatedAt = '刚刚'
  } else {
    centralDataSources.value.push({
      id: binding.sourceId,
      name: currentConfig.name,
      collector: (currentConfig.collector as CollectorType) || 'logs',
      status: 'enabled',
      description: currentConfig.description || '从工作流保存的全局数据源',
      options: { ...currentConfig.options },
      rules: {
        fields: [...currentConfig.rules.fields],
        filterLevel: currentConfig.rules.filterLevel ? [...currentConfig.rules.filterLevel] : [],
        sortBy: currentConfig.rules.sortBy,
        descending: currentConfig.rules.descending,
        format: currentConfig.rules.format,
      },
      advanced: {
        extractions: currentConfig.advanced.extractions.map((e) => ({ ...e })),
        filterExpr: currentConfig.advanced.filterExpr,
        excludeFields: [...currentConfig.advanced.excludeFields],
        timeout: currentConfig.advanced.timeout,
        onError: currentConfig.advanced.onError,
        onMissing: currentConfig.advanced.onMissing,
        onEmpty: currentConfig.advanced.onEmpty,
        onFilteredEmpty: currentConfig.advanced.onFilteredEmpty,
      },
      updatedAt: '刚刚',
    })
  }

  binding.mode = 'linked'
  delete binding.customConfig
  ElMessage.success(`已保存为全局数据源「${currentConfig.name}」！后续全局更新将自动同步。`)
}

// [6. 保存采集器配置 (免弹窗选择，直接保存)]
function saveSourceConfig() {
  const fields = sourceForm.value.rules.fieldsStr
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  const excludeFields = sourceForm.value.advanced.excludeFieldsStr
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  const advancedData: SourceAdvancedSettings = {
    extractions: sourceForm.value.advanced.extractions.map((e) => ({ ...e })),
    filterExpr: sourceForm.value.advanced.filterExpr,
    excludeFields,
    timeout: sourceForm.value.advanced.timeout,
    onError: sourceForm.value.advanced.onError,
    onMissing: sourceForm.value.advanced.onMissing,
    onEmpty: sourceForm.value.advanced.onEmpty,
    onFilteredEmpty: sourceForm.value.advanced.onFilteredEmpty,
  }

  if (isNewSourceMode.value) {
    const newId = `src_${Date.now().toString().slice(-4)}`
    activeWorkflow.value.sources.push({
      bindingId: `b_${Date.now()}`,
      sourceId: newId,
      mode: 'detached',
      expandedAdvanced: false,
      customConfig: {
        name: sourceForm.value.name,
        collector: sourceForm.value.collector,
        description: sourceForm.value.description,
        options: { ...sourceForm.value.options },
        rules: {
          fields,
          filterLevel: sourceForm.value.rules.filterLevel,
          sortBy: sourceForm.value.rules.sortBy,
          descending: sourceForm.value.rules.descending,
          format: sourceForm.value.rules.format,
        },
        advanced: advancedData,
      },
    })
    ElMessage.success(`已添加采集源「${sourceForm.value.name}」`)
    sourceDrawer.value = false
    return
  }

  // 编辑工作流中的现有数据源
  if (activeEditingBinding.value) {
    const binding = activeEditingBinding.value

    if (binding.mode === 'linked') {
      // 来自全局模板：保存后自动转为本工作流独立配置，无需弹窗确认
      binding.mode = 'detached'
      binding.customConfig = {
        name: sourceForm.value.name,
        collector: sourceForm.value.collector,
        description: sourceForm.value.description,
        options: { ...sourceForm.value.options },
        rules: {
          fields,
          filterLevel: sourceForm.value.rules.filterLevel,
          sortBy: sourceForm.value.rules.sortBy,
          descending: sourceForm.value.rules.descending,
          format: sourceForm.value.rules.format,
        },
        advanced: advancedData,
      }
      ElMessage.success('配置已保存为本工作流专属配置！若需共享给全局，可在卡片点击「保存数据源」。')
    } else if (binding.mode === 'detached' && binding.customConfig) {
      binding.customConfig.name = sourceForm.value.name
      binding.customConfig.collector = sourceForm.value.collector
      binding.customConfig.description = sourceForm.value.description
      binding.customConfig.options = { ...sourceForm.value.options }
      binding.customConfig.rules = {
        fields,
        filterLevel: sourceForm.value.rules.filterLevel,
        sortBy: sourceForm.value.rules.sortBy,
        descending: sourceForm.value.rules.descending,
        format: sourceForm.value.rules.format,
      }
      binding.customConfig.advanced = advancedData
      ElMessage.success('专属配置已更新')
    }

    sourceDrawer.value = false
  }
}

// 移除数据源绑定
function removeSourceBinding(bindingId: string) {
  activeWorkflow.value.sources = activeWorkflow.value.sources.filter(
    (s) => s.bindingId !== bindingId,
  )
  ElMessage.info('已移除数据源')
}

// ==========================================
// 5. 阶段 2：并行 AI 分析交互
// ==========================================
function addAnalysisTask() {
  const idx = activeWorkflow.value.analyses.length + 1
  activeWorkflow.value.analyses.push({
    id: `task_${idx}`,
    name: `新增分析维度 ${idx}`,
    model: 'qwen-2.5-72b',
    prompt: '根据采集到的数据进行异常行为定位...',
  })
  ElMessage.success('已添加新的并行 AI 分析任务')
}

function removeAnalysisTask(index: number) {
  activeWorkflow.value.analyses.splice(index, 1)
  ElMessage.info('已移除分析任务')
}

// ==========================================
// 6. 资源配置中心视角操作 (广播同步)
// ==========================================
function openEditCentral(src: CentralDataSource) {
  isNewSourceMode.value = false
  drawerTab.value = 'basic'
  showRawJsonEditor.value = false
  activeEditingBinding.value = null
  activeEditingCentral.value = src

  const adv = src.advanced || {
    extractions: [],
    filterExpr: '',
    excludeFields: [],
    timeout: 60,
    onError: 'notice',
    onMissing: 'notice',
    onEmpty: 'notice',
    onFilteredEmpty: 'skip',
  }

  sourceForm.value = {
    id: src.id,
    name: src.name,
    collector: src.collector,
    description: src.description,
    options: { ...src.options, apiKey: '' },
    rules: {
      fieldsStr: src.rules.fields.join(', '),
      filterLevel: src.rules.filterLevel ? [...src.rules.filterLevel] : [],
      sortBy: src.rules.sortBy,
      descending: src.rules.descending,
      format: src.rules.format,
    },
    advanced: {
      extractions: adv.extractions ? adv.extractions.map((e) => ({ ...e })) : [],
      filterExpr: adv.filterExpr || '',
      excludeFieldsStr: adv.excludeFields ? adv.excludeFields.join(', ') : '',
      timeout: adv.timeout ?? 60,
      onError: adv.onError ?? 'notice',
      onMissing: adv.onMissing ?? 'notice',
      onEmpty: adv.onEmpty ?? 'notice',
      onFilteredEmpty: adv.onFilteredEmpty ?? 'skip',
      rawOptionsJson: '',
      rawSettersJson: '',
    },
  }
  syncRawJson()
  sourceDrawer.value = true
}

async function saveCentralConfig() {
  if (!activeEditingCentral.value) return
  const src = activeEditingCentral.value
  const linkedWfs = getLinkedWorkflows(src.id)
  const fields = sourceForm.value.rules.fieldsStr
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  const excludeFields = sourceForm.value.advanced.excludeFieldsStr
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  const advancedData: SourceAdvancedSettings = {
    extractions: sourceForm.value.advanced.extractions.map((e) => ({ ...e })),
    filterExpr: sourceForm.value.advanced.filterExpr,
    excludeFields,
    timeout: sourceForm.value.advanced.timeout,
    onError: sourceForm.value.advanced.onError,
    onMissing: sourceForm.value.advanced.onMissing,
    onEmpty: sourceForm.value.advanced.onEmpty,
    onFilteredEmpty: sourceForm.value.advanced.onFilteredEmpty,
  }

  if (linkedWfs.length > 0) {
    try {
      const names = linkedWfs.map((w) => `• ${w.name}`).join('\n')
      await ElMessageBox.confirm(
        `在资源配置中心修改此数据源，将自动同步广播更新以下 ${linkedWfs.length} 个工作流（包含字段规则与高级抽取配置）：\n\n${names}\n\n是否确认保存并全量广播同步？`,
        '广播同步确认',
        { confirmButtonText: '确认并全量同步', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }

  src.name = sourceForm.value.name
  src.description = sourceForm.value.description
  src.options = { ...sourceForm.value.options }
  src.rules = {
    fields,
    filterLevel: sourceForm.value.rules.filterLevel,
    sortBy: sourceForm.value.rules.sortBy,
    descending: sourceForm.value.rules.descending,
    format: sourceForm.value.rules.format,
  }
  src.advanced = advancedData
  src.updatedAt = '刚刚'
  sourceDrawer.value = false
  ElMessage.success(`全局数据源「${src.name}」已更新，并已同步广播给 ${linkedWfs.length} 个工作流！`)
}

// ==========================================
// 7. 模拟运行工作流弹窗
// ==========================================
const runModalVisible = ref(false)
const runExecuting = ref(false)
const runLogs = ref<string[]>([])

function simulateRunWorkflow() {
  runModalVisible.value = true
  runExecuting.value = true
  runLogs.value = [
    `[00:01] 触发工作流「${activeWorkflow.value.name}」执行流水线...`,
    `[00:02] [阶段 1: 数据采集] 启动 ${activeWorkflow.value.collectionConcurrency} 路并发采集，共挂载 ${activeWorkflow.value.sources.length} 个数据源...`,
  ]

  activeWorkflow.value.sources.forEach((s) => {
    const cfg = getEffectiveSourceConfig(s)
    if (cfg?.advanced?.extractions?.length) {
      const extList = cfg.advanced.extractions
        .map((e) => `${e.targetField}(${e.sourceType === 'json_path' ? 'JSONPath' : e.sourceType === 'regex' ? '正则' : '缺省'})`)
        .join(', ')
      runLogs.value.push(`       ↳ [${cfg.name}] 正在执行不规则字段抽取: ${extList}`)
    }
    if (cfg?.advanced?.filterExpr) {
      runLogs.value.push(`       ↳ [${cfg.name}] 应用过滤表达式: ${cfg.advanced.filterExpr}`)
    }
  })

  setTimeout(() => {
    runLogs.value.push(
      `[00:04] [阶段 1: 数据采集] 采集完成，共读取并规整 548 条事件，各非标准字段已对齐，已拼接为共享输入。`,
      `[00:05] [阶段 2: 并行 AI 分析] 启动 ${activeWorkflow.value.analyses.length} 个并发分析任务...`,
    )
    activeWorkflow.value.analyses.forEach((t) => {
      runLogs.value.push(`       ↳ [${t.name}] 使用模型 ${t.model} 推理中...`)
    })
  }, 1000)

  setTimeout(() => {
    runLogs.value.push(`[00:07] [阶段 2: 并行 AI 分析] 各路分析均已完成，生成 2 份深度归因诊断。`)
    if (activeWorkflow.value.fanIn.enabled) {
      runLogs.value.push(
        `[00:08] [阶段 3: 汇聚汇总] 使用 ${activeWorkflow.value.fanIn.model} 汇总为高层体检日报...`,
      )
    } else {
      runLogs.value.push(`[00:08] [阶段 3: 汇聚汇总] 未启用汇总，直接传递分析结果。`)
    }
  }, 2200)

  setTimeout(() => {
    runLogs.value.push(
      `[00:09] [阶段 4: 渠道分发] 成功将报告投递至 ${activeWorkflow.value.channels.join(', ')}。`,
      `[00:10] 工作流整体执行完毕，运行状态: Success (已归档快照)。`,
    )
    runExecuting.value = false
  }, 3200)
}

function collectorIcon(c: CollectorType): 'database' | 'history' | 'settings' {
  if (c === 'logs') return 'database'
  if (c === 'history') return 'history'
  return 'settings'
}
</script>

<template>
  <div class="workflow-demo-root">
    <!-- 顶部标题与导航栏 -->
    <PageHeader
      title="工作流管理与数据源中心设计演示"
      description="完整 4 阶段工作流管线（采集、AI分析、汇聚、分发），消除冗余模板分拆，支持全局广播同步与一键脱离"
    >
      <div class="flex items-center gap-2">
        <el-button type="primary" plain @click="simulateRunWorkflow">
          <AppIcon name="play" size="sm" />
          <span>模拟运行当前工作流</span>
        </el-button>
      </div>
    </PageHeader>

    <!-- 界面切换 Tab (工作流管理 VS 资源配置中心) -->
    <div class="view-tab-nav">
      <button
        type="button"
        class="nav-tab-item"
        :class="{ active: activeNav === 'workflows' }"
        @click="selectNav('workflows')"
      >
        <AppIcon name="workflow" size="sm" />
        <span>工作流管理 (完整 4 阶段编排)</span>
      </button>

      <button
        type="button"
        class="nav-tab-item"
        :class="{ active: activeNav === 'resources' }"
        @click="selectNav('resources')"
      >
        <AppIcon name="database" size="sm" />
        <span>资源配置中心 (全局数据源维护与广播)</span>
      </button>
    </div>

    <!-- ======================================================= -->
    <!-- 视图 A：工作流管理视角 (包含 1.采集 -> 2.分析 -> 3.汇总 -> 4.分发) -->
    <!-- ======================================================= -->
    <div v-if="activeNav === 'workflows'" class="workflow-orchestrator-layout">
      <!-- 左侧工作流列表选择器 -->
      <aside class="workflow-sidebar">
        <div class="sidebar-top">
          <span class="text-xs font-bold text-muted">工作流列表 ({{ workflows.length }})</span>
        </div>
        <div class="sidebar-cards">
          <button
            v-for="wf in workflows"
            :key="wf.id"
            type="button"
            class="wf-selector-card"
            :class="{ selected: wf.id === selectedWorkflowId }"
            @click="selectWorkflow(wf.id)"
          >
            <div class="card-head">
              <strong>{{ wf.name }}</strong>
              <span class="cron-pill">{{ wf.cron }}</span>
            </div>
            <p class="card-desc">{{ wf.description }}</p>
            <div class="card-badges">
              <span>{{ wf.sources.length }} 个数据源</span>
              <span>{{ wf.analyses.length }} 个分析任务</span>
              <span v-if="wf.fanIn.enabled" class="tag-accent">已汇聚</span>
            </div>
          </button>
        </div>
      </aside>

      <!-- 右侧工作流编排主面板 (1 -> 2 -> 3 -> 4) -->
      <main class="pipeline-main-column">
        <!-- 阶段 0：工作流基础元信息 -->
        <div class="pipeline-header-card">
          <div>
            <div class="eyebrow">PIPELINE DESIGNER</div>
            <h2>{{ activeWorkflow.name }}</h2>
            <p class="text-muted text-sm">{{ activeWorkflow.description }}</p>
          </div>
          <div class="flex items-center gap-3">
            <span class="cron-pill font-mono">定时：{{ activeWorkflow.cron }}</span>
            <el-button size="small" type="primary" @click="simulateRunWorkflow">
              <AppIcon name="play" size="sm" />
              <span>立即运行</span>
            </el-button>
          </div>
        </div>

        <!-- 4 步骤流程导航栏 (支持分步聚焦与全览模式，由 Vue Router 驱动) -->
        <div class="pipeline-step-nav">
          <button
            type="button"
            class="step-nav-btn"
            :class="{ active: activeStage === 'sources' }"
            @click="selectStage('sources')"
          >
            <span class="step-num">1</span>
            <div class="step-text">
              <strong>数据采集源</strong>
              <small>{{ activeWorkflow.sources.length }} 个输入源</small>
            </div>
          </button>

          <span class="step-arrow">➔</span>

          <button
            type="button"
            class="step-nav-btn"
            :class="{ active: activeStage === 'analyses' }"
            @click="selectStage('analyses')"
          >
            <span class="step-num">2</span>
            <div class="step-text">
              <strong>并行 AI 分析</strong>
              <small>{{ activeWorkflow.analyses.length }} 路任务</small>
            </div>
          </button>

          <span class="step-arrow">➔</span>

          <button
            type="button"
            class="step-nav-btn"
            :class="{ active: activeStage === 'fanin' }"
            @click="selectStage('fanin')"
          >
            <span class="step-num">3</span>
            <div class="step-text">
              <strong>汇聚汇总</strong>
              <small>{{ activeWorkflow.fanIn.enabled ? '已启用汇总' : '未启用' }}</small>
            </div>
          </button>

          <span class="step-arrow">➔</span>

          <button
            type="button"
            class="step-nav-btn"
            :class="{ active: activeStage === 'channels' }"
            @click="selectStage('channels')"
          >
            <span class="step-num">4</span>
            <div class="step-text">
              <strong>渠道分发</strong>
              <small>{{ activeWorkflow.channels.length }} 个渠道</small>
            </div>
          </button>

          <div class="step-nav-extra">
            <button
              type="button"
              class="btn-all-overview"
              :class="{ active: activeStage === 'all' }"
              @click="selectStage('all')"
            >
              <AppIcon name="workflow" size="sm" />
              <span>全览模式</span>
            </button>
          </div>
        </div>

        <!-- ========================================== -->
        <!-- 阶段 1：数据采集 (以数据源为中心：新增、加载、保存、脱离模板) -->
        <!-- ========================================== -->
        <section v-if="activeStage === 'sources' || activeStage === 'all'" class="stage-card stage-1">
          <div class="stage-card-head">
            <div class="stage-title-wrap">
              <span class="stage-index">1</span>
              <div>
                <h3>数据采集源管理</h3>
                <p>配置采集输入源。支持规整标准日志与任意不规则非结构化数据，自动抽取为共享输入。支持调整上下次序。</p>
              </div>
            </div>
            <div class="stage-head-actions">
              <el-button size="small" @click="openLoadSourceModal">
                <AppIcon name="database" size="sm" />
                <span>加载已有数据源</span>
              </el-button>
              <el-button size="small" type="primary" @click="openCreateSource">
                <AppIcon name="plus" size="sm" />
                <span>新增采集源</span>
              </el-button>
            </div>
          </div>

          <!-- 工作流级高级运行参数折叠条 (对齐真实系统 WorkflowDefinition 采集参数) -->
          <div class="workflow-advanced-params-bar">
            <div
              class="params-bar-summary"
              @click="isWorkflowAdvancedExpanded = !isWorkflowAdvancedExpanded"
            >
              <div class="flex items-center gap-2">
                <AppIcon name="sliders" size="sm" />
                <span class="font-bold text-xs">工作流级高级采集参数</span>
                <span class="badge-param">并发: {{ activeWorkflow.collectionConcurrency }}</span>
                <span class="badge-param">全空策略: {{ activeWorkflow.onAllEmpty }}</span>
                <span class="badge-param">分隔符: {{ activeWorkflow.inputSeparator === '\n\n' ? '双换行 (默认)' : '自定义' }}</span>
              </div>
              <button type="button" class="btn-toggle-subtle">
                {{ isWorkflowAdvancedExpanded ? '收起高级参数 ▴' : '展开参数设置 ▾' }}
              </button>
            </div>

            <div v-if="isWorkflowAdvancedExpanded" class="params-bar-content">
              <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div>
                  <label class="block text-xs font-bold text-muted mb-1">采集并发数 (Concurrency)</label>
                  <el-input-number
                    v-model="activeWorkflow.collectionConcurrency"
                    :min="1"
                    :max="10"
                    size="small"
                    class="w-full"
                  />
                  <p class="text-[11px] text-muted mt-1">多数据源并行拉取加速</p>
                </div>

                <div>
                  <label class="block text-xs font-bold text-muted mb-1">全部来源为空时策略</label>
                  <el-select v-model="activeWorkflow.onAllEmpty" size="small" class="w-full">
                    <el-option value="notice" label="⚠️ 告警提示并继续 (notice)" />
                    <el-option value="stop" label="⛔ 终止后续分析 (stop)" />
                    <el-option value="skip" label="🔕 静默跳过 (skip)" />
                  </el-select>
                  <p class="text-[11px] text-muted mt-1">无日志产出时的流程行为</p>
                </div>

                <div>
                  <label class="block text-xs font-bold text-muted mb-1">跨来源正文输入分隔符</label>
                  <el-input
                    v-model="activeWorkflow.inputSeparator"
                    size="small"
                    placeholder="如 \n\n 或 \n---\n"
                  />
                  <p class="text-[11px] text-muted mt-1">拼接各源内容时的物理分隔</p>
                </div>

                <div class="flex flex-col justify-center">
                  <div class="flex items-center justify-between">
                    <span class="text-xs font-bold text-muted">输入中包含采集条数统计</span>
                    <el-switch v-model="activeWorkflow.includeCounts" size="small" />
                  </div>
                  <p class="text-[11px] text-muted mt-1">在 AI 输入前注入数据量统计头</p>
                </div>
              </div>
            </div>
          </div>

          <!-- 采集源挂载列表 -->
          <div class="sources-list">
            <div
              v-for="(binding, idx) in activeWorkflow.sources"
              :key="binding.bindingId"
              class="source-row-card"
            >
              <div class="source-main-info">
                <div class="source-top-meta">
                  <span class="index-badge">#{{ idx + 1 }}</span>
                  <span class="collector-icon">
                    <AppIcon
                      :name="
                        collectorIcon(
                          (getEffectiveSourceConfig(binding)?.collector as CollectorType) ||
                            'logs',
                        )
                      "
                      size="sm"
                    />
                  </span>
                  <strong class="source-title">
                    {{ getEffectiveSourceConfig(binding)?.name }}
                  </strong>

                  <!-- 同步模式标签 (纯净素雅设计) -->
                  <span
                    v-if="binding.mode === 'linked'"
                    class="tag-status linked"
                    title="跟随资源配置中心，中心修改时自动同步"
                  >
                    <span class="dot" />
                    <span>全局同步 ({{ getLinkedCount(binding.sourceId) }})</span>
                  </span>
                  <span
                    v-else
                    class="tag-status detached"
                    title="已脱离全局模板，为本流独立专属配置"
                  >
                    <span>专属配置</span>
                  </span>

                  <!-- 高级特性指示徽标 (素雅中性标签) -->
                  <span
                    v-if="getEffectiveSourceConfig(binding)?.advanced?.extractions?.length"
                    class="tag-status neutral"
                  >
                    <span>{{ getEffectiveSourceConfig(binding)?.advanced.extractions.length }} 项抽取</span>
                  </span>
                </div>

                <!-- 基础属性摘要 (小白友好清晰呈现) -->
                <div class="source-details-summary">
                  <span>
                    目标路径:
                    <code>{{ getEffectiveSourceConfig(binding)?.options.path }}</code>
                  </span>
                  <span>
                    读取上限:
                    <strong>{{ getEffectiveSourceConfig(binding)?.options.maxLines }}</strong>
                    行
                  </span>
                  <span>
                    基础字段:
                    <span class="fields-list">
                      {{ getEffectiveSourceConfig(binding)?.rules.fields.join(', ') }}
                    </span>
                  </span>
                  <span>
                    格式:
                    <span class="uppercase text-xs font-mono font-bold">
                      {{ getEffectiveSourceConfig(binding)?.rules.format }}
                    </span>
                  </span>
                </div>

                <!-- 高级规则快捷预览开关与展开面板 (不整齐字段与高级设置) -->
                <div class="source-advanced-preview-wrap">
                  <button
                    type="button"
                    class="toggle-inline-adv-btn"
                    @click="binding.expandedAdvanced = !binding.expandedAdvanced"
                  >
                    <AppIcon :name="binding.expandedAdvanced ? 'chevronDown' : 'chevronRight'" size="sm" />
                    <span>
                      {{
                        binding.expandedAdvanced
                          ? '收起高级抽取规则与参数 ▴'
                          : '查看高级设置 (不规则字段抽取、复杂过滤与异常策略) ▾'
                      }}
                    </span>
                  </button>

                  <div v-if="binding.expandedAdvanced" class="inline-adv-panel">
                    <!-- 不规则字段动态抽取规则 -->
                    <div class="inline-adv-section">
                      <div class="adv-sec-label">
                        <AppIcon name="sparkles" size="sm" />
                        <span>不规则字段动态提取 (JSONPath / 正则表达式):</span>
                      </div>
                      <div
                        v-if="getEffectiveSourceConfig(binding)?.advanced?.extractions?.length"
                        class="extractions-pill-grid"
                      >
                        <div
                          v-for="ex in getEffectiveSourceConfig(binding)?.advanced.extractions"
                          :key="ex.id"
                          class="extraction-pill-item"
                        >
                          <span class="target-field font-mono font-bold">{{ ex.targetField }}</span>
                          <span class="sep">←</span>
                          <span class="source-expr font-mono">{{ ex.expression }}</span>
                          <span class="type-tag">{{ ex.sourceType === 'json_path' ? 'JSONPath' : ex.sourceType === 'regex' ? '正则' : '缺省值' }}</span>
                          <span v-if="ex.fallbackValue" class="fallback-tag">缺省: {{ ex.fallbackValue }}</span>
                        </div>
                      </div>
                      <div v-else class="text-xs text-muted">
                        暂无自定义不规则字段抽取，直接使用基础日志字段。
                      </div>
                    </div>

                    <!-- 高级过滤表达式与脱敏 -->
                    <div class="inline-adv-section mt-2">
                      <div class="adv-sec-label">
                        <AppIcon name="sliders" size="sm" />
                        <span>复杂过滤条件与脱敏排除:</span>
                      </div>
                      <div class="flex flex-wrap items-center gap-3 text-xs">
                        <div>
                          <span class="text-muted">原始过滤表达式: </span>
                          <code v-if="getEffectiveSourceConfig(binding)?.advanced?.filterExpr">
                            {{ getEffectiveSourceConfig(binding)?.advanced.filterExpr }}
                          </code>
                          <span v-else class="text-muted">无 (全量采集)</span>
                        </div>
                        <div v-if="getEffectiveSourceConfig(binding)?.advanced?.excludeFields?.length">
                          <span class="text-muted">排除字段: </span>
                          <span class="text-rose-600 dark:text-rose-400 font-mono">
                            {{ getEffectiveSourceConfig(binding)?.advanced.excludeFields.join(', ') }}
                          </span>
                        </div>
                      </div>
                    </div>

                    <!-- 运行时异常策略与超时 -->
                    <div class="inline-adv-section mt-2">
                      <div class="adv-sec-label">
                        <AppIcon name="settings" size="sm" />
                        <span>运行时异常策略 (SourcePolicy) 与超时:</span>
                      </div>
                      <div class="policy-badges-row">
                        <span class="badge-policy">
                          报错策略: <strong>{{ getEffectiveSourceConfig(binding)?.advanced?.onError }}</strong>
                        </span>
                        <span class="badge-policy">
                          目标缺失: <strong>{{ getEffectiveSourceConfig(binding)?.advanced?.onMissing }}</strong>
                        </span>
                        <span class="badge-policy">
                          结果为空: <strong>{{ getEffectiveSourceConfig(binding)?.advanced?.onEmpty }}</strong>
                        </span>
                        <span class="badge-policy">
                          过滤后为空: <strong>{{ getEffectiveSourceConfig(binding)?.advanced?.onFilteredEmpty }}</strong>
                        </span>
                        <span class="badge-policy">
                          超时上限: <strong>{{ getEffectiveSourceConfig(binding)?.advanced?.timeout }} 秒</strong>
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="source-hint-row">
                  <span
                    v-if="binding.mode === 'linked'"
                    class="text-xs text-muted"
                  >
                    全局同步：与资源中心保持一致。若在当前工作流中修改，将自动脱离为专属独立配置。
                  </span>
                  <span v-else class="text-xs text-muted">
                    专属独立配置：仅对本工作流生效。点击「保存数据源」可直接同步发布到资源配置中心。
                  </span>
                </div>
              </div>

              <!-- 操作按钮栏 -->
              <div class="source-actions">
                <div class="order-btn-group" title="调整采集优先级与执行顺序">
                  <button
                    type="button"
                    class="order-btn"
                    :disabled="idx === 0"
                    title="上移（优先采集）"
                    @click="moveSourceUp(idx)"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    class="order-btn"
                    :disabled="idx === activeWorkflow.sources.length - 1"
                    title="下移"
                    @click="moveSourceDown(idx)"
                  >
                    ↓
                  </button>
                </div>

                <el-button
                  v-if="binding.mode === 'detached'"
                  size="small"
                  text
                  type="primary"
                  @click="saveSourceToCentral(binding)"
                >
                  <AppIcon name="database" size="sm" />
                  <span>保存数据源</span>
                </el-button>

                <el-button
                  v-if="binding.mode === 'linked'"
                  size="small"
                  text
                  @click="detachSource(binding)"
                >
                  <AppIcon name="fork" size="sm" />
                  <span>脱离独立</span>
                </el-button>

                <el-button size="small" @click="openEditBinding(binding)">
                  <AppIcon name="settings" size="sm" />
                  <span>编辑配置</span>
                </el-button>

                <el-button
                  size="small"
                  text
                  type="danger"
                  @click="removeSourceBinding(binding.bindingId)"
                >
                  移除
                </el-button>
              </div>
            </div>

            <el-empty
              v-if="!activeWorkflow.sources.length"
              description="暂无采集源，请点击下方按钮加载已有数据源或新建"
              :image-size="64"
            >
              <div class="flex gap-2 justify-center mt-2">
                <el-button size="small" @click="openLoadSourceModal">
                  <AppIcon name="database" size="sm" />
                  <span>加载已有数据源</span>
                </el-button>
                <el-button size="small" type="primary" @click="openCreateSource">
                  <AppIcon name="plus" size="sm" />
                  <span>新增采集源</span>
                </el-button>
              </div>
            </el-empty>
          </div>

          <div v-if="activeStage !== 'all'" class="step-footer-actions">
            <span class="text-xs text-muted">采集源顺序决定数据读取与规整的先后流向</span>
            <el-button type="primary" @click="selectStage('analyses')">
              <span>下一步：配置并行 AI 分析 ➔</span>
            </el-button>
          </div>
        </section>

        <!-- ========================================== -->
        <!-- 阶段 2：并行 AI 分析 (Fan-Out 任务组) -->
        <!-- ========================================== -->
        <section v-if="activeStage === 'analyses' || activeStage === 'all'" class="stage-card stage-2">
          <div class="stage-card-head">
            <div class="stage-title-wrap">
              <span class="stage-index">2</span>
              <div>
                <h3>并行 AI 分析 (Fan-Out)</h3>
                <p>各分析任务接收统一的采集输入，使用不同 AI 模型与提示词并发处理。可通过上下箭头调整分析执行顺序。</p>
              </div>
            </div>
            <el-button size="small" @click="addAnalysisTask">
              <AppIcon name="plus" size="sm" />
              <span>添加分析维度</span>
            </el-button>
          </div>

          <div class="analysis-tasks-grid">
            <div
              v-for="(task, tIndex) in activeWorkflow.analyses"
              :key="task.id"
              class="analysis-task-card"
            >
              <div class="task-card-head">
                <div class="task-id-badge">
                  <span class="index-badge">#{{ tIndex + 1 }}</span>
                  <el-input v-model="task.name" size="small" class="task-name-input" />
                </div>
                <div class="flex items-center gap-2">
                  <div class="order-btn-group" title="调整分析执行顺序">
                    <button
                      type="button"
                      class="order-btn"
                      :disabled="tIndex === 0"
                      title="上移（优先分析）"
                      @click="moveAnalysisUp(tIndex)"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      class="order-btn"
                      :disabled="tIndex === activeWorkflow.analyses.length - 1"
                      title="下移"
                      @click="moveAnalysisDown(tIndex)"
                    >
                      ↓
                    </button>
                  </div>
                  <el-button size="small" text type="danger" @click="removeAnalysisTask(tIndex)">
                    删除
                  </el-button>
                </div>
              </div>

              <div class="task-card-body">
                <div class="form-row">
                  <span class="field-label">AI 模型选择:</span>
                  <el-select v-model="task.model" size="small" class="w-full">
                    <el-option
                      v-for="m in availableModels"
                      :key="m.id"
                      :value="m.id"
                      :label="m.name"
                    />
                  </el-select>
                </div>

                <div class="form-row mt-2">
                  <span class="field-label">提示词模板 (Prompt):</span>
                  <el-input
                    v-model="task.prompt"
                    type="textarea"
                    :rows="3"
                    placeholder="输入分析指令，可引用 {input}..."
                  />
                </div>
              </div>
            </div>
          </div>

          <div v-if="activeStage !== 'all'" class="step-footer-actions">
            <el-button @click="selectStage('sources')">
              <span>⬅ 上一步：数据采集源</span>
            </el-button>
            <el-button type="primary" @click="selectStage('fanin')">
              <span>下一步：配置汇聚汇总 ➔</span>
            </el-button>
          </div>
        </section>

        <!-- ========================================== -->
        <!-- 阶段 3：汇聚汇总 (Fan-In 聚合阶段) -->
        <!-- ========================================== -->
        <section v-if="activeStage === 'fanin' || activeStage === 'all'" class="stage-card stage-3">
          <div class="stage-card-head">
            <div class="stage-title-wrap">
              <span class="stage-index">3</span>
              <div>
                <h3>汇聚汇总 (Fan-In)</h3>
                <p>按指定顺序汇总各分析维度的结论，可选由高级大模型撰写综合日报。</p>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs text-muted">启用汇总</span>
              <el-switch v-model="activeWorkflow.fanIn.enabled" />
            </div>
          </div>

          <div v-if="activeWorkflow.fanIn.enabled" class="fanin-config-body">
            <div class="form-grid-2">
              <div>
                <label class="block text-xs font-bold text-muted mb-2">汇总参与项与顺序:</label>
                <el-select v-model="activeWorkflow.fanIn.order" multiple class="w-full">
                  <el-option value="$input" label="原始共享输入 ($input)" />
                  <el-option
                    v-for="t in activeWorkflow.analyses"
                    :key="t.id"
                    :value="t.id"
                    :label="t.name"
                  />
                </el-select>
              </div>

              <div>
                <label class="block text-xs font-bold text-muted mb-2">汇总大模型 (AI):</label>
                <el-select v-model="activeWorkflow.fanIn.model" class="w-full">
                  <el-option
                    v-for="m in availableModels"
                    :key="m.id"
                    :value="m.id"
                    :label="m.name"
                  />
                </el-select>
              </div>
            </div>

            <div class="mt-3">
              <label class="block text-xs font-bold text-muted mb-2">综合提炼提示词模板:</label>
              <el-input
                v-model="activeWorkflow.fanIn.prompt"
                type="textarea"
                :rows="3"
                placeholder="例如：提炼为简报、标注严重级别..."
              />
            </div>
          </div>
          <div v-else class="text-xs text-muted p-3 bg-slate-50 dark:bg-slate-900 rounded-lg">
            当前未启用汇聚汇总，各分析任务的结论将原样保留并直接进入渠道分发。
          </div>

          <div v-if="activeStage !== 'all'" class="step-footer-actions">
            <el-button @click="selectStage('analyses')">
              <span>⬅ 上一步：并行 AI 分析</span>
            </el-button>
            <el-button type="primary" @click="selectStage('channels')">
              <span>下一步：配置渠道分发 ➔</span>
            </el-button>
          </div>
        </section>

        <!-- ========================================== -->
        <!-- 阶段 4：渠道分发 (Notification & Delivery) -->
        <!-- ========================================== -->
        <section v-if="activeStage === 'channels' || activeStage === 'all'" class="stage-card stage-4">
          <div class="stage-card-head">
            <div class="stage-title-wrap">
              <span class="stage-index">4</span>
              <div>
                <h3>渠道分发</h3>
                <p>将最终的分析报告或告警摘要安全投递至指定通知渠道。</p>
              </div>
            </div>
          </div>

          <div class="channel-selection-grid">
            <div
              v-for="chan in centralChannels"
              :key="chan.id"
              class="channel-option-card"
              :class="{ selected: activeWorkflow.channels.includes(chan.id) }"
              @click="
                activeWorkflow.channels.includes(chan.id)
                  ? (activeWorkflow.channels = activeWorkflow.channels.filter(
                      (c) => c !== chan.id,
                    ))
                  : activeWorkflow.channels.push(chan.id)
              "
            >
              <div class="chan-icon">
                <AppIcon :name="chan.type === 'email' ? 'mail' : 'settings'" size="sm" />
              </div>
              <div class="chan-info">
                <strong>{{ chan.name }}</strong>
                <span class="chan-target-mono">{{ chan.target }}</span>
              </div>
              <el-checkbox
                :model-value="activeWorkflow.channels.includes(chan.id)"
                @click.stop
              />
            </div>
          </div>

          <div v-if="activeStage !== 'all'" class="step-footer-actions">
            <el-button @click="selectStage('fanin')">
              <span>⬅ 上一步：汇聚汇总</span>
            </el-button>
            <el-button type="primary" @click="simulateRunWorkflow">
              <AppIcon name="play" size="sm" />
              <span>立即运行当前流水线</span>
            </el-button>
          </div>
        </section>
      </main>
    </div>

    <!-- ======================================================= -->
    <!-- 视图 B：资源配置中心视角 (Axonhub 风格全局维护界面) -->
    <!-- ======================================================= -->
    <div v-else class="resource-center-layout">
      <div class="resource-intro-bar">
        <div>
          <h3>🏢 全局数据源配置中心</h3>
          <p class="text-xs text-muted">
            在此处集中维护标准数据源。当修改全局数据源时，系统将自动广播同步到所有处于【全局同步】状态的工作流。
          </p>
        </div>
        <el-button
          type="primary"
          @click="
            openCreateSource();
            isNewSourceMode = true
          "
        >
          <AppIcon name="plus" size="sm" />
          <span>新建全局数据源</span>
        </el-button>
      </div>

      <!-- 全局数据源卡片列表 (Axonhub 风格) -->
      <div class="central-source-cards">
        <div v-for="src in centralDataSources" :key="src.id" class="axon-source-card">
          <div class="axon-card-top">
            <div class="axon-source-id">
              <span class="axon-avatar">
                <AppIcon :name="collectorIcon(src.collector)" size="sm" />
              </span>
              <div>
                <strong>{{ src.name }}</strong>
                <span class="source-key-tag">{{ src.id }}</span>
              </div>
            </div>
            <el-switch
              v-model="src.status"
              active-value="enabled"
              inactive-value="paused"
              @change="ElMessage.success(`状态已设为 ${src.status}`)"
            />
          </div>

          <p class="axon-desc">{{ src.description }}</p>

          <div class="axon-props-box">
            <div>
              <span class="k">采集目标</span>
              <span class="v mono">{{ src.options.path }}</span>
            </div>
            <div>
              <span class="k">读取上限</span>
              <span class="v">{{ src.options.maxLines }} 行</span>
            </div>
            <div>
              <span class="k">输出格式</span>
              <span class="v uppercase">{{ src.rules.format }}</span>
            </div>
          </div>

          <!-- 高级不规则规则指示徽标 -->
          <div class="axon-adv-badges">
            <span class="adv-pill">
              <AppIcon name="sparkles" size="sm" />
              <span>{{ src.advanced.extractions.length }} 项不规则字段抽取</span>
            </span>
            <span class="adv-pill subtle">
              <span>超时: {{ src.advanced.timeout }}s · 报错: {{ src.advanced.onError }}</span>
            </span>
            <span v-if="src.advanced.filterExpr" class="adv-pill filter">
              <span>含复杂过滤表达式</span>
            </span>
          </div>

          <!-- 广播影响面 (显示有几个工作流在同步) -->
          <div class="sync-impact-box">
            <span class="impact-title">
              <AppIcon name="workflow" size="sm" />
              <span>当前正在同步此源的工作流 ({{ getLinkedCount(src.id) }} 个):</span>
            </span>
            <div class="impact-wf-tags">
              <span
                v-for="wf in getLinkedWorkflows(src.id)"
                :key="wf.id"
                class="impact-tag"
                @click="
                  selectedWorkflowId = wf.id;
                  activeNav = 'workflows'
                "
              >
                {{ wf.name }}
              </span>
              <span v-if="!getLinkedCount(src.id)" class="text-xs text-muted">
                暂无工作流关联（修改不会产生外部影响）
              </span>
            </div>
          </div>

          <div class="axon-card-bottom">
            <span class="text-xs text-muted">更新于 {{ src.updatedAt }}</span>
            <el-button size="small" type="primary" plain @click="openEditCentral(src)">
              <AppIcon name="settings" size="sm" />
              <span>配置并全量广播同步</span>
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- 抽屉：编辑/新增采集器 (常规与高级不规则设置双层设计) -->
    <!-- ========================================== -->
    <el-drawer
      v-model="sourceDrawer"
      :title="
        isNewSourceMode
          ? '新增数据源'
          : activeEditingCentral
            ? `修改全局数据源：${sourceForm.name}`
            : `编辑工作流数据源：${sourceForm.name}`
      "
      size="min(94vw, 760px)"
      append-to-body
      destroy-on-close
    >
      <div class="drawer-form-content">
        <!-- 业务提示 -->
        <div v-if="activeEditingCentral" class="banner-alert info">
          <AppIcon name="sparkles" size="md" />
          <div>
            <strong>📢 正在编辑资源配置中心全局数据源</strong>
            <p>
              保存后将为所有处于全局同步中的
              {{ getLinkedCount(activeEditingCentral.id) }} 个工作流进行广播同步（包含基础设置与不规则抽取配置）！
            </p>
          </div>
        </div>

        <div
          v-else-if="activeEditingBinding && activeEditingBinding.mode === 'linked'"
          class="banner-alert warning"
        >
          <AppIcon name="fork" size="md" />
          <div>
            <strong>⚠️ 正在工作流中编辑共享数据源</strong>
            <p>
              {{
                getLinkedCount(activeEditingBinding.sourceId) > 1
                  ? '该源正被多个工作流共同引用。为保障安全，保存时将自动为您【脱离模板】，转为专属独立配置！'
                  : '当前工作流是该数据源的唯一使用方，您可以选择同步到全局，或脱离为独立配置。'
              }}
            </p>
          </div>
        </div>

        <!-- 顶部分段切换：常规基础配置 VS 高级不规则设置 -->
        <div class="drawer-segmented-nav">
          <button
            type="button"
            class="seg-btn"
            :class="{ active: drawerTab === 'basic' }"
            @click="drawerTab = 'basic'"
          >
            <AppIcon name="file" size="sm" />
            <span>常规基础配置 (小白友好)</span>
          </button>
          <button
            type="button"
            class="seg-btn"
            :class="{ active: drawerTab === 'advanced' }"
            @click="drawerTab = 'advanced'"
          >
            <AppIcon name="sliders" size="sm" />
            <span>高级扩展与不规则字段 (专业)</span>
            <span
              v-if="sourceForm.advanced.extractions.length"
              class="seg-badge"
            >
              {{ sourceForm.advanced.extractions.length }}
            </span>
          </button>
        </div>

        <el-form label-position="top">
          <!-- ============================================== -->
          <!-- 标签页 1：常规基础配置 -->
          <!-- ============================================== -->
          <div v-if="drawerTab === 'basic'" class="drawer-tab-pane">
            <div class="form-section">
              <div class="sec-title">01 · 基础信息</div>
              <div class="form-grid-2">
                <el-form-item label="数据源名称">
                  <el-input v-model="sourceForm.name" />
                </el-form-item>
                <el-form-item label="采集器类型">
                  <el-select
                    v-model="sourceForm.collector"
                    class="w-full"
                    :disabled="!isNewSourceMode"
                  >
                    <el-option value="logs" label="应用运行日志 (logs)" />
                    <el-option value="history" label="工作流历史运行 (history)" />
                    <el-option value="mock" label="离线桩数据 (mock)" />
                  </el-select>
                </el-form-item>
              </div>
              <el-form-item label="用途说明">
                <el-input v-model="sourceForm.description" />
              </el-form-item>
            </div>

            <div class="form-section">
              <div class="sec-title">02 · 采集连接参数 (从哪里采集)</div>
              <el-form-item label="目标路径 / 文件路径">
                <el-input v-model="sourceForm.options.path" />
              </el-form-item>
              <div class="form-grid-2">
                <el-form-item label="最大读取行数">
                  <el-input-number
                    v-model="sourceForm.options.maxLines"
                    :min="10"
                    :max="10000"
                    class="w-full"
                  />
                </el-form-item>
                <el-form-item label="访问 Token (可选)">
                  <el-input
                    v-model="sourceForm.options.apiKey"
                    type="password"
                    placeholder="可选认证鉴权"
                  />
                </el-form-item>
              </div>
            </div>

            <div class="form-section">
              <div class="sec-title">03 · 处理规则 (采集后保留与排序)</div>
              <el-form-item label="基础保留字段 (逗号分隔)">
                <el-input v-model="sourceForm.rules.fieldsStr" />
                <p class="text-[11px] text-muted mt-1">
                  标准常规字段，如 <code>time, level, module, message</code>。
                </p>
              </el-form-item>
              <div class="form-grid-2">
                <el-form-item label="级别过滤 (Level)">
                  <el-select
                    v-model="sourceForm.rules.filterLevel"
                    multiple
                    placeholder="不过滤"
                    class="w-full"
                  >
                    <el-option value="error" label="ERROR" />
                    <el-option value="warning" label="WARNING" />
                    <el-option value="info" label="INFO" />
                  </el-select>
                </el-form-item>
                <el-form-item label="排序基准字段">
                  <el-input v-model="sourceForm.rules.sortBy" />
                </el-form-item>
              </div>
              <div class="form-grid-2">
                <el-form-item label="输出格式">
                  <el-select v-model="sourceForm.rules.format" class="w-full">
                    <el-option value="markdown" label="Markdown" />
                    <el-option value="text" label="纯文本" />
                    <el-option value="jsonl" label="JSONL" />
                  </el-select>
                </el-form-item>
                <el-form-item label="倒序排列">
                  <el-switch v-model="sourceForm.rules.descending" />
                </el-form-item>
              </div>
            </div>

            <!-- 引导切换到高级设置的提示条 -->
            <div class="subtle-guide-box" @click="drawerTab = 'advanced'">
              <div class="flex items-center gap-2">
                <AppIcon name="sparkles" size="sm" />
                <span class="font-bold text-xs">日志字段不规则？需要抽取深层 JSON 或复杂正则？</span>
              </div>
              <span class="text-xs text-primary underline">前往「高级扩展与不规则字段」配置 ➔</span>
            </div>
          </div>

          <!-- ============================================== -->
          <!-- 标签页 2：高级设置 (不规则字段抽取、异常策略与底层JSON) -->
          <!-- ============================================== -->
          <div v-else class="drawer-tab-pane">
            <!-- 模块 A：不规则字段动态提取 -->
            <div class="form-section">
              <div class="flex justify-between items-center mb-2">
                <div>
                  <div class="sec-title mb-0">01 · 不规则字段动态提取 (JSONPath / 正则表达式)</div>
                  <p class="text-[11px] text-muted">
                    真实日志常存在深层嵌套 JSON 或半结构化字符串，在此添加动态抽取规则，将其规整为标准字段。
                  </p>
                </div>
                <el-button size="small" type="primary" plain @click="addCustomExtraction">
                  <AppIcon name="plus" size="sm" />
                  <span>添加规则</span>
                </el-button>
              </div>

              <!-- 快捷预设按钮组 -->
              <div class="preset-buttons-bar">
                <span class="text-[11px] text-muted">常用预设模板:</span>
                <button type="button" class="preset-btn" @click="addExtractionPreset('trace_id')">
                  + TraceID (JSONPath)
                </button>
                <button type="button" class="preset-btn" @click="addExtractionPreset('client_ip')">
                  + Client IP (正则)
                </button>
                <button type="button" class="preset-btn" @click="addExtractionPreset('header')">
                  + 请求头 Header (JSONPath)
                </button>
              </div>

              <!-- 抽取规则列表卡片 -->
              <div class="extractions-editor-list">
                <div
                  v-for="(rule, rIdx) in sourceForm.advanced.extractions"
                  :key="rule.id"
                  class="extraction-edit-card"
                >
                  <div class="card-line-top">
                    <span class="badge-idx">规则 #{{ rIdx + 1 }}</span>
                    <el-input
                      v-model="rule.targetField"
                      size="small"
                      placeholder="目标字段名 (如 trace_id)"
                      class="target-name-input"
                      @input="syncRawJson"
                    />
                    <el-select
                      v-model="rule.sourceType"
                      size="small"
                      class="type-select"
                      @change="syncRawJson"
                    >
                      <el-option value="json_path" label="JSON 嵌套路径 (JSONPath)" />
                      <el-option value="regex" label="正则表达式捕获 (Regex)" />
                      <el-option value="default_value" label="缺省默认填充值" />
                    </el-select>
                    <el-button
                      size="small"
                      text
                      type="danger"
                      @click="removeExtraction(rIdx)"
                    >
                      删除
                    </el-button>
                  </div>

                  <div class="card-line-bottom">
                    <div class="flex-1">
                      <label class="block text-[10px] text-muted mb-1">
                        {{
                          rule.sourceType === 'json_path'
                            ? 'JSONPath 表达式 (如 $.meta.trace.id 或 $.headers["x-req-id"])'
                            : rule.sourceType === 'regex'
                              ? '命名捕获正则 (如 client=(?P<ip>\\S+))'
                              : '静态默认值'
                        }}
                      </label>
                      <el-input
                        v-model="rule.expression"
                        size="small"
                        placeholder="输入抽取表达式..."
                        @input="syncRawJson"
                      />
                    </div>
                    <div class="w-40">
                      <label class="block text-[10px] text-muted mb-1">缺失兜底值 (可选)</label>
                      <el-input
                        v-model="rule.fallbackValue"
                        size="small"
                        placeholder="如 none 或 127.0.0.1"
                        @input="syncRawJson"
                      />
                    </div>
                  </div>
                </div>

                <div
                  v-if="!sourceForm.advanced.extractions.length"
                  class="empty-extraction-hint"
                >
                  暂无不规则字段抽取规则。点击上方「添加规则」或选择预设模板开始配置。
                </div>
              </div>
            </div>

            <!-- 模块 B：高级过滤条件与敏感字段脱敏 -->
            <div class="form-section">
              <div class="sec-title">02 · 高级过滤条件与敏感字段脱敏</div>
              <el-form-item label="原始布尔过滤表达式 (Filter Expression)">
                <el-input
                  v-model="sourceForm.advanced.filterExpr"
                  placeholder="例如: latency_ms > 1500 or (status >= 500 and uri.startswith('/api/v1'))"
                  @input="syncRawJson"
                />
                <p class="text-[11px] text-muted mt-1">
                  支持多条件组合过滤，仅符合表达式的日志事件才会被送往 AI 分析。
                </p>
              </el-form-item>

              <el-form-item label="敏感字段脱敏/排除清单 (逗号分隔)">
                <el-input
                  v-model="sourceForm.advanced.excludeFieldsStr"
                  placeholder="例如: password, authorization, token, cookie"
                  @input="syncRawJson"
                />
                <p class="text-[11px] text-muted mt-1">
                  被列出的敏感属性将在采集后自动剥离，保障数据安全隐私。
                </p>
              </el-form-item>
            </div>

            <!-- 模块 C：运行时异常策略与超时 -->
            <div class="form-section">
              <div class="sec-title">03 · 运行时异常策略 (SourcePolicy) 与超时控制</div>
              <div class="form-grid-2">
                <el-form-item label="采集报错时策略 (on_error)">
                  <el-select
                    v-model="sourceForm.advanced.onError"
                    class="w-full"
                    @change="syncRawJson"
                  >
                    <el-option value="notice" label="⚠️ 告警提示并继续 (notice - 推荐)" />
                    <el-option value="stop" label="⛔ 终止整个工作流 (stop)" />
                    <el-option value="skip" label="🔕 静默跳过该源 (skip)" />
                  </el-select>
                </el-form-item>

                <el-form-item label="目标缺失时策略 (on_missing)">
                  <el-select
                    v-model="sourceForm.advanced.onMissing"
                    class="w-full"
                    @change="syncRawJson"
                  >
                    <el-option value="notice" label="⚠️ 告警提示并继续 (notice)" />
                    <el-option value="stop" label="⛔ 终止整个工作流 (stop)" />
                    <el-option value="skip" label="🔕 静默跳过该源 (skip - 推荐)" />
                  </el-select>
                </el-form-item>
              </div>

              <div class="form-grid-2">
                <el-form-item label="采集内容为空时 (on_empty)">
                  <el-select
                    v-model="sourceForm.advanced.onEmpty"
                    class="w-full"
                    @change="syncRawJson"
                  >
                    <el-option value="notice" label="⚠️ 告警提示并继续 (notice - 推荐)" />
                    <el-option value="stop" label="⛔ 终止整个工作流 (stop)" />
                    <el-option value="skip" label="🔕 静默跳过该源 (skip)" />
                  </el-select>
                </el-form-item>

                <el-form-item label="过滤后为空时 (on_filtered_empty)">
                  <el-select
                    v-model="sourceForm.advanced.onFilteredEmpty"
                    class="w-full"
                    @change="syncRawJson"
                  >
                    <el-option value="skip" label="🔕 静默跳过该源 (skip - 推荐)" />
                    <el-option value="notice" label="⚠️ 告警提示并继续 (notice)" />
                    <el-option value="stop" label="⛔ 终止整个工作流 (stop)" />
                  </el-select>
                </el-form-item>
              </div>

              <div class="w-1/2 pr-2">
                <el-form-item label="采集超时时间 (秒)">
                  <el-input-number
                    v-model="sourceForm.advanced.timeout"
                    :min="5"
                    :max="600"
                    class="w-full"
                    @change="syncRawJson"
                  />
                </el-form-item>
              </div>
            </div>

            <!-- 模块 D：底层原始 JSON 查看与编辑模式 (高保真) -->
            <div class="form-section">
              <div class="flex justify-between items-center mb-2">
                <div class="sec-title mb-0">04 · 底层原始 JSON 配置 (开发者模式)</div>
                <el-button
                  size="small"
                  text
                  @click="showRawJsonEditor = !showRawJsonEditor"
                >
                  {{ showRawJsonEditor ? '收起底层 JSON' : '查看/编辑底层 JSON' }}
                </el-button>
              </div>

              <div v-if="showRawJsonEditor" class="raw-json-editor-wrap">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <span class="block text-[11px] font-mono text-muted mb-1">Options JSON (采集参数)</span>
                    <el-input
                      v-model="sourceForm.advanced.rawOptionsJson"
                      type="textarea"
                      :rows="6"
                      class="font-mono text-xs"
                    />
                  </div>
                  <div>
                    <span class="block text-[11px] font-mono text-muted mb-1">Setters JSON (处理规则与抽取)</span>
                    <el-input
                      v-model="sourceForm.advanced.rawSettersJson"
                      type="textarea"
                      :rows="6"
                      class="font-mono text-xs"
                    />
                  </div>
                </div>
                <div class="flex justify-end mt-2">
                  <el-button size="small" @click="syncRawJson">刷新/格式化 JSON</el-button>
                </div>
              </div>
            </div>
          </div>
        </el-form>

        <div class="drawer-footer-bar">
          <el-button @click="sourceDrawer = false">取消</el-button>
          <el-button
            type="primary"
            @click="activeEditingCentral ? saveCentralConfig() : saveSourceConfig()"
          >
            {{
              activeEditingCentral
                ? '保存并全量广播同步'
                : '保存配置'
            }}
          </el-button>
        </div>
      </div>
    </el-drawer>

    <!-- ========================================== -->
    <!-- 从资源配置中心加载已有数据源弹窗 -->
    <!-- ========================================== -->
    <el-dialog
      v-model="loadSourceModal"
      title="从资源配置中心加载已有数据源"
      width="740px"
      append-to-body
      destroy-on-close
    >
      <div class="load-source-dialog-body">
        <p class="dialog-subtitle">
          选择全局维护的标准数据源挂载至当前工作流。挂载后为跟随全局模式，在资源配置中心修改时将自动同步。
        </p>

        <div class="load-source-cards-list">
          <div
            v-for="src in centralDataSources"
            :key="src.id"
            class="load-source-card"
            :class="{ 'is-added': isSourceAlreadyLoaded(src.id) }"
          >
            <div class="load-source-main">
              <div class="load-source-top">
                <span class="collector-icon">
                  <AppIcon :name="collectorIcon(src.collector)" size="sm" />
                </span>
                <strong class="text-sm font-bold">{{ src.name }}</strong>
                <span class="badge-collector uppercase">{{ src.collector }}</span>
                <span v-if="src.advanced?.extractions?.length" class="badge-ext">
                  {{ src.advanced.extractions.length }} 项抽取
                </span>
                <span v-if="src.advanced?.filterExpr" class="badge-filter">
                  已配过滤
                </span>
              </div>
              <p class="load-source-desc">{{ src.description || '暂无描述' }}</p>
              <div class="load-source-meta">
                <span>路径: <code>{{ src.options.path }}</code></span>
                <span>上限: {{ src.options.maxLines }} 行</span>
                <span>保留字段: {{ src.rules.fields.slice(0, 4).join(', ') }}{{ src.rules.fields.length > 4 ? '...' : '' }}</span>
              </div>
            </div>

            <div class="load-source-action">
              <el-tag v-if="isSourceAlreadyLoaded(src.id)" type="info" size="small">
                已在工作流中
              </el-tag>
              <el-button
                v-else
                size="small"
                type="primary"
                @click="loadSourceIntoWorkflow(src)"
              >
                加载到本工作流
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-between items-center">
          <button
            type="button"
            class="text-xs text-primary hover:underline cursor-pointer bg-transparent border-0"
            @click="loadSourceModal = false; openCreateSource()"
          >
            没有合适的数据源？直接新建采集源 ➔
          </button>
          <el-button @click="loadSourceModal = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- ========================================== -->
    <!-- 模拟运行流水线弹窗 -->
    <!-- ========================================== -->
    <el-dialog v-model="runModalVisible" title="模拟运行工作流流水线" width="680px" append-to-body>
      <div class="run-dialog-body">
        <div class="pipeline-progress-steps">
          <div class="mini-step done">
            <AppIcon name="check" size="sm" />
            <span>1. 数据采集</span>
          </div>
          <div class="mini-line" />
          <div class="mini-step" :class="{ done: !runExecuting }">
            <AppIcon :name="!runExecuting ? 'check' : 'rotate'" size="sm" />
            <span>2. 并行分析</span>
          </div>
          <div class="mini-line" />
          <div class="mini-step" :class="{ done: !runExecuting }">
            <AppIcon :name="!runExecuting ? 'check' : 'sparkles'" size="sm" />
            <span>3. 汇聚汇总</span>
          </div>
          <div class="mini-line" />
          <div class="mini-step" :class="{ done: !runExecuting }">
            <AppIcon :name="!runExecuting ? 'check' : 'mail'" size="sm" />
            <span>4. 渠道分发</span>
          </div>
        </div>

        <div class="run-logs-terminal">
          <div v-for="(l, i) in runLogs" :key="i" class="log-line">{{ l }}</div>
          <div v-if="runExecuting" class="log-line blink">▌</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.workflow-demo-root {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1360px;
  margin: 0 auto;
  padding-bottom: 40px;
}

/* 顶部导航切换 */
.view-tab-nav {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--el-fill-color-dark);
  border: 1px solid var(--border);
  border-radius: 10px;
  width: fit-content;
}

.nav-tab-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.nav-tab-item.active {
  background: var(--surface);
  color: var(--el-color-primary);
  font-weight: 700;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

/* 视图 A：工作流布局 */
.workflow-orchestrator-layout {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.workflow-sidebar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}

.sidebar-top {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.sidebar-cards {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.wf-selector-card {
  display: flex;
  flex-direction: column;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  text-align: left;
  cursor: pointer;
  color: inherit;
  transition: all 0.12s ease;
  width: 100%;
}

.wf-selector-card:hover {
  background: var(--el-fill-color-light);
  border-color: var(--border);
}

.wf-selector-card.selected {
  background: color-mix(in srgb, var(--el-color-primary) 6%, var(--surface));
  border-color: color-mix(in srgb, var(--el-color-primary) 35%, transparent);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-head strong {
  font-size: 13px;
}

.cron-pill {
  font-size: 10px;
  font-family: ui-monospace, monospace;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-fill-color);
  color: var(--muted);
}

.card-desc {
  margin: 4px 0 8px;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-badges {
  display: flex;
  gap: 6px;
  font-size: 11px;
  color: var(--muted);
}

.tag-accent {
  background: #dbeafe;
  color: #1d4ed8;
  padding: 0 4px;
  border-radius: 3px;
  font-size: 10px;
}

/* 主编排流主干 */
.pipeline-main-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pipeline-header-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 18px 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.eyebrow {
  font-size: 10px;
  letter-spacing: 0.08em;
  font-weight: 700;
  color: var(--muted);
}

.pipeline-header-card h2 {
  margin: 2px 0 0;
  font-size: 20px;
}

/* 4 阶段通用卡片 */
.stage-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px 24px;
}

.stage-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.stage-title-wrap {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.stage-index {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: var(--el-fill-color);
  color: var(--el-text-color-primary);
  font-weight: 700;
  font-family: ui-monospace, monospace;
  font-size: 13px;
}

.stage-title-wrap h3 {
  margin: 0;
  font-size: 16px;
}

.stage-title-wrap p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.stage-head-actions {
  display: flex;
  gap: 8px;
}

/* 4 步骤流程导航栏 (Progressive Step Nav with Vue Router) */
.pipeline-step-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow-x: auto;
}

.step-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.step-nav-btn:hover {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
}

.step-nav-btn.active {
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--surface));
  border-color: color-mix(in srgb, var(--el-color-primary) 30%, transparent);
  color: var(--el-color-primary);
}

.step-num {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  background: var(--el-fill-color);
  color: var(--muted);
}

.step-nav-btn.active .step-num {
  background: var(--el-color-primary);
  color: #fff;
}

.step-text {
  display: flex;
  flex-direction: column;
}

.step-text strong {
  font-size: 13px;
  line-height: 1.2;
}

.step-text small {
  font-size: 11px;
  opacity: 0.8;
}

.step-arrow {
  color: var(--border);
  font-size: 12px;
  user-select: none;
}

.step-nav-extra {
  margin-left: auto;
}

.btn-all-overview {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--el-fill-color-light);
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.btn-all-overview:hover,
.btn-all-overview.active {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.step-footer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

/* 阶段 1：数据源卡片样式 (素雅中性无彩光) */
.sources-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.source-row-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  transition: all 0.15s ease;
}

.source-row-card:hover {
  border-color: var(--el-border-color);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.source-main-info {
  flex: 1;
  min-width: 0;
}

.source-top-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.index-badge {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  font-weight: 700;
  color: var(--muted);
  background: var(--el-fill-color);
  padding: 1px 6px;
  border-radius: 4px;
}

.collector-icon {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: var(--el-fill-color);
  color: var(--muted);
}

.source-title {
  font-size: 13px;
}

/* 纯净素雅的中性标签体系 (彻底告别五颜六色视觉疲劳) */
.tag-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid var(--border);
  background: var(--el-fill-color-light);
  color: var(--muted);
}

.tag-status.linked {
  color: var(--el-text-color-regular);
}

.tag-status.linked .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--el-color-primary);
}

.tag-status.detached {
  color: var(--muted);
}

.tag-status.neutral {
  color: var(--muted);
}

.source-details-summary {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}

.source-details-summary code {
  font-family: ui-monospace, monospace;
  color: var(--el-text-color-primary);
}

.source-hint-row {
  margin-top: 6px;
}

.source-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

/* 排序移动按钮组 */
.order-btn-group {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background: var(--surface);
}

.order-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  transition: all 0.12s ease;
}

.order-btn:hover:not(:disabled) {
  background: var(--el-fill-color);
  color: var(--el-color-primary);
}

.order-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.order-btn:first-child {
  border-right: 1px solid var(--border);
}

/* 阶段 2：并行 AI 分析网格 */
.analysis-tasks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
}

.analysis-task-card {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--el-fill-color-light);
}

.task-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.task-id-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.task-tag-mono {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  color: var(--muted);
}

.task-name-input {
  max-width: 160px;
}

.form-row .field-label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  margin-bottom: 4px;
}

/* 阶段 3：汇聚汇总 */
.fanin-config-body {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--el-fill-color-light);
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

/* 阶段 4：渠道分发卡片 */
.channel-selection-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.channel-option-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  cursor: pointer;
  transition: all 0.15s ease;
}

.channel-option-card:hover {
  border-color: var(--el-color-primary);
}

.channel-option-card.selected {
  border-color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 5%, var(--surface));
}

.chan-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: var(--el-fill-color);
  color: var(--el-color-primary);
}

.chan-info {
  flex: 1;
  min-width: 0;
}

.chan-info strong {
  display: block;
  font-size: 13px;
}

.chan-target-mono {
  display: block;
  font-size: 10px;
  font-family: ui-monospace, monospace;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 视图 B：资源配置中心 (Axonhub 风格) */
.resource-center-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.resource-intro-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.resource-intro-bar h3 {
  margin: 0 0 4px;
  font-size: 16px;
}

.central-source-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}

.axon-source-card {
  padding: 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.axon-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}

.axon-source-id {
  display: flex;
  align-items: center;
  gap: 10px;
}

.axon-avatar {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-color-primary) 10%, transparent);
  color: var(--el-color-primary);
}

.axon-source-id strong {
  display: block;
  font-size: 14px;
}

.source-key-tag {
  font-size: 10px;
  font-family: ui-monospace, monospace;
  color: var(--muted);
}

.axon-desc {
  font-size: 12px;
  color: var(--muted);
  margin: 0 0 12px;
  height: 36px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.axon-props-box {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  margin-bottom: 12px;
}

.axon-props-box .k {
  display: block;
  font-size: 10px;
  color: var(--muted);
}

.axon-props-box .v {
  font-size: 11px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sync-impact-box {
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  margin-bottom: 12px;
}

.impact-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 6px;
}

.impact-wf-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.impact-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--surface));
  color: var(--el-color-primary);
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 20%, transparent);
  cursor: pointer;
  transition: all 0.15s ease;
}

.impact-tag:hover {
  background: var(--el-color-primary);
  color: #fff;
}

.axon-card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

/* 抽屉与弹窗组件 */
.picker-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  cursor: pointer;
}

.picker-item:hover {
  border-color: var(--el-color-primary);
}

.drawer-form-content {
  padding-bottom: 70px;
}

.banner-alert {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 16px;
  margin-bottom: 16px;
  border-radius: 8px;
}

.banner-alert.info {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
}

.banner-alert.warning {
  background: #fffbeb;
  border-color: #fde68a;
  color: #92400e;
}

.banner-alert p {
  margin: 3px 0 0;
  font-size: 12px;
}

.form-section {
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.sec-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  letter-spacing: 0.05em;
  margin-bottom: 10px;
}

.drawer-footer-bar {
  position: fixed;
  right: 0;
  bottom: 0;
  width: min(94vw, 760px);
  padding: 14px 24px;
  background: var(--surface);
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  z-index: 10;
}

/* 工作流采集高级参数折叠栏 */
.workflow-advanced-params-bar {
  background: var(--el-fill-color-light);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 14px;
  overflow: hidden;
}

.params-bar-summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  background: color-mix(in srgb, var(--surface) 60%, transparent);
}

.params-bar-summary:hover {
  background: var(--el-fill-color);
}

.badge-param {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted);
}

.btn-toggle-subtle {
  border: none;
  background: transparent;
  font-size: 11px;
  color: var(--el-color-primary);
  cursor: pointer;
  font-weight: 500;
}

.params-bar-content {
  padding: 12px 14px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}

/* 采集源行卡片：高级特性指示徽标与展开面板 */
.adv-feature-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 12px;
  background: color-mix(in srgb, #8b5cf6 10%, transparent);
  color: #7c3aed;
  font-size: 11px;
  font-weight: 600;
}

.source-advanced-preview-wrap {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}

.toggle-inline-adv-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  font-size: 11px;
  font-weight: 600;
  color: var(--el-color-primary);
  cursor: pointer;
  padding: 0;
}

.toggle-inline-adv-btn:hover {
  text-decoration: underline;
}

.inline-adv-panel {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.adv-sec-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  margin-bottom: 4px;
}

.extractions-pill-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.extraction-pill-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 11px;
}

.extraction-pill-item .target-field {
  color: var(--el-color-primary);
}

.extraction-pill-item .sep {
  color: var(--muted);
}

.extraction-pill-item .source-expr {
  color: var(--el-text-color-primary);
  background: var(--el-fill-color);
  padding: 1px 4px;
  border-radius: 4px;
}

.extraction-pill-item .type-tag {
  font-size: 10px;
  padding: 0 4px;
  border-radius: 3px;
  background: #e0e7ff;
  color: #3730a3;
}

.extraction-pill-item .fallback-tag {
  font-size: 10px;
  color: var(--muted);
}

.policy-badges-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.badge-policy {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--muted);
}

.badge-policy strong {
  color: var(--el-text-color-primary);
}

/* Axonhub 全局数据源卡片高级特性 */
.axon-adv-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.adv-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--el-fill-color);
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 11px;
}

.adv-pill.subtle {
  background: var(--el-fill-color);
  color: var(--muted);
}

.adv-pill.filter {
  background: var(--el-fill-color);
  color: var(--muted);
}

/* 抽屉分段导航控制 */
.drawer-segmented-nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 4px;
  background: var(--el-fill-color-dark);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 16px;
}

.seg-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.seg-btn.active {
  background: var(--surface);
  color: var(--el-color-primary);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.seg-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  background: #7c3aed;
  color: #fff;
  font-weight: 700;
}

.subtle-guide-box {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: color-mix(in srgb, var(--el-color-primary) 6%, var(--surface));
  border: 1px dashed color-mix(in srgb, var(--el-color-primary) 30%, transparent);
  border-radius: 8px;
  cursor: pointer;
  margin-top: 14px;
  transition: all 0.15s ease;
}

.subtle-guide-box:hover {
  background: color-mix(in srgb, var(--el-color-primary) 10%, var(--surface));
}

/* 抽屉高级设置：预设与抽取规则编辑器 */
.preset-buttons-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.preset-btn {
  border: 1px solid var(--border);
  background: var(--surface);
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  color: var(--el-text-color-primary);
  transition: all 0.12s ease;
}

.preset-btn:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.extractions-editor-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.extraction-edit-card {
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.card-line-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.badge-idx {
  font-size: 10px;
  font-family: ui-monospace, monospace;
  font-weight: 700;
  color: var(--muted);
  white-space: nowrap;
}

.target-name-input {
  max-width: 180px;
}

.type-select {
  flex: 1;
}

.card-line-bottom {
  display: flex;
  gap: 10px;
}

.empty-extraction-hint {
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
  border: 1px dashed var(--border);
  border-radius: 8px;
}

.raw-json-editor-wrap {
  margin-top: 8px;
  padding: 12px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--border);
  border-radius: 8px;
}

/* 运行模拟器 */
.run-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pipeline-progress-steps {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.mini-step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--muted);
}

.mini-step.done {
  color: #10b981;
  font-weight: 600;
}

.mini-line {
  flex: 1;
  height: 2px;
  background: var(--border);
  margin: 0 8px;
}

.run-logs-terminal {
  background: #0f172a;
  color: #38bdf8;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  padding: 14px;
  border-radius: 8px;
  height: 240px;
  overflow-y: auto;
}

.log-line {
  line-height: 1.6;
}

.blink {
  animation: blink 1s infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

:global(.dark) .tag-status {
  background: var(--surface);
  border-color: var(--border);
}

:global(.dark) .banner-alert.info {
  background: #1e293b;
  border-color: #334155;
  color: #93c5fd;
}

:global(.dark) .banner-alert.warning {
  background: #1e293b;
  border-color: #334155;
  color: #e2e8f0;
}

:global(.dark) .extraction-pill-item {
  background: var(--surface);
  border-color: var(--border);
}

:global(.dark) .extraction-pill-item .type-tag {
  background: var(--el-fill-color);
  color: var(--muted);
}

:global(.dark) .extraction-edit-card,
:global(.dark) .inline-adv-panel,
:global(.dark) .raw-json-editor-wrap {
  background: var(--surface);
}

:global(.dark) .adv-pill {
  background: var(--surface);
  border-color: var(--border);
  color: var(--muted);
}

/* 加载已有数据源弹窗样式 */
.load-source-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dialog-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
}

.load-source-cards-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 420px;
  overflow-y: auto;
  padding-right: 4px;
}

.load-source-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  transition: all 0.15s ease;
}

.load-source-card:hover {
  border-color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 3%, var(--surface));
}

.load-source-card.is-added {
  opacity: 0.75;
  background: var(--el-fill-color-light);
}

.load-source-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.load-source-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.badge-collector {
  font-size: 10px;
  font-weight: 700;
  font-family: ui-monospace, monospace;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-fill-color);
  color: var(--muted);
}

.badge-ext {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, #8b5cf6 15%, transparent);
  color: #7c3aed;
  font-weight: 600;
}

.badge-filter {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, #f59e0b 15%, transparent);
  color: #b45309;
  font-weight: 600;
}

.load-source-desc {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.4;
}

.load-source-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 11px;
  color: var(--muted);
}

.load-source-meta code {
  font-size: 10px;
  font-family: ui-monospace, monospace;
  background: var(--el-fill-color);
  padding: 1px 4px;
  border-radius: 3px;
}

.load-source-action {
  flex-shrink: 0;
}

:global(.dark) .load-source-card.is-added {
  background: var(--surface);
  opacity: 0.6;
}
</style>
