export interface UserInfo {
  id: number;
  username: string;
  role: "admin" | "user";
  must_change_password: boolean;
  created_at?: string;
}

export interface Company {
  bd_code: string;
  company_name: string;
  project_name: string;
}

export interface StepConfig {
  base_url: string;
  api_key: string;
  model: string;
}

export interface AISettings {
  researcher: StepConfig;
  matcher_agent?: StepConfig;
  writer_agent?: StepConfig;
  tracking_processor?: StepConfig;
  info_chunk_writer?: StepConfig;
  index_builder?: StepConfig;
  attachment_update_planner?: StepConfig;
  rating_agent?: StepConfig;
  intake_agent?: IntakeAgentConfig;
  fastgpt?: FastGPTConfig;
}

export interface ProgressEvent {
  step: number;
  total: number;
  message: string;
}

export interface CompleteEvent {
  report_id: string;
}

export interface ErrorEvent {
  error: string;
}

export interface ReportResponse {
  report_id: string;
  content: string;
}

export interface ReportMeta {
  report_id: string;
  bd_code: string;
  company_name: string;
  project_name?: string;
  industry: string;
  province: string;
  city?: string;
  district?: string;
  is_listed: string;
  stock_code?: string;
  revenue?: string | null;
  revenue_yuan?: string | null;
  net_profit?: string | null;
  net_profit_yuan?: string | null;
  valuation_yuan?: string | null;
  valuation_date?: string | null;
  offer_yuan?: string | null;
  offer_date?: string | null;
  website?: string | null;
  description?: string | null;
  company_intro?: string | null;
  industry_tags?: string | null;
  referral_status?: string | null;
  is_traded?: string | null;
  dept_primary?: string | null;
  dept_owner?: string | null;
  remarks?: string | null;
  score: number | null;
  rating: string | null;
  manual_rating?: string | null;
  manual_rating_note?: string | null;
  feasibility_rating?: string | null;
  feasibility_rating_detail?: string | null;
  feasibility_rating_at?: string | null;
  pending_rating_change?: string | null;
  status: string;
  created_at: string;
  updated_at?: string;
  file_size: number;
  attachments?: AttachmentInfo[];
  push_status?: PushStatus;
  push_info?: PushRecord | null;
  owner?: string;
  push_records?: Record<string, PushRecord>;
  token_usage_json?: string | null;
  estimated_cost?: number | null;
  [key: string]: any; // allow extra fields
}

