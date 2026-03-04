import { useState, useCallback, useEffect } from "react";
import { useLocation } from "react-router-dom";
import FileUpload from "./FileUpload";
import CompanySelector from "./CompanySelector";
import CompanySelectorMulti from "./CompanySelectorMulti";
import PipelineProgress from "./PipelineProgress";
import BatchProgress from "./BatchProgress";
import ReportViewer from "./ReportViewer";
import ReportActions from "./ReportActions";
import {
  uploadExcel,
  uploadAttachments,
  generateReport,
  batchGenerateReports,
  getReport,
  submitManualInput,
  getFieldDefs,
} from "../api/client";
import { useSSE } from "../hooks/useSSE";
import type { Company, FieldDef, ReportMeta } from "../types";

type InputMode = "excel" | "manual";
type GenerateMode = "single" | "batch";

// Manual input form field ordering (required first)
const REQUIRED_KEYS = ["company_name", "project_name"];  // bd_code now optional (auto-generated)

interface RegenerateState {
  regenerateId: string;
  meta: ReportMeta;
}

export default function HomePage() {
  const location = useLocation();
  const regenState = location.state as RegenerateState | null;

  // Input mode
  const [inputMode, setInputMode] = useState<InputMode>(
    regenState ? "manual" : "excel",
  );

  // Upload state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedBd, setSelectedBd] = useState<string | null>(null);
  const [selectedBds, setSelectedBds] = useState<Set<string>>(new Set());
  const [generateMode, setGenerateMode] = useState<GenerateMode>("single");
  const [attachmentNames, setAttachmentNames] = useState<string[]>(() => {
    if (regenState?.meta?.attachments) {
      return regenState.meta.attachments.map((a) => a.filename);
    }
    return [];
  });
  const [uploading, setUploading] = useState(false);

  // Manual input state
  const [fieldDefs, setFieldDefs] = useState<FieldDef[]>([]);
  const [manualData, setManualData] = useState<Record<string, string>>(() => {
    if (regenState?.meta) {
      const m = regenState.meta;
      const init: Record<string, string> = {};
      // Copy all string fields from meta
      for (const [k, v] of Object.entries(m)) {
        if (v != null && typeof v !== "object") init[k] = String(v);
      }
      return init;
    }
    return {};
  });
  const [manualReady, setManualReady] = useState(false);

  // Regeneration: report_id to overwrite
  const [regenerateId] = useState<string | null>(regenState?.regenerateId ?? null);

  // Generation state
  const [taskId, setTaskId] = useState<string | null>(null);
  const [batchTaskIds, setBatchTaskIds] = useState<string[]>([]);
  const [reportContent, setReportContent] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const sse = useSSE(taskId);

  // Load field definitions for manual input
  useEffect(() => {
    getFieldDefs()
      .then(setFieldDefs)
      .catch(() => {});
  }, []);

  // When SSE completes, fetch the report
  const handleSSEComplete = useCallback(async () => {
    if (sse.reportId && !reportContent) {
      const data = await getReport(sse.reportId);
      setReportContent(data.content);
      setGenerating(false);
    }
  }, [sse.reportId, reportContent]);

  if (sse.done && sse.reportId && !reportContent) {
    handleSSEComplete();
  }

  // Reset all state when switching input mode (with confirmation)
  const switchMode = (mode: InputMode) => {
    if (mode === inputMode) return;
    // Warn if there is existing data that will be lost
    const hasData = sessionId || manualReady || companies.length > 0 || Object.keys(manualData).length > 0;
    if (hasData) {
      const ok = window.confirm("切换输入方式将清空当前已填写的信息，确定继续吗？");
      if (!ok) return;
    }
    setInputMode(mode);
    setSessionId(null);
    setCompanies([]);
    setSelectedBd(null);
    setSelectedBds(new Set());
    setGenerateMode("single");
    setAttachmentNames([]);
    setTaskId(null);
    setBatchTaskIds([]);
    setReportContent(null);
    setManualData({});
    setManualReady(false);
  };

  // Step 1a: Upload Excel
  const handleExcelUpload = async (files: File[]) => {
    if (files.length === 0) return;
    setUploading(true);
    try {
      const res = await uploadExcel(files[0]);
      setSessionId(res.session_id);
      setCompanies(res.companies);
      setSelectedBd(null);
      setAttachmentNames([]);
      setTaskId(null);
      setReportContent(null);
    } catch (e: any) {
      alert("Excel上传失败: " + e.message);
    }
    setUploading(false);
  };

  // Step 1b: Manual input submit
  const handleManualSubmit = async () => {
    // Validate required fields
    for (const key of REQUIRED_KEYS) {
      if (!manualData[key]?.trim()) {
        const def = fieldDefs.find((f) => f.key === key);
        alert(`请填写必填字段: ${def?.label || key}`);
        return;
      }
    }
    setUploading(true);
    try {
      const res = await submitManualInput(manualData);
      setSessionId(res.session_id);
      setSelectedBd(res.bd_code);
      setManualReady(true);
      if (!regenerateId) setAttachmentNames([]);
      setTaskId(null);
      setReportContent(null);
    } catch (e: any) {
      alert("提交失败: " + e.message);
    }
    setUploading(false);
  };

  // Upload attachments
  const handleAttachments = async (files: File[]) => {
    if (!sessionId || !selectedBd || files.length === 0) return;
    setUploading(true);
    try {
      await uploadAttachments(sessionId, selectedBd, files);
      const names = files.map((f) => f.name);
      setAttachmentNames((prev) => [...prev, ...names]);
    } catch (e: any) {
      alert("附件上传失败: " + e.message);
    }
    setUploading(false);
  };

  // Generate
  const handleGenerate = async () => {
    if (!sessionId || !selectedBd) return;
    setGenerating(true);
    setReportContent(null);
    setTaskId(null);
    setBatchTaskIds([]);
    try {
      const res = await generateReport(sessionId, selectedBd, regenerateId ?? undefined);
      setTaskId(res.task_id);
    } catch (e: any) {
      alert("生成失败: " + e.message);
      setGenerating(false);
    }
  };

  // Batch generate
  const handleBatchGenerate = async () => {
    if (!sessionId || selectedBds.size === 0) return;
    setGenerating(true);
    setReportContent(null);
    setTaskId(null);
    setBatchTaskIds([]);
    try {
      const res = await batchGenerateReports(sessionId, Array.from(selectedBds));
      setBatchTaskIds(res.task_ids);
    } catch (e: any) {
      alert("批量生成失败: " + e.message);
      setGenerating(false);
    }
  };

  // Multi-select handlers
  const handleToggleBd = (bdCode: string) => {
    setSelectedBds((prev) => {
      const next = new Set(prev);
      if (next.has(bdCode)) next.delete(bdCode);
      else next.add(bdCode);
      return next;
    });
  };

  const handleSelectAll = () => {
    setSelectedBds(new Set(companies.map((c) => c.bd_code)));
  };

  const handleClearAll = () => {
    setSelectedBds(new Set());
  };

  const selectedCompany = companies.find((c) => c.bd_code === selectedBd);
  const displayName =
    selectedCompany?.project_name || manualData.project_name || "";

  // Has completed step 1 (either mode)
  const step1Done =
    inputMode === "excel" ? companies.length > 0 : manualReady;
  // Has completed step 2
  const step2Done =
    inputMode === "excel"
      ? generateMode === "single"
        ? !!selectedBd
        : selectedBds.size > 0
      : manualReady;

  // Sort field defs: required first, then by original order
  const sortedFields = [...fieldDefs].sort((a, b) => {
    if (a.required && !b.required) return -1;
    if (!a.required && b.required) return 1;
    return 0;
  });

  return (
    <div className="space-y-6">
      {/* Regeneration banner */}
      {regenerateId && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-3 text-sm text-orange-700 flex items-center gap-2">
          <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span>
            正在为 <strong>{manualData.company_name || manualData.bd_code}</strong> 重新生成报告，将覆盖原报告。
          </span>
        </div>
      )}

      {/* Input mode toggle */}
      <section className="bg-white rounded-lg shadow p-5">
        <h2 className="font-bold text-lg mb-3">1. 输入标的信息</h2>
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => switchMode("excel")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
              inputMode === "excel"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            上传Excel
          </button>
          <button
            onClick={() => switchMode("manual")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
              inputMode === "manual"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            手动输入
          </button>
        </div>

        {inputMode === "excel" && (
          <>
            {/* Template download button */}
            <div className="mb-3">
              <a
                href="/api/upload/template"
                download
                className="inline-flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-700 hover:underline"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                下载Excel模板
              </a>
            </div>

            <FileUpload
              label="上传卖家表 (.xlsx)"
              accept=".xlsx,.xls"
              onFiles={handleExcelUpload}
              disabled={uploading}
              hint="支持 .xlsx、.xls 格式"
            />
            {companies.length > 0 && (
              <p className="text-sm text-green-600 mt-2">
                已解析 {companies.length} 个项目
              </p>
            )}
          </>
        )}

        {inputMode === "manual" && !manualReady && (
          <div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[420px] overflow-y-auto pr-2">
              {sortedFields.map((f) => (
                <div key={f.key} className={f.key === "description" || f.key === "company_intro" || f.key === "referral_status" ? "md:col-span-2" : ""}>
                  <label className="block text-sm text-gray-600 mb-1">
                    {f.label}
                    {f.required && <span className="text-red-500 ml-1">*</span>}
                  </label>
                  {(f.key === "description" || f.key === "company_intro" || f.key === "referral_status") ? (
                    <textarea
                      value={manualData[f.key] || ""}
                      onChange={(e) =>
                        setManualData((prev) => ({ ...prev, [f.key]: e.target.value }))
                      }
                      rows={3}
                      className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                      placeholder={f.label}
                    />
                  ) : (
                    <input
                      type="text"
                      value={manualData[f.key] || ""}
                      onChange={(e) =>
                        setManualData((prev) => ({ ...prev, [f.key]: e.target.value }))
                      }
                      className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                      placeholder={f.label}
                    />
                  )}
                </div>
              ))}
            </div>
            <button
              onClick={handleManualSubmit}
              disabled={uploading}
              className="mt-4 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
            >
              {uploading ? "提交中..." : "确认提交"}
            </button>
          </div>
        )}

        {inputMode === "manual" && manualReady && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm text-green-700">
            已提交：{manualData.bd_code} - {manualData.project_name}（{manualData.company_name}）
            <button
              onClick={() => { setManualReady(false); setSessionId(null); setSelectedBd(null); }}
              className="ml-3 text-blue-600 underline text-xs"
            >
              修改内容
            </button>
          </div>
        )}
      </section>

      {/* Step 2: Select project (Excel mode only) */}
      {inputMode === "excel" && companies.length > 0 && (
        <section className="bg-white rounded-lg shadow p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold text-lg">2. 选择目标项目</h2>
            <div className="flex gap-2">
              <button
                onClick={() => setGenerateMode("single")}
                className={`px-3 py-1 rounded text-sm font-medium transition ${
                  generateMode === "single"
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                单个生成
              </button>
              <button
                onClick={() => setGenerateMode("batch")}
                className={`px-3 py-1 rounded text-sm font-medium transition ${
                  generateMode === "batch"
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                批量生成
              </button>
            </div>
          </div>
          {generateMode === "single" ? (
            <CompanySelector
              companies={companies}
              selected={selectedBd}
              onSelect={(bd) => {
                setSelectedBd(bd);
                setAttachmentNames([]);
                setTaskId(null);
                setBatchTaskIds([]);
                setReportContent(null);
              }}
            />
          ) : (
            <CompanySelectorMulti
              companies={companies}
              selected={selectedBds}
              onToggle={handleToggleBd}
              onSelectAll={handleSelectAll}
              onClearAll={handleClearAll}
            />
          )}
        </section>
      )}

      {/* Upload attachments */}
      {step2Done && (
        <section className="bg-white rounded-lg shadow p-5">
          <h2 className="font-bold text-lg mb-3">
            {inputMode === "excel" ? "3" : "2"}. 上传附件（可选）
            <span className="text-sm font-normal text-gray-400 ml-2">
              {displayName}
            </span>
          </h2>
          <FileUpload
            label="上传附件（PDF/Word/PPT/MD）"
            accept=".pdf,.md,.txt,.docx,.pptx"
            multiple
            onFiles={handleAttachments}
            disabled={uploading}
            hint="支持 PDF、Word、PPT、Markdown 格式"
          />
          {attachmentNames.length > 0 && (
            <div className="mt-3 space-y-1">
              {attachmentNames.map((name, i) => (
                <div key={i} className="flex items-center gap-2 text-sm text-gray-600">
                  <svg className="w-4 h-4 text-green-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="truncate">{name}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Generate */}
      {step2Done && (
        <section className="bg-white rounded-lg shadow p-5">
          <h2 className="font-bold text-lg mb-3">
            {inputMode === "excel" ? "4" : "3"}. 生成报告
          </h2>
          {generateMode === "single" ? (
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
            >
              {generating
                ? "生成中..."
                : regenerateId
                  ? `重新生成 ${displayName} 的尽调报告`
                  : `生成 ${displayName} 的尽调报告`}
            </button>
          ) : (
            <button
              onClick={handleBatchGenerate}
              disabled={generating || selectedBds.size === 0}
              className="px-6 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 font-medium"
            >
              {generating
                ? "批量生成中..."
                : `批量生成 ${selectedBds.size} 份报告`}
            </button>
          )}
        </section>
      )}

      {/* Progress */}
      {taskId && generateMode === "single" && (
        <section className="bg-white rounded-lg shadow p-5">
          <h2 className="font-bold text-lg mb-3">生成进度</h2>
          <PipelineProgress
            progress={sse.progress}
            logs={sse.logs}
            error={sse.error}
            done={sse.done}
          />
        </section>
      )}

      {/* Batch Progress */}
      {batchTaskIds.length > 0 && generateMode === "batch" && (
        <section className="bg-white rounded-lg shadow p-5">
          <h2 className="font-bold text-lg mb-3">批量生成进度</h2>
          <BatchProgress
            taskIds={batchTaskIds}
            companies={companies.filter((c) => selectedBds.has(c.bd_code))}
            onAllComplete={() => {
              setGenerating(false);
              alert("批量生成完成！");
            }}
          />
        </section>
      )}

      {/* Report */}
      {reportContent && sse.reportId && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold text-lg">生成的报告</h2>
            <ReportActions reportId={sse.reportId} content={reportContent} />
          </div>
          <ReportViewer content={reportContent} />
        </section>
      )}
    </div>
  );
}
