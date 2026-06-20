"use client";

import type { CSSProperties } from "react";
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
  color: string;
};

type BoundArt = { image: string; thumb: string; hero: string };

const ART = {
  neon: {
    image: "/playforge/neon-featured.jpg",
    thumb: "/playforge/neon-trending.jpg",
    hero: "/playforge/neon-trending.jpg",
  },
  pixel: {
    image: "/playforge/pixel-drifter.jpg",
    thumb: "/playforge/thumb-pixel.jpg",
    hero: "/playforge/pixel-drifter.jpg",
  },
  sky: {
    image: "/playforge/skybound-chronicles.jpg",
    thumb: "/playforge/thumb-skybound.jpg",
    hero: "/playforge/skybound-chronicles.jpg",
  },
  dungeon: {
    image: "/playforge/dungeon-dice.jpg",
    thumb: "/playforge/dungeon-dice.jpg",
    hero: "/playforge/dungeon-dice.jpg",
  },
  circuit: {
    image: "/playforge/circuit-breakers.jpg",
    thumb: "/playforge/thumb-circuit.jpg",
    hero: "/playforge/circuit-breakers.jpg",
  },
  echoes: {
    image: "/playforge/echoes-deep.jpg",
    thumb: "/playforge/thumb-echoes.jpg",
    hero: "/playforge/echoes-deep.jpg",
  },
  mystic: {
    image: "/playforge/mystic-grove.jpg",
    thumb: "/playforge/thumb-mystic.jpg",
    hero: "/playforge/mystic-grove.jpg",
  },
  moonlit: {
    image: "/playforge/covers/moonlit-koi.jpg",
    thumb: "/playforge/covers/moonlit-koi.jpg",
    hero: "/playforge/covers/moonlit-koi.jpg",
  },
  rune: {
    image: "/playforge/covers/rune-circuit.jpg",
    thumb: "/playforge/covers/rune-circuit.jpg",
    hero: "/playforge/covers/rune-circuit.jpg",
  },
  cloud: {
    image: "/playforge/covers/cloud-courier.jpg",
    thumb: "/playforge/covers/cloud-courier.jpg",
    hero: "/playforge/covers/cloud-courier.jpg",
  },
  orbit: {
    image: "/playforge/covers/orbit-bloom.jpg",
    thumb: "/playforge/covers/orbit-bloom.jpg",
    hero: "/playforge/covers/orbit-bloom.jpg",
  },
  star: {
    image: "/playforge/covers/star-catcher.jpg",
    thumb: "/playforge/covers/star-catcher.jpg",
    hero: "/playforge/covers/star-catcher.jpg",
  },
  color: {
    image: "/playforge/covers/color-echo.jpg",
    thumb: "/playforge/covers/color-echo.jpg",
    hero: "/playforge/covers/color-echo.jpg",
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
    image: "/playforge/neon-featured.jpg",
    thumb: "/playforge/neon-trending.jpg",
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
    image: "/playforge/pixel-drifter.jpg",
    thumb: "/playforge/thumb-pixel.jpg",
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
    image: "/playforge/skybound-chronicles.jpg",
    thumb: "/playforge/thumb-skybound.jpg",
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
    image: "/playforge/circuit-breakers.jpg",
    thumb: "/playforge/thumb-circuit.jpg",
    tags: ["Puzzle", "Logic", "Grid"],
    date: "May 4, 2024",
    plays: "9.3K",
    playsLabel: "9.3K Plays",
    playsNumber: 9300,
    ai: false,
  },
];

const flowSteps: Step[] = [
  {
    title: "Describe",
    detail: "Enter your game idea in plain language.",
    icon: MessageCircle,
    color: "#7c5cff",
  },
  {
    title: "Upload",
    detail: "Add images, videos, or other assets.",
    icon: UploadCloud,
    color: "#4f7dff",
  },
  {
    title: "Generate",
    detail: "AI agents build your game worlds and mechanics.",
    icon: WandSparkles,
    color: "#18b98e",
  },
  {
    title: "Publish & Play",
    detail: "Launch to the community instantly and enjoy!",
    icon: PlaySquare,
    color: "#f26b5d",
  },
];

