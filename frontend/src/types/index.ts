/**
 * 契约数据类型定义 (镜像 contracts/data-models.md 与 contracts/module-interfaces.md)
 */

export type ID = string;

export type JSONValue =
  | string
  | number
  | boolean
  | null
  | { [key: string]: JSONValue }
  | JSONValue[];

export type JSONObject = { [key: string]: JSONValue };

export interface ErrorInfo {
  code: string;
  message: string;
  details?: JSONObject;
}

// ----------------- 资源配置 -----------------

export interface SourceConfig {
  id: ID;
  collector: string;
  options: JSONObject;
  setters: JSONObject;
  template?: string | null;
  timeout?: number;
  on_error?: 'stop' | 'skip';
  on_empty?: 'stop' | 'skip';
  on_filtered_empty?: 'stop' | 'skip';
}

export interface SetterTemplate {
  id: ID;
  collector: string;
  setters: JSONObject;
  description?: string;
}

export interface AIConfig {
  id: ID;
  provider: string;
  base_url?: string;
  api_key?: string;
  system_prompt?: string;
  timeout?: number;
  retries?: number;
  // models 字典：模型名 -> 额外参数
  models: Record<string, JSONObject>;
}

export interface ChannelConfig {
  id: ID;
  type: string;
  options: JSONObject;
}

export interface Credential {
  id: ID;
  type: 'env' | 'encrypted';
  reference?: string;
}

// ----------------- Workflow 定义 -----------------

export interface SourceOverride {
  options?: JSONObject;
  setters?: JSONObject;
  template?: string | null;
}

export interface ChannelOverride {
  options?: JSONObject;
}

export interface AnalysisTask {
  task_id: ID;
  task_name?: string;
  ai: ID;
  model: string;
  prompt: string;
}

export interface FanInConfig {
  enabled: boolean;
  ai?: ID | null;
  model?: string | null;
  prompt?: string | null;
}

export interface BackupPolicy {
  enabled: boolean;
  snapshot: boolean;
  collection: boolean;
  analysis: boolean;
  final: boolean;
  retention_days?: number | null;
  on_failure: 'stop' | 'continue';
}

export interface WorkflowDefinition {
  id: ID;
  name: string;
  description?: string;
  sources: ID[];
  source_overrides?: Record<ID, SourceOverride>;
  on_error?: 'stop' | 'skip';
  on_all_empty?: 'stop' | 'skip';
  analysis_tasks: AnalysisTask[];
  analysis_failure?: 'stop' | 'continue';
  send_partial?: boolean;
  fan_in?: FanInConfig;
  channels: ID[];
  channel_overrides?: Record<ID, ChannelOverride>;
  backup_policy: BackupPolicy;
}

// ----------------- 运行与 Session -----------------

export type SessionStatus =
  | 'created'
  | 'running'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'interrupted';

export type StageName =
  | 'collection'
  | 'analysis'
  | 'fan_in'
  | 'notification'
  | 'finish';

export type ArtifactAvailability =
  | 'available'
  | 'pending'
  | 'not_saved'
  | 'expired'
  | 'missing'
  | 'corrupt'
  | 'write_failed';

export interface ArtifactInfo {
  stage: StageName;
  availability: ArtifactAvailability;
  size_bytes?: number;
  error?: ErrorInfo;
}

export interface SessionRecord {
  workflow_id: ID;
  session_id: ID;
  version: number;
  status: SessionStatus;
  current_stage: StageName;
  created_at: string;
  updated_at: string;
  error?: ErrorInfo | null;
  stage_artifacts: Record<string, ArtifactInfo>;
  snapshot_availability: ArtifactAvailability;
}

export interface PhaseContent {
  session_id: ID;
  version: number;
  stage: StageName;
  content: JSONValue;
}

export interface DeliveryResult {
  channel_id: ID;
  status: 'success' | 'failed' | 'skipped' | 'delivery_uncertain';
  attempts: number;
  delivered_at?: string;
  error?: ErrorInfo;
}

// ----------------- 插件与系统 -----------------

export interface CapabilityDescription {
  id: string;
  kind: 'collector' | 'channel';
  version: string;
  owner?: string;
  options_schema: JSONObject;
  fields?: string[];
  description?: string;
}

export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  uptime_seconds: number;
  active_runs: number;
  max_concurrent_runs: number;
}
