import type { AgentLogItem, Task } from "@/lib/types";
import { activityMessageFromEvent, logEntries, usageFromEvent } from "./agent-events";

const STREAM_TOKEN_RE = /^stream_tokens=(\d+)$/;

export function isStreamTokenLine(line: string | null | undefined) {
  return Boolean(line && STREAM_TOKEN_RE.test(line.trim()));
}

export function cleanStreamLine(line: string | null | undefined) {
  if (!line || isStreamTokenLine(line)) return null;
  return line;
}

export function activeTaskLogs(task?: Task) {
  const logs = task?.logs ?? [];
  const running = logs.filter((log) => log.status === "running");
  return running.length ? running : logs.slice(-1);
}

export function getLiveTokenTotal(task?: Task) {
  // Per-response usage is committed before usage_progress is published.  The
  // durable task counter is therefore already live; adding streamed totals here
  // double-counts the active response.
  return task?.tokens ?? null;
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
  const entries = log.entries?.flatMap((entry) => {
    if (!isStreamTokenLine(entry.line)) return [entry];
    if (!usageFromEvent(entry.event)) return [];
    const usageMessage = activityMessageFromEvent(entry.event);
    return usageMessage ? [{ ...entry, line: usageMessage }] : [];
  });
  const lines = log.entries?.length
    ? (entries ?? []).map((entry) => entry.line)
    : log.lines.filter((line) => !isStreamTokenLine(line));
  const message = isStreamTokenLine(log.message) ? (lines.at(-1) ?? "") : log.message;
  return { ...log, message, lines, entries };
}
