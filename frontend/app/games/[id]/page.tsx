"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Calendar,
  Database,
  GitFork,
  Heart,
  Play,
  Share2,
  Star,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { coverBackgroundStyle } from "@/lib/cover";
import { useToast } from "@/lib/toast";
import { Centered, DetailStat, RelatedAndComments } from "./_components/GameDetailPanels";

export default function DetailPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { data: game, isError, isLoading } = useQuery({ queryKey: ["game", id], queryFn: () => api.game(id) });
  const { user } = useAuth();
  const flash = useToast();
  const queryClient = useQueryClient();
  const commentsQ = useQuery({ queryKey: ["comments", id], queryFn: () => api.comments(id) });
  const relatedQ = useQuery({ queryKey: ["related", id], queryFn: () => api.relatedGames(id) });
  const manifestQ = useQuery({ queryKey: ["manifest", id], queryFn: () => api.gameManifest(id) });
  const [commentText, setCommentText] = useState("");
  const [posting, setPosting] = useState(false);
  const [liked, setLiked] = useState(false);
  const [favorited, setFavorited] = useState(false);
  const [likes, setLikes] = useState(0);

  useEffect(() => {
    if (!game) return;
    setLiked(!!game.liked);
    setFavorited(!!game.favorited);
    setLikes(game.likes);
  }, [game]);

  if (isLoading) return <Centered>Loading game...</Centered>;
  if (isError || !game) return <Centered>Game not found.</Centered>;

  const requireUser = (message: string) => {
    if (user) return true;
    flash(message);
    router.push("/login");
    return false;
  };

  const toggleLike = () => {
    if (!requireUser("Sign in to like games")) return;
    if (liked) {
      setLiked(false);
      setLikes((value) => Math.max(0, value - 1));
      api.unlike(game.id).catch(() => {});
    } else {
      setLiked(true);
      setLikes((value) => value + 1);
      api.like(game.id).catch(() => {});
    }
  };

  const toggleFavorite = () => {
    if (!requireUser("Sign in to save favorites")) return;
    const next = !favorited;
    setFavorited(next);
    (next ? api.favorite(game.id) : api.unfavorite(game.id)).catch(() => {});
    queryClient.invalidateQueries({ queryKey: ["me-favorites"] });
  };

  const share = async () => {
    const url = window.location.href;
    try {
      if (navigator.share) await navigator.share({ title: game.title, url });
      else {
        await navigator.clipboard.writeText(url);
        flash("Link copied");
      }
    } catch {
      /* user cancelled */
    }
  };

  const remix = () => {
    if (!requireUser("Sign in to remix games")) return;
    const params = new URLSearchParams({
      remix: game.id,
      sourceTitle: game.title,
      idea: `Remix ${game.title} with a fresh mechanic and visual twist.`,
    });
    router.push(`/create?${params.toString()}`);
  };

  const postComment = async () => {
    if (!requireUser("Sign in to comment")) return;
    const body = commentText.trim();
    if (!body) return;
    try {
      setPosting(true);
      await api.addComment(game.id, body);
      setCommentText("");
      queryClient.invalidateQueries({ queryKey: ["comments", id] });
    } catch {
      flash("Could not post comment");
    } finally {
      setPosting(false);
    }
  };

  const removeComment = async (commentId: string) => {
    try {
      await api.deleteComment(game.id, commentId);
      queryClient.invalidateQueries({ queryKey: ["comments", id] });
    } catch {
      flash("Could not delete comment");
    }
  };

  return (
    <main className="px-5 py-8 sm:px-8 lg:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <Button className="w-fit gap-2 rounded-lg" onClick={() => router.push("/explore")} type="button" variant="ghost">
          <ArrowLeft size={16} />
          Back to arcade
        </Button>

        <Card className="overflow-hidden rounded-lg border-slate-200/80 bg-white/90 py-0 shadow-xl shadow-slate-900/5">
          <CardContent className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[420px_minmax(0,1fr)]">
            <div className="space-y-4">
              <div className="relative aspect-[4/3] overflow-hidden rounded-lg bg-slate-900 bg-cover bg-center" style={coverBackgroundStyle(game.cover)}>
                <span className="absolute inset-0 bg-gradient-to-t from-slate-950/65 via-slate-950/5 to-transparent" />
                <Badge className="absolute left-4 top-4 border-white/20 bg-white/90 text-slate-900" variant="outline">
                  {game.genre}
                </Badge>
              </div>
              <Button className="h-11 w-full rounded-lg" onClick={() => router.push(`/play/${game.id}`)} type="button">
                <Play size={18} fill="currentColor" />
                Play now
              </Button>
            </div>

            <div className="min-w-0 space-y-6">
              <div className="space-y-4">
                <h1 className="font-display text-4xl font-semibold tracking-normal text-slate-950 sm:text-5xl">{game.title}</h1>
                <Button className="h-auto justify-start gap-2 px-0 py-0 text-slate-600" onClick={() => router.push(`/users/${game.author_id}`)} type="button" variant="link">
                  <i className="flex size-7 items-center justify-center rounded-full bg-indigo-600 text-xs not-italic text-white">{game.author_init}</i>
                  <span>{game.author}</span>
                  <Calendar size={14} />
                  <span>{game.date}</span>
                </Button>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button className="rounded-lg" onClick={toggleLike} type="button" variant={liked ? "default" : "outline"}>
                  <Heart size={16} fill={liked ? "currentColor" : "none"} />
                  {likes}
                </Button>
                <Button className="rounded-lg" onClick={toggleFavorite} type="button" variant={favorited ? "default" : "outline"}>
                  <Star size={16} fill={favorited ? "currentColor" : "none"} />
                  {favorited ? "Saved" : "Save"}
                </Button>
                <Button className="rounded-lg" onClick={share} type="button" variant="outline">
                  <Share2 size={16} />
                  Share
                </Button>
                <Button className="rounded-lg" onClick={remix} type="button" variant="outline">
                  <GitFork size={16} />
                  Remix
                </Button>
              </div>

              <p className="text-base leading-7 text-slate-600">{game.summary}</p>

              <div className="flex flex-wrap gap-2">
                {(game.tags.length ? game.tags : [game.genre]).map((tag) => (
                  <Badge className="border-slate-200 bg-slate-50 text-slate-600" key={tag} variant="outline">
                    #{tag}
                  </Badge>
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
                  {(manifestQ.data?.files?.length ?? 0) > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {(manifestQ.data?.files ?? []).map((file) => (
                        <Badge
                          className={file.path === (manifestQ.data?.entry || "index.html") ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-slate-200 bg-white text-slate-600"}
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
                <Button
                  className="h-auto justify-start rounded-lg whitespace-normal"
                  onClick={() => router.push(`/games/${game.remixed_from?.id}`)}
                  type="button"
                  variant="outline"
                >
                  <GitFork size={16} />
                  Remix of {game.remixed_from.title} by {game.remixed_from.author}
                </Button>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <RelatedAndComments
          canModerate={(authorId) => !!user && (user.id === authorId || user.id === game.author_id)}
          commentText={commentText}
          comments={commentsQ.data?.items ?? []}
          onDelete={removeComment}
          onOpen={(relatedId) => router.push(`/games/${relatedId}`)}
          onPost={postComment}
          posting={posting}
          related={relatedQ.data?.items ?? []}
          setCommentText={setCommentText}
        />
      </div>
    </main>
  );
}
