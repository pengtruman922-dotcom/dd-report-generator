import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelIntakeTask,
  executeIntake,
  getParseIntakeStatus,
  listIntakeTasks,
  startParseIntake,
} from "../api/client";
import type {
  IntakeConfirmationItem,
  IntakeExecuteResult,
  IntakeOperation,
  IntakeParseResult,
  IntakeTaskStatus,
} from "../types";
import { useSSE } from "../hooks/useSSE";
import PipelineProgress from "./PipelineProgress";

const IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]);
const DOC_EXTS = new Set([".pdf", ".md", ".txt", ".docx", ".pptx"]);
const MAX_PROJECT_CARDS = 5;
const MAX_PARSE_CONCURRENCY = 5;
const PARSE_TIMEOUT_MS = 10 * 60 * 1000;

type ConfirmationDraft = {
  id: string;
  enabled: boolean;
  executable: boolean;
  operation: IntakeOperation;
  confirmation: IntakeConfirmationItem | null;
};

type ProjectInputCard = {
  id: string;
  projectNameInfo: string;
  text: string;
  files: File[];
};

type ParseScopeKind = "main" | "card";

type ParseScope = {
  id: string;
  kind: ParseScopeKind;
  label: string;
  projectNameInfo: string;
  text: string;
  files: File[];
};

type ParseScopeState = {
  id: string;
  kind: ParseScopeKind;
  label: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  error: string | null;
  result: IntakeParseResult | null;
};

type ExecutionCard = IntakeExecuteResult & {
  placeholder?: boolean;
  displayName?: string;
};

function getExt(name: string) {
  return name.toLowerCase().slice(name.lastIndexOf("."));
}

function getConfidenceLabel(confidence?: "high" | "medium" | "low" | null) {
  if (confidence === "high") return "高置信";
  if (confidence === "medium") return "中置信";
  if (confidence === "low") return "低置信";
  return "待确认";
}

function getConfidenceClass(confidence?: "high" | "medium" | "low" | null) {
  if (confidence === "high") return "bg-green-100 text-green-700";
  if (confidence === "medium") return "bg-amber-100 text-amber-700";
  if (confidence === "low") return "bg-red-100 text-red-700";
  return "bg-gray-100 text-gray-600";
}

function cloneOperation(operation: IntakeOperation): IntakeOperation {
  return {
    ...operation,
    fields: operation.fields ? { ...operation.fields } : undefined,
    changed_fields: operation.changed_fields ? { ...operation.changed_fields } : undefined,
    source: [...operation.source],
    related_attachments: operation.related_attachments ? [...operation.related_attachments] : [],
    related_attachment_paths: operation.related_attachment_paths
      ? { ...operation.related_attachment_paths }
      : undefined,
    available_attachments: operation.available_attachments ? [...operation.available_attachments] : [],
    available_attachment_paths: operation.available_attachment_paths
      ? { ...operation.available_attachment_paths }
      : undefined,
  };
}

function cloneConfirmation(
  confirmation: IntakeConfirmationItem | null | undefined,
): IntakeConfirmationItem | null {
  if (!confirmation) return null;
  return {
    ...confirmation,
    related_attachments: confirmation.related_attachments
      ? [...confirmation.related_attachments]
      : [],
  };
}

function uniqueStrings(values: Array<string | undefined | null>) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = String(value || "").trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function normalizeAttachmentName(value?: string | null) {
  return String(value || "").trim();
}

function pickSelectedAttachments(
  availableAttachments: string[] | undefined,
  ...attachmentSets: Array<string[] | undefined>
) {
  const available = uniqueStrings((availableAttachments || []).map((name) => normalizeAttachmentName(name)));
  const selectedCandidates = uniqueStrings(
    attachmentSets.flatMap((items) => (items || []).map((name) => normalizeAttachmentName(name))),
  );
  if (available.length === 0) return selectedCandidates;
  const availableSet = new Set(available);
  return selectedCandidates.filter((name) => availableSet.has(name));
}

function buildSelectedAttachmentPaths(
  selectedAttachments: string[],
  ...pathMaps: Array<Record<string, string> | undefined>
) {
  const mergedPaths = Object.assign({}, ...pathMaps.filter(Boolean));
  const nextPaths = Object.fromEntries(
    selectedAttachments
      .map((name) => [name, mergedPaths[name]])
      .filter(([, path]) => Boolean(path)),
  ) as Record<string, string>;
  return Object.keys(nextPaths).length > 0 ? nextPaths : undefined;
}

function mergeStringMaps(
  first?: Record<string, string>,
  second?: Record<string, string>,
): Record<string, string> | undefined {
  const merged = { ...(first || {}), ...(second || {}) };
  return Object.keys(merged).length > 0 ? merged : undefined;
}

function mergeSummaryText(first?: string, second?: string) {
  return uniqueStrings([first, second]).join("\n\n");
}

