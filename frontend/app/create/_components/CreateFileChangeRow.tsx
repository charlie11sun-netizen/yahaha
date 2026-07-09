"use client";

import { Edit3 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { fileChangeLabel, type FileChange } from "../_lib/create-state";

export function FileChangeRow({ change, showDiff = false }: { change: FileChange; showDiff?: boolean }) {
  const tone =
    change.action === "created"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : change.action === "deleted"
        ? "border-rose-200 bg-rose-50 text-rose-700"
        : "border-indigo-200 bg-indigo-50 text-indigo-700";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Edit3 className="size-4 text-slate-400" />
        <Badge className={tone} variant="outline">
          {fileChangeLabel(change.action)}
        </Badge>
        <strong className="min-w-0 break-all font-mono text-xs text-slate-700">{change.path}</strong>
        <b className="text-xs font-semibold text-emerald-600">+{change.added}</b>
        <b className="text-xs font-semibold text-rose-600">-{change.deleted}</b>
        {change.detail ? <em className="basis-full text-xs not-italic text-slate-500">{change.detail}</em> : null}
      </div>
      {showDiff && change.diff && change.diffFormat === "unified" ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold text-indigo-600">View diff</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
            {change.diff}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
