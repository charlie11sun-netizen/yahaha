"use client";

import type { ReactNode } from "react";
import { Edit3, FileText, X } from "lucide-react";

import { FileChangeRow } from "./CreateFileChangeRow";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  contextSourceLabel,
  getGameplayQaStatus,
  getLogFileChanges,
  gameplayTechLabel,
  latestAgentContext,
  visibleAgentLogs,
  type AgentContextSummary,
} from "../_lib/create-state";
import type { Task } from "@/lib/types";

export function ActivityDrawer({ onClose, task }: { onClose: () => void; task?: Task }) {
  const logs = visibleAgentLogs(task);
  const agentContext = latestAgentContext(logs);
  const gameplayStatus = getGameplayQaStatus(task);
  const designFields = task?.design?.fields.slice(0, 4) ?? [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/45 p-3 backdrop-blur-sm" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div>
            <h2 className="font-display text-2xl font-semibold tracking-normal text-slate-950">Activity</h2>
            <p className="mt-1 text-sm text-slate-500">{task?.game_title || "Generation task"}</p>
          </div>
          <Button aria-label="Close activity" onClick={onClose} size="icon" type="button" variant="ghost">
            <X size={18} />
          </Button>
        </header>

        <div className="flex-1 space-y-6 overflow-auto p-5">
          <section className="space-y-3">
            <h3 className="font-display text-lg font-semibold tracking-normal text-slate-950">Technical details</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <TechItem label="Task status" value={task?.status || "No active task"} />
              <TechItem label="Manifest" value={task?.manifest_url || "Pending"} />
              <TechItem label="Preview" value={task?.preview_url || "Pending"} />
              {gameplayStatus ? <TechItem label="Gameplay QA" value={gameplayTechLabel(gameplayStatus)} /> : null}
              {designFields.map((field) => (
                <TechItem key={field.label} label={field.label} value={field.value} />
              ))}
              <TechItem label="Repair attempts" value={`${task?.repair_attempts ?? 0}/${task?.max_repair_attempts ?? 2}`} />
              <TechItem label="Replan attempts" value={`${task?.replan_attempts ?? 0}/${task?.max_replan_attempts ?? 1}`} />
              <TechItem label="Tokens" value={(task?.tokens ?? 0).toLocaleString()} />
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="font-display text-lg font-semibold tracking-normal text-slate-950">Agent context</h3>
            <AgentContextPanel context={agentContext} />
          </section>

          <section className="space-y-3">
            <h3 className="font-display text-lg font-semibold tracking-normal text-slate-950">Agent activity</h3>
            {logs.length === 0 ? (
              <EmptyState>No activity yet.</EmptyState>
            ) : (
              logs.map((log, index) => {
                const changes = getLogFileChanges(log);
                const changeLines = new Set(changes.map((change) => change.line));
                const visibleLines = (log.lines.length ? log.lines : [log.message]).filter((line) => !changeLines.has(line));
                return (
                  <div className="rounded-lg border border-slate-200 bg-white p-4" key={`${log.agent_name}-${index}`}>
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span
                        className={cn(
                          "size-2 rounded-full",
                          log.status === "failed" ? "bg-rose-500" : log.status === "completed" ? "bg-emerald-500" : "bg-indigo-500",
                        )}
                      />
                      <strong className="font-semibold text-slate-950">{log.agent_name}</strong>
                      <em className="not-italic text-slate-500">{log.step}</em>
                      {log.duration ? <time className="font-mono text-xs text-slate-400">{log.duration}</time> : null}
                    </div>
                    {changes.length > 0 ? (
                      <div className="mt-3 grid gap-2">
                        {changes.map((change) => (
                          <FileChangeRow change={change} key={`${change.action}-${change.path}-${change.line}`} showDiff />
                        ))}
                      </div>
                    ) : null}
                    {visibleLines.length > 0 ? (
                      <div className="mt-3 rounded-lg bg-slate-950 p-3 font-mono text-xs leading-6 text-slate-100">
                        {visibleLines.map((line, lineIndex) => (
                          <p key={`${line}-${lineIndex}`}>{line}</p>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}

function AgentContextPanel({ context }: { context: AgentContextSummary }) {
  if (context.files.length === 0 && context.filesInContext.length === 0) {
    return <EmptyState>No agent context yet.</EmptyState>;
  }

  return (
    <div className="space-y-4">
      {context.files.length > 0 ? (
        <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <FileText size={14} />
            <span>Bundle</span>
          </div>
          <div className="grid gap-2">
            {context.files.map((file) => (
              <div className="grid gap-1 rounded-lg border border-slate-200 bg-white p-3 text-xs" key={file.path}>
                <strong className="break-all font-mono text-slate-800">{file.path}</strong>
                <div className="flex flex-wrap gap-2 text-slate-500">
                  <span>{file.kind || "file"}</span>
                  <span>{file.lines ?? 0} lines</span>
                  <span>{file.referenced ? "referenced" : "unreferenced"}</span>
                </div>
              </div>
            ))}
          </div>
          {context.scriptRefs.length > 0 ? (
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">script order</span>
              <strong className="mt-1 block break-all font-mono text-xs text-slate-800">{context.scriptRefs.join(" -> ")}</strong>
            </div>
          ) : null}
        </div>
      ) : null}

      {context.filesInContext.length > 0 ? (
        <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <Edit3 size={14} />
            <span>Files in context</span>
          </div>
          <div className="grid gap-2">
            {context.filesInContext.map((file) => (
              <div
                className={cn(
                  "grid gap-1 rounded-lg border bg-white p-3 text-xs",
                  file.deleted ? "border-rose-200 bg-rose-50" : "border-slate-200",
                )}
                key={file.path}
              >
                <strong className="break-all font-mono text-slate-800">{file.path}</strong>
                <div className="flex flex-wrap gap-2 text-slate-500">
                  <span>{contextSourceLabel(file.record_source)}</span>
                  <span>{file.record_state || "active"}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">{children}</p>;
}

function TechItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</span>
      <strong className="mt-1 block break-all text-sm font-semibold text-slate-900">{value}</strong>
    </div>
  );
}