export interface ReportListResponse {
  reports: ReportMeta[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ChunkIndex {
  text: string;
}

export interface ReportChunk {
  title: string;
  q: string;
  indexes: ChunkIndex[];
  chunk_id?: string;
  chunk_kind?: "info" | "tracking";
  summary?: string;
  content?: string;
}

export interface FastGPTConfig {
  enabled: boolean;
  api_url: string;
  api_key: string;
  dataset_id: string;
}

export interface AttachmentInfo {
  filename: string;
  size: number;
}

export type PushStatus = "no_chunks" | "not_pushed" | "pushed" | "outdated";

export interface PushRecord {
  collection_id: string;
  pushed_at: string;
  chunks_hash: string;
  uploaded: number;
  total: number;
}

// ── Tool configuration types ──────────────────────────────────

export interface ToolConfigField {
  key: string;
  label: string;
  type: "text" | "password" | "number";
  required: boolean;
  default: any;
  description: string;
}

export interface ToolProviderInfo {
  provider_id: string;
  tool_type: string;
  display_name: string;
  description: string;
  config_schema: ToolConfigField[];
  target_company_type: "all" | "listed" | "unlisted";
}

export interface ToolTypeConfig {
  active_provider?: string;       // for search/scraper (single select)
  active_providers?: string[];    // for datasource (multi select)
  providers: Record<string, Record<string, any>>;
}

export interface ToolsConfig {
  search: ToolTypeConfig;
  scraper: ToolTypeConfig;
  datasource: ToolTypeConfig;
}

// ── Intake Agent types ────────────────────────────────────────

export interface IntakeChangedField {
  old: string | number | null;
  new: string | number | null;
  source_chunk?: string;
  source_label?: string;
}

export interface IntakeOperation {
  type: "create" | "update";
  company_name: string;
  bd_code?: string;
  fields?: Record<string, string>;            // for create
  changed_fields?: Record<string, IntakeChangedField>;  // for update
  source: string[];
  material_summary?: string;
  related_attachments?: string[];
  related_attachment_paths?: Record<string, string>;
  available_attachments?: string[];
  available_attachment_paths?: Record<string, string>;
  match_confidence?: "high" | "medium" | "low" | null;
  match_reason?: string | null;
}

export interface IntakeConfirmationItem {
  project_name: string;
  action: "create" | "update";
  matched_report_id?: string | null;
  matched_company_name?: string | null;
  match_confidence?: "high" | "medium" | "low" | null;
  match_reason?: string | null;
  material_summary?: string;
  related_attachments?: string[];
  needs_user_attention?: boolean;
  attention_reason?: string;
}

export interface IntakeParseResult {
  operations: IntakeOperation[];
  summary: string;
  mode: string;
  input_sources: string[];
  confirmation_items?: IntakeConfirmationItem[];
  targets?: Array<Record<string, any>>;
  matcher_result?: Array<Record<string, any>>;
  raw_content_summary?: string;
}

export interface IntakeParseStatus {
  parse_job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  message: string;
  progress: number;
  result: IntakeParseResult | null;
  error: string | null;
}

export interface IntakeExecuteResult {
  task_id: string;
  report_id?: string;
  bd_code?: string;
  type: "create" | "update" | "attachment_update" | "light_update" | "full_regenerate";
  needs_research_prompt?: boolean;
  research_age_days?: number | null;
  research_expired?: boolean;
  auto_push_enabled?: boolean;
}

// In-memory intake task status from backend
export interface IntakeTaskStatus {
  task_id: string;
  report_id?: string;
  bd_code?: string;
  company_name: string;
  op_type: "create" | "update" | "light_update" | "full_regenerate";
  status: "pending" | "queued" | "running" | "completed" | "cancelling" | "cancelled" | "failed";
  step: number;
  total_steps: number;
  queue_position?: number;
  message?: string;
  error_message?: string | null;
}

export interface IntakeLog {
  id: number;
  report_id: string;
  log_type: "create" | "update" | "attachment_update" | "light_update" | "full_regenerate";
  trigger_reason: string | null;
  input_sources: string[];
  changed_fields: Record<string, IntakeChangedField>;
  steps_executed: string[];
  steps_skipped: Array<{ step: string; reason: string }>;
  research_data_age_days: number | null;
  operator: string | null;
  created_at: string;
}

export interface IntakeAgentConfig {
  base_url: string;
  api_key: string;
  model: string;
  max_crawl_depth: number;
  default_mode: "auto" | "manual";
  core_fields_trigger_research: string[];
  research_data_expire_days: number;
}

export interface ModelPromptView {
  id: string;
  default: string;
  current: string;
  overridden: boolean;
  label?: string;
}

export interface ModelConfigSourceView {
  mode: "custom" | "inherited" | "system_default";
  label: string;
  source_node?: string | null;
}

export interface ModelProviderFieldView {
  key: "base_url" | "api_key" | "model";
  label: string;
  input_type: "text" | "password";
  value: string;
  default_value?: string;
  editable: boolean;
  is_secret?: boolean;
  configured?: boolean;
  display_value?: string;
  status_text?: string;
  source: ModelConfigSourceView;
}

export interface ModelProviderView {
  fields: ModelProviderFieldView[];
  summary: {
    model: string;
    base_url: string;
    api_key_configured: boolean;
  };
}

export interface ModelBehaviorFieldOption {
  label: string;
  value: string;
}

export interface ModelBehaviorFieldView {
  key: string;
  label: string;
  input_type: "text" | "number" | "select" | "tags";
  description?: string;
  options?: ModelBehaviorFieldOption[];
  value: any;
  default_value?: any;
  editable: boolean;
  source: ModelConfigSourceView;
}

export interface ModelBehaviorView {
  fields: ModelBehaviorFieldView[];
}

export interface ModelNodeView {
  id: string;
  label: string;
  group: string;
  stage: string;
  description: string;
  runtime_file: string;
  prompt_file: string;
  is_primary: boolean;
  config_key?: string;
  config_mode: "custom" | "inherited" | "prompt_only";
  node_kind: "model" | "model_with_behavior" | "prompt_only";
  inherits_from?: string;
  source_badge?: string;
  can_customize?: boolean;
  can_reset?: boolean;
  reset_label?: string;
  prompt_override_count?: number;
  provider?: ModelProviderView;
  behavior?: ModelBehaviorView;
  prompt?: ModelPromptView;
  prompt_variants?: ModelPromptView[];
}

export interface ModelWorkbenchResponse {
  nodes: ModelNodeView[];
  ai_config: Record<string, any>;
  prompt_overrides: Record<string, string>;
}
