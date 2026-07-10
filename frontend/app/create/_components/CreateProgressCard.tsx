"use client";

import { useMemo, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowRight,
  Check,
  Circle,
  Clock3,
  Loader2,
  Sparkles,
  Timer,
  WandSparkles,
} from "lucide-react";

import { FileChangeRow } from "./CreateFileChangeRow";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getLiveAgentActivity, getLiveStreamTokens } from "../_lib/agent-activity";
import {
  buildStepRows,
  getActiveStepIndex,
  getCurrentIssue,
  getProgressTitle,
  getRecentUpdates,
  isActiveTask,
  type StepState,
} from "../_lib/create-progress";
import { formatElapsed, formatRelative } from "../_lib/create-time";
import { getLiveFileChanges } from "../_lib/file-changes";
import type { Task } from "@/lib/types";

export function CreateProgressCard({
  connectionStatus,
  now,
  onOpenActivity,
  task,
}: {
  connectionStatus: string;
  now: number;
  onOpenActivity: () => void;
  task?: Task;
}) {
  const rows = useMemo(() => buildStepRows(task), [task]);
  const activeIndex = getActiveStepIndex(rows, task);
  const activeStep = rows[activeIndex] ?? rows[0];
  const issue = getCurrentIssue(task, activeStep);
  const recentUpdates = getRecentUpdates(task, now);
  const statusTitle = getProgressTitle(task);
  const lastUpdated = formatRelative(task?.updated_at || task?.created_at, now) || "Waiting";
  const elapsed = formatElapsed(task?.created_at, now);
  const taskActive = isActiveTask(task?.status);
  const liveTokens = getLiveStreamTokens(task);
  const liveActivity = liveTokens === null && taskActive ? getLiveAgentActivity(task) : "";
  const liveFileChanges = getLiveFileChanges(task).slice(-4);

  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-6 p-5 sm:p-6">
        <div className="grid gap-4 md:grid-cols-[auto_1fr_auto] md:items-center">
          <span className="flex size-12 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
            <Sparkles size={28} />
          </span>
          <div className="min-w-0">
            <h2 className="font-display text-2xl font-semibold tracking-normal text-slate-950">{statusTitle}</h2>
            <p className="mt-1 text-sm text-slate-600">
              Step {Math.min(activeIndex + 1, rows.length)} of {rows.length}
              <span> - </span>
              {activeStep?.label || "Preparing task"}
            </p>
          </div>
          <Badge className="gap-1 border-indigo-200 bg-indigo-50 text-indigo-700" variant="outline">
            <ArrowRight size={14} />
            You can leave this page
          </Badge>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <StatusPill icon={<Clock3 size={15} />} label={`Last update ${lastUpdated}`} />
          <StatusPill
            icon={<Circle size={10} fill="currentColor" />}
            label={connectionStatus}
            tone={connectionStatus === "Connected" ? "success" : "warning"}
          />
          <StatusPill icon={<Timer size={15} />} label={`Elapsed ${elapsed}`} />
        </div>

        {liveTokens !== null && taskActive ? (
          <div className="flex items-center justify-between rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3">
            <span className="text-xs font-bold uppercase tracking-[0.16em] text-indigo-600">tokens</span>
            <strong className="font-display text-2xl font-semibold tracking-normal text-indigo-950" key={liveTokens}>
              {liveTokens.toLocaleString()}
            </strong>
          </div>
        ) : null}

        {liveActivity ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <span className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">activity</span>
            <strong className="mt-1 block text-sm font-semibold text-slate-800">{liveActivity}</strong>
          </div>
        ) : null}

        {liveFileChanges.length > 0 ? (
          <div className="grid gap-2" aria-label="Live file changes">
            {liveFileChanges.map((change) => (
              <FileChangeRow change={change} key={`${change.action}-${change.path}-${change.line}`} />
            ))}
          </div>
        ) : null}

        <div className="grid gap-3">
          {rows.map((step, index) => {
            const isActive = index === activeIndex && step.status !== "completed";
            return (
              <div className="grid grid-cols-[auto_1fr] gap-3" key={step.key}>
                <StepMarker active={isActive} status={step.status} />
                <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <strong className="text-sm font-semibold text-slate-900">{step.label}</strong>
                  {isActive && issue ? (
                    <div
                      className={cn(
                        "mt-3 flex gap-3 rounded-lg border p-3",
                        issue.level === "error"
                          ? "border-rose-200 bg-rose-50 text-rose-800"
                          : "border-indigo-200 bg-indigo-50 text-indigo-800",
                      )}
                    >
                      <span className="mt-0.5 shrink-0">
                        {issue.level === "error" ? <AlertCircle size={17} /> : <WandSparkles size={17} />}
                      </span>
                      <div>
                        <b className="text-sm font-semibold">{issue.title}</b>
                        <p className="mt-1 text-sm leading-6">{issue.message}</p>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-display text-lg font-semibold tracking-normal text-slate-950">Recent updates</h3>
            <Button className="rounded-lg" onClick={onOpenActivity} type="button" variant="outline">
              View full activity
              <ArrowRight size={16} />
            </Button>
          </div>
          <div className="space-y-3">
            {recentUpdates.map((update, index) => (
              <div className="grid grid-cols-[auto_auto_1fr] items-start gap-3 text-sm" key={`${update.message}-${index}`}>
                <span
                  className={cn(
                    "mt-1 size-2 rounded-full",
                    update.level === "error" ? "bg-rose-500" : update.level === "success" ? "bg-emerald-500" : "bg-indigo-500",
                  )}
                />
                <time className="font-mono text-xs text-slate-400">{update.time}</time>
                <p className="leading-6 text-slate-600">{update.message}</p>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusPill({
  icon,
  label,
  tone = "neutral",
}: {
  icon: ReactNode;
  label: string;
  tone?: "neutral" | "success" | "warning";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold",
        tone === "success"
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : tone === "warning"
            ? "border-amber-200 bg-amber-50 text-amber-700"
            : "border-slate-200 bg-slate-50 text-slate-600",
      )}
    >
      {icon}
      {label}
    </span>
  );
}

function StepMarker({ active, status }: { active: boolean; status: StepState }) {
  return (
    <span
      className={cn(
        "flex size-8 items-center justify-center rounded-full border",
        status === "completed"
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : status === "failed"
            ? "border-rose-200 bg-rose-50 text-rose-700"
            : active
              ? "border-indigo-200 bg-indigo-50 text-indigo-700"
              : "border-slate-200 bg-white text-slate-400",
      )}
    >
      {status === "completed" ? (
        <Check size={14} />
      ) : status === "failed" ? (
        <AlertCircle size={14} />
      ) : active ? (
        <Loader2 className="size-4 animate-spin" />
      ) : null}
    </span>
  );
}
