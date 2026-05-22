import { useState, useEffect } from "react";
import { confirmRatingChange } from "../api/client";

interface RatingConfirmModalProps {
  reportId: string;
  currentRating: string | null;
  pendingChange: string | null;
  onClose: () => void;
  onConfirm: () => void;
}

export default function RatingConfirmModal({
  reportId,
  currentRating,
  pendingChange,
  onClose,
  onConfirm,
}: RatingConfirmModalProps) {
  const [pending, setPending] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (pendingChange) {
      try {
        setPending(JSON.parse(pendingChange));
      } catch (e) {
        setError("无法解析待确认的评级数据");
      }
    }
  }, [pendingChange]);

  if (!pending) {
    return null;
  }

  const handleAction = async (action: "accept" | "reject") => {
    setLoading(true);
    setError("");

    try {
      await confirmRatingChange(reportId, action, "");
      onConfirm();
      onClose();
    } catch (err: any) {
      setError(err.message || "操作失败");
    } finally {
      setLoading(false);
    }
  };

  const ratingColors: Record<string, string> = {
    A: "bg-green-100 text-green-700 border-green-300",
    B: "bg-blue-100 text-blue-700 border-blue-300",
    C: "bg-yellow-100 text-yellow-700 border-yellow-300",
    D: "bg-orange-100 text-orange-700 border-orange-300",
    E: "bg-red-100 text-red-700 border-red-300",
  };

  const currentColor = ratingColors[currentRating || ""] || "bg-gray-100 text-gray-500 border-gray-300";
  const newColor = ratingColors[pending.rating] || "bg-gray-100 text-gray-500 border-gray-300";

  const dimensions = pending.dimensions || {};

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-xl font-semibold mb-4">确认评级变更</h2>

          {/* Rating Change */}
          <div className="mb-6 flex items-center gap-4">
            <div className="text-center">
              <div className="text-sm text-gray-500 mb-2">当前评级</div>
              <span className={`inline-block px-4 py-2 rounded text-lg font-bold border-2 ${currentColor}`}>
                {currentRating || "无"}
              </span>
            </div>
            <div className="text-2xl text-gray-400">→</div>
            <div className="text-center">
              <div className="text-sm text-gray-500 mb-2">新评级</div>
              <span className={`inline-block px-4 py-2 rounded text-lg font-bold border-2 ${newColor}`}>
                {pending.rating}
              </span>
            </div>
          </div>

          {/* Reasoning */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-700 mb-2">评级依据</h3>
            <p className="text-sm text-gray-600 bg-gray-50 p-3 rounded">
              {pending.reasoning || "无"}
            </p>
          </div>

          {/* Dimensions */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">四维度评估</h3>
            <div className="space-y-3">
              {/* Willingness */}
              <div className="border rounded p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-700">出售意愿</span>
                  <span className="text-sm font-semibold text-blue-600">
                    {dimensions.willingness?.level || "未知"}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{dimensions.willingness?.evidence || "无"}</p>
              </div>

              {/* Cooperation */}
              <div className="border rounded p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-700">配合度</span>
                  <span className="text-sm font-semibold text-blue-600">
                    {dimensions.cooperation?.level || "未知"}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{dimensions.cooperation?.evidence || "无"}</p>
              </div>

              {/* Conditions */}
              <div className="border rounded p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-700">客观条件</span>
                  <span className="text-sm font-semibold text-blue-600">
                    {dimensions.conditions?.level || "未知"}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{dimensions.conditions?.evidence || "无"}</p>
              </div>

              {/* Status */}
              <div className="border rounded p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-700">当前状态</span>
                  <span className="text-sm font-semibold text-blue-600">
                    {dimensions.status?.level || "未知"}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{dimensions.status?.evidence || "无"}</p>
              </div>
            </div>
          </div>

          {/* Key Factors */}
          {pending.key_factors && pending.key_factors.length > 0 && (
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">关键因素</h3>
              <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
                {pending.key_factors.map((factor: string, idx: number) => (
                  <li key={idx}>{factor}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-600">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 justify-end">
            <button
              onClick={onClose}
              disabled={loading}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
            >
              取消
            </button>
            <button
              onClick={() => handleAction("reject")}
              disabled={loading}
              className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded hover:bg-red-700 disabled:opacity-50"
            >
              驳回
            </button>
            <button
              onClick={() => handleAction("accept")}
              disabled={loading}
              className="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded hover:bg-green-700 disabled:opacity-50"
            >
              {loading ? "处理中..." : "确认"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
