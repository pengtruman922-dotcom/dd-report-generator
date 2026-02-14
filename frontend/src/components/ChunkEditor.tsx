import { useState, useEffect } from "react";
import {
  getChunks,
  saveChunks,
  regenerateChunks,
  pushToFastGPT,
} from "../api/client";
import type { ReportChunk } from "../types";

interface Props {
  reportId: string;
}

export default function ChunkEditor({ reportId }: Props) {
  const [chunks, setChunks] = useState<ReportChunk[]>([]);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [message, setMessage] = useState("");
  const [newTag, setNewTag] = useState("");
  const [empty, setEmpty] = useState(false);

  useEffect(() => {
    setLoading(true);
    getChunks(reportId)
      .then((data) => {
        if (data.length === 0) {
          setEmpty(true);
        } else {
          setChunks(data);
          setEmpty(false);
        }
        setLoading(false);
      })
      .catch(() => {
        setEmpty(true);
        setLoading(false);
      });
  }, [reportId]);

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    try {
      await saveChunks(reportId, chunks);
      setMessage("保存成功");
    } catch (e: any) {
      setMessage("保存失败: " + e.message);
    }
    setSaving(false);
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    setMessage("");
    try {
      const data = await regenerateChunks(reportId);
      setChunks(data);
      setEmpty(false);
      setSelected(0);
      setMessage("重新生成完成");
    } catch (e: any) {
      setMessage("重新生成失败: " + e.message);
    }
    setRegenerating(false);
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

  const updateQ = (chunkIdx: number, value: string) => {
    setChunks((prev) =>
      prev.map((c, i) => (i === chunkIdx ? { ...c, q: value } : c)),
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
        <p className="text-gray-400 mb-4">暂无分块数据</p>
        <button
          onClick={handleRegenerate}
          disabled={regenerating}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {regenerating ? "生成中..." : "生成分块与索引"}
        </button>
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

  return (
    <div className="space-y-4">
      {/* Action bar */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "保存中..." : "保存修改"}
        </button>
        <button
          onClick={handleRegenerate}
          disabled={regenerating}
          className="px-4 py-2 bg-amber-500 text-white text-sm rounded hover:bg-amber-600 disabled:opacity-50"
        >
          {regenerating ? "生成中..." : "重新生成索引"}
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
        {/* Left sidebar: chunk tabs */}
        <div className="w-56 flex-shrink-0 space-y-1">
          {chunks.map((chunk, i) => (
            <button
              key={i}
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

        {/* Main content area */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Content editor */}
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">
              内容（q 字段）
            </label>
            <textarea
              value={current?.q || ""}
              onChange={(e) => updateQ(selected, e.target.value)}
              rows={12}
              className="w-full border rounded-lg px-3 py-2 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-300 resize-y"
            />
          </div>

          {/* Indexes */}
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-2">
              索引标签（{current?.indexes.length || 0} 个）
            </label>
            <div className="flex flex-wrap gap-2 mb-3">
              {current?.indexes.map((idx, j) => (
                <span
                  key={j}
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

            {/* Add new tag */}
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
