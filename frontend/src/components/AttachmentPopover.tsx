import { useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  listAttachments,
  deleteAttachment,
  downloadAttachmentFile,
  startAttachmentUpdate,
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
  onTaskCreated?: () => void;
}

export default function AttachmentPopover({ reportId, initialCount, onUpdate, onTaskCreated }: Props) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<AttachmentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [confirmUpdateOpen, setConfirmUpdateOpen] = useState(false);
  const [pendingUpdateFiles, setPendingUpdateFiles] = useState<string[]>([]);
  const [updateSelection, setUpdateSelection] = useState<string[]>([]);
  const [updateNote, setUpdateNote] = useState("");
  const [creatingUpdate, setCreatingUpdate] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });

  // Calculate popover position based on button rect
  const updatePos = useCallback(() => {
    if (!btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    const popoverWidth = 288; // w-72 = 18rem = 288px
    let left = rect.left;
    // Prevent overflow on the right edge
    if (left + popoverWidth > window.innerWidth - 8) {
      left = window.innerWidth - popoverWidth - 8;
    }
    if (left < 8) left = 8;
    setPos({ top: rect.bottom + 4, left });
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
      const result = await uploadReportAttachments(reportId, Array.from(fileList));
      await fetchFiles();
      onUpdate?.();
      const uploadedNames = (result.files || []).map((item) => item.filename).filter(Boolean);
      if (uploadedNames.length > 0) {
        setPendingUpdateFiles(uploadedNames);
        setUpdateSelection(uploadedNames);
        setUpdateNote("");
        setConfirmUpdateOpen(true);
      }
    } catch (err: any) {
      alert("上传失败: " + err.message);
    }
    setUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDownload = async (filename: string) => {
    setDownloading(filename);
    try {
      const blob = await downloadAttachmentFile(reportId, filename);
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (e: any) {
      alert("下载失败: " + e.message);
    } finally {
      setDownloading((current) => (current === filename ? null : current));
    }
  };

  const toggleUpdateFile = (filename: string) => {
    setUpdateSelection((prev) => (
      prev.includes(filename)
        ? prev.filter((item) => item !== filename)
        : [...prev, filename]
    ));
  };

  const handleCreateAttachmentUpdate = async () => {
    if (updateSelection.length === 0) {
      alert("请至少选择一个附件参与更新");
      return;
    }
    setCreatingUpdate(true);
    try {
      await startAttachmentUpdate(reportId, updateSelection, updateNote);
      setConfirmUpdateOpen(false);
      setPendingUpdateFiles([]);
      setUpdateSelection([]);
      setUpdateNote("");
      setOpen(false);
      onUpdate?.();
      onTaskCreated?.();
      alert("已创建附件更新任务");
    } catch (e: any) {
      alert("创建更新任务失败: " + e.message);
    } finally {
      setCreatingUpdate(false);
    }
  };

  const handleKeepAttachmentsOnly = () => {
    setConfirmUpdateOpen(false);
    setPendingUpdateFiles([]);
    setUpdateSelection([]);
    setUpdateNote("");
  };

  return (
    <>
      <button
        ref={btnRef}
        onClick={handleOpen}
        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ${
          initialCount > 0
            ? "bg-gray-100 text-gray-600 hover:bg-gray-200"
            : "border border-dashed border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100"
        }`}
        title={initialCount > 0 ? "查看附件" : "上传附件"}
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
        </svg>
        {initialCount > 0 ? initialCount : "上传"}
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
              <div className="px-4 py-6 text-center">
                <div className="text-sm text-gray-500">暂无附件</div>
                <div className="mt-1 text-xs text-gray-400">可上传 PDF / DOCX / PPTX / TXT / MD 附件</div>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs text-blue-600 hover:bg-blue-100"
                >
                  上传附件
                </button>
              </div>
            ) : (
              files.map((f) => (
              <div key={f.filename} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 text-sm group">
                  <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <button
                    onClick={() => handleDownload(f.filename)}
                    className="flex-1 truncate text-left text-blue-600 hover:underline"
                    title={`下载 ${f.filename}`}
                  >
                    {f.filename}
                  </button>
                  <span className="text-xs text-gray-400 flex-shrink-0">
                    {formatSize(f.size)}{downloading === f.filename ? " · 下载中..." : ""}
                  </span>
                  <button
                    onClick={() => handleDownload(f.filename)}
                    className="p-1 text-gray-400 hover:text-blue-600 opacity-0 group-hover:opacity-100"
                    title="下载"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a2 2 0 002 2h12a2 2 0 002-2v-1m-4-5l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                  </button>
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

      {confirmUpdateOpen && createPortal(
        <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/35 px-4">
          <div className="w-full max-w-lg rounded-xl bg-white shadow-2xl">
            <div className="border-b px-5 py-4">
              <div className="text-base font-semibold text-gray-900">附件已上传</div>
              <p className="mt-1 text-sm text-gray-500">
                是否基于这些新附件更新当前报告？本次更新不会联网调研，仅依据新附件和当前报告内容更新受影响章节，并在完成后重新评级和推送。
              </p>
            </div>

            <div className="space-y-4 px-5 py-4">
              <div>
                <div className="mb-2 text-sm font-medium text-gray-700">参与更新的附件</div>
                <div className="max-h-40 space-y-2 overflow-y-auto rounded-lg border bg-gray-50 p-3">
                  {pendingUpdateFiles.map((filename) => (
                    <label key={filename} className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={updateSelection.includes(filename)}
                        onChange={() => toggleUpdateFile(filename)}
                        className="rounded"
                      />
                      <span className="truncate">{filename}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <div className="mb-2 text-sm font-medium text-gray-700">更新备注（可选）</div>
                <textarea
                  value={updateNote}
                  onChange={(e) => setUpdateNote(e.target.value)}
                  rows={3}
                  placeholder="例如：重点更新财务数据和交易条款"
                  className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 border-t px-5 py-4">
              <button
                onClick={handleKeepAttachmentsOnly}
                disabled={creatingUpdate}
                className="rounded-lg border px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                仅保存附件
              </button>
              <button
                onClick={handleCreateAttachmentUpdate}
                disabled={creatingUpdate || updateSelection.length === 0}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {creatingUpdate ? "创建任务中..." : "保存并更新报告"}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
