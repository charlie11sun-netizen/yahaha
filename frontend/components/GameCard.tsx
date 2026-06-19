"use client";
import { useRouter } from "next/navigation";

import type { Game } from "@/lib/types";

export default function GameCard({ game }: { game: Game }) {
  const router = useRouter();
  return (
    <div
      onClick={() => router.push(`/games/${game.id}`)}
      style={{ background: "#fff", border: "1px solid #e8e3d8", borderRadius: 18, overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 2px 8px rgba(40,30,20,.05)", cursor: "pointer" }}
    >
      <div style={{ position: "relative", height: 150, overflow: "hidden", background: "#181613" }}>
        <div style={{ position: "absolute", inset: 0, background: coverBackground(game.cover) }} />
        <div style={{ position: "absolute", width: 130, height: 130, borderRadius: "50%", background: "rgba(255,255,255,.16)", top: -40, right: -30 }} />
        <div style={{ position: "absolute", width: 80, height: 80, borderRadius: 24, background: "rgba(0,0,0,.12)", bottom: -22, left: 18, transform: "rotate(18deg)" }} />
        <span style={{ position: "absolute", top: 12, left: 13, fontFamily: "'IBM Plex Mono'", fontSize: 10.5, fontWeight: 600, letterSpacing: ".08em", color: "#fff", background: "rgba(0,0,0,.28)", padding: "4px 9px", borderRadius: 999, backdropFilter: "blur(4px)" }}>{game.genre}</span>
        {game.from_create && (
          <span style={{ position: "absolute", top: 12, right: 13, fontFamily: "'IBM Plex Mono'", fontSize: 10, fontWeight: 600, color: "#181613", background: "#ffd54a", padding: "4px 8px", borderRadius: 999 }}>✦ AI-MADE</span>
        )}
        {game.status && game.status !== "published" && (
          <span style={{ position: "absolute", bottom: 12, left: 13, fontFamily: "'IBM Plex Mono'", fontSize: 10, fontWeight: 600, color: "#fff", background: game.status === "preview" ? "rgba(212,80,31,.92)" : "rgba(70,70,70,.85)", padding: "4px 9px", borderRadius: 999, backdropFilter: "blur(4px)" }}>{game.status === "preview" ? "预览" : "草稿"}</span>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); router.push(`/play/${game.id}`); }}
          style={{ position: "absolute", bottom: 12, right: 12, border: "none", cursor: "pointer", width: 42, height: 42, borderRadius: "50%", background: "#fff", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 4px 12px rgba(0,0,0,.25)" }}
        >
          <div style={{ width: 0, height: 0, borderLeft: "12px solid #181613", borderTop: "8px solid transparent", borderBottom: "8px solid transparent", marginLeft: 3 }} />
        </button>
      </div>
      <div style={{ padding: "15px 16px 16px", display: "flex", flexDirection: "column", flex: 1 }}>
        <div style={{ fontFamily: "'Space Grotesk'", fontWeight: 600, fontSize: 17, letterSpacing: "-.01em", marginBottom: 5 }}>{game.title}</div>
        <p style={{ fontSize: 13.5, color: "#7a756c", lineHeight: 1.45, marginBottom: 12, flex: 1 }}>{game.summary}</p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 13 }}>
          {game.tags.map((t) => (
            <span key={t} style={{ fontSize: 11.5, color: "#8a8479", background: "#f4f1e9", border: "1px solid #ece7dc", padding: "3px 9px", borderRadius: 999 }}>{t}</span>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 9, paddingTop: 12, borderTop: "1px solid #f0ece2" }}>
          <div style={{ width: 24, height: 24, borderRadius: "50%", background: "#efe9dc", color: "#5c574e", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, fontFamily: "'Space Grotesk'" }}>{game.author_init}</div>
          <span style={{ fontSize: 12.5, color: "#5c574e", fontWeight: 500 }}>{game.author}</span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: "#a8a294", fontFamily: "'IBM Plex Mono'" }}>▶ {game.plays_str}</span>
        </div>
      </div>
    </div>
  );
}

function coverBackground(cover: string) {
  if (cover.startsWith("/") || cover.startsWith("http://") || cover.startsWith("https://")) {
    return `url("${cover}") center / cover`;
  }
  return cover;
}
