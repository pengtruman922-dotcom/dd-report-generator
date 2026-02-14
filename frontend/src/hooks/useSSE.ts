import { useEffect, useRef, useState, useCallback } from "react";
import type { ProgressEvent, CompleteEvent, ErrorEvent } from "../types";

interface SSEState {
  progress: ProgressEvent | null;
  logs: string[];
  reportId: string | null;
  error: string | null;
  done: boolean;
}

export function useSSE(taskId: string | null) {
  const [state, setState] = useState<SSEState>({
    progress: null,
    logs: [],
    reportId: null,
    error: null,
    done: false,
  });
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!taskId) return;

    // Reset state
    setState({ progress: null, logs: [], reportId: null, error: null, done: false });

    const es = new EventSource(`/api/report/progress/${taskId}`);
    esRef.current = es;

    es.addEventListener("progress", (e) => {
      const data: ProgressEvent = JSON.parse(e.data);
      setState((prev) => ({
        ...prev,
        progress: data,
        logs: [...prev.logs, data.message],
      }));
    });

    es.addEventListener("complete", (e) => {
      const data: CompleteEvent = JSON.parse(e.data);
      setState((prev) => ({
        ...prev,
        reportId: data.report_id,
        done: true,
        logs: [...prev.logs, "报告生成完成!"],
      }));
      es.close();
    });

    es.addEventListener("error", (e) => {
      // SSE error event — could be a server-sent error or connection error
      try {
        const data: ErrorEvent = JSON.parse((e as MessageEvent).data);
        setState((prev) => ({
          ...prev,
          error: data.error,
          done: true,
          logs: [...prev.logs, `错误: ${data.error}`],
        }));
      } catch {
        // connection error
        setState((prev) => ({
          ...prev,
          error: "SSE connection lost",
          done: true,
        }));
      }
      es.close();
    });

    return () => {
      es.close();
    };
  }, [taskId]);

  return state;
}
