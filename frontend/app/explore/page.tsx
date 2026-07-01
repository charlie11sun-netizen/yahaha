"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  BadgeCheck,
  Calendar,
  CirclePlay,
  Database,
  Gamepad2,
  Globe2,
  Layers,
  ListChecks,
  MessageCircle,
  Play,
  PlaySquare,
  Search,
  Server,
  Sparkles,
  UploadCloud,
  WandSparkles,
} from "lucide-react";

import { api } from "@/lib/api";
import type { Game as ApiGame } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";

const SHELL = "mx-auto w-full max-w-[1240px] px-5 sm:px-8 lg:px-10";

type HomeGame = {
  id?: string;
  title: string;
  author: string;
  authorInit: string;
  summary: string;
  genre: string;
  image: string;
  thumb: string;
  heroImage?: string;
  tags: string[];
  date: string;
  plays: string;
  playsLabel: string;
  playsNumber: number;
  ai: boolean;
};

type Step = {
  title: string;
  detail: string;
  icon: LucideIcon;
  tint: string;
};

type BoundArt = { image: string; thumb: string; hero: string };

const ART = {
  neon: {
    image: "/gameweave/neon-featured.jpg",
    thumb: "/gameweave/neon-trending.jpg",
    hero: "/gameweave/neon-trending.jpg",
  },
  pixel: {
    image: "/gameweave/pixel-drifter.jpg",
    thumb: "/gameweave/thumb-pixel.jpg",
    hero: "/gameweave/pixel-drifter.jpg",
  },
  sky: {
    image: "/gameweave/skybound-chronicles.jpg",
    thumb: "/gameweave/thumb-skybound.jpg",
    hero: "/gameweave/skybound-chronicles.jpg",
  },
  dungeon: {
    image: "/gameweave/dungeon-dice.jpg",
    thumb: "/gameweave/dungeon-dice.jpg",
    hero: "/gameweave/dungeon-dice.jpg",
  },
  circuit: {
    image: "/gameweave/circuit-breakers.jpg",
    thumb: "/gameweave/thumb-circuit.jpg",
    hero: "/gameweave/circuit-breakers.jpg",
  },
  echoes: {
    image: "/gameweave/echoes-deep.jpg",
    thumb: "/gameweave/thumb-echoes.jpg",
    hero: "/gameweave/echoes-deep.jpg",
  },
  mystic: {
    image: "/gameweave/mystic-grove.jpg",
    thumb: "/gameweave/thumb-mystic.jpg",
    hero: "/gameweave/mystic-grove.jpg",
  },
  moonlit: {
    image: "/gameweave/covers/moonlit-koi.jpg",
    thumb: "/gameweave/covers/moonlit-koi.jpg",
    hero: "/gameweave/covers/moonlit-koi.jpg",
  },
  rune: {
    image: "/gameweave/covers/rune-circuit.jpg",
    thumb: "/gameweave/covers/rune-circuit.jpg",
    hero: "/gameweave/covers/rune-circuit.jpg",
  },
  cloud: {
    image: "/gameweave/covers/cloud-courier.jpg",
    thumb: "/gameweave/covers/cloud-courier.jpg",
    hero: "/gameweave/covers/cloud-courier.jpg",
  },
  orbit: {
    image: "/gameweave/covers/orbit-bloom.jpg",
    thumb: "/gameweave/covers/orbit-bloom.jpg",
    hero: "/gameweave/covers/orbit-bloom.jpg",
  },
  star: {
    image: "/gameweave/covers/star-catcher.jpg",
    thumb: "/gameweave/covers/star-catcher.jpg",
    hero: "/gameweave/covers/star-catcher.jpg",
  },
  color: {
    image: "/gameweave/covers/color-echo.jpg",
    thumb: "/gameweave/covers/color-echo.jpg",
    hero: "/gameweave/covers/color-echo.jpg",
  },
} satisfies Record<string, BoundArt>;

const boundArtPool = [
  ART.neon,
  ART.pixel,
  ART.sky,
  ART.dungeon,
  ART.circuit,
  ART.echoes,
  ART.mystic,
  ART.moonlit,
  ART.rune,
  ART.cloud,
  ART.orbit,
  ART.star,
  ART.color,
];

