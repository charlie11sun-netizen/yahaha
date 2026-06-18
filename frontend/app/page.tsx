"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import GameCard from "@/components/GameCard";
import { api } from "@/lib/api";
import { fmt } from "@/lib/format";

const ORANGE = "#ff6b35";

export default function HomePage() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("All");

  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.tags });
  const gamesQ = useQuery({ queryKey: ["games", q, tag], queryFn: () => api.games(q, tag) });

  const chips = ["All", ...(tagsQ.data?.tags ?? [])].slice(0, 7);
  const cards = gamesQ.data?.items ?? [];

  return (
    <div style={{ maxWidth: 1200, width: "100%", margin: "0 auto", padding: "36px 28px 80px" }}>
      {/* hero */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap", marginBottom: 30 }}>
        <div style={{ maxWidth: 620 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "#fff1ea", color: "#d4501f", fontFamily: "'IBM Plex Mono'", fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 999, letterSpacing: ".02em", marginBottom: 16 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: ORANGE, animation: "pfpulse 1.6s infinite" }} /> AI-NATIVE GAME PLATFORM
          </div>
          <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 46, lineHeight: 1.04, fontWeight: 700, letterSpacing: "-.03em", marginBottom: 14 }}>
            Prompt a game.<br />Play it in seconds.
          </h1>
          <p style={{ fontSize: 16.5, color: "#7a756c", lineHeight: 1.5, maxWidth: 520 }}>
            Describe an idea, drop in some art, and our multi-agent pipeline builds a playable game — published straight to the arcade below.
          </p>
          <button onClick={() => router.push("/create")} style={{ marginTop: 22, border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 600, fontSize: 15.5, padding: "13px 24px", borderRadius: 12, boxShadow: "0 8px 22px rgba(255,107,53,.32)" }}>
            Start creating →
          </button>
        </div>
        <div style={{ display: "flex", gap: 30 }}>
          <Stat value={`${stats.data?.game_count ?? 0}`} label="live games" />
          <Stat value={fmt(stats.data?.total_plays ?? 0)} label="total plays" />
        </div>
      </div>

      {/* search + tags */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, background: "#fff", border: "1px solid #e8e3d8", borderRadius: 11, padding: "10px 14px", flex: 1, minWidth: 240, maxWidth: 360 }}>
          <span style={{ fontSize: 16, color: "#a8a294" }}>⌕</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search games, tags, creators…" style={{ border: "none", outline: "none", background: "none", fontSize: 14.5, width: "100%", color: "#181613" }} />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {chips.map((t) => {
            const active = tag === t;
            return (
              <button key={t} onClick={() => setTag(t)} style={{ border: `1px solid ${active ? ORANGE : "#e8e3d8"}`, background: active ? ORANGE : "#fff", color: active ? "#fff" : "#5c574e", cursor: "pointer", fontWeight: 600, fontSize: 13, padding: "8px 14px", borderRadius: 999 }}>{t}</button>
            );
          })}
        </div>
      </div>

      {/* grid */}
      {cards.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(290px,1fr))", gap: 22 }}>
          {cards.map((g) => (<GameCard key={g.id} game={g} />))}
        </div>
      ) : (
        <div style={{ textAlign: "center", padding: "70px 20px", color: "#a8a294", fontFamily: "'IBM Plex Mono'", fontSize: 14 }}>
          {gamesQ.isLoading ? "Loading arcade…" : `No games match “${q}”.`}
        </div>
      )}
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div style={{ fontFamily: "'Space Grotesk'", fontSize: 30, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 13, color: "#7a756c", fontFamily: "'IBM Plex Mono'" }}>{label}</div>
    </div>
  );
}
