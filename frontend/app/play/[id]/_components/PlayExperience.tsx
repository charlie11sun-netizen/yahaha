"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Box,
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  Maximize2,
  Minimize2,
  RefreshCw,
  Share2,
  Trophy,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { coverBackgroundValue } from "@/lib/cover";
import type { Game, GameManifest } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ActivityFeed, RuntimeList } from "./PlayPanels";
import { handleGameStorageRequest } from "./game-storage";
import { INITIAL_RUNTIME, type Phase, type RuntimeKey, type RuntimeStatus } from "../_lib/play-runtime";

export function PlayExperience({
  game,
  initialLeaderboard,
  related,
  requestedVersion,
}: {
  game: Game;
  initialLeaderboard: components["schemas"]["ScoreOut"][];
  related: Game[];
  requestedVersion: string | null;
}) {
  const id = game.id;
  const router = useRouter();
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const played = useRef(false);
  const qc = useQueryClient();
  const lbQ = useQuery({
    queryKey: ["leaderboard", id],
    queryFn: () => api.leaderboard(id),
    initialData: { items: initialLeaderboard },
    staleTime: 30_000,
  });

  const [phase, setPhase] = useState<Phase>("loading");
  const [runtime, setRuntime] = useState<Record<RuntimeKey, RuntimeStatus>>(INITIAL_RUNTIME);
  const [activity, setActivity] = useState<string[]>([]);
  const [iframeKey, setIframeKey] = useState(0);
  const [bundleUrl, setBundleUrl] = useState<string | null>(null);
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [isTheater, setIsTheater] = useState(false);

  const patchRuntime = (key: RuntimeKey, status: RuntimeStatus) => {
    setRuntime((current) => ({ ...current, [key]: status }));
  };

  const addActivity = (line: string) => {
    setActivity((current) => [...current.slice(-3), line]);
  };

  const runLoad = async (nextGame: Game) => {
    setPhase("loading");
    setRuntime({ manifest: "running", sandbox: "pending", bundle: "pending" });
    setActivity(["Fetching manifest from object storage..."]);

    let manifest: GameManifest | null = null;
    try {
      manifest = requestedVersion
        ? await api.gameManifestVersion(nextGame.id, requestedVersion)
        : await api.gameManifest(nextGame.id);
      patchRuntime("manifest", "ready");
      const sha = manifest.sha256 ? ` sha256=${String(manifest.sha256).slice(0, 12)}` : "";
      const fileCount = manifest.files?.length ? ` files=${manifest.files.length}` : "";
      addActivity(
        `Manifest ${manifest._source === "oss" ? "fetched from OSS" : "resolved"} entry=${manifest.entry || "index.html"} runtime=${manifest.runtime || "iframe"}${fileCount}${sha}`,
      );
    } catch {
      patchRuntime("manifest", "failed");
      addActivity("Manifest fetch failed");
      setPhase("error");
      return;
    }

    if (!manifest) {
      setPhase("error");
      return;
    }
    const nextBundleUrl = manifest.entry_url || nextGame.bundle_url;
    if (!nextBundleUrl) {
      patchRuntime("sandbox", "failed");
      patchRuntime("bundle", "failed");
      addActivity("Bundle URL is missing");
      setPhase("error");
      return;
    }
    setBundleUrl(nextBundleUrl);
    patchRuntime("sandbox", "ready");
    addActivity("Sandboxed iframe prepared");
    patchRuntime("bundle", "running");
    addActivity("Mounting bundle from object storage...");
    setIframeKey((key) => key + 1);
    setPhase("ready");
  };

  const onBundleLoaded = () => {
    patchRuntime("bundle", "ready");
    recordPlay();
  };

  useEffect(() => {
    if (game) void runLoad(game);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [game?.id, game?.bundle_url, requestedVersion]);

  useEffect(() => {
    const onFullScreenChange = () => {
      setIsFullScreen(document.fullscreenElement === stageRef.current);
    };
    document.addEventListener("fullscreenchange", onFullScreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullScreenChange);
  }, []);

  useEffect(() => {
    document.body.style.overflow = isTheater ? "hidden" : "";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsTheater(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isTheater]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frameWindow = frameRef.current?.contentWindow;
      // Sandboxed games have an opaque origin ("null"), so the live iframe
      // WindowProxy is the security boundary. Stale/replaced frames cannot act.
      if (!frameWindow || event.source !== frameWindow) return;
      const data = event.data;
      if (data && typeof data === "object" && data.type === "gameweave:score" && typeof data.points === "number") {
        api
          .submitScore(id, Math.max(0, Math.floor(data.points)), typeof data.name === "string" ? data.name : undefined)
          .then(() => qc.invalidateQueries({ queryKey: ["leaderboard", id] }))
          .catch(() => {});
        return;
      }
      const storageResponse = handleGameStorageRequest(window.localStorage, id, data);
      if (storageResponse) frameWindow.postMessage(storageResponse, "*");
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [id, qc]);

  const restart = () => {
    if (!game) return;
    void runLoad(game);
  };

  const recordPlay = () => {
    if (played.current) return;
    played.current = true;
    api.play(id).catch(() => {});
  };

  const share = async () => {
    const url = typeof window !== "undefined" ? window.location.href : "";
    try {
      if (navigator.share) await navigator.share({ title: game?.title || "GameWeave game", url });
      else await navigator.clipboard.writeText(url);
    } catch {
      /* cancelled */
    }
  };

  const toggleFullScreen = async () => {
    if (!stageRef.current) return;
    try {
      if (document.fullscreenElement === stageRef.current) {
        await document.exitFullscreen();
      } else if (isTheater) {
        setIsTheater(false);
      } else {
        await stageRef.current.requestFullscreen();
        setTimeout(() => {
          if (document.fullscreenElement !== stageRef.current) setIsTheater(true);
        }, 120);
      }
    } catch {
      setIsTheater((current) => !current);
    }
  };

  const retry = restart;

  return (
    <main className="min-h-screen bg-slate-100">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 px-5 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4">
          <button className="flex items-center gap-3 rounded-lg text-left" onClick={() => router.push("/")} type="button">
            <span className="flex size-9 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-lg shadow-indigo-500/25">
              <Box size={18} />
            </span>
            <strong className="font-display text-base font-semibold tracking-normal text-slate-950">GameWeave AI</strong>
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="line-clamp-1 font-display text-lg font-semibold tracking-normal text-slate-950">
              {game?.title || "Loading game"}
            </h1>
            <p className="line-clamp-1 text-sm text-slate-500">
              {game ? `by ${game.author} . ${requestedVersion || game.version}` : "Preparing browser runtime"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button className="rounded-lg" onClick={() => router.back()} type="button" variant="outline">
              <ArrowLeft size={17} />
              Exit
            </Button>
            <Button className="rounded-lg" disabled={!game || phase !== "ready"} onClick={restart} type="button" variant="outline">
              <RefreshCw size={17} />
              Restart
            </Button>
            <Button className="rounded-lg" disabled={!game || phase !== "ready"} onClick={toggleFullScreen} type="button" variant="outline">
              {isFullScreen || isTheater ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
              {isFullScreen || isTheater ? "Exit Fullscreen" : "Fullscreen"}
            </Button>
            <Button className="rounded-lg" onClick={share} type="button" variant="outline">
              <Share2 size={17} />
              Share
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1600px] gap-5 px-5 py-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className={cn("space-y-5", isTheater && "hidden")}>
          <Card className="rounded-lg border-slate-200 bg-white shadow-sm">
            <CardContent className="space-y-3 p-5">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-normal text-slate-950">{game?.title || "Generated game"}</h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {game?.summary || "GameWeave is loading the generated game bundle."}
                </p>
              </div>
              {game?.oss_path ? <p className="break-all font-mono text-xs text-slate-500">{game.oss_path}</p> : null}
            </CardContent>
          </Card>

          <Card className="rounded-lg border-slate-200 bg-white shadow-sm">
            <CardHeader>
              <CardTitle className="font-display text-lg tracking-normal text-slate-950">Runtime</CardTitle>
            </CardHeader>
            <CardContent>
              <RuntimeList runtime={runtime} />
            </CardContent>
          </Card>

          {(lbQ.data?.items?.length ?? 0) > 0 ? (
            <Card className="rounded-lg border-slate-200 bg-white shadow-sm">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 font-display text-lg tracking-normal text-slate-950">
                  <Trophy size={16} />
                  Leaderboard
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ol className="space-y-2">
                  {lbQ.data!.items.map((score) => (
                    <li className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm" key={`${score.rank}-${score.name}`}>
                      <span className="min-w-0 truncate text-slate-700">
                        {score.rank}. {score.name}
                      </span>
                      <strong className="font-semibold text-slate-950">{score.points}</strong>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          ) : null}

          {related.length > 0 ? (
            <Card className="rounded-lg border-slate-200 bg-white shadow-sm">
              <CardHeader>
                <CardTitle className="font-display text-lg tracking-normal text-slate-950">More games</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                {related.slice(0, 4).map((relatedGame) => (
                  <button
                    className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 text-left transition hover:border-indigo-200 hover:bg-indigo-50/40"
                    key={relatedGame.id}
                    onClick={() => router.push(`/play/${relatedGame.id}`)}
                    type="button"
                  >
                    <span className="h-12 w-16 shrink-0 rounded-md bg-slate-900 bg-cover bg-center" style={{ background: coverBackgroundValue(relatedGame.cover) }} />
                    <b className="line-clamp-2 text-sm font-semibold text-slate-950">{relatedGame.title}</b>
                  </button>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </aside>

        <section
          className={cn(
            "relative min-h-[640px] overflow-hidden rounded-lg border border-slate-200 bg-slate-950 shadow-2xl shadow-slate-900/20",
            isTheater && "fixed inset-0 z-[80] min-h-screen rounded-none border-0",
          )}
          ref={stageRef}
        >
          {phase === "loading" ? (
            <div className="flex h-full min-h-[640px] flex-col items-center justify-center gap-5 p-6 text-center text-white">
              <LoaderCircle className="size-12 animate-spin text-indigo-300" />
              <div className="space-y-2">
                <h2 className="font-display text-2xl font-semibold tracking-normal">
                  Preparing runtime...
                </h2>
                <p className="max-w-xl text-sm leading-6 text-slate-300">
                  Validating the manifest, opening a sandbox, and mounting the generated bundle.
                </p>
              </div>
              <RuntimeList runtime={runtime} compact />
              <ActivityFeed lines={activity} />
            </div>
          ) : null}

          {phase === "ready" && game && bundleUrl ? (
            <>
              <iframe
                allow="fullscreen"
                className="h-full min-h-[640px] w-full border-0 bg-white"
                key={iframeKey}
                onLoad={onBundleLoaded}
                ref={frameRef}
                sandbox="allow-scripts allow-pointer-lock"
                src={bundleUrl}
                title={game.title}
              />
              <div className="absolute bottom-4 left-4 right-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/15 bg-slate-950/85 px-4 py-3 text-sm text-white backdrop-blur">
                <Badge className="gap-2 border-emerald-400/30 bg-emerald-400/15 text-emerald-100" variant="outline">
                  <CircleCheck size={15} />
                  Running in isolated preview
                </Badge>
                <Button className="rounded-lg border-white/20 bg-white/10 text-white hover:bg-white/20" onClick={toggleFullScreen} type="button" variant="outline">
                  {isFullScreen || isTheater ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                  {isFullScreen || isTheater ? "Exit" : "Fullscreen"}
                </Button>
              </div>
            </>
          ) : null}

          {phase === "error" ? (
            <div className="flex h-full min-h-[640px] flex-col items-center justify-center gap-5 p-6 text-center text-white">
              <span className="flex size-14 items-center justify-center rounded-lg bg-rose-500/15 text-rose-200">
                <CircleAlert size={30} />
              </span>
              <div className="space-y-2">
                <h2 className="font-display text-2xl font-semibold tracking-normal">Could not load this game</h2>
                <p className="max-w-xl text-sm leading-6 text-slate-300">
                  The generated bundle could not be mounted. Try again or return to your studio.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-3">
                <Button className="rounded-lg" onClick={retry} type="button">
                  <RefreshCw size={16} />
                  Retry
                </Button>
                <Button className="rounded-lg border-white/20 bg-white/10 text-white hover:bg-white/20" onClick={() => router.push("/me?section=games")} type="button" variant="outline">
                  Back to Studio
                </Button>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
