import { useMemo } from "react";
import type { ProgressEvent } from "../types";

interface Props {
  progress: ProgressEvent | null;
  logs: string[];
  error: string | null;
  done: boolean;
  totalSteps?: number;
  autoPushEnabled?: boolean;
}

type StageStatus = "pending" | "active" | "completed" | "skipped";
type StageKey = "planning" | "research" | "writing" | "rating" | "push";

interface StageDefinition {
  key: StageKey;
  label: string;
}

const BASE_STAGES: StageDefinition[] = [
  { key: "planning", label: "链路规划" },
  { key: "research", label: "公开事实" },
  { key: "writing", label: "动态/信息写作" },
  { key: "rating", label: "内部评级" },
];

const PUSH_STAGE: StageDefinition = { key: "push", label: "推送知识库" };

function normalizeMessage(message: string | undefined | null): string {
  return (message || "").trim();
}

function includesAny(message: string, patterns: string[]): boolean {
  return patterns.some((pattern) => message.includes(pattern));
}

function classifyStageKey(message: string): StageKey | null {
  const text = normalizeMessage(message);
  if (!text) return null;

  if (includesAny(text, ["FastGPT", "知识库", "推送"])) return "push";
  if (includesAny(text, ["评级", "RatingAgent"])) return "rating";
  if (
    includesAny(text, [
      "Tracking Processor",
      "Info Chunk",
      "tracking_chunk",
      "info_chunk",
      "并行写入",
      "write_chunk",
      "保存数据",
      "数据已保存",
      "Step 3/4: 保存数据",
    ]) ||
    (text.includes("chunk") && includesAny(text, ["写入", "完成"]))
  ) {
    return "writing";
  }
  if (
    includesAny(text, [
      "正在调研",
      "web_search:",
      "fetch_webpage:",
      "cninfo_search:",
      "akshare_query:",
      "run_researcher",
      "Research 完成",
    ])
  ) {
    return "research";
  }
  if (includesAny(text, ["WriterAgent", "规划", "事实链路"])) return "planning";
  return null;
}

function buildStages(totalSteps?: number, autoPushEnabled?: boolean): StageDefinition[] {
  if (typeof autoPushEnabled === "boolean") {
    return autoPushEnabled ? [...BASE_STAGES, PUSH_STAGE] : BASE_STAGES;
  }
  return totalSteps && totalSteps >= 5 ? [...BASE_STAGES, PUSH_STAGE] : BASE_STAGES;
}

function deriveStageState(
  stages: StageDefinition[],
  logs: string[],
  currentMessage: string,
  done: boolean,
) {
  const seen = new Set<StageKey>();
  let activeKey: StageKey | null = null;
  let pushSkipped = false;

  for (const raw of [...logs, currentMessage]) {
    const message = normalizeMessage(raw);
    if (!message) continue;

    if (message.includes("未检测到报告内容变化") || message.includes("当前报告没有可推送的 chunks")) {
      pushSkipped = true;
    }

    const key = classifyStageKey(message);
    if (!key) continue;
    seen.add(key);
    activeKey = key;
  }

  const defaultActive = activeKey ?? "planning";
  const currentIndex = stages.findIndex((stage) => stage.key === defaultActive);
  const lastCompletedIndex = done ? stages.length - 1 : Math.max(currentIndex - 1, -1);

  const statuses = new Map<StageKey, StageStatus>();
  stages.forEach((stage, index) => {
    if (stage.key === "push" && pushSkipped) {
      statuses.set(stage.key, "skipped");
      return;
    }
    if (done) {
      statuses.set(stage.key, pushSkipped && stage.key === "push" ? "skipped" : "completed");
      return;
    }
    if (index < lastCompletedIndex || seen.has(stage.key) && index < currentIndex) {
      statuses.set(stage.key, "completed");
      return;
    }
    if (index === currentIndex) {
      statuses.set(stage.key, "active");
      return;
    }
    statuses.set(stage.key, "pending");
  });

  return { statuses, activeKey: defaultActive };
}

function getStageTone(status: StageStatus) {
  if (status === "completed") {
    return {
      dot: "bg-green-500 text-white",
      text: "text-green-700",
      marker: "✓",
    };
  }
  if (status === "active") {
    return {
      dot: "bg-blue-500 text-white animate-pulse",
      text: "text-blue-700 font-medium",
      marker: null,
    };
  }
  if (status === "skipped") {
    return {
      dot: "bg-amber-100 text-amber-700 border border-amber-300",
      text: "text-amber-700",
      marker: "跳",
    };
  }
  return {
    dot: "bg-gray-200 text-gray-500",
    text: "text-gray-500",
    marker: null,
  };
}

export default function PipelineProgress({
  progress,
  logs,
  error,
  done,
  totalSteps,
  autoPushEnabled,
}: Props) {
  const stages = useMemo(
    () => buildStages(totalSteps ?? progress?.total, autoPushEnabled),
    [autoPushEnabled, progress?.total, totalSteps],
  );
  const currentMessage = normalizeMessage(progress?.message);
  const { statuses } = useMemo(
    () => deriveStageState(stages, logs, currentMessage, done),
    [currentMessage, done, logs, stages],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {stages.map((stage, index) => {
          const status = statuses.get(stage.key) || "pending";
          const tone = getStageTone(status);
          return (
            <div key={stage.key} className="flex items-center gap-2">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${tone.dot}`}
              >
                {tone.marker ?? index + 1}
              </div>
              <span className={`text-sm ${tone.text}`}>{stage.label}</span>
              {index < stages.length - 1 ? <div className="h-0.5 w-8 bg-gray-200" /> : null}
            </div>
          );
        })}
      </div>

      <div className="max-h-48 overflow-y-auto rounded-lg bg-gray-900 p-4 font-mono text-xs text-green-400">
        {logs.map((log, index) => (
          <div key={index}>{log}</div>
        ))}
        {!done && !error ? <span className="animate-pulse">▌</span> : null}
      </div>

      {error ? (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
    </div>
  );
}
