"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { isActiveTask } from "./create-progress";
import { api, ApiError, openTaskEventStream } from "@/lib/api";
import type { AgentLogEntry, AgentLogItem, Task, TaskListResponse } from "@/lib/types";

type StreamState = "idle" | "connecting" | "connected" | "reconnecting";

type TaskLogDelta = {
  cursor: number;
  step_id: string;
  agent_name: string;
  step: string;
  status: string;
  entry: AgentLogEntry;
};

type TaskEventDelta = {
  cursor: number;
  task: Task;
  logs: TaskLogDelta[];
  steps: TaskStepStatusPatch[];
};

type TaskStepStatusPatch = {
  step_id: string;
  agent_name: string;
  step: string;
  status: string;
  duration?: string | null;
};

type StreamProgress = { cursor: number; revision: number };

function streamProgressFor(progress: Map<string, StreamProgress>, taskId: string) {
  const existing = progress.get(taskId);
  if (existing) return existing;
  const created = { cursor: 0, revision: 0 };
  progress.set(taskId, created);
  return created;
}

function parseEventCursor(eventId: string) {
  const value = Number(eventId);
  return Number.isInteger(value) && value >= 0 ? value : null;
}

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

export function mergeTaskEventDelta(current: Task | undefined, delta: TaskEventDelta): Task {
  const logs = [...(current?.logs ?? [])];
  delta.logs.forEach((item) => {
    const index = logs.findIndex(
      (log) =>
        (log.step_id && log.step_id === item.step_id) ||
        (!log.step_id && log.agent_name === item.agent_name && log.step === item.step),
    );
    const existing = index >= 0 ? logs[index] : undefined;
    const entries = [...(existing?.entries ?? [])];
    const duplicate = entries.some(
      (entry) => item.entry.cursor != null && entry.cursor === item.entry.cursor,
    );
    if (!duplicate) entries.push(item.entry);
    const lines = duplicate ? [...(existing?.lines ?? [])] : [...(existing?.lines ?? []), item.entry.line];
    const next: AgentLogItem = {
      ...existing,
      step_id: item.step_id,
      agent_name: item.agent_name,
      step: item.step,
      status: item.status,
      message: item.entry.line,
      created_at: item.entry.created_at,
      duration: existing?.duration,
      lines,
      entries,
    };
    if (index >= 0) logs[index] = next;
    else logs.push(next);
  });
  (delta.steps ?? []).forEach((item) => {
    const index = logs.findIndex(
      (log) =>
        (log.step_id && log.step_id === item.step_id) ||
        (!log.step_id && log.agent_name === item.agent_name && log.step === item.step),
    );
    if (index < 0) return;
    logs[index] = {
      ...logs[index],
      status: item.status,
      duration: item.duration ?? logs[index].duration,
    };
  });
  return { ...current, ...delta.task, logs };
}

async function consumeTaskEventStream(
  response: Response,
  onTask: (task: Task, eventId: string) => boolean,
  onTaskDelta: (delta: TaskEventDelta, eventId: string) => boolean,
  onDeleted: (eventId: string) => boolean,
  onEventId: (eventId: string) => void,
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
      let eventId = "";
      const data: string[] = [];
      frame.split("\n").forEach((line) => {
        if (line.startsWith("id:")) eventId = line.slice(3).trim();
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      });
      if (event === "task" && data.length) {
        const task = JSON.parse(data.join("\n")) as Task;
        const applied = onTask(task, eventId);
        if (applied && eventId) onEventId(eventId);
        if (applied && !isActiveTask(task.status)) return true;
      } else if (event === "task_delta" && data.length) {
        const delta = JSON.parse(data.join("\n")) as TaskEventDelta;
        const applied = onTaskDelta(delta, eventId);
        if (applied && eventId) onEventId(eventId);
        if (applied && !isActiveTask(delta.task.status)) return true;
      } else if (event === "deleted") {
        const applied = onDeleted(eventId);
        if (applied && eventId) onEventId(eventId);
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
  const streamProgressRef = useRef(new Map<string, StreamProgress>());
  const query = useQuery({
    queryKey: ["task", taskId],
    queryFn: async () => {
      const id = taskId as string;
      const startedRevision = streamProgressFor(streamProgressRef.current, id).revision;
      const task = await api.task(id);
      const latestRevision = streamProgressFor(streamProgressRef.current, id).revision;
      if (latestRevision > startedRevision) {
        return queryClient.getQueryData<Task>(["task", id]) ?? task;
      }
      return task;
    },
    enabled: !!taskId,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && (error.status === 404 || error.status === 403)) && failureCount < 3,
    refetchInterval: (query) => {
      if (streamState === "connecting" || streamState === "connected") return false;
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
    let lastEventId: string | null = null;
    const progress = streamProgressFor(streamProgressRef.current, taskId);

    const applyTask = (task: Task, eventId: string) => {
      const eventCursor = parseEventCursor(eventId);
      if (eventCursor !== null && eventCursor < progress.cursor) return false;
      queryClient.setQueryData(["task", taskId], task);
      queryClient.setQueryData<TaskListResponse | undefined>(["tasks"], (current) =>
        updateTaskListCache(current, task),
      );
      if (eventCursor !== null) progress.cursor = Math.max(progress.cursor, eventCursor);
      progress.revision += 1;
      return true;
    };
    const removeTask = (eventId: string) => {
      const eventCursor = parseEventCursor(eventId);
      if (eventCursor !== null && eventCursor < progress.cursor) return false;
      queryClient.removeQueries({ queryKey: ["task", taskId], exact: true });
      queryClient.setQueryData<TaskListResponse | undefined>(["tasks"], (current) =>
        current ? { ...current, items: current.items.filter((item) => item.id !== taskId) } : current,
      );
      if (eventCursor !== null) progress.cursor = Math.max(progress.cursor, eventCursor);
      progress.revision += 1;
      return true;
    };
    const applyTaskDelta = (delta: TaskEventDelta, eventId: string) => {
      const eventCursor = parseEventCursor(eventId);
      const deltaCursor = Number.isInteger(delta.cursor) && delta.cursor >= 0 ? delta.cursor : eventCursor;
      if (deltaCursor !== null && deltaCursor < progress.cursor) return false;
      let merged: Task | undefined;
      queryClient.setQueryData<Task | undefined>(["task", taskId], (current) => {
        merged = mergeTaskEventDelta(current, delta);
        return merged;
      });
      if (merged) {
        queryClient.setQueryData<TaskListResponse | undefined>(["tasks"], (current) =>
          updateTaskListCache(current, merged as Task),
        );
      }
      if (deltaCursor !== null) progress.cursor = Math.max(progress.cursor, deltaCursor);
      progress.revision += 1;
      return true;
    };

    const connect = async () => {
      let retryMs = 1000;
      setStreamState("connecting");
      while (!disposed) {
        try {
          const response = await openTaskEventStream(taskId, controller.signal, lastEventId);
          if (disposed) return;
          await queryClient.cancelQueries({ queryKey: ["task", taskId], exact: true });
          setStreamState("connected");
          const terminal = await consumeTaskEventStream(
            response,
            applyTask,
            applyTaskDelta,
            removeTask,
            (eventId) => {
              lastEventId = eventId;
            },
          );
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
