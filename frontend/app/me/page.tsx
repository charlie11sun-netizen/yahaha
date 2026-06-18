"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import GameCard from "@/components/GameCard";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/format";

const ORANGE = "#ff6b35";

export default function ProfilePage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<"games" | "favorites">("games");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  const gamesQ = useQuery({ queryKey: ["me-games"], queryFn: api.myGames, enabled: !!user });
  const favQ = useQuery({ queryKey: ["me-favorites"], queryFn: api.myFavorites, enabled: !!user });

  if (loading || !user) return null;

  const games = gamesQ.data?.items ?? [];
  const favorites = favQ.data?.items ?? [];
  const published = games.filter((g) => g.status === "published");
  const totalPlays = published.reduce((a, g) => a + (g.plays || 0), 0);
  const list = tab === "games" ? games : favorites;

  return (
    <div style={{ maxWidth: 1200, width: "100%", margin: "0 auto", padding: "36px 28px 80px" }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 22, flexWrap: "wrap", marginBottom: 30 }}>
        <div style={{ width: 84, height: 84, borderRadius: "50%", flex: "none", background: "#181613", color: "#faf8f3", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 30, fontWeight: 700, fontFamily: "'Space Grotesk'" }}>{user.init}</div>
        <div>
          <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 30, fontWeight: 700, letterSpacing: "-.02em" }}>{user.name}</h1>
          <div style={{ fontSize: 14.5, color: "#7a756c", marginTop: 3 }}>{user.email}</div>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 10, background: "#fff1ea", color: "#d4501f", fontFamily: "'IBM Plex Mono'", fontSize: 11.5, fontWeight: 600, padding: "4px 11px", borderRadius: 999 }}>创作者</span>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 30 }}>
          <Stat value={`${games.length}`} label="作品" />
          <Stat value={`${published.length}`} label="已发布" />
          <Stat value={fmt(totalPlays)} label="总游玩" />
        </div>
      </div>

      {/* tabs */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e8e3d8", marginBottom: 26 }}>
        <Tab active={tab === "games"} onClick={() => setTab("games")}>我的作品 {games.length > 0 && <Count n={games.length} />}</Tab>
        <Tab active={tab === "favorites"} onClick={() => setTab("favorites")}>收藏 {favorites.length > 0 && <Count n={favorites.length} />}</Tab>
      </div>

      {/* grid */}
      {list.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(290px,1fr))", gap: 22 }}>
          {list.map((g) => (<GameCard key={g.id} game={g} />))}
        </div>
      ) : (
        <Empty
          loading={tab === "games" ? gamesQ.isLoading : favQ.isLoading}
          text={tab === "games" ? "你还没有创建游戏" : "还没有收藏的游戏"}
          ctaText={tab === "games" ? "去创建一个 →" : "去首页逛逛 →"}
          onCta={() => router.push(tab === "games" ? "/create" : "/")}
        />
      )}
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontFamily: "'Space Grotesk'", fontSize: 26, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 12.5, color: "#7a756c", fontFamily: "'IBM Plex Mono'" }}>{label}</div>
    </div>
  );
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} style={{ border: "none", background: "none", cursor: "pointer", fontFamily: "'Space Grotesk'", fontWeight: 600, fontSize: 15, color: active ? "#181613" : "#a8a294", padding: "10px 14px", borderBottom: `2px solid ${active ? ORANGE : "transparent"}`, marginBottom: -1, display: "inline-flex", alignItems: "center", gap: 7 }}>{children}</button>
  );
}

function Count({ n }: { n: number }) {
  return <span style={{ fontFamily: "'IBM Plex Mono'", fontSize: 11.5, fontWeight: 600, color: "#a8a294", background: "#f4f1e9", padding: "1px 7px", borderRadius: 999 }}>{n}</span>;
}

function Empty({ loading, text, ctaText, onCta }: { loading: boolean; text: string; ctaText: string; onCta: () => void }) {
  return (
    <div style={{ textAlign: "center", padding: "70px 20px", border: "1px dashed #e0dac9", borderRadius: 18, background: "#fdfcf9" }}>
      <div style={{ fontFamily: "'IBM Plex Mono'", fontSize: 14, color: "#a8a294" }}>{loading ? "加载中…" : text}</div>
      {!loading && (
        <button onClick={onCta} style={{ marginTop: 16, border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 600, fontSize: 14.5, padding: "11px 20px", borderRadius: 11, boxShadow: `0 8px 20px ${ORANGE}33` }}>{ctaText}</button>
      )}
    </div>
  );
}
