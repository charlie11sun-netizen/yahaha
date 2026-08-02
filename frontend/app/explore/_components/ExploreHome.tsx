import { cn } from "@/lib/utils";
import type { GameListResponse } from "@/lib/types";
import { ExploreFeatureStrip } from "./ExploreFeatureStrip";
import { ExploreFooter } from "./ExploreFooter";
import { ExploreGamesSection } from "./ExploreGamesSection";
import { ExploreHero } from "./ExploreHero";
import { ExploreHowSection } from "./ExploreHowSection";
import { Aurora } from "./ExplorePanels";
import { ExploreSpotlightSection } from "./ExploreSpotlightSection";
import type { HomeGame } from "../_lib/explore-data";

export function ExploreHome({
  featured,
  initialError,
  initialGames,
  tags,
  trending,
}: {
  featured?: HomeGame;
  initialError: boolean;
  initialGames: GameListResponse;
  tags: string[];
  trending: HomeGame[];
}) {
  return (
    <div className={cn("relative isolate overflow-hidden bg-[#f7f8fc] text-slate-900")}>
      <Aurora />
      <ExploreHero featured={featured} trending={trending} />
      <ExploreSpotlightSection featured={featured} />
      <ExploreGamesSection initialError={initialError} initialGames={initialGames} tags={tags} />
      <ExploreHowSection />
      <ExploreFeatureStrip />
      <ExploreFooter />
    </div>
  );
}
