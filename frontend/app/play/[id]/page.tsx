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
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Game, GameManifest } from "@/lib/types";
import { ActivityFeed, RuntimeList } from "./_components/PlayPanels";
import { INITIAL_RUNTIME, coverBg, type Phase, type RuntimeKey, type RuntimeStatus } from "./_lib/play-runtime";

export default function PlayPage() {
  const { id } = useParams() as { id: string };
  const searchParams = useSearchParams();
  const requestedVersion = searchParams.get("version");
  const router = useRouter();
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
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
    setActivity(["Fetching manifest from object storage…"]);

    // 真实拉取 manifest（后端从 OSS 读取），替代此前的纯动画
    let manifest: GameManifest | null = null;
    try {
      manifest = requestedVersion
        ? await api.gameManifestVersion(nextGame.id, requestedVersion)
        : await api.gameManifest(nextGame.id);
      patchRuntime("manifest", "ready");
      const sha = manifest.sha256 ? ` · sha256=${String(manifest.sha256).slice(0, 12)}` : "";
      const fileCount = manifest.files?.length ? ` · files=${manifest.files.length}` : "";
      addActivity(
        `Manifest ${manifest._source === "oss" ? "fetched from OSS" : "resolved"} ✓ entry=${manifest.entry || "index.html"} · runtime=${manifest.runtime || "iframe"}${fileCount}${sha}`,
      );
    } catch {
      patchRuntime("manifest", "failed");
      addActivity("Manifest fetch failed");
      setPhase("error");
      return;
    }

    // 舞台状态绑定真实事件：bundle 状态由 iframe onLoad 翻转，
    // 不再用 setTimeout 表演"已挂载"（真 404 时旧 UI 已显示 Bundle mounted）。
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
    addActivity("Sandboxed iframe prepared (scripts only, no same-origin)");
    patchRuntime("bundle", "running");
    addActivity("Mounting bundle from object storage…");
    setIframeKey((key) => key + 1);
    setPhase("ready");
  };

  const onBundleLoaded = () => {
    patchRuntime("bundle", "ready");
    recordPlay();
  };

  useEffect(() => {
    if (game) runLoad(game);
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
    if (error) setPhase("error");
  }, [error]);

  // iframe 游戏可回传分数：window.parent.postMessage({type:"gameweave:score", points, name})
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      // 只信任游戏 iframe 本身发来的消息，其他窗口引用（opener、嵌入内容）不得刷榜
      if (!frameRef.current || event.source !== frameRef.current.contentWindow) return;
      const d = event.data;
      if (d && typeof d === "object" && d.type === "gameweave:score" && typeof d.points === "number") {
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
    // played 不重置：plays 统计的是"一次游玩会话"，点 Restart 不该 +1
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
          <strong>GameWeave AI</strong>
        </button>
        <div className="pf-play-game-meta">
          <h1>{game?.title || "Loading game"}</h1>
          <p>{game ? `by ${game.author} . ${requestedVersion || game.version}` : "Preparing browser runtime"}</p>
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
              <p>{game?.summary || "GameWeave is loading the generated game bundle."}</p>
            </div>
            {game?.oss_path && <span>{game.oss_path}</span>}
          </div>
          <RuntimeList runtime={runtime} />
          {(lbQ.data?.items?.length ?? 0) > 0 && (
            <div className="pf-play-side-panel">
              <h3>
                <Trophy size={14} /> Leaderboard
              </h3>
              <ol className="pf-play-leaderboard">
                {lbQ.data!.items.map((s) => (
                  <li key={`${s.rank}-${s.name}`}>
                    <span>{s.rank}. {s.name}</span>
                    <strong>{s.points}</strong>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {(relatedQ.data?.items?.length ?? 0) > 0 && (
            <div className="pf-play-side-panel">
              <h3>More games</h3>
              <div className="pf-play-related-list">
                {relatedQ.data!.items.slice(0, 4).map((r) => (
                  <button key={r.id} onClick={() => router.push(`/play/${r.id}`)} type="button">
                    <span style={{ background: coverBg(r.cover) }} />
                    <b>{r.title}</b>
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

          {phase === "ready" && game && bundleUrl && (
            <>
              <iframe
                allow="fullscreen"
                key={iframeKey}
                onLoad={onBundleLoaded}
                ref={frameRef}
                sandbox="allow-scripts allow-pointer-lock"
                src={bundleUrl}
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
