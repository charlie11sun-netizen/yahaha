"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { isActiveTask } from "./create-progress";
import { api, ApiError, openTaskEventStream } from "@/lib/api";
import type { Task, TaskListResponse } from "@/lib/types";

type StreamState = "idle" | "connecting" | "connected" | "reconnecting";

function updateTaskListCache(
  current: TaskListResponse | undefined,
  task: Task,
): TaskListResponse | undefined {
  if (!current) return current;
  return {
    ...current,
    items: current.items.map((item) => (item.id === task.id ? { ...item, ...task } : item)),
  };
}

async function consumeTaskEventStream(
  response: Response,
  onTask: (task: Task) => void,
  onDeleted: () => void,
): Promise<boolean> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) return false;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");

      let event = "message";
      const data: string[] = [];
      frame.split("\n").forEach((line) => {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      });
      if (event === "task" && data.length) {
        const task = JSON.parse(data.join("\n")) as Task;
        onTask(task);
        if (!isActiveTask(task.status)) return true;
      } else if (event === "deleted") {
        onDeleted();
        return true;
      } else if (event === "unavailable") {
        throw new ApiError(503, "Task event stream unavailable");
      }
    }
  }
}

export function useCreateTaskQuery(taskId: string | null) {
  const queryClient = useQueryClient();
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const query = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.task(taskId as string),
    enabled: !!taskId,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && (error.status === 404 || error.status === 403)) && failureCount < 3,
    refetchInterval: (query) => {
      const err = query.state.error;
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) return false;
      if (err) return 10000;
      const status = query.state.data?.status;
      if (!status) return 30000;
      return isActiveTask(status) ? 30000 : false;
    },
  });
  const isMissing = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403);

  useEffect(() => {
    if (!taskId || isMissing) {
      setStreamState("idle");
      return;
    }
    const controller = new AbortController();
    let disposed = false;

    const applyTask = (task: Task) => {
      queryClient.setQueryData(["task", taskId], task);
      queryClient.setQueryData<TaskListResponse | undefined>(["tasks"], (current) =>
        updateTaskListCache(current, task),
      );
    };
    const removeTask = () => {
      queryClient.removeQueries({ queryKey: ["task", taskId], exact: true });
      queryClient.setQueryData<TaskListResponse | undefined>(["tasks"], (current) =>
        current ? { ...current, items: current.items.filter((item) => item.id !== taskId) } : current,
      );
    };

    const connect = async () => {
      let retryMs = 1000;
      setStreamState("connecting");
      while (!disposed) {
        try {
          const response = await openTaskEventStream(taskId, controller.signal);
          if (disposed) return;
          setStreamState("connected");
          const terminal = await consumeTaskEventStream(response, applyTask, removeTask);
          if (disposed) return;
          if (terminal) {
            setStreamState("idle");
            return;
          }
        } catch (error) {
          if (disposed || controller.signal.aborted) return;
          if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
            void queryClient.invalidateQueries({ queryKey: ["task", taskId], exact: true });
            return;
          }
        }
        setStreamState("reconnecting");
        void queryClient.invalidateQueries({ queryKey: ["task", taskId], exact: true });
        await new Promise((resolve) => window.setTimeout(resolve, retryMs));
        retryMs = Math.min(retryMs * 2, 15000);
      }
    };

    void connect();
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [isMissing, queryClient, taskId]);

  return {
    ...query,
    isMissing,
    streamState,
  };
}

export function useGeneratedTaskAssetsQuery(taskId: string | null, task?: Task) {
  return useQuery({
    queryKey: ["task-generated-assets", taskId],
    queryFn: () => api.generatedTaskAssets(taskId as string),
    enabled: Boolean(taskId && task && !task.game),
    refetchInterval: (query) => {
      if (query.state.data?.items.length) return false;
      return isActiveTask(task?.status) ? 3000 : false;
    },
    staleTime: 60000,
  });
}

export function useCreateTasksQuery(enabled: boolean) {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: api.tasks,
    enabled,
    refetchInterval: enabled ? 30000 : false,
  });
}
