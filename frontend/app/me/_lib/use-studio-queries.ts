"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useStudioQueries(enabled: boolean) {
  const gamesQ = useQuery({ queryKey: ["me-games"], queryFn: api.myGames, enabled });
  const favQ = useQuery({ queryKey: ["me-favorites"], queryFn: api.myFavorites, enabled });
  const tasksQ = useQuery({
    queryKey: ["tasks"],
    queryFn: api.tasks,
    enabled,
    refetchInterval: (query) =>
      query.state.data?.items?.some((task) => task.status === "pending" || task.status === "running") ? 3500 : false,
  });
  const memoryQ = useQuery({ queryKey: ["memory"], queryFn: () => api.memories(), enabled });
  const memoryProfilesQ = useQuery({ queryKey: ["memory-profiles"], queryFn: () => api.memoryProfiles(), enabled });
  const memorySettingsQ = useQuery({ queryKey: ["memory-settings"], queryFn: api.memorySettings, enabled });

  return { gamesQ, favQ, tasksQ, memoryQ, memoryProfilesQ, memorySettingsQ };
}
