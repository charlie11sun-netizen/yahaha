"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Gamepad2, HeartHandshake, Play, Sparkles } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { StatusPage } from "@/app/_components/StatusPage";
import GameCard from "@/components/GameCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
    <main className="px-5 py-8 sm:px-8 lg:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <Button className="w-fit gap-2 rounded-lg" onClick={() => router.push("/explore")} type="button" variant="ghost">
          <ArrowLeft size={16} />
          Back to arcade
        </Button>

        <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-xl shadow-slate-900/5">
          <CardContent className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[auto_1fr_auto] lg:items-center">
            <div className="flex size-24 items-center justify-center rounded-lg bg-indigo-600 font-display text-3xl font-semibold text-white shadow-lg shadow-indigo-500/25">
              {profile.init}
            </div>
            <div className="min-w-0 space-y-3">
              <h1 className="font-display text-4xl font-semibold tracking-normal text-slate-950">{profile.name}</h1>
              <p className="max-w-2xl text-base leading-7 text-slate-600">
                Creator profile, published games, and community activity.
              </p>
            </div>
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-3 gap-3">
                <Stat icon={Gamepad2} label="games" value={String(profile.game_count)} />
                <Stat icon={Play} label="plays" value={fmt(profile.total_plays)} />
                <Stat icon={HeartHandshake} label="followers" value={String(profile.followers)} />
              </div>
              {!profile.is_self ? (
                <Button
                  className="rounded-lg"
                  onClick={toggleFollow}
                  type="button"
                  variant={profile.is_following ? "secondary" : "default"}
                >
                  <Sparkles size={16} />
                  {profile.is_following ? "Following" : "Follow"}
                </Button>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <section className="space-y-5">
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="font-display text-2xl font-semibold tracking-normal text-slate-950">Published games</h2>
              <p className="text-sm text-slate-500">{games.length} total</p>
            </div>
          </header>
          {games.length ? (
            <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {games.map((game) => (
                <GameCard game={game} key={game.id} />
              ))}
            </div>
          ) : (
            <Card className="rounded-lg border-dashed border-slate-200 bg-white/70 text-center text-sm text-slate-500">
              <CardContent className="p-10">No published games yet.</CardContent>
            </Card>
          )}
        </section>
      </div>
    </main>
  );
}

function Stat({ icon: Icon, label, value }: { icon: typeof Gamepad2; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <Icon className="mb-3 size-4 text-indigo-600" />
      <strong className="block font-display text-lg font-semibold tracking-normal text-slate-950">{value}</strong>
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</span>
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return <StatusPage>{children}</StatusPage>;
}
