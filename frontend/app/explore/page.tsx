"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ArrowRight, Database, Gamepad2, Globe2, MessageCircle, PlaySquare, Search, Sparkles } from "lucide-react";

import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Aurora, FeaturedSpotlight, GameCard, GameCardSkeleton, ShowcaseCard } from "./_components/ExplorePanels";
import {
  SHELL,
  featureStrip,
  flowSteps,
  footerColumns,
  scrollToId,
  toHomeGame,
  type HomeGame,
} from "./_lib/explore-data";

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState("All");
  const [limit, setLimit] = useState(12);
  const [sort, setSort] = useState<"newest" | "popular">("newest");

  const backendTag = activeFilter === "AI Generated" ? "All" : activeFilter;
  const gamesQ = useQuery({
    queryKey: ["games", query, backendTag, sort, limit],
    queryFn: () => api.games(query, backendTag, { sort, limit }),
  });

  useEffect(() => {
    setLimit(12);
  }, [query, activeFilter, sort]);

  const allGamesQ = useQuery({
    queryKey: ["games", "", "All"],
    queryFn: () => api.games("", "All"),
  });
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.tags });

  // 加载中/失败一律不用假数据顶替：骨架屏 + 明确错误态（假卡会侵蚀用户信任）
  const allGames = useMemo(() => {
    const live = allGamesQ.data?.items;
    return live ? live.map(toHomeGame) : [];
  }, [allGamesQ.data?.items]);

  const visibleGames = useMemo(() => {
    const live = gamesQ.data?.items;
    const mapped = live ? live.map(toHomeGame) : [];
    // 搜索/标签已在服务端过滤；客户端只保留服务端没有的 "AI Generated" 维度
    return activeFilter === "AI Generated" ? mapped.filter((game) => game.ai) : mapped;
  }, [activeFilter, gamesQ.data?.items]);

  const rankedGames = useMemo(() => [...allGames].sort((a, b) => b.playsNumber - a.playsNumber), [allGames]);
  const featured: HomeGame | undefined = rankedGames[0];
  const trending = rankedGames.slice(0, 4);

  const filterTabs = useMemo(() => {
    const liveTags = tagsQ.data?.tags ?? [];
    const merged = ["All", "AI Generated", ...liveTags, "Arcade", "Puzzle", "RPG", "Adventure"];
    return Array.from(new Set(merged)).slice(0, 6);
  }, [tagsQ.data?.tags]);

  const goCreate = () => router.push("/create");
  const goDetail = (id?: string) => (id ? router.push(`/games/${id}`) : scrollToId("explore"));
  const goPlay = (id?: string) => (id ? router.push(`/play/${id}`) : scrollToId("explore"));
  const goFooter = (label: string) => {
    const map: Record<string, string> = {
      Explore: "/explore", Create: "/create", "My Games": "/me", "How It Works": "/explore#how",
      About: "/about", Contact: "/about", Blog: "/about", Careers: "/about", Documentation: "/about",
    };
    router.push(map[label] || "/");
  };

  return (
    <div className="relative isolate overflow-hidden bg-[#f7f8fc] text-slate-900">
      <Aurora />

      {/* ─── Hero ─────────────────────────────────────────────── */}
      <section className={cn(SHELL, "grid items-center gap-12 pt-14 pb-10 lg:grid-cols-[0.92fr_1.08fr] lg:pt-20 lg:pb-16")}>
        <div className="[animation:pf-rise-in_0.6s_var(--pf-ease)_both]">
          <Badge variant="secondary" className="gap-1.5 rounded-full border border-violet-200/70 bg-white/70 px-3 py-1.5 text-violet-700 backdrop-blur">
            <Sparkles className="size-3.5" />
            AI-native game platform
          </Badge>
          <h1 className="mt-5 font-display text-[2.75rem] leading-[1.04] font-bold tracking-tight text-slate-950 sm:text-6xl">
            Turn any idea into a{" "}
            <span className="bg-gradient-to-r from-violet-600 via-indigo-500 to-blue-500 bg-clip-text text-transparent">
              playable AI game
            </span>
          </h1>
          <p className="mt-5 max-w-md text-[15px] leading-relaxed text-slate-600">
            Describe a game concept, upload assets, and let AI agents generate, package, and publish a
            playable experience — in seconds.
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <Button
              size="lg"
              onClick={goCreate}
              className="bg-gradient-to-r from-violet-600 to-blue-500 text-white shadow-lg shadow-violet-500/30 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-violet-500/40"
            >
              <Sparkles className="size-4" />
              Create with AI
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => scrollToId("explore")}
              className="border-slate-200 bg-white/70 backdrop-blur transition-all hover:-translate-y-0.5"
            >
              <Gamepad2 className="size-4.5" />
              Explore Games
            </Button>
          </div>

          <div className="mt-9 flex flex-wrap items-center gap-x-3 gap-y-4">
            {flowSteps.map((step, index) => (
              <div key={step.title} className="flex items-center gap-3">
                <div className="flex flex-col items-center gap-2 text-center">
                  <div className={cn("flex size-12 items-center justify-center rounded-2xl bg-gradient-to-br text-white shadow-md", step.tint)}>
                    <step.icon className="size-5" />
                  </div>
                  <span className="text-xs font-semibold text-slate-700">
                    {index === flowSteps.length - 1 ? "Play" : step.title}
                  </span>
                </div>
                {index < flowSteps.length - 1 && <ArrowRight className="size-4 text-slate-300" />}
              </div>
            ))}
          </div>
        </div>

        {featured ? (
          <ShowcaseCard featured={featured} trending={trending} onOpen={goDetail} onPlay={goPlay} />
        ) : (
          <div aria-hidden className="h-[420px] animate-pulse rounded-3xl border border-slate-200 bg-white/60" />
        )}
      </section>

      {/* ─── Featured spotlight ───────────────────────────────── */}
      {featured && (
        <section className={cn(SHELL, "pb-4")}>
          <FeaturedSpotlight game={featured} onPlay={goPlay} />
        </section>
      )}

      {/* ─── Explore ──────────────────────────────────────────── */}
      <section id="explore" className={cn(SHELL, "scroll-mt-20 pt-12 pb-6")}>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="font-display text-2xl font-bold tracking-tight text-slate-900">Explore Published Games</h2>
            {gamesQ.isError ? (
              <p className="mt-1 text-xs font-medium text-rose-500">Could not load games — the backend may be unreachable.</p>
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
              {(["newest", "popular"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSort(s)}
                  className={cn(
                    "rounded-full px-3.5 py-1.5 text-xs font-semibold capitalize transition-colors",
                    sort === s ? "bg-slate-900 text-white shadow-sm" : "text-slate-500 hover:text-slate-800",
                  )}
                >
                  {s}
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
            Array.from({ length: 6 }).map((_, i) => <GameCardSkeleton key={i} />)
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
              <GameCard key={game.id ?? game.title} game={game} onOpen={() => goDetail(game.id)} onPlay={() => goPlay(game.id)} />
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

      {/* ─── How it works ─────────────────────────────────────── */}
      <section id="how" className={cn(SHELL, "scroll-mt-20 pt-12 pb-6")}>
        <h2 className="font-display text-2xl font-bold tracking-tight text-slate-900">From idea to play</h2>
        <p className="mt-1 text-sm text-slate-500">Four steps, fully automated by a team of AI agents.</p>
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {flowSteps.map((step, index) => (
            <Card
              key={step.title}
              className="group relative gap-0 overflow-hidden rounded-2xl border-slate-200/80 bg-white/80 p-5 backdrop-blur transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-slate-900/5"
            >
              <div className="flex items-center justify-between">
                <div className={cn("flex size-11 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-md", step.tint)}>
                  <step.icon className="size-5" />
                </div>
                <span className="font-display text-3xl font-bold text-slate-200 transition-colors group-hover:text-slate-300">
                  {String(index + 1).padStart(2, "0")}
                </span>
              </div>
              <h3 className="mt-4 font-display text-base font-bold text-slate-900">{step.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{step.detail}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* ─── Platform strip ───────────────────────────────────── */}
      <section className={cn(SHELL, "pt-10 pb-14")}>
        <Card className="grid grid-cols-1 gap-x-8 gap-y-7 rounded-3xl border-slate-200/80 bg-white/70 p-8 backdrop-blur sm:grid-cols-2 lg:grid-cols-4">
          {featureStrip.map((item) => (
            <div key={item.title} className="flex items-start gap-3.5">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-violet-100 bg-violet-50 text-violet-600">
                <item.icon className="size-5" />
              </div>
              <div>
                <strong className="block text-sm font-bold text-slate-900">{item.title}</strong>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">{item.detail}</p>
              </div>
            </div>
          ))}
        </Card>
      </section>

      {/* ─── Footer ───────────────────────────────────────────── */}
      <footer className="border-t border-slate-200/80 bg-white/70 backdrop-blur">
        <div className={cn(SHELL, "grid grid-cols-2 gap-8 py-12 md:grid-cols-[1.8fr_repeat(3,0.8fr)]")}>
          <div className="col-span-2 md:col-span-1">
            <div className="flex items-center gap-2.5">
              <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-600 to-blue-500 text-white shadow-md shadow-violet-500/30">
                <Globe2 className="size-4.5" />
              </span>
              <strong className="font-display text-base font-bold text-slate-900">GameWeave AI</strong>
            </div>
            <p className="mt-3 max-w-56 text-xs leading-relaxed text-slate-500">
              The AI-native platform for creating, sharing, and playing web games.
            </p>
            <div className="mt-4 flex gap-2">
              {[MessageCircle, Gamepad2, PlaySquare, Database].map((Icon, i) => (
                <button
                  key={i}
                  type="button"
                  aria-label="Social link"
                  className="flex size-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition-colors hover:border-violet-300 hover:text-violet-600"
                >
                  <Icon className="size-4" />
                </button>
              ))}
            </div>
          </div>
          {footerColumns.map((column) => (
            <div key={column.title} className="flex flex-col gap-2.5">
              <strong className="text-xs font-bold tracking-wide text-slate-900 uppercase">{column.title}</strong>
              {column.links.map((link) => (
                <button key={link} onClick={() => goFooter(link)} type="button" className="text-left text-xs text-slate-500 transition-colors hover:text-violet-600">
                  {link}
                </button>
              ))}
            </div>
          ))}
        </div>
        <div className={cn(SHELL, "flex flex-col items-center justify-between gap-3 border-t border-slate-200/70 py-5 sm:flex-row")}>
          <p className="text-xs text-slate-400">© 2024 GameWeave AI. All rights reserved.</p>
          <div className="flex gap-5">
            <button onClick={() => router.push("/privacy")} type="button" className="text-xs text-slate-400 transition-colors hover:text-violet-600">Privacy Policy</button>
            <button onClick={() => router.push("/terms")} type="button" className="text-xs text-slate-400 transition-colors hover:text-violet-600">Terms of Service</button>
            <button onClick={() => router.push("/about")} type="button" className="text-xs text-slate-400 transition-colors hover:text-violet-600">Docs</button>
          </div>
        </div>
      </footer>
    </div>
  );
}
