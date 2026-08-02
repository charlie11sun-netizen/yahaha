import { notFound } from "next/navigation";

import { PlayExperience } from "@/app/play/[id]/_components/PlayExperience";
import {
  getPublicGame,
  getPublicLeaderboard,
  getPublicRelatedGames,
  ServerApiError,
} from "@/lib/server-api";

export default async function PlayPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ version?: string }>;
}) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  let game;
  try {
    game = await getPublicGame(id);
  } catch (error) {
    if (error instanceof ServerApiError && error.status === 404) notFound();
    throw error;
  }
  const [leaderboardResult, relatedResult] = await Promise.allSettled([
    getPublicLeaderboard(id),
    getPublicRelatedGames(id),
  ]);

  return (
    <PlayExperience
      game={game}
      initialLeaderboard={leaderboardResult.status === "fulfilled" ? leaderboardResult.value.items : []}
      related={relatedResult.status === "fulfilled" ? relatedResult.value.items : []}
      requestedVersion={query.version || null}
    />
  );
}
