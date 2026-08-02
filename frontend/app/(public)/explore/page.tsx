import type { Metadata } from "next";

import { ExploreHome } from "@/app/explore/_components/ExploreHome";
import { toHomeGame } from "@/app/explore/_lib/explore-data";
import { getPublicGames, getPublicTags } from "@/lib/server-api";
import type { GameListResponse } from "@/lib/types";

export const metadata: Metadata = {
  title: "Explore AI Games · GameWeave AI",
  description: "Discover playable web games generated and published by the GameWeave community.",
};

const EMPTY_GAMES: GameListResponse = { items: [], total: 0, has_more: false };

export default async function ExplorePage() {
  const [newestResult, popularResult, tagsResult] = await Promise.allSettled([
    getPublicGames("", "All", { sort: "newest", limit: 12 }),
    getPublicGames("", "All", { sort: "popular", limit: 24 }),
    getPublicTags(),
  ]);
  const newest = newestResult.status === "fulfilled" ? newestResult.value : EMPTY_GAMES;
  const popular = popularResult.status === "fulfilled" ? popularResult.value.items.map(toHomeGame) : [];
  const tags = tagsResult.status === "fulfilled" ? tagsResult.value.tags : [];

  return (
    <ExploreHome
      featured={popular[0]}
      initialError={newestResult.status === "rejected"}
      initialGames={newest}
      tags={tags}
      trending={popular.slice(0, 4)}
    />
  );
}
