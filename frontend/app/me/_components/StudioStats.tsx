"use client";

import { Gamepad2, Pencil, Play, Sparkles } from "lucide-react";

import { fmt } from "@/lib/format";
import { StatCard } from "./StudioPanels";

export function StudioStats({
  draftCount,
  publishedCount,
  taskCount,
  totalPlays,
}: {
  draftCount: number;
  publishedCount: number;
  taskCount: number;
  totalPlays: number;
}) {
  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard icon={Gamepad2} label="Published Games" value={String(publishedCount)} />
      <StatCard icon={Pencil} label="Draft Games" value={String(draftCount)} />
      <StatCard icon={Sparkles} label="Generation Tasks" value={String(taskCount)} />
      <StatCard icon={Play} label="Total Plays" value={fmt(totalPlays)} />
    </section>
  );
}
