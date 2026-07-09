"use client";

import { useMemo } from "react";
import {
  AlertCircle,
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  Edit3,
  FileImage,
  FileText,
  Gamepad2,
  Image as ImageIcon,
  Loader2,
  MoreHorizontal,
  Play,
  RefreshCcw,
  Sparkles,
  Timer,
  Trash2,
  UploadCloud,
  WandSparkles,
  X,
} from "lucide-react";

import {
  buildStepRows,
  contextSourceLabel,
  fileChangeLabel,
  formatElapsed,
  formatRelative,
  getActiveStepIndex,
  getBrief,
  getCurrentIssue,
  getGameplayQaStatus,
  getLiveAgentActivity,
  getLiveFileChanges,
  getLiveStreamTokens,
  getLogFileChanges,
  getProgressTitle,
  getRecentUpdates,
  gameplayRuntimeLabel,
  gameplayTechLabel,
  isActiveTask,
  latestAgentContext,
  visibleAgentLogs,
  type AgentContextSummary,
  type FileChange,
  type StepRow,
} from "../_lib/create-state";
import type { Task, UploadedAsset } from "@/lib/types";

export function TaskMissingCard({ onBack }: { onBack: () => void }) {
  return (
    <article className="pf-create-card pf-action-card">
      <AlertCircle size={20} />
      <h2>Task not found</h2>
      <p className="pf-action-note">
        This generation task no longer exists — it may have been deleted, or the link is stale.
      </p>
      <button className="pf-primary-wide" onClick={onBack} type="button">
        Start a new game
      </button>
    </article>
  );
}

