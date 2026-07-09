"use client";

import { Play, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { coverBackgroundStyle } from "@/lib/cover";
import type { Game } from "@/lib/types";

export default function GameCard({ game }: { game: Game }) {
  const router = useRouter();
  const isPublished = game.status === "published";
  const coverStyle = coverBackgroundStyle(game.cover);
  const tags = (game.tags.length ? game.tags : [game.genre]).slice(0, 4);

  return (
    <Card className="group gap-0 overflow-hidden rounded-lg border-slate-200/80 bg-white/90 p-0 pt-0 shadow-sm transition-all hover:-translate-y-1 hover:border-indigo-200 hover:shadow-xl hover:shadow-indigo-500/10">
      <button
        className="relative aspect-[16/10] w-full overflow-hidden bg-slate-900 text-left"
        onClick={() => router.push(`/games/${game.id}`)}
        style={coverStyle}
        type="button"
      >
        <span className="absolute inset-0 bg-gradient-to-t from-slate-950/75 via-slate-950/10 to-transparent" />
        <Badge className="absolute left-3 top-3 border-white/20 bg-white/90 text-slate-900" variant="outline">
          {game.genre}
        </Badge>
        {game.from_create ? (
          <Badge className="absolute right-3 top-3 gap-1 border-indigo-200 bg-indigo-50 text-indigo-700" variant="outline">
            <Sparkles size={12} />
            AI made
          </Badge>
        ) : null}
        {!isPublished ? (
          <Badge className="absolute bottom-3 left-3 border-amber-200 bg-amber-50 text-amber-700" variant="outline">
            {game.status === "preview" ? "Preview" : "Draft"}
          </Badge>
        ) : null}
      </button>

      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex items-start gap-3">
          <button
            className="min-w-0 flex-1 text-left"
            onClick={() => router.push(`/games/${game.id}`)}
            type="button"
          >
            <h3 className="line-clamp-1 font-display text-lg font-semibold tracking-normal text-slate-950">{game.title}</h3>
          </button>
          <Button
            aria-label={`Play ${game.title}`}
            className="size-9 shrink-0 rounded-lg"
            onClick={(event) => {
              event.stopPropagation();
              router.push(`/play/${game.id}`);
            }}
            size="icon"
            type="button"
          >
            <Play size={15} fill="currentColor" />
          </Button>
        </div>

        <p className="line-clamp-2 text-sm leading-6 text-slate-600">{game.summary}</p>

        <div className="flex flex-wrap gap-2">
          {tags.map((tag) => (
            <Badge className="border-slate-200 bg-slate-50 text-slate-600" key={tag} variant="outline">
              {tag}
            </Badge>
          ))}
        </div>

        <div className="mt-auto flex items-center justify-between gap-3 text-sm text-slate-500">
          <span className="flex min-w-0 items-center gap-2">
            <i className="flex size-6 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs not-italic text-white">
              {game.author_init}
            </i>
            <span className="truncate">{game.author}</span>
          </span>
          <span className="shrink-0">{game.plays_str} plays</span>
        </div>
      </CardContent>
    </Card>
  );
}
