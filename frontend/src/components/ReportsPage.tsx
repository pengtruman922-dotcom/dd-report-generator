import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import {
  listReports,
  deleteReport,
  batchDeleteReports,
  getPdfDownloadUrl,
  pushToFastGPT,
  confirmReport,
  updateReportMeta,
  listIntakeTasks,
} from "../api/client";
import type { ReportMeta, PushStatus, IntakeTaskStatus } from "../types";
import { useAuth } from "../contexts/AuthContext";
import BatchPushModal from "./BatchPushModal";
import EditReportModal from "./EditReportModal";
import AttachmentPopover from "./AttachmentPopover";
import RatingConfirmModal from "./RatingConfirmModal";

/* ── Column definitions ────────────────────────────────────────── */

interface ColumnDef {
  key: string;
  label: string;
  defaultVisible: boolean;
  sortable?: boolean;
  /** render override */
  render?: (val: any, row: ReportMeta) => React.ReactNode;
}

type SuggestionSource = "项目名" | "行业" | "标签";
type SearchSuggestionItem = { value: string; source: SuggestionSource };

/* ── Helper functions ───────────────────────────────────────── */

function formatMoney(val: string | number | null | undefined): string {
  if (val === null || val === undefined || val === "") return "--";
  const num = typeof val === "string" ? parseFloat(val) : val;
  if (isNaN(num)) return "--";
  if (num >= 1e8) return `${(num / 1e8).toFixed(2)}亿`;
  if (num >= 1e4) return `${(num / 1e4).toFixed(0)}万`;
  return `${num}`;
}

function formatDate(iso: string): string {
  if (!iso) return "--";
  return iso.slice(0, 10);
}

function formatMonth(iso: string | null | undefined): string {
  if (!iso) return "--";
  return iso.slice(0, 7);
}

function hasMeaningfulAmount(val: string | number | null | undefined): boolean {
  if (val === null || val === undefined) return false;
  const raw = String(val).trim();
  if (!raw) return false;
  const num = Number(raw);
  if (!Number.isNaN(num)) return num !== 0;
  return raw !== "0";
}

function ratingColor(r: string | null | undefined): string {
  if (!r) return "bg-gray-100 text-gray-500 border-gray-300";
  const map: Record<string, string> = {
    A: "bg-green-100 text-green-700 border-green-300",
    B: "bg-blue-100 text-blue-700 border-blue-300",
    C: "bg-yellow-100 text-yellow-700 border-yellow-300",
    D: "bg-orange-100 text-orange-700 border-orange-300",
    E: "bg-red-100 text-red-700 border-red-300",
  };
  return map[r] || "bg-gray-100 text-gray-500 border-gray-300";
}

/** Get offer first, then valuation, then null */
function getOfferOrValuation(row: ReportMeta): { value: string; isEstimate: boolean } | null {
  if (hasMeaningfulAmount(row.offer_yuan)) {
    return { value: String(row.offer_yuan), isEstimate: false };
  }
  if (hasMeaningfulAmount(row.valuation_yuan)) {
    return { value: String(row.valuation_yuan), isEstimate: true };
  }
  return null;
}

function getOfferOrValuationDate(row: ReportMeta): string | null {
  if (hasMeaningfulAmount(row.offer_yuan) && row.offer_date) {
    return row.offer_date;
  }
  if (hasMeaningfulAmount(row.valuation_yuan) && row.valuation_date) {
    return row.valuation_date;
  }
  return null;
}

