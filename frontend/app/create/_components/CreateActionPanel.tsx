"use client";

import { useState } from "react";
import {
  BarChart3,
  CheckCircle2,
  Loader2,
  Play,
  RefreshCcw,
  Trash2,
  WandSparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CreateRevisionDialog } from "./CreateRevisionDialog";
import { isActiveTask } from "../_lib/create-progress";
import type { Task } from "@/lib/types";

export function ActionPanel({
  onCancel,
  onOpenActivity,
  onPreview,
  onPublish,
  onRevision,
  onRetry,
  publishing,
  revising,
  task,
}: {
  onCancel: () => void;
  onOpenActivity: () => void;
  onPreview: () => void;
  onPublish: () => void;
  onRevision: (feedback: string) => Promise<boolean>;
  onRetry: () => void;
  publishing: boolean;
  revising: boolean;
  task?: Task;
}) {
  const [revisionOpen, setRevisionOpen] = useState(false);
  const succeeded = task?.status === "succeeded" && task.game;
  const failed = task?.status === "failed";
  const imageRetryRequired = failed && task?.error_code === "ASSET_GENERATION_FAILED";
  const cancelled = task?.status === "cancelled";
  const active = isActiveTask(task?.status);

  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardContent className="flex flex-col gap-3 p-5">
        <Button className="rounded-lg" onClick={onOpenActivity} type="button" variant="outline">
          <BarChart3 size={18} />
          View Activity
        </Button>

        {succeeded ? (
          <>
            <Button className="rounded-lg" onClick={onPreview} type="button" variant="outline">
              <Play size={17} />
              Play Preview
            </Button>
            <Button className="rounded-lg" disabled={publishing} onClick={onPublish} type="button">
              {publishing ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 size={17} />}
              {publishing ? "Publishing..." : "Publish to Home"}
            </Button>
            <div className="border-t border-slate-200 pt-3">
              <Button
                className="w-full rounded-lg border-indigo-200 bg-indigo-50 text-indigo-700 shadow-none hover:bg-indigo-100 hover:text-indigo-800"
                disabled={revising}
                onClick={() => setRevisionOpen(true)}
                type="button"
                variant="outline"
              >
                {revising ? <Loader2 className="size-4 animate-spin" /> : <WandSparkles size={17} />}
                {revising ? "Starting revision..." : "Plan the next version"}
              </Button>
            </div>
            <CreateRevisionDialog
              onOpenChange={setRevisionOpen}
              onSubmit={onRevision}
              open={revisionOpen}
              revising={revising}
              task={task}
            />
          </>
        ) : null}

        {failed ? (
          <>
            <Button className="rounded-lg" onClick={onRetry} type="button">
              <RefreshCcw size={17} />
              {imageRetryRequired ? "Retry image generation" : "Retry failed step"}
            </Button>
            <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm leading-6 text-rose-700">
              {task?.error || "Generation stopped before a playable preview was created."}
            </p>
          </>
        ) : null}

        {cancelled ? (
          <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-700">
            This task was cancelled. Start a new version from the brief when you are ready.
          </p>
        ) : null}

        {active ? (
          <Button className="rounded-lg text-rose-700 hover:text-rose-700" onClick={onCancel} type="button" variant="outline">
            <Trash2 size={17} />
            Cancel task
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
