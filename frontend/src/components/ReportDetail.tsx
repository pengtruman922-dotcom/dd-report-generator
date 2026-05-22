import { useState, useEffect } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { getDownloadUrl, getPdfDownloadUrl, getChunks } from "../api/client";
import ChunkEditor from "./ChunkEditor";
import IntakeLogs from "./IntakeLogs";
import AttachmentsTab from "./AttachmentsTab";

type Tab = "chunks" | "intake_logs" | "attachments";

export default function ReportDetail() {
  const { reportId } = useParams<{ reportId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(() => {
    const requestedTab = searchParams.get("tab");
    return requestedTab === "chunks" || requestedTab === "intake_logs" || requestedTab === "attachments"
      ? requestedTab
      : "chunks";
  });
  const [hasChunks, setHasChunks] = useState(false);
  const focusChunkId = searchParams.get("chunk") || undefined;

  useEffect(() => {
    const requestedTab = searchParams.get("tab");
    if (requestedTab === "chunks" || requestedTab === "intake_logs" || requestedTab === "attachments") {
      setTab(requestedTab);
    } else if (requestedTab === "report") {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("tab", "chunks");
      setSearchParams(nextParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleTabChange = (nextTab: Tab) => {
    setTab(nextTab);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("tab", nextTab);
    if (nextTab !== "chunks") nextParams.delete("chunk");
    setSearchParams(nextParams, { replace: true });
  };

  useEffect(() => {
    if (!reportId) return;
    setLoading(true);
    getChunks(reportId)
      .then((chunks) => {
        const chunksExist = chunks.length > 0;
        setHasChunks(chunksExist);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [reportId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400">
        加载报告中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        加载失败: {error}
        <button onClick={() => navigate("/reports")} className="ml-3 underline">
          返回列表
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <button
          onClick={() => navigate("/reports")}
          className="text-sm text-gray-500 hover:text-blue-600 flex items-center gap-1"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          返回报告列表
        </button>
        <div className="flex gap-3">
          <a
            href={getDownloadUrl(reportId!)}
            download
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
          >
            下载 .md
          </a>
          <a
            href={getPdfDownloadUrl(reportId!)}
            download
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
          >
            下载 PDF
          </a>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b">
        <button
          onClick={() => { handleTabChange("chunks"); setHasChunks(true); }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
            tab === "chunks"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Info / Tracking
          {hasChunks && (
            <span className="ml-1.5 inline-block w-2 h-2 bg-green-400 rounded-full" />
          )}
        </button>
        <button
          onClick={() => handleTabChange("intake_logs")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
            tab === "intake_logs"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          更新记录
        </button>
        <button
          onClick={() => handleTabChange("attachments")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
            tab === "attachments"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          附件
        </button>
      </div>

      {tab === "chunks" && <ChunkEditor reportId={reportId!} initialChunkId={focusChunkId} />}
      {tab === "intake_logs" && <IntakeLogs reportId={reportId!} />}
      {tab === "attachments" && <AttachmentsTab reportId={reportId!} />}
    </div>
  );
}
