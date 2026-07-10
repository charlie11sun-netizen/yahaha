"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { GameListResponse } from "@/lib/types";
import { cn } from "@/lib/utils";
import { GameCard, GameCardSkeleton } from "./ExplorePanels";
import { SHELL, toHomeGame } from "../_lib/explore-data";

export function ExploreGamesSection({
  initialError,
  initialGames,
  tags,
}: {
  initialError: boolean;
  initialGames: GameListResponse;
  tags: string[];
}) {
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState("All");
  const [limit, setLimit] = useState(12);
  const [sort, setSort] = useState<"newest" | "popular">("newest");
  const backendTag = activeFilter === "AI Generated" ? "All" : activeFilter;
  const isInitialQuery = !query && backendTag === "All" && sort === "newest" && limit === 12;
  const gamesQ = useQuery({
    queryKey: ["games", query, backendTag, sort, limit],
    queryFn: () => api.games(query, backendTag, { sort, limit }),
    initialData: isInitialQuery && !initialError ? initialGames : undefined,
    staleTime: isInitialQuery ? 30_000 : 0,
  });

  useEffect(() => {
    setLimit(12);
  }, [query, activeFilter, sort]);

  const visibleGames = useMemo(() => {
    const mapped = (gamesQ.data?.items ?? []).map(toHomeGame);
    return activeFilter === "AI Generated" ? mapped.filter((game) => game.ai) : mapped;
  }, [activeFilter, gamesQ.data?.items]);
  const filterTabs = useMemo(() => {
    const merged = ["All", "AI Generated", ...tags, "Arcade", "Puzzle", "RPG", "Adventure"];
    return Array.from(new Set(merged)).slice(0, 6);
  }, [tags]);

  return (
    <section id="explore" className={cn(SHELL, "scroll-mt-20 pt-12 pb-6")}>
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight text-slate-900">Explore Published Games</h2>
          {gamesQ.isError ? (
            <p className="mt-1 text-xs font-medium text-rose-500">Could not load games - the backend may be unreachable.</p>
          ) : (
            <p className="mt-1 text-sm text-slate-500">Fresh drops from the community, generated and published with AI.</p>
          )}
        </div>
        <div className="flex w-full items-center gap-2.5 sm:w-auto">
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search games..."
              aria-label="Search games"
              className="h-10 rounded-full border-slate-200 bg-white/80 pl-9 backdrop-blur"
            />
          </div>
          <div className="flex rounded-full border border-slate-200 bg-white/80 p-1 backdrop-blur">
            {(["newest", "popular"] as const).map((nextSort) => (
              <button
                key={nextSort}
                type="button"
                onClick={() => setSort(nextSort)}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-xs font-semibold capitalize transition-colors",
                  sort === nextSort ? "bg-slate-900 text-white shadow-sm" : "text-slate-500 hover:text-slate-800",
                )}
              >
                {nextSort}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {filterTabs.map((tab) => {
          const active = activeFilter === tab;
          return (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveFilter(tab)}
              className={cn(
                "rounded-full px-4 py-2 text-xs font-semibold transition-all",
                active
                  ? "bg-gradient-to-r from-violet-600 to-blue-500 text-white shadow-md shadow-violet-500/25"
                  : "border border-slate-200 bg-white/70 text-slate-600 backdrop-blur hover:border-violet-300 hover:text-violet-700",
              )}
            >
              {tab}
            </button>
          );
        })}
      </div>

      <div className="mt-7 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {gamesQ.isLoading ? (
          Array.from({ length: 6 }).map((_, index) => <GameCardSkeleton key={index} />)
        ) : gamesQ.isError ? (
          <div className="col-span-full rounded-2xl border border-dashed border-rose-200 bg-rose-50/60 p-12 text-center text-sm text-rose-600">
            <p>Could not load games. Check your connection or try again.</p>
            <Button className="mt-4 rounded-full" variant="outline" onClick={() => gamesQ.refetch()}>
              Retry
            </Button>
          </div>
        ) : visibleGames.length === 0 ? (
          <div className="col-span-full rounded-2xl border border-dashed border-slate-200 bg-white/60 p-12 text-center text-sm text-slate-500">
            No published games match this search.
          </div>
        ) : (
          visibleGames.map((game) => (
            <GameCard key={game.id ?? game.title} game={game} />
          ))
        )}
      </div>

      {gamesQ.data?.has_more && !gamesQ.isLoading ? (
        <div className="mt-8 flex justify-center">
          <Button variant="outline" onClick={() => setLimit((value) => value + 12)} className="rounded-full border-slate-200 bg-white/70 px-6 backdrop-blur">
            Load more games
          </Button>
        </div>
      ) : null}
    </section>
  );
}
