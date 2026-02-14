import type { ProgressEvent } from "../types";

interface Props {
  progress: ProgressEvent | null;
  logs: string[];
  error: string | null;
  done: boolean;
}

const STEP_LABELS = ["信息提取", "联网研究", "报告生成", "字段回填", "索引生成", "知识库推送"];

export default function PipelineProgress({ progress, logs, error, done }: Props) {
  const currentStep = progress?.step ?? 0;

  return (
    <div className="space-y-4">
      {/* Step indicator */}
      <div className="flex items-center gap-2">
        {STEP_LABELS.map((label, i) => {
          const step = i + 1;
          const isActive = step === currentStep;
          const isComplete = step < currentStep || done;
          return (
            <div key={step} className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold
                  ${isComplete ? "bg-green-500 text-white" : isActive ? "bg-blue-500 text-white animate-pulse" : "bg-gray-200 text-gray-500"}`}
              >
                {isComplete ? "✓" : step}
              </div>
              <span className={`text-sm ${isActive ? "text-blue-700 font-medium" : "text-gray-500"}`}>
                {label}
              </span>
              {i < STEP_LABELS.length - 1 && <div className="w-8 h-0.5 bg-gray-200" />}
            </div>
          );
        })}
      </div>

      {/* Log output */}
      <div className="bg-gray-900 text-green-400 rounded-lg p-4 text-xs font-mono max-h-48 overflow-y-auto">
        {logs.map((log, i) => (
          <div key={i}>{log}</div>
        ))}
        {!done && !error && <span className="animate-pulse">▌</span>}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
