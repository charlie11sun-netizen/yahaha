"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import {
  ActivityDrawer,
  CreateInput,
  CreateWorkspace,
  TaskMissingCard,
  TasksDrawer,
} from "./_components/CreatePanels";
import { useCreateTaskQuery, useCreateTasksQuery } from "./_lib/use-create-queries";
import { useNow } from "./_lib/create-state";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { UploadedAsset } from "@/lib/types";

const DRAFT_KEY = "pf_create_draft_v2";
const LAST_TASK_KEY = "pf_last_create_task";

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

  const taskQuery = useCreateTaskQuery(taskId);
  const taskMissing = taskQuery.isMissing;
  const tasksQuery = useCreateTasksQuery(tasksOpen);

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
