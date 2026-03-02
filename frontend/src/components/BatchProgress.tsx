import { useState, useEffect } from "react";
import { useSSE } from "../hooks/useSSE";
import type { Company } from "../types";

interface Props {
  taskIds: string[];
  companies: Company[];
  onAllComplete?: () => void;
}

interface TaskProgress {
  taskId: string;
  company: Company;
  progress: number;
  message: string;
  done: boolean;
  error: string | null;
  reportId: string | null;
}

export default function BatchProgress({ taskIds, companies, onAllComplete }: Props) {
  const [tasks, setTasks] = useState<TaskProgress[]>(() =>
    taskIds.map((taskId, i) => ({
      taskId,
      company: companies[i] || { bd_code: taskId, company_name: "未知", project_name: "" },
      progress: 0,
      message: "等待开始...",
      done: false,
      error: null,
      reportId: null,
    }))
  );

  // Track SSE connections for each task
  const [sseStates, setSseStates] = useState<Record<string, any>>({});

  useEffect(() => {
    // Subscribe to SSE for each task
    const newStates: Record<string, any> = {};
    taskIds.forEach((taskId) => {
      const sse = useSSE(taskId);
      newStates[taskId] = sse;
    });
    setSseStates(newStates);
  }, [taskIds]);

  // Update task progress from SSE states
  useEffect(() => {
    setTasks((prev) =>
      prev.map((task) => {
        const sse = sseStates[task.taskId];
        if (!sse) return task;
        return {
          ...task,
          progress: sse.progress?.step || 0,
          message: sse.progress?.message || task.message,
          done: sse.done,
          error: sse.error,
          reportId: sse.reportId,
        };
      })
    );
  }, [sseStates]);

  // Check if all tasks are complete
  useEffect(() => {
    if (tasks.length > 0 && tasks.every((t) => t.done)) {
      onAllComplete?.();
    }
  }, [tasks, onAllComplete]);

  const completedCount = tasks.filter((t) => t.done).length;
  const errorCount = tasks.filter((t) => t.error).length;

  return (
    <div className="space-y-4">
      {/* Overall progress */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-blue-700">
            批量生成进度: {completedCount} / {tasks.length}
          </span>
          <span className="text-xs text-blue-600">
            {errorCount > 0 && `${errorCount} 个失败`}
          </span>
        </div>
        <div className="w-full bg-blue-200 rounded-full h-2">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
            style={{ width: `${(completedCount / tasks.length) * 100}%` }}
          />
        </div>
      </div>

      {/* Individual task progress */}
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {tasks.map((task) => (
          <div
            key={task.taskId}
            className={`border rounded-lg p-3 ${
              task.error
                ? "bg-red-50 border-red-200"
                : task.done
                  ? "bg-green-50 border-green-200"
                  : "bg-white border-gray-200"
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">
                    {task.company.project_name || task.company.company_name}
                  </span>
                  <span className="text-xs text-gray-500">
                    ({task.company.bd_code})
                  </span>
                </div>
                <div className="text-xs text-gray-600 mt-1">{task.message}</div>
              </div>
              <div className="flex-shrink-0 ml-3">
                {task.error ? (
                  <span className="text-red-600 text-xs">✗ 失败</span>
                ) : task.done ? (
                  <span className="text-green-600 text-xs">✓ 完成</span>
                ) : (
                  <span className="text-blue-600 text-xs animate-pulse">
                    步骤 {task.progress}/6
                  </span>
                )}
              </div>
            </div>
            {task.error && (
              <div className="mt-2 text-xs text-red-700 bg-red-100 rounded p-2">
                {task.error}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
