"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { AgentLogItem, StepSummary, Task, UploadedAsset } from "@/lib/types";

const DRAFT_KEY = "pf_create_draft_v2";
const LAST_TASK_KEY = "pf_last_create_task";
const GAMEPLAY_STEP_KEYS = ["gameplay_qa", "gameplay_repair"] as const;
const STREAM_TOKEN_RE = /^stream_tokens=(\d+)$/;

type UserStep = { key: string; label: string; backendKeys?: readonly string[]; optional?: boolean };

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

type StepState = "pending" | "running" | "completed" | "failed";
type StepRow = { key: string; label: string; status: StepState; summary?: string | null };

export default function CreatePage() {
  return (
    <Suspense fallback={null}>
      <CreatePageInner />
    </Suspense>
  );
}

function CreatePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const flash = useToast();
  const { user, loading } = useAuth();
  const now = useNow(1000);
  const taskParam = searchParams.get("task");
  const resumeLast = searchParams.get("resume") === "1";
  const remixSourceId = searchParams.get("remix");
  const remixSourceTitle = searchParams.get("sourceTitle") || "this game";
  const remixIdea = searchParams.get("idea");

  const [idea, setIdea] = useState("");
  const [dimension, setDimension] = useState<"2d" | "3d">("2d");
  const [files, setFiles] = useState<UploadedAsset[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [revising, setRevising] = useState(false);
  const [revisionFeedback, setRevisionFeedback] = useState("");
  const [activityOpen, setActivityOpen] = useState(false);
  const [tasksOpen, setTasksOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login?intent=create");
    }
  }, [loading, router, user]);

  useEffect(() => {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return;
    try {
      const draft = JSON.parse(raw) as { idea?: string; files?: UploadedAsset[]; dimension?: "2d" | "3d" };
      setIdea(draft.idea || "");
      setDimension(draft.dimension === "3d" ? "3d" : "2d");
      setFiles(Array.isArray(draft.files) ? draft.files : []);
    } catch {
      localStorage.removeItem(DRAFT_KEY);
    }
  }, []);

  useEffect(() => {
    if (!remixSourceId) return;
    setIdea((current) =>
      current.trim() ? current : remixIdea || `Remix ${remixSourceTitle} with a fresh mechanic and visual twist.`,
    );
  }, [remixIdea, remixSourceId, remixSourceTitle]);

  useEffect(() => {
    if (taskParam) {
      setTaskId(taskParam);
      localStorage.setItem(LAST_TASK_KEY, taskParam);
      return;
    }
    if (resumeLast) {
      setTaskId(localStorage.getItem(LAST_TASK_KEY));
      return;
    }
    setTaskId(null);
  }, [resumeLast, taskParam]);

  // 输入页顶部的"继续上次任务"横幅：站内导航离开再回来时，进行中的任务不再凭空消失
  const [lastTaskId, setLastTaskId] = useState<string | null>(null);
  useEffect(() => {
    setLastTaskId(taskId ? null : localStorage.getItem(LAST_TASK_KEY));
  }, [taskId]);

  const saveDraft = useCallback(() => {
    if (!idea.trim() && files.length === 0) {
      flash("Nothing to save yet");
      return;
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ idea, files, dimension, savedAt: new Date().toISOString() }));
    flash("Draft saved");
  }, [dimension, files, flash, idea]);

  useEffect(() => {
    const openTasks = () => setTasksOpen(true);
    window.addEventListener("pf-save-create-draft", saveDraft);
    window.addEventListener("pf-open-create-tasks", openTasks);
    return () => {
      window.removeEventListener("pf-save-create-draft", saveDraft);
      window.removeEventListener("pf-open-create-tasks", openTasks);
    };
  }, [saveDraft]);

  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.task(taskId as string),
    enabled: !!taskId,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && (error.status === 404 || error.status === 403)) && failureCount < 3,
    refetchInterval: (query) => {
      const err = query.state.error;
      // 任务已删除/无权限：停止轮询，改渲染明确的 not-found 空态
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) return false;
      // 瞬时故障（网络抖动/后端重启）：3s 退避继续轮询 —— "Reconnecting" 必须是真的。
      // 首拉即失败时 data 为 undefined，绝不能据此停轮（否则一次故障就永久卡死）。
      if (err) return 3000;
      const status = query.state.data?.status;
      if (!status) return 1000;
      return isActiveTask(status) ? 1000 : false;
    },
  });
  const taskMissing =
    taskQuery.error instanceof ApiError &&
    (taskQuery.error.status === 404 || taskQuery.error.status === 403);

  const tasksQuery = useQuery({
    queryKey: ["tasks"],
    queryFn: api.tasks,
    enabled: tasksOpen,
    refetchInterval: tasksOpen ? 5000 : false,
  });

  const task = taskQuery.data;

  const MAX_ASSETS = 6; // 与后端 uploads.MAX_FILES 对齐

  const pickFiles = async (picked: FileList | File[] | null) => {
    if (!picked || picked.length === 0 || uploading) return;
    const room = MAX_ASSETS - files.length;
    if (room <= 0) {
      flash(`At most ${MAX_ASSETS} assets per task`, { error: true });
      return;
    }
    const selected = Array.from(picked);
    setUploading(true);
    try {
      const result = await api.upload(selected.slice(0, room));
      setFiles((current) => [...current, ...result.assets].slice(0, MAX_ASSETS));
      const dropped = selected.length - Math.min(selected.length, room);
      flash(
        `${result.assets.length} asset${result.assets.length === 1 ? "" : "s"} uploaded` +
          (dropped > 0 ? ` (${dropped} skipped — max ${MAX_ASSETS})` : ""),
      );
    } catch (error) {
      // 把后端 413/415 的具体原因透传给用户，而不是笼统的 "Upload failed"
      flash(error instanceof ApiError ? `Upload failed: ${error.message}` : "Upload failed", { error: true });
    } finally {
      setUploading(false);
    }
  };

  const startGeneration = async () => {
    if (!idea.trim() || busy) return;
    setBusy(true);
    try {
      const result = await api.createTask(
        idea.trim(),
        files.map((file) => file.id),
        dimension,
        remixSourceId ? { task_kind: "remix", source_game_id: remixSourceId } : undefined,
      );
      setTaskId(result.task_id);
      localStorage.setItem(LAST_TASK_KEY, result.task_id);
      router.replace(`/create?task=${encodeURIComponent(result.task_id)}`);
      flash("Generation task started");
    } catch {
      flash("Could not start generation", { error: true });
    } finally {
      setBusy(false);
    }
  };

  const retryTask = async () => {
    if (!task) return;
    try {
      const result = await api.retryTask(task.id);
      setTaskId(result.task_id);
      localStorage.setItem(LAST_TASK_KEY, result.task_id);
      router.replace(`/create?task=${encodeURIComponent(result.task_id)}`);
      await queryClient.invalidateQueries({ queryKey: ["task", result.task_id] });
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      flash("Retry started");
    } catch {
      flash("Retry failed", { error: true });
    }
  };

  const cancelTask = async () => {
    if (!task) return;
    try {
      const cancelled = await api.cancelTask(task.id);
      queryClient.setQueryData(["task", task.id], cancelled);
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      flash("Task cancelled");
    } catch {
      flash("Could not cancel task", { error: true });
    }
  };

  const publishGame = async () => {
    if (!task?.game) return;
    setPublishing(true);
    try {
      await api.publish(task.game.id);
      await queryClient.invalidateQueries({ queryKey: ["games"] });
      await queryClient.invalidateQueries({ queryKey: ["stats"] });
      flash(`${task.game.title} published`);
      router.push("/explore"); // 游戏列表在 /explore，首页是营销落地页
    } catch {
      flash("Publish failed", { error: true });
    } finally {
      setPublishing(false);
    }
  };

  const reviseGame = async () => {
    if (!task?.game || !revisionFeedback.trim() || revising) return;
    setRevising(true);
    try {
      const result = await api.reviseTask(task.id, revisionFeedback.trim());
      setRevisionFeedback("");
      setTaskId(result.task_id);
      localStorage.setItem(LAST_TASK_KEY, result.task_id);
      router.replace(`/create?task=${encodeURIComponent(result.task_id)}`);
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      flash("Revision task started from the current preview");
    } catch {
      flash("Could not start revision", { error: true });
    } finally {
      setRevising(false);
    }
  };

  const openPreview = () => {
    if (task?.game) {
      window.open(`/play/${task.game.id}`, "_blank", "noopener");
    }
  };

  const editBrief = () => {
    setTaskId(null);
    localStorage.removeItem(LAST_TASK_KEY);
    router.replace("/create");
  };

  const resumeTask = (id: string) => {
    setTaskId(id);
    localStorage.setItem(LAST_TASK_KEY, id);
    router.replace(`/create?task=${encodeURIComponent(id)}`);
    setTasksOpen(false);
  };

  if (loading || !user) return null;

  return (
    <div className="pf-create-page">
      <section className="pf-create-shell">
        <header className="pf-create-header">
          <h1>Create with AI</h1>
          <p>Describe your idea, upload references, and generate a playable web game.</p>
        </header>

        {taskId && taskMissing ? (
          <TaskMissingCard onBack={editBrief} />
        ) : taskId ? (
          <CreateWorkspace
            connectionStatus={taskQuery.isError ? "Reconnecting" : "Connected"}
            files={files}
            now={now}
            onCancel={cancelTask}
            onEditBrief={editBrief}
            onOpenActivity={() => setActivityOpen(true)}
            onPreview={openPreview}
            onPublish={publishGame}
            onRevision={reviseGame}
            onRetry={retryTask}
            publishing={publishing}
            revisionFeedback={revisionFeedback}
            revising={revising}
            setRevisionFeedback={setRevisionFeedback}
            task={task}
          />
        ) : (
          <CreateInput
            busy={busy}
            dimension={dimension}
            files={files}
            idea={idea}
            now={now}
            onGenerate={startGeneration}
            onOpenActivity={() => setActivityOpen(true)}
            onPickFiles={pickFiles}
            onRemoveFile={(id) => setFiles((current) => current.filter((file) => file.id !== id))}
            onResumeLast={lastTaskId ? () => resumeTask(lastTaskId) : undefined}
            onSetDimension={setDimension}
            onSetIdea={setIdea}
            remixSourceTitle={remixSourceId ? remixSourceTitle : undefined}
            uploading={uploading}
          />
        )}
      </section>

      {activityOpen && <ActivityDrawer onClose={() => setActivityOpen(false)} task={task} />}
      {tasksOpen && (
        <TasksDrawer
          currentTaskId={taskId}
          loading={tasksQuery.isLoading}
          now={now}
          onClose={() => setTasksOpen(false)}
          onResume={resumeTask}
          tasks={tasksQuery.data?.items ?? []}
        />
      )}
    </div>
  );
}

