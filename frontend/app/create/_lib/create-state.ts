"use client";

import { useEffect, useState } from "react";

import type { AgentBundleFile, AgentFileContext, AgentLogItem, StepSummary, Task, UploadedAsset } from "@/lib/types";

export const GAMEPLAY_STEP_KEYS = ["gameplay_qa", "gameplay_repair"] as const;
const STREAM_TOKEN_RE = /^stream_tokens=(\d+)$/;

export type UserStep = { key: string; label: string; backendKeys?: readonly string[]; optional?: boolean };

const USER_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Idea checked" },
  { key: "intent_spec", label: "Game spec created", backendKeys: ["intent_spec", "brief_expansion", "mechanic_planner", "archetype_router"] },
  { key: "asset_processing", label: "Assets processed" },
  { key: "game_design", label: "Game designed", backendKeys: ["game_design", "content_plan", "balance_plan"] },
  { key: "code_generation", label: "Files generated" },
  { key: "build_validation", label: "Validating build", backendKeys: ["build_validation", "static_validation"] },
  { key: "gameplay_qa", label: "Playtesting game", backendKeys: GAMEPLAY_STEP_KEYS, optional: true },
  { key: "publish_artifact", label: "Preparing preview" },
  { key: "ready", label: "Ready to publish" },
];
const USER_REVISION_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Feedback checked" },
  { key: "feedback_understanding", label: "Feedback understood" },
  { key: "code_revision", label: "Existing files revised" },
  { key: "build_validation", label: "Validating changes" },
  { key: "gameplay_qa", label: "Regression playtest" },
  { key: "publish_revision", label: "Saving new preview" },
  { key: "ready", label: "Ready to publish" },
];
const USER_REMIX_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Remix checked" },
  { key: "feedback_understanding", label: "Remix goal understood" },
  { key: "code_revision", label: "Source files transformed" },
  { key: "build_validation", label: "Validating remix" },
  { key: "gameplay_qa", label: "Playtesting remix" },
  { key: "publish_remix", label: "Saving remix preview" },
  { key: "ready", label: "Ready to publish" },
];

export type StepState = "pending" | "running" | "completed" | "failed";
export type StepRow = { key: string; label: string; status: StepState; summary?: string | null };
export type FileChange = {
  action: "created" | "modified" | "deleted";
  added: number;
  deleted: number;
  detail?: string;
  diff?: string | null;
  diffFormat?: string;
  line: string;
  path: string;
};
export type AgentContextSummary = {
  files: AgentBundleFile[];
  filesInContext: AgentFileContext[];
  scriptRefs: string[];
};

export function buildStepRows(task?: Task): StepRow[] {
  const backend = new Map<string, StepSummary>((task?.step_summaries ?? []).map((step) => [step.step, step]));
  const configuredSteps =
    task?.task_kind === "remix" ? USER_REMIX_STEPS : task?.task_kind === "revision" ? USER_REVISION_STEPS : USER_STEPS;
  const visibleSteps = configuredSteps.filter((step) => !step.optional || stepHasBackendSummary(step, backend));
  const rows = visibleSteps.map((step) => {
    if (step.key === "ready") {
      return {
        key: step.key,
        label: step.label,
        status: task?.status === "succeeded" ? "completed" : "pending",
      } satisfies StepRow;
    }
    const summaries = stepSummariesFor(step, backend);
    return {
      key: step.key,
      label: step.label,
      status: mergedStepStatus(summaries),
      summary: displayStepSummary(summaries),
    } satisfies StepRow;
  });

  if (task?.status === "succeeded") {
    return rows.map((row) => ({ ...row, status: "completed" }));
  }

  if (task?.status === "failed" || task?.status === "cancelled") {
    const failedIndex = rows.findIndex((row) => row.status === "running" || row.status === "failed");
    const index = failedIndex >= 0 ? failedIndex : Math.min(Math.max((task.current_step || 1) - 1, 0), rows.length - 1);
    return rows.map((row, rowIndex) => (rowIndex === index ? { ...row, status: "failed" } : row));
  }

  return rows;
}

function stepKeys(step: UserStep) {
  return step.backendKeys ?? [step.key];
}

