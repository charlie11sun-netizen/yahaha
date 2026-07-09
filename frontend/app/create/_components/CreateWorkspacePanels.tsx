"use client";

import { ActionPanel } from "./CreateActionPanel";
import { CreateBriefCard } from "./CreateBriefCard";
import { CreateProgressCard } from "./CreateProgressCard";
import { PreviewCard } from "./CreatePreviewCard";
import { getBrief } from "../_lib/create-state";
import type { Task, UploadedAsset } from "@/lib/types";

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
  const brief = getBrief(task, files);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex min-w-0 flex-col gap-6">
        <CreateBriefCard brief={brief} onEditBrief={onEditBrief} />
        <CreateProgressCard
          connectionStatus={connectionStatus}
          now={now}
          onOpenActivity={onOpenActivity}
          task={task}
        />
      </div>

      <aside className="flex min-w-0 flex-col gap-6">
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
