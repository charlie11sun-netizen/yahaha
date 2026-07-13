"use client";

import Image from "next/image";
import {
  AlertCircle,
  ArrowRight,
  Box,
  Edit3,
  FileImage,
  Gamepad2,
  Layers3,
  Loader2,
  Palette,
  Plus,
  RefreshCcw,
  RotateCcw,
  Trophy,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { UploadedAsset } from "@/lib/types";

const SAMPLE_PROMPT =
  "A fast one-minute drifting game on a neon night circuit. Chain boost gates, drift longer to build score, and beat the clock.";

const SAMPLE_REFERENCES = [
  {
    alt: "Neon racing circuit reference",
    name: "neon-track.png",
    src: "/gameweave/create-references/neon-track.png",
  },
  {
    alt: "Neon drifting car reference",
    name: "neon-car.png",
    src: "/gameweave/create-references/neon-car.png",
  },
];

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
  onGenerate,
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
  const canGenerate = idea.trim().length > 0 && !busy && !uploading;
  const brief = buildLiveBrief(idea);

  const addSampleReference = async (src: string, name: string) => {
    if (uploading) return;
    try {
      const response = await fetch(src);
      if (!response.ok) return;
      const blob = await response.blob();
      onSetIdea(idea.trim() ? idea : SAMPLE_PROMPT);
      onPickFiles([new File([blob], name, { type: blob.type || "image/png" })]);
    } catch {
      // The regular upload surface remains available if a local sample cannot be loaded.
    }
  };

  return (
    <div className="relative grid min-h-[760px] gap-8 xl:grid-cols-[minmax(520px,0.88fr)_minmax(0,1.12fr)] xl:gap-0">
      <section className="flex min-w-0 flex-col xl:border-r xl:border-slate-200 xl:pr-10 2xl:pr-12">
        {onResumeLast ? (
          <Button
            className="mb-6 h-auto justify-between rounded-lg border-indigo-200 bg-indigo-50/70 px-4 py-3 text-indigo-950 hover:bg-indigo-100/70"
            onClick={onResumeLast}
            type="button"
            variant="outline"
          >
            <span className="inline-flex items-center gap-2">
              <RefreshCcw size={15} />
              Continue your last generation task
            </span>
            <ArrowRight size={15} />
          </Button>
        ) : null}

        <div>
          <p className="text-xs font-bold uppercase tracking-[0.08em] text-indigo-600">AI game studio</p>
          <h1 className="mt-4 max-w-2xl font-display text-4xl font-semibold leading-[1.05] tracking-[-0.03em] text-slate-950 sm:text-[42px]">
            {remixSourceTitle ? `Remix ${remixSourceTitle}` : "Make something playable"}
          </h1>
          <p className="mt-4 max-w-lg text-base leading-7 text-slate-500">
            {remixSourceTitle
              ? "Describe the change. We’ll build a new playable version from the current game."
              : "Describe the core loop. We’ll build the first version."}
          </p>
        </div>

        <label className="mt-8 grid gap-3" htmlFor="idea">
          <span className="text-sm font-semibold text-slate-800">Game idea</span>
          <span className="relative">
            <textarea
              className="min-h-36 w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-4 pr-16 text-base leading-7 text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100"
              id="idea"
              maxLength={2000}
              onChange={(event) => onSetIdea(event.target.value)}
              placeholder={SAMPLE_PROMPT}
              value={idea}
            />
            <span className="pointer-events-none absolute bottom-3 right-4 text-xs font-medium text-slate-400">
              {idea.length}/2000
            </span>
          </span>
        </label>

        <div className="mt-4 grid gap-2.5">
          <BriefRow icon={RotateCcw} label="Core loop" value={brief.coreLoop} />
          <BriefRow icon={Trophy} label="Win condition" value={brief.winCondition} />
          <BriefRow icon={Palette} label="Visual style" value={brief.visualStyle} />
        </div>

        <div className="mt-7">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h2 className="text-sm font-semibold text-slate-800">Reference board</h2>
            <span className="text-xs font-medium text-slate-400">{files.length} / 6 uploaded</span>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <label
              className="group flex aspect-square cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-300 bg-white text-center text-slate-600 transition hover:border-indigo-400 hover:bg-indigo-50/50 hover:text-indigo-700"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                onPickFiles(event.dataTransfer.files);
              }}
            >
              <span className="flex size-10 items-center justify-center rounded-full bg-indigo-600 text-white shadow-sm transition group-hover:scale-105">
                {uploading ? <Loader2 className="size-5 animate-spin" /> : <Plus size={21} />}
              </span>
              <span className="px-2 text-xs font-semibold">{uploading ? "Uploading..." : "Add reference"}</span>
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

            {files.length > 0
              ? files.slice(0, 2).map((file) => (
                  <div className="group relative aspect-square overflow-hidden rounded-xl border border-slate-200 bg-slate-100" key={file.id}>
                    {file.kind === "image" && file.url ? (
                      <img alt="" className="size-full object-cover" src={file.url} />
                    ) : (
                      <span className="flex size-full items-center justify-center text-slate-500">
                        <FileImage size={28} />
                      </span>
                    )}
                    <Button
                      aria-label={`Remove ${file.name}`}
                      className="absolute right-2 top-2 size-8 rounded-full bg-slate-950/80 text-white opacity-0 shadow-sm hover:bg-slate-950 group-focus-within:opacity-100 group-hover:opacity-100"
                      onClick={() => onRemoveFile(file.id)}
                      size="icon"
                      type="button"
                      variant="ghost"
                    >
                      <X size={14} />
                    </Button>
                  </div>
                ))
              : SAMPLE_REFERENCES.map((sample) => (
                  <button
                    aria-label={`Use ${sample.alt}`}
                    className="group relative aspect-square overflow-hidden rounded-xl border border-slate-200 bg-slate-100 text-left transition hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-md focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-indigo-100"
                    disabled={uploading}
                    key={sample.src}
                    onClick={() => void addSampleReference(sample.src, sample.name)}
                    type="button"
                  >
                    <Image alt={sample.alt} className="object-cover transition duration-300 group-hover:scale-105" fill sizes="180px" src={sample.src} />
                  </button>
                ))}
          </div>
        </div>

        <div className="mt-auto flex flex-col gap-4 pt-8 sm:flex-row sm:items-center sm:justify-between">
          <div aria-label="Render mode" className="grid grid-cols-2 rounded-lg border border-slate-200 bg-white p-1" role="group">
            {(["2d", "3d"] as const).map((mode) => (
              <button
                aria-pressed={dimension === mode}
                className={cn(
                  "flex h-11 min-w-32 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold transition",
                  dimension === mode
                    ? "bg-indigo-50 text-indigo-700 shadow-sm ring-1 ring-indigo-200"
                    : "text-slate-500 hover:text-slate-800",
                )}
                key={mode}
                onClick={() => onSetDimension(mode)}
                type="button"
              >
                {mode === "2d" ? <Layers3 size={16} /> : <Box size={16} />}
                {mode === "2d" ? "2D Canvas" : "3D WebGL"}
              </button>
            ))}
          </div>

          <Button
            className="h-12 rounded-lg bg-indigo-600 px-6 text-white shadow-[0_12px_30px_rgba(79,70,229,0.25)] hover:bg-indigo-700 sm:min-w-48"
            disabled={!canGenerate}
            onClick={onGenerate}
            type="button"
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Gamepad2 size={18} />}
            {busy ? "Starting task..." : "Start building"}
          </Button>
        </div>
      </section>

      <aside className="min-w-0 xl:pl-10 2xl:pl-12">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-display text-2xl font-semibold tracking-[-0.02em] text-slate-950">First playable preview</h2>
          <Badge className="gap-2 border-0 bg-slate-100 px-3 py-1 text-slate-500 shadow-none" variant="outline">
            <span className="size-2 rounded-full bg-slate-400" />
            Not started
          </Badge>
        </div>

        <div className="relative mt-6 aspect-[5/4] min-h-[500px] overflow-hidden rounded-2xl border border-slate-200 bg-[#f7f7ff] shadow-[0_18px_50px_rgba(79,70,229,0.08)]">
          <Image
            alt="Soft lavender browser-game preview illustration"
            className="object-contain"
            fill
            priority
            sizes="(min-width: 1280px) 58vw, 100vw"
            src="/gameweave/create-runtime-preview.png"
          />
          <div className="absolute inset-x-0 bottom-7 flex justify-center px-5">
            <span className="rounded-lg border border-white/80 bg-white/88 px-5 py-2.5 text-sm font-semibold text-slate-500 shadow-sm backdrop-blur-md">
              Your game will appear here
            </span>
          </div>
        </div>

        <div className="mt-8 grid grid-cols-[1fr_auto_1fr_auto_1fr] items-start gap-3 px-2" aria-label="Build timeline">
          <TimelineStage active label="Brief" />
          <span className="mt-4 h-px min-w-12 bg-indigo-200" />
          <TimelineStage label="Build" />
          <span className="mt-4 h-px min-w-12 bg-slate-300" />
          <TimelineStage label="Play" />
        </div>

        <p className="mt-6 text-center text-sm text-slate-500">Usually ready for a first playtest in a few minutes.</p>
      </aside>
    </div>
  );
}

