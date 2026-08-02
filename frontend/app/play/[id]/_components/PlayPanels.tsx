import { CircleAlert, CircleCheck, LoaderCircle, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";
import { runtimeLabel, type RuntimeKey, type RuntimeStatus } from "../_lib/play-runtime";

export function RuntimeList({
  compact = false,
  runtime,
}: {
  compact?: boolean;
  runtime: Record<RuntimeKey, RuntimeStatus>;
}) {
  const rows: { key: RuntimeKey; label: string }[] = [
    { key: "manifest", label: "Manifest" },
    { key: "sandbox", label: "Sandbox" },
    { key: "bundle", label: "Bundle" },
  ];

  return (
    <div className={cn("grid gap-3", compact ? "w-full max-w-md" : "w-full")}>
      {rows.map((row) => {
        const status = runtime[row.key];
        return (
          <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" key={row.key}>
            <RuntimeIcon status={status} />
            <span className="min-w-0 flex-1 font-medium text-slate-700">{row.label}</span>
            <strong className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{runtimeLabel(status)}</strong>
          </div>
        );
      })}
    </div>
  );
}

export function ActivityFeed({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="w-full max-w-md rounded-lg border border-slate-200 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-200">
      {lines.map((line, index) => (
        <p key={`${index}-${line}`}>{line}</p>
      ))}
    </div>
  );
}

function RuntimeIcon({ status }: { status: RuntimeStatus }) {
  if (status === "ready") return <CircleCheck className="size-4 text-emerald-600" />;
  if (status === "failed") return <CircleAlert className="size-4 text-rose-600" />;
  if (status === "running") return <LoaderCircle className="size-4 animate-spin text-indigo-600" />;
  return <ShieldCheck className="size-4 text-slate-400" />;
}
