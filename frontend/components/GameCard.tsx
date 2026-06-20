"use client";

import { Play, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import type { CSSProperties } from "react";

import type { Game } from "@/lib/types";

export default function GameCard({ game }: { game: Game }) {
  const router = useRouter();
  const isPublished = game.status === "published";
  const coverStyle = coverBackground(game.cover);

  return (
    <article className="pf-library-card">
      <button
        className="pf-library-cover"
        onClick={() => router.push(`/games/${game.id}`)}
        style={coverStyle}
        type="button"
      >
        <span className="pf-library-genre">{game.genre}</span>
        {game.from_create ? (
          <span className="pf-library-ai">
            <Sparkles size={12} />
            AI made
          </span>
        ) : null}
        {!isPublished ? <span className="pf-library-state">{game.status === "preview" ? "Preview" : "Draft"}</span> : null}
      </button>

      <div className="pf-library-body">
        <div className="pf-library-title-row">
          <h3>{game.title}</h3>
          <button
            aria-label={`Play ${game.title}`}
            className="pf-library-play"
            onClick={(event) => {
              event.stopPropagation();
              router.push(`/play/${game.id}`);
            }}
            type="button"
          >
            <Play size={15} fill="currentColor" />
          </button>
        </div>
        <p>{game.summary}</p>
        <div className="pf-library-tags">
          {(game.tags.length ? game.tags : [game.genre]).slice(0, 4).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <div className="pf-library-meta">
          <span className="pf-library-author">
            <i>{game.author_init}</i>
            {game.author}
          </span>
          <span>{game.plays_str} plays</span>
        </div>
      </div>
    </article>
  );
}

function coverBackground(cover: string): CSSProperties {
  if (cover.startsWith("/") || cover.startsWith("http://") || cover.startsWith("https://")) {
    return { backgroundImage: `url("${cover}")` };
  }
  return { background: cover };
}