function stepSummariesFor(step: UserStep, backend: Map<string, StepSummary>) {
  return stepKeys(step)
    .map((key) => backend.get(key))
    .filter((summary): summary is StepSummary => Boolean(summary));
}

function stepHasBackendSummary(step: UserStep, backend: Map<string, StepSummary>) {
  return stepSummariesFor(step, backend).length > 0;
}

function mergedStepStatus(summaries: StepSummary[]): StepState {
  if (summaries.length === 0) return "pending";
  const statuses = summaries.map((summary) => normalizeStatus(summary.status));
  if (statuses.includes("running")) return "running";
  if (statuses.includes("failed")) return "failed";
  if (statuses.every((status) => status === "completed")) return "completed";
  return "pending";
}

function displayStepSummary(summaries: StepSummary[]) {
  return (
    cleanStreamLine(summaries.find((summary) => normalizeStatus(summary.status) === "running")?.summary) ||
    cleanStreamLine(summaries.find((summary) => normalizeStatus(summary.status) === "failed")?.summary) ||
    cleanStreamLine([...summaries].reverse().find((summary) => summary.summary)?.summary) ||
    null
  );
}

export function getActiveStepIndex(rows: StepRow[], task?: Task) {
  if (task?.status === "succeeded") return rows.length - 1;
  const failed = rows.findIndex((row) => row.status === "failed");
  if (failed >= 0) return failed;
  const running = rows.findIndex((row) => row.status === "running");
  if (running >= 0) return running;
  const lastCompleted = rows.reduce((last, row, index) => (row.status === "completed" ? index : last), -1);
  return Math.min(lastCompleted + 1, rows.length - 1);
}

function normalizeStatus(status?: string): StepState {
  if (status === "completed" || status === "running" || status === "failed") return status;
  if (status === "done") return "completed";
  return "pending";
}

export function getBrief(task: Task | undefined, uploadedFiles: UploadedAsset[]) {
  const title = task?.game_title || task?.game?.title || summarizeIdea(task?.idea) || summarizeIdea(uploadedFiles[0]?.name) || "Untitled game";
  const source = `${title} ${task?.idea || ""}`.toLowerCase();
  const genre = inferGenre(source);
  const style = inferStyle(source);
  const assetCount = task?.assets?.filter((asset) => asset.type === "uploaded").length ?? uploadedFiles.length;
  const runtime = task?.dimension === "3d" ? "3D · WebGL" : task ? "2D · Canvas" : "Browser runtime";
  return { title, assetCount, genre, style, runtime };
}

function summarizeIdea(value?: string) {
  if (!value) return "";
  const cleaned = value.replace(/\s+/g, " ").trim();
  if (!cleaned) return "";
  return cleaned.length > 34 ? `${cleaned.slice(0, 31)}...` : cleaned;
}

function inferGenre(source: string) {
  if (source.includes("puzzle") || source.includes("logic")) return "Puzzle";
  if (source.includes("racing") || source.includes("race") || source.includes("drift")) return "Racing";
  if (source.includes("runner") || source.includes("dodge") || source.includes("arcade")) return "Arcade";
  if (source.includes("rpg") || source.includes("quest")) return "RPG";
  return "Arcade";
}

function inferStyle(source: string) {
  if (source.includes("cyberpunk") || source.includes("neon")) return "Cyberpunk";
  if (source.includes("forest") || source.includes("magic") || source.includes("fantasy")) return "Fantasy";
  if (source.includes("pixel")) return "Pixel";
  if (source.includes("cozy")) return "Cozy";
  return "AI generated";
}

export function getProgressTitle(task?: Task) {
  if (task?.status === "succeeded") return "Game ready";
  if (task?.status === "failed") return "Generation stopped";
  if (task?.status === "cancelled") return "Task cancelled";
  return "Creating your game";
}