function getTrackingPreviewLines(value: string | null | undefined): string[] {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

const ALL_COLUMNS: ColumnDef[] = [
  // 1. 标的编码
  { key: "bd_code", label: "标的编码", defaultVisible: true, sortable: true },

  // 2. 标的项目（可点击跳转）
  {
    key: "project_name",
    label: "标的项目",
    defaultVisible: true,
    render: (val, row) => (
      <button
        onClick={() => window.__navigateReport?.(row.report_id)}
        className="text-blue-600 hover:underline text-left truncate block max-w-[200px]"
        title={val}
      >
        {val || "--"}
      </button>
    ),
  },

  // 3. 标的主体（普通文本）
  {
    key: "company_name",
    label: "标的主体",
    defaultVisible: true,
    render: (val) => (
      <span className="truncate block max-w-[200px]" title={val}>
        {val || "--"}
      </span>
    ),
  },

  // 4. 行业（合并 industry + industry_tags）
  {
    key: "industry",
    label: "行业",
    defaultVisible: true,
    render: (val, row) => {
      const tags = row.industry_tags
        ? String(row.industry_tags).split(/[,，]/).map((t: string) => t.trim()).filter(Boolean)
        : [];
      return (
        <div className="flex flex-wrap items-center gap-1 max-w-[250px]">
          {val ? <span className="text-sm text-gray-800">{val}</span> : null}
          {tags.map((tag: string, i: number) => (
            <span key={i} className="inline-block px-1.5 py-0 rounded text-xs bg-blue-50 text-blue-600">
              #{tag}
            </span>
          ))}
          {!val && tags.length === 0 && <span className="text-gray-400 text-xs">--</span>}
        </div>
      );
    },
  },

  // 5. 可行性评级（A-E + 手动覆盖下拉）
  {
    key: "feasibility_rating",
    label: "评级",
    defaultVisible: true,
    sortable: true,
    render: (val, row) => {
      const rating = row.feasibility_rating;
      const hasPending = !!row.pending_rating_change;
      const options = ["A", "B", "C", "D", "E"];

      if (hasPending) {
        let pendingRating = "";
        try {
          const pending = JSON.parse(row.pending_rating_change || "{}");
          pendingRating = pending.rating || "";
        } catch (e) { /* ignore */ }

        return (
          <div className="flex items-center gap-1">
            <span className={`inline-block px-2 py-0.5 rounded text-xs border ${ratingColor(rating)}`}>
              {rating || "?"}
            </span>
            <span className="text-xs text-gray-400">→</span>
            <span className={`inline-block px-2 py-0.5 rounded text-xs border ${ratingColor(pendingRating)} animate-pulse`}>
              {pendingRating}
            </span>
            <button
              onClick={(e) => { e.stopPropagation(); window.__openRatingConfirmModal?.(row.report_id); }}
              className="text-xs text-blue-600 hover:underline"
            >
              待确认
            </button>
          </div>
        );
      }

      return (
        <div className="flex items-center gap-1">
          <span className={`inline-block px-2 py-0.5 rounded text-xs border ${ratingColor(rating)}`}>
            {rating || "--"}
          </span>
          <select
            value={rating || ""}
            onChange={(e) => window.__updateFeasibilityRating?.(row.report_id, e.target.value || null)}
            className="text-xs px-1 py-0.5 rounded border bg-white hover:bg-gray-50"
            title="手动覆盖评级"
            onClick={(e) => e.stopPropagation()}
          >
            <option value="">AI评级</option>
            {options.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      );
    },
  },

  // 6. 评级时间
  {
    key: "feasibility_rating_at",
    label: "评级时间",
    defaultVisible: true,
    render: (val) => <span className="text-xs text-gray-600">{formatDate(val || "")}</span>,
  },

  // 7. 报告生成状态
  {
    key: "status",
    label: "报告生成状态",
    defaultVisible: true,
    render: (val, row) => {
      const liveTask = window.__intakeTasks?.[row.report_id]
        ?? (row.bd_code ? window.__intakeTasks?.[row.bd_code] : undefined);
      if (liveTask && liveTask.status !== "completed" && liveTask.status !== "cancelled" && liveTask.status !== "failed") {
        const stepLabel = liveTask.step > 0 ? ` Step${liveTask.step}/${liveTask.total_steps}` : "";
        if (liveTask.status === "cancelling")
          return <span className="inline-block px-2 py-0.5 rounded text-xs bg-orange-100 text-orange-600 animate-pulse">终止中</span>;
        if (liveTask.status === "queued") {
          const pos = liveTask.queue_position ?? "";
          return <span className="inline-block px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-500">排队中{pos ? ` 第${pos}位` : ""}</span>;
        }
        const isUpdate = liveTask.op_type === "light_update" || liveTask.op_type === "full_regenerate" || liveTask.op_type === "update";
        return (
          <span className="inline-block px-2 py-0.5 rounded text-xs bg-blue-100 text-blue-700 animate-pulse">
            {isUpdate ? "更新中" : "生成中"}⟳{stepLabel}
          </span>
        );
      }
      if (val === "completed")
        return <span className="inline-block px-2 py-0.5 rounded text-xs bg-green-100 text-green-700">已完成</span>;
      if (val === "updated")
        return (
          <button
            onClick={() => window.__confirmReport?.(row.report_id)}
            className="inline-block px-2 py-0.5 rounded text-xs bg-yellow-100 text-yellow-700 hover:bg-yellow-200 cursor-pointer"
            title="点击确认"
          >
            已更新
          </button>
        );
      if (val === "generating")
        return <span className="inline-block px-2 py-0.5 rounded text-xs bg-blue-100 text-blue-700 animate-pulse">生成中</span>;
      if (val === "failed")
        return <span className="inline-block px-2 py-0.5 rounded text-xs bg-red-100 text-red-700">失败</span>;
      return <span className="text-gray-400">{val || "--"}</span>;
    },
  },

  // 8. 跟进动态
  {
    key: "referral_status",
    label: "跟进动态",
    defaultVisible: true,
    render: (val, row) => {
      const lines = getTrackingPreviewLines(val);
      const previewLines = lines.slice(0, 3);
      const fullPreview = lines.slice(0, 5).join("\n");
      if (previewLines.length === 0) {
        return <span className="text-gray-400 text-xs">--</span>;
      }
      return (
        <div className="max-w-[280px]" title={fullPreview}>
          <div className="space-y-1">
            {previewLines.map((line, idx) => (
              <p
                key={`${row.report_id}-tracking-${idx}`}
                className="text-xs leading-5 text-gray-700 line-clamp-1"
              >
                {line}
              </p>
            ))}
          </div>
              <button
            onClick={(e) => {
              e.stopPropagation();
              window.__navigateReportChunk?.(row.report_id, "tracking");
            }}
            className="mt-1 text-xs text-blue-600 hover:underline"
            title={fullPreview}
          >
            {lines.length > 3 ? "查看更多" : "查看详情"}
          </button>
        </div>
      );
    },
  },

  // 9. 营业收入
  {
    key: "revenue",
    label: "营业收入",
    defaultVisible: true,
    render: (val, row) => {
      if (row.revenue_yuan) return <span className="text-sm">{formatMoney(row.revenue_yuan)}</span>;
      return <span className="text-sm">{val || "--"}</span>;
    },
  },

  // 10. 报价/估值
  {
    key: "offer_or_valuation",
    label: "报价/估值",
    defaultVisible: true,
    sortable: true,
    render: (_val, row) => {
      const data = getOfferOrValuation(row);
      if (!data) return <span className="text-gray-400 text-xs">--</span>;
      return (
        <span className="text-sm">
          {formatMoney(data.value)}
          {data.isEstimate && <span className="text-orange-500 text-xs ml-0.5" title="估值（非报价）">*</span>}
        </span>
      );
    },
  },

  // 11. 报价/估值时间
  {
    key: "offer_or_valuation_date",
    label: "报价/估值时间",
    defaultVisible: true,
    render: (_val, row) => {
      const date = getOfferOrValuationDate(row);
      return <span className="text-xs text-gray-600">{date ? formatMonth(date) : "--"}</span>;
    },
  },

  // 12. 附件
  {
    key: "attachments",
    label: "附件",
    defaultVisible: true,
    render: (val, row) => {
      const count = Array.isArray(val) ? val.length : 0;
      return (
        <AttachmentPopover
          reportId={row.report_id}
          initialCount={count}
          onUpdate={() => window.__refreshReports?.()}
          onTaskCreated={() => window.__refreshIntakeTasks?.()}
        />
      );
    },
  },

  // 13. 推送状态
  {
    key: "push_status",
    label: "推送状态",
    defaultVisible: true,
    render: (val: PushStatus | undefined, row: ReportMeta) => {
      const info = row.push_info;
      const tooltip = info
        ? `推送时间: ${info.pushed_at?.slice(0, 19).replace("T", " ") ?? "?"}\n已推送: ${info.uploaded}/${info.total} 条`
        : undefined;
      if (val === "no_chunks")
        return <span className="inline-block px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-500" title="无��引数据">无索引</span>;
      if (val === "not_pushed")
        return <span className="inline-block px-2 py-0.5 rounded text-xs bg-blue-100 text-blue-600">未推送</span>;
      if (val === "pushed")
        return <span className="inline-block px-2 py-0.5 rounded text-xs bg-green-100 text-green-700" title={tooltip}>已推送</span>;
      if (val === "outdated")
        return <span className="inline-block px-2 py-0.5 rounded text-xs bg-orange-100 text-orange-700" title={tooltip}>需更新</span>;
      return <span className="text-gray-400">--</span>;
    },
  },

  // 14. 更新时间
  {
    key: "updated_at",
    label: "更新时间",
    defaultVisible: true,
    sortable: true,
    render: (val) => <span className="text-xs text-gray-600">{formatDate(val || "")}</span>,
  },

  // ── 默认隐藏 ──
  { key: "net_profit", label: "净利润", defaultVisible: false },
  { key: "province", label: "省", defaultVisible: false },
  { key: "city", label: "市", defaultVisible: false },
  { key: "district", label: "区", defaultVisible: false },
  { key: "is_listed", label: "上市情况", defaultVisible: false },
  { key: "stock_code", label: "上市编号", defaultVisible: false },
  { key: "website", label: "官网地址", defaultVisible: false },
  { key: "description", label: "标的描述", defaultVisible: false },
  { key: "dept_primary", label: "负责人主属部门", defaultVisible: false },
  { key: "dept_owner", label: "归属部门", defaultVisible: false },
  { key: "estimated_cost", label: "预估成本", defaultVisible: false, sortable: true,
    render: (val) => {
      if (val === null || val === undefined) return <span className="text-gray-400 text-xs">--</span>;
      return <span className="text-xs text-gray-600">¥{Number(val).toFixed(2)}</span>;
    },
  },
];

// Persist column config in localStorage
const STORAGE_KEY = "dd_report_columns_v4";
const LEGACY_STORAGE_KEY = "dd_report_columns_v3";

function loadColumnConfig(): { visible: string[]; order: string[] } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveColumnConfig(visible: string[], order: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ visible, order }));
}

