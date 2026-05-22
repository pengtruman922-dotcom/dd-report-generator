import { useEffect, useState } from "react";
import {
  getChunks,
  saveChunks,
  pushToFastGPT,
} from "../api/client";
import type { ReportChunk } from "../types";

interface Props {
  reportId: string;
  initialChunkId?: string;
}

export default function ChunkEditor({ reportId, initialChunkId }: Props) {
  const [chunks, setChunks] = useState<ReportChunk[]>([]);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [message, setMessage] = useState("");
  const [newTag, setNewTag] = useState("");
  const [empty, setEmpty] = useState(false);

  useEffect(() => {
    loadChunks();
  }, [reportId, initialChunkId]);

  const loadChunks = async () => {
    setLoading(true);
    setMessage("");
    try {
      const data = await getChunks(reportId);
      if (data.length === 0) {
        setChunks([]);
        setEmpty(true);
      } else {
        setChunks(data);
        setEmpty(false);
        if (initialChunkId) {
          const normalizedChunkId = initialChunkId === "chunk7" ? "tracking" : initialChunkId;
          const targetIndex = data.findIndex((chunk) => chunk.chunk_id === normalizedChunkId);
          setSelected(targetIndex >= 0 ? targetIndex : 0);
        } else {
          setSelected(0);
        }
      }
    } catch {
      setChunks([]);
      setEmpty(true);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (!initialChunkId || chunks.length === 0) return;
    const normalizedChunkId = initialChunkId === "chunk7" ? "tracking" : initialChunkId;
    const targetIndex = chunks.findIndex((chunk) => chunk.chunk_id === normalizedChunkId);
    if (targetIndex >= 0 && targetIndex !== selected) {
      setSelected(targetIndex);
    }
  }, [chunks, initialChunkId, selected]);

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    try {
      await saveChunks(reportId, chunks);
      await loadChunks();
      setMessage("保存成功");
    } catch (e: any) {
      setMessage("保存失败: " + e.message);
    }
    setSaving(false);
  };

  const handlePush = async () => {
    setPushing(true);
    setMessage("");
    try {
      const result = await pushToFastGPT(reportId);
      setMessage(`已推送 ${result.uploaded}/${result.total} 条到知识库`);
    } catch (e: any) {
      setMessage("推送失败: " + e.message);
    }
    setPushing(false);
  };

  const removeIndex = (chunkIdx: number, tagIdx: number) => {
    setChunks((prev) =>
      prev.map((c, i) =>
        i === chunkIdx
          ? { ...c, indexes: c.indexes.filter((_, j) => j !== tagIdx) }
          : c,
      ),
    );
  };

  const addIndex = (chunkIdx: number) => {
    const tag = newTag.trim();
    if (!tag) return;
    setChunks((prev) =>
      prev.map((c, i) =>
        i === chunkIdx
          ? { ...c, indexes: [...c.indexes, { text: tag }] }
          : c,
      ),
    );
    setNewTag("");
  };

  const updateContent = (chunkIdx: number, value: string) => {
    setChunks((prev) =>
      prev.map((c, i) =>
        i === chunkIdx
          ? {
              ...c,
              q: value,
              content: value,
            }
          : c,
      ),
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-gray-400">
        加载分块数据中...
      </div>
    );
  }

  if (empty) {
    return (
      <div className="text-center py-10">
        <p className="text-gray-400 mb-1">暂无分块数据</p>
        <p className="text-xs text-gray-500">请先完成智能录入或写作流程。</p>
        {message && (
          <p
            className={`mt-3 text-sm ${message.includes("失败") ? "text-red-600" : "text-green-600"}`}
          >
            {message}
          </p>
        )}
      </div>
    );
  }

  const current = chunks[selected];
  const currentContent = current?.content || current?.q || "";
  const currentKind =
    current?.chunk_id === "tracking" ? "tracking"
      : current?.chunk_id === "info" ? "info"
      : "legacy";
  const kindLabel =
    currentKind === "tracking" ? "跟进动态块"
      : currentKind === "info" ? "标的信息块"
      : "历史内容块";
  const kindHint =
    currentKind === "tracking"
      ? "内部时间线，保留动态变化与历史值，不推送到 FastGPT。"
      : currentKind === "info"
        ? "对外检索主内容，只保留当前有效事实。"
        : "兼容旧结构的历史块内容。";

  return (
    <div className="space-y-4">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 flex items-center gap-2">
        <span className="text-blue-700 font-medium text-sm">📦 当前内容</span>
        <span className="text-blue-600 text-xs">当前内容来自 `report_chunks`，可直接编辑并保存。</span>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "保存中..." : "保存修改"}
        </button>
        <button
          onClick={handlePush}
          disabled={pushing}
          className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
        >
          {pushing ? "推送中..." : "推送到知识库"}
        </button>
        {message && (
          <span
            className={`text-sm ${message.includes("失败") ? "text-red-600" : "text-green-600"}`}
          >
            {message}
          </span>
        )}
      </div>

      <div className="flex gap-4">
        <div className="w-56 flex-shrink-0 space-y-1">
          {chunks.map((chunk, i) => (
            <button
              key={chunk.chunk_id || `${chunk.title}-${i}`}
              onClick={() => setSelected(i)}
              className={`w-full text-left px-3 py-2 rounded text-sm transition ${
                i === selected
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              <span className="font-medium">{chunk.title}</span>
              <span className="block text-xs opacity-70 mt-0.5">
                {chunk.indexes.length} 个索引
              </span>
            </button>
          ))}
        </div>

        <div className="flex-1 min-w-0 space-y-4">
          <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
            <div className="text-sm font-medium text-gray-800">{kindLabel}</div>
            <div className="mt-1 text-xs text-gray-500">{kindHint}</div>
          </div>

          {current?.summary && (
            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1">
                摘要
              </label>
              <div className="bg-gray-50 border rounded-lg px-3 py-2 text-sm text-gray-700 whitespace-pre-wrap">
                {current.summary}
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">
              内容
            </label>
            <textarea
              value={currentContent}
              onChange={(e) => updateContent(selected, e.target.value)}
              rows={12}
              className="w-full border rounded-lg px-3 py-2 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-300 resize-y"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-600 mb-2">
              索引标签（{current?.indexes.length || 0} 个）
            </label>
            <div className="flex flex-wrap gap-2 mb-3">
              {current?.indexes.map((idx, j) => (
                <span
                  key={`${idx.text}-${j}`}
                  className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-50 text-blue-700 text-sm rounded-full border border-blue-200"
                >
                  {idx.text}
                  <button
                    onClick={() => removeIndex(selected, j)}
                    className="text-blue-400 hover:text-red-500 ml-0.5"
                    title="删除"
                  >
                    <svg
                      className="w-3.5 h-3.5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </span>
              ))}
            </div>

            <div className="flex gap-2">
              <input
                type="text"
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addIndex(selected);
                  }
                }}
                placeholder="输入新标签..."
                className="flex-1 border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
              />
              <button
                onClick={() => addIndex(selected)}
                className="px-4 py-1.5 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
              >
                添加
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
