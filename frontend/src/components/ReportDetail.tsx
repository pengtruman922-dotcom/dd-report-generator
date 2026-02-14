import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getReport, getDownloadUrl, getChunks } from "../api/client";
import ReportViewer from "./ReportViewer";
import ChunkEditor from "./ChunkEditor";

type Tab = "report" | "chunks";

export default function ReportDetail() {
  const { reportId } = useParams<{ reportId: string }>();
  const navigate = useNavigate();
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("report");
  const [hasChunks, setHasChunks] = useState(false);

  useEffect(() => {
    if (!reportId) return;
    setLoading(true);
    Promise.all([
      getReport(reportId),
      getChunks(reportId).then((c) => c.length > 0).catch(() => false),
    ])
      .then(([data, chunksExist]) => {
        setContent(data.content);
        setHasChunks(chunksExist);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [reportId]);

  const handleCopy = () => {
    if (content) navigator.clipboard.writeText(content);
  };

  const handlePrint = () => window.print();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400">
        加载报告中...
      </div>
    );
  }

  if (error || !content) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        加载失败: {error || "报告不存在"}
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
          <button
            onClick={handleCopy}
            className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
          >
            复制内容
          </button>
          <button
            onClick={handlePrint}
            className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
          >
            打印
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b">
        <button
          onClick={() => setTab("report")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
            tab === "report"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          报告内容
        </button>
        <button
          onClick={() => { setTab("chunks"); setHasChunks(true); }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
            tab === "chunks"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Chunks & 索引
          {hasChunks && (
            <span className="ml-1.5 inline-block w-2 h-2 bg-green-400 rounded-full" />
          )}
        </button>
      </div>

      {tab === "report" && <ReportViewer content={content} />}
      {tab === "chunks" && <ChunkEditor reportId={reportId!} />}
    </div>
  );
}
