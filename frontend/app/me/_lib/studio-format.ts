import type { CSSProperties } from "react";

import type { MemoryItem, MemoryProfile, Task } from "@/lib/types";


export function avatarChoices(name: string) {
  const initial = (name.trim().slice(0, 1) || "A").toUpperCase();
  return Array.from(new Set([initial, "AI", "PF", "XP", "01", "GG"]));
}

export function coverStyle(cover?: string | null): CSSProperties {
  if (!cover) {
    return {
      background: "linear-gradient(135deg, #101844, #4f7dff 52%, #8be8f1)",
    };
  }
  if (cover.startsWith("/") || cover.startsWith("http://") || cover.startsWith("https://")) {
    return { backgroundImage: `url("${cover}")` };
  }
  return { background: cover };
}

export function joinedDate(value?: string | null) {
  if (!value) return "Recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  return new Intl.DateTimeFormat("en", { month: "long", year: "numeric" }).format(date);
}

export function shortId(id: string) {
  return `GEN-${id.replace(/-/g, "").slice(0, 4).toUpperCase()}`;
}

export function formatBytes(value?: number | null) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function taskStatusLabel(status: string) {
  if (status === "succeeded") return "Succeeded";
  if (status === "running") return "Running";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Cancelled";
  return "Pending";
}

export function taskActionLabel(task: Task) {
  if (task.status === "succeeded" && task.game) return "Open Result";
  if (task.status === "failed") return "View Logs";
  return "View Activity";
}

export function taskStep(task: Task) {
  if (task.status === "succeeded") return "Preview ready";
  if (task.status === "failed") return "Validation failed";
  const running = task.step_summaries?.find((step) => step.status === "running");
  const lastDone = [...(task.step_summaries ?? [])].reverse().find((step) => step.status === "completed");
  return running?.title || lastDone?.title || "Queued";
}

export function memoryScopeLabel(item: MemoryItem) {
  if (item.scope_type === "game") return `Game ${item.source_version || ""}`.trim();
  if (item.scope_type === "task") return "Task";
  return item.pinned ? "User preference · pinned" : "User preference";
}

export function profileScopeLabel(profile: MemoryProfile) {
  if (profile.scope_type === "game") return "Current game";
  if (profile.scope_type === "task") return "One task";
  return "All games";
}

export function memoryDate(value?: string | null) {
  if (!value) return "recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "recently";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
}
