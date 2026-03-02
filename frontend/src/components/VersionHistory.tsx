import { useState, useEffect } from "react";
import { listVersions, getVersion, restoreVersion } from "../api/client";

interface Props {
  reportId: string;
  onRestore?: () => void;
}

interface Version {
  version_id: string;
  version_number: number;
  created_at: string;
  created_by: string | null;
  reason: string;
  content_size: number;
}

export default function VersionHistory({ reportId, onRestore }: Props) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<any | null>(null);
  const [viewingContent, setViewingContent] = useState(false);
  const [restoring, setRestoring] = useState(false);

  useEffect(() => {
    loadVersions();
  }, [reportId]);

  const loadVersions = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listVersions(reportId);
      setVersions(data.versions);
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleViewVersion = async (versionId: string) => {
    try {
      const version = await getVersion(reportId, versionId);
      setSelectedVersion(version);
      setViewingContent(true);
    } catch (e: any) {
      alert("加载版本失败: " + e.message);
    }
  };

  const handleRestore = async (versionId: string, versionNumber: number) => {
    const ok = window.confirm(
      `确定要恢复到版本 ${versionNumber} 吗？当前版本将被保存为新版本。`
    );
    if (!ok) return;

    setRestoring(true);
    try {
      await restoreVersion(reportId, versionId);
      alert("版本恢复成功！");
      setViewingContent(false);
      setSelectedVersion(null);
      loadVersions();
      onRestore?.();
    } catch (e: any) {
      alert("恢复失败: " + e.message);
    }
    setRestoring(false);
  };

  const formatDate = (iso: string) => {
    if (!iso) return "--";
    return iso.slice(0, 19).replace("T", " ");
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const getReasonLabel = (reason: string) => {
    const labels: Record<string, string> = {
      before_regeneration: "重新生成前备份",
      before_restore: "恢复前备份",
      manual_save: "手动保存",
      auto_backup: "自动备份",
    };
    return labels[reason] || reason;
  };

  if (loading) {
    return <div className="text-center py-8 text-gray-400">加载中...</div>;
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        加载失败: {error}
      </div>
    );
  }

  if (versions.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400">
        暂无历史版本
      </div>
    );
  }

  if (viewingContent && selectedVersion) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <button
            onClick={() => { setViewingContent(false); setSelectedVersion(null); }}
            className="text-sm text-gray-500 hover:text-blue-600 flex items-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            返回版本列表
          </button>
          <button
            onClick={() => handleRestore(selectedVersion.version_id, selectedVersion.version_number)}
            disabled={restoring}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {restoring ? "恢复中..." : "恢复此版本"}
          </button>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <div className="mb-4 pb-4 border-b">
            <h3 className="font-bold text-lg">版本 {selectedVersion.version_number}</h3>
            <div className="text-sm text-gray-500 mt-1">
              <span>{formatDate(selectedVersion.created_at)}</span>
              {selectedVersion.created_by && <span className="ml-3">创建者: {selectedVersion.created_by}</span>}
              <span className="ml-3">{getReasonLabel(selectedVersion.reason)}</span>
            </div>
          </div>
          <div className="prose max-w-none">
            <pre className="whitespace-pre-wrap text-sm bg-gray-50 p-4 rounded">
              {selectedVersion.content}
            </pre>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-sm text-gray-500 mb-4">
        共 {versions.length} 个历史版本
      </div>
      {versions.map((v) => (
        <div
          key={v.version_id}
          className="bg-white border rounded-lg p-4 hover:shadow-md transition"
        >
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <span className="font-bold text-lg text-blue-600">
                  版本 {v.version_number}
                </span>
                <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
                  {getReasonLabel(v.reason)}
                </span>
              </div>
              <div className="text-sm text-gray-500 mt-1">
                <span>{formatDate(v.created_at)}</span>
                {v.created_by && <span className="ml-3">创建者: {v.created_by}</span>}
                <span className="ml-3">大小: {formatSize(v.content_size)}</span>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => handleViewVersion(v.version_id)}
                className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
              >
                查看
              </button>
              <button
                onClick={() => handleRestore(v.version_id, v.version_number)}
                disabled={restoring}
                className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                恢复
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