export function CreateInput({
  busy,
  dimension,
  files,
  idea,
  now,
  onGenerate,
  onOpenActivity,
  onPickFiles,
  onRemoveFile,
  onResumeLast,
  onSetDimension,
  onSetIdea,
  remixSourceTitle,
  uploading,
}: {
  busy: boolean;
  dimension: "2d" | "3d";
  files: UploadedAsset[];
  idea: string;
  now: number;
  onGenerate: () => void;
  onOpenActivity: () => void;
  onPickFiles: (files: FileList | File[] | null) => void;
  onRemoveFile: (id: string) => void;
  onResumeLast?: () => void;
  onSetDimension: (dimension: "2d" | "3d") => void;
  onSetIdea: (idea: string) => void;
  remixSourceTitle?: string;
  uploading: boolean;
}) {
  const examples = ["Cyberpunk cat runner", "Cozy forest puzzle", "Pixel racing game"];
  const canGenerate = idea.trim().length > 0 && !busy && !uploading;

  return (
    <div className="pf-create-grid">
      <div className="pf-create-main">
        {onResumeLast && (
          <button className="pf-resume-banner" onClick={onResumeLast} type="button">
            <RefreshCcw size={15} />
            <span>Continue your last generation task</span>
            <ArrowRight size={15} />
          </button>
        )}
        <article className="pf-create-card pf-input-card">
          <div className="pf-input-heading">
            <span className="pf-orb-icon">
              <WandSparkles size={30} />
            </span>
            <div>
              <h2>{remixSourceTitle ? `Remix ${remixSourceTitle}` : "What do you want to create?"}</h2>
              <p>
                {remixSourceTitle
                  ? "Describe the gameplay, visual, or rule changes for this remix."
                  : "Give GameWeave a playable concept, reference style, rules, and win conditions."}
              </p>
            </div>
          </div>

          <label className="pf-field-label" htmlFor="idea">
            Game idea
          </label>
          <textarea
            className="pf-prompt-input"
            id="idea"
            onChange={(event) => onSetIdea(event.target.value)}
            placeholder="Example: Make a 2D cyberpunk runner where a street-smart cat dodges drones, hacks neon terminals, and survives for 90 seconds."
            value={idea}
          />

          <div className="pf-example-row">
            {examples.map((example) => (
              <button key={example} onClick={() => onSetIdea(example)} type="button">
                {example}
              </button>
            ))}
          </div>

          <label className="pf-field-label" style={{ marginTop: 18 }}>
            Render mode
          </label>
          <div aria-label="Render mode" className="pf-dimension-row" role="group">
            {(["2d", "3d"] as const).map((d) => (
              <button
                aria-pressed={dimension === d}
                className={`pf-dimension-option${dimension === d ? " is-active" : ""}`}
                key={d}
                onClick={() => onSetDimension(d)}
                type="button"
              >
                <span className="pf-dimension-title">{d === "2d" ? "2D · Canvas" : "3D · WebGL"}</span>
                <span className="pf-dimension-sub">
                  {d === "2d" ? "Classic 2D arcade — fast and reliable" : "Real 3D via Three.js — FPS, runner, racer"}
                </span>
              </button>
            ))}
          </div>
          {dimension === "3d" && (
            <p className="pf-dimension-note">
              <AlertCircle size={15} />
              3D is authored by the AI model directly — enable real-model generation for the best result.
            </p>
          )}

          <label
            className="pf-upload-zone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              onPickFiles(event.dataTransfer.files);
            }}
          >
            {uploading ? <Loader2 className="pf-spin" size={30} /> : <UploadCloud size={30} />}
            <strong>{uploading ? "Uploading…" : "Upload references"}</strong>
            <span>Drop images, video, or files here. Up to 6 assets, 10MB each.</span>
            <input
              multiple
              onChange={(event) => {
                onPickFiles(event.target.files);
                event.currentTarget.value = "";
              }}
              type="file"
            />
          </label>

          {files.length > 0 && (
            <div className="pf-uploaded-assets">
              {files.map((file) => (
                <div className="pf-uploaded-asset" key={file.id}>
                  {file.kind === "image" && file.url ? (
                    <img alt="" src={file.url} />
                  ) : (
                    <span>
                      <FileImage size={18} />
                    </span>
                  )}
                  <strong>{file.name}</strong>
                  <button aria-label={`Remove ${file.name}`} onClick={() => onRemoveFile(file.id)} type="button">
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button className="pf-generate-btn" disabled={!canGenerate} onClick={onGenerate} type="button">
            {busy ? <Loader2 className="pf-spin" size={18} /> : <Sparkles size={18} />}
            {busy ? "Starting task..." : "Generate Game"}
          </button>
        </article>
      </div>

      <aside className="pf-create-side">
        <PreviewCard now={now} task={undefined} />
        <ActionPanel
          onCancel={() => undefined}
          onOpenActivity={onOpenActivity}
          onPreview={() => undefined}
          onPublish={() => undefined}
          onRevision={() => undefined}
          onRetry={() => undefined}
          publishing={false}
          revisionFeedback=""
          revising={false}
          setRevisionFeedback={() => undefined}
          task={undefined}
        />
      </aside>
    </div>
  );
}

export function CreateWorkspace({
  connectionStatus,
  files,
  now,
  onCancel,
  onEditBrief,
  onOpenActivity,
  onPreview,
  onPublish,
  onRevision,
  onRetry,
  publishing,
  revisionFeedback,
  revising,
  setRevisionFeedback,
  task,
}: {
  connectionStatus: string;
  files: UploadedAsset[];
  now: number;
  onCancel: () => void;
  onEditBrief: () => void;
  onOpenActivity: () => void;
  onPreview: () => void;
  onPublish: () => void;
  onRevision: () => void;
  onRetry: () => void;
  publishing: boolean;
  revisionFeedback: string;
  revising: boolean;
  setRevisionFeedback: (value: string) => void;
  task?: Task;
}) {
  const rows = useMemo(() => buildStepRows(task), [task]);
  const activeIndex = getActiveStepIndex(rows, task);
  const activeStep = rows[activeIndex] ?? rows[0];
  const issue = getCurrentIssue(task, activeStep);
  const recentUpdates = getRecentUpdates(task, now);
  const brief = getBrief(task, files);

  return (
    <div className="pf-create-grid">
      <div className="pf-create-main">
        <GameBriefCard brief={brief} onEditBrief={onEditBrief} />
        <ProgressCard
          activeIndex={activeIndex}
          activeStep={activeStep}
          connectionStatus={connectionStatus}
          issue={issue}
          now={now}
          onOpenActivity={onOpenActivity}
          recentUpdates={recentUpdates}
          rows={rows}
          task={task}
        />
      </div>

      <aside className="pf-create-side">
        <PreviewCard now={now} task={task} />
        <ActionPanel
          onCancel={onCancel}
          onOpenActivity={onOpenActivity}
          onPreview={onPreview}
          onPublish={onPublish}
          onRevision={onRevision}
          onRetry={onRetry}
          publishing={publishing}
          revisionFeedback={revisionFeedback}
          revising={revising}
          setRevisionFeedback={setRevisionFeedback}
          task={task}
        />
      </aside>
    </div>
  );
}

function GameBriefCard({
  brief,
  onEditBrief,
}: {
  brief: { title: string; assetCount: number; genre: string; style: string; runtime: string };
  onEditBrief: () => void;
}) {
  return (
    <article className="pf-create-card pf-brief-card">
      <span className="pf-brief-icon">
        <FileText size={30} />
      </span>
      <div className="pf-brief-copy">
        <h2>Game brief</h2>
        <div className="pf-brief-chip">{brief.title}</div>
        <div className="pf-brief-meta">
          <ImageIcon size={16} />
          <span>
            {brief.assetCount} asset{brief.assetCount === 1 ? "" : "s"} uploaded
          </span>
          <i />
          <span>{brief.genre}</span>
          <i />
          <span>{brief.style}</span>
          <i />
          <span>{brief.runtime}</span>
        </div>
      </div>
      <button className="pf-edit-brief" onClick={onEditBrief} type="button">
        <Edit3 size={16} />
        Edit brief
      </button>
    </article>
  );
}

function ProgressCard({
  activeIndex,
  activeStep,
  connectionStatus,
  issue,
  now,
  onOpenActivity,
  recentUpdates,
  rows,
  task,
}: {
  activeIndex: number;
  activeStep: StepRow;
  connectionStatus: string;
  issue: ReturnType<typeof getCurrentIssue>;
  now: number;
  onOpenActivity: () => void;
  recentUpdates: Array<{ level: "info" | "success" | "warning" | "error"; message: string; time: string }>;
  rows: StepRow[];
  task?: Task;
}) {
  const statusTitle = getProgressTitle(task);
  const lastUpdated = formatRelative(task?.updated_at || task?.created_at, now) || "Waiting";
  const elapsed = formatElapsed(task?.created_at, now);
  const taskActive = isActiveTask(task?.status);
  const liveTokens = getLiveStreamTokens(task);
  const liveActivity = liveTokens === null && taskActive ? getLiveAgentActivity(task) : "";
  const liveFileChanges = getLiveFileChanges(task).slice(-4);

  return (
    <article className="pf-create-card pf-progress-card">
      <div className="pf-progress-head">
        <span className="pf-orb-icon">
          <Sparkles size={30} />
        </span>
        <div className="pf-progress-title">
          <h2>{statusTitle}</h2>
          <p>
            Step {Math.min(activeIndex + 1, rows.length)} of {rows.length}
            <span> - </span>
            {activeStep?.label || "Preparing task"}
          </p>
        </div>
        <div className="pf-leave-note">
          <ArrowRight size={15} />
          You can leave this page
        </div>
      </div>

      <div className="pf-status-pills">
        <span>
          <Clock3 size={15} />
          Last update {lastUpdated}
        </span>
        <span className={connectionStatus === "Connected" ? "is-connected" : "is-warning"}>
          <Circle size={10} fill="currentColor" />
          {connectionStatus}
        </span>
        <span>
          <Timer size={15} />
          Elapsed {elapsed}
        </span>
      </div>

      {liveTokens !== null && taskActive && (
        <div className="pf-live-token-row" aria-label="Live output tokens">
          <span>tokens</span>
          <strong key={liveTokens}>{liveTokens.toLocaleString()}</strong>
        </div>
      )}

      {liveActivity && (
        <div className="pf-live-activity-row" aria-label="Live agent activity">
          <span>activity</span>
          <strong>{liveActivity}</strong>
        </div>
      )}

      {liveFileChanges.length > 0 && (
        <div className="pf-file-change-panel" aria-label="Live file changes">
          <div className="pf-file-change-list">
            {liveFileChanges.map((change) => (
              <FileChangeRow change={change} key={`${change.action}-${change.path}-${change.line}`} />
            ))}
          </div>
        </div>
      )}

      <div className="pf-step-list">
        {rows.map((step, index) => {
          const isActive = index === activeIndex && step.status !== "completed";
          return (
            <div className={`pf-step-row is-${step.status}${isActive ? " is-active" : ""}`} key={step.key}>
              <span className="pf-step-marker">
                {step.status === "completed" ? <Check size={14} /> : step.status === "failed" ? <AlertCircle size={14} /> : isActive ? <Loader2 className="pf-spin" size={14} /> : null}
              </span>
              <div className="pf-step-body">
                <strong>{step.label}</strong>
                {isActive && issue && (
                  <div className={`pf-issue-box is-${issue.level}`}>
                    <span>
                      {issue.level === "error" ? <AlertCircle size={17} /> : <WandSparkles size={17} />}
                    </span>
                    <div>
                      <b>{issue.title}</b>
                      <p>{issue.message}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="pf-recent-updates">
        <h3>Recent updates</h3>
        {recentUpdates.map((update, index) => (
          <div className={`pf-update-row is-${update.level}`} key={`${update.message}-${index}`}>
            <span />
            <time>{update.time}</time>
            <p>{update.message}</p>
          </div>
        ))}
        <button onClick={onOpenActivity} type="button">
          View full activity
          <ArrowRight size={16} />
        </button>
      </div>
    </article>
  );
}

function PreviewCard({ now, task }: { now: number; task?: Task }) {
  const succeeded = task?.status === "succeeded" && task.game;
  const previewAvailable = Boolean(task?.game);
  const previewSrc = task?.game?.bundle_url || task?.preview_url || (task?.game ? `/play/${task.game.id}` : "");
  const active = isActiveTask(task?.status);
  const failed = task?.status === "failed";
  const cancelled = task?.status === "cancelled";
  const gameplayStatus = getGameplayQaStatus(task);
  const statusLine = succeeded
    ? "Preview ready"
    : failed
      ? "Preview unavailable"
      : cancelled
        ? "Task cancelled"
        : active
          ? "Preparing runtime..."
          : "Your playable preview will appear here.";

  return (
    <article className="pf-create-card pf-preview-card">
      <h2>
        Preview
        <Gamepad2 size={19} />
      </h2>

      {previewAvailable ? (
        <div className="pf-preview-frame">
          <iframe
            sandbox="allow-scripts allow-pointer-lock"
            src={previewSrc}
            title={`${task?.game?.title || "Game"} preview`}
          />
        </div>
      ) : (
        <img alt="" className="pf-runtime-art" src="/gameweave/create-runtime-preview.png" />
      )}

      <h3>{statusLine}</h3>

      <div className="pf-runtime-list">
        {/* 沙箱在预览 iframe 挂载时才真实存在，不再恒显 ready */}
        <RuntimeRow label={previewAvailable ? "Sandboxed preview mounted" : "Sandbox pending"} ready={previewAvailable} />
        {gameplayStatus && (
          <RuntimeRow label={gameplayRuntimeLabel(gameplayStatus)} ready={gameplayStatus === "completed"} />
        )}
        <RuntimeRow label={succeeded ? "Manifest uploaded" : "Manifest pending"} ready={Boolean(task?.manifest_url)} />
        <RuntimeRow label={succeeded ? "Bundle ready" : "Bundle pending"} ready={Boolean(succeeded)} />
      </div>

      {task && !succeeded && isActiveTask(task.status) && (
        <p className="pf-heartbeat">
          Last heartbeat {formatRelative(task.updated_at || task.created_at, now) || "just now"}
        </p>
      )}
    </article>
  );
}

function RuntimeRow({ label, ready }: { label: string; ready?: boolean }) {
  return (
    <div className={`pf-runtime-row${ready ? " is-ready" : ""}`}>
      <span>{ready ? <Check size={15} /> : <MoreHorizontal size={17} />}</span>
      <p>{label}</p>
    </div>
  );
}

function ActionPanel({
  onCancel,
  onOpenActivity,
  onPreview,
  onPublish,
  onRevision,
  onRetry,
  publishing,
  revisionFeedback,
  revising,
  setRevisionFeedback,
  task,
}: {
  onCancel: () => void;
  onOpenActivity: () => void;
  onPreview: () => void;
  onPublish: () => void;
  onRevision: () => void;
  onRetry: () => void;
  publishing: boolean;
  revisionFeedback: string;
  revising: boolean;
  setRevisionFeedback: (value: string) => void;
  task?: Task;
}) {
  const succeeded = task?.status === "succeeded" && task.game;
  const failed = task?.status === "failed";
  const cancelled = task?.status === "cancelled";
  const active = isActiveTask(task?.status);

  return (
    <article className="pf-create-card pf-action-card">
      <button className="pf-outline-wide" onClick={onOpenActivity} type="button">
        <BarChart3 size={18} />
        View Activity
      </button>

      {succeeded && (
        <>
          <button className="pf-outline-wide" onClick={onPreview} type="button">
            <Play size={17} />
            Play Preview
          </button>
          <button className="pf-primary-wide" disabled={publishing} onClick={onPublish} type="button">
            {publishing ? <Loader2 className="pf-spin" size={17} /> : <CheckCircle2 size={17} />}
            {publishing ? "Publishing..." : "Publish to Home"}
          </button>
          <div className="pf-revision-form">
            <label htmlFor="preview-feedback">What should change?</label>
            <textarea
              id="preview-feedback"
              maxLength={2000}
              onChange={(event) => setRevisionFeedback(event.target.value)}
              placeholder="Describe the feel, behavior, visuals, or rules you want changed. Your wording is preserved."
              value={revisionFeedback}
            />
            <button
              className="pf-outline-wide"
              disabled={revising || !revisionFeedback.trim()}
              onClick={onRevision}
              type="button"
            >
              {revising ? <Loader2 className="pf-spin" size={17} /> : <WandSparkles size={17} />}
              {revising ? "Starting revision..." : "Apply feedback to this version"}
            </button>
          </div>
        </>
      )}

      {failed && (
        <>
          <button className="pf-primary-wide" onClick={onRetry} type="button">
            <RefreshCcw size={17} />
            Retry from validation
          </button>
          <p className="pf-action-note">{task?.error || "Generation stopped before a playable preview was created."}</p>
        </>
      )}

      {cancelled && <p className="pf-action-note">This task was cancelled. Start a new version from the brief when you are ready.</p>}

      {active && (
        <button className="pf-danger-link" onClick={onCancel} type="button">
          <Trash2 size={17} />
          Cancel task
        </button>
      )}
    </article>
  );
}

function designField(task: Task | undefined, label: string) {
  return task?.design?.fields.find((field) => field.label === label)?.value;
}

export function ActivityDrawer({ onClose, task }: { onClose: () => void; task?: Task }) {
  const logs = visibleAgentLogs(task);
  const agentContext = latestAgentContext(logs);
  const gameplayStatus = getGameplayQaStatus(task);
  const archetype = designField(task, "玩法原型");
  const mechanic = designField(task, "核心机制");
  const balance = designField(task, "平衡参数");
  const contentWaves = designField(task, "内容波次");

  return (
    <div className="pf-drawer-backdrop" onClick={onClose}>
      <aside className="pf-drawer" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h2>Activity</h2>
            <p>{task?.game_title || "Generation task"}</p>
          </div>
          <button aria-label="Close activity" onClick={onClose} type="button">
            <X size={18} />
          </button>
        </header>

        <section className="pf-drawer-section">
          <h3>Technical details</h3>
          <div className="pf-tech-grid">
            <TechItem label="Task status" value={task?.status || "No active task"} />
            <TechItem label="Manifest" value={task?.manifest_url || "Pending"} />
            <TechItem label="Preview" value={task?.preview_url || "Pending"} />
            {gameplayStatus && <TechItem label="Gameplay QA" value={gameplayTechLabel(gameplayStatus)} />}
            {archetype && <TechItem label="Archetype" value={archetype} />}
            {mechanic && <TechItem label="Mechanic" value={mechanic} />}
            {balance && <TechItem label="Balance" value={balance} />}
            {contentWaves && <TechItem label="Content" value={contentWaves} />}
            <TechItem label="Repair attempts" value={`${task?.repair_attempts ?? 0}/${task?.max_repair_attempts ?? 2}`} />
            <TechItem label="Replan attempts" value={`${task?.replan_attempts ?? 0}/${task?.max_replan_attempts ?? 1}`} />
            <TechItem label="Tokens" value={(task?.tokens ?? 0).toLocaleString()} />
          </div>
        </section>

        <section className="pf-drawer-section">
          <h3>Agent context</h3>
          <AgentContextPanel context={agentContext} />
        </section>

        <section className="pf-drawer-section">
          <h3>Agent activity</h3>
          {logs.length === 0 ? (
            <p className="pf-empty-state">No activity yet.</p>
          ) : (
            logs.map((log, index) => {
              const changes = getLogFileChanges(log);
              const changeLines = new Set(changes.map((change) => change.line));
              const visibleLines = (log.lines.length ? log.lines : [log.message]).filter((line) => !changeLines.has(line));
              return (
                <div className={`pf-log-block is-${log.status}`} key={`${log.agent_name}-${index}`}>
                  <div className="pf-log-head">
                    <span />
                    <strong>{log.agent_name}</strong>
                    <em>{log.step}</em>
                    {log.duration && <time>{log.duration}</time>}
                  </div>
                  {changes.length > 0 && (
                    <div className="pf-log-file-changes">
                      {changes.map((change) => (
                        <FileChangeRow change={change} key={`${change.action}-${change.path}-${change.line}`} showDiff />
                      ))}
                    </div>
                  )}
                  {visibleLines.length > 0 && (
                    <div className="pf-log-lines">
                      {visibleLines.map((line, lineIndex) => (
                        <p key={`${line}-${lineIndex}`}>{line}</p>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </section>
      </aside>
    </div>
  );
}

function AgentContextPanel({ context }: { context: AgentContextSummary }) {
  if (context.files.length === 0 && context.filesInContext.length === 0) {
    return <p className="pf-empty-state">No agent context yet.</p>;
  }

  return (
    <div className="pf-agent-context">
      {context.files.length > 0 && (
        <div className="pf-agent-context-group">
          <div className="pf-agent-context-subhead">
            <FileText size={14} />
            <span>Bundle</span>
          </div>
          <div className="pf-agent-file-list">
            {context.files.map((file) => (
              <div className="pf-agent-file-row" key={file.path}>
                <strong>{file.path}</strong>
                <span>{file.kind || "file"}</span>
                <em>{file.lines ?? 0} lines</em>
                <b>{file.referenced ? "referenced" : "unreferenced"}</b>
              </div>
            ))}
          </div>
          {context.scriptRefs.length > 0 && (
            <div className="pf-agent-script-order">
              <span>script order</span>
              <strong>{context.scriptRefs.join(" -> ")}</strong>
            </div>
          )}
        </div>
      )}

      {context.filesInContext.length > 0 && (
        <div className="pf-agent-context-group">
          <div className="pf-agent-context-subhead">
            <Edit3 size={14} />
            <span>Files in context</span>
          </div>
          <div className="pf-agent-context-list">
            {context.filesInContext.map((file) => (
              <div className={`pf-agent-context-row${file.deleted ? " is-deleted" : ""}`} key={file.path}>
                <strong>{file.path}</strong>
                <span>{contextSourceLabel(file.record_source)}</span>
                <em>{file.record_state || "active"}</em>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FileChangeRow({ change, showDiff = false }: { change: FileChange; showDiff?: boolean }) {
  return (
    <div className={`pf-file-change-row is-${change.action}`}>
      <div className="pf-file-change-summary">
        <Edit3 size={14} />
        <span className="pf-file-change-action">{fileChangeLabel(change.action)}</span>
        <strong>{change.path}</strong>
        <b className="pf-file-change-plus">+{change.added}</b>
        <b className="pf-file-change-minus">-{change.deleted}</b>
        {change.detail && <em>{change.detail}</em>}
      </div>
      {showDiff && change.diff && change.diffFormat === "unified" && (
        <details className="pf-file-diff">
          <summary>View diff</summary>
          <pre>{change.diff}</pre>
        </details>
      )}
    </div>
  );
}

export function TasksDrawer({
  currentTaskId,
  loading,
  now,
  onClose,
  onResume,
  tasks,
}: {
  currentTaskId: string | null;
  loading: boolean;
  now: number;
  onClose: () => void;
  onResume: (id: string) => void;
  tasks: Task[];
}) {
  return (
    <div className="pf-drawer-backdrop" onClick={onClose}>
      <aside className="pf-drawer pf-task-drawer" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h2>My Tasks</h2>
            <p>Resume recent generation tasks.</p>
          </div>
          <button aria-label="Close tasks" onClick={onClose} type="button">
            <X size={18} />
          </button>
        </header>

        <section className="pf-drawer-section">
          {loading && <p className="pf-empty-state">Loading tasks...</p>}
          {!loading && tasks.length === 0 && <p className="pf-empty-state">No generation tasks yet.</p>}
          {tasks.map((task) => (
            <button className={`pf-task-item${task.id === currentTaskId ? " is-current" : ""}`} key={task.id} onClick={() => onResume(task.id)} type="button">
              <span className={`pf-task-status is-${task.status}`} />
              <div>
                <strong>{getBrief(task, []).title}</strong>
                <p>
                  {task.status} - {formatRelative(task.updated_at || task.created_at, now) || "recently"}
                </p>
              </div>
              <ArrowRight size={16} />
            </button>
          ))}
        </section>
      </aside>
    </div>
  );
}

function TechItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="pf-tech-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
