"use client";

import { ArrowRight, Sparkles } from "lucide-react";

import { ActionPanel } from "./CreateActionPanel";
import { CreateBriefCard } from "./CreateBriefCard";
import { CreateProgressCard } from "./CreateProgressCard";
import { PreviewCard } from "./CreatePreviewCard";
import { Badge } from "@/components/ui/badge";
import { getBrief } from "../_lib/create-progress";
import type { GeneratedTaskAsset, Task, UploadedAsset } from "@/lib/types";

export function CreateWorkspace({
  connectionStatus,
  files,
  generatedAssets,
  now,
  onCancel,
  onEditBrief,
  onOpenActivity,
  onPreview,
  onPublish,
  onRevision,
  onRetry,
  publishing,
  revising,
  task,
}: {
  connectionStatus: string;
  files: UploadedAsset[];
  generatedAssets: GeneratedTaskAsset[];
  now: number;
  onCancel: () => void;
  onEditBrief: () => void;
  onOpenActivity: () => void;
  onPreview: () => void;
  onPublish: () => void;
  onRevision: (feedback: string) => Promise<boolean>;
  onRetry: () => void;
  publishing: boolean;
  revising: boolean;
  task?: Task;
}) {
  const brief = getBrief(task, files, generatedAssets.length);

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="grid gap-5 border-b border-slate-200/80 pb-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="flex min-w-0 items-start gap-4">
          <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-slate-950 text-white shadow-sm">
            <Sparkles size={22} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-indigo-600">AI game studio</p>
            <h1 className="mt-1 font-display text-3xl font-semibold leading-none text-slate-950 sm:text-4xl">Build workspace</h1>
            <CreateBriefCard brief={brief} onEditBrief={onEditBrief} />
          </div>
        </div>
        <Badge className="w-fit gap-1.5 border-indigo-200 bg-indigo-50 px-3 py-2 text-indigo-700" variant="outline">
          <ArrowRight size={14} />
          You can leave this page
        </Badge>
      </header>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)] xl:grid-cols-[minmax(0,1.12fr)_minmax(420px,0.88fr)]">
        <div className="min-w-0">
        <CreateProgressCard
          connectionStatus={connectionStatus}
          now={now}
          onOpenActivity={onOpenActivity}
          task={task}
        />
      </div>

      <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-24">
        <PreviewCard generatedAssets={generatedAssets} now={now} task={task} />
        <ActionPanel
          onCancel={onCancel}
          onOpenActivity={onOpenActivity}
          onPreview={onPreview}
          onPublish={onPublish}
          onRevision={onRevision}
          onRetry={onRetry}
          publishing={publishing}
          revising={revising}
          task={task}
        />
      </aside>
      </div>
    </div>
  );
}
