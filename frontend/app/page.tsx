"use client";

import type { CSSProperties } from "react";
import { useMemo, useState } from "react";
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

type Game = {
  title: string;
  author: string;
  summary: string;
  image: string;
  thumb?: string;
  tags: string[];
  date: string;
  plays: string;
  ai?: boolean;
};

type Step = {
  title: string;
  detail: string;
  icon: LucideIcon;
  color: string;
};

const featured = {
  title: "Neon Alley Cat",
  author: "PixelPioneer",
  summary:
    "A fast-paced arcade game where a street-smart cat dodges drones, hacks terminals, and outruns the city enforcers in a neon-soaked future.",
  image: "/playforge/neon-featured.jpg",
  heroImage: "/playforge/neon-trending.jpg",
  tags: ["Action", "Arcade", "Cyberpunk", "Cat", "AI Generated"],
  date: "May 8, 2024",
  plays: "12.4K Plays",
};

const games: Game[] = [
  {
    title: "Pixel Drifter",
    author: "RetroKnight",
    summary: "Drift through endless pixel roads, collect boosters, run your best.",
    image: "/playforge/pixel-drifter.jpg",
    thumb: "/playforge/thumb-pixel.jpg",
    tags: ["Arcade", "Racing", "Pixel"],
    date: "Apr 28, 2024",
    plays: "3.1K",
    ai: true,
  },
  {
    title: "Skybound Chronicles",
    author: "StoryWeaver",
    summary: "A story-rich adventure across floating islands and ancient ruins.",
    image: "/playforge/skybound-chronicles.jpg",
    thumb: "/playforge/thumb-skybound.jpg",
    tags: ["RPG", "Adventure", "Fantasy"],
    date: "May 6, 2024",
    plays: "15.8K",
    ai: true,
  },
  {
    title: "Dungeon & Dice",
    author: "LootLab",
    summary: "Dice roll, fate calls. A roguelike dungeon crawler of chance.",
    image: "/playforge/dungeon-dice.jpg",
    tags: ["Roguelike", "Dice", "Co-op"],
    date: "Apr 24, 2024",
    plays: "6.1K",
  },
  {
    title: "Circuit Breakers",
    author: "CodeStorm",
    summary: "Solve logic puzzles by restoring power and lighting the grid.",
    image: "/playforge/circuit-breakers.jpg",
    thumb: "/playforge/thumb-circuit.jpg",
    tags: ["Puzzle", "Logic", "Grid"],
    date: "May 4, 2024",
    plays: "9.3K",
  },
  {
    title: "Echoes of the Deep",
    author: "BlueMarsh",
    summary: "Explore the abyss, uncover secrets, and survive the unknown.",
    image: "/playforge/echoes-deep.jpg",
    thumb: "/playforge/thumb-echoes.jpg",
    tags: ["Adventure", "Exploration", "Mystery"],
    date: "Apr 30, 2024",
    plays: "11.6K",
  },
  {
    title: "Mystic Grove",
    author: "GreenThumb",
    summary: "A cozy exploration game about restoring a magical forest.",
    image: "/playforge/mystic-grove.jpg",
    thumb: "/playforge/thumb-mystic.jpg",
    tags: ["Relaxing", "Adventure", "Nature"],
    date: "May 2, 2024",
    plays: "7.4K",
  },
];

const trending: Game[] = [
  games[1],
  games[0],
  games[5],
  games[3],
  games[4],
  {
    title: "Lumen Path",
    author: "EmberWorks",
    summary: "Follow the lanterns through an ancient underground shrine.",
    image: "/playforge/lumen-path.jpg",
    thumb: "/playforge/thumb-lumen.jpg",
    tags: ["Adventure"],
    date: "May 1, 2024",
    plays: "5.2K",
  },
];

const filterTabs = ["All", "AI Generated", "Arcade", "Puzzle", "RPG", "Adventure"];

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

  const filteredGames = useMemo(() => {
    const q = query.trim().toLowerCase();
    return games.filter((game) => {
      const matchesFilter =
        activeFilter === "All" ||
        (activeFilter === "AI Generated" && game.ai) ||
        game.tags.includes(activeFilter);
      const searchable = `${game.title} ${game.author} ${game.summary} ${game.tags.join(" ")}`.toLowerCase();
      return matchesFilter && (!q || searchable.includes(q));
    });
  }, [activeFilter, query]);

  const goCreate = () => router.push("/create");
  const goPlay = () => scrollToId("explore");

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
            <button className="pf-trending-feature" onClick={goPlay} type="button">
              <img src={featured.heroImage} alt={`${featured.title} game art`} />
              <span>
                <CirclePlay size={13} />
                Featured
              </span>
            </button>
            <div className="pf-trending-list">
              {trending.map((game) => (
                <button className="pf-trending-row" key={game.title} onClick={goPlay} type="button">
                  <img src={game.thumb ?? game.image} alt={`${game.title} thumbnail`} />
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
                <span className="pf-author-dot">P</span>
                By {featured.author}
                <BadgeCheck size={15} />
              </div>
              <div className="pf-tags">
                {featured.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
              <p>{featured.summary}</p>
              <div className="pf-featured-meta">
                <span>
                  <CirclePlay size={14} />
                  {featured.plays}
                </span>
                <span>
                  <Calendar size={14} />
                  {featured.date}
                </span>
                <button className="pf-primary-btn pf-play-now" onClick={goPlay} type="button">
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
          <h2 id="explore-heading">Explore Published Games</h2>
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
        </div>

        <div className="pf-game-grid">
          {filteredGames.map((game) => (
            <GameCard game={game} key={game.title} onPlay={goPlay} />
          ))}
        </div>
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
                <button key={link} type="button">
                  {link}
                </button>
              ))}
            </div>
          ))}
          <div className="pf-footer-links">
            <button type="button">Privacy Policy</button>
            <button type="button">Terms of Service</button>
            <button type="button">Docs</button>
          </div>
          <p className="pf-copyright">© 2024 PlayForge AI. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

function GameCard({ game, onPlay }: { game: Game; onPlay: () => void }) {
  return (
    <article className="pf-game-card">
      <img src={game.image} alt={`${game.title} game preview`} />
      <div className="pf-game-body">
        <h3>{game.title}</h3>
        <span className="pf-game-author">By {game.author}</span>
        <p>{game.summary}</p>
        <div className="pf-game-tags">
          {game.tags.map((tag) => (
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
          <button onClick={onPlay} type="button">
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

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
