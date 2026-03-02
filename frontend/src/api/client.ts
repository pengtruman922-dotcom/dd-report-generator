import type {
  AISettings,
  UploadResponse,
  GenerateResponse,
  ReportResponse,
  ReportListResponse,
  ManualInputResponse,
  FieldDef,
  ReportChunk,
  UserInfo,
  AttachmentInfo,
  ToolProviderInfo,
  ToolsConfig,
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

// ── Upload (no auth needed for upload endpoints, but we add token anyway) ──

export async function uploadExcel(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await authFetch(`${BASE}/upload/excel`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitManualInput(
  data: Record<string, string>,
): Promise<ManualInputResponse> {
  const res = await authFetch(`${BASE}/upload/manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getFieldDefs(): Promise<FieldDef[]> {
  const res = await authFetch(`${BASE}/upload/fields`);
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.fields;
}

export async function uploadAttachments(
  sessionId: string,
  bdCode: string,
  files: File[],
): Promise<{ uploaded: number }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await authFetch(
    `${BASE}/upload/attachments?session_id=${sessionId}&bd_code=${bdCode}`,
    { method: "POST", body: form },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
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

// ── Report generation & management ──

export async function generateReport(
  sessionId: string,
  bdCode: string,
  reportId?: string,
): Promise<GenerateResponse> {
  const body: Record<string, string> = { session_id: sessionId, bd_code: bdCode };
  if (reportId) body.report_id = reportId;
  const res = await authFetch(`${BASE}/report/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function batchGenerateReports(
  sessionId: string,
  bdCodes: string[],
): Promise<{ task_ids: string[]; count: number }> {
  const res = await authFetch(`${BASE}/report/batch-generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, bd_codes: bdCodes }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getReport(reportId: string): Promise<ReportResponse> {
  const res = await authFetch(`${BASE}/report/${reportId}`);
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
  owner?: string;
  sort_by?: string;
  sort_dir?: string;
}

export async function listReports(params?: ListReportsParams): Promise<ReportListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.page) queryParams.set("page", params.page.toString());
  if (params?.page_size) queryParams.set("page_size", params.page_size.toString());
  if (params?.search) queryParams.set("search", params.search);
  if (params?.status) queryParams.set("status", params.status);
  if (params?.rating) queryParams.set("rating", params.rating);
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

export async function regenerateChunks(
  reportId: string,
): Promise<ReportChunk[]> {
  const res = await authFetch(`${BASE}/report/${reportId}/regenerate-chunks`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.chunks;
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

export async function updateReportContent(
  reportId: string,
  content: string,
): Promise<void> {
  const res = await authFetch(`${BASE}/report/${reportId}/content`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
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
): Promise<{ uploaded: number }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await authFetch(`${BASE}/report/${reportId}/attachments`, {
    method: "POST",
    body: form,
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

// ── Version Management ──

export async function listVersions(reportId: string): Promise<{ versions: any[]; count: number }> {
  const res = await authFetch(`${BASE}/report/${reportId}/versions`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getVersion(reportId: string, versionId: string): Promise<any> {
  const res = await authFetch(`${BASE}/report/${reportId}/versions/${versionId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function restoreVersion(reportId: string, versionId: string): Promise<void> {
  const res = await authFetch(`${BASE}/report/${reportId}/versions/${versionId}/restore`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
}

