"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import type { CSSProperties, ReactNode } from "react";

import GameCard from "@/components/GameCard";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/format";
import { useToast } from "@/lib/toast";

const ORANGE = "#ff6b35";
const mono = "'IBM Plex Mono'";

export default function AuthorPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { user } = useAuth();
  const flash = useToast();
  const qc = useQueryClient();
  const profileQ = useQuery({ queryKey: ["user", id], queryFn: () => api.userProfile(id) });
  const gamesQ = useQuery({ queryKey: ["user-games", id], queryFn: () => api.userGames(id) });
  const p = profileQ.data;
  const games = gamesQ.data?.items ?? [];

  const toggleFollow = async () => {
    if (!user) {
      flash("Sign in to follow creators");
      router.push("/login");
      return;
    }
    if (!p) return;
    try {
      if (p.is_following) await api.unfollowUser(id);
      else await api.followUser(id);
      qc.invalidateQueries({ queryKey: ["user", id] });
    } catch {
      flash("Could not update follow");
    }
  };

  if (profileQ.isLoading) return <Centered>Loading…</Centered>;
  if (profileQ.isError || !p) return <Centered>Creator not found.</Centered>;

  return (
    <div style={{ maxWidth: 1100, width: "100%", margin: "0 auto", padding: "36px 28px 80px" }}>
      <button onClick={() => router.push("/")} style={{ border: "none", background: "none", cursor: "pointer", color: "#7a756c", fontSize: 14, fontWeight: 500, marginBottom: 18 }}>← Back to arcade</button>
      <div style={{ display: "flex", alignItems: "center", gap: 22, flexWrap: "wrap", marginBottom: 30 }}>
        <div style={avatarStyle}>{p.init}</div>
        <div>
          <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 30, fontWeight: 700, letterSpacing: "-.02em" }}>{p.name}</h1>
          <div style={{ fontSize: 13.5, color: "#7a756c", marginTop: 4 }}>Creator</div>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 26, alignItems: "center", flexWrap: "wrap" }}>
          <Stat value={String(p.game_count)} label="games" />
          <Stat value={fmt(p.total_plays)} label="plays" />
          <Stat value={String(p.followers)} label="followers" />
          {!p.is_self && (
            <button onClick={toggleFollow} style={followBtn(p.is_following)} type="button">
              {p.is_following ? "Following" : "Follow"}
            </button>
          )}
        </div>
      </div>

      {games.length ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(290px,1fr))", gap: 22 }}>
          {games.map((g) => (
            <GameCard key={g.id} game={g} />
          ))}
        </div>
      ) : (
        <Centered>No published games yet.</Centered>
      )}
    </div>
  );
}

const avatarStyle: CSSProperties = {
  width: 84,
  height: 84,
  borderRadius: "50%",
  flex: "none",
  background: "#181613",
  color: "#faf8f3",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 30,
  fontWeight: 700,
  fontFamily: "'Space Grotesk'",
};

function followBtn(active: boolean): CSSProperties {
  return {
    border: `1px solid ${active ? "#e8e3d8" : ORANGE}`,
    background: active ? "#fff" : ORANGE,
    color: active ? "#5c574e" : "#fff",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 14,
    padding: "10px 20px",
    borderRadius: 11,
  };
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontFamily: "'Space Grotesk'", fontSize: 24, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 12, color: "#7a756c", fontFamily: mono }}>{label}</div>
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return <div style={{ textAlign: "center", padding: "90px 20px", color: "#a8a294", fontFamily: mono, fontSize: 14 }}>{children}</div>;
}