const titleArtMap: Record<string, BoundArt> = {
  "neon alley cat": ART.neon,
  "neon drift dodge": ART.neon,
  "pixel drifter": ART.pixel,
  "skybound chronicles": ART.sky,
  "circuit breakers": ART.circuit,
  "dungeon & dice": ART.dungeon,
  "echoes of the deep": ART.echoes,
  "mystic grove": ART.mystic,
  "lumen path": ART.dungeon,
  "moonlit koi": ART.moonlit,
  "rune circuit": ART.rune,
  "cloud courier": ART.cloud,
  "orbit bloom": ART.orbit,
  "star catcher": ART.star,
  "color echo": ART.color,
  "黄金矿工": ART.dungeon,
  "海底金币大冒险": ART.echoes,
  "魔法森林守卫战": ART.mystic,
  "迷你俄罗斯方块": ART.rune,
};

const keywordArtMap: Array<{ keywords: string[]; art: BoundArt }> = [
  { keywords: ["gold", "miner", "mine", "coin", "treasure", "黄金", "矿工", "金币", "宝石"], art: ART.dungeon },
  { keywords: ["forest", "magic", "grove", "森林", "魔法"], art: ART.mystic },
  { keywords: ["koi", "pond", "ocean", "deep", "sea", "海底", "水", "鱼"], art: ART.echoes },
  { keywords: ["tetris", "block", "rune", "circuit", "logic", "俄罗斯方块", "方块", "符文"], art: ART.rune },
  { keywords: ["space", "orbit", "star", "rocket", "宇宙", "太空", "星"], art: ART.orbit },
  { keywords: ["cloud", "flight", "courier", "sky", "云", "飞行"], art: ART.cloud },
  { keywords: ["neon", "cat", "cyberpunk", "runner", "霓虹", "赛博", "猫"], art: ART.neon },
  { keywords: ["drift", "race", "pixel", "racing", "像素", "赛车"], art: ART.pixel },
  { keywords: ["adventure", "chronicle", "fantasy", "quest", "冒险"], art: ART.sky },
  { keywords: ["echo", "color", "palette", "颜色"], art: ART.color },
];

const fallbackGames: HomeGame[] = [
  {
    title: "Neon Alley Cat",
    author: "PixelPioneer",
    authorInit: "P",
    summary:
      "A fast-paced arcade game where a street-smart cat dodges drones, hacks terminals, and outruns the city enforcers in a neon-soaked future.",
    genre: "Action Arcade",
    image: "/gameweave/neon-featured.jpg",
    thumb: "/gameweave/neon-trending.jpg",
    tags: ["Action", "Arcade", "Cyberpunk", "Cat", "AI Generated"],
    date: "May 8, 2024",
    plays: "12.4K",
    playsLabel: "12.4K Plays",
    playsNumber: 12400,
    ai: true,
  },
  {
    title: "Pixel Drifter",
    author: "RetroKnight",
    authorInit: "R",
    summary: "Drift through endless pixel roads, collect boosters, run your best.",
    genre: "Arcade",
    image: "/gameweave/pixel-drifter.jpg",
    thumb: "/gameweave/thumb-pixel.jpg",
    tags: ["Arcade", "Racing", "Pixel"],
    date: "Apr 28, 2024",
    plays: "3.1K",
    playsLabel: "3.1K Plays",
    playsNumber: 3100,
    ai: true,
  },
  {
    title: "Skybound Chronicles",
    author: "StoryWeaver",
    authorInit: "S",
    summary: "A story-rich adventure across floating islands and ancient ruins.",
    genre: "RPG Adventure",
    image: "/gameweave/skybound-chronicles.jpg",
    thumb: "/gameweave/thumb-skybound.jpg",
    tags: ["RPG", "Adventure", "Fantasy"],
    date: "May 6, 2024",
    plays: "15.8K",
    playsLabel: "15.8K Plays",
    playsNumber: 15800,
    ai: true,
  },
  {
    title: "Circuit Breakers",
    author: "CodeStorm",
    authorInit: "C",
    summary: "Solve logic puzzles by restoring power and lighting the grid.",
    genre: "Puzzle",
    image: "/gameweave/circuit-breakers.jpg",
    thumb: "/gameweave/thumb-circuit.jpg",
    tags: ["Puzzle", "Logic", "Grid"],
    date: "May 4, 2024",
    plays: "9.3K",
    playsLabel: "9.3K Plays",
    playsNumber: 9300,
    ai: false,
  },
];

const flowSteps: Step[] = [
  { title: "Describe", detail: "Enter your game idea in plain language.", icon: MessageCircle, tint: "from-violet-500 to-purple-500" },
  { title: "Upload", detail: "Add images, videos, or other assets.", icon: UploadCloud, tint: "from-blue-500 to-sky-500" },
  { title: "Generate", detail: "AI agents build your worlds and mechanics.", icon: WandSparkles, tint: "from-emerald-500 to-teal-500" },
  { title: "Publish & Play", detail: "Launch to the community instantly and enjoy.", icon: PlaySquare, tint: "from-rose-500 to-orange-500" },
];

