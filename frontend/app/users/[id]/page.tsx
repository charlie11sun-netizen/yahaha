"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Gamepad2, HeartHandshake, Play, Sparkles } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import GameCard from "@/components/GameCard";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/format";
import { useToast } from "@/lib/toast";

export default function AuthorPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { user } = useAuth();
  const flash = useToast();
  const queryClient = useQueryClient();
  const profileQ = useQuery({ queryKey: ["user", id], queryFn: () => api.userProfile(id) });
  const gamesQ = useQuery({ queryKey: ["user-games", id], queryFn: () => api.userGames(id) });
  const profile = profileQ.data;
  const games = gamesQ.data?.items ?? [];

  const toggleFollow = async () => {
    if (!user) {
      flash("Sign in to follow creators");
      router.push("/login");
      return;
    }
    if (!profile) return;
    try {
      if (profile.is_following) await api.unfollowUser(id);
      else await api.followUser(id);
      queryClient.invalidateQueries({ queryKey: ["user", id] });
    } catch {
      flash("Could not update follow");
    }
  };

  if (profileQ.isLoading) return <Centered>Loading creator...</Centered>;
  if (profileQ.isError || !profile) return <Centered>Creator not found.</Centered>;

  return (
    <div className="pf-author-page">
      <div className="pf-author-shell">
        <button className="pf-back-link" onClick={() => router.push("/")} type="button">
          <ArrowLeft size={16} />
          Back to arcade
        </button>

        <section className="pf-author-hero">
          <div className="pf-author-avatar">{profile.init}</div>
          <div className="pf-author-copy">
            <h1>{profile.name}</h1>
            <p>Creator profile, published games, and community activity.</p>
          </div>
          <div className="pf-author-stats">
            <Stat icon={Gamepad2} label="games" value={String(profile.game_count)} />
            <Stat icon={Play} label="plays" value={fmt(profile.total_plays)} />
            <Stat icon={HeartHandshake} label="followers" value={String(profile.followers)} />
          </div>
          {!profile.is_self ? (
            <button className={profile.is_following ? "pf-author-follow is-active" : "pf-author-follow"} onClick={toggleFollow} type="button">
              <Sparkles size={16} />
              {profile.is_following ? "Following" : "Follow"}
            </button>
          ) : null}
        </section>

        <section className="pf-author-games">
          <header>
            <h2>Published games</h2>
            <span>{games.length} total</span>
          </header>
          {games.length ? (
            <div className="pf-author-game-grid">
              {games.map((game) => (
                <GameCard game={game} key={game.id} />
              ))}
            </div>
          ) : (
            <div className="pf-studio-empty">No published games yet.</div>
          )}
        </section>
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value }: { icon: typeof Gamepad2; label: string; value: string }) {
  return (
    <div>
      <Icon size={18} />
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="pf-state-page">{children}</div>;
}