export function getCurrentIssue(task: Task | undefined, activeStep?: StepRow) {
  if (!task) return null;
  if (task.status === "failed") {
    return {
      level: "error" as const,
      title: "Issue found",
      message: task.error || "Build validation could not pass after repair attempts.",
    };
  }
  if (task.status === "cancelled") {
    return {
      level: "warning" as const,
      title: "Cancelled",
      message: "This task was stopped before preview generation completed.",
    };
  }
  if (task.repair_attempts && activeStep?.key === "build_validation") {
    return {
      level: "warning" as const,
      title: "Issue found - Auto-repairing",
      message: `Repair attempt ${task.repair_attempts} of ${task.max_repair_attempts || 2} - ${latestReadableLog(task) || "Fixing a runtime validation issue."}`,
    };
  }
  if (task.replan_attempts && activeStep?.key === "build_validation") {
    return {
      level: "warning" as const,
      title: "Design adjusted",
      message: `Replanning a simpler playable version - Attempt ${task.replan_attempts} of ${task.max_replan_attempts || 1}.`,
    };
  }
  if (activeStep?.key === "gameplay_qa" && activeStep.status === "running") {
    return {
      level: "warning" as const,
      title: "Playtest running",
      message: latestReadableLog(task) || "Checking restart, input response, scoring, and difficulty before preview.",
    };
  }
  if (activeStep?.key === "gameplay_qa" && activeStep.status === "failed") {
    return {
      level: "error" as const,
      title: "Gameplay issue found",
      message: latestReadableLog(task) || "The generated game needs a balance or logic repair before publishing.",
    };
  }
  return null;
}

function latestReadableLog(task?: Task) {
  const logs = visibleAgentLogs(task);
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const line = logs[index].message || logs[index].lines.at(-1);
    if (line) return friendlyMessage(line);
  }
  return "";
}

export function getRecentUpdates(task: Task | undefined, now: number) {
  const logs = visibleAgentLogs(task);
  const updates = logs
    .filter((log) => log.message || log.lines.length)
    .slice(-3)
    .reverse()
    .map((log) => ({
      level: log.status === "failed" ? ("error" as const) : log.status === "completed" ? ("success" as const) : ("info" as const),
      message: friendlyMessage(log.message || log.lines.at(-1) || "Task updated"),
      time: formatRelative(log.created_at || task?.updated_at || task?.created_at, now) || "just now",
    }));

  if (updates.length > 0) return updates;
  // 没有真实日志时不编造系统状态（"sandbox ready / pipeline connected" 之类
  // 会在故障时显示一切正常）—— 只说我们真正知道的事。
  if (!task) {
    return [{ level: "info" as const, message: "Loading task…", time: "now" }];
  }
  if (task.status === "succeeded") {
    return [
      { level: "success" as const, message: "Preview ready", time: formatRelative(task.finished_at || task.updated_at, now) || "just now" },
    ];
  }
  return [
    { level: "info" as const, message: "Generation task created", time: formatRelative(task.created_at, now) || "just now" },
    { level: "info" as const, message: "Waiting for the first agent update", time: "now" },
  ];
}

export function friendlyMessage(message: string) {
  const compact = message.replace(/\s+/g, " ").trim();
  if (isStreamTokenLine(compact)) return "";
  const lower = compact.toLowerCase();
  if (lower.includes("repair")) return "Repair attempt started";
  if (lower.includes("playtest") || lower.includes("gameplay") || lower.includes("qa")) return "Gameplay playtest updated";
  if (lower.includes("difficulty") || lower.includes("balance")) return "Difficulty balance adjusted";
  if (lower.includes("validation") && lower.includes("issue")) return "Validation found an issue";
  if (lower.includes("asset")) return "Assets processed successfully";
  if (lower.includes("manifest")) return "Manifest uploaded";
  if (lower.includes("preview")) return "Preview prepared";
  if (lower.includes("design")) return "Game designed";
  if (lower.includes("code")) return "Files generated";
  return compact.length > 86 ? `${compact.slice(0, 83)}...` : compact || "Task updated";
}

function isStreamTokenLine(line: string | null | undefined) {
  return Boolean(line && STREAM_TOKEN_RE.test(line.trim()));
}

function cleanStreamLine(line: string | null | undefined) {
  if (!line || isStreamTokenLine(line)) return null;
  return line;
}

function parseStreamTokens(line: string | null | undefined) {
  const match = line?.trim().match(STREAM_TOKEN_RE);
  return match ? Number(match[1]) : null;
}

function activeTaskLogs(task?: Task) {
  const logs = task?.logs ?? [];
  const running = logs.filter((log) => log.status === "running");
  return running.length ? running : logs.slice(-1);
}

