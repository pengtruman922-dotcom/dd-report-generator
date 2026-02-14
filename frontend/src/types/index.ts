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
  status: string;
  created_at: string;
  file_size: number;
  attachments?: AttachmentInfo[];
  push_status?: PushStatus;
  push_info?: PushRecord | null;
  owner?: string;
  push_records?: Record<string, PushRecord>;
  [key: string]: any; // allow extra fields
}

export interface ReportListResponse {
  reports: ReportMeta[];
  total: number;
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
