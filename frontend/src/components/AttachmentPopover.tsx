import { useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  listAttachments,
  deleteAttachment,
  uploadReportAttachments,
} from "../api/client";
import type { AttachmentInfo } from "../types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

interface Props {
  reportId: string;
  initialCount: number;
  onUpdate?: () => void;
}

export default function AttachmentPopover({ reportId, initialCount, onUpdate }: Props) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<AttachmentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });

  // Calculate popover position based on button rect
  const updatePos = useCallback(() => {
    if (!btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    setPos({ top: rect.bottom + 4, left: rect.left });
  }, []);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        btnRef.current && !btnRef.current.contains(target) &&
        popoverRef.current && !popoverRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Reposition on scroll/resize
  useEffect(() => {
    if (!open) return;
    updatePos();
    window.addEventListener("scroll", updatePos, true);
    window.addEventListener("resize", updatePos);
    return () => {
      window.removeEventListener("scroll", updatePos, true);
      window.removeEventListener("resize", updatePos);
    };
  }, [open, updatePos]);

  const fetchFiles = async () => {
    setLoading(true);
    try {
      const data = await listAttachments(reportId);
      setFiles(data);
    } catch {
      setFiles([]);
    }
    setLoading(false);
  };

  const handleOpen = () => {
    if (!open) {
      updatePos();
      fetchFiles();
    }
    setOpen(!open);
  };

  const handleDelete = async (filename: string) => {
    try {
      await deleteAttachment(reportId, filename);
      fetchFiles();
      onUpdate?.();
    } catch (e: any) {
      alert("删除失败: " + e.message);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    try {
      await uploadReportAttachments(reportId, Array.from(fileList));
      fetchFiles();
      onUpdate?.();
    } catch (err: any) {
      alert("上传失败: " + err.message);
    }
    setUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <>
      <button
        ref={btnRef}
        onClick={handleOpen}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-600 hover:bg-gray-200"
        title="查看附件"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
        </svg>
        {initialCount}
      </button>

      {open && createPortal(
        <div
          ref={popoverRef}
          className="fixed w-72 bg-white border rounded-lg shadow-xl z-[9999]"
          style={{ top: pos.top, left: pos.left }}
        >
          <div className="px-3 py-2 border-b flex items-center justify-between">
            <span className="text-sm font-medium">附件列表</span>
            <label className={`text-xs text-blue-600 hover:underline cursor-pointer ${uploading ? "opacity-50 pointer-events-none" : ""}`}>
              {uploading ? "上传中..." : "+ 上传"}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.md,.txt,.docx,.pptx"
                className="hidden"
                onChange={handleUpload}
                disabled={uploading}
              />
            </label>
          </div>
          <div className="max-h-48 overflow-y-auto">
            {loading ? (
              <div className="px-3 py-4 text-center text-gray-400 text-sm">加载中...</div>
            ) : files.length === 0 ? (
              <div className="px-3 py-4 text-center text-gray-400 text-sm">无附件</div>
            ) : (
              files.map((f) => (
                <div key={f.filename} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 text-sm group">
                  <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="flex-1 truncate" title={f.filename}>{f.filename}</span>
                  <span className="text-xs text-gray-400 flex-shrink-0">{formatSize(f.size)}</span>
                  <button
                    onClick={() => handleDelete(f.filename)}
                    className="p-1 text-gray-400 hover:text-red-600 opacity-0 group-hover:opacity-100"
                    title="删除"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
