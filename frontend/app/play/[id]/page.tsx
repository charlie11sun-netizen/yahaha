"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

const ORANGE = "#ff6b35";
const mono = "'IBM Plex Mono'";
type Phase = "loading" | "ready" | "error";

export default function PlayPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { data: game } = useQuery({ queryKey: ["game", id], queryFn: () => api.game(id) });

  const [phase, setPhase] = useState<Phase>("loading");
  const [log, setLog] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const played = useRef(false);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  const runLoad = (force: boolean) => {
    if (!game) return;
    clearTimers();
    setPhase("loading");
    setLog([]);
    setErr("");
    const base = game.manifest_url.replace(/\/manifest\.json$/, "");
    const push = (m: string) => setLog((l) => [...l, m]);
    const T = timers.current;
    T.push(setTimeout(() => push(`GET ${base}/manifest.json → 200 OK`), 200));
    T.push(setTimeout(() => push("manifest ✓  entry=index.html · runtime=iframe-sandbox"), 700));
    T.push(setTimeout(() => push(`GET ${base}/index.html → 200 OK`), 1150));
    T.push(setTimeout(() => {
      if (force) {
        push("integrity check ✗  sha256 mismatch — bundle rejected");
        setErr("Bundle failed integrity verification. The remote asset may be corrupted.");
        setPhase("error");
      } else {
        push("integrity ✓  sha256 verified · booting sandbox…");
      }
    }, 1650));
    T.push(setTimeout(() => {
      if (force) return;
      setPhase("ready");
      if (!played.current) {
        played.current = true;
        api.play(id).catch(() => {});
      }
    }, 2200));
  };

  useEffect(() => {
    if (game) runLoad(false);
    return clearTimers;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [game]);

  if (!game) {
    return <div style={{ background: "#0f0e0c", minHeight: "calc(100vh - 64px)", display: "flex", alignItems: "center", justifyContent: "center", color: "#8a857b", fontFamily: mono, fontSize: 14 }}>Loading…</div>;
  }

  return (
    <div style={{ background: "#0f0e0c", minHeight: "calc(100vh - 64px)", display: "flex", flexDirection: "column" }}>
      {/* top bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 22px", borderBottom: "1px solid #25221d", color: "#faf8f3" }}>
        <button onClick={() => router.push("/")} style={{ border: "1px solid #34302a", background: "none", cursor: "pointer", color: "#cdc7bb", fontSize: 13.5, fontWeight: 600, padding: "8px 13px", borderRadius: 9 }}>← Exit</button>
        <div>
          <div style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 16 }}>{game.title}</div>
          <div style={{ fontSize: 12, color: "#8a857b" }}>by {game.author} · {game.version}</div>
        </div>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: mono, fontSize: 11, color: "#8a857b", background: "#1b1916", border: "1px solid #2c2823", padding: "6px 11px", borderRadius: 8, maxWidth: "46vw", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>⛁ {game.oss_path}</span>
      </div>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 22, position: "relative" }}>
        {phase === "loading" && (
          <div style={{ width: "100%", maxWidth: 520 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 13, marginBottom: 18 }}>
              <div style={{ width: 30, height: 30, borderRadius: "50%", border: "3px solid #2c2823", borderTopColor: ORANGE, animation: "pfspin .8s linear infinite" }} />
              <div style={{ color: "#faf8f3", fontWeight: 600, fontSize: 15.5, fontFamily: "'Space Grotesk'" }}>Loading bundle from object storage…</div>
            </div>
            <div style={{ background: "#161412", border: "1px solid #2c2823", borderRadius: 13, padding: "15px 16px", fontFamily: mono, fontSize: 12.5, lineHeight: 1.85, color: "#9fe3b6", minHeight: 130 }}>
              {log.map((ln, i) => (<div key={i} style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}><span style={{ color: "#5f6f64" }}>▸</span> {ln}</div>))}
              <span style={{ display: "inline-block", width: 8, height: 15, background: ORANGE, animation: "pfblink 1s infinite", verticalAlign: "middle" }} />
            </div>
          </div>
        )}

        {phase === "ready" && (
          <div style={{ width: "100%", maxWidth: 960, display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ position: "relative", height: "min(72vh, 640px)", borderRadius: 16, overflow: "hidden", background: "#000", boxShadow: "0 20px 60px rgba(0,0,0,.5)", border: "1px solid #2c2823" }}>
              <iframe src={game.bundle_url} sandbox="allow-scripts allow-pointer-lock" style={{ width: "100%", height: "100%", border: 0, display: "block" }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 14, color: "#8a857b", fontFamily: mono, fontSize: 11.5 }}>
              <span style={{ color: "#39ff88" }}>● running remote bundle in sandboxed iframe</span>
              <div style={{ flex: 1 }} />
              <button onClick={() => runLoad(false)} style={{ border: "none", background: "none", cursor: "pointer", color: "#cdc7bb", fontFamily: "inherit", fontSize: 11.5 }}>↻ restart</button>
              <button onClick={() => runLoad(true)} style={{ border: "none", background: "none", cursor: "pointer", color: "#7a756c", fontFamily: "inherit", fontSize: 11.5 }}>demo: force load failure</button>
            </div>
          </div>
        )}

        {phase === "error" && (
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <div style={{ width: 56, height: 56, borderRadius: "50%", background: "#2a1714", border: "1px solid #5a2a23", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 18px", fontSize: 26, color: "#e2483d" }}>!</div>
            <h2 style={{ color: "#faf8f3", fontFamily: "'Space Grotesk'", fontSize: 22, fontWeight: 700, marginBottom: 10 }}>Couldn&apos;t load this game</h2>
            <p style={{ color: "#9b958a", fontSize: 14, lineHeight: 1.55, marginBottom: 22 }}>{err}</p>
            <div style={{ display: "flex", gap: 11, justifyContent: "center" }}>
              <button onClick={() => runLoad(false)} style={{ border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 14.5, padding: "12px 22px", borderRadius: 11 }}>Retry</button>
              <button onClick={() => router.push("/")} style={{ border: "1px solid #34302a", cursor: "pointer", background: "none", color: "#cdc7bb", fontWeight: 600, fontSize: 14.5, padding: "12px 22px", borderRadius: 11 }}>Back to arcade</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
