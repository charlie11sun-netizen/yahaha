"use client";

import { cn } from "@/lib/utils";
import { ExploreFeatureStrip } from "./ExploreFeatureStrip";
import { ExploreFooter } from "./ExploreFooter";
import { ExploreGamesSection } from "./ExploreGamesSection";
import { ExploreHero } from "./ExploreHero";
import { ExploreHowSection } from "./ExploreHowSection";
import { Aurora } from "./ExplorePanels";
import { ExploreSpotlightSection } from "./ExploreSpotlightSection";
import type { ExploreHomeState } from "../_lib/use-explore-home";

export function ExploreHome({ state }: { state: ExploreHomeState }) {
  const { featured, goCreate, goDetail, goFooter, goPlay, router, trending } = state;

  return (
    <div className={cn("relative isolate overflow-hidden bg-[#f7f8fc] text-slate-900")}>
      <Aurora />
      <ExploreHero
        featured={featured}
        onCreate={goCreate}
        onOpen={goDetail}
        onPlay={goPlay}
        trending={trending}
      />
      <ExploreSpotlightSection featured={featured} onPlay={goPlay} />
      <ExploreGamesSection {...state} />
      <ExploreHowSection />
      <ExploreFeatureStrip />
      <ExploreFooter onFooterLink={goFooter} onRoute={(path) => router.push(path)} />
    </div>
  );
}