export function getLiveStreamTokens(task?: Task) {
  const logs = activeTaskLogs(task);
  for (let logIndex = logs.length - 1; logIndex >= 0; logIndex -= 1) {
    const lines = logs[logIndex].lines.length ? logs[logIndex].lines : [logs[logIndex].message];
    for (let lineIndex = lines.length - 1; lineIndex >= 0; lineIndex -= 1) {
      const value = parseStreamTokens(lines[lineIndex]);
      if (value !== null) return value;
    }
  }
  return null;
}

export function getLiveAgentActivity(task?: Task) {
  const logs = activeTaskLogs(task)
    .map(stripStreamTokenEntries)
    .filter((log) => log.message || log.lines.length || (log.entries?.length ?? 0) > 0);
  for (let logIndex = logs.length - 1; logIndex >= 0; logIndex -= 1) {
    const entries = logEntries(logs[logIndex]);
    for (let entryIndex = entries.length - 1; entryIndex >= 0; entryIndex -= 1) {
      const eventMessage = activityMessageFromEvent(entries[entryIndex].event);
      if (eventMessage) return eventMessage;
    }
    const lines = logs[logIndex].lines.length ? logs[logIndex].lines : [logs[logIndex].message];
    for (let lineIndex = lines.length - 1; lineIndex >= 0; lineIndex -= 1) {
      const compact = lines[lineIndex]?.replace(/\s+/g, " ").trim();
      if (compact) return compact.length > 104 ? `${compact.slice(0, 101)}...` : compact;
    }
  }
  return "";
}

function eventType(event: unknown): string {
  if (!event || typeof event !== "object") return "";
  const value = (event as { type?: unknown }).type;
  return typeof value === "string" ? value : "";
}

function eventNumber(event: unknown, key: string): number {
  if (!event || typeof event !== "object") return 0;
  const value = (event as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function eventString(event: unknown, key: string): string {
  if (!event || typeof event !== "object") return "";
  const value = (event as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

function eventArray(event: unknown, key: string): unknown[] {
  if (!event || typeof event !== "object") return [];
  const value = (event as Record<string, unknown>)[key];
  return Array.isArray(value) ? value : [];
}

function eventRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function optionalEventNumber(record: Record<string, unknown>, key: string): number | undefined {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function eventStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : [];
}

function bundleFilesFromValue(value: unknown): AgentBundleFile[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): AgentBundleFile[] => {
    const record = eventRecord(item);
    const path = typeof record?.path === "string" ? record.path : "";
    if (!record || !path) return [];
    return [
      {
        bytes: optionalEventNumber(record, "bytes"),
        kind: typeof record.kind === "string" ? record.kind : undefined,
        lines: optionalEventNumber(record, "lines"),
        path,
        referenced: typeof record.referenced === "boolean" ? record.referenced : undefined,
      },
    ];
  });
}

function fileContextsFromValue(value: unknown): AgentFileContext[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): AgentFileContext[] => {
    const record = eventRecord(item);
    const path = typeof record?.path === "string" ? record.path : "";
    if (!record || !path) return [];
    return [
      {
        bytes: optionalEventNumber(record, "bytes"),
        cline_edit_date: optionalEventNumber(record, "cline_edit_date") ?? null,
        cline_read_date: optionalEventNumber(record, "cline_read_date") ?? null,
        deleted: typeof record.deleted === "boolean" ? record.deleted : undefined,
        lines: optionalEventNumber(record, "lines"),
        path,
        record_source: typeof record.record_source === "string" ? record.record_source : undefined,
        record_state: typeof record.record_state === "string" ? record.record_state : undefined,
        updated_at: optionalEventNumber(record, "updated_at"),
      },
    ];
  });
}

