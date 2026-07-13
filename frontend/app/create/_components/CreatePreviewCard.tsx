"use client";

import { Check, Circle, Gamepad2, Images } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getGameplayQaStatus, gameplayRuntimeLabel, isActiveTask } from "../_lib/create-progress";
import { formatRelative } from "../_lib/create-time";
import type { GeneratedTaskAsset, Task } from "@/lib/types";

export function PreviewCard({
  generatedAssets,
  now,
  task,
}: {
  generatedAssets: GeneratedTaskAsset[];
  now: number;
  task?: Task;
}) {
  const succeeded = task?.status === "succeeded" && task.game;
  const previewAvailable = Boolean(task?.game);
  const previewSrc = task?.game?.bundle_url || task?.preview_url || (task?.game ? `/play/${task.game.id}` : "");
  const active = isActiveTask(task?.status);
  const failed = task?.status === "failed";
  const cancelled = task?.status === "cancelled";
  const gameplayStatus = getGameplayQaStatus(task);
  const assetsAvailable = generatedAssets.length > 0;
  const statusLine = succeeded
    ? "Preview ready"
    : assetsAvailable
      ? "Generated assets ready"
      : failed
        ? "Preview unavailable"
        : cancelled
          ? "Task cancelled"
          : active
            ? "Preparing runtime..."
            : "Your playable preview will appear here.";
  const statusDescription = succeeded
    ? "Your first playable version is ready to test."
    : assetsAvailable
      ? "Your generated artwork is ready while the playable runtime continues building."
      : failed
        ? "Generation stopped before a playable preview was created."
        : cancelled
          ? "This task ended before the preview was prepared."
          : "This preview updates automatically as your game is built.";

  return (
    <Card className="gap-0 overflow-hidden rounded-xl border-slate-200/90 bg-white py-0 shadow-sm">
      <CardHeader className="border-b border-slate-200 px-5 py-4">
        <CardTitle className="flex items-center justify-between font-display text-lg text-slate-950">
          {assetsAvailable && !previewAvailable ? `Generated assets (${generatedAssets.length})` : "Preview"}
          {assetsAvailable && !previewAvailable ? (
            <Images size={18} className="text-indigo-500" />
          ) : (
            <Gamepad2 size={18} className="text-slate-400" />
          )}
        </CardTitle>
      </CardHeader>

      <CardContent className="p-0">
        {previewAvailable ? (
          <div className="aspect-[16/10] overflow-hidden bg-slate-950">
            <iframe
              className="h-full w-full border-0 bg-white"
              sandbox="allow-scripts allow-pointer-lock"
              src={previewSrc}
              title={`${task?.game?.title || "Game"} preview`}
            />
          </div>
        ) : assetsAvailable ? (
          <GeneratedAssetGallery assets={generatedAssets} />
        ) : (
          <img
            alt=""
            className="aspect-[16/10] w-full bg-indigo-50/40 object-cover"
            src="/gameweave/create-runtime-preview.png"
          />
        )}

        <div className="space-y-4 p-5">
          <div>
            <h3 className="font-display text-xl font-semibold text-slate-950">{statusLine}</h3>
            <p className="mt-1 text-sm text-slate-500">{statusDescription}</p>
          </div>

          <div className="grid grid-cols-2 gap-x-4 border-t border-slate-100 pt-3">
            <RuntimeRow label={previewAvailable ? "Sandbox mounted" : "Sandbox"} ready={previewAvailable} />
            {gameplayStatus ? (
              <RuntimeRow label={gameplayRuntimeLabel(gameplayStatus)} ready={gameplayStatus === "completed"} />
            ) : (
              <RuntimeRow label="Playtest" ready={false} />
            )}
            <RuntimeRow label="Manifest" ready={Boolean(task?.manifest_url)} />
            <RuntimeRow label="Bundle" ready={Boolean(succeeded)} />
          </div>

          {task && !succeeded && active ? (
            <p className="inline-flex items-center gap-2 text-xs text-slate-400">
              <Circle size={7} className="text-emerald-500" fill="currentColor" />
              Last heartbeat {formatRelative(task.updated_at || task.created_at, now) || "just now"}
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function GeneratedAssetGallery({ assets }: { assets: GeneratedTaskAsset[] }) {
  return (
    <div className="grid aspect-[16/10] grid-cols-2 auto-rows-[minmax(140px,1fr)] gap-3 overflow-y-auto bg-slate-50 p-4">
      {assets.map((asset, index) => (
        <figure
          className={cn(
            "group relative min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm",
            assets.length === 1 && "col-span-2",
          )}
          key={`${asset.key}-${index}`}
        >
          <img
            alt={asset.name}
            className="h-full w-full object-contain transition duration-300 group-hover:scale-[1.02]"
            src={asset.data_url}
          />
          <figcaption className="absolute inset-x-2 bottom-2 flex items-center justify-between gap-2 rounded-lg bg-slate-950/80 px-2.5 py-1.5 text-white backdrop-blur">
            <span className="truncate text-xs font-semibold">{asset.name}</span>
            <span className="shrink-0 text-[10px] uppercase tracking-wide text-slate-300">{asset.kind}</span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

function RuntimeRow({ label, ready }: { label: string; ready?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2 border-b border-slate-100 py-2.5 text-sm last:border-b-0">
      <span
        className={cn(
          "flex size-5 shrink-0 items-center justify-center rounded-full border",
          ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 text-slate-300",
        )}
      >
        {ready ? <Check size={12} /> : <Circle size={6} fill="currentColor" />}
      </span>
      <p className={cn("truncate", ready ? "text-slate-700" : "text-slate-500")}>{label}</p>
    </div>
  );
}
