import { useLocation } from "react-router-dom";
import IntakeAgent from "./IntakeAgent";
import type { ReportMeta } from "../types";

interface RegenerateState {
  regenerateId: string;
  meta: ReportMeta;
}

export default function HomePage() {
  const location = useLocation();
  const regenState = location.state as RegenerateState | null;
  const companyLabel =
    regenState?.meta?.project_name || regenState?.meta?.company_name || regenState?.meta?.bd_code || "";

  return (
    <div className="space-y-6">
      {regenState && (
        <section className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-3">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-orange-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            <div className="text-sm text-orange-800">
              <div className="font-medium">智能更新模式</div>
              <div className="mt-1">
                当前准备更新 <strong>{companyLabel}</strong>。请在下方粘贴最新沟通记录、上传附件或补充链接，让智能录入自动识别更新信息。
              </div>
            </div>
          </div>
        </section>
      )}

      <section className="bg-white rounded-lg shadow p-5">
        <div className="mb-4">
          <h1 className="font-bold text-xl text-gray-900">智能录入</h1>
        </div>
        <IntakeAgent />
      </section>
    </div>
  );
}
