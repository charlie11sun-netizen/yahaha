import type { AgentBundleFile, AgentFileContext, AgentLogItem } from "@/lib/types";

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

export function contextSourceLabel(source: string | null | undefined) {
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

export function activityMessageFromEvent(event: unknown): string {
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

export function fileChangeFromEvent(event: unknown, line: string): FileChange | null {
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

export function logEntries(log: AgentLogItem) {
  if (log.entries?.length) return log.entries;
  const lines = log.lines.length ? log.lines : [log.message];
  return lines.map((line) => ({ line, event: null }));
}
