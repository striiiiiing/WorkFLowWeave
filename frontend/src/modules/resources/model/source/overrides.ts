import type { SourceConfig, SourceLimits } from './definition'
import type { SourceParameters } from './parameters'

export interface SourceOverride {
  source?: SourceConfig | null
  arguments?: SourceParameters | null
  limits?: SourceLimits
}

export type SourceSaveTarget =
  | { kind: 'shared-resource'; resourceId: string }
  | { kind: 'workflow-draft'; workflowId: string; sourceId: string }

export interface SourceUsageView {
  id: string
  name: string
  detached: boolean
}

/** The editor receives a save target; it does not choose persistence scope. */
export interface SourceConfigEditorGateway {
  resolve(sourceId: string, override?: SourceOverride, signal?: AbortSignal): Promise<SourceConfig>
  save(target: SourceSaveTarget, value: SourceConfig): Promise<void>
}
