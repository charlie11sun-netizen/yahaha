import type { LucideIcon } from "lucide-react";
import {
  Database,
  Layers,
  ListChecks,
  MessageCircle,
  PlaySquare,
  Server,
  UploadCloud,
  WandSparkles,
} from "lucide-react";

import type { Game as ApiGame } from "@/lib/types";

export const SHELL = "mx-auto w-full max-w-[1240px] px-5 sm:px-8 lg:px-10";

export type HomeGame = {
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

export type Step = {
  title: string;
  detail: string;
  icon: LucideIcon;
  tint: string;
};

export type BoundArt = { image: string; thumb: string; hero: string };

export const ART = {
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

export const boundArtPool = [
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

export const titleArtMap: Record<string, BoundArt> = {
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

export const keywordArtMap: Array<{ keywords: string[]; art: BoundArt }> = [
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

export const flowSteps: Step[] = [
  { title: "Describe", detail: "Enter your game idea in plain language.", icon: MessageCircle, tint: "from-violet-500 to-purple-500" },
  { title: "Upload", detail: "Add images, videos, or other assets.", icon: UploadCloud, tint: "from-blue-500 to-sky-500" },
  { title: "Generate", detail: "AI agents build your worlds and mechanics.", icon: WandSparkles, tint: "from-emerald-500 to-teal-500" },
  { title: "Publish & Play", detail: "Launch to the community instantly and enjoy.", icon: PlaySquare, tint: "from-rose-500 to-orange-500" },
];

export const featureStrip = [
  { title: "Built for Creators", detail: "Tunable AI agents that simplify game development.", icon: Database },
  { title: "Scalable Infrastructure", detail: "Fast asset delivery & serverless game hosting.", icon: Layers },
  { title: "Agent Task Logs", detail: "Transparent logs for every AI task and action.", icon: ListChecks },
  { title: "Playable Everywhere", detail: "Run games instantly in your browser. No installs.", icon: Server },
];

export const footerColumns = [
  { title: "Product", links: ["Explore", "Create", "My Games"] },
  { title: "Resources", links: ["How It Works", "Blog", "Documentation"] },
  { title: "Company", links: ["About", "Careers", "Contact"] },
];

export function toHomeGame(game: ApiGame): HomeGame {
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

export function artForGame(game: ApiGame): BoundArt {
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

export function imageSource(cover?: string | null) {
  if (!cover || cover.includes("gradient(")) return null;
  if (cover.startsWith("http://") || cover.startsWith("https://") || cover.startsWith("/")) return cover;
  return null;
}

export function heroImageForGame(game: HomeGame) {
  return game.heroImage || game.image;
}

export function normalizeArtKey(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

export function stableHash(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
