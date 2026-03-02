import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { updateReportContent } from "../api/client";

interface Props {
  content: string;
  reportId?: string;
  onContentUpdate?: (newContent: string) => void;
}

export default function ReportViewer({ content, reportId, onContentUpdate }: Props) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(content);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!reportId) return;
    setSaving(true);
    setError(null);
    try {
      await updateReportContent(reportId, editContent);
      onContentUpdate?.(editContent);
      setIsEditing(false);
    } catch (e: any) {
      setError(e.message);
    }
    setSaving(false);
  };

  const handleCancel = () => {
    setEditContent(content);
    setIsEditing(false);
    setError(null);
  };

  if (isEditing) {
    return (
      <div className="space-y-3">
        {error && (
          <div className="bg-red-50 text-red-700 p-3 rounded-lg text-sm">
            保存失败: {error}
          </div>
        )}
        <div className="flex items-center justify-between bg-blue-50 border border-blue-200 rounded-lg px-4 py-2">
          <span className="text-sm text-blue-700 font-medium">编辑模式</span>
          <div className="flex gap-2">
            <button
              onClick={handleCancel}
              disabled={saving}
              className="px-3 py-1 text-sm border rounded hover:bg-white disabled:opacity-50"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "保存中..." : "保存"}
            </button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">Markdown 源码</label>
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="w-full h-[600px] p-4 border rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 resize-none"
              spellCheck={false}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">实时预览</label>
            <div className="h-[600px] overflow-y-auto bg-white rounded-lg shadow p-6 border report-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{editContent}</ReactMarkdown>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {reportId && (
        <div className="flex justify-end">
          <button
            onClick={() => setIsEditing(true)}
            className="px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
            编辑报告
          </button>
        </div>
      )}
      <div className="bg-white rounded-lg shadow p-6 report-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </div>
  );
}
