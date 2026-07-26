"use client";

import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  Check,
  Circle,
  ClipboardList,
  FileCode2,
  FileImage,
  Images,
  Play,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { GeneratedTaskAsset, Task, UploadedAsset } from "@/lib/types";
import { buildStepRows, getActiveStepIndex, type StepRow } from "../_lib/create-progress";

type SourcePreview = {
  alt: string;
  name: string;
  src: string;
};

const FALLBACK_SOURCES: SourcePreview[] = [
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
  {
    alt: "Generated game style reference",
    name: "style-reference.png",
    src: "/gameweave/create-runtime-preview.png",
  },
];

type AssetAudit = {
  passed?: boolean;
  released_with_warnings?: boolean;
  required_asset_coverage?: number;
  failed_frame_ids?: string[];
};

export function CreateAssetWorkspace({
  files,
  generatedAssets,
  onBack,
  onOpenActivity,
  onPreview,
  task,
}: {
  files: UploadedAsset[];
  generatedAssets: GeneratedTaskAsset[];
  onBack: () => void;
  onOpenActivity: () => void;
  onPreview: () => void;
  task?: Task;
}) {
  const rows = useMemo(() => buildStepRows(task), [task]);
  const activeIndex = getActiveStepIndex(rows, task);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showManifest, setShowManifest] = useState(false);
  const [openBatches, setOpenBatches] = useState<Record<string, boolean>>({
    "batch-1": true,
    "batch-2": true,
  });

  const sources = buildSources(files);
  const batches = splitBatches(generatedAssets);
  const selected = generatedAssets[selectedIndex] || generatedAssets[0];
  const selectedAudit = auditFor(selected);
  const selectedStatus = auditStatus(selectedAudit);
  const allComplete = task?.status === "succeeded";
  const activeLabel = rows[activeIndex]?.label || (allComplete ? "Ready to publish" : "Assets prepared");

  const toggleBatch = (batchId: string) => {
    setOpenBatches((current) => ({ ...current, [batchId]: !current[batchId] }));
  };

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="border-b border-slate-200/80 pb-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Button className="h-auto px-0 text-sm font-semibold text-indigo-700 hover:bg-transparent hover:text-indigo-800" onClick={onBack} type="button" variant="ghost">
              <ArrowLeft size={16} />
              Back to build workspace
            </Button>
            <div className="mt-4 flex items-start gap-3">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
                <Images size={21} />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-bold uppercase tracking-[0.14em] text-indigo-600">Asset control room</p>
                <h1 className="mt-1 font-display text-3xl font-semibold leading-tight text-slate-950 sm:text-4xl">Generated assets</h1>
                <p className="mt-2 text-sm text-slate-500">
                  Review the source materials, generated batches, and runtime-ready frames for this task.
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge className="gap-2 border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-700" variant="outline">
              <span className="size-2 rounded-full bg-emerald-500" />
              {allComplete ? "Ready to publish" : activeLabel}
            </Badge>
            <Button className="rounded-lg" onClick={onOpenActivity} type="button" variant="outline">
              <ClipboardList size={16} />
              View activity
            </Button>
          </div>
        </div>

        <AssetProgressRail activeIndex={activeIndex} rows={rows} />
      </header>

      <div className="grid items-start gap-5 xl:grid-cols-[220px_minmax(0,1fr)_300px]">
        <aside className="min-w-0 xl:sticky xl:top-24">
          <div className="rounded-xl border border-slate-200/90 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-display text-base font-semibold text-slate-950">Source materials</h2>
              <Badge className="border-indigo-100 bg-indigo-50 text-indigo-700" variant="outline">
                {sources.length}
              </Badge>
            </div>
            <div className="mt-2 flex items-center justify-between gap-3 text-xs text-slate-500">
              <span>Keep sources visible</span>
              <span className="relative inline-flex h-5 w-9 rounded-full bg-indigo-600">
                <span className="absolute right-1 top-1 size-3 rounded-full bg-white shadow-sm" />
              </span>
            </div>

            <div className="mt-4 grid gap-4">
              {sources.map((source) => (
                <figure key={`${source.name}-${source.src}`}>
                  <div className="aspect-[4/3] overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
                    <img alt={source.alt} className="size-full object-cover" src={source.src} />
                  </div>
                  <figcaption className="mt-2 truncate text-xs font-semibold text-slate-700">{source.name}</figcaption>
                </figure>
              ))}
            </div>
          </div>
        </aside>

        <main className="min-w-0 rounded-xl border border-slate-200/90 bg-white p-4 shadow-sm sm:p-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Sparkles className="text-indigo-600" size={18} />
                <h2 className="font-display text-xl font-semibold text-slate-950">Generated assets</h2>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {generatedAssets.length ? `${generatedAssets.length} generated asset${generatedAssets.length === 1 ? "" : "s"} linked to this task.` : "Generated assets will appear here as the task progresses."}
              </p>
            </div>
            <Badge className="gap-1.5 border-indigo-100 bg-indigo-50 text-indigo-700" variant="outline">
              <FileImage size={14} />
              {generatedAssets.length} total
            </Badge>
          </div>

          <div className="mt-5 grid gap-4">
            {batches.map((batch) => {
              const isOpen = openBatches[batch.id] ?? true;
              return (
                <section className="overflow-hidden rounded-xl border border-slate-200" key={batch.id}>
                  <button
                    aria-expanded={isOpen}
                    className="flex w-full items-center justify-between gap-4 bg-slate-50/80 px-4 py-3 text-left transition hover:bg-indigo-50/60"
                    onClick={() => toggleBatch(batch.id)}
                    type="button"
                  >
                    <span>
                      <strong className="block text-sm font-semibold text-slate-900">{batch.title}</strong>
                      <span className="mt-0.5 block text-xs text-slate-500">{batch.items.length} asset{batch.items.length === 1 ? "" : "s"} · source-linked generation batch</span>
                    </span>
                    {isOpen ? <ChevronUp className="text-slate-400" size={17} /> : <ChevronDown className="text-slate-400" size={17} />}
                  </button>

                  {isOpen ? (
                    <div className="grid gap-3 p-3 sm:grid-cols-2 2xl:grid-cols-4">
                      {batch.items.map(({ asset, index }) => (
                        <AssetTile
                          asset={asset}
                          index={index}
                          key={`${asset.key}-${index}`}
                          onSelect={() => setSelectedIndex(index)}
                          selected={index === selectedIndex}
                        />
                      ))}
                    </div>
                  ) : null}
                </section>
              );
            })}
          </div>

          {generatedAssets.length === 0 ? (
            <div className="mt-5 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
              <FileImage className="mx-auto text-slate-400" size={24} />
              <p className="mt-3 text-sm font-semibold text-slate-700">Waiting for the first asset batch</p>
              <p className="mt-1 text-sm text-slate-500">You can keep this view open while the generation task continues.</p>
            </div>
          ) : null}
        </main>

        <aside className="min-w-0 xl:sticky xl:top-24">
          <div className="rounded-xl border border-slate-200/90 bg-white p-4 shadow-sm sm:p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-display text-base font-semibold text-slate-950">Selected asset</h2>
              <Badge className="border-slate-200 bg-slate-50 text-slate-600" variant="outline">
                {selected ? `${selectedIndex + 1} of ${generatedAssets.length}` : "—"}
              </Badge>
            </div>

            <div className="mt-4 aspect-square overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
              {selected ? <img alt={selected.name} className="size-full object-contain p-5" src={selected.data_url} /> : <FileImage className="mx-auto mt-24 text-slate-300" size={32} />}
            </div>

            <h3 className="mt-4 truncate font-display text-xl font-semibold text-slate-950">{selected?.name || "Waiting for asset"}</h3>
            <p className="mt-1 text-sm text-slate-500">{selected ? "Linked to the current generation batch" : "The selected asset will appear here."}</p>

            <div className="mt-4 flex flex-wrap items-center gap-1.5 text-[11px] font-medium text-slate-500">
              {[
                ["Source", true],
                ["Generate", true],
                ["Slice", true],
                ["Audit", selectedStatus === "Audited"],
                ["Runtime", allComplete],
              ].map(([label, complete], index, items) => (
                <span className="inline-flex items-center gap-1.5" key={String(label)}>
                  <span className={cn("rounded-md px-1.5 py-1", complete ? "bg-emerald-50 text-emerald-700" : "bg-slate-50 text-slate-500")}>{label}</span>
                  {index < items.length - 1 ? <span className="text-slate-300">→</span> : null}
                </span>
              ))}
            </div>

            <div className={cn("mt-5 rounded-xl border p-4", selectedStatus === "Needs review" ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50")}>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <span className={cn("flex size-7 items-center justify-center rounded-full", selectedStatus === "Needs review" ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700")}>
                  {selectedStatus === "Needs review" ? <SlidersHorizontal size={15} /> : <Check size={15} />}
                </span>
                Frame Audit · {selectedStatus}
              </div>
              <p className="mt-1 pl-9 text-xs text-slate-600">{coverageLabel(selectedAudit)}</p>
            </div>

            <div className="mt-5 grid gap-2">
              <Button className="w-full rounded-lg" disabled={!task?.game} onClick={onPreview} type="button" variant="outline">
                <Play size={16} />
                View in runtime
              </Button>
              <Button className="w-full rounded-lg" onClick={() => setShowManifest((current) => !current)} type="button">
                <FileCode2 size={16} />
                {showManifest ? "Hide asset manifest" : "Open asset manifest"}
              </Button>
            </div>

            {showManifest ? <ManifestSummary asset={selected} /> : null}
          </div>
        </aside>
      </div>
    </div>
  );
}

