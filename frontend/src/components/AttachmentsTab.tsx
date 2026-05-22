import { useState, useEffect } from "react";
import { downloadAttachmentFile, listAttachments } from "../api/client";
import type { AttachmentInfo } from "../types";

interface AttachmentsTabProps {
  reportId: string;
}

export default function AttachmentsTab({ reportId }: AttachmentsTabProps) {
  const [attachments, setAttachments] = useState<AttachmentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    loadAttachments();
  }, [reportId]);

  const loadAttachments = async () => {
    setLoading(true);
    setError("");

    try {
      const files = await listAttachments(reportId);
      setAttachments(files || []);
    } catch (err: any) {
      setError(err.message || "加载附件失败");
    } finally {
      setLoading(false);
    }
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const getFileIcon = (filename: string): string => {
    const ext = filename.toLowerCase().split(".").pop();
    switch (ext) {
      case "pdf":
        return "📄";
      case "doc":
      case "docx":
        return "📝";
      case "xls":
      case "xlsx":
        return "📊";
      case "ppt":
      case "pptx":
        return "📽️";
      case "jpg":
      case "jpeg":
      case "png":
      case "gif":
        return "🖼️";
      case "zip":
      case "rar":
        return "📦";
      default:
        return "📎";
    }
  };

  const handleDownload = async (attachment: AttachmentInfo) => {
    setDownloading(attachment.filename);
    try {
      const blob = await downloadAttachmentFile(reportId, attachment.filename);
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = attachment.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (err: any) {
      setError(err.message || "下载附件失败");
    } finally {
      setDownloading((current) => (current === attachment.filename ? null : current));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400">
        加载附件中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        {error}
      </div>
    );
  }

  if (attachments.length === 0) {
    return (
      <div className="text-center py-20 text-gray-400">
        <div className="text-4xl mb-4">📎</div>
        <div>暂无附件</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          附件列表 <span className="text-sm font-normal text-gray-400">({attachments.length} 个文件)</span>
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {attachments.map((attachment, idx) => (
          <div
            key={idx}
            className="border rounded-lg p-4 hover:shadow-md transition cursor-pointer"
            onClick={() => handleDownload(attachment)}
          >
            <div className="flex items-start gap-3">
              <div className="text-3xl">{getFileIcon(attachment.filename)}</div>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate" title={attachment.filename}>
                  {attachment.filename}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {formatSize(attachment.size)}{downloading === attachment.filename ? " · 下载中..." : ""}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