const featureStrip = [
  { title: "Built for Creators", detail: "Tunable AI agents that simplify game development.", icon: Database },
  { title: "Scalable Infrastructure", detail: "Fast asset delivery & serverless game hosting.", icon: Layers },
  { title: "Agent Task Logs", detail: "Transparent logs for every AI task and action.", icon: ListChecks },
  { title: "Playable Everywhere", detail: "Run games instantly in your browser. No installs.", icon: Server },
];

const footerColumns = [
  { title: "Product", links: ["Explore", "Create", "My Games"] },
  { title: "Resources", links: ["How It Works", "Blog", "Documentation"] },
  { title: "Company", links: ["About", "Careers", "Contact"] },
];

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

  const allGames = useMemo(() => {
    const live = allGamesQ.data?.items;
    return live ? live.map(toHomeGame) : fallbackGames;
  }, [allGamesQ.data?.items]);

  const visibleGames = useMemo(() => {
    const live = gamesQ.data?.items;
    const mapped = live ? live.map(toHomeGame) : fallbackGames;
    return mapped.filter((game) => {
      if (activeFilter === "AI Generated" && !game.ai) return false;
      if (activeFilter !== "All" && activeFilter !== "AI Generated" && !game.tags.includes(activeFilter)) return false;
      const q = query.trim().toLowerCase();
      if (!q) return true;
      return `${game.title} ${game.author} ${game.summary} ${game.tags.join(" ")}`.toLowerCase().includes(q);
    });
  }, [activeFilter, gamesQ.data?.items, query]);

  const rankedGames = useMemo(() => [...allGames].sort((a, b) => b.playsNumber - a.playsNumber), [allGames]);
  const featured = rankedGames[0] ?? fallbackGames[0];
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

        <ShowcaseCard featured={featured} trending={trending} onOpen={goDetail} onPlay={goPlay} />
      </section>

      {/* ─── Featured spotlight ───────────────────────────────── */}
      <section className={cn(SHELL, "pb-4")}>
        <FeaturedSpotlight game={featured} onPlay={goPlay} />
      </section>

      {/* ─── Explore ──────────────────────────────────────────── */}
      <section id="explore" className={cn(SHELL, "scroll-mt-20 pt-12 pb-6")}>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="font-display text-2xl font-bold tracking-tight text-slate-900">Explore Published Games</h2>
            {gamesQ.isError ? (
              <p className="mt-1 text-xs font-medium text-slate-400">Live games unavailable — showing local preview content.</p>
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
          {gamesQ.isLoading
            ? Array.from({ length: 6 }).map((_, i) => <GameCardSkeleton key={i} />)
            : visibleGames.length === 0
              ? (
                <div className="col-span-full rounded-2xl border border-dashed border-slate-200 bg-white/60 p-12 text-center text-sm text-slate-500">
                  No published games match this search.
                </div>
              )
              : visibleGames.map((game) => (
                  <GameCard key={game.id ?? game.title} game={game} onOpen={() => goDetail(game.id)} onPlay={() => goPlay(game.id)} />
                ))}
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

/* ─────────────────────────── Pieces ─────────────────────────── */

function Aurora() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div className="absolute -top-40 -left-32 size-[34rem] rounded-full bg-violet-400/25 blur-3xl" />
      <div className="absolute -top-24 right-0 size-[30rem] rounded-full bg-sky-300/25 blur-3xl" />
      <div className="absolute top-[28rem] left-1/3 size-[26rem] rounded-full bg-fuchsia-300/15 blur-3xl" />
    </div>
  );
}