// Global helpers for render functions
declare global {
  interface Window {
    __navigateReport?: (id: string) => void;
    __navigateReportChunk?: (id: string, chunkId: string) => void;
    __confirmReport?: (id: string) => void;
    __refreshReports?: () => void;
    __refreshIntakeTasks?: () => void;
    __updateFeasibilityRating?: (id: string, rating: string | null) => void;
    __openRatingConfirmModal?: (id: string) => void;
    __intakeTasks?: Record<string, IntakeTaskStatus>;
  }
}

/* ── Component ─────────────────────────────────────────────────── */

type SortDir = "asc" | "desc";

export default function ReportsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  // Edit modal
  const [editReport, setEditReport] = useState<ReportMeta | null>(null);

  // Rating confirm modal
  const [ratingConfirmReport, setRatingConfirmReport] = useState<ReportMeta | null>(null);

  // Confirm report handler
  const handleConfirm = useCallback(async (id: string) => {
    try {
      await confirmReport(id);
      fetchReportsRef.current?.();
    } catch (e: any) {
      alert("确认失败: " + e.message);
    }
  }, []);

  // Update feasibility rating handler
  const handleUpdateFeasibilityRating = useCallback(async (id: string, rating: string | null) => {
    try {
      await updateReportMeta(id, { feasibility_rating: rating });
      fetchReportsRef.current?.();
    } catch (e: any) {
      alert("更新评级失败: " + e.message);
    }
  }, []);

  // Intake task status — poll while any tasks are running, expose via window global
  const [intakeTasks, setIntakeTasks] = useState<Record<string, IntakeTaskStatus>>({});;

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastKnownActiveTask = true;

    const scheduleNextPoll = (delay = 3000) => {
      if (!active) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(poll, delay);
    };

    const poll = async () => {
      try {
        const { tasks } = await listIntakeTasks();
        if (!active) return;
        // Index by report_id and bd_code for O(1) lookup in render
        const byKey: Record<string, IntakeTaskStatus> = {};
        let hasRunningTasks = false;
        for (const t of tasks) {
          if (t.report_id) byKey[t.report_id] = t;
          if (t.bd_code) byKey[t.bd_code] = t;
          if (t.status !== "completed" && t.status !== "cancelled" && t.status !== "failed") {
            hasRunningTasks = true;
          }
        }
        lastKnownActiveTask = hasRunningTasks;
        setIntakeTasks(byKey);
        window.__intakeTasks = byKey;
        if (hasRunningTasks) {
          scheduleNextPoll();
        }
      } catch {
        // Keep retrying after transient request failures so list badges can recover.
        if (lastKnownActiveTask) {
          scheduleNextPoll();
        }
      }
    };
    window.__refreshIntakeTasks = () => {
      lastKnownActiveTask = true;
      poll();
    };
    poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
      delete window.__intakeTasks;
      delete window.__refreshIntakeTasks;
    };
  }, []);

  // fetchReports ref for global access
  const fetchReportsRef = useRef<(() => void) | null>(null);
  const searchBoxRef = useRef<HTMLDivElement>(null);
  const hasLoadedOnceRef = useRef(false);

  const [reports, setReports] = useState<ReportMeta[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Register global helpers for render functions
  useEffect(() => {
    window.__navigateReport = (id: string) => navigate(`/report/${id}`);
    window.__navigateReportChunk = (id: string, chunkId: string) =>
      navigate(`/report/${id}?tab=chunks&chunk=${encodeURIComponent(chunkId)}`);
    window.__confirmReport = (id: string) => handleConfirm(id);
    window.__refreshReports = () => fetchReportsRef.current?.();
    window.__updateFeasibilityRating = (id: string, rating: string | null) => handleUpdateFeasibilityRating(id, rating);
    window.__openRatingConfirmModal = (id: string) => {
      const report = reports.find(r => r.report_id === id);
      if (report) setRatingConfirmReport(report);
    };
    return () => {
      delete window.__navigateReport;
      delete window.__navigateReportChunk;
      delete window.__confirmReport;
      delete window.__refreshReports;
      delete window.__updateFeasibilityRating;
      delete window.__openRatingConfirmModal;
    };
  }, [navigate, handleConfirm, handleUpdateFeasibilityRating, reports]);

  // Filters
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [showSearchSuggestions, setShowSearchSuggestions] = useState(false);
  const [searchSuggestionPool, setSearchSuggestionPool] = useState<SearchSuggestionItem[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [ratingFilter, setRatingFilter] = useState("all");
  const [pushStatusFilter, setPushStatusFilter] = useState("all");
  const [ownerFilter, setOwnerFilter] = useState("all");

  const searchSuggestions = useMemo(() => {
    const q = searchInput.trim().toLowerCase();
    if (!q) return [];
    const scoreName = (name: string, source: SuggestionSource): number => {
      const n = name.toLowerCase();
      const sourceBoost = source === "项目名" ? 20 : source === "行业" ? 10 : 0;
      if (n === q) return 1000;
      if (n.startsWith(q)) return 800 - (n.length - q.length) + sourceBoost;
      const idx = n.indexOf(q);
      if (idx >= 0) return 600 - idx + sourceBoost;
      let pos = 0;
      let matched = 0;
      for (const ch of q) {
        const found = n.indexOf(ch, pos);
        if (found === -1) break;
        matched += 1;
        pos = found + 1;
      }
      return matched > 0 ? matched * 10 + sourceBoost : -1;
    };
    return searchSuggestionPool
      .map((item) => ({ ...item, score: scoreName(item.value, item.source) }))
      .filter((x) => x.score >= 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 10)
      .map((x) => ({ value: x.value, source: x.source }));
  }, [searchInput, searchSuggestionPool]);

  const renderSuggestion = (item: SearchSuggestionItem) => {
    const q = searchInput.trim();
    const name = item.value;
    if (!q) return name;
    const idx = name.toLowerCase().indexOf(q.toLowerCase());
    if (idx < 0) return name;
    const before = name.slice(0, idx);
    const hit = name.slice(idx, idx + q.length);
    const after = name.slice(idx + q.length);
    return (
      <>
        {before}
        <span className="bg-yellow-100 text-yellow-800 px-0.5 rounded">{hit}</span>
        {after}
      </>
    );
  };

  // Batch push modal
  const [showBatchPush, setShowBatchPush] = useState(false);

  // Sort
  const [sortKey, setSortKey] = useState<string>("created_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Selection
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Pagination (server-side)
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [totalRecords, setTotalRecords] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  // Delete confirm
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false);

  // Column config — merge new columns into saved config
  const saved = loadColumnConfig();
  const allKeys = ALL_COLUMNS.map((c) => c.key);
  const [visibleKeys, setVisibleKeys] = useState<string[]>(() => {
    if (!saved) return ALL_COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key);
    // Add any new defaultVisible columns not in saved config
    const newVisible = ALL_COLUMNS
      .filter((c) => c.defaultVisible && !saved.visible.includes(c.key) && !(saved.order ?? []).includes(c.key))
      .map((c) => c.key);
    return [...saved.visible, ...newVisible];
  });
  const [columnOrder, setColumnOrder] = useState<string[]>(() => {
    if (!saved) return allKeys;
    // Append any new columns not in saved order
    const missing = allKeys.filter((k) => !saved.order.includes(k));
    return [...saved.order, ...missing];
  });
  const [showColConfig, setShowColConfig] = useState(false);
  const colConfigRef = useRef<HTMLDivElement>(null);

  // Close column config on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (colConfigRef.current && !colConfigRef.current.contains(e.target as Node)) {
        setShowColConfig(false);
      }
    };
    if (showColConfig) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showColConfig]);

  useEffect(() => {
    if (!showSearchSuggestions) return;
    const handler = (e: MouseEvent) => {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setShowSearchSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showSearchSuggestions]);

  // Save column config when it changes
  useEffect(() => {
    saveColumnConfig(visibleKeys, columnOrder);
  }, [visibleKeys, columnOrder]);

  // Ordered visible columns
  const visibleColumns = useMemo(() => {
    const keySet = new Set(visibleKeys);
    return columnOrder
      .filter((k) => keySet.has(k))
      .map((k) => ALL_COLUMNS.find((c) => c.key === k)!)
      .filter(Boolean);
  }, [visibleKeys, columnOrder]);

  // Ordered all columns (for config panel)
  const orderedAllColumns = useMemo(() => {
    return columnOrder
      .map((k) => ALL_COLUMNS.find((c) => c.key === k)!)
      .filter(Boolean);
  }, [columnOrder]);

  // Unique owners for admin filter
  const [ownerOptions, setOwnerOptions] = useState<string[]>([]);

  const fetchReports = useCallback(async () => {
    if (!hasLoadedOnceRef.current) setInitialLoading(true);
    else setTableLoading(true);
    setError(null);
    try {
      // Map frontend filter values to backend API values
      const params: any = {
        page,
        page_size: pageSize,
        sort_by: sortKey,
        sort_dir: sortDir,
      };

      if (search) params.search = search;
      if (statusFilter !== "all") params.status = statusFilter;
      if (ownerFilter !== "all") params.owner = ownerFilter;

      // Feasibility rating filter (A-E)
      if (ratingFilter !== "all") {
        params.feasibility_rating = ratingFilter;
      }

      // Note: pushStatusFilter is not supported by backend yet, so we skip it

      const data = await listReports(params);
      setReports(data.reports);
      setTotalRecords(data.total);
      setTotalPages(data.total_pages);
      setSearchSuggestionPool((prev) => {
        const priority: Record<SuggestionSource, number> = { "项目名": 3, "行业": 2, "标签": 1 };
        const next = new Map<string, SearchSuggestionItem>();
        prev.forEach((item) => next.set(item.value, item));
        const upsert = (value: string, source: SuggestionSource) => {
          const key = value.trim();
          if (!key) return;
          const old = next.get(key);
          if (!old || priority[source] > priority[old.source]) {
            next.set(key, { value: key, source });
          }
        };
        data.reports.forEach((r) => {
          const projectName = String(r.project_name || "").trim();
          upsert(projectName, "项目名");
          const industry = String(r.industry || "").trim();
          upsert(industry, "行业");
          const tags = String(r.industry_tags || "")
            .split(/[,\uff0c]/)
            .map((t) => t.trim())
            .filter(Boolean);
          tags.forEach((t) => upsert(t, "标签"));
        });
        return Array.from(next.values());
      });

      // Extract unique owners for filter dropdown (only on first load or when needed)
      if (isAdmin && ownerOptions.length === 0) {
        const owners = new Set<string>();
        data.reports.forEach((r) => { if (r.owner) owners.add(r.owner); });
        setOwnerOptions(Array.from(owners).sort());
      }
    } catch (e: any) {
      setError(e.message);
    }
    hasLoadedOnceRef.current = true;
    setInitialLoading(false);
    setTableLoading(false);
  }, [page, pageSize, search, statusFilter, ratingFilter, ownerFilter, sortKey, sortDir, isAdmin, ownerOptions.length]);

  fetchReportsRef.current = fetchReports;

  useEffect(() => {
    fetchReports();
  }, [fetchReports]);

  const executeSearch = () => {
    const next = searchInput.trim();
    if (next === search) {
      setPage(1);
      fetchReportsRef.current?.();
    } else {
      setSearch(next);
      setPage(1);
    }
    setShowSearchSuggestions(false);
  };

  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [statusFilter, ratingFilter, pushStatusFilter, ownerFilter, pageSize]);

  const allOnPageSelected =
    reports.length > 0 && reports.every((r) => selected.has(r.report_id));

  const toggleAll = () => {
    if (allOnPageSelected) {
      const next = new Set(selected);
      reports.forEach((r) => next.delete(r.report_id));
      setSelected(next);
    } else {
      const next = new Set(selected);
      reports.forEach((r) => next.add(r.report_id));
      setSelected(next);
    }
  };

  const toggleOne = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };

  const handleSort = (key: string) => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  };

  const sortIcon = (key: string) => {
    if (sortKey !== key) return "\u2195";
    return sortDir === "asc" ? "\u2191" : "\u2193";
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteReport(id);
      setConfirmDelete(null);
      setSelected((prev) => { const next = new Set(prev); next.delete(id); return next; });
      fetchReports();
    } catch (e: any) { alert("删除失败: " + e.message); }
  };

  const handleBatchDelete = async () => {
    try {
      await batchDeleteReports(Array.from(selected));
      setConfirmBatchDelete(false);
      setSelected(new Set());
      fetchReports();
    } catch (e: any) { alert("批量删除失败: " + e.message); }
  };

  // Single-report push
  const [pushingId, setPushingId] = useState<string | null>(null);
  const handlePush = async (id: string) => {
    setPushingId(id);
    try {
      const result = await pushToFastGPT(id);
      alert(`已推送 ${result.uploaded}/${result.total} 条到知识库`);
      fetchReports();
    } catch (e: any) {
      alert("推送失败: " + e.message);
    }
    setPushingId(null);
  };

  // "More" dropdown — portal-based to avoid overflow clipping
  const [moreOpenId, setMoreOpenId] = useState<string | null>(null);
  const [morePos, setMorePos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const moreRef = useRef<HTMLDivElement>(null);
  const moreBtnRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const openMore = (id: string) => {
    if (moreOpenId === id) { setMoreOpenId(null); return; }
    const btn = moreBtnRefs.current.get(id);
    if (btn) {
      const rect = btn.getBoundingClientRect();
      const menuW = 144; // w-36
      let left = rect.right - menuW;
      if (left < 8) left = 8;
      setMorePos({ top: rect.bottom + 4, left });
    }
    setMoreOpenId(id);
  };

  useEffect(() => {
    if (!moreOpenId) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      const btn = moreBtnRefs.current.get(moreOpenId);
      if (
        moreRef.current && !moreRef.current.contains(target) &&
        (!btn || !btn.contains(target))
      ) {
        setMoreOpenId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [moreOpenId]);

  // Column config helpers
  const toggleColumn = (key: string) => {
    setVisibleKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const resetColumns = () => {
    setVisibleKeys(ALL_COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key));
    setColumnOrder(ALL_COLUMNS.map((c) => c.key));
  };

  // Drag-and-drop column reorder
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);

  const handleDragStart = (e: React.DragEvent, key: string) => {
    setDragKey(key);
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragOver = (e: React.DragEvent, key: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (key !== dragOverKey) setDragOverKey(key);
  };

  const handleDrop = (e: React.DragEvent, targetKey: string) => {
    e.preventDefault();
    if (dragKey && dragKey !== targetKey) {
      setColumnOrder((prev) => {
        const fromIdx = prev.indexOf(dragKey);
        const toIdx = prev.indexOf(targetKey);
        if (fromIdx < 0 || toIdx < 0) return prev;
        const next = [...prev];
        next.splice(fromIdx, 1);
        next.splice(toIdx, 0, dragKey);
        return next;
      });
    }
    setDragKey(null);
    setDragOverKey(null);
  };

  const handleDragEnd = () => {
    setDragKey(null);
    setDragOverKey(null);
  };

  // ── Cell text helper (for tooltip & export) ──────────────────
  const getCellText = (col: ColumnDef, row: ReportMeta): string => {
    const val = row[col.key];
    if (val === null || val === undefined) return "";
    if (col.key === "updated_at" || col.key === "feasibility_rating_at") return formatDate(String(val));
    if (col.key === "status") {
      if (val === "completed") return "已完成";
      if (val === "updated") return "已更新";
      if (val === "generating") return "生成中";
      if (val === "failed") return "失败";
    }
    if (col.key === "attachments") {
      const count = Array.isArray(val) ? val.length : 0;
      return String(count);
    }
    if (col.key === "push_status") {
      if (val === "no_chunks") return "无索引";
      if (val === "not_pushed") return "未推送";
      if (val === "pushed") return "已推送";
      if (val === "outdated") return "需更新";
    }
    if (col.key === "feasibility_rating") return String(val);
    if (col.key === "offer_or_valuation") {
      const data = getOfferOrValuation(row);
      return data ? `${formatMoney(data.value)}${data.isEstimate ? "*" : ""}` : "";
    }
    if (col.key === "offer_or_valuation_date") {
      const date = getOfferOrValuationDate(row);
      return date ? formatMonth(date) : "";
    }
    if (col.key === "revenue" && row.revenue_yuan) return formatMoney(row.revenue_yuan);
    if (col.key === "manual_rating") return val || "";
    if (col.key === "token_usage_json") {
      if (!val) return "";
      try {
        const usage = JSON.parse(String(val));
        const total = Object.values(usage).reduce((sum: number, count: any) => sum + (typeof count === 'number' ? count : 0), 0);
        return String(total);
      } catch {
        return "";
      }
    }
    if (col.key === "estimated_cost") {
      return typeof val === "number" ? `¥${val.toFixed(2)}` : "";
    }
    return String(val);
  };

  // ── Export Excel (CSV with BOM) ──────────────────────────────
  const handleExportExcel = () => {
    const headers = visibleColumns.map((c) => c.label);
    const rows = reports.map((r) =>
      visibleColumns.map((c) => getCellText(c, r)),
    );
    const BOM = "\uFEFF";
    const csv = [
      headers.join(","),
      ...rows.map((row) =>
        row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(","),
      ),
    ].join("\n");
    const blob = new Blob([BOM + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `标的数据_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (initialLoading) {
    return <div className="flex items-center justify-center py-20 text-gray-400">加载中...</div>;
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        加载失败: {error}
        <button onClick={fetchReports} className="ml-3 underline">重试</button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">
          标的管理 <span className="text-sm font-normal text-gray-400">({totalRecords} 份)</span>
        </h1>
        <button
          onClick={() => navigate("/new")}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + 智能录入
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative w-72" ref={searchBoxRef}>
          <button
            onClick={executeSearch}
            className="absolute left-1 top-1/2 -translate-y-1/2 p-1.5 text-gray-500 hover:text-blue-600"
            title="搜索"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35m1.35-5.65a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </button>
          <input
            type="text"
            placeholder="搜索项目名称、行业"
            value={searchInput}
            onFocus={() => setShowSearchSuggestions(searchSuggestions.length > 0)}
            onChange={(e) => {
              setSearchInput(e.target.value);
              setShowSearchSuggestions(e.target.value.trim().length > 0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") executeSearch();
            }}
            className="border rounded-lg pl-9 pr-3 py-1.5 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
          {showSearchSuggestions && searchSuggestions.length > 0 && (
            <div className="absolute z-50 top-full mt-1 w-full bg-white border rounded-lg shadow-lg overflow-hidden">
              {searchSuggestions.map((item) => (
                <button
                  key={`${item.source}-${item.value}`}
                  onClick={() => {
                    setSearchInput(item.value);
                    setShowSearchSuggestions(false);
                  }}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 flex items-center justify-between gap-2"
                  title={item.value}
                >
                  <span className="truncate">{renderSuggestion(item)}</span>
                  <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 shrink-0">
                    {item.source}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <select value={ratingFilter} onChange={(e) => setRatingFilter(e.target.value)}
          className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300">
          <option value="all">评级: 全部</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
          <option value="D">D</option>
          <option value="E">E</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300">
          <option value="all">状态: 全部</option>
          <option value="completed">已完成</option>
          <option value="updated">已更新</option>
        </select>
        <select value={pushStatusFilter} onChange={(e) => setPushStatusFilter(e.target.value)}
          className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300">
          <option value="all">推送: 全部</option>
          <option value="not_pushed">未推送</option>
          <option value="pushed">已推送</option>
          <option value="outdated">需更新</option>
          <option value="no_chunks">无索引</option>
        </select>
        {isAdmin && ownerOptions.length > 0 && (
          <select value={ownerFilter} onChange={(e) => setOwnerFilter(e.target.value)}
            className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300">
            <option value="all">用户: 全部</option>
            {ownerOptions.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        )}
        {tableLoading && <span className="text-xs text-gray-500">加载中...</span>}
        {/* Export & Column config */}
        <div className="flex items-center gap-2 ml-auto">
        <button
          onClick={handleExportExcel}
          disabled={reports.length === 0}
          className="px-3 py-1.5 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-1 disabled:opacity-30"
          title="导出当前筛选结果为 Excel"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          导出
        </button>
        <div className="relative" ref={colConfigRef}>
          <button
            onClick={() => setShowColConfig(!showColConfig)}
            className="px-3 py-1.5 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-1"
            title="配置显示列"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
            </svg>
            列配置
          </button>
          {showColConfig && (
            <div className="absolute right-0 top-full mt-1 w-72 bg-white border rounded-lg shadow-xl z-50 max-h-[480px] overflow-y-auto">
              <div className="sticky top-0 bg-white border-b px-3 py-2 flex items-center justify-between">
                <span className="text-sm font-medium">显示/隐藏列</span>
                <button onClick={resetColumns} className="text-xs text-blue-600 hover:underline">
                  恢复默认
                </button>
              </div>
              {orderedAllColumns.map((col) => (
                <div
                  key={col.key}
                  draggable
                  onDragStart={(e) => handleDragStart(e, col.key)}
                  onDragOver={(e) => handleDragOver(e, col.key)}
                  onDrop={(e) => handleDrop(e, col.key)}
                  onDragEnd={handleDragEnd}
                  className={`flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 text-sm cursor-grab active:cursor-grabbing
                    ${dragKey === col.key ? "opacity-40" : ""}
                    ${dragOverKey === col.key && dragKey !== col.key ? "border-t-2 border-blue-400" : ""}`}
                >
                  <svg className="w-3.5 h-3.5 text-gray-300 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 6h2v2H8V6zm6 0h2v2h-2V6zM8 11h2v2H8v-2zm6 0h2v2h-2v-2zm-6 5h2v2H8v-2zm6 0h2v2h-2v-2z"/>
                  </svg>
                  <input
                    type="checkbox"
                    checked={visibleKeys.includes(col.key)}
                    onChange={() => toggleColumn(col.key)}
                    className="rounded"
                  />
                  <span className="flex-1 truncate">{col.label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        </div>
      </div>

      {/* Batch actions */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 bg-blue-50 border border-blue-200 rounded-lg px-4 py-2 text-sm">
          <span className="text-blue-700 font-medium">已选 {selected.size} 项</span>
          <button onClick={() => setShowBatchPush(true)}
            className="px-3 py-1 bg-green-500 text-white rounded hover:bg-green-600 text-xs">推送到知识库</button>
          <button onClick={() => setConfirmBatchDelete(true)}
            className="px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600 text-xs">批量删除</button>
          <button onClick={() => setSelected(new Set())}
            className="px-3 py-1 bg-gray-200 text-gray-600 rounded hover:bg-gray-300 text-xs">取消选择</button>
        </div>
      )}

      {/* Table */}
      {reports.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          {totalRecords === 0 ? "暂无报告，点击「智能录入」开始创建或更新标的" : "没有符合筛选条件的报告"}
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-x-auto">
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead>
              <tr className="bg-gray-50 border-b text-left">
                <th className="px-3 py-2.5 w-10 sticky left-0 z-20 bg-gray-50 border-b">
                  <input type="checkbox" checked={allOnPageSelected} onChange={toggleAll} className="rounded" />
                </th>
                {visibleColumns.map((col, i) => (
                  <th
                    key={col.key}
                    className={`px-3 py-2.5 whitespace-nowrap border-b ${col.sortable ? "cursor-pointer hover:text-blue-600" : ""} ${i === 0 ? "sticky left-10 z-20 bg-gray-50 shadow-[2px_0_5px_-2px_rgba(0,0,0,0.1)]" : ""}`}
                    onClick={() => col.sortable && handleSort(col.key)}
                  >
                    {col.label} {col.sortable ? sortIcon(col.key) : ""}
                  </th>
                ))}
                <th className="px-3 py-2.5 whitespace-nowrap text-center sticky right-0 z-20 bg-gray-50 border-b shadow-[-2px_0_5px_-2px_rgba(0,0,0,0.1)]">操作</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.report_id} className="border-b group hover:bg-gray-50 transition-colors">
                  <td className="px-3 py-2.5 sticky left-0 z-10 bg-white group-hover:bg-gray-50 transition-colors">
                    <input type="checkbox" checked={selected.has(r.report_id)}
                      onChange={() => toggleOne(r.report_id)} className="rounded" />
                  </td>
                  {visibleColumns.map((col, i) => (
                    <td key={col.key}
                      title={String(r[col.key] ?? "")}
                      className={`px-3 py-2.5 whitespace-nowrap text-gray-600 max-w-[240px] truncate ${i === 0 ? "sticky left-10 z-10 bg-white group-hover:bg-gray-50 transition-colors shadow-[2px_0_5px_-2px_rgba(0,0,0,0.1)]" : ""}`}>
                      {col.render ? col.render(r[col.key], r) : (r[col.key] ?? "--")}
                    </td>
                  ))}
                  <td className="px-3 py-2.5 whitespace-nowrap text-center sticky right-0 z-10 bg-white group-hover:bg-gray-50 transition-colors shadow-[-2px_0_5px_-2px_rgba(0,0,0,0.1)]">
                    <div className="flex items-center justify-center gap-1">
                      <button onClick={() => navigate(`/report/${r.report_id}`)}
                        className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded" title="查看">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                      </button>
                      <button onClick={() => setEditReport(r)}
                        className="p-1.5 text-gray-500 hover:text-purple-600 hover:bg-purple-50 rounded" title="编辑">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                      <button
                        onClick={() => handlePush(r.report_id)}
                        disabled={pushingId === r.report_id}
                        className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-50 rounded disabled:opacity-40"
                        title="推送到知识库"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                        </svg>
                      </button>
                      {/* More dropdown trigger */}
                      <button
                        ref={(el) => { if (el) moreBtnRefs.current.set(r.report_id, el); }}
                        onClick={() => openMore(r.report_id)}
                        className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
                        title="更多"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* "More" dropdown portal */}
      {moreOpenId && (() => {
        const r = reports.find((x) => x.report_id === moreOpenId);
        if (!r) return null;
        return createPortal(
          <div
            ref={moreRef}
            className="fixed w-36 bg-white border rounded-lg shadow-xl z-[9999] py-1"
            style={{ top: morePos.top, left: morePos.left }}
          >
            <button
              onClick={() => { setMoreOpenId(null); navigate("/new", { state: { regenerateId: r.report_id, meta: r } }); }}
              className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
            >
              <svg className="w-4 h-4 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              智能更新
            </button>
            <a
              href={getPdfDownloadUrl(r.report_id)}
              download
              onClick={() => setMoreOpenId(null)}
              className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
            >
              <svg className="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              下载 PDF
            </a>
            <button
              onClick={() => { setMoreOpenId(null); setConfirmDelete(r.report_id); }}
              className="w-full text-left px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              删除
            </button>
          </div>,
          document.body,
        );
      })()}

      {/* Pagination */}
      {totalRecords > 0 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <div className="flex items-center gap-2">
            <span>每页</span>
            <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}
              className="border rounded px-2 py-1 text-sm">
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <span>条</span>
            <span className="ml-3">共 {totalRecords} 条记录</span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}
              className="px-3 py-1 border rounded hover:bg-gray-50 disabled:opacity-30">上一页</button>
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              let p: number;
              if (totalPages <= 7) p = i + 1;
              else if (page <= 4) p = i + 1;
              else if (page >= totalPages - 3) p = totalPages - 6 + i;
              else p = page - 3 + i;
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={`px-3 py-1 border rounded ${p === page ? "bg-blue-600 text-white border-blue-600" : "hover:bg-gray-50"}`}>
                  {p}
                </button>
              );
            })}
            <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page >= totalPages}
              className="px-3 py-1 border rounded hover:bg-gray-50 disabled:opacity-30">下一页</button>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="font-bold text-lg mb-2">确认删除</h3>
            <p className="text-gray-600 text-sm mb-4">确定要删除这份报告吗？此操作不可撤销。</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmDelete(null)}
                className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50">取消</button>
              <button onClick={() => handleDelete(confirmDelete)}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700">删除</button>
            </div>
          </div>
        </div>
      )}

      {/* Batch delete confirmation modal */}
      {confirmBatchDelete && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="font-bold text-lg mb-2">确认批量删除</h3>
            <p className="text-gray-600 text-sm mb-4">确定要删除选中的 {selected.size} 份报告吗？此操作不可撤销。</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setConfirmBatchDelete(false)}
                className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50">取消</button>
              <button onClick={handleBatchDelete}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700">删除 {selected.size} 份</button>
            </div>
          </div>
        </div>
      )}

      {/* Batch push modal */}
      {showBatchPush && (
        <BatchPushModal
          reports={reports.filter((r) => selected.has(r.report_id))}
          onClose={() => setShowBatchPush(false)}
          onComplete={() => { setShowBatchPush(false); setSelected(new Set()); fetchReports(); }}
        />
      )}

      {/* Edit report modal */}
      {editReport && (
        <EditReportModal
          report={editReport}
          onClose={() => setEditReport(null)}
          onSaved={() => { setEditReport(null); fetchReports(); }}
        />
      )}

      {/* Rating confirm modal */}
      {ratingConfirmReport && (
        <RatingConfirmModal
          reportId={ratingConfirmReport.report_id}
          currentRating={ratingConfirmReport.feasibility_rating || null}
          pendingChange={ratingConfirmReport.pending_rating_change || null}
          onClose={() => setRatingConfirmReport(null)}
          onConfirm={() => { setRatingConfirmReport(null); fetchReports(); }}
        />
      )}
    </div>
  );
}