function AssetProgressRail({ activeIndex, rows }: { activeIndex: number; rows: StepRow[] }) {
  const visibleRows = rows.length > 8 ? rows.filter((row, index) => index < 5 || index >= rows.length - 3 || index === activeIndex) : rows;
  return (
    <div className="mt-6 overflow-x-auto pb-1">
      <ol className="flex min-w-[760px] items-start gap-0" aria-label="Generation progress">
        {visibleRows.map((row, index) => {
          const isActive = row.status === "running" || index === visibleRows.findIndex((item) => item.key === rows[activeIndex]?.key);
          const isComplete = row.status === "completed";
          return (
            <li className="relative flex min-w-0 flex-1 flex-col items-center text-center" key={`${row.key}-${index}`}>
              {index < visibleRows.length - 1 ? <span className={cn("absolute left-1/2 right-[-50%] top-4 h-px", isComplete ? "bg-emerald-300" : "bg-slate-200")} /> : null}
              <span className={cn("relative z-10 flex size-8 items-center justify-center rounded-full border-2 bg-white text-xs font-semibold", isComplete ? "border-emerald-400 bg-emerald-500 text-white" : isActive ? "border-indigo-500 text-indigo-700" : "border-slate-200 text-slate-400")}>
                {isComplete ? <Check size={14} /> : isActive ? <Circle className="fill-indigo-500 text-indigo-500" size={11} /> : index + 1}
              </span>
              <span className={cn("mt-2 max-w-24 text-[11px] leading-4", isActive ? "font-semibold text-indigo-700" : isComplete ? "text-slate-700" : "text-slate-400")}>{row.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function AssetTile({ asset, index, onSelect, selected }: { asset: GeneratedTaskAsset; index: number; onSelect: () => void; selected: boolean }) {
  const audit = auditFor(asset);
  const status = auditStatus(audit);
  return (
    <button className={cn("group min-w-0 rounded-xl border p-2.5 text-left transition", selected ? "border-indigo-400 bg-indigo-50/60 shadow-[0_0_0_3px_rgba(99,102,241,0.1)]" : "border-slate-200 bg-white hover:border-indigo-200 hover:bg-indigo-50/30")} onClick={onSelect} type="button">
      <div className="relative aspect-square overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
        <img alt={asset.name} className="size-full object-contain p-2 transition duration-300 group-hover:scale-[1.03]" src={asset.data_url} />
        <span className={cn("absolute left-2 top-2 flex size-6 items-center justify-center rounded-full text-[11px] font-bold", selected ? "bg-indigo-600 text-white" : "bg-white/90 text-slate-600 shadow-sm")}>{index + 1}</span>
      </div>
      <p className="mt-2 truncate text-sm font-semibold text-slate-800">{asset.name || asset.key}</p>
      <p className="mt-0.5 truncate text-xs text-slate-500">{asset.semantic_ids?.[0] || asset.kind || "Generated image"}</p>
      <span className={cn("mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-semibold", status === "Audited" ? "bg-emerald-50 text-emerald-700" : status === "Needs review" ? "bg-amber-50 text-amber-700" : "bg-sky-50 text-sky-700")}>
        <span className={cn("size-1.5 rounded-full", status === "Audited" ? "bg-emerald-500" : status === "Needs review" ? "bg-amber-500" : "bg-sky-500")} />
        {status}
      </span>
    </button>
  );
}

function ManifestSummary({ asset }: { asset?: GeneratedTaskAsset }) {
  if (!asset) return null;
  const audit = auditFor(asset);
  return (
    <dl className="mt-4 divide-y divide-slate-200 rounded-xl border border-slate-200 bg-slate-50 text-xs">
      <ManifestRow label="Key" value={asset.key} />
      <ManifestRow label="Kind" value={asset.kind} />
      <ManifestRow label="Format" value={asset.content_type} />
      <ManifestRow label="Bytes" value={asset.bytes.toLocaleString()} />
      <ManifestRow label="Semantic frames" value={String(asset.semantic_ids?.length || 0)} />
      <ManifestRow label="Audit" value={coverageLabel(audit)} />
    </dl>
  );
}

function ManifestRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[auto_1fr] gap-3 px-3 py-2.5 first:pt-3 last:pb-3">
      <dt className="font-semibold text-slate-500">{label}</dt>
      <dd className="truncate text-right font-medium text-slate-700">{value}</dd>
    </div>
  );
}

function buildSources(files: UploadedAsset[]) {
  if (files.length === 0) return FALLBACK_SOURCES;
  return files.slice(0, 3).map((file, index) => ({
    alt: file.name,
    name: file.name,
    src: file.kind === "image" && file.url ? file.url : FALLBACK_SOURCES[index % FALLBACK_SOURCES.length].src,
  }));
}

function splitBatches(assets: GeneratedTaskAsset[]) {
  if (assets.length === 0) return [];
  const firstSize = Math.max(1, Math.ceil(assets.length / 2));
  const groups = [assets.slice(0, firstSize), assets.slice(firstSize)].filter((items) => items.length > 0);
  return groups.map((items, index) => ({
    id: `batch-${index + 1}`,
    title: index === 0 ? "Batch 01 · Character set" : "Batch 02 · World & pickups",
    items: items.map((asset) => ({ asset, index: assets.indexOf(asset) })),
  }));
}

function auditFor(asset?: GeneratedTaskAsset): AssetAudit {
  return (asset?.frame_audit || {}) as AssetAudit;
}

function auditStatus(audit: AssetAudit) {
  if (audit.passed === true && !audit.released_with_warnings) return "Audited";
  if (audit.passed === false || audit.released_with_warnings || (audit.failed_frame_ids?.length || 0) > 0) return "Needs review";
  return "Checking";
}

function coverageLabel(audit: AssetAudit) {
  if (typeof audit.required_asset_coverage === "number") return `${Math.round(audit.required_asset_coverage * 100)}% required coverage`;
  return auditStatus(audit) === "Audited" ? "Passed · required coverage verified" : "Awaiting frame audit";
}