const featureStrip = [
  {
    title: "Built for Creators",
    detail: "Remote tunable AI agents that simplify game development.",
    icon: Database,
  },
  {
    title: "Scalable Infrastructure",
    detail: "Fast, reliable asset delivery & serverless game hosting.",
    icon: Layers,
  },
  {
    title: "Agent Task Logs",
    detail: "Transparent logs for every AI task and action taken.",
    icon: ListChecks,
  },
  {
    title: "Playable Everywhere",
    detail: "Run games instantly in your browser. No installs.",
    icon: Server,
    alert: true,
  },
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

  const rankedGames = useMemo(
    () => [...allGames].sort((a, b) => b.playsNumber - a.playsNumber),
    [allGames],
  );
  const featured = rankedGames[0] ?? fallbackGames[0];
  const trending = rankedGames.slice(0, 6);
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
      Explore: "/", Create: "/create", "My Games": "/me", "How It Works": "/#how",
      About: "/about", Contact: "/about", Blog: "/about", Careers: "/about", Documentation: "/about",
    };
    router.push(map[label] || "/");
  };

  return (
    <div className="pf-page">
      <section className="pf-hero pf-shell">
        <div className="pf-hero-copy">
          <Decorations />
          <h1>
            Turn any idea
            <br />
            into a playable
            <br />
            <span>AI game</span>
          </h1>
          <p>
            Describe a game concept, upload assets, and let AI agents generate,
            package, and publish a playable experience.
          </p>
          <div className="pf-hero-actions">
            <button className="pf-primary-btn" onClick={goCreate} type="button">
              <Sparkles size={16} />
              Create with AI
            </button>
            <button className="pf-secondary-btn" onClick={() => scrollToId("explore")} type="button">
              <Gamepad2 size={18} />
              Explore Games
            </button>
          </div>
          <div className="pf-mini-flow" aria-label="Creation flow">
            {flowSteps.map((step, index) => (
              <div className="pf-mini-flow-item" key={step.title}>
                <div className="pf-mini-icon">
                  <step.icon size={24} />
                </div>
                <span>{index === flowSteps.length - 1 ? "Play" : step.title}</span>
                {index < flowSteps.length - 1 ? <ArrowRight className="pf-mini-arrow" size={15} /> : null}
              </div>
            ))}
          </div>
        </div>

        <aside className="pf-trending-card" aria-label="Trending games">
          <div className="pf-card-heading">
            <h2>Trending on PlayForge</h2>
            <button onClick={() => scrollToId("explore")} type="button">
              View all
              <ArrowRight size={13} />
            </button>
          </div>
          <div className="pf-trending-grid">
            <button className="pf-trending-feature" onClick={() => goDetail(featured.id)} type="button">
              <img src={heroImageForGame(featured)} alt={`${featured.title} game art`} />
              <span>
                <CirclePlay size={13} />
                Featured
              </span>
            </button>
            <div className="pf-trending-list">
              {trending.map((game) => (
                <button className="pf-trending-row" key={game.id ?? game.title} onClick={() => goDetail(game.id)} type="button">
                  <img src={game.thumb} alt={`${game.title} thumbnail`} />
                  <strong>{game.title}</strong>
                </button>
              ))}
            </div>
          </div>
        </aside>
      </section>

      <section className="pf-featured pf-shell" aria-labelledby="featured-game">
        <div className="pf-featured-card">
          <div className="pf-section-kicker" id="featured-game">
            <Sparkles size={19} />
            Featured Game
          </div>
          <div className="pf-featured-grid">
            <img className="pf-featured-image" src={featured.image} alt={`${featured.title} gameplay scene`} />
            <div className="pf-featured-copy">
              <h2>{featured.title}</h2>
              <div className="pf-author">
                <span className="pf-author-dot">{featured.authorInit}</span>
                By {featured.author}
                <BadgeCheck size={15} />
              </div>
              <div className="pf-tags">
                {featured.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
                {featured.ai && !featured.tags.includes("AI Generated") ? <span>AI Generated</span> : null}
              </div>
              <p>{featured.summary}</p>
              <div className="pf-featured-meta">
                <span>
                  <CirclePlay size={14} />
                  {featured.playsLabel}
                </span>
                <span>
                  <Calendar size={14} />
                  {featured.date}
                </span>
                <button className="pf-primary-btn pf-play-now" onClick={() => goPlay(featured.id)} type="button">
                  <Play size={16} fill="currentColor" />
                  Play Now
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="pf-explore pf-shell" id="explore" aria-labelledby="explore-heading">
        <div className="pf-explore-toolbar">
          <div>
            <h2 id="explore-heading">Explore Published Games</h2>
            {gamesQ.isError ? <p className="pf-live-note">Live games unavailable. Showing local preview content.</p> : null}
          </div>
          <label className="pf-search">
            <Search size={17} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search games..."
              aria-label="Search games"
            />
          </label>
          <div className="pf-filter-tabs" aria-label="Filter games">
            {filterTabs.map((tab) => (
              <button
                className={activeFilter === tab ? "is-active" : ""}
                key={tab}
                onClick={() => setActiveFilter(tab)}
                type="button"
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="pf-sort-tabs" aria-label="Sort games">
            {(["newest", "popular"] as const).map((s) => (
              <button
                className={sort === s ? "is-active" : ""}
                key={s}
                onClick={() => setSort(s)}
                type="button"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {gamesQ.isLoading ? (
          <div className="pf-grid-state">Loading live games...</div>
        ) : visibleGames.length === 0 ? (
          <div className="pf-grid-state">No published games match this search.</div>
        ) : (
          <>
            <div className="pf-game-grid">
              {visibleGames.map((game) => (
                <GameCard game={game} key={game.id ?? game.title} onOpen={() => goDetail(game.id)} onPlay={() => goPlay(game.id)} />
              ))}
            </div>
            {gamesQ.data?.has_more ? (
              <div className="pf-load-more">
                <button className="pf-secondary-btn" onClick={() => setLimit((value) => value + 12)} type="button">
                  Load more games
                </button>
              </div>
            ) : null}
          </>
        )}
      </section>

      <section className="pf-process pf-shell" id="how" aria-labelledby="process-heading">
        <h2 id="process-heading">From Idea to Play</h2>
        <div className="pf-process-row">
          {flowSteps.map((step, index) => (
            <div className="pf-process-item" key={step.title}>
              <div className="pf-process-card" style={{ "--accent": step.color } as CSSProperties}>
                <span className="pf-step-number">{index + 1}</span>
                <step.icon size={36} />
                <div>
                  <strong>{step.title}</strong>
                  <p>{step.detail}</p>
                </div>
              </div>
              {index < flowSteps.length - 1 ? <ArrowRight className="pf-process-arrow" size={18} /> : null}
            </div>
          ))}
        </div>
      </section>

      <section className="pf-platform pf-shell" aria-label="Platform features">
        {featureStrip.map((item) => (
          <div className="pf-platform-item" key={item.title}>
            <span className={item.alert ? "pf-platform-icon is-alert" : "pf-platform-icon"}>
              <item.icon size={24} />
            </span>
            <div>
              <strong>{item.title}</strong>
              <p>{item.detail}</p>
            </div>
          </div>
        ))}
      </section>

      <footer className="pf-footer">
        <div className="pf-footer-inner pf-shell">
          <div className="pf-footer-brand">
            <div className="pf-footer-logo">
              <span className="pf-logo-mark">
                <Globe2 size={18} />
              </span>
              <strong>PlayForge AI</strong>
            </div>
            <p>The AI-native platform for creating, sharing, and playing web games.</p>
            <div className="pf-socials" aria-label="Social links">
              <button type="button" aria-label="Community">
                <MessageCircle size={18} />
              </button>
              <button type="button" aria-label="Players">
                <Gamepad2 size={18} />
              </button>
              <button type="button" aria-label="Videos">
                <PlaySquare size={18} />
              </button>
              <button type="button" aria-label="Developers">
                <Database size={18} />
              </button>
            </div>
          </div>
          {footerColumns.map((column) => (
            <div className="pf-footer-col" key={column.title}>
              <strong>{column.title}</strong>
              {column.links.map((link) => (
                <button key={link} onClick={() => goFooter(link)} type="button">
                  {link}
                </button>
              ))}
            </div>
          ))}
          <div className="pf-footer-links">
            <button onClick={() => router.push("/privacy")} type="button">Privacy Policy</button>
            <button onClick={() => router.push("/terms")} type="button">Terms of Service</button>
            <button onClick={() => router.push("/about")} type="button">Docs</button>
          </div>
          <p className="pf-copyright">&copy; 2024 PlayForge AI. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

function GameCard({
  game,
  onOpen,
  onPlay,
}: {
  game: HomeGame;
  onOpen: () => void;
  onPlay: () => void;
}) {
  return (
    <article className="pf-game-card" onClick={onOpen}>
      <img src={game.image} alt={`${game.title} game preview`} />
      <div className="pf-game-body">
        <h3>{game.title}</h3>
        <span className="pf-game-author">By {game.author}</span>
        <p>{game.summary}</p>
        <div className="pf-game-tags">
          {game.tags.slice(0, 3).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <div className="pf-game-meta">
          <span>
            <Calendar size={13} />
            {game.date}
          </span>
          <span>
            <CirclePlay size={13} />
            {game.plays}
          </span>
          <button
            onClick={(event) => {
              event.stopPropagation();
              onPlay();
            }}
            type="button"
          >
            <Play size={14} fill="currentColor" />
            Play
          </button>
        </div>
      </div>
    </article>
  );
}

function Decorations() {
  return (
    <div aria-hidden className="pf-hero-decor">
      <span className="pf-decor-dot pf-decor-dot-a" />
      <span className="pf-decor-dot pf-decor-dot-b" />
      <span className="pf-decor-ring" />
      <Sparkles className="pf-decor-spark pf-decor-spark-a" size={19} />
      <Sparkles className="pf-decor-spark pf-decor-spark-b" size={14} />
      <span className="pf-decor-plus">+</span>
    </div>
  );
}

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
