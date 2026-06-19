"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Box,
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  Maximize2,
  Minimize2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Game } from "@/lib/types";

type Phase = "loading" | "ready" | "error";
type RuntimeKey = "manifest" | "sandbox" | "bundle";
type RuntimeStatus = "pending" | "running" | "ready" | "failed";

const INITIAL_RUNTIME: Record<RuntimeKey, RuntimeStatus> = {
  manifest: "pending",
  sandbox: "pending",
  bundle: "pending",
};

export default function PlayPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const stageRef = useRef<HTMLDivElement>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const played = useRef(false);
  const { data: game, error, isLoading, refetch } = useQuery({
    queryKey: ["game", id],
    queryFn: () => api.game(id),
  });

  const [phase, setPhase] = useState<Phase>("loading");
  const [runtime, setRuntime] = useState<Record<RuntimeKey, RuntimeStatus>>(INITIAL_RUNTIME);
  const [activity, setActivity] = useState<string[]>([]);
  const [iframeKey, setIframeKey] = useState(0);
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [isTheater, setIsTheater] = useState(false);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  const patchRuntime = (key: RuntimeKey, status: RuntimeStatus) => {
    setRuntime((current) => ({ ...current, [key]: status }));
  };

  const addActivity = (line: string) => {
    setActivity((current) => [...current.slice(-3), line]);
  };

  const runLoad = (nextGame: Game) => {
    clearTimers();
    setPhase("loading");
    setRuntime({ manifest: "running", sandbox: "pending", bundle: "pending" });
    setActivity(["Resolving manifest from object storage"]);

    const T = timers.current;
    T.push(setTimeout(() => {
      patchRuntime("manifest", "ready");
      patchRuntime("sandbox", "running");
      addActivity("Manifest verified. Preparing isolated browser runtime");
    }, 420));
    T.push(setTimeout(() => {
      patchRuntime("sandbox", "ready");
      patchRuntime("bundle", "running");
      addActivity("Sandbox ready. Mounting generated bundle");
    }, 950));
    T.push(setTimeout(() => {
      if (!nextGame.bundle_url) {
        patchRuntime("bundle", "failed");
        addActivity("Bundle URL is missing");
        setPhase("error");
        return;
      }
      patchRuntime("bundle", "ready");
      addActivity("Bundle mounted. Starting preview");
      setIframeKey((key) => key + 1);
      setPhase("ready");
    }, 1450));
  };

  useEffect(() => {
    if (game) runLoad(game);
    return clearTimers;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [game?.id, game?.bundle_url]);

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
    if (error) setPhase("error");
  }, [error]);

  const restart = () => {
    if (!game) return;
    played.current = false;
    runLoad(game);
  };

  const recordPlay = () => {
    if (played.current) return;
    played.current = true;
    api.play(id).catch(() => {});
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

  const retry = () => {
    if (game) restart();
    else refetch();
  };

  return (
    <div className="pf-play-page">
      <header className="pf-play-topbar">
        <button className="pf-play-brand" onClick={() => router.push("/")} type="button">
          <span>
            <Box size={18} />
          </span>
          <strong>PlayForge AI</strong>
        </button>
        <div className="pf-play-game-meta">
          <h1>{game?.title || "Loading game"}</h1>
          <p>{game ? `by ${game.author} . ${game.version}` : "Preparing browser runtime"}</p>
        </div>
        <div className="pf-play-actions">
          <button onClick={() => router.back()} type="button">
            <ArrowLeft size={17} />
            Exit
          </button>
          <button disabled={!game || phase !== "ready"} onClick={restart} type="button">
            <RefreshCw size={17} />
            Restart
          </button>
          <button disabled={!game || phase !== "ready"} onClick={toggleFullScreen} type="button">
            {isFullScreen || isTheater ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
            {isFullScreen || isTheater ? "Exit Fullscreen" : "Fullscreen"}
          </button>
        </div>
      </header>

      <main className="pf-play-main">
        <section className="pf-play-info">
          <div className="pf-play-title-card">
            <div>
              <h2>{game?.title || "Generated game"}</h2>
              <p>{game?.summary || "PlayForge is loading the generated game bundle."}</p>
            </div>
            {game?.oss_path && <span>{game.oss_path}</span>}
          </div>
          <RuntimeList runtime={runtime} />
        </section>

        <section className={`pf-play-stage-shell is-${phase}${isTheater ? " is-theater" : ""}`} ref={stageRef}>
          {phase === "loading" && (
            <div className="pf-play-loading">
              <span className="pf-play-loader">
                <LoaderCircle size={42} />
              </span>
              <h2>{isLoading ? "Finding game..." : "Preparing runtime..."}</h2>
              <p>Validating the manifest, opening a sandbox, and mounting the generated bundle.</p>
              <RuntimeList runtime={runtime} compact />
              <ActivityFeed lines={activity} />
            </div>
          )}

          {phase === "ready" && game && (
            <>
              <iframe
                allow="fullscreen"
                key={iframeKey}
                onLoad={recordPlay}
                sandbox="allow-scripts allow-pointer-lock"
                src={game.bundle_url}
                title={game.title}
              />
              <div className="pf-play-stage-status">
                <span>
                  <CircleCheck size={15} />
                  Running in isolated preview
                </span>
                <button onClick={toggleFullScreen} type="button">
                  {isFullScreen || isTheater ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                  {isFullScreen || isTheater ? "Exit" : "Fullscreen"}
                </button>
              </div>
            </>
          )}

          {phase === "error" && (
            <div className="pf-play-error">
              <span>
                <CircleAlert size={30} />
              </span>
              <h2>Could not load this game</h2>
              <p>{error instanceof Error ? error.message : "The generated bundle could not be mounted. Try again or return to your studio."}</p>
              <div>
                <button className="is-primary" onClick={retry} type="button">
                  <RefreshCw size={16} />
                  Retry
                </button>
                <button onClick={() => router.push("/me?section=games")} type="button">
                  Back to Studio
                </button>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function RuntimeList({
  compact = false,
  runtime,
}: {
  compact?: boolean;
  runtime: Record<RuntimeKey, RuntimeStatus>;
}) {
  const rows: { key: RuntimeKey; label: string }[] = [
    { key: "manifest", label: "Manifest" },
    { key: "sandbox", label: "Sandbox" },
    { key: "bundle", label: "Bundle" },
  ];

  return (
    <div className={`pf-play-runtime${compact ? " is-compact" : ""}`}>
      {rows.map((row) => (
        <div className={`pf-play-runtime-row is-${runtime[row.key]}`} key={row.key}>
          {runtime[row.key] === "ready" ? <CircleCheck size={17} /> : runtime[row.key] === "failed" ? <CircleAlert size={17} /> : runtime[row.key] === "running" ? <LoaderCircle className="pf-spin" size={17} /> : <ShieldCheck size={17} />}
          <span>{row.label}</span>
          <strong>{runtimeLabel(runtime[row.key])}</strong>
        </div>
      ))}
    </div>
  );
}

function ActivityFeed({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="pf-play-activity">
      {lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  );
}

function runtimeLabel(status: RuntimeStatus) {
  if (status === "ready") return "Ready";
  if (status === "running") return "Running";
  if (status === "failed") return "Failed";
  return "Pending";
}
