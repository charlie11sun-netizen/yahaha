"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { Comment, Game } from "@/lib/types";

const ORANGE = "#ff6b35";
const mono = "'IBM Plex Mono'";

const pillBtn = (on: boolean): React.CSSProperties => ({
  display: "inline-flex", alignItems: "center", gap: 7,
  border: `1px solid ${on ? ORANGE : "#e8e3d8"}`, background: on ? "#fff1ea" : "#fff",
  color: on ? "#d4501f" : "#5c574e", cursor: "pointer", fontWeight: 600, fontSize: 13.5,
  padding: "8px 15px", borderRadius: 10,
});

function Centered({ children }: { children: React.ReactNode }) {
  return <div style={{ textAlign: "center", padding: "90px 20px", color: "#a8a294", fontFamily: mono, fontSize: 14 }}>{children}</div>;
}

export default function DetailPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { data: g, isLoading, isError } = useQuery({ queryKey: ["game", id], queryFn: () => api.game(id) });
  const { user } = useAuth();
  const flash = useToast();
  const qc = useQueryClient();
  const commentsQ = useQuery({ queryKey: ["comments", id], queryFn: () => api.comments(id) });
  const relatedQ = useQuery({ queryKey: ["related", id], queryFn: () => api.relatedGames(id) });
  const [commentText, setCommentText] = useState("");
  const [posting, setPosting] = useState(false);
  const [liked, setLiked] = useState(false);
  const [favorited, setFavorited] = useState(false);
  const [likes, setLikes] = useState(0);
  useEffect(() => {
    if (g) { setLiked(!!g.liked); setFavorited(!!g.favorited); setLikes(g.likes); }
  }, [g]);

  if (isLoading) return <Centered>Loading…</Centered>;
  if (isError || !g) return <Centered>Game not found.</Centered>;

  const toggleLike = () => {
    if (!user) { flash("登录后可点赞"); router.push("/login"); return; }
    if (liked) { setLiked(false); setLikes((l) => Math.max(0, l - 1)); api.unlike(g.id).catch(() => {}); }
    else { setLiked(true); setLikes((l) => l + 1); api.like(g.id).catch(() => {}); }
  };
  const toggleFav = () => {
    if (!user) { flash("登录后可收藏"); router.push("/login"); return; }
    const next = !favorited;
    setFavorited(next);
    (next ? api.favorite(g.id) : api.unfavorite(g.id)).catch(() => {});
    qc.invalidateQueries({ queryKey: ["me-favorites"] });
  };

  const share = async () => {
    const url = window.location.href;
    try {
      if (navigator.share) await navigator.share({ title: g.title, url });
      else { await navigator.clipboard.writeText(url); flash("Link copied"); }
    } catch { /* cancelled */ }
  };
  const postComment = async () => {
    if (!user) { flash("Sign in to comment"); router.push("/login"); return; }
    const body = commentText.trim();
    if (!body) return;
    try {
      setPosting(true);
      await api.addComment(g.id, body);
      setCommentText("");
      qc.invalidateQueries({ queryKey: ["comments", id] });
    } catch { flash("Could not post comment"); } finally { setPosting(false); }
  };
  const removeComment = async (cid: string) => {
    try { await api.deleteComment(g.id, cid); qc.invalidateQueries({ queryKey: ["comments", id] }); }
    catch { flash("Could not delete"); }
  };

  return (
    <div style={{ maxWidth: 980, width: "100%", margin: "0 auto", padding: "24px 28px 80px" }}>
      <button onClick={() => router.push("/")} style={{ border: "none", background: "none", cursor: "pointer", color: "#7a756c", fontSize: 14, fontWeight: 500, marginBottom: 20, padding: "6px 0" }}>← Back to arcade</button>
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 30, alignItems: "start" }}>
        <div>
          <div style={{ position: "relative", height: 300, borderRadius: 20, overflow: "hidden", boxShadow: "0 14px 40px rgba(40,30,20,.16)", background: "#181613" }}>
            <div style={{ position: "absolute", inset: 0, background: coverBackground(g.cover) }} />
            <div style={{ position: "absolute", width: 220, height: 220, borderRadius: "50%", background: "rgba(255,255,255,.15)", top: -70, right: -50 }} />
            <div style={{ position: "absolute", width: 120, height: 120, borderRadius: 32, background: "rgba(0,0,0,.13)", bottom: -30, left: 30, transform: "rotate(18deg)" }} />
            <span style={{ position: "absolute", top: 16, left: 16, fontFamily: mono, fontSize: 11, fontWeight: 600, letterSpacing: ".08em", color: "#fff", background: "rgba(0,0,0,.3)", padding: "5px 11px", borderRadius: 999 }}>{g.genre}</span>
          </div>
          <button onClick={() => router.push(`/play/${g.id}`)} style={{ marginTop: 18, width: "100%", border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 17, padding: 16, borderRadius: 14, boxShadow: "0 10px 26px rgba(255,107,53,.32)", display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
            <div style={{ width: 0, height: 0, borderLeft: "13px solid #fff", borderTop: "9px solid transparent", borderBottom: "9px solid transparent" }} /> Play now
          </button>
        </div>
        <div>
          <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 34, fontWeight: 700, letterSpacing: "-.02em", lineHeight: 1.1, marginBottom: 12 }}>{g.title}</h1>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
            <button onClick={() => router.push(`/users/${g.author_id}`)} style={{ display: "inline-flex", alignItems: "center", gap: 10, border: "none", background: "none", cursor: "pointer", padding: 0 }}>
              <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#181613", color: "#faf8f3", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, fontFamily: "'Space Grotesk'" }}>{g.author_init}</div>
              <span style={{ fontSize: 14.5, fontWeight: 600 }}>{g.author}</span>
            </button>
            <span style={{ color: "#cfc8b8" }}>·</span>
            <span style={{ fontSize: 13.5, color: "#7a756c" }}>{g.date}</span>
          </div>
          <div style={{ display: "flex", gap: 10, marginBottom: 20 }}>
            <button onClick={toggleLike} style={pillBtn(liked)}>{liked ? "♥" : "♡"} {likes}</button>
            <button onClick={toggleFav} style={pillBtn(favorited)}>{favorited ? "★" : "☆"} 收藏</button>
            <button onClick={share} style={pillBtn(false)}>↗ Share</button>
          </div>
          <p style={{ fontSize: 15.5, color: "#3a362f", lineHeight: 1.6, marginBottom: 20 }}>{g.summary}</p>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 22 }}>
            {g.tags.map((t) => (<span key={t} style={{ fontSize: 12.5, color: "#8a8479", background: "#fff", border: "1px solid #e8e3d8", padding: "5px 12px", borderRadius: 999 }}>#{t}</span>))}
          </div>
          <div style={{ display: "flex", gap: 26, padding: "18px 0", borderTop: "1px solid #e8e3d8", borderBottom: "1px solid #e8e3d8", marginBottom: 20 }}>
            <DetailStat value={g.plays_str} label="plays" />
            <DetailStat value={g.likes_str} label="likes" />
            <DetailStat value={g.version} label="version" />
          </div>
          <div style={{ background: "#fff", border: "1px solid #e8e3d8", borderRadius: 14, padding: "15px 16px" }}>
            <div style={{ fontFamily: mono, fontSize: 11, fontWeight: 600, color: "#a8a294", letterSpacing: ".06em", marginBottom: 9 }}>REMOTE BUNDLE · OBJECT STORAGE</div>
            <div style={{ fontFamily: mono, fontSize: 12, color: "#5c574e", wordBreak: "break-all", lineHeight: 1.6 }}>{g.oss_path}</div>
          </div>
          {g.from_create && g.prompt && (
            <div style={{ marginTop: 14, background: "#fff8ec", border: "1px solid #f3e2bf", borderRadius: 14, padding: "15px 16px" }}>
              <div style={{ fontFamily: mono, fontSize: 11, fontWeight: 600, color: "#b5862a", letterSpacing: ".06em", marginBottom: 8 }}>✦ GENERATED FROM PROMPT</div>
              <p style={{ fontSize: 13.5, color: "#6b5a2e", lineHeight: 1.5, fontStyle: "italic" }}>“{g.prompt}”</p>
            </div>
          )}
        </div>
      </div>

      <RelatedAndComments
        related={relatedQ.data?.items ?? []}
        comments={commentsQ.data?.items ?? []}
        commentText={commentText}
        setCommentText={setCommentText}
        onPost={postComment}
        posting={posting}
        onDelete={removeComment}
        canModerate={(authorId) => !!user && (user.id === authorId || user.id === g.author_id)}
        onOpen={(rid) => router.push(`/games/${rid}`)}
      />
    </div>
  );
}

function RelatedAndComments(props: {
  related: Game[];
  comments: Comment[];
  commentText: string;
  setCommentText: (v: string) => void;
  onPost: () => void;
  posting: boolean;
  onDelete: (id: string) => void;
  canModerate: (authorId: string) => boolean;
  onOpen: (id: string) => void;
}) {
  const { related, comments, commentText, setCommentText, onPost, posting, onDelete, canModerate, onOpen } = props;
  return (
    <div style={{ marginTop: 40, display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 30, alignItems: "start" }}>
      <div>
        <h2 style={sectionTitle}>Comments</h2>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <input
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") onPost(); }}
            placeholder="Add a comment…"
            style={{ flex: 1, border: "1px solid #e8e3d8", borderRadius: 10, padding: "10px 12px", fontSize: 14, outline: "none" }}
          />
          <button onClick={onPost} disabled={posting} style={{ border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 13.5, padding: "10px 16px", borderRadius: 10 }}>{posting ? "…" : "Post"}</button>
        </div>
        {comments.length === 0 ? (
          <p style={{ color: "#a8a294", fontFamily: mono, fontSize: 13 }}>No comments yet. Be the first.</p>
        ) : (
          comments.map((c) => (
            <div key={c.id} style={{ display: "flex", gap: 10, padding: "12px 0", borderTop: "1px solid #f0ece2" }}>
              <div style={{ width: 30, height: 30, borderRadius: "50%", flex: "none", background: "#efe9dc", color: "#5c574e", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, fontFamily: "'Space Grotesk'" }}>{c.author_init}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{c.author} <span style={{ color: "#a8a294", fontWeight: 400, fontFamily: mono, fontSize: 11 }}>· {c.ago}</span></div>
                <p style={{ fontSize: 14, color: "#3a362f", marginTop: 2, lineHeight: 1.5 }}>{c.body}</p>
              </div>
              {canModerate(c.author_id) && (
                <button onClick={() => onDelete(c.id)} aria-label="Delete comment" style={{ border: "none", background: "none", cursor: "pointer", color: "#c0392b", fontSize: 13 }}>✕</button>
              )}
            </div>
          ))
        )}
      </div>
      <div>
        <h2 style={sectionTitle}>Related games</h2>
        {related.length === 0 ? (
          <p style={{ color: "#a8a294", fontFamily: mono, fontSize: 13 }}>Nothing related yet.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {related.slice(0, 5).map((r) => (
              <button key={r.id} onClick={() => onOpen(r.id)} style={{ display: "flex", gap: 11, alignItems: "center", textAlign: "left", border: "1px solid #e8e3d8", background: "#fff", cursor: "pointer", borderRadius: 12, padding: 10 }}>
                <div style={{ width: 54, height: 40, borderRadius: 8, flex: "none", background: coverBackground(r.cover) }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.title}</div>
                  <div style={{ fontSize: 11.5, color: "#7a756c", fontFamily: mono }}>▶ {r.plays_str}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const sectionTitle: React.CSSProperties = { fontFamily: "'Space Grotesk'", fontSize: 20, fontWeight: 700, marginBottom: 14 };

function DetailStat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div style={{ fontFamily: "'Space Grotesk'", fontSize: 22, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 12, color: "#7a756c", fontFamily: mono }}>{label}</div>
    </div>
  );
}

function coverBackground(cover: string) {
  if (cover.startsWith("/") || cover.startsWith("http://") || cover.startsWith("https://")) {
    return `url("${cover}") center / cover`;
  }
  return cover;
}