export function latestAgentContext(logs: AgentLogItem[]): AgentContextSummary {
  let files: AgentBundleFile[] = [];
  let filesInContext: AgentFileContext[] = [];
  let scriptRefs: string[] = [];

  logs.forEach((log) => {
    logEntries(log).forEach((entry) => {
      const event = eventRecord(entry.event);
      if (!event) return;
      const bundle = eventRecord(event.bundle);
      const bundleFiles = bundleFilesFromValue(bundle?.files);
      const eventFiles = bundleFilesFromValue(event.files);
      const bundleContext = fileContextsFromValue(bundle?.files_in_context);
      const eventContext = fileContextsFromValue(event.files_in_context);
      const bundleRefs = eventStringArray(bundle?.script_refs);
      const eventRefs = eventStringArray(event.script_refs);

      if (bundleFiles.length) files = bundleFiles;
      if (eventFiles.length) files = eventFiles;
      if (bundleContext.length) filesInContext = bundleContext;
      if (eventContext.length) filesInContext = eventContext;
      if (bundleRefs.length) scriptRefs = bundleRefs;
      if (eventRefs.length) scriptRefs = eventRefs;
    });
  });

  return { files, filesInContext, scriptRefs };
}

export function contextSourceLabel(source: string | undefined) {
  switch (source) {
    case "read_tool":
      return "read";
    case "cline_edited":
      return "edited";
    case "user_edited":
      return "user edited";
    case "file_mentioned":
      return "mentioned";
    default:
      return source || "tracked";
  }
}

function clineToolLabel(tool: string) {
  switch (tool) {
    case "readFile":
      return "Read file";
    case "searchFiles":
      return "Searched files";
    case "listFilesTopLevel":
    case "listFilesRecursive":
      return "Listed files";
    case "editedExistingFile":
      return "Edited file";
    case "newFileCreated":
      return "Created file";
    case "fileDeleted":
      return "Deleted file";
    case "useSkill":
      return "Read skill";
    default:
      return tool.replace(/_/g, " ");
  }
}

function activityMessageFromEvent(event: unknown): string {
  const type = eventType(event);
  if (type === "turn_state") {
    const phase = eventString(event, "phase");
    const message = eventString(event, "message");
    const toolCount = eventNumber(event, "tool_count");
    if (phase === "streaming" && toolCount) return `Agent running with ${toolCount} tool(s)`;
    if (phase === "completed") return message || "Agent completed";
    if (phase === "error") return message || "Agent stopped";
    return message || (phase ? `Agent ${phase}` : "");
  }
  if (type === "usage") {
    const total = eventNumber(event, "total_tokens");
    const cached = eventNumber(event, "cached_tokens");
    const cachePercent = eventNumber(event, "cache_percent");
    return total ? `Model usage ${total.toLocaleString()} tokens, cache ${cached.toLocaleString()} (${cachePercent}%)` : "";
  }
  if (type === "file_change") {
    const change = fileChangeFromEvent(event, "");
    if (!change) return "";
    const label = change.action === "created" ? "Created" : change.action === "deleted" ? "Deleted" : "Edited";
    return `${label} ${change.path} (+${change.added} -${change.deleted})`;
  }
  if (type === "heartbeat") {
    const phase = eventString(event, "phase") || "authoring";
    const elapsed = eventNumber(event, "elapsed_seconds");
    const idle = eventNumber(event, "idle_seconds");
    const files = eventNumber(event, "file_count");
    const changed = eventNumber(event, "changed_count");
    const checks = eventString(event, "checks") || "pending";
    return `${phase} waiting on model response: ${elapsed}s elapsed, ${idle}s since last tool, bundle=${files} file(s), changed=${changed}, checks=${checks}`;
  }
  if (type === "check") {
    const checksOk = Boolean((event as Record<string, unknown>).checks_ok);
    const staticErrors = eventNumber(event, "static_errors");
    const smokeOk = Boolean((event as Record<string, unknown>).smoke_ok);
    return `checks ${checksOk ? "passed" : "pending"}: static ${staticErrors ? `${staticErrors} error(s)` : "OK"}, smoke ${smokeOk ? "ok" : "pending"}`;
  }
  if (type === "tool") {
    const clineTool = eventString(event, "cline_tool");
    const tool = clineTool ? clineToolLabel(clineTool) : eventString(event, "tool") || "tool";
    const path = eventString(event, "path") || eventString(event, "name");
    const query = eventString(event, "query");
    const matchCount = eventArray(event, "matches").length;
    const fileCount = eventArray(event, "files").length;
    if (query) return `${tool}: "${query}"${matchCount ? ` (${matchCount} match(es))` : ""}`;
    if (fileCount) return `${tool}: ${fileCount} file(s)`;
    return path ? `${tool} ${path}` : tool;
  }
  if (type === "error") return eventString(event, "message") || "Agent error";
  if (type === "notice") return eventString(event, "message") || "Agent update";
  return "";
}

