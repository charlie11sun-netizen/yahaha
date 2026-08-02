import { ArrowLeft, Calendar, Database, GitFork, Play } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { GameActions } from "@/app/games/[id]/_components/GameActions";
import { GameComments } from "@/app/games/[id]/_components/GameComments";
import { DetailStat, RelatedGames } from "@/app/games/[id]/_components/GameDetailPanels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { coverBackgroundStyle } from "@/lib/cover";
import {
  getPublicGame,
  getPublicGameComments,
  getPublicGameManifest,
  getPublicRelatedGames,
  ServerApiError,
} from "@/lib/server-api";

export default async function GameDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let game;
  try {
    game = await getPublicGame(id);
  } catch (error) {
    if (error instanceof ServerApiError && error.status === 404) notFound();
    throw error;
  }

  const [commentsResult, relatedResult, manifestResult] = await Promise.allSettled([
    getPublicGameComments(id),
    getPublicRelatedGames(id),
    getPublicGameManifest(id),
  ]);
  const comments = commentsResult.status === "fulfilled" ? commentsResult.value.items : [];
  const related = relatedResult.status === "fulfilled" ? relatedResult.value.items : [];
  const manifest = manifestResult.status === "fulfilled" ? manifestResult.value : null;
  const manifestFiles = manifest?.files ?? [];

  return (
    <main className="px-5 py-8 sm:px-8 lg:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <Button asChild className="w-fit gap-2 rounded-lg" variant="ghost">
          <Link href="/explore"><ArrowLeft size={16} />Back to arcade</Link>
        </Button>

        <Card className="overflow-hidden rounded-lg border-slate-200/80 bg-white/90 py-0 shadow-xl shadow-slate-900/5">
          <CardContent className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[420px_minmax(0,1fr)]">
            <div className="space-y-4">
              <div className="relative aspect-[4/3] overflow-hidden rounded-lg bg-slate-900 bg-cover bg-center" style={coverBackgroundStyle(game.cover)}>
                <span className="absolute inset-0 bg-gradient-to-t from-slate-950/65 via-slate-950/5 to-transparent" />
                <Badge className="absolute left-4 top-4 border-white/20 bg-white/90 text-slate-900" variant="outline">{game.genre}</Badge>
              </div>
              <Button asChild className="h-11 w-full rounded-lg">
                <Link href={`/play/${game.id}`}><Play size={18} fill="currentColor" />Play now</Link>
              </Button>
            </div>

            <div className="min-w-0 space-y-6">
              <div className="space-y-4">
                <h1 className="font-display text-4xl font-semibold tracking-normal text-slate-950 sm:text-5xl">{game.title}</h1>
                <Link className="flex w-fit items-center gap-2 text-sm text-slate-600 hover:text-indigo-700" href={`/users/${game.author_id}`}>
                  <i className="flex size-7 items-center justify-center rounded-full bg-indigo-600 text-xs not-italic text-white">{game.author_init}</i>
                  <span>{game.author}</span><Calendar size={14} /><span>{game.date}</span>
                </Link>
              </div>

              <GameActions
                gameId={game.id}
                initialFavorited={!!game.favorited}
                initialLiked={!!game.liked}
                initialLikes={game.likes}
                title={game.title}
              />

              <p className="text-base leading-7 text-slate-600">{game.summary}</p>
              <div className="flex flex-wrap gap-2">
                {(game.tags.length ? game.tags : [game.genre]).map((tag) => (
                  <Badge className="border-slate-200 bg-slate-50 text-slate-600" key={tag} variant="outline">#{tag}</Badge>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <DetailStat value={game.plays_str} label="plays" />
                <DetailStat value={game.likes_str} label="likes" />
                <DetailStat value={game.version} label="version" />
                <DetailStat value={String(game.remix_count ?? 0)} label="remixes" />
              </div>

              <div className="flex gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <Database className="mt-0.5 size-4 shrink-0 text-indigo-600" />
                <div className="min-w-0 space-y-2">
                  <strong className="block text-sm font-semibold text-slate-950">Remote bundle</strong>
                  <span className="block break-all font-mono text-xs text-slate-500">{game.oss_path}</span>
                  {manifestFiles.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {manifestFiles.map((file) => (
                        <Badge
                          className={file.path === (manifest?.entry || "index.html") ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-slate-200 bg-white text-slate-600"}
                          key={file.path}
                          variant="outline"
                        >
                          {file.path}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              {game.from_create && game.prompt ? (
                <div className="rounded-lg border border-indigo-100 bg-indigo-50/70 p-4">
                  <strong className="text-sm font-semibold text-indigo-900">Generated from prompt</strong>
                  <p className="mt-2 text-sm leading-6 text-indigo-900/75">{game.prompt}</p>
                </div>
              ) : null}

              {game.remixed_from ? (
                <Button asChild className="h-auto justify-start rounded-lg whitespace-normal" variant="outline">
                  <Link href={`/games/${game.remixed_from.id}`}><GitFork size={16} />Remix of {game.remixed_from.title} by {game.remixed_from.author}</Link>
                </Button>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <GameComments gameAuthorId={game.author_id} gameId={game.id} initialComments={comments} />
          <RelatedGames games={related} />
        </section>
      </div>
    </main>
  );
}
