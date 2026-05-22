import { useState, useEffect } from "react";
import { getIntakeLogs } from "../api/client";
import type { IntakeLog } from "../types";

const LOG_TYPE_LABELS: Record<string, string> = {
  create: "新建标的",
  update: "智能录入更新",
  attachment_update: "附件更新",
  light_update: "轻量更新",
  full_regenerate: "完整重调研",
};

const LOG_TYPE_COLORS: Record<string, string> = {
  create: "bg-green-100 text-green-700",
  update: "bg-blue-100 text-blue-700",
  attachment_update: "bg-indigo-100 text-indigo-700",
  light_update: "bg-blue-100 text-blue-700",
  full_regenerate: "bg-orange-100 text-orange-700",
};

const FIELD_LABELS: Record<string, string> = {
  company_name: "标的主体",
  project_name: "标的项目",
  is_listed: "上市情况",
  stock_code: "股票代码",
  province: "省",
  city: "市",
  district: "区县",
  website: "官网地址",
  revenue: "营业收入",
  net_profit: "净利润",
  revenue_yuan: "营业收入(元)",
  net_profit_yuan: "净利润(元)",
  description: "标的描述",
  company_intro: "公司简介",
  industry: "行业",
  industry_tags: "行业标签",
  valuation_yuan: "估值金额",
  valuation_date: "估值时间",
  offer_yuan: "报价金额",
  offer_date: "报价时间",
  is_traded: "交易状态",
  referral_status: "跟进动态",
  feasibility_rating: "项目评级",
  manual_rating: "人工评级",
  manual_rating_note: "评级备注",
};

function getFieldLabel(fieldKey: string) {
  return FIELD_LABELS[fieldKey] || fieldKey;
}

function formatMoneyLikeHomepage(val: string | number | null | undefined): string {
  if (val === null || val === undefined || val === "") return "（空）";
  const num = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(num)) return String(val);
  if (num >= 1e8) return `${(num / 1e8).toFixed(2)}亿`;
  if (num >= 1e4) return `${(num / 1e4).toFixed(0)}万`;
  return `${num}`;
}

function formatFieldValue(fieldKey: string, value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "（空）";
  if (["revenue_yuan", "net_profit_yuan", "valuation_yuan", "offer_yuan"].includes(fieldKey)) {
    return formatMoneyLikeHomepage(value);
  }
  return String(value);
}

function formatLogDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function FieldChangeRow({ fieldKey, change }: { fieldKey: string; change: any }) {
  const fieldLabel = getFieldLabel(fieldKey);
  if (typeof change === "object" && change !== null && "old" in change) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs py-0.5">
        <span className="text-gray-400 w-32 flex-shrink-0">{fieldLabel}</span>
        <span className="text-gray-500 line-through">{formatFieldValue(fieldKey, change.old)}</span>
        <span className="text-gray-400 mx-1">→</span>
        <span className="text-gray-800 font-medium">{formatFieldValue(fieldKey, change.new)}</span>
        {change.source_label && (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">
            来源: {change.source_label}
          </span>
        )}
      </div>
    );
  }
  return (
    <div className="flex gap-2 text-xs py-0.5">
      <span className="text-gray-400 w-32 flex-shrink-0">{fieldLabel}</span>
      <span className="text-gray-800">{formatFieldValue(fieldKey, change)}</span>
    </div>
  );
}

function LogCard({ log }: { log: IntakeLog }) {
  const [expanded, setExpanded] = useState(false);
  const date = formatLogDate(log.created_at);

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
              {getFieldLabel(k)}:&nbsp;
              {typeof v === "object" && v
                ? (
                  <span>
                    <s className="text-gray-400">{formatFieldValue(k, (v as any).old)}</s>
                    &nbsp;→&nbsp;
                    <span className="text-gray-700">{formatFieldValue(k, (v as any).new)}</span>
                    {(v as any).source_label ? (
                      <span className="ml-1 text-[11px] text-slate-400">[{(v as any).source_label}]</span>
                    ) : null}
                  </span>
                )
                : formatFieldValue(k, v as any)
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

  const counts = logs.reduce<Record<string, number>>((acc, log) => {
    acc[log.log_type] = (acc[log.log_type] || 0) + 1;
    return acc;
  }, {});
  const summaryItems = [
    { key: "create", label: LOG_TYPE_LABELS.create },
    { key: "update", label: LOG_TYPE_LABELS.update },
    { key: "attachment_update", label: LOG_TYPE_LABELS.attachment_update },
    { key: "full_regenerate", label: LOG_TYPE_LABELS.full_regenerate },
  ].filter((item) => counts[item.key] > 0);
  const latestLogAt = logs[0]?.created_at ? formatLogDate(logs[0].created_at) : null;

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
        <p className="text-xs mt-1">后续的智能录入新建、更新、附件更新与重调研记录都会显示在这里</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="text-sm font-medium text-slate-800">这里集中展示该项目的全部更新历史</p>
          <span className="text-xs text-slate-500">共 {logs.length} 条</span>
          {latestLogAt && <span className="text-xs text-slate-500">最近一次：{latestLogAt}</span>}
        </div>
        {summaryItems.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {summaryItems.map((item) => (
              <span
                key={item.key}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${LOG_TYPE_COLORS[item.key]}`}
              >
                {item.label} {counts[item.key]}
              </span>
            ))}
          </div>
        )}
      </div>
      {logs.map((log) => (
        <LogCard key={log.id} log={log} />
      ))}
    </div>
  );
}
