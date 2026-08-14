export type PackName = 'OPD' | 'IPD'
export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type CellStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'
export type JudgeMode = 'gold_grade' | 'doc_grade' | 'head_to_head'

export interface Runtime { model_id: string | null; thinking_budget: number | null; thinking_level: string | null; max_output_tokens: number | null; timeout_s: number | null }
export interface RunSpec { name: string; pack: PackName; variant: string | null; selected_tasks: string[]; document_ids: number[]; model_ids: string[]; upstream_mode: 'gold' | 'model'; prompt_overrides: Record<string, {system_prompt: string; instruction_template: string}>; runtime_overrides: Record<string, Partial<Runtime>>; concurrency: {global: number; per_provider: Record<string, number>}; judge: {enabled: boolean; model_id: string; modes: JudgeMode[]}; compression: {enabled: boolean; max_megapixels: number; max_image_mb: number | null}; confirm_large: boolean }
export interface DocumentItem { id: number; filename: string; name?: string; sha256?: string; page_count?: number; origin?: string; created_at?: string | null; has_gold?: boolean | Record<string, boolean>; gold_keys?: string[] }

export interface TaskMeta { name: string; deterministic: boolean; depends_on: string[]; document_types?: string[]; is_text_task?: boolean; reference_runtime: Runtime; gold_feed_keys: string[]; system_prompt?: string; instruction_template?: string }
export interface PackMeta { name: PackName; variants?: string[]; tasks: TaskMeta[]; order?: string[] }
export interface ModelCapabilities {
  modalities?: string[]
  pdf_native?: boolean
  vision?: boolean
  structured_method?: string
  thinking?: boolean | string
  caching?: boolean
  batch?: boolean
  context_window?: number | null
  [key: string]: unknown
}

export interface ModelItem {
  id: string
  model_id?: string
  name?: string
  provider: string
  family?: string
  enabled?: boolean
  verified?: boolean
  gate_reason?: string | null
  release_date?: string | null
  context_window?: number | null
  capabilities?: string[] | ModelCapabilities
  pricing?: {
    input?: number | null
    output?: number | null
    input_per_million?: number | null
    output_per_million?: number | null
    cache_read_per_million?: number | null
    thinking_per_million?: number | null
  }
}

export interface DiscoveredModelItem {
  model_id: string
  name: string
  provider: string
  family: string
  publisher: string
  description?: string | null
  is_registered: boolean
  is_callable?: boolean | null
  capabilities: ModelCapabilities
  pricing: {
    input?: number | null
    output?: number | null
    input_per_million?: number | null
    output_per_million?: number | null
    cache_read_per_million?: number | null
    thinking_per_million?: number | null
  }
  release_date?: string | null
  status: 'registered' | 'available' | 'callable' | 'unverified' | string
}

export interface DiscoverVertexResponse {
  total: number
  has_credentials: boolean
  project?: string | null
  location: string
  discovered: DiscoveredModelItem[]
}

export interface AddModelPayload {
  model_id: string
  display_name: string
  provider?: string
  family?: string | null
  access?: string
  modalities?: string[]
  pdf_native?: boolean
  vision?: boolean
  context_window?: number | null
  structured_method?: string
  thinking?: boolean
  caching?: boolean
  batch?: boolean
  input_per_million?: number
  output_per_million?: number
  enabled?: boolean
  verify_now?: boolean
  notes?: string | null
}
export interface TokenUsage {
  input_tokens?: number
  output_tokens?: number
  thinking_tokens?: number
  cached_tokens?: number
  total_tokens?: number
  [key: string]: number | undefined
}

export interface CostBreakdown {
  input_usd?: number
  output_usd?: number
  cache_usd?: number
  thinking_usd?: number
  total_usd?: number
}

export interface Counts { total: number; succeeded: number; failed: number; skipped: number; pending: number; running?: number }
export interface Cell { document_id?: number; document?: string; document_name?: string; model?: string; model_id: string; task: string; status: CellStatus; created_at?: string | null; completed_at?: string | null; latency_ms?: number | null; cost_usd?: number | null; cost_breakdown?: CostBreakdown | null; error?: string | null; skip_reason?: string | null; retries?: number; parsed_output?: unknown; prompt_system?: string; prompt_instruction?: string; prompt_version?: string | null; raw_response?: unknown; usage?: TokenUsage; score?: Record<string, unknown> }
export interface RunItem { run_id: number; id?: number; name: string; pack: PackName; status: RunStatus; created_at: string; elapsed_ms?: number | null; counts: Counts; spec: RunSpec; cost_usd?: number; judge_status?: string; failure_reason?: string | null }
export interface RunDetail { run: RunItem; cells: Cell[] }
export interface ProgressEvent { type: 'cell' | 'run'; run_id: number; document_id?: number; document?: string; model_id?: string; task?: string; status: CellStatus | RunStatus; latency_ms?: number; cost_usd?: number; error?: string | null; skip_reason?: string | null; counts?: Counts }
export interface DryRun { layers: string[][]; gold_requirements: Record<string, string[]>; cost_estimate: number | {usd?: number; total_usd?: number}; missing_gold?: Record<string, string[]> }
export interface Prompt { task?: string; task_name?: string; active_version?: number; version?: number; system_prompt: string; instruction_template: string; source_repo?: string; source_branch?: string; source_path?: string; active?: boolean; differs_from_code?: boolean; created_at?: string; source?: string }
export interface LeaderboardRow { task: string; model: string; model_id?: string; accuracy?: number; valid_percent?: number; valid_rate?: number; judge_score?: number; mean_rank?: number; win_rate?: number; cost_per_doc?: number; cost_usd?: number; median_latency_ms?: number; latency_ms?: number; composite?: number }
export interface FieldRow { path: string; per_model: Record<string, number> }
export interface SideBySide { gold: unknown; models?: Record<string, {parsed_output: unknown; latency_ms?: number | null; completed_at?: string | null; field_metrics?: Record<string, unknown>; judge?: unknown; prompt_system?: string; prompt_instruction?: string; prompt_version?: string | null; raw_response?: string}>; outputs?: Array<{model_id: string; parsed_output: unknown; latency_ms?: number | null; completed_at?: string | null; field_metrics?: Record<string, unknown>; judge?: unknown; prompt_system?: string; prompt_instruction?: string; prompt_version?: string | null; raw_response?: string}>; judge?: unknown }
