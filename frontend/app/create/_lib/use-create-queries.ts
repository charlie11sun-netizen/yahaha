"use client";

import { useQuery } from "@tanstack/react-query";

import { isActiveTask } from "./create-state";
import { api, ApiError } from "@/lib/api";

export function useCreateTaskQuery(taskId: string | null) {
  const query = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.task(taskId as string),
    enabled: !!taskId,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && (error.status === 404 || error.status === 403)) && failureCount < 3,
    refetchInterval: (query) => {
      const err = query.state.error;
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) return false;
      if (err) return 3000;
      const status = query.state.data?.status;
      if (!status) return 1000;
      return isActiveTask(status) ? 1000 : false;
    },
  });

  return {
    ...query,
    isMissing: query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403),
  };
}

export function useCreateTasksQuery(enabled: boolean) {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: api.tasks,
    enabled,
    refetchInterval: enabled ? 5000 : false,
  });
}
