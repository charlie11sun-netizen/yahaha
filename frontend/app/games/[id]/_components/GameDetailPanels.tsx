import { UserRound } from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { coverBackgroundStyle } from "@/lib/cover";
import type { Game } from "@/lib/types";

export function RelatedGames({ games }: { games: Game[] }) {
  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 font-display text-xl tracking-normal text-slate-950">
          <UserRound size={18} />Related games
        </CardTitle>
      </CardHeader>
      <CardContent>
        {games.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">Nothing related yet.</p>
        ) : (
          <div className="grid gap-3">
            {games.slice(0, 5).map((game) => (
              <Link
                className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 text-left transition hover:border-indigo-200 hover:bg-indigo-50/40"
                href={`/games/${game.id}`}
                key={game.id}
              >
                <span className="h-14 w-20 shrink-0 rounded-md bg-slate-900 bg-cover bg-center" style={coverBackgroundStyle(game.cover)} />
                <div className="min-w-0">
                  <strong className="line-clamp-1 text-sm font-semibold text-slate-950">{game.title}</strong>
                  <i className="text-xs not-italic text-slate-500">{game.plays_str} plays</i>
                </div>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <strong className="block font-display text-xl font-semibold tracking-normal text-slate-950">{value}</strong>
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</span>
    </div>
  );
}
