import { useState, useEffect } from "react";
import { getIntakeLogs } from "../api/client";
import type { IntakeLog } from "../types";

const LOG_TYPE_LABELS: Record<string, string> = {
  create: "新建标的",
  light_update: "轻量更新",
  full_regenerate: "完整重调研",
};

const LOG_TYPE_COLORS: Record<string, string> = {
  create: "bg-green-100 text-green-700",
  light_update: "bg-blue-100 text-blue-700",
  full_regenerate: "bg-orange-100 text-orange-700",
};

function FieldChangeRow({ fieldKey, change }: { fieldKey: string; change: any }) {
  if (typeof change === "object" && change !== null && "old" in change) {
    return (
      <div className="flex gap-2 text-xs py-0.5">
        <span className="text-gray-400 w-32 flex-shrink-0">{fieldKey}</span>
        <span className="text-gray-500 line-through">{change.old ?? "（空）"}</span>
        <span className="text-gray-400 mx-1">→</span>
        <span className="text-gray-800 font-medium">{change.new}</span>
      </div>
    );
  }
  return (
    <div className="flex gap-2 text-xs py-0.5">
      <span className="text-gray-400 w-32 flex-shrink-0">{fieldKey}</span>
      <span className="text-gray-800">{String(change)}</span>
    </div>
  );
}

function LogCard({ log }: { log: IntakeLog }) {
  const [expanded, setExpanded] = useState(false);
  const date = new Date(log.created_at).toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });

  const changedFieldCount = Object.keys(log.changed_fields || {}).length;

  return (
    <div className="border rounded-lg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`px-2 py-0.5 rounded text-xs font-semibold ${LOG_TYPE_COLORS[log.log_type] || "bg-gray-100 text-gray-600"}`}>
            {LOG_TYPE_LABELS[log.log_type] || log.log_type}
          </span>
          <span className="text-sm text-gray-600">{date}</span>
          {log.operator && (
            <span className="text-xs text-gray-400">操作人: {log.operator}</span>
          )}
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-xs text-gray-400 hover:text-blue-600 underline flex-shrink-0"
        >
          {expanded ? "收起" : "展开"}
        </button>
      </div>

      {/* Trigger reason */}
      {log.trigger_reason && (
        <p className="text-xs text-gray-500 mt-1.5">触发原因：{log.trigger_reason}</p>
      )}

      {/* Input sources */}
      {log.input_sources?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {log.input_sources.map((s, i) => (
            <span key={i} className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
              {s}
            </span>
          ))}
        </div>
      )}

      {/* Changed fields (compact) */}
      {!expanded && changedFieldCount > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5">
          {Object.entries(log.changed_fields).slice(0, 3).map(([k, v]) => (
            <span key={k} className="text-xs text-gray-500">
              {k}:&nbsp;
              {typeof v === "object" && v
                ? <span><s className="text-gray-400">{(v as any).old ?? "空"}</s>&nbsp;→&nbsp;<span className="text-gray-700">{(v as any).new}</span></span>
                : String(v)
              }
            </span>
          ))}
          {changedFieldCount > 3 && (
            <span className="text-xs text-gray-400">+{changedFieldCount - 3} 个字段</span>
          )}
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <div className="mt-3 space-y-4 border-t pt-3">
          {/* All changed fields */}
          {changedFieldCount > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">字段变化</p>
              <div className="space-y-0.5">
                {Object.entries(log.changed_fields).map(([k, v]) => (
                  <FieldChangeRow key={k} fieldKey={k} change={v} />
                ))}
              </div>
            </div>
          )}

          {/* Steps executed */}
          {log.steps_executed?.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">执行操作</p>
              <div className="flex flex-wrap gap-1.5">
                {log.steps_executed.map((s) => (
                  <span key={s} className="flex items-center gap-1 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded">
                    ✓ {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Steps skipped */}
          {log.steps_skipped?.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">跳过操作</p>
              <div className="space-y-0.5">
                {log.steps_skipped.map((s, i) => (
                  <p key={i} className="text-xs text-gray-400">
                    {s.step} — {s.reason}
                    {s.step === "Step2" && log.research_data_age_days != null && (
                      <span className={`ml-1 ${log.research_data_age_days > 90 ? "text-amber-500" : ""}`}>
                        （{log.research_data_age_days} 天前）
                      </span>
                    )}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function IntakeLogs({ reportId }: { reportId: string }) {
  const [logs, setLogs] = useState<IntakeLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!reportId) return;
    getIntakeLogs(reportId)
      .then((data) => {
        setLogs(data.logs);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [reportId]);

  if (loading) {
    return <div className="py-8 text-center text-gray-400 text-sm">加载中...</div>;
  }

  if (error) {
    return <div className="py-8 text-center text-red-500 text-sm">加载失败: {error}</div>;
  }

  if (logs.length === 0) {
    return (
      <div className="py-12 text-center text-gray-400">
        <p className="text-sm">暂无更新记录</p>
        <p className="text-xs mt-1">通过「智能录入」更新标的后，操作记录将显示在这里</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-400">共 {logs.length} 条记录，最新在前</p>
      {logs.map((log) => (
        <LogCard key={log.id} log={log} />
      ))}
    </div>
  );
}
