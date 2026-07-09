import { ArrowRight, BadgeCheck, Calendar, CirclePlay, Play, Sparkles } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { heroImageForGame, type HomeGame } from "../_lib/explore-data";

export function Aurora() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div className="absolute -top-40 -left-32 size-[34rem] rounded-full bg-violet-400/25 blur-3xl" />
      <div className="absolute -top-24 right-0 size-[30rem] rounded-full bg-sky-300/25 blur-3xl" />
      <div className="absolute top-[28rem] left-1/3 size-[26rem] rounded-full bg-fuchsia-300/15 blur-3xl" />
    </div>
  );
}

export function ShowcaseCard({
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
      <div className="group relative aspect-[16/10] w-full overflow-hidden rounded-[1.25rem]">
        <img
          src={heroImageForGame(featured)}
          alt={`${featured.title} game art`}
          className="size-full object-cover transition-transform duration-700 group-hover:scale-105"
        />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-slate-950/75 via-slate-950/10 to-transparent" />
        <button
          type="button"
          onClick={() => onOpen(featured.id)}
          className="absolute inset-0 z-10 cursor-pointer rounded-[1.25rem]"
          aria-label={`Open ${featured.title}`}
        />
        <div className="pointer-events-none absolute top-3.5 left-3.5 z-20">
          <Badge className="gap-1.5 border-0 bg-white/90 text-violet-700 shadow-sm backdrop-blur">
            <CirclePlay className="size-3.5" />
            Featured
          </Badge>
        </div>
        <div className="absolute right-3.5 bottom-3.5 left-3.5 z-20 flex items-end justify-between gap-3 text-left">
          <div className="pointer-events-none min-w-0">
            <h3 className="font-display text-xl font-bold text-white drop-shadow-sm">{featured.title}</h3>
            <p className="mt-0.5 text-xs font-medium text-white/80">{featured.playsLabel}</p>
          </div>
          <button
            type="button"
            onClick={() => onPlay(featured.id)}
            className="flex shrink-0 items-center gap-1.5 rounded-full bg-white px-4 py-2 text-xs font-bold text-slate-900 shadow-lg transition-transform hover:scale-105"
          >
            <Play className="size-3.5 fill-current" />
            Play
          </button>
        </div>
      </div>

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

export function FeaturedSpotlight({ game, onPlay }: { game: HomeGame; onPlay: (id?: string) => void }) {
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

export function GameCard({ game, onOpen, onPlay }: { game: HomeGame; onOpen: () => void; onPlay: () => void }) {
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

export function GameCardSkeleton() {
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