function normalizeProjectKey(value?: string | null) {
  return (value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function getDraftTargetName(operation: IntakeOperation, confirmation: IntakeConfirmationItem | null) {
  if (confirmation?.matched_company_name) return confirmation.matched_company_name;
  if (confirmation?.project_name) return confirmation.project_name;
  return operation.fields?.project_name || operation.company_name;
}

function getOperationPriority(operation: IntakeOperation) {
  if (operation.type === "update" && operation.bd_code) return 4;
  if (operation.type === "update") return 3;
  if (operation.fields?.bd_code) return 2;
  return 1;
}

function mergeDraftPair(base: ConfirmationDraft, incoming: ConfirmationDraft): ConfirmationDraft {
  const basePriority = getOperationPriority(base.operation);
  const incomingPriority = getOperationPriority(incoming.operation);
  const primary = incomingPriority > basePriority ? incoming : base;
  const secondary = primary === base ? incoming : base;

  const mergedOperation = cloneOperation(primary.operation);
  const mergedConfirmation = cloneConfirmation(primary.confirmation || secondary.confirmation);
  const mergedTargetName = getDraftTargetName(primary.operation, primary.confirmation || secondary.confirmation);

  mergedOperation.source = uniqueStrings([
    ...primary.operation.source,
    ...secondary.operation.source,
  ]);
  mergedOperation.material_summary = mergeSummaryText(
    primary.operation.material_summary,
    secondary.operation.material_summary,
  );
  mergedOperation.related_attachments = uniqueStrings([
    ...(primary.operation.related_attachments || []),
    ...(secondary.operation.related_attachments || []),
  ]);
  mergedOperation.related_attachment_paths = mergeStringMaps(
    primary.operation.related_attachment_paths,
    secondary.operation.related_attachment_paths,
  );
  mergedOperation.available_attachments = uniqueStrings([
    ...(primary.operation.available_attachments || []),
    ...(secondary.operation.available_attachments || []),
  ]);
  mergedOperation.available_attachment_paths = mergeStringMaps(
    primary.operation.available_attachment_paths,
    secondary.operation.available_attachment_paths,
  );

  const selectedAttachments = pickSelectedAttachments(
    mergedOperation.available_attachments,
    mergedOperation.related_attachments,
    primary.confirmation?.related_attachments,
    secondary.confirmation?.related_attachments,
  );
  mergedOperation.related_attachments = selectedAttachments;
  mergedOperation.related_attachment_paths = buildSelectedAttachmentPaths(
    selectedAttachments,
    mergedOperation.available_attachment_paths,
    mergedOperation.related_attachment_paths,
    primary.operation.related_attachment_paths,
    secondary.operation.related_attachment_paths,
  );

  if (mergedOperation.type === "create") {
    mergedOperation.company_name = mergedTargetName;
    mergedOperation.fields = {
      ...(secondary.operation.fields || {}),
      ...(primary.operation.fields || {}),
      company_name: mergedTargetName,
      project_name: mergedTargetName,
    };
  } else {
    mergedOperation.company_name = mergedTargetName;
    mergedOperation.bd_code = primary.operation.bd_code || secondary.operation.bd_code;
    mergedOperation.changed_fields = {
      ...(secondary.operation.changed_fields || {}),
      ...(primary.operation.changed_fields || {}),
    };
  }

  if (mergedConfirmation) {
    mergedConfirmation.project_name = mergedConfirmation.project_name || mergedTargetName;
    mergedConfirmation.material_summary = mergeSummaryText(
      primary.confirmation?.material_summary || primary.operation.material_summary,
      secondary.confirmation?.material_summary || secondary.operation.material_summary,
    );
    mergedConfirmation.related_attachments = selectedAttachments;
    mergedConfirmation.needs_user_attention =
      Boolean(primary.confirmation?.needs_user_attention)
      || Boolean(secondary.confirmation?.needs_user_attention);
    mergedConfirmation.attention_reason = uniqueStrings([
      primary.confirmation?.attention_reason,
      secondary.confirmation?.attention_reason,
    ]).join("；");
  }

  const executable = mergedOperation.type === "create" || Boolean(mergedOperation.bd_code);
  return {
    id: primary.id,
    enabled: executable && (base.enabled || incoming.enabled),
    executable,
    operation: mergedOperation,
    confirmation: mergedConfirmation,
  };
}

function buildConfirmationDrafts(result: IntakeParseResult): ConfirmationDraft[] {
  const flatDrafts = result.operations.map((operation, index) => {
    const confirmation = result.confirmation_items?.[index] ?? null;
    const availableAttachments = operation.available_attachments ? [...operation.available_attachments] : [];
    const selectedAttachments = pickSelectedAttachments(
      availableAttachments,
      operation.related_attachments,
      confirmation?.related_attachments,
    );
    const selectedAttachmentPaths = buildSelectedAttachmentPaths(
      selectedAttachments,
      operation.available_attachment_paths,
      operation.related_attachment_paths,
    );
    const executable = operation.type === "create" || Boolean(operation.bd_code);
    return {
      id: `${operation.type}-${operation.bd_code || operation.company_name}-${index}`,
      enabled: executable,
      executable,
      operation: {
        ...cloneOperation(operation),
        available_attachments: availableAttachments,
        related_attachments: selectedAttachments,
        related_attachment_paths: selectedAttachmentPaths,
      },
      confirmation: confirmation
        ? {
            ...cloneConfirmation(confirmation),
            related_attachments: selectedAttachments,
          }
        : null,
    } as ConfirmationDraft;
  });

  const merged = new Map<string, ConfirmationDraft>();
  for (let index = 0; index < flatDrafts.length; index += 1) {
    const draft = flatDrafts[index];
    const keyBase = getDraftTargetName(draft.operation, draft.confirmation);
    const key = normalizeProjectKey(keyBase) || `${draft.operation.type}-${index}`;
    const existing = merged.get(key);
    merged.set(key, existing ? mergeDraftPair(existing, draft) : draft);
  }
  return Array.from(merged.values());
}

function buildScopedText(projectNameInfo: string, text: string) {
  const parts: string[] = [];
  if (projectNameInfo.trim()) {
    parts.push(`【项目名称信息】\n${projectNameInfo.trim()}`);
  }
  if (text.trim()) {
    parts.push(`【用户正文】\n${text.trim()}`);
  }
  return parts.join("\n\n").trim();
}

function buildFileSignature(files: File[]) {
  return files
    .map((file) => `${file.name}:${file.size}:${file.lastModified}`)
    .sort()
    .join("|");
}

function buildInputSignature(
  mainProjectNameInfo: string,
  text: string,
  files: File[],
  cards: ProjectInputCard[],
) {
  const cardSignature = cards
    .map((card) => [
      card.id,
      card.projectNameInfo.trim(),
      card.text.trim(),
      buildFileSignature(card.files),
    ].join("::"))
    .join("||");
  return [
    mainProjectNameInfo.trim(),
    text.trim(),
    buildFileSignature(files),
    cardSignature,
  ].join("__");
}

function extractUrls(text: string) {
  const urlRegex = /https?:\/\/[^\s\u3000\uff0c\uff01\uff1f\u3002\u300d\u300f\u301f"']+/g;
  return text.match(urlRegex) ?? [];
}

function hasScopeInput(projectNameInfo: string, text: string, files: File[]) {
  return Boolean(projectNameInfo.trim() || text.trim() || files.length > 0);
}

function buildParseScopes(
  mainProjectNameInfo: string,
  text: string,
  files: File[],
  cards: ProjectInputCard[],
): ParseScope[] {
  const scopes: ParseScope[] = [];
  if (hasScopeInput(mainProjectNameInfo, text, files)) {
    scopes.push({
      id: "main",
      kind: "main",
      label: "项目 1",
      projectNameInfo: mainProjectNameInfo,
      text,
      files,
    });
  }
  cards.forEach((card, index) => {
    if (!hasScopeInput(card.projectNameInfo, card.text, card.files)) return;
    scopes.push({
      id: card.id,
      kind: "card",
      label: `项目 ${index + 2}`,
      projectNameInfo: card.projectNameInfo,
      text: card.text,
      files: card.files,
    });
  });
  return scopes;
}

function buildAggregatedParseResult(states: ParseScopeState[]): IntakeParseResult | null {
  const completed = states.filter((state) => state.status === "completed" && state.result);
  if (completed.length === 0) return null;

  const allOperations: IntakeOperation[] = [];
  const allConfirmations: IntakeConfirmationItem[] = [];
  const allSources = new Set<string>();
  const completedLabels = completed.map((state) => state.label);
  const failedCount = states.filter((state) => state.status === "failed").length;

  completed.forEach((state) => {
    const result = state.result!;
    result.input_sources.forEach((source) => allSources.add(source));
    result.operations.forEach((operation, index) => {
      allOperations.push(cloneOperation(operation));
      allConfirmations.push(cloneConfirmation(result.confirmation_items?.[index]) as IntakeConfirmationItem);
    });
  });

  return {
    operations: allOperations,
    confirmation_items: allConfirmations,
    summary: `本次共提交 ${states.length} 个输入区，成功解析 ${completed.length} 个，失败 ${failedCount} 个；汇总后得到 ${allOperations.length} 个候选操作。`,
    mode: "manual",
    input_sources: Array.from(allSources),
    raw_content_summary: `成功输入区：${completedLabels.join("、")}`,
  };
}

function TaskCard({
  taskInfo,
  execResult,
  onCancel,
}: {
  taskInfo: IntakeTaskStatus | null;
  execResult: ExecutionCard;
  onCancel: (taskId: string) => void;
}) {
  const sse = useSSE(execResult.placeholder ? null : execResult.task_id);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [taskLogs, setTaskLogs] = useState<string[]>([]);

  const isCreate = execResult.type === "create";
  const isPlaceholder = Boolean(execResult.placeholder);
  const failedMessage = sse.error || taskInfo?.error_message || (taskInfo?.status === "failed" ? taskInfo.message : null) || null;
  const isFailed = Boolean(failedMessage) || taskInfo?.status === "failed" || taskInfo?.status === "cancelled";
  const isDone = !isFailed && (sse.done || taskInfo?.status === "completed");
  const isCancelling = cancelling || taskInfo?.status === "cancelling";
  const reportHref = sse.reportId || execResult.report_id || taskInfo?.report_id;

  useEffect(() => {
    const msg = taskInfo?.message?.trim();
    if (!msg) return;
    setTaskLogs((prev) => (prev[prev.length - 1] === msg ? prev : [...prev, msg]));
  }, [taskInfo?.message]);

  const progress = sse.progress || (taskInfo
    ? {
        step: taskInfo.step,
        total: taskInfo.total_steps,
        message: taskInfo.message || `Step${taskInfo.step}/${taskInfo.total_steps}`,
      }
    : null);

  const logs = sse.logs.length > 0 ? sse.logs : taskLogs;
  const statusLabel = isPlaceholder
    ? "正在创建任务..."
    : progress?.message || taskInfo?.message || "";

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
    <div className="rounded-lg border bg-white p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={`flex-shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${
              isCreate ? "bg-green-100 text-green-700" : "bg-blue-100 text-blue-700"
            }`}
          >
            {isCreate ? "新建" : "更新"}
          </span>
          <span className="text-sm font-medium">
            {execResult.bd_code ? `${execResult.bd_code} ` : ""}
            {execResult.displayName || ""}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {isCancelling ? <span className="text-xs text-orange-500">终止中...</span> : null}
          {isFailed && !isCancelling ? (
            <span className="text-xs font-medium text-red-600">失败</span>
          ) : null}
          {isDone && !isCancelling ? (
            <span className="text-xs font-medium text-green-600">完成</span>
          ) : null}
          {!isDone && !isFailed && !isCancelling ? (
            <span className="text-xs text-blue-500">处理中{statusLabel ? ` - ${statusLabel}` : ""}</span>
          ) : null}

          {!isDone && !isFailed && !isCancelling && !isPlaceholder ? (
            confirmCancel ? (
              <div className="flex items-center gap-1">
                <span className="text-xs text-gray-500">终止后本次操作会回滚，确认？</span>
                <button
                  onClick={handleCancel}
                  className="text-xs font-medium text-red-600 hover:underline"
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
                className="rounded border border-red-200 px-1.5 py-0.5 text-xs text-red-400 hover:text-red-600"
              >
                终止
              </button>
            )
          ) : null}
        </div>
      </div>

      {!isDone && !isCancelling ? (
        isPlaceholder ? (
          <div className="rounded-lg border border-dashed border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
            正在向后端创建执行任务，请稍候...
          </div>
        ) : (
          <PipelineProgress
            progress={progress}
            logs={logs}
            error={failedMessage}
            done={isDone}
            totalSteps={taskInfo?.total_steps ?? progress?.total}
            autoPushEnabled={execResult.auto_push_enabled}
          />
        )
      ) : null}

      {isDone && !isCancelling && !isPlaceholder && reportHref ? (
        <a
          href={`/report/${reportHref}`}
          className="text-sm text-blue-600 hover:underline"
        >
          查看报告 -
        </a>
      ) : null}
    </div>
  );
}

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="mx-4 w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start gap-3">
          <span className="text-2xl">!</span>
          <div>
            <h3 className="font-semibold text-gray-800">建议完整重新调研</h3>
            <p className="mt-1 text-sm text-gray-500">
              本次更新涉及核心字段：<strong>{changedFields.join("、")}</strong>，建议重新调研以获得更准确结论。
            </p>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={onLightUpdate}
            className="flex-1 rounded-lg border px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            仅更新字段和报告
          </button>
          <button
            onClick={onFullResearch}
            className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
          >
            完整重新调研
          </button>
        </div>
      </div>
    </div>
  );
}

export default function IntakeAgent() {
  const [mainProjectNameInfo, setMainProjectNameInfo] = useState("");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [projectCards, setProjectCards] = useState<ProjectInputCard[]>([]);
  const [parseScopes, setParseScopes] = useState<Record<string, ParseScopeState>>({});
  const [confirmationDrafts, setConfirmationDrafts] = useState<ConfirmationDraft[]>([]);
  const [executing, setExecuting] = useState(false);
  const [execResults, setExecResults] = useState<ExecutionCard[]>([]);
  const [taskStatuses, setTaskStatuses] = useState<Record<string, IntakeTaskStatus>>({});
  const [cancelledIds, setCancelledIds] = useState<Set<string>>(new Set());
  const [lastExecutedInputSignature, setLastExecutedInputSignature] = useState<string | null>(null);
  const [researchPrompt, setResearchPrompt] = useState<{
    op: IntakeOperation;
    inputSources: string[];
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const currentInputSignature = buildInputSignature(mainProjectNameInfo, text, files, projectCards);
  const parseLockedByExecutedInput =
    execResults.length > 0 && lastExecutedInputSignature === currentInputSignature;

  const parseScopeList = useMemo(() => Object.values(parseScopes), [parseScopes]);
  const hasRunningParses = parseScopeList.some(
    (scope) => scope.status === "queued" || scope.status === "running",
  );
  const allParsesFinished = parseScopeList.length > 0 && !hasRunningParses;
  const failedParseScopes = parseScopeList.filter((scope) => scope.status === "failed");
  const aggregatedParseResult = useMemo(() => buildAggregatedParseResult(parseScopeList), [parseScopeList]);

  useEffect(() => {
    if (!allParsesFinished) return;
    if (!aggregatedParseResult) {
      setConfirmationDrafts([]);
      return;
    }
    setConfirmationDrafts(buildConfirmationDrafts(aggregatedParseResult));
  }, [aggregatedParseResult, allParsesFinished]);

  const activeTaskIds = execResults
    .filter((result) => !result.placeholder)
    .map((result) => result.task_id)
    .filter((taskId) => !cancelledIds.has(taskId));

  useEffect(() => {
    if (activeTaskIds.length === 0) return;

    const poll = async () => {
      try {
        const { tasks } = await listIntakeTasks();
        const byId: Record<string, IntakeTaskStatus> = {};
        for (const task of tasks) byId[task.task_id] = task;
        setTaskStatuses(byId);
      } catch {
        // Keep polling silent to avoid interrupting the task wall.
      }
    };

    poll();
    const timer = setInterval(poll, 3000);
    return () => clearInterval(timer);
  }, [activeTaskIds.join(",")]);

  const buildCurrentScopes = useCallback(
    () => buildParseScopes(mainProjectNameInfo, text, files, projectCards),
    [files, mainProjectNameInfo, projectCards, text],
  );

  const runSingleParseScope = useCallback(async (scope: ParseScope) => {
    const wrappedText = buildScopedText(scope.projectNameInfo, scope.text);
    const urls = extractUrls(scope.text);
    setParseScopes((prev) => ({
      ...prev,
      [scope.id]: {
        id: scope.id,
        kind: scope.kind,
        label: scope.label,
        status: "queued",
        progress: 0,
        message: "解析任务已创建",
        error: null,
        result: null,
      },
    }));

    try {
      const { parse_job_id } = await startParseIntake(wrappedText, urls, scope.files, "manual");
      const startedAt = Date.now();

      while (Date.now() - startedAt < PARSE_TIMEOUT_MS) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const status = await getParseIntakeStatus(parse_job_id);
        setParseScopes((prev) => ({
          ...prev,
          [scope.id]: {
            id: scope.id,
            kind: scope.kind,
            label: scope.label,
            status: status.status === "failed" ? "failed" : status.status === "completed" ? "completed" : "running",
            progress: status.progress ?? 0,
            message: status.message || "解析中...",
            error: status.error,
            result: status.result,
          },
        }));

        if (status.status === "completed") return;
        if (status.status === "failed") {
          throw new Error(status.error || "解析失败");
        }
      }

      throw new Error("解析超时，请重试");
    } catch (error: any) {
      setParseScopes((prev) => ({
        ...prev,
        [scope.id]: {
          id: scope.id,
          kind: scope.kind,
          label: scope.label,
          status: "failed",
          progress: prev[scope.id]?.progress ?? 0,
          message: prev[scope.id]?.message || "解析失败",
          error: error.message || "解析失败",
          result: null,
        },
      }));
    }
  }, []);

  const runParseScopes = useCallback(async (scopes: ParseScope[]) => {
    for (let index = 0; index < scopes.length; index += MAX_PARSE_CONCURRENCY) {
      const batch = scopes.slice(index, index + MAX_PARSE_CONCURRENCY);
      await Promise.all(batch.map((scope) => runSingleParseScope(scope)));
    }
  }, [runSingleParseScope]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    const valid = selected.filter((file) => {
      const ext = getExt(file.name);
      return IMAGE_EXTS.has(ext) || DOC_EXTS.has(ext);
    });
    setFiles((prev) => [...prev, ...valid]);
    e.target.value = "";
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files).filter((file) => {
      const ext = getExt(file.name);
      return IMAGE_EXTS.has(ext) || DOC_EXTS.has(ext);
    });
    setFiles((prev) => [...prev, ...dropped]);
  };

  const handleCardDrop = (cardId: string, e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files).filter((file) => {
      const ext = getExt(file.name);
      return IMAGE_EXTS.has(ext) || DOC_EXTS.has(ext);
    });
    setProjectCards((prev) => prev.map((card) => (
      card.id === cardId ? { ...card, files: [...card.files, ...dropped] } : card
    )));
  };

  const handleCardFileSelect = (cardId: string, e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []).filter((file) => {
      const ext = getExt(file.name);
      return IMAGE_EXTS.has(ext) || DOC_EXTS.has(ext);
    });
    setProjectCards((prev) => prev.map((card) => (
      card.id === cardId ? { ...card, files: [...card.files, ...selected] } : card
    )));
    e.target.value = "";
  };

  const addProjectCard = () => {
    if (projectCards.length >= MAX_PROJECT_CARDS) return;
    setProjectCards((prev) => [
      ...prev,
      {
        id: `card-${Date.now()}-${prev.length}`,
        projectNameInfo: "",
        text: "",
        files: [],
      },
    ]);
  };

  const updateProjectCard = (
    cardId: string,
    field: "projectNameInfo" | "text",
    value: string,
  ) => {
    setProjectCards((prev) => prev.map((card) => (
      card.id === cardId ? { ...card, [field]: value } : card
    )));
  };

  const removeProjectCard = (cardId: string) => {
    setProjectCards((prev) => prev.filter((card) => card.id !== cardId));
    setParseScopes((prev) => {
      const next = { ...prev };
      delete next[cardId];
      return next;
    });
  };

  const removeProjectCardFile = (cardId: string, fileIndex: number) => {
    setProjectCards((prev) => prev.map((card) => (
      card.id === cardId
        ? { ...card, files: card.files.filter((_, index) => index !== fileIndex) }
        : card
    )));
  };

  const executeAll = useCallback(async (ops: IntakeOperation[], inputSources: string[]) => {
    setExecuting(true);
    setLastExecutedInputSignature(buildInputSignature(mainProjectNameInfo, text, files, projectCards));
    const placeholders: ExecutionCard[] = ops.map((op, index) => ({
      task_id: `local-${Date.now()}-${index}`,
      type: op.type === "update" ? "update" : "create",
      bd_code: op.bd_code,
      auto_push_enabled: true,
      placeholder: true,
      displayName: op.company_name,
    }));
    setExecResults(placeholders);
    const batchSize = 5;

    for (let index = 0; index < ops.length; index += batchSize) {
      const batch = ops.slice(index, index + batchSize);
      await Promise.all(
        batch.map(async (op, batchOffset) => {
          const placeholder = placeholders[index + batchOffset];
          try {
            const res = await executeIntake(op, inputSources, false);
            if (res.needs_research_prompt) {
              setResearchPrompt({ op, inputSources });
              setExecResults((prev) => prev.filter((item) => item.task_id !== placeholder.task_id));
              return;
            }
            setExecResults((prev) => prev.map((item) => (
              item.task_id === placeholder.task_id
                ? { ...res, displayName: op.company_name }
                : item
            )));
          } catch (e: any) {
            setExecResults((prev) => prev.filter((item) => item.task_id !== placeholder.task_id));
            alert(`执行失败 (${op.company_name}): ${e.message}`);
          }
        }),
      );
    }

    setExecuting(false);
  }, [files, mainProjectNameInfo, projectCards, text]);

  const handleParse = async () => {
    const scopes = buildCurrentScopes();
    if (scopes.length === 0) {
      alert("请提供至少一种输入：文字、图片、文档或项目名称信息");
      return;
    }

    setConfirmationDrafts([]);
    setExecResults([]);
    setCancelledIds(new Set());
    setParseScopes(Object.fromEntries(
      scopes.map((scope) => [
        scope.id,
        {
          id: scope.id,
          kind: scope.kind,
          label: scope.label,
          status: "queued",
          progress: 0,
          message: "解析任务已创建",
          error: null,
          result: null,
        } satisfies ParseScopeState,
      ]),
    ));

    await runParseScopes(scopes);
  };

  const retryParseScope = async (scopeId: string) => {
    const scope = buildCurrentScopes().find((item) => item.id === scopeId);
    if (!scope) return;
    await runSingleParseScope(scope);
  };

  const updateDraft = (draftId: string, updater: (draft: ConfirmationDraft) => ConfirmationDraft) => {
    setConfirmationDrafts((prev) => prev.map((draft) => (draft.id === draftId ? updater(draft) : draft)));
  };

  const handleToggleDraft = (draftId: string) => {
    updateDraft(draftId, (draft) => {
      if (!draft.executable) return draft;
      return { ...draft, enabled: !draft.enabled };
    });
  };

  const handleCreateNameChange = (draftId: string, value: string) => {
    updateDraft(draftId, (draft) => ({
      ...draft,
      operation: {
        ...draft.operation,
        company_name: value,
        fields: {
          ...(draft.operation.fields || {}),
          company_name: value,
          project_name: value,
        },
      },
      confirmation: draft.confirmation
        ? {
            ...draft.confirmation,
            project_name: value,
          }
        : draft.confirmation,
    }));
  };

  const handleSummaryChange = (draftId: string, value: string) => {
    updateDraft(draftId, (draft) => ({
      ...draft,
      operation: {
        ...draft.operation,
        material_summary: value,
      },
      confirmation: draft.confirmation
        ? {
            ...draft.confirmation,
            material_summary: value,
          }
        : draft.confirmation,
    }));
  };

  const handleAttachmentToggle = (draftId: string, filename: string) => {
    updateDraft(draftId, (draft) => {
      const current = draft.operation.related_attachments || [];
      const nextAttachments = current.includes(filename)
        ? current.filter((item) => item !== filename)
        : [...current, filename];
      const availablePaths = draft.operation.available_attachment_paths
        || draft.operation.related_attachment_paths
        || {};
      const nextPaths = Object.fromEntries(
        nextAttachments
          .map((name) => [name, availablePaths[name]])
          .filter(([, path]) => Boolean(path)),
      ) as Record<string, string>;

      return {
        ...draft,
        operation: {
          ...draft.operation,
          related_attachments: nextAttachments,
          related_attachment_paths: nextPaths,
        },
        confirmation: draft.confirmation
          ? {
              ...draft.confirmation,
              related_attachments: nextAttachments,
            }
          : draft.confirmation,
      };
    });
  };

  const handleCancel = (taskId: string) => {
    setCancelledIds((prev) => new Set([...prev, taskId]));
    setTaskStatuses((prev) => {
      const next = { ...prev };
      delete next[taskId];
      return next;
    });
  };

  const selectedDrafts = confirmationDrafts.filter((draft) => draft.enabled);
  const selectedOperations = selectedDrafts.map((draft) => draft.operation);
  const selectedCreateCount = selectedDrafts.filter((draft) => draft.operation.type === "create").length;
  const selectedUpdateCount = selectedDrafts.length - selectedCreateCount;

  return (
    <div className="space-y-4">
      {researchPrompt ? (
        <ResearchPromptModal
          changedFields={Object.keys(researchPrompt.op.changed_fields || {})}
          onLightUpdate={async () => {
            setResearchPrompt(null);
            setLastExecutedInputSignature(currentInputSignature);
            const res = await executeIntake(researchPrompt.op, researchPrompt.inputSources, false);
            setExecResults((prev) => [...prev, res]);
          }}
          onFullResearch={async () => {
            setResearchPrompt(null);
            setLastExecutedInputSignature(currentInputSignature);
            const res = await executeIntake(researchPrompt.op, researchPrompt.inputSources, true);
            setExecResults((prev) => [...prev, res]);
          }}
        />
      ) : null}

      <div className="rounded-lg bg-white p-5 shadow">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <button
            onClick={addProjectCard}
            disabled={projectCards.length >= MAX_PROJECT_CARDS}
            className="rounded-lg border px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            + 增加项目
          </button>
          <p className="text-sm text-gray-500">
            请确保提交的内容或附件中包含明确的标的名称或者公司名称，避免只写“矿山项目”这类极简名称，以免影响调研和报告质量。不同项目请分开填写，不要混传附件。
          </p>
        </div>

        <div className="space-y-3">
          <div className="rounded-lg border border-gray-200 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-medium text-gray-800">项目 1</div>
            </div>

            <div className="mb-3">
              <label className="mb-1 block text-sm text-gray-500">项目名称信息（选填）</label>
              <input
                value={mainProjectNameInfo}
                onChange={(e) => setMainProjectNameInfo(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                placeholder="例如：科德教育"
              />
            </div>

            <div className="mb-3">
              <label className="mb-1 block text-sm text-gray-500">文字内容</label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={4}
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                placeholder="粘贴聊天记录、邮件正文、备忘录内容..."
              />
            </div>

            <div>
              <label className="mb-1 block text-sm text-gray-500">上传附件</label>
              <div
                onDrop={handleDrop}
                onDragOver={(e) => e.preventDefault()}
                onClick={() => fileInputRef.current?.click()}
                className="cursor-pointer rounded-lg border-2 border-dashed border-gray-200 p-4 text-center transition hover:border-blue-300 hover:bg-blue-50"
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.md,.txt,.docx,.pptx,.jpg,.jpeg,.png,.gif,.webp"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <p className="text-sm text-gray-400">拖入或点击上传文件（图片 / PDF / Word / PPT）</p>
                {files.length > 0 ? (
                  <div className="mt-2 flex flex-wrap justify-center gap-2">
                    {files.map((file, index) => (
                      <span
                        key={`${file.name}-${index}`}
                        className="flex items-center gap-1 rounded bg-gray-100 px-2 py-1 text-xs text-gray-600"
                      >
                        {file.name}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setFiles((prev) => prev.filter((_, fileIndex) => fileIndex !== index));
                          }}
                          className="ml-1 text-red-400 hover:text-red-600"
                        >
                          x
                        </button>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {projectCards.map((card, index) => (
            <div key={card.id} className="rounded-lg border border-gray-200 p-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-sm font-medium text-gray-800">项目 {index + 2}</div>
                <button
                  onClick={() => removeProjectCard(card.id)}
                  className="text-sm text-red-500 hover:text-red-700"
                >
                  删除
                </button>
              </div>

              <div className="mb-3">
                <label className="mb-1 block text-sm text-gray-500">项目名称信息（选填）</label>
                <input
                  value={card.projectNameInfo}
                  onChange={(e) => updateProjectCard(card.id, "projectNameInfo", e.target.value)}
                  className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                  placeholder="例如：科德教育"
                />
              </div>

              <div className="mb-3">
                <label className="mb-1 block text-sm text-gray-500">文字内容</label>
                <textarea
                  value={card.text}
                  onChange={(e) => updateProjectCard(card.id, "text", e.target.value)}
                  rows={4}
                  className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                  placeholder="粘贴聊天记录、邮件正文、备忘录内容..."
                />
              </div>

              <div>
                <label className="mb-1 block text-sm text-gray-500">上传附件</label>
                <div
                  onDrop={(e) => handleCardDrop(card.id, e)}
                  onDragOver={(e) => e.preventDefault()}
                  className="rounded-lg border-2 border-dashed border-gray-200 p-4 text-center transition hover:border-blue-300 hover:bg-blue-50"
                >
                  <input
                    id={`card-file-${card.id}`}
                    type="file"
                    multiple
                    accept=".pdf,.md,.txt,.docx,.pptx,.jpg,.jpeg,.png,.gif,.webp"
                    className="hidden"
                    onChange={(e) => handleCardFileSelect(card.id, e)}
                  />
                  <label htmlFor={`card-file-${card.id}`} className="cursor-pointer text-sm text-gray-400">
                    拖入或点击上传文件（图片 / PDF / Word / PPT）
                  </label>
                  {card.files.length > 0 ? (
                    <div className="mt-2 flex flex-wrap justify-center gap-2">
                      {card.files.map((file, fileIndex) => (
                        <span
                          key={`${card.id}-${file.name}-${fileIndex}`}
                          className="flex items-center gap-1 rounded bg-gray-100 px-2 py-1 text-xs text-gray-600"
                        >
                          {file.name}
                          <button
                            onClick={() => removeProjectCardFile(card.id, fileIndex)}
                            className="ml-1 text-red-400 hover:text-red-600"
                          >
                            x
                          </button>
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={handleParse}
          disabled={hasRunningParses || parseLockedByExecutedInput}
          className="mt-4 w-full rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {hasRunningParses ? "解析中..." : "开始解析"}
        </button>
        {!hasRunningParses && parseLockedByExecutedInput ? (
          <div className="mt-2 text-xs text-gray-500">已执行当前输入内容；修改文字或附件后可重新解析。</div>
        ) : null}
      </div>

      {parseScopeList.length > 0 ? (
        <div className="rounded-lg bg-white p-5 shadow">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-gray-800">解析状态</h3>
              <p className="mt-1 text-sm text-gray-500">
                各输入区独立解析；失败项可单独重试，成功项会统一汇总到下方确认区。
              </p>
            </div>
            <span className="text-xs text-gray-400">
              成功 {parseScopeList.filter((scope) => scope.status === "completed").length} / {parseScopeList.length}
            </span>
          </div>

          <div className="space-y-3">
            {parseScopeList.map((scope) => {
              const tone = scope.status === "completed"
                ? "border-green-200 bg-green-50"
                : scope.status === "failed"
                  ? "border-red-200 bg-red-50"
                  : "border-blue-200 bg-blue-50";
              return (
                <div key={scope.id} className={`rounded-lg border px-4 py-3 ${tone}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-gray-800">{scope.label}</div>
                      <div className="mt-1 text-xs text-gray-500">
                        {scope.status === "queued" || scope.status === "running"
                          ? `${scope.message} (${scope.progress}%)`
                          : scope.status === "completed"
                            ? "解析完成"
                            : `解析失败：${scope.error || scope.message}`}
                      </div>
                    </div>
                    {scope.status === "failed" ? (
                      <button
                        onClick={() => retryParseScope(scope.id)}
                        disabled={hasRunningParses}
                        className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-white disabled:opacity-50"
                      >
                        重试该项
                      </button>
                    ) : (
                      <span className="text-xs text-gray-500">
                        {scope.status === "completed" ? "已完成" : "进行中"}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {aggregatedParseResult && allParsesFinished && !executing && execResults.length === 0 ? (
        <div className="rounded-lg bg-white p-5 shadow">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h3 className="font-semibold text-gray-800">解析结果确认</h3>
              <p className="mt-1 text-sm text-gray-500">{aggregatedParseResult.summary}</p>
              {aggregatedParseResult.raw_content_summary ? (
                <p className="mt-1 text-xs text-gray-400">{aggregatedParseResult.raw_content_summary}</p>
              ) : null}
              {failedParseScopes.length > 0 ? (
                <p className="mt-1 text-xs text-amber-600">
                  仍有 {failedParseScopes.length} 个输入区解析失败；成功结果已合并，可先确认，也可重试失败项。
                </p>
              ) : null}
            </div>
            <button
              onClick={() => {
                setParseScopes({});
                setConfirmationDrafts([]);
              }}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              清空结果
            </button>
          </div>

          {confirmationDrafts.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">
              本次未识别到可执行操作，请检查输入内容后重试。
            </div>
          ) : (
            <>
              <div className="mb-4 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                已选择 {selectedDrafts.length} 项，其中新建 {selectedCreateCount} 项、更新 {selectedUpdateCount} 项。
              </div>

              <div className="space-y-3">
                {confirmationDrafts.map((draft, index) => {
                  const confidence = draft.confirmation?.match_confidence ?? draft.operation.match_confidence;
                  const relatedAttachments = draft.operation.related_attachments ?? [];
                  const availableAttachments = draft.operation.available_attachments ?? [];
                  const isCreate = draft.operation.type === "create";
                  const targetName = isCreate
                    ? draft.confirmation?.project_name || draft.operation.company_name
                    : draft.confirmation?.matched_company_name || draft.operation.company_name;

                  return (
                    <div
                      key={draft.id}
                      className={`rounded-lg border p-4 ${
                        draft.enabled ? "border-gray-200 bg-white" : "border-gray-200 bg-gray-50 opacity-70"
                      }`}
                    >
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3">
                          <input
                            type="checkbox"
                            checked={draft.enabled}
                            disabled={!draft.executable}
                            onChange={() => handleToggleDraft(draft.id)}
                            className="mt-1 rounded"
                          />
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <span
                                className={`rounded px-2 py-0.5 text-xs font-semibold ${
                                  isCreate ? "bg-green-100 text-green-700" : "bg-blue-100 text-blue-700"
                                }`}
                              >
                                {isCreate ? "新建" : "更新"}
                              </span>
                              <span className="text-sm font-medium text-gray-900">
                                {targetName || `操作 ${index + 1}`}
                              </span>
                              <span
                                className={`rounded px-2 py-0.5 text-xs font-medium ${getConfidenceClass(confidence)}`}
                              >
                                {getConfidenceLabel(confidence)}
                              </span>
                              {!draft.executable ? (
                                <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                                  缺少可执行标的
                                </span>
                              ) : null}
                            </div>
                            <div className="mt-1 text-xs text-gray-500">
                              {isCreate
                                ? "将创建新的标的和报告"
                                : `将更新现有标的${draft.operation.bd_code ? `（${draft.operation.bd_code}）` : ""}`}
                            </div>
                          </div>
                        </div>
                        <button
                          onClick={() => handleToggleDraft(draft.id)}
                          disabled={!draft.executable}
                          className="text-sm text-gray-500 hover:text-gray-700 disabled:cursor-not-allowed disabled:text-gray-300"
                        >
                          {draft.enabled ? "跳过" : "恢复"}
                        </button>
                      </div>

                      {draft.confirmation?.needs_user_attention ? (
                        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                          {draft.confirmation.attention_reason || "该项需要人工确认后再执行。"}
                        </div>
                      ) : null}

                      {isCreate ? (
                        <div className="mb-3">
                          <label className="mb-1 block text-xs font-medium text-gray-500">新建标的名称</label>
                          <input
                            value={draft.confirmation?.project_name || draft.operation.company_name}
                            onChange={(e) => handleCreateNameChange(draft.id, e.target.value)}
                            className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                          />
                        </div>
                      ) : (
                        <div className="mb-3 grid gap-3 md:grid-cols-2">
                          <div>
                            <div className="mb-1 text-xs font-medium text-gray-500">匹配到的标的</div>
                            <div className="rounded-lg border bg-gray-50 px-3 py-2 text-sm text-gray-700">
                              {draft.confirmation?.matched_company_name || draft.operation.company_name}
                            </div>
                          </div>
                          <div>
                            <div className="mb-1 text-xs font-medium text-gray-500">匹配说明</div>
                            <div className="rounded-lg border bg-gray-50 px-3 py-2 text-sm text-gray-700">
                              {draft.confirmation?.match_reason || draft.operation.match_reason || "未返回说明"}
                            </div>
                          </div>
                        </div>
                      )}

                      <div className="mb-3">
                        <label className="mb-1 block text-xs font-medium text-gray-500">材料摘要</label>
                        <textarea
                          value={draft.operation.material_summary || ""}
                          onChange={(e) => handleSummaryChange(draft.id, e.target.value)}
                          rows={4}
                          className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                          placeholder="补充或修正材料摘要，执行时会传给当前 v4 写作链路。"
                        />
                      </div>

                      <div className="grid gap-3 md:grid-cols-2">
                        <div>
                          <div className="mb-1 text-xs font-medium text-gray-500">来源</div>
                          <div className="flex flex-wrap gap-2">
                            {draft.operation.source.map((source, sourceIndex) => (
                              <span
                                key={`${draft.id}-source-${sourceIndex}`}
                                className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600"
                              >
                                {source}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div>
                          <div className="mb-1 text-xs font-medium text-gray-500">关联附件</div>
                          {availableAttachments.length > 0 ? (
                            <div className="space-y-2">
                              <div className="flex flex-wrap gap-2">
                                {availableAttachments.map((filename, fileIndex) => {
                                  const checked = relatedAttachments.includes(filename);
                                  return (
                                    <label
                                      key={`${draft.id}-file-${fileIndex}`}
                                      className={`flex cursor-pointer items-center gap-2 rounded border px-2 py-1 text-xs ${
                                        checked
                                          ? "border-blue-200 bg-blue-50 text-blue-700"
                                          : "border-gray-200 bg-white text-gray-600"
                                      }`}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => handleAttachmentToggle(draft.id, filename)}
                                        className="rounded"
                                      />
                                      <span>{filename}</span>
                                    </label>
                                  );
                                })}
                              </div>
                              <div className="text-xs text-gray-400">
                                已选 {relatedAttachments.length} / {availableAttachments.length}
                              </div>
                            </div>
                          ) : (
                            <div className="text-sm text-gray-400">无</div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-5 flex flex-col gap-3 md:flex-row">
                <button
                  onClick={() => {
                    if (!aggregatedParseResult || selectedOperations.length === 0) return;
                    executeAll(selectedOperations, aggregatedParseResult.input_sources);
                  }}
                  disabled={selectedOperations.length === 0 || executing}
                  className="flex-1 rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  确认并执行 ({selectedOperations.length})
                </button>
                <button
                  onClick={handleParse}
                  disabled={hasRunningParses || executing}
                  className="rounded-lg border px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  重新解析
                </button>
              </div>
            </>
          )}
        </div>
      ) : null}

      {execResults.length > 0 ? (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-800">
            执行任务 ({execResults.filter((result) => !cancelledIds.has(result.task_id)).length})
          </h3>
          {execResults.map((result) => {
            if (cancelledIds.has(result.task_id)) return null;
            return (
              <TaskCard
                key={result.task_id}
                taskInfo={taskStatuses[result.task_id] ?? null}
                execResult={result}
                onCancel={handleCancel}
              />
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
