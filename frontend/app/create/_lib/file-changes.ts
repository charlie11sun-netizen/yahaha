import type { AgentLogItem, Task } from "@/lib/types";
import { activeTaskLogs } from "./agent-activity";
import { fileChangeFromEvent, logEntries, type FileChange } from "./agent-events";

export type { FileChange } from "./agent-events";

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
  if (action === "created") return "Created";
  if (action === "deleted") return "Deleted";
  return "Edited";
}
