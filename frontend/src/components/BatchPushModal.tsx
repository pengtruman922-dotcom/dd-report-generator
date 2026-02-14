import { useState, useCallback } from "react";
import { pushToFastGPT } from "../api/client";
import type { ReportMeta } from "../types";

type ItemStatus = "pending" | "pushing" | "success" | "failed" | "skipped";

interface ItemState {
  report_id: string;
  company_name: string;
  status: ItemStatus;
  message?: string;
}

interface Props {
  reports: ReportMeta[];
  onClose: () => void;
  onComplete: () => void;
}

export default function BatchPushModal({ reports, onClose, onComplete }: Props) {
  const [items, setItems] = useState<ItemState[]>(() =>
    reports.map((r) => ({
      report_id: r.report_id,
      company_name: r.company_name || r.report_id,
      status: r.push_status === "pushed" ? "skipped" : "pending",
      message: r.push_status === "pushed" ? "跳过（已推送）" : undefined,
    }))
  );
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);

  const updateItem = (idx: number, patch: Partial<ItemState>) => {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  };

  const handleStart = useCallback(async () => {
    setRunning(true);
    const current = [...items];

    for (let i = 0; i < current.length; i++) {
      if (current[i].status === "skipped") continue;

      updateItem(i, { status: "pushing" });
      try {
        const result = await pushToFastGPT(current[i].report_id);
        current[i].status = "success";
        updateItem(i, {
          status: "success",
          message: `${result.uploaded}/${result.total} 条`,
        });
      } catch (e: any) {
        current[i].status = "failed";
        updateItem(i, {
          status: "failed",
          message: e.message || "推送失败",
        });
      }
    }

    setRunning(false);
    setDone(true);
  }, [items]);

  const counts = {
    success: items.filter((i) => i.status === "success").length,
    failed: items.filter((i) => i.status === "failed").length,
    skipped: items.filter((i) => i.status === "skipped").length,
    pending: items.filter((i) => i.status === "pending").length,
    pushing: items.filter((i) => i.status === "pushing").length,
  };

  const completed = counts.success + counts.failed + counts.skipped;

  const statusIcon = (s: ItemStatus) => {
    switch (s) {
      case "pending":
        return <span className="text-gray-400">&#9711;</span>;
      case "pushing":
        return <span className="text-blue-500 animate-spin inline-block">&#9881;</span>;
      case "success":
        return <span className="text-green-600">&#10003;</span>;
      case "failed":
        return <span className="text-red-600">&#10007;</span>;
      case "skipped":
        return <span className="text-gray-400">&#9654;</span>;
    }
  };

  const statusColor = (s: ItemStatus) => {
    switch (s) {
      case "pending": return "text-gray-500";
      case "pushing": return "text-blue-600";
      case "success": return "text-green-600";
      case "failed": return "text-red-600";
      case "skipped": return "text-gray-400";
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b">
          <h3 className="font-bold text-lg">批量推送到知识库</h3>
          <p className="text-xs text-gray-500 mt-1">
            共 {items.length} 份报告
            {counts.skipped > 0 && `，其中 ${counts.skipped} 份将跳过（已推送）`}
          </p>
        </div>

        {/* Report list */}
        <div className="flex-1 overflow-y-auto px-6 py-3">
          <div className="space-y-1.5">
            {items.map((item, idx) => (
              <div
                key={item.report_id}
                className="flex items-center gap-2 text-sm py-1.5 px-2 rounded hover:bg-gray-50"
              >
                <span className="w-5 text-center flex-shrink-0">{statusIcon(item.status)}</span>
                <span className="flex-1 truncate" title={item.company_name}>
                  {idx + 1}. {item.company_name}
                </span>
                {item.message && (
                  <span className={`text-xs flex-shrink-0 ${statusColor(item.status)}`}>
                    {item.message}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Progress bar */}
        {(running || done) && (
          <div className="px-6 py-2 border-t">
            <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
              <span>进度: {completed}/{items.length}</span>
              {done && (
                <span>
                  {counts.success > 0 && <span className="text-green-600">{counts.success} 成功</span>}
                  {counts.skipped > 0 && <span className="text-gray-400 ml-2">{counts.skipped} 跳过</span>}
                  {counts.failed > 0 && <span className="text-red-600 ml-2">{counts.failed} 失败</span>}
                </span>
              )}
            </div>
            <div className="w-full bg-gray-200 rounded-full h-1.5">
              <div
                className={`h-1.5 rounded-full transition-all ${counts.failed > 0 ? "bg-orange-400" : "bg-green-500"}`}
                style={{ width: `${(completed / items.length) * 100}%` }}
              />
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="px-6 py-4 border-t flex justify-end gap-3">
          {!done ? (
            <>
              <button
                onClick={onClose}
                disabled={running}
                className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50 disabled:opacity-30"
              >
                取消
              </button>
              <button
                onClick={handleStart}
                disabled={running || counts.pending === 0}
                className="px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
              >
                {running ? "推送中..." : `开始推送 (${counts.pending} 份)`}
              </button>
            </>
          ) : (
            <button
              onClick={onComplete}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              关闭
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
