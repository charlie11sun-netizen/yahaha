"use client";

import { Check, Gamepad2, MoreHorizontal } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  getGameplayQaStatus,
  gameplayRuntimeLabel,
  isActiveTask,
} from "../_lib/create-progress";
import { formatRelative } from "../_lib/create-time";
import type { Task } from "@/lib/types";

export function PreviewCard({ now, task }: { now: number; task?: Task }) {
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
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center justify-between font-display text-xl tracking-normal text-slate-950">
          Preview
          <Gamepad2 size={19} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {previewAvailable ? (
          <div className="aspect-[16/10] overflow-hidden rounded-lg border border-slate-200 bg-slate-950">
            <iframe
              className="h-full w-full border-0 bg-white"
              sandbox="allow-scripts allow-pointer-lock"
              src={previewSrc}
              title={`${task?.game?.title || "Game"} preview`}
            />
          </div>
        ) : (
          <img alt="" className="aspect-[16/10] w-full rounded-lg border border-slate-200 object-cover" src="/gameweave/create-runtime-preview.png" />
        )}

        <h3 className="font-display text-lg font-semibold tracking-normal text-slate-950">{statusLine}</h3>

        <div className="grid gap-2">
          <RuntimeRow label={previewAvailable ? "Sandboxed preview mounted" : "Sandbox pending"} ready={previewAvailable} />
          {gameplayStatus ? (
            <RuntimeRow label={gameplayRuntimeLabel(gameplayStatus)} ready={gameplayStatus === "completed"} />
          ) : null}
          <RuntimeRow label={succeeded ? "Manifest uploaded" : "Manifest pending"} ready={Boolean(task?.manifest_url)} />
          <RuntimeRow label={succeeded ? "Bundle ready" : "Bundle pending"} ready={Boolean(succeeded)} />
        </div>

        {task && !succeeded && isActiveTask(task.status) ? (
          <p className="rounded-lg border border-indigo-100 bg-indigo-50 p-3 text-sm text-indigo-700">
            Last heartbeat {formatRelative(task.updated_at || task.created_at, now) || "just now"}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function RuntimeRow({ label, ready }: { label: string; ready?: boolean }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
      <span
        className={cn(
          "flex size-6 items-center justify-center rounded-full",
          ready ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-500",
        )}
      >
        {ready ? <Check size={15} /> : <MoreHorizontal size={17} />}
      </span>
      <p className="text-slate-700">{label}</p>
    </div>
  );
}
