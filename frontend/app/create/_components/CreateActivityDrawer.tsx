"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock3,
  Database,
  ExternalLink,
  FileCode2,
  FileText,
  Loader2,
  Monitor,
  Play,
  RefreshCcw,
  Wrench,
  X,
} from "lucide-react";

import { AuthorTeamProgressList } from "./CreateAuthorTeamProgress";
import { FileChangeRow } from "./CreateFileChangeRow";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { getLiveTokenTotal, visibleAgentLogs } from "../_lib/agent-activity";
import { getAuthorTeamProgress } from "../_lib/author-team";
import {
  contextSourceLabel,
  latestAgentContext,
  type AgentContextSummary,
} from "../_lib/agent-events";
import {
  getGameplayQaStatus,
  gameplayTechLabel,
} from "../_lib/create-progress";
import { formatElapsed } from "../_lib/create-time";
import { getLogFileChanges, type FileChange } from "../_lib/file-changes";
import type { AgentLogItem, Task } from "@/lib/types";

type IndexedLog = {
  key: string;
  log: AgentLogItem;
  sourceIndex: number;
};

type ContextFileSummary = {
  action?: FileChange["action"];
  added: number;
  deleted: number;
  kind?: string | null;
  lines?: number | null;
  path: string;
  referenced?: boolean | null;
};