function TaskMissingCard({ onBack }: { onBack: () => void }) {
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

function CreateInput({
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
                  {file.kind === "image" ? (
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

function CreateWorkspace({
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
  const liveTokens = getLiveStreamTokens(task);

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

      {liveTokens !== null && isActiveTask(task?.status) && (
        <div className="pf-live-token-row" aria-label="Live output tokens">
          <span>tokens</span>
          <strong key={liveTokens}>{liveTokens.toLocaleString()}</strong>
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

function ActivityDrawer({ onClose, task }: { onClose: () => void; task?: Task }) {
  const logs = visibleAgentLogs(task);
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
          <h3>Agent activity</h3>
          {logs.length === 0 ? (
            <p className="pf-empty-state">No activity yet.</p>
          ) : (
            logs.map((log, index) => (
              <div className={`pf-log-block is-${log.status}`} key={`${log.agent_name}-${index}`}>
                <div className="pf-log-head">
                  <span />
                  <strong>{log.agent_name}</strong>
                  <em>{log.step}</em>
                  {log.duration && <time>{log.duration}</time>}
                </div>
                <div className="pf-log-lines">
                  {(log.lines.length ? log.lines : [log.message]).map((line, lineIndex) => (
                    <p key={`${line}-${lineIndex}`}>{line}</p>
                  ))}
                </div>
              </div>
            ))
          )}
        </section>
      </aside>
    </div>
  );
}

function TasksDrawer({
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

function buildStepRows(task?: Task): StepRow[] {
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

function getActiveStepIndex(rows: StepRow[], task?: Task) {
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

function getBrief(task: Task | undefined, uploadedFiles: UploadedAsset[]) {
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

function getProgressTitle(task?: Task) {
  if (task?.status === "succeeded") return "Game ready";
  if (task?.status === "failed") return "Generation stopped";
  if (task?.status === "cancelled") return "Task cancelled";
  return "Creating your game";
}

function getCurrentIssue(task: Task | undefined, activeStep?: StepRow) {
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

function getRecentUpdates(task: Task | undefined, now: number) {
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

function friendlyMessage(message: string) {
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

function getLiveStreamTokens(task?: Task) {
  const logs = task?.logs ?? [];
  for (let logIndex = logs.length - 1; logIndex >= 0; logIndex -= 1) {
    const lines = logs[logIndex].lines.length ? logs[logIndex].lines : [logs[logIndex].message];
    for (let lineIndex = lines.length - 1; lineIndex >= 0; lineIndex -= 1) {
      const value = parseStreamTokens(lines[lineIndex]);
      if (value !== null) return value;
    }
  }
  return null;
}

function visibleAgentLogs(task?: Task): AgentLogItem[] {
  return (task?.logs ?? [])
    .map((log) => {
      const lines = log.lines.filter((line) => !isStreamTokenLine(line));
      const message = isStreamTokenLine(log.message) ? (lines.at(-1) ?? "") : log.message;
      return { ...log, message, lines };
    })
    .filter((log) => log.message || log.lines.length);
}

function getGameplayQaStatus(task?: Task): StepState | null {
  const summaries = (task?.step_summaries ?? []).filter((summary) => GAMEPLAY_STEP_KEYS.includes(summary.step as (typeof GAMEPLAY_STEP_KEYS)[number]));
  return summaries.length > 0 ? mergedStepStatus(summaries) : null;
}

function gameplayRuntimeLabel(status: StepState) {
  if (status === "completed") return "Playtest passed";
  if (status === "running") return "Playtest running";
  if (status === "failed") return "Playtest needs repair";
  return "Playtest pending";
}

function gameplayTechLabel(status: StepState) {
  if (status === "completed") return "Passed";
  if (status === "running") return "Running";
  if (status === "failed") return "Needs repair";
  return "Pending";
}

function isActiveTask(status?: string) {
  return status === "pending" || status === "running";
}

function formatRelative(value: string | null | undefined, now: number) {
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

function formatElapsed(value: string | null | undefined, now: number) {
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

function useNow(intervalMs: number) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(interval);
  }, [intervalMs]);
  return now;
}
