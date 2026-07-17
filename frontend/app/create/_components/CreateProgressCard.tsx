"use client";

import { useMemo } from "react";
import {
  AlertCircle,
  ArrowRight,
  Check,
  Circle,
  Clock3,
  Database,
  Loader2,
  Sparkles,
  Timer,
  WandSparkles,
} from "lucide-react";

import { FileChangeRow } from "./CreateFileChangeRow";
import { AuthorTeamProgressList } from "./CreateAuthorTeamProgress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getLiveAgentActivity, getLiveTokenTotal } from "../_lib/agent-activity";
import { getAuthorTeamProgress } from "../_lib/author-team";
import {
  buildStepRows,
  friendlyMessage,
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
  const liveTokens = getLiveTokenTotal(task);
  const liveActivity = taskActive ? getLiveAgentActivity(task) : "";
  const authorTeamProgress = getAuthorTeamProgress(task);
  const visibleAuthorTeamProgress = activeStep?.key === "code_generation" ? authorTeamProgress : null;
  const liveFileChanges = getLiveFileChanges(task).slice(-2);
  const tokenTotal = liveTokens ?? task?.tokens ?? 0;
  const currentTitle = issue?.title || visibleAuthorTeamProgress?.currentLabel || activeStep?.label || "Preparing task";
  const currentDetail =
    issue?.message ||
    visibleAuthorTeamProgress?.currentDetail ||
    friendlyMessage(
      activeStep?.summary ||
        liveActivity ||
        (taskActive ? "Preparing the next playable part of your game." : "This generation step is complete."),
    );

  return (
    <Card className="gap-0 overflow-hidden rounded-xl border-slate-200/90 bg-white py-0 shadow-sm">
      <CardContent className="space-y-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
              <Sparkles size={23} />
            </span>
            <div className="min-w-0">
              <h2 className="font-display text-2xl font-semibold text-slate-950">{statusTitle}</h2>
              <p className="mt-1 text-sm text-slate-600">
                Step {Math.min(activeIndex + 1, rows.length)} of {rows.length}
                <span className="mx-1.5 text-slate-300">·</span>
                {activeStep?.label || "Preparing task"}
              </p>
            </div>
          </div>

          <div className="flex flex-col items-start gap-2 sm:items-end">
            <Badge
              className={cn(
                "gap-2 px-3 py-2",
                connectionStatus === "Connected"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-amber-200 bg-amber-50 text-amber-700",
              )}
              variant="outline"
            >
              <Circle size={9} fill="currentColor" />
              {connectionStatus}
            </Badge>
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
              <Clock3 size={13} />
              Last update {lastUpdated}
            </span>
          </div>
        </div>

        <div className="-mx-2 overflow-x-auto px-2 pb-1">
          <ol
            aria-label="Generation progress"
            className="grid min-w-[700px]"
            style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(72px, 1fr))` }}
          >
            {rows.map((step, index) => {
              const isActive = index === activeIndex && step.status !== "completed";
              return (
                <li className="relative min-w-0 text-center" key={step.key}>
                  {index < rows.length - 1 ? (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "absolute left-[calc(50%+18px)] right-[calc(-50%+18px)] top-4 h-px",
                        step.status === "completed" ? "bg-emerald-300" : "bg-slate-200",
                      )}
                    />
                  ) : null}
                  <StepMarker active={isActive} status={step.status} />
                  <span
                    className={cn(
                      "mx-auto mt-2 block max-w-[72px] px-1 text-[11px] font-medium leading-4",
                      isActive ? "text-indigo-700" : step.status === "completed" ? "text-slate-700" : "text-slate-400",
                    )}
                  >
                    {step.label}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>

        <section
          className={cn(
            "flex gap-3 rounded-xl border p-4",
            issue?.level === "error"
              ? "border-rose-200 bg-rose-50"
              : issue
                ? "border-amber-200 bg-amber-50"
                : "border-indigo-100 bg-indigo-50/70",
          )}
          aria-label="Current generation action"
        >
          <span
            className={cn(
              "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-white",
              issue?.level === "error" ? "text-rose-600" : issue ? "text-amber-600" : "text-indigo-600",
            )}
          >
            {issue?.level === "error" ? (
              <AlertCircle size={18} />
            ) : issue ? (
              <WandSparkles size={18} />
            ) : taskActive ? (
              <Loader2 className="size-5 animate-spin" />
            ) : (
              <Check size={18} />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-500">Current action</p>
            <h3 className="mt-1 text-sm font-semibold text-slate-950">{currentTitle}</h3>
            <p className="mt-1 text-sm leading-5 text-slate-600">{currentDetail}</p>
            {visibleAuthorTeamProgress ? (
              <div className="mt-3 border-t border-indigo-100 pt-3">
                <div className="mb-2 flex items-center justify-between gap-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  <span>Implementation team</span>
                  <span>{visibleAuthorTeamProgress.completedCount}/{visibleAuthorTeamProgress.roles.length} complete</span>
                </div>
                <AuthorTeamProgressList compact progress={visibleAuthorTeamProgress} />
              </div>
            ) : null}
          </div>
        </section>

        <div className="grid gap-3 sm:grid-cols-2">
          <Metric icon={<Database size={16} />} label="Tokens" value={tokenTotal.toLocaleString()} />
          <Metric icon={<Timer size={16} />} label="Elapsed" value={elapsed} />
        </div>

        <section className="border-t border-slate-200 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-display text-lg font-semibold text-slate-950">Recent activity</h3>
            <Button className="h-auto rounded-lg px-2 py-1 text-indigo-700" onClick={onOpenActivity} type="button" variant="ghost">
              View full activity
              <ArrowRight size={15} />
            </Button>
          </div>

          <div className="mt-2 divide-y divide-slate-100">
            {recentUpdates.map((update, index) => (
              <div className="grid grid-cols-[auto_1fr_auto] items-start gap-3 py-3 text-sm" key={`${update.message}-${index}`}>
                <span
                  className={cn(
                    "mt-1 flex size-5 items-center justify-center rounded-full border",
                    update.level === "error"
                      ? "border-rose-200 bg-rose-50 text-rose-600"
                      : update.level === "success"
                        ? "border-emerald-200 bg-emerald-50 text-emerald-600"
                        : "border-indigo-200 bg-indigo-50 text-indigo-600",
                  )}
                >
                  {update.level === "success" ? <Check size={12} /> : <Circle size={7} fill="currentColor" />}
                </span>
                <p className="min-w-0 leading-5 text-slate-700">{update.message}</p>
                <time className="whitespace-nowrap font-mono text-xs text-slate-400">{update.time}</time>
              </div>
            ))}
          </div>

          {liveFileChanges.length > 0 ? (
            <div className="grid gap-2 border-t border-slate-100 pt-3" aria-label="Live file changes">
              {liveFileChanges.map((change, index) => (
                <FileChangeRow change={change} key={`${change.action}-${change.path}-${index}`} />
              ))}
            </div>
          ) : null}
        </section>
      </CardContent>
    </Card>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <span className="flex size-8 items-center justify-center rounded-lg bg-slate-50 text-slate-500">{icon}</span>
      <div>
        <span className="text-xs font-medium text-slate-400">{label}</span>
        <strong className="block font-display text-lg font-semibold leading-5 text-slate-900">{value}</strong>
      </div>
    </div>
  );
}

function StepMarker({ active, status }: { active: boolean; status: StepState }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative z-10 mx-auto flex size-8 items-center justify-center rounded-full border-2 bg-white",
        status === "completed"
          ? "border-emerald-300 bg-emerald-500 text-white"
          : status === "failed"
            ? "border-rose-300 bg-rose-50 text-rose-700"
            : active
              ? "border-indigo-500 text-indigo-700"
              : "border-slate-200 text-slate-400",
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
