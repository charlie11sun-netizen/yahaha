"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GitFork, Heart, Share2, Star } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";

export function GameActions({
  gameId,
  initialFavorited,
  initialLiked,
  initialLikes,
  title,
}: {
  gameId: string;
  initialFavorited: boolean;
  initialLiked: boolean;
  initialLikes: number;
  title: string;
}) {
  const { loading: authLoading, user } = useAuth();
  const flash = useToast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [liked, setLiked] = useState(initialLiked);
  const [favorited, setFavorited] = useState(initialFavorited);
  const [likes, setLikes] = useState(initialLikes);
  const personalized = useQuery({
    queryKey: ["game-personalized", gameId, user?.id],
    queryFn: () => api.game(gameId),
    enabled: !!user,
    staleTime: 15_000,
  });
  const personalizedLoading = !!user && personalized.isLoading;

  useEffect(() => {
    if (!personalized.data) return;
    setLiked(!!personalized.data.liked);
    setFavorited(!!personalized.data.favorited);
    setLikes(personalized.data.likes);
  }, [personalized.data]);

  const requireUser = (message: string) => {
    if (authLoading) return false;
    if (user) return true;
    flash(message);
    router.push(`/login?next=${encodeURIComponent(`/games/${gameId}`)}`);
    return false;
  };

  const toggleLike = async () => {
    if (!requireUser("Sign in to like games")) return;
    const previous = { liked, likes };
    const nextLiked = !liked;
    setLiked(nextLiked);
    setLikes((value) => Math.max(0, value + (nextLiked ? 1 : -1)));
    try {
      const result = nextLiked ? await api.like(gameId) : await api.unlike(gameId);
      setLiked(result.liked);
      setLikes(result.likes);
    } catch {
      setLiked(previous.liked);
      setLikes(previous.likes);
      flash("Could not update like");
    }
  };

  const toggleFavorite = async () => {
    if (!requireUser("Sign in to save favorites")) return;
    const previous = favorited;
    const next = !favorited;
    setFavorited(next);
    try {
      const result = next ? await api.favorite(gameId) : await api.unfavorite(gameId);
      setFavorited(result.favorited);
      await queryClient.invalidateQueries({ queryKey: ["me-favorites"] });
    } catch {
      setFavorited(previous);
      flash("Could not update favorites");
    }
  };

  const share = async () => {
    const url = window.location.href;
    try {
      if (navigator.share) await navigator.share({ title, url });
      else {
        await navigator.clipboard.writeText(url);
        flash("Link copied");
      }
    } catch {
      // The native share sheet may be dismissed without an error state.
    }
  };

  const remix = () => {
    if (!requireUser("Sign in to remix games")) return;
    const params = new URLSearchParams({
      remix: gameId,
      sourceTitle: title,
      idea: `Remix ${title} with a fresh mechanic and visual twist.`,
    });
    router.push(`/create?${params.toString()}`);
  };

  return (
    <div className="flex flex-wrap gap-3">
      <Button aria-label={`Like ${title}`} aria-pressed={liked} className="rounded-lg" disabled={authLoading || personalizedLoading} onClick={toggleLike} type="button" variant={liked ? "default" : "outline"}>
        <Heart size={16} fill={liked ? "currentColor" : "none"} />
        {likes}
      </Button>
      <Button className="rounded-lg" disabled={authLoading || personalizedLoading} onClick={toggleFavorite} type="button" variant={favorited ? "default" : "outline"}>
        <Star size={16} fill={favorited ? "currentColor" : "none"} />
        {favorited ? "Saved" : "Save"}
      </Button>
      <Button className="rounded-lg" onClick={share} type="button" variant="outline">
        <Share2 size={16} />Share
      </Button>
      <Button className="rounded-lg" disabled={authLoading} onClick={remix} type="button" variant="outline">
        <GitFork size={16} />Remix
      </Button>
    </div>
  );
}