function BriefRow({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="grid min-h-14 grid-cols-[28px_auto_1fr_24px] items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 shadow-sm">
      <Icon className="text-indigo-600" size={18} />
      <span className="text-sm font-semibold text-slate-800">{label}</span>
      <span className="truncate text-sm text-slate-500">·&nbsp; {value}</span>
      <Edit3 className="text-slate-400" size={15} />
    </div>
  );
}

function TimelineStage({ active = false, label }: { active?: boolean; label: string }) {
  return (
    <div className="grid justify-items-center gap-2 text-center">
      <span
        className={cn(
          "flex size-9 items-center justify-center rounded-full border-2 bg-white",
          active ? "border-indigo-300 text-indigo-600 shadow-[0_0_0_6px_rgba(99,102,241,0.1)]" : "border-slate-300 text-slate-400",
        )}
      >
        <span className={cn("size-3 rounded-full", active ? "bg-indigo-600" : "bg-transparent")} />
      </span>
      <span className={cn("text-sm font-semibold", active ? "text-indigo-600" : "text-slate-500")}>{label}</span>
    </div>
  );
}

function buildLiveBrief(idea: string) {
  const text = idea.trim().toLowerCase();
  if (!text) {
    return {
      coreLoop: "Drift through boost gates",
      winCondition: "Beat the clock",
      visualStyle: "Neon night circuit",
    };
  }

  const coreLoop = text.includes("drift")
    ? "Drift through boost gates"
    : text.includes("runner")
      ? "Dodge obstacles and build speed"
      : text.includes("puzzle") || text.includes("rotate")
        ? "Solve linked path puzzles"
        : summarizeIdea(idea);

  const winCondition = text.includes("clock") || text.includes("time trial") || text.includes("one-minute")
    ? "Beat the clock"
    : text.includes("survive")
      ? "Survive to the finish"
      : text.includes("guide") || text.includes("home")
        ? "Guide every spirit home"
        : "Reach a clear playable goal";

  const visualStyle = text.includes("neon") || text.includes("cyberpunk")
    ? "Neon night circuit"
    : text.includes("cozy") || text.includes("forest")
      ? "Cozy illustrated forest"
      : text.includes("fantasy")
        ? "Painterly fantasy adventure"
        : "Style inferred from your brief";

  return { coreLoop, winCondition, visualStyle };
}

function summarizeIdea(idea: string) {
  const firstSentence = idea.trim().split(/[.!?]/)[0] || idea.trim();
  return firstSentence.length > 48 ? `${firstSentence.slice(0, 45).trim()}...` : firstSentence;
}
