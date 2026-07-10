"use client";

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
            <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
              <label className="text-sm font-semibold text-slate-700" htmlFor="preview-feedback">
                What should change?
              </label>
              <textarea
                className="min-h-28 resize-y rounded-md border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-800 outline-none transition focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                id="preview-feedback"
                maxLength={2000}
                onChange={(event) => setRevisionFeedback(event.target.value)}
                placeholder="Describe the feel, behavior, visuals, or rules you want changed. Your wording is preserved."
                value={revisionFeedback}
              />
              <Button
                className="rounded-lg"
                disabled={revising || !revisionFeedback.trim()}
                onClick={onRevision}
                type="button"
                variant="outline"
              >
                {revising ? <Loader2 className="size-4 animate-spin" /> : <WandSparkles size={17} />}
                {revising ? "Starting revision..." : "Apply feedback to this version"}
              </Button>
            </div>
          </>
        ) : null}

        {failed ? (
          <>
            <Button className="rounded-lg" onClick={onRetry} type="button">
              <RefreshCcw size={17} />
              Retry from validation
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
