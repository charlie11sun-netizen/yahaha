"use client";

import { Edit3, FileText, Image as ImageIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

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
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardContent className="grid gap-5 p-5 md:grid-cols-[auto_1fr_auto] md:items-center">
        <span className="flex size-12 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
          <FileText size={26} />
        </span>
        <div className="min-w-0 space-y-3">
          <h2 className="font-display text-xl font-semibold tracking-normal text-slate-950">Game brief</h2>
          <Badge className="max-w-full truncate border-indigo-200 bg-indigo-50 text-indigo-700" variant="outline">
            {brief.title}
          </Badge>
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
            <ImageIcon size={16} />
            <span>
              {brief.assetCount} asset{brief.assetCount === 1 ? "" : "s"} uploaded
            </span>
            <span>{brief.genre}</span>
            <span>{brief.style}</span>
            <span>{brief.runtime}</span>
          </div>
        </div>
        <Button className="rounded-lg" onClick={onEditBrief} type="button" variant="outline">
          <Edit3 size={16} />
          Edit brief
        </Button>
      </CardContent>
    </Card>
  );
}
