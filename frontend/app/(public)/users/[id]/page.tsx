import { ArrowLeft, Gamepad2, HeartHandshake, Play } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { FollowButton } from "@/app/users/[id]/_components/FollowButton";
import GameCard from "@/components/GameCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { fmt } from "@/lib/format";
import { getPublicUserGames, getPublicUserProfile, ServerApiError } from "@/lib/server-api";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  try {
    const profile = await getPublicUserProfile(id);
    return {
      title: `${profile.name} · GameWeave AI`,
      description: `Games published by ${profile.name} on GameWeave AI.`,
    };
  } catch {
    return { title: "Creator · GameWeave AI" };
  }
}

export default async function AuthorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let profile;
  try {
    profile = await getPublicUserProfile(id);
  } catch (error) {
    if (error instanceof ServerApiError && error.status === 404) notFound();
    throw error;
  }
  const gamesResult = await getPublicUserGames(id).catch(() => ({ items: [] }));
  const games = gamesResult.items;

  return (
    <main className="px-5 py-8 sm:px-8 lg:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <Button asChild className="w-fit gap-2 rounded-lg" variant="ghost">
          <Link href="/explore"><ArrowLeft size={16} />Back to arcade</Link>
        </Button>

        <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-xl shadow-slate-900/5">
          <CardContent className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[auto_1fr_auto] lg:items-center">
            <div className="flex size-24 items-center justify-center rounded-lg bg-indigo-600 font-display text-3xl font-semibold text-white shadow-lg shadow-indigo-500/25">{profile.init}</div>
            <div className="min-w-0 space-y-3">
              <h1 className="font-display text-4xl font-semibold tracking-normal text-slate-950">{profile.name}</h1>
              <p className="max-w-2xl text-base leading-7 text-slate-600">Creator profile, published games, and community activity.</p>
            </div>
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-3 gap-3">
                <Stat icon={Gamepad2} label="games" value={String(profile.game_count)} />
                <Stat icon={Play} label="plays" value={fmt(profile.total_plays)} />
                <Stat icon={HeartHandshake} label="followers" value={String(profile.followers)} />
              </div>
              <FollowButton initialProfile={profile} />
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
              {games.map((game) => <GameCard game={game} key={game.id} />)}
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
