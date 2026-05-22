import type {
  AISettings,
  ReportResponse,
  ReportListResponse,
  ReportChunk,
  UserInfo,
  AttachmentInfo,
  ToolProviderInfo,
  ToolsConfig,
  ModelWorkbenchResponse,
} from "../types";

const BASE = "/api";
const TOKEN_KEY = "dd_auth_token";

function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/login";
    throw new Error("登录已过期");
  }
  return res;
}

// ── Settings ──

export async function getSettings(): Promise<AISettings> {
  const res = await authFetch(`${BASE}/settings`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveSettings(cfg: AISettings): Promise<void> {
  const res = await authFetch(`${BASE}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── Report management ──

export async function getReport(reportId: string): Promise<ReportResponse> {
  const res = await authFetch(`${BASE}/report/${reportId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getReportMeta(reportId: string): Promise<import("../types").ReportMeta> {
  const res = await authFetch(`${BASE}/report/${reportId}/meta`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function getDownloadUrl(reportId: string): string {
  return `${BASE}/report/${reportId}/download`;
}

export function getPdfDownloadUrl(reportId: string): string {
  return `${BASE}/report/${reportId}/download/pdf`;
}

export function createProgressSource(taskId: string): EventSource {
  return new EventSource(`${BASE}/report/progress/${taskId}`);
}

export interface ListReportsParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  rating?: string;
  feasibility_rating?: string;
  owner?: string;
  sort_by?: string;
  sort_dir?: string;
}

export async function getModelWorkbench(): Promise<ModelWorkbenchResponse> {
  const res = await authFetch(`${BASE}/settings/model-workbench`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveModelWorkbench(payload: {
  ai_config: Record<string, any>;
  prompt_overrides: Record<string, string>;
}): Promise<void> {
  const res = await authFetch(`${BASE}/settings/model-workbench`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function testModelWorkbenchNode(payload: {
  node_id: string;
  ai_config: Record<string, any>;
}): Promise<{
  ok: boolean;
  node_id: string;
  node_label: string;
  message: string;
  provider: {
    base_url: string;
    model: string;
    base_url_source: string;
    model_source: string;
    api_key_source: string;
  };
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}> {
  const res = await authFetch(`${BASE}/settings/model-workbench/test-node`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let message = await res.text();
    try {
      const data = JSON.parse(message);
      message = data.detail || message;
    } catch {}
    throw new Error(message);
  }
  return res.json();
}

export async function listReports(params?: ListReportsParams): Promise<ReportListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.page) queryParams.set("page", params.page.toString());
  if (params?.page_size) queryParams.set("page_size", params.page_size.toString());
  if (params?.search) queryParams.set("search", params.search);
  if (params?.status) queryParams.set("status", params.status);
  if (params?.rating) queryParams.set("rating", params.rating);
  if (params?.feasibility_rating) queryParams.set("feasibility_rating", params.feasibility_rating);
  if (params?.owner) queryParams.set("owner", params.owner);
  if (params?.sort_by) queryParams.set("sort_by", params.sort_by);
  if (params?.sort_dir) queryParams.set("sort_dir", params.sort_dir);

  const queryString = queryParams.toString();
  const url = queryString ? `${BASE}/report/list?${queryString}` : `${BASE}/report/list`;
  const res = await authFetch(url);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteReport(reportId: string): Promise<void> {
  const res = await authFetch(`${BASE}/report/${reportId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export async function batchDeleteReports(reportIds: string[]): Promise<void> {
  const res = await authFetch(`${BASE}/report/batch-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ report_ids: reportIds }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── Chunks & FastGPT ──

export async function getChunks(
  reportId: string,
): Promise<ReportChunk[]> {
  const res = await authFetch(`${BASE}/report/${reportId}/chunks`);
  if (!res.ok) {
    if (res.status === 404) return [];
    throw new Error(await res.text());
  }
  const data = await res.json();
  return data.chunks;
}

export async function saveChunks(
  reportId: string,
  chunks: ReportChunk[],
): Promise<void> {
  const res = await authFetch(`${BASE}/report/${reportId}/chunks`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(chunks),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function pushToFastGPT(
  reportId: string,
): Promise<{ collection_id: string; uploaded: number; total: number }> {
  const res = await authFetch(`${BASE}/report/${reportId}/push-fastgpt`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── User management (admin) ──

export async function listUsers(): Promise<UserInfo[]> {
  const res = await authFetch(`${BASE}/auth/users`);
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.users;
}

export async function createUser(
  username: string,
  password: string,
  role: string,
): Promise<void> {
  const res = await authFetch(`${BASE}/auth/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, role }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "创建失败" }));
    throw new Error(data.detail || "创建失败");
  }
}

export async function updateUser(id: number, role: string): Promise<void> {
  const res = await authFetch(`${BASE}/auth/users/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "修改失败" }));
    throw new Error(data.detail || "修改失败");
  }
}

export async function deleteUser(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/auth/users/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "删除失败" }));
    throw new Error(data.detail || "删除失败");
  }
}

export async function resetUserPassword(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/auth/users/${id}/reset-password`, {
    method: "POST",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "重置失败" }));
    throw new Error(data.detail || "重置失败");
  }
}

// ── Report metadata & attachments ──

export async function updateReportMeta(
  reportId: string,
  updates: Record<string, any>,
): Promise<void> {
  const res = await authFetch(`${BASE}/report/${reportId}/meta`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function confirmReport(reportId: string): Promise<void> {
  const res = await authFetch(`${BASE}/report/${reportId}/confirm`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function listAttachments(reportId: string): Promise<AttachmentInfo[]> {
  const res = await authFetch(`${BASE}/report/${reportId}/attachments`);
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.attachments;
}

export function getAttachmentDownloadUrl(reportId: string, filename: string): string {
  return `${BASE}/report/${reportId}/attachments/${encodeURIComponent(filename)}`;
}

export async function downloadAttachmentFile(reportId: string, filename: string): Promise<Blob> {
  const res = await authFetch(
    `${BASE}/report/${reportId}/attachments/${encodeURIComponent(filename)}`,
  );
  if (!res.ok) throw new Error(await res.text());
  return res.blob();
}

export async function deleteAttachment(reportId: string, filename: string): Promise<void> {
  const res = await authFetch(
    `${BASE}/report/${reportId}/attachments/${encodeURIComponent(filename)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await res.text());
}

export async function uploadReportAttachments(
  reportId: string,
  files: File[],
): Promise<{ uploaded: number; files: AttachmentInfo[] }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await authFetch(`${BASE}/report/${reportId}/attachments`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function startAttachmentUpdate(
  reportId: string,
  attachmentFilenames: string[],
  note = "",
): Promise<import("../types").IntakeExecuteResult> {
  const res = await authFetch(`${BASE}/report/${reportId}/attachments/update-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ attachment_filenames: attachmentFilenames, note }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Tool configuration ──

export async function getToolProviders(): Promise<Record<string, ToolProviderInfo[]>> {
  const res = await authFetch(`${BASE}/tools/providers`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getToolsConfig(): Promise<ToolsConfig> {
  const res = await authFetch(`${BASE}/tools`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveToolsConfig(config: ToolsConfig): Promise<void> {
  const res = await authFetch(`${BASE}/tools`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tools: config }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── Intake Agent ──

export async function startParseIntake(
  text: string,
  urls: string[],
  files: File[],
  mode: "auto" | "manual",
): Promise<{ parse_job_id: string }> {
  const form = new FormData();
  form.append("text", text);
  form.append("urls", JSON.stringify(urls));
  form.append("mode", mode);
  for (const f of files) form.append("files", f);
  const res = await authFetch(`${BASE}/intake/parse-async`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getParseIntakeStatus(
  parseJobId: string,
): Promise<import("../types").IntakeParseStatus> {
  const res = await authFetch(`${BASE}/intake/parse-status/${parseJobId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function executeIntake(
  operation: import("../types").IntakeOperation,
  inputSources: string[],
  forceFullResearch = false,
): Promise<import("../types").IntakeExecuteResult> {
  const res = await authFetch(`${BASE}/intake/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operation, input_sources: inputSources, force_full_research: forceFullResearch }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getIntakeLogs(
  reportId: string,
): Promise<{ logs: import("../types").IntakeLog[]; count: number }> {
  const res = await authFetch(`${BASE}/intake/logs/${reportId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function cancelIntakeTask(taskId: string): Promise<{ ok: boolean; rolled_back: boolean }> {
  const res = await authFetch(`${BASE}/intake/cancel/${taskId}`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listIntakeTasks(): Promise<{ tasks: import("../types").IntakeTaskStatus[] }> {
  const res = await authFetch(`${BASE}/intake/tasks`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Rating management ──

export async function confirmRatingChange(
  reportId: string,
  action: "accept" | "reject",
  note?: string
): Promise<{ status: string; new_rating?: string }> {
  const res = await authFetch(`${BASE}/report/${reportId}/rating-confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, note }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Legacy chunk compatibility ──

export async function getLegacyChunks(reportId: string): Promise<Record<string, any>> {
  const res = await authFetch(`${BASE}/report/${reportId}/chunks-legacy`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const getChunksV3 = getLegacyChunks;

