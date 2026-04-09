import { useState, useRef, useEffect, useCallback } from "react";
import { parseIntake, executeIntake, cancelIntakeTask, listIntakeTasks } from "../api/client";
import type { IntakeOperation, IntakeParseResult, IntakeExecuteResult, IntakeTaskStatus } from "../types";
import { useSSE } from "../hooks/useSSE";
import PipelineProgress from "./PipelineProgress";

const IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]);
const DOC_EXTS = new Set([".pdf", ".md", ".txt", ".docx", ".pptx"]);

function getExt(name: string) {
  return name.toLowerCase().slice(name.lastIndexOf("."));
}

// ── Single task card ──────────────────────────────────────────────────────────
function TaskCard({
  taskInfo,
  execResult,
  onCancel,
}: {
  taskInfo: IntakeTaskStatus | null;
  execResult: IntakeExecuteResult;
  onCancel: (taskId: string) => void;
}) {
  const sse = useSSE(execResult.task_id);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const isCreate = execResult.type === "create";
  const isDone = sse.done || (taskInfo?.status === "completed");
  const isCancelling = cancelling || taskInfo?.status === "cancelling";

  const stepLabel = sse.progress
    ? `Step${sse.progress.step}/${sse.progress.total}`
    : taskInfo
    ? `Step${taskInfo.step}/${taskInfo.total_steps}`
    : "";

  const handleCancel = async () => {
    setCancelling(true);
    setConfirmCancel(false);
    try {
      await cancelIntakeTask(execResult.task_id);
      onCancel(execResult.task_id);
    } catch (e: any) {
      alert("终止失败: " + e.message);
      setCancelling(false);
    }
  };

  return (
    <div className="border rounded-lg p-4 bg-white">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 rounded text-xs font-semibold flex-shrink-0 ${
              isCreate ? "bg-green-100 text-green-700" : "bg-blue-100 text-blue-700"
            }`}
          >
            {isCreate ? "新建" : "更新"}
          </span>
          <span className="font-medium text-sm">{execResult.bd_code ? `${execResult.bd_code} ` : ""}</span>
        </div>

        {/* Status */}
        <div className="flex items-center gap-2">
          {isCancelling && <span className="text-xs text-orange-500">终止中...</span>}
          {isDone && !isCancelling && (
            <span className="text-xs text-green-600 font-medium">✓ 完成</span>
          )}
          {!isDone && !isCancelling && (
            <span className="text-xs text-blue-500">
              ⟳ {stepLabel || "处理中"}
            </span>
          )}

          {/* Cancel button */}
          {!isDone && !isCancelling && (
            <>
              {confirmCancel ? (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-gray-500">终止任务将丢失本次操作数据，确认？</span>
                  <button
                    onClick={handleCancel}
                    className="text-xs text-red-600 font-medium hover:underline"
                  >
                    确认终止
                  </button>
                  <button
                    onClick={() => setConfirmCancel(false)}
                    className="text-xs text-gray-400 hover:text-gray-600"
                  >
                    取消
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmCancel(true)}
                  className="text-xs text-red-400 hover:text-red-600 border border-red-200 rounded px-1.5 py-0.5"
                >
                  终止
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {!isDone && !isCancelling && (
        <PipelineProgress
          progress={sse.progress}
          logs={sse.logs}
          error={sse.error}
          done={sse.done}
        />
      )}

      {/* Done: link to report */}
      {isDone && !isCancelling && (sse.reportId || execResult.report_id) && (
        <a
          href={`/report/${sse.reportId || execResult.report_id}`}
          className="text-blue-600 hover:underline text-sm"
        >
          查看报告 →
        </a>
      )}
    </div>
  );
}

// ── Research prompt modal ─────────────────────────────────────────────────────
function ResearchPromptModal({
  onLightUpdate,
  onFullResearch,
  changedFields,
}: {
  onLightUpdate: () => void;
  onFullResearch: () => void;
  changedFields: string[];
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl p-6 max-w-md w-full mx-4">
        <div className="flex items-start gap-3 mb-4">
          <span className="text-2xl">⚠️</span>
          <div>
            <h3 className="font-semibold text-gray-800">建议完整重新调研</h3>
            <p className="text-sm text-gray-500 mt-1">
              本次更新涉及核心字段：<strong>{changedFields.join("、")}</strong>，
              建议重新调研以获得更准确结论。
            </p>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={onLightUpdate}
            className="flex-1 px-4 py-2 border rounded-lg text-sm text-gray-700 hover:bg-gray-50"
          >
            仅更新字段和报告
          </button>
          <button
            onClick={onFullResearch}
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"
          >
            完整重新调研（约10分钟）
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function IntakeAgent() {
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [parsing, setParsing] = useState(false);
  const [parseResult, setParseResult] = useState<IntakeParseResult | null>(null);
  const [operations, setOperations] = useState<IntakeOperation[]>([]);
  const [executing, setExecuting] = useState(false);
  const [execResults, setExecResults] = useState<IntakeExecuteResult[]>([]);
  const [taskStatuses, setTaskStatuses] = useState<Record<string, IntakeTaskStatus>>({});
  const [cancelledIds, setCancelledIds] = useState<Set<string>>(new Set());
  const [researchPrompt, setResearchPrompt] = useState<{
    op: IntakeOperation;
    inputSources: string[];
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Poll task statuses while tasks are running
  const activeTaskIds = execResults
    .map((r) => r.task_id)
    .filter((id) => !cancelledIds.has(id));

  useEffect(() => {
    if (activeTaskIds.length === 0) return;
    const poll = async () => {
      try {
        const { tasks } = await listIntakeTasks();
        const byId: Record<string, IntakeTaskStatus> = {};
        for (const t of tasks) byId[t.task_id] = t;
        setTaskStatuses(byId);
      } catch {}
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => clearInterval(timer);
  }, [activeTaskIds.join(",")]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    const valid = selected.filter((f) => {
      const ext = getExt(f.name);
      return IMAGE_EXTS.has(ext) || DOC_EXTS.has(ext);
    });
    setFiles((prev) => [...prev, ...valid]);
    e.target.value = "";
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files).filter((f) => {
      const ext = getExt(f.name);
      return IMAGE_EXTS.has(ext) || DOC_EXTS.has(ext);
    });
    setFiles((prev) => [...prev, ...dropped]);
  };

  const executeAll = useCallback(async (ops: IntakeOperation[], inputSources: string[]) => {
    setExecuting(true);
    const results: IntakeExecuteResult[] = [];

    // Execute up to 5 in parallel (backend handles semaphore too, but UI can batch)
    const BATCH = 5;
    for (let i = 0; i < ops.length; i += BATCH) {
      const batch = ops.slice(i, i + BATCH);
      const batchResults = await Promise.all(
        batch.map(async (op) => {
          try {
            const res = await executeIntake(op, inputSources, false);
            if (res.needs_research_prompt) {
              // Show modal for first op that needs it; others proceed
              setResearchPrompt({ op, inputSources });
              setExecuting(false);
              return res;
            }
            return res;
          } catch (e: any) {
            alert(`执行失败 (${op.company_name}): ${e.message}`);
            return null;
          }
        })
      );
      results.push(...batchResults.filter(Boolean) as IntakeExecuteResult[]);
      setExecResults([...results]);
    }
    setExecuting(false);
  }, []);

  const handleParse = async () => {
    if (!text.trim() && files.length === 0) {
      alert("请提供至少一种输入：文字、图片或文档");
      return;
    }
    const urlRegex = /https?:\/\/[^\s\u3000\uff0c\uff01\uff1f\u3002\u300d\u300f\u301f"']+/g;
    const extractedUrls = text.match(urlRegex) ?? [];
    setParsing(true);
    setParseResult(null);
    setOperations([]);
    setExecResults([]);
    setCancelledIds(new Set());
    try {
      const result = await parseIntake(text, extractedUrls, files, mode);
      setParseResult(result);
      setOperations(result.operations);
      if (mode === "auto" && result.operations.length > 0) {
        await executeAll(result.operations, result.input_sources);
      }
    } catch (e: any) {
      alert("解析失败: " + e.message);
    }
    setParsing(false);
  };

  const handleConfirmAll = () => {
    if (parseResult) {
      executeAll(operations, parseResult.input_sources);
    }
  };

  const handleCancel = (taskId: string) => {
    setCancelledIds((prev) => new Set([...prev, taskId]));
    setTaskStatuses((prev) => {
      const next = { ...prev };
      delete next[taskId];
      return next;
    });
  };

  return (
    <div className="space-y-4">
      {/* Research prompt modal */}
      {researchPrompt && (
        <ResearchPromptModal
          changedFields={Object.keys(researchPrompt.op.changed_fields || {})}
          onLightUpdate={async () => {
            setResearchPrompt(null);
            const res = await executeIntake(researchPrompt.op, researchPrompt.inputSources, false);
            setExecResults((prev) => [...prev, res]);
          }}
          onFullResearch={async () => {
            setResearchPrompt(null);
            const res = await executeIntake(researchPrompt.op, researchPrompt.inputSources, true);
            setExecResults((prev) => [...prev, res]);
          }}
        />
      )}

      {/* Input area */}
      <div className="bg-white rounded-lg shadow p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-bold text-lg">智能录入</h2>
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={mode === "manual"}
              onChange={(e) => setMode(e.target.checked ? "manual" : "auto")}
              className="rounded"
            />
            手动确认模式
          </label>
        </div>

        <div className="mb-3">
          <label className="block text-sm text-gray-500 mb-1">文字内容（聊天记录/邮件/备忘录，链接粘贴在这里即可自动识别）</label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            placeholder="粘贴聊天记录、邮件正文、备忘录内容..."
          />
        </div>

        <div
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => fileInputRef.current?.click()}
          className="border-2 border-dashed border-gray-200 rounded-lg p-4 text-center cursor-pointer hover:border-blue-300 hover:bg-blue-50 transition mb-4"
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.md,.txt,.docx,.pptx,.jpg,.jpeg,.png,.gif,.webp"
            className="hidden"
            onChange={handleFileSelect}
          />
          <p className="text-sm text-gray-400">
            拖入或点击上传文件（图片截图 / PDF / Word / PPT）
          </p>
          {files.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2 justify-center">
              {files.map((f, i) => (
                <span key={i} className="flex items-center gap-1 bg-gray-100 px-2 py-1 rounded text-xs text-gray-600">
                  {f.name}
                  <button
                    onClick={(e) => { e.stopPropagation(); setFiles((prev) => prev.filter((_, j) => j !== i)); }}
                    className="text-red-400 hover:text-red-600 ml-1"
                  >×</button>
                </span>
              ))}
            </div>
          )}
        </div>

        <button
          onClick={handleParse}
          disabled={parsing}
          className="w-full py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium text-sm"
        >
          {parsing ? "解析中..." : "开始解析"}
        </button>
      </div>

      {/* Manual mode: preview + confirm */}
      {mode === "manual" && parseResult && operations.length > 0 && !executing && execResults.length === 0 && (
        <div className="bg-white rounded-lg shadow p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-800">
              解析完成，识别到 {operations.length} 个操作
            </h3>
            <p className="text-xs text-gray-400">{parseResult.summary}</p>
          </div>
          <div className="space-y-2 mb-4">
            {operations.map((op, i) => (
              <div key={i} className="border rounded-lg p-3 bg-gray-50 text-sm">
                <span className={`mr-2 px-1.5 py-0.5 rounded text-xs font-semibold ${op.type === "create" ? "bg-green-100 text-green-700" : "bg-blue-100 text-blue-700"}`}>
                  {op.type === "create" ? "新建" : "更新"}
                </span>
                {op.company_name}
                {op.bd_code && <span className="ml-2 text-gray-400 text-xs">{op.bd_code}</span>}
              </div>
            ))}
          </div>
          <button
            onClick={handleConfirmAll}
            className="w-full py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium text-sm"
          >
            全部确认 → 执行
          </button>
        </div>
      )}

      {/* Auto mode summary */}
      {mode === "auto" && parseResult && !parsing && execResults.length === 0 && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700">
          {parseResult.summary}
        </div>
      )}

      {/* Task cards */}
      {execResults.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-800">
            执行中 ({execResults.filter(r => !cancelledIds.has(r.task_id)).length} 个任务)
          </h3>
          {execResults.map((res) => {
            if (cancelledIds.has(res.task_id)) return null;
            return (
              <TaskCard
                key={res.task_id}
                taskInfo={taskStatuses[res.task_id] ?? null}
                execResult={res}
                onCancel={handleCancel}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