function ShowcaseCard({
  featured,
  trending,
  onOpen,
  onPlay,
}: {
  featured: HomeGame;
  trending: HomeGame[];
  onOpen: (id?: string) => void;
  onPlay: (id?: string) => void;
}) {
  return (
    <Card className="gap-0 overflow-hidden rounded-3xl border-white/60 bg-white/60 p-2 shadow-2xl shadow-slate-900/10 backdrop-blur-xl [animation:pf-rise-in_0.6s_var(--pf-ease)_0.1s_both]">
      <button
        type="button"
        onClick={() => onOpen(featured.id)}
        className="group relative block aspect-[16/10] w-full overflow-hidden rounded-[1.25rem]"
      >
        <img
          src={heroImageForGame(featured)}
          alt={`${featured.title} game art`}
          className="size-full object-cover transition-transform duration-700 group-hover:scale-105"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/75 via-slate-950/10 to-transparent" />
        <div className="absolute top-3.5 left-3.5">
          <Badge className="gap-1.5 border-0 bg-white/90 text-violet-700 shadow-sm backdrop-blur">
            <CirclePlay className="size-3.5" />
            Featured
          </Badge>
        </div>
        <div className="absolute right-3.5 bottom-3.5 left-3.5 flex items-end justify-between gap-3 text-left">
          <div className="min-w-0">
            <h3 className="font-display text-xl font-bold text-white drop-shadow-sm">{featured.title}</h3>
            <p className="mt-0.5 text-xs font-medium text-white/80">{featured.playsLabel}</p>
          </div>
          <span
            onClick={(e) => { e.stopPropagation(); onPlay(featured.id); }}
            className="flex shrink-0 items-center gap-1.5 rounded-full bg-white px-4 py-2 text-xs font-bold text-slate-900 shadow-lg transition-transform hover:scale-105"
          >
            <Play className="size-3.5 fill-current" />
            Play
          </span>
        </div>
      </button>

      <div className="px-2.5 pt-3 pb-1.5">
        <div className="flex items-center justify-between px-1">
          <span className="text-xs font-bold tracking-wide text-slate-500 uppercase">Trending now</span>
          <button type="button" onClick={() => onOpen(undefined)} className="flex items-center gap-1 text-xs font-semibold text-violet-600 hover:text-violet-700">
            View all <ArrowRight className="size-3" />
          </button>
        </div>
        <div className="mt-2 grid gap-1">
          {trending.map((game) => (
            <button
              key={game.id ?? game.title}
              type="button"
              onClick={() => onOpen(game.id)}
              className="group flex items-center gap-3 rounded-xl p-1.5 text-left transition-colors hover:bg-violet-50/70"
            >
              <img src={game.thumb} alt="" className="size-11 shrink-0 rounded-lg object-cover" />
              <div className="min-w-0 flex-1">
                <strong className="block truncate text-[13px] font-bold text-slate-800">{game.title}</strong>
                <span className="text-[11px] text-slate-400">{game.playsLabel}</span>
              </div>
              <ArrowRight className="size-4 shrink-0 text-slate-300 transition-all group-hover:translate-x-0.5 group-hover:text-violet-500" />
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}

function FeaturedSpotlight({ game, onPlay }: { game: HomeGame; onPlay: (id?: string) => void }) {
  return (
    <Card className="grid grid-cols-1 items-center gap-6 overflow-hidden rounded-3xl border-slate-200/80 bg-white/80 p-5 backdrop-blur lg:grid-cols-[0.85fr_1.15fr] lg:p-6">
      <div className="group relative aspect-[16/10] overflow-hidden rounded-2xl">
        <img src={game.image} alt={`${game.title} scene`} className="size-full object-cover transition-transform duration-700 group-hover:scale-105" />
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2 font-display text-sm font-bold text-violet-600">
          <Sparkles className="size-4.5" />
          Featured Game
        </div>
        <h2 className="mt-2 font-display text-2xl font-bold tracking-tight text-slate-900 lg:text-3xl">{game.title}</h2>
        <div className="mt-2 flex items-center gap-2 text-xs font-semibold text-slate-500">
          <Avatar className="size-5">
            <AvatarFallback className="bg-gradient-to-br from-violet-600 to-blue-500 text-[10px] font-bold text-white">{game.authorInit}</AvatarFallback>
          </Avatar>
          By {game.author}
          <BadgeCheck className="size-4 text-blue-500" />
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {game.tags.slice(0, 5).map((tag) => (
            <Badge key={tag} variant="secondary" className="border-0 bg-violet-50 text-[11px] text-violet-700">{tag}</Badge>
          ))}
        </div>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-slate-600">{game.summary}</p>
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <span className="flex items-center gap-1.5 text-xs text-slate-500"><CirclePlay className="size-4" />{game.playsLabel}</span>
          <span className="flex items-center gap-1.5 text-xs text-slate-500"><Calendar className="size-4" />{game.date}</span>
          <Button
            onClick={() => onPlay(game.id)}
            className="ml-auto bg-gradient-to-r from-violet-600 to-blue-500 text-white shadow-lg shadow-violet-500/30 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-violet-500/40"
          >
            <Play className="size-4 fill-current" />
            Play Now
          </Button>
        </div>
      </div>
    </Card>
  );
}

function GameCard({ game, onOpen, onPlay }: { game: HomeGame; onOpen: () => void; onPlay: () => void }) {
  return (
    <Card
      onClick={onOpen}
      className="group cursor-pointer gap-0 overflow-hidden rounded-2xl border-slate-200/80 bg-white/90 p-0 pt-0 transition-all duration-300 hover:-translate-y-1.5 hover:border-violet-300 hover:shadow-xl hover:shadow-violet-500/10"
    >
      <div className="relative aspect-[16/9] overflow-hidden">
        <img src={game.image} alt={`${game.title} preview`} className="size-full object-cover transition-transform duration-500 group-hover:scale-105" />
        {game.ai ? (
          <Badge className="absolute top-2.5 right-2.5 gap-1 border-0 bg-white/90 text-[10px] text-violet-700 shadow-sm backdrop-blur">
            <Sparkles className="size-3" />
            AI
          </Badge>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col p-4">
        <h3 className="font-display text-lg leading-tight font-bold text-slate-900">{game.title}</h3>
        <div className="mt-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-500">
          <Avatar className="size-4.5">
            <AvatarFallback className="bg-gradient-to-br from-violet-600 to-blue-500 text-[9px] font-bold text-white">{game.authorInit}</AvatarFallback>
          </Avatar>
          {game.author}
        </div>
        <p className="mt-2.5 line-clamp-2 min-h-[2.5rem] text-[13px] leading-relaxed text-slate-500">{game.summary}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {game.tags.slice(0, 3).map((tag) => (
            <Badge key={tag} variant="secondary" className="border-0 bg-slate-100 text-[10px] font-semibold text-slate-600">{tag}</Badge>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3 border-t border-slate-100 pt-3 text-[11px] text-slate-500">
          <span className="flex items-center gap-1"><Calendar className="size-3.5" />{game.date}</span>
          <span className="flex items-center gap-1"><CirclePlay className="size-3.5" />{game.plays}</span>
          <Button
            size="sm"
            onClick={(event) => { event.stopPropagation(); onPlay(); }}
            className="ml-auto h-8 gap-1.5 bg-gradient-to-r from-violet-600 to-blue-500 text-white shadow-sm transition-transform hover:scale-105"
          >
            <Play className="size-3.5 fill-current" />
            Play
          </Button>
        </div>
      </div>
    </Card>
  );
}

function GameCardSkeleton() {
  return (
    <Card className="gap-0 overflow-hidden rounded-2xl border-slate-200/80 bg-white/80 p-0">
      <Skeleton className="aspect-[16/9] w-full rounded-none" />
      <div className="flex flex-col gap-3 p-4">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-3 w-1/3" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
        <div className="mt-2 flex gap-2">
          <Skeleton className="h-5 w-12 rounded-full" />
          <Skeleton className="h-5 w-12 rounded-full" />
        </div>
      </div>
    </Card>
  );
}

/* ─────────────────────────── Helpers ────────────────────────── */

function toHomeGame(game: ApiGame): HomeGame {
  const art = artForGame(game);
  return {
    id: game.id,
    title: game.title,
    author: game.author,
    authorInit: game.author_init || "?",
    summary: game.summary,
    genre: game.genre,
    image: art.image,
    thumb: art.thumb,
    heroImage: art.hero,
    tags: game.tags,
    date: game.date,
    plays: game.plays_str,
    playsLabel: `${game.plays_str} Plays`,
    playsNumber: game.plays,
    ai: game.from_create,
  };
}

function artForGame(game: ApiGame): BoundArt {
  const cover = imageSource(game.cover);
  if (cover) return { image: cover, thumb: cover, hero: cover };

  const titleKey = normalizeArtKey(game.title);
  const titleArt = titleArtMap[titleKey];
  if (titleArt) return titleArt;

  const searchable = normalizeArtKey(`${game.title} ${game.genre} ${game.summary} ${game.tags.join(" ")}`);
  const keywordArt = keywordArtMap.find((entry) => entry.keywords.some((keyword) => searchable.includes(normalizeArtKey(keyword))));
  if (keywordArt) return keywordArt.art;

  const stableSeed = `${game.id || game.title}|${game.genre}|${game.tags.join("|")}`;
  return boundArtPool[stableHash(stableSeed) % boundArtPool.length];
}

function imageSource(cover: string) {
  if (!cover || cover.includes("gradient(")) return null;
  if (cover.startsWith("http://") || cover.startsWith("https://") || cover.startsWith("/")) return cover;
  return null;
}

function heroImageForGame(game: HomeGame) {
  return game.heroImage || game.image;
}

function normalizeArtKey(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function stableHash(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