export function ActivityDrawer({ onClose, task }: { onClose: () => void; task?: Task }) {
  const logs = visibleAgentLogs(task);
  const agentContext = latestAgentContext(logs);
  const gameplayStatus = getGameplayQaStatus(task);
  const authorTeamProgress = getAuthorTeamProgress(task);
  const tokenTotal = getLiveTokenTotal(task) ?? task?.tokens ?? 0;
  const elapsed = formatElapsed(task?.created_at, Date.now());
  const designFields = task?.design?.fields ?? [];
  const allChanges = useMemo(() => logs.flatMap((log) => getLogFileChanges(log)), [logs]);
  const contextFiles = useMemo(() => buildContextFiles(agentContext, allChanges), [agentContext, allChanges]);
  const indexedLogs = useMemo<IndexedLog[]>(
    () => logs.map((log, sourceIndex) => ({ key: `${log.agent_name}-${log.step}-${sourceIndex}`, log, sourceIndex })),
    [logs],
  );
  const agentNames = useMemo(
    () => Array.from(new Set(logs.map((log) => log.agent_name).filter(Boolean))),
    [logs],
  );
  const defaultExpandedKeys = useMemo(
    () => indexedLogs.filter(({ log }, index) => log.status === "running" || index < 2).map(({ key }) => key),
    [indexedLogs],
  );
  const [agentFilter, setAgentFilter] = useState("all");
  const [expandedLogKeys, setExpandedLogKeys] = useState<string[] | null>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  const filteredLogs = agentFilter === "all"
    ? indexedLogs
    : indexedLogs.filter(({ log }) => log.agent_name === agentFilter);
  const expandedKeys = expandedLogKeys ?? defaultExpandedKeys;
  const statusSucceeded = task?.status === "succeeded";
  const previewHref = task?.game?.id ? `/play/${task.game.id}` : task?.preview_url || "";
  const dimension = findDesignField(designFields, ["dimension", "维度"]) || "Pending";
  const gameType = findDesignField(designFields, ["type", "类型"]) || "Pending";
  const theme = findDesignField(designFields, ["theme", "主题"]) || "Pending";

  const toggleLog = (key: string) => {
    setExpandedLogKeys((current) => {
      const next = new Set(current ?? defaultExpandedKeys);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return Array.from(next);
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-2 backdrop-blur-[2px] sm:p-4"
      onClick={onClose}
    >
      <section
        aria-label="Generation activity"
        aria-modal="true"
        className="flex h-[min(900px,calc(100dvh-1rem))] w-full max-w-[1380px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl sm:h-[min(900px,calc(100dvh-2rem))]"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <Tabs className="min-h-0 flex-1 gap-0" defaultValue="activity">
          <header className="flex flex-wrap items-center gap-4 border-b border-slate-200 px-4 py-5 sm:px-6">
            <div className="flex min-w-0 items-center gap-3 sm:min-w-[240px]">
              <span
                className="flex size-11 shrink-0 items-center justify-center rounded-xl text-white shadow-lg shadow-indigo-200"
                style={{ background: "var(--pf-grad)" }}
              >
                <Activity size={20} />
              </span>
              <div className="min-w-0">
                <h2 className="font-display text-xl font-semibold leading-6 text-slate-950">Activity</h2>
                <p className="truncate text-xs text-slate-500">{task?.game_title || "Generation task"}</p>
              </div>
            </div>
            <span aria-hidden="true" className="hidden h-6 w-px bg-slate-200 sm:block" />

            <TabsList className="order-3 h-auto w-full justify-start gap-2 rounded-none bg-transparent p-0 sm:order-none sm:w-auto">
              <TabsTrigger className="h-10 rounded-none border-x-0 border-t-0 border-b-2 border-transparent px-4 text-slate-600 focus-visible:border-x-0 focus-visible:border-t-0 focus-visible:bg-indigo-50 focus-visible:ring-0 focus-visible:outline-none data-[state=active]:border-indigo-500 data-[state=active]:bg-transparent data-[state=active]:text-indigo-700 data-[state=active]:shadow-none" value="overview">
                Overview
              </TabsTrigger>
              <TabsTrigger className="h-10 rounded-none border-x-0 border-t-0 border-b-2 border-transparent px-4 text-slate-600 focus-visible:border-x-0 focus-visible:border-t-0 focus-visible:bg-indigo-50 focus-visible:ring-0 focus-visible:outline-none data-[state=active]:border-indigo-500 data-[state=active]:bg-transparent data-[state=active]:text-indigo-700 data-[state=active]:shadow-none" value="activity">
                Activity
              </TabsTrigger>
              <TabsTrigger className="h-10 rounded-none border-x-0 border-t-0 border-b-2 border-transparent px-4 text-slate-600 focus-visible:border-x-0 focus-visible:border-t-0 focus-visible:bg-indigo-50 focus-visible:ring-0 focus-visible:outline-none data-[state=active]:border-indigo-500 data-[state=active]:bg-transparent data-[state=active]:text-indigo-700 data-[state=active]:shadow-none" value="files">
                Files
              </TabsTrigger>
            </TabsList>

            <div className="ml-auto flex items-center gap-2">
              <span
                className={cn(
                  "hidden items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-semibold sm:inline-flex",
                  statusSucceeded
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-slate-200 bg-slate-50 text-slate-600",
                )}
              >
                {statusSucceeded ? <CheckCircle2 size={14} /> : <Circle size={12} />}
                {statusLabel(task?.status)}
              </span>
              {previewHref ? (
                <Button asChild className="rounded-lg border-indigo-200 text-indigo-700 hover:bg-indigo-50 hover:text-indigo-800" variant="outline">
                  <a href={previewHref} rel="noreferrer" target="_blank">
                    <Play size={15} />
                    <span className="hidden sm:inline">Play preview</span>
                  </a>
                </Button>
              ) : null}
              <Button aria-label="Close activity" className="rounded-lg" onClick={onClose} size="icon" type="button" variant="ghost">
                <X size={19} />
              </Button>
            </div>
          </header>

          <TabsContent className="min-h-0 flex-1" value="activity">
            <div className="grid h-full min-h-0 overflow-auto xl:grid-cols-[280px_minmax(0,1fr)_340px] xl:overflow-hidden">
              <TaskSummary
                dimension={dimension}
                elapsed={elapsed}
                gameplayStatus={gameplayStatus ? gameplayTechLabel(gameplayStatus) : "Pending"}
                manifestUrl={task?.manifest_url || ""}
                status={task?.status}
                task={task}
                tokenTotal={tokenTotal}
              />

              <main className="order-1 min-h-[520px] min-w-0 border-t border-slate-200 bg-white xl:order-none xl:min-h-0 xl:overflow-y-auto xl:border-l xl:border-t-0">
                <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-white/95 px-5 py-4 backdrop-blur sm:px-7">
                  <div>
                    <h3 className="font-display text-lg font-semibold text-slate-950">Activity timeline</h3>
                    <p className="mt-0.5 text-xs text-slate-500">Agent decisions, implementation notes, and checks.</p>
                  </div>
                  <label className="relative">
                    <span className="sr-only">Filter by agent</span>
                    <select
                      className="h-9 appearance-none rounded-lg border border-slate-200 bg-slate-50 py-0 pl-3 pr-9 text-xs font-semibold text-slate-700 outline-none transition focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                      onChange={(event) => setAgentFilter(event.target.value)}
                      value={agentFilter}
                    >
                      <option value="all">All agents</option>
                      {agentNames.map((agentName) => <option key={agentName} value={agentName}>{agentName}</option>)}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-3 top-2.5 size-4 text-slate-400" />
                  </label>
                </div>

                <div className="px-5 py-2 sm:px-7">
                  {filteredLogs.length === 0 ? (
                    <EmptyState>No activity for this filter yet.</EmptyState>
                  ) : (
                    <ol aria-label="Agent activity timeline">
                      {filteredLogs.map(({ key, log, sourceIndex }, visibleIndex) => (
                        <TimelineLog
                          authorTeamProgress={authorTeamProgress}
                          expanded={expandedKeys.includes(key)}
                          isLast={visibleIndex === filteredLogs.length - 1}
                          key={key}
                          log={log}
                          onToggle={() => toggleLog(key)}
                          sourceIndex={sourceIndex}
                        />
                      ))}
                    </ol>
                  )}
                </div>
              </main>

              <ContextInspector
                context={agentContext}
                contextFiles={contextFiles}
                designFields={designFields}
                dimension={dimension}
                gameType={gameType}
                manifestUrl={task?.manifest_url || ""}
                previewUrl={task?.preview_url || previewHref}
                theme={theme}
              />
            </div>
          </TabsContent>

          <TabsContent className="min-h-0 flex-1 overflow-auto bg-slate-50/60 p-5 sm:p-7" value="overview">
            <div className="mx-auto grid max-w-5xl gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
              <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
                <p className="text-xs font-bold uppercase tracking-[0.14em] text-indigo-600">Task overview</p>
                <h3 className="mt-2 font-display text-2xl font-semibold text-slate-950">{task?.game_title || "Generation task"}</h3>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                  A compact view of task health, implementation progress, and the context used by the authoring agents.
                </p>
                {authorTeamProgress ? (
                  <div className="mt-6 border-t border-slate-100 pt-5">
                    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                      <div>
                        <h4 className="font-display text-lg font-semibold text-slate-950">Implementation team</h4>
                        <p className="mt-1 text-sm text-slate-500">{authorTeamProgress.currentDetail}</p>
                      </div>
                      <span className="text-xs font-semibold text-slate-500">
                        {authorTeamProgress.completedCount}/{authorTeamProgress.roles.length} complete
                      </span>
                    </div>
                    <AuthorTeamProgressList progress={authorTeamProgress} />
                  </div>
                ) : null}
              </section>
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h3 className="font-display text-lg font-semibold text-slate-950">At a glance</h3>
                <div className="mt-4 divide-y divide-slate-100">
                  <DetailRow label="Status" value={statusLabel(task?.status)} />
                  <DetailRow label="Gameplay QA" value={gameplayStatus ? gameplayTechLabel(gameplayStatus) : "Pending"} />
                  <DetailRow label="Elapsed" value={elapsed} />
                  <DetailRow label="Dimension" value={dimension} />
                  <DetailRow label="Tokens" value={tokenTotal.toLocaleString()} />
                </div>
              </section>
            </div>
          </TabsContent>

          <TabsContent className="min-h-0 flex-1 overflow-auto bg-slate-50/60 p-5 sm:p-7" value="files">
            <div className="mx-auto max-w-5xl">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h3 className="font-display text-2xl font-semibold text-slate-950">Changed files</h3>
                  <p className="mt-1 text-sm text-slate-500">Files created or updated while this task was running.</p>
                </div>
                <span className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600">
                  {contextFiles.length} files in context
                </span>
              </div>
              {allChanges.length > 0 ? (
                <div className="mt-5 grid gap-3 lg:grid-cols-2">
                  {allChanges.map((change, index) => (
                    <FileChangeRow change={change} key={`${change.action}-${change.path}-${index}`} showDiff />
                  ))}
                </div>
              ) : (
                <div className="mt-5"><EmptyState>No file changes have been reported yet.</EmptyState></div>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </section>
    </div>
  );
}

function TaskSummary({
  dimension,
  elapsed,
  gameplayStatus,
  manifestUrl,
  status,
  task,
  tokenTotal,
}: {
  dimension: string;
  elapsed: string;
  gameplayStatus: string;
  manifestUrl: string;
  status?: string;
  task?: Task;
  tokenTotal: number;
}) {
  return (
    <aside className="order-2 border-t border-slate-200 bg-white px-5 py-5 xl:order-none xl:overflow-y-auto xl:border-t-0">
      <h3 className="font-display text-base font-semibold text-slate-950">Task summary</h3>
      <div className="mt-6 space-y-6">
        <SummaryMetric icon={<CheckCircle2 size={17} />} label="Status" tone={status === "succeeded" ? "success" : "neutral"} value={statusLabel(status)} />
        <SummaryMetric icon={<Clock3 size={17} />} label="Elapsed time" value={elapsed} />
        <SummaryMetric icon={<CheckCircle2 size={17} />} label="Gameplay QA" tone={gameplayStatus === "Passed" ? "success" : "neutral"} value={gameplayStatus} />
        <div className="border-t border-slate-100 pt-6">
          <div className="space-y-6">
            <SummaryMetric icon={<Database size={17} />} label="Tokens" value={tokenTotal.toLocaleString()} />
            <SummaryMetric icon={<Wrench size={17} />} label="Repair attempts" value={`${task?.repair_attempts ?? 0}/${task?.max_repair_attempts ?? 2}`} />
            <SummaryMetric icon={<RefreshCcw size={17} />} label="Replan attempts" value={`${task?.replan_attempts ?? 0}/${task?.max_replan_attempts ?? 1}`} />
            <SummaryMetric icon={<Monitor size={17} />} label="Game dimension" value={dimension} />
            {manifestUrl ? (
              <div>
                <p className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">
                  <ExternalLink size={15} /> Manifest
                </p>
                <a className="mt-2 block truncate text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:underline" href={manifestUrl} rel="noreferrer" target="_blank">
                  {manifestUrl}
                </a>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </aside>
  );
}

function SummaryMetric({ icon, label, tone = "neutral", value }: { icon: ReactNode; label: string; tone?: "neutral" | "success"; value: string }) {
  return (
    <div>
      <p className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">{icon}{label}</p>
      <strong className={cn("mt-2 block text-sm font-semibold", tone === "success" ? "text-emerald-700" : "text-slate-900")}>{value}</strong>
    </div>
  );
}

function TimelineLog({
  authorTeamProgress,
  expanded,
  isLast,
  log,
  onToggle,
}: {
  authorTeamProgress: ReturnType<typeof getAuthorTeamProgress>;
  expanded: boolean;
  isLast: boolean;
  log: AgentLogItem;
  onToggle: () => void;
  sourceIndex: number;
}) {
  const changes = getLogFileChanges(log);
  const changeLines = new Set(changes.map((change) => change.line));
  const visibleLines = (log.lines.length ? log.lines : [log.message]).filter((line) => line && !changeLines.has(line));
  const showTeam = Boolean(
    authorTeamProgress && (log.status === "running" || /code|author|implement|generation/i.test(`${log.agent_name} ${log.step}`)),
  );

  return (
    <li className="relative grid grid-cols-[34px_minmax(0,1fr)] gap-3 py-4">
      {!isLast ? <span aria-hidden="true" className="absolute bottom-0 left-4 top-10 w-px bg-slate-200" /> : null}
      <TimelineMarker status={log.status} />
      <div className="min-w-0">
        <button className="flex w-full items-start justify-between gap-4 text-left" onClick={onToggle} type="button">
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <strong className="font-display text-base font-semibold text-slate-950">{log.step || log.agent_name}</strong>
              {log.status === "running" ? (
                <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700">Running</span>
              ) : null}
            </span>
            <span className="mt-1 line-clamp-2 block text-sm leading-5 text-slate-500">{log.message || log.agent_name}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 pt-0.5 text-xs text-slate-400">
            {log.duration ? <time className="font-mono">{log.duration}</time> : null}
            {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </span>
        </button>

        {expanded ? (
          <div className={cn("mt-3 space-y-3 rounded-xl border p-3", log.status === "running" ? "border-indigo-100 bg-indigo-50/50" : "border-slate-200 bg-slate-50/70")}>
            {visibleLines.length > 0 ? (
              <div className="space-y-1 font-mono text-xs leading-5 text-slate-600">
                {visibleLines.slice(-5).map((line, lineIndex) => <p className="line-clamp-2 break-words" key={`${line}-${lineIndex}`}>• {line}</p>)}
              </div>
            ) : null}
            {changes.length > 0 ? (
              <div className="divide-y divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white">
                {changes.map((change, changeIndex) => (
                  <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-3 py-2 text-xs" key={`${change.action}-${change.path}-${changeIndex}`}>
                    <FileCode2 className="size-4 text-slate-400" />
                    <span className="truncate font-mono text-slate-700">{change.path}</span>
                    <span className="flex gap-2 font-semibold"><b className="text-emerald-600">+{change.added}</b><b className="text-rose-600">-{change.deleted}</b></span>
                  </div>
                ))}
              </div>
            ) : null}
            {showTeam && authorTeamProgress ? (
              <div className="border-t border-indigo-100 pt-3">
                <div className="mb-2 flex items-center justify-between gap-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  <span>Implementation team</span>
                  <span>{authorTeamProgress.completedCount}/{authorTeamProgress.roles.length} complete</span>
                </div>
                <AuthorTeamProgressList compact progress={authorTeamProgress} />
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function TimelineMarker({ status }: { status: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative z-[1] flex size-8 items-center justify-center rounded-full border-2 bg-white",
        status === "completed"
          ? "border-emerald-500 bg-emerald-500 text-white"
          : status === "failed"
            ? "border-rose-400 bg-rose-50 text-rose-600"
            : status === "running"
              ? "border-indigo-500 text-indigo-600"
              : "border-slate-300 text-slate-400",
      )}
    >
      {status === "completed" ? <Check size={15} /> : status === "running" ? <Loader2 className="size-4 animate-spin" /> : <Circle size={12} />}
    </span>
  );
}

function ContextInspector({
  context,
  contextFiles,
  designFields,
  dimension,
  gameType,
  manifestUrl,
  previewUrl,
  theme,
}: {
  context: AgentContextSummary;
  contextFiles: ContextFileSummary[];
  designFields: NonNullable<Task["design"]>["fields"];
  dimension: string;
  gameType: string;
  manifestUrl: string;
  previewUrl: string;
  theme: string;
}) {
  return (
    <aside className="order-3 border-t border-slate-200 bg-slate-50/45 px-5 py-5 xl:order-none xl:overflow-y-auto xl:border-l xl:border-t-0">
      <h3 className="font-display text-base font-semibold text-slate-950">Agent context</h3>
      <div className="mt-6">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">Files in context</p>
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-500">
            <FileText size={12} /> {contextFiles.length}
          </span>
        </div>
        {contextFiles.length > 0 ? (
          <div className="mt-3 divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
            {contextFiles.slice(0, 6).map((file) => (
              <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-3 py-3" key={file.path}>
                <FileCode2 className="size-4 text-indigo-500" />
                <div className="min-w-0">
                  <strong className="block truncate font-mono text-[11px] text-slate-800">{file.path}</strong>
                  <span className="mt-0.5 block text-[10px] text-slate-400">
                    {file.kind || "file"}{file.lines ? ` · ${file.lines} lines` : ""}{file.referenced ? " · referenced" : ""}
                  </span>
                </div>
                {file.added || file.deleted ? (
                  <span className="flex gap-1 text-[10px] font-bold"><b className="text-emerald-600">+{file.added}</b><b className="text-rose-600">-{file.deleted}</b></span>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3"><EmptyState>No agent context yet.</EmptyState></div>
        )}
      </div>

      <div className="mt-6 border-t border-slate-200 pt-6">
        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">Technical details</p>
        <div className="mt-3 divide-y divide-slate-200">
          <DetailRow href={manifestUrl} label="Manifest URL" value={manifestUrl || "Pending"} />
          <DetailRow href={previewUrl} label="Preview URL" value={previewUrl || "Pending"} />
          <DetailRow label="Dimension" value={dimension} />
          <DetailRow label="Type" value={gameType} />
          <DetailRow label="Theme" value={theme} />
          {designFields
            .filter((field) => !["dimension", "维度", "type", "类型", "theme", "主题"].some((label) => field.label.toLowerCase() === label.toLowerCase()))
            .slice(0, 2)
            .map((field) => <DetailRow key={field.label} label={field.label} value={field.value} />)}
        </div>
      </div>

      {context.filesInContext.length > 0 ? (
        <div className="mt-6 border-t border-slate-200 pt-6">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">Record sources</p>
          <div className="mt-3 space-y-2">
            {context.filesInContext.slice(0, 4).map((file) => (
              <div className="flex items-center justify-between gap-3 text-xs" key={file.path}>
                <span className="min-w-0 truncate font-mono text-slate-700">{file.path}</span>
                <span className="shrink-0 text-[10px] text-slate-400">{contextSourceLabel(file.record_source)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  );
}

function DetailRow({ href, label, value }: { href?: string; label: string; value: string }) {
  return (
    <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-3 py-3 text-xs">
      <span className="text-slate-500">{label}</span>
      {href ? (
        <a className="flex min-w-0 items-start gap-1 font-medium text-indigo-600 hover:text-indigo-800 hover:underline" href={href} rel="noreferrer" target="_blank">
          <span className="min-w-0 break-all">{value}</span><ExternalLink className="mt-0.5 size-3 shrink-0" />
        </a>
      ) : (
        <strong className="min-w-0 break-words font-semibold text-slate-800">{value}</strong>
      )}
    </div>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-slate-200 bg-white p-6 text-center text-sm text-slate-500">{children}</p>;
}

function findDesignField(fields: NonNullable<Task["design"]>["fields"], labels: string[]) {
  const normalized = labels.map((label) => label.toLowerCase());
  return fields.find((field) => normalized.includes(field.label.toLowerCase()))?.value;
}

function statusLabel(status?: string) {
  if (!status) return "No active task";
  if (status === "succeeded") return "Succeeded";
  if (status === "in_progress" || status === "running") return "In progress";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Cancelled";
  return status.replaceAll("_", " ");
}

function buildContextFiles(context: AgentContextSummary, changes: FileChange[]): ContextFileSummary[] {
  const byPath = new Map<string, ContextFileSummary>();
  context.files.forEach((file) => {
    if (!file.path) return;
    byPath.set(file.path, {
      added: 0,
      deleted: 0,
      kind: file.kind,
      lines: file.lines,
      path: file.path,
      referenced: file.referenced,
    });
  });
  changes.forEach((change) => {
    const current = byPath.get(change.path) ?? { added: 0, deleted: 0, path: change.path };
    byPath.set(change.path, {
      ...current,
      action: change.action,
      added: current.added + change.added,
      deleted: current.deleted + change.deleted,
    });
  });
  return Array.from(byPath.values()).sort((a, b) => (b.added + b.deleted) - (a.added + a.deleted));
}
