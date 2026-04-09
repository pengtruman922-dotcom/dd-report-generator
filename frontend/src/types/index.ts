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
  extractor: StepConfig;
  researcher: StepConfig;
  writer: StepConfig;
  field_extractor: StepConfig;
  chunker: StepConfig;
  fastgpt?: FastGPTConfig;
}

export interface UploadResponse {
  session_id: string;
  company_count: number;
  companies: Company[];
}

export interface ManualInputResponse {
  session_id: string;
  bd_code: string;
  company_name: string;
  project_name: string;
}

export interface FieldDef {
  key: string;
  label: string;
  required: boolean;
}

export interface GenerateResponse {
  task_id: string;
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
  status: string;
  created_at: string;
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
  old: string | null;
  new: string;
}

export interface IntakeOperation {
  type: "create" | "update";
  company_name: string;
  bd_code?: string;
  fields?: Record<string, string>;            // for create
  changed_fields?: Record<string, IntakeChangedField>;  // for update
  source: string[];
}

export interface IntakeParseResult {
  operations: IntakeOperation[];
  summary: string;
  mode: string;
  input_sources: string[];
  raw_content_summary?: string;
}

export interface IntakeExecuteResult {
  task_id: string;
  report_id?: string;
  bd_code?: string;
  type: "create" | "light_update" | "full_regenerate";
  needs_research_prompt?: boolean;
  research_age_days?: number | null;
  research_expired?: boolean;
}

// In-memory intake task status from backend
export interface IntakeTaskStatus {
  task_id: string;
  report_id?: string;
  bd_code?: string;
  company_name: string;
  op_type: "create" | "light_update" | "full_regenerate";
  status: "queued" | "running" | "completed" | "cancelling" | "cancelled" | "failed";
  step: number;
  total_steps: number;
  queue_position?: number;
}

export interface IntakeLog {
  id: number;
  report_id: string;
  log_type: "create" | "light_update" | "full_regenerate";
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
