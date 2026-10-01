// Transitional type exports; removed by P7. DTO definitions live with their owner.
export type { JsonValue, JsonObject, ErrorInfo } from '@/shared/types'
export type {
  SourcePolicy,
  SourceConfig,
  MCPServerConfig,
  Credential,
  AIConfig,
  ChannelConfig,
  SourceOverride,
  ChannelOverride,
  ResourceMap,
  ResourceKind,
} from '@/modules/resources/model/types'
export type {
  ContinuePolicy,
  AnalysisTask,
  FanInConfig,
  BackupPolicy,
  WorkflowDefinition,
} from '@/modules/workflows/model/types'
export type {
  WorkflowStage,
  SessionStatus,
  ArtifactAvailability,
  ArtifactInfo,
  PhaseContent,
  SessionRecord,
  RecoveryAvailability,
  ReportSection,
} from '@/modules/runs/model/types'
export type {
  CapabilityDescription,
  DiscoveryReport,
  ComponentHealth,
  HealthReport,
} from '@/modules/system/model/types'
