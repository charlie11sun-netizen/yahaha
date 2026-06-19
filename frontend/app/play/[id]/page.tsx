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
  ShieldCheck,
  Trophy,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

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
  const qc = useQueryClient();
  const { data: game, error, isLoading, refetch } = useQuery({
    queryKey: ["game", id],
    queryFn: () => api.game(id),
  });
  const lbQ = useQuery({ queryKey: ["leaderboard", id], queryFn: () => api.leaderboard(id) });
  const relatedQ = useQuery({ queryKey: ["related", id], queryFn: () => api.relatedGames(id) });

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

  const runLoad = async (nextGame: Game) => {
    clearTimers();
    setPhase("loading");
    setRuntime({ manifest: "running", sandbox: "pending", bundle: "pending" });
    setActivity(["Fetching manifest from object storage…"]);

    // 真实拉取 manifest（后端从 OSS 读取），替代此前的纯动画
    try {
      const m = await api.gameManifest(nextGame.id);
      patchRuntime("manifest", "ready");
      const sha = m.sha256 ? ` · sha256=${String(m.sha256).slice(0, 12)}` : "";
      addActivity(
        `Manifest ${m._source === "oss" ? "fetched from OSS" : "resolved"} ✓ entry=${m.entry || "index.html"} · runtime=${m.runtime || "iframe"}${sha}`,
      );
    } catch {
      patchRuntime("manifest", "failed");
      addActivity("Manifest fetch failed");
      setPhase("error");
      return;
    }

    patchRuntime("sandbox", "running");
    addActivity("Preparing isolated browser runtime");
    const T = timers.current;
    T.push(setTimeout(() => {
      patchRuntime("sandbox", "ready");
      patchRuntime("bundle", "running");
      addActivity("Sandbox ready. Mounting generated bundle");
    }, 400));
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
    }, 850));
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

  // iframe 游戏可回传分数：window.parent.postMessage({type:"playforge:score", points, name})
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const d = event.data;
      if (d && typeof d === "object" && d.type === "playforge:score" && typeof d.points === "number") {
        api
          .submitScore(id, Math.max(0, Math.floor(d.points)), typeof d.name === "string" ? d.name : undefined)
          .then(() => qc.invalidateQueries({ queryKey: ["leaderboard", id] }))
          .catch(() => {});
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [id, qc]);

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

  const share = async () => {
    const url = typeof window !== "undefined" ? window.location.href : "";
    try {
      if (navigator.share) await navigator.share({ title: game?.title || "PlayForge game", url });
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
          <button onClick={share} type="button">
            <Share2 size={17} />
            Share
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
          {(lbQ.data?.items?.length ?? 0) > 0 && (
            <div style={panelStyle}>
              <h3 style={panelTitle}>
                <Trophy size={14} /> Leaderboard
              </h3>
              <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                {lbQ.data!.items.map((s) => (
                  <li key={`${s.rank}-${s.name}`} style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12.5, color: "#cdc7bb" }}>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.rank}. {s.name}</span>
                    <strong style={{ color: "#faf8f3" }}>{s.points}</strong>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {(relatedQ.data?.items?.length ?? 0) > 0 && (
            <div style={panelStyle}>
              <h3 style={panelTitle}>More games</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {relatedQ.data!.items.slice(0, 4).map((r) => (
                  <button key={r.id} onClick={() => router.push(`/play/${r.id}`)} type="button" style={{ display: "flex", gap: 10, alignItems: "center", textAlign: "left", border: "1px solid #2c2823", background: "#161412", cursor: "pointer", borderRadius: 9, padding: 7 }}>
                    <span style={{ width: 42, height: 30, borderRadius: 6, flex: "none", background: coverBg(r.cover) }} />
                    <b style={{ fontSize: 12.5, color: "#faf8f3", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.title}</b>
                  </button>
                ))}
              </div>
            </div>
          )}
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
      {lines.map((line, index) => (
        <p key={`${index}-${line}`}>{line}</p>
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

const panelStyle: CSSProperties = {
  marginTop: 14,
  background: "#1b1916",
  border: "1px solid #2c2823",
  borderRadius: 12,
  padding: "13px 14px",
};

const panelTitle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  color: "#faf8f3",
  fontSize: 13,
  fontWeight: 700,
  fontFamily: "'Space Grotesk'",
  marginBottom: 10,
};

function coverBg(cover: string) {
  if (cover && (cover.startsWith("/") || cover.startsWith("http"))) return `url("${cover}") center / cover`;
  return cover || "linear-gradient(135deg,#101844,#4f7dff)";
}
