import { useState } from "react";
import { updateReportMeta } from "../api/client";
import type { ReportMeta } from "../types";

// System fields that cannot be edited
const PROTECTED_KEYS = new Set([
  "report_id", "bd_code", "status", "score", "rating",
  "created_at", "file_size", "owner", "push_records",
  "push_status", "push_info", "attachments",
]);

// Editable fields with labels
const EDITABLE_FIELDS: { key: string; label: string; textarea?: boolean }[] = [
  { key: "company_name", label: "标的主体" },
  { key: "project_name", label: "标的项目" },
  { key: "industry", label: "行业" },
  { key: "province", label: "省" },
  { key: "city", label: "市" },
  { key: "district", label: "区" },
  { key: "is_listed", label: "上市情况" },
  { key: "stock_code", label: "上市编号" },
  { key: "revenue", label: "营业收入" },
  { key: "revenue_yuan", label: "营业收入（元）" },
  { key: "net_profit", label: "净利润" },
  { key: "net_profit_yuan", label: "净利润（元）" },
  { key: "valuation_yuan", label: "估值（元）" },
  { key: "valuation_date", label: "估值日期" },
  { key: "website", label: "官网地址" },
  { key: "industry_tags", label: "行业标签" },
  { key: "referral_status", label: "推介情况", textarea: true },
  { key: "is_traded", label: "是否已交易" },
  { key: "dept_primary", label: "负责人主属部门" },
  { key: "dept_owner", label: "归属部门" },
  { key: "description", label: "标的描述", textarea: true },
  { key: "company_intro", label: "标的主体公司简介", textarea: true },
  { key: "remarks", label: "备注", textarea: true },
];

interface Props {
  report: ReportMeta;
  onClose: () => void;
  onSaved: () => void;
}

export default function EditReportModal({ report, onClose, onSaved }: Props) {
  const [form, setForm] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of EDITABLE_FIELDS) {
      init[f.key] = report[f.key] != null ? String(report[f.key]) : "";
    }
    return init;
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    setError("");
    setSaving(true);
    try {
      // Only send changed fields
      const updates: Record<string, string | null> = {};
      for (const f of EDITABLE_FIELDS) {
        const oldVal = report[f.key] != null ? String(report[f.key]) : "";
        if (form[f.key] !== oldVal) {
          updates[f.key] = form[f.key] || null;
        }
      }
      if (Object.keys(updates).length === 0) {
        onClose();
        return;
      }
      await updateReportMeta(report.report_id, updates);
      onSaved();
    } catch (e: any) {
      setError(e.message);
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
        <h3 className="font-bold text-lg mb-1">编辑标的信息</h3>
        <p className="text-xs text-gray-400 mb-4">标的编码: {report.bd_code}</p>

        {error && (
          <div className="bg-red-50 text-red-600 text-sm rounded-lg p-3 mb-3">{error}</div>
        )}

        <div className="flex-1 overflow-y-auto pr-2">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {EDITABLE_FIELDS.map((f) => (
              <div key={f.key} className={f.textarea ? "md:col-span-2" : ""}>
                <label className="block text-sm text-gray-600 mb-1">{f.label}</label>
                {f.textarea ? (
                  <textarea
                    value={form[f.key]}
                    onChange={(e) => setForm((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    rows={2}
                    className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                  />
                ) : (
                  <input
                    type="text"
                    value={form[f.key]}
                    onChange={(e) => setForm((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-4 border-t mt-4">
          <button onClick={onClose} className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50">
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
