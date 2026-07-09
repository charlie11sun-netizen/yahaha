"use client";

import { cn } from "@/lib/utils";
import { FeaturedSpotlight } from "./ExplorePanels";
import { SHELL, type HomeGame } from "../_lib/explore-data";

export function ExploreSpotlightSection({
  featured,
  onPlay,
}: {
  featured?: HomeGame;
  onPlay: (id?: string) => void;
}) {
  if (!featured) return null;

  return (
    <section className={cn(SHELL, "pb-4")}>
      <FeaturedSpotlight game={featured} onPlay={onPlay} />
    </section>
  );
}
