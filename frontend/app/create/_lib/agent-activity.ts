import type { AgentLogItem, Task } from "@/lib/types";
import { activityMessageFromEvent, logEntries } from "./agent-events";

const STREAM_TOKEN_RE = /^stream_tokens=(\d+)$/;

export function isStreamTokenLine(line: string | null | undefined) {
  return Boolean(line && STREAM_TOKEN_RE.test(line.trim()));
}

export function cleanStreamLine(line: string | null | undefined) {
  if (!line || isStreamTokenLine(line)) return null;
  return line;
}

function parseStreamTokens(line: string | null | undefined) {
  const match = line?.trim().match(STREAM_TOKEN_RE);
  return match ? Number(match[1]) : null;
}

export function activeTaskLogs(task?: Task) {
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
