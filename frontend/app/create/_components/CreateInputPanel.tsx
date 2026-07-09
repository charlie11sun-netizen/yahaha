"use client";

import {
  AlertCircle,
  ArrowRight,
  FileImage,
  Loader2,
  RefreshCcw,
  Sparkles,
  UploadCloud,
  WandSparkles,
  X,
} from "lucide-react";

import { ActionPanel } from "./CreateActionPanel";
import { PreviewCard } from "./CreatePreviewCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { UploadedAsset } from "@/lib/types";

export function TaskMissingCard({ onBack }: { onBack: () => void }) {
  return (
    <Card className="rounded-lg border-rose-200 bg-rose-50/80 shadow-sm">
      <CardContent className="flex flex-col items-start gap-4 p-6">
        <span className="flex size-10 items-center justify-center rounded-lg bg-rose-100 text-rose-700">
          <AlertCircle size={20} />
        </span>
        <div>
          <h2 className="font-display text-2xl font-semibold tracking-normal text-rose-950">Task not found</h2>
          <p className="mt-2 text-sm leading-6 text-rose-700">
            This generation task no longer exists. It may have been deleted, or the link is stale.
          </p>
        </div>
        <Button className="rounded-lg" onClick={onBack} type="button">
          Start a new game
        </Button>
      </CardContent>
    </Card>
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
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex min-w-0 flex-col gap-6">
        {onResumeLast ? (
          <Button className="h-auto justify-between rounded-lg px-4 py-3" onClick={onResumeLast} type="button" variant="outline">
            <span className="inline-flex items-center gap-2">
              <RefreshCcw size={15} />
              Continue your last generation task
            </span>
            <ArrowRight size={15} />
          </Button>
        ) : null}

        <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
          <CardContent className="space-y-6 p-5 sm:p-6">
            <div className="flex gap-4">
              <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                <WandSparkles size={28} />
              </span>
              <div className="min-w-0">
                <h2 className="font-display text-2xl font-semibold tracking-normal text-slate-950">
                  {remixSourceTitle ? `Remix ${remixSourceTitle}` : "What do you want to create?"}
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {remixSourceTitle
                    ? "Describe the gameplay, visual, or rule changes for this remix."
                    : "Give GameWeave a playable concept, reference style, rules, and win conditions."}
                </p>
              </div>
            </div>

            <label className="grid gap-2" htmlFor="idea">
              <span className="text-sm font-semibold text-slate-700">Game idea</span>
              <textarea
                className="min-h-44 resize-y rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                id="idea"
                onChange={(event) => onSetIdea(event.target.value)}
                placeholder="Example: Make a 2D cyberpunk runner where a street-smart cat dodges drones, hacks neon terminals, and survives for 90 seconds."
                value={idea}
              />
            </label>

            <div className="flex flex-wrap gap-2">
              {examples.map((example) => (
                <Button className="rounded-lg" key={example} onClick={() => onSetIdea(example)} type="button" variant="outline">
                  {example}
                </Button>
              ))}
            </div>

            <div className="grid gap-3">
              <span className="text-sm font-semibold text-slate-700">Render mode</span>
              <div aria-label="Render mode" className="grid gap-3 sm:grid-cols-2" role="group">
                {(["2d", "3d"] as const).map((mode) => (
                  <button
                    aria-pressed={dimension === mode}
                    className={cn(
                      "rounded-lg border p-4 text-left transition",
                      dimension === mode
                        ? "border-indigo-300 bg-indigo-50 text-indigo-950 shadow-sm"
                        : "border-slate-200 bg-white text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/40",
                    )}
                    key={mode}
                    onClick={() => onSetDimension(mode)}
                    type="button"
                  >
                    <span className="block font-semibold">{mode === "2d" ? "2D - Canvas" : "3D - WebGL"}</span>
                    <span className="mt-1 block text-sm leading-6 text-slate-500">
                      {mode === "2d" ? "Classic 2D arcade, fast and reliable" : "Real 3D via Three.js: FPS, runner, racer"}
                    </span>
                  </button>
                ))}
              </div>
              {dimension === "3d" ? (
                <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-800">
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  3D is authored by the AI model directly. Enable real-model generation for the best result.
                </p>
              ) : null}
            </div>

            <label
              className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-indigo-200 bg-indigo-50/50 px-5 py-8 text-center text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-50"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                onPickFiles(event.dataTransfer.files);
              }}
            >
              {uploading ? <Loader2 className="size-8 animate-spin" /> : <UploadCloud size={30} />}
              <strong>{uploading ? "Uploading..." : "Upload references"}</strong>
              <span className="text-sm text-indigo-700/75">Drop images, video, or files here. Up to 6 assets, 10MB each.</span>
              <input
                className="sr-only"
                multiple
                onChange={(event) => {
                  onPickFiles(event.target.files);
                  event.currentTarget.value = "";
                }}
                type="file"
              />
            </label>

            {files.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {files.map((file) => (
                  <div className="grid grid-cols-[44px_1fr_auto] items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3" key={file.id}>
                    {file.kind === "image" && file.url ? (
                      <img alt="" className="size-11 rounded-md object-cover" src={file.url} />
                    ) : (
                      <span className="flex size-11 items-center justify-center rounded-md bg-white text-slate-500">
                        <FileImage size={18} />
                      </span>
                    )}
                    <strong className="min-w-0 truncate text-sm font-semibold text-slate-800">{file.name}</strong>
                    <Button aria-label={`Remove ${file.name}`} onClick={() => onRemoveFile(file.id)} size="icon" type="button" variant="ghost">
                      <X size={14} />
                    </Button>
                  </div>
                ))}
              </div>
            ) : null}

            <Button className="h-11 w-full rounded-lg" disabled={!canGenerate} onClick={onGenerate} type="button">
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Sparkles size={18} />}
              {busy ? "Starting task..." : "Generate Game"}
            </Button>
          </CardContent>
        </Card>
      </div>

      <aside className="flex min-w-0 flex-col gap-6">
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