function fileChangeFromEvent(event: unknown, line: string): FileChange | null {
  if (eventType(event) !== "file_change") return null;
  const path = eventString(event, "path");
  if (!path) return null;
  const action = eventString(event, "action");
  return {
    action: action === "created" || action === "deleted" ? action : "modified",
    added: eventNumber(event, "added"),
    deleted: eventNumber(event, "deleted"),
    detail: eventString(event, "detail") || undefined,
    diff: eventString(event, "diff") || null,
    diffFormat: eventString(event, "diff_format") || undefined,
    line,
    path,
  };
}

function logEntries(log: AgentLogItem) {
  if (log.entries?.length) return log.entries;
  const lines = log.lines.length ? log.lines : [log.message];
  return lines.map((line) => ({ line, event: null }));
}

function parseFileChange(line: string | null | undefined): FileChange | null {
  const compact = line?.replace(/\s+/g, " ").trim();
  if (!compact) return null;
  const match = compact.match(/^agent (wrote|patched|added|deleted) ([^\s]+) \(\+(\d+) -(\d+)(?:,\s*([^)]+))?\)$/);
  if (!match) return null;
  const verb = match[1];
  return {
    action: verb === "added" ? "created" : verb === "deleted" ? "deleted" : "modified",
    added: Number(match[3]),
    deleted: Number(match[4]),
    detail: match[5],
    line: compact,
    path: match[2],
  };
}

export function getLogFileChanges(log: AgentLogItem): FileChange[] {
  const structured = logEntries(log)
    .map((entry) => fileChangeFromEvent(entry.event, entry.line))
    .filter((change): change is FileChange => Boolean(change));
  if (structured.length > 0) return structured;
  const lines = log.lines.length ? log.lines : [log.message];
  return lines.map(parseFileChange).filter((change): change is FileChange => Boolean(change));
}

export function getLiveFileChanges(task?: Task): FileChange[] {
  return activeTaskLogs(task).flatMap(getLogFileChanges);
}

export function fileChangeLabel(action: FileChange["action"]) {
  if (action === "created") return "已创建";
  if (action === "deleted") return "已删除";
  return "正在编辑";
}

export function visibleAgentLogs(task?: Task): AgentLogItem[] {
  return (task?.logs ?? [])
    .map(stripStreamTokenEntries)
    .filter((log) => log.message || log.lines.length || (log.entries?.length ?? 0) > 0);
}

function stripStreamTokenEntries(log: AgentLogItem): AgentLogItem {
  const lines = log.lines.filter((line) => !isStreamTokenLine(line));
  const entries = log.entries?.filter((entry) => !isStreamTokenLine(entry.line));
  const message = isStreamTokenLine(log.message) ? (lines.at(-1) ?? entries?.at(-1)?.line ?? "") : log.message;
  return { ...log, message, lines, entries };
}

export function getGameplayQaStatus(task?: Task): StepState | null {
  const summaries = (task?.step_summaries ?? []).filter((summary) => GAMEPLAY_STEP_KEYS.includes(summary.step as (typeof GAMEPLAY_STEP_KEYS)[number]));
  return summaries.length > 0 ? mergedStepStatus(summaries) : null;
}

export function gameplayRuntimeLabel(status: StepState) {
  if (status === "completed") return "Playtest passed";
  if (status === "running") return "Playtest running";
  if (status === "failed") return "Playtest needs repair";
  return "Playtest pending";
}

export function gameplayTechLabel(status: StepState) {
  if (status === "completed") return "Passed";
  if (status === "running") return "Running";
  if (status === "failed") return "Needs repair";
  return "Pending";
}

export function isActiveTask(status?: string) {
  return status === "pending" || status === "running";
}

export function formatRelative(value: string | null | undefined, now: number) {
  if (!value) return "";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "";
  const seconds = Math.max(0, Math.round((now - timestamp) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatElapsed(value: string | null | undefined, now: number) {
  if (!value) return "0s";
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "0s";
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remaining}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function useNow(intervalMs: number) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(interval);
  }, [intervalMs]);
  return now;
}
