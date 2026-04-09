import { useState, useEffect, useRef } from "react";
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

  const eventSourcesRef = useRef<Map<string, EventSource>>(new Map());

  useEffect(() => {
    // Create SSE connection for each task
    taskIds.forEach((taskId) => {
      if (eventSourcesRef.current.has(taskId)) return;

      const es = new EventSource(`/api/tasks/${taskId}/stream`);
      eventSourcesRef.current.set(taskId, es);

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setTasks((prev) =>
            prev.map((task) =>
              task.taskId === taskId
                ? {
                    ...task,
                    progress: data.progress?.step || task.progress,
                    message: data.progress?.message || task.message,
                    done: data.done || task.done,
                    error: data.error || task.error,
                    reportId: data.report_id || task.reportId,
                  }
                : task
            )
          );
        } catch (e) {
          console.error("Failed to parse SSE data:", e);
        }
      };

      es.onerror = () => {
        es.close();
        eventSourcesRef.current.delete(taskId);
      };
    });

    // Cleanup on unmount
    return () => {
      eventSourcesRef.current.forEach((es) => es.close());
      eventSourcesRef.current.clear();
    };
  }, [taskIds]);

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
