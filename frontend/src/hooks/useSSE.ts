import { useEffect, useRef, useState } from "react";
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
        es.close();
      } catch {
        // Connection loss/timeout: keep task alive and rely on intake task polling.
        // Do not mark done here, otherwise long-running intake tasks appear "suddenly completed".
        setState((prev) => ({
          ...prev,
          logs: prev.logs.includes("SSE连接中断，已切换到轮询状态")
            ? prev.logs
            : [...prev.logs, "SSE连接中断，已切换到轮询状态"],
        }));
      }
    });

    return () => {
      es.close();
    };
  }, [taskId]);

  return state;
}
