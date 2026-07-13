"use client";

import { Edit3, FileText, Image as ImageIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

type Brief = {
  title: string;
  assetCount: number;
  genre: string;
  style: string;
  runtime: string;
};

export function CreateBriefCard({
  brief,
  onEditBrief,
}: {
  brief: Brief;
  onEditBrief: () => void;
}) {
  return (
    <div className="mt-3 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 text-sm text-slate-500">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
        <FileText size={17} />
      </span>
      <h2 className="sr-only">Game brief</h2>
      <strong className="max-w-full truncate font-medium text-indigo-700 sm:max-w-[320px]">{brief.title}</strong>
      <span className="hidden text-slate-300 sm:inline">/</span>
      <span className="inline-flex items-center gap-1.5">
        <ImageIcon size={14} />
        {brief.assetCount} asset{brief.assetCount === 1 ? "" : "s"}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        {[brief.genre, brief.style, brief.runtime].map((item) => (
          <span className="before:mr-2 before:text-slate-300 before:content-['·']" key={item}>
            {item}
          </span>
        ))}
      </div>
      <Button className="h-8 rounded-lg px-2 text-slate-500" onClick={onEditBrief} size="sm" type="button" variant="ghost">
        <Edit3 size={14} />
        Edit brief
      </Button>
    </div>
  );
}
