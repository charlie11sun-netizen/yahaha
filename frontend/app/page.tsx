"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { Game } from "@/lib/types";

const GRAD = "linear-gradient(135deg,#7c5cff,#5b8def)";
const INK = "#16182e";
const GRAY = "#6b7280";
const LIGHT = "#9ca3af";
const BORDER = "#ececf4";
const SOFT = "#f7f8fd";
const SG = "'Space Grotesk'";

/* icons */
const sv = (s: number) => ({ width: s, height: s, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const });
const IcChat = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>);
const IcUpload = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>);
const IcSparkle = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" /></svg>);
const IcPlay = ({ s = 16 }: { s?: number }) => (<svg {...sv(s)} fill="currentColor" stroke="none"><polygon points="6 4 20 12 6 20" /></svg>);
const IcSearch = ({ s = 16 }: { s?: number }) => (<svg {...sv(s)}><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>);
const IcDb = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>);
const IcServer = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><rect x="3" y="4" width="18" height="7" rx="2" /><rect x="3" y="13" width="18" height="7" rx="2" /><line x1="7" y1="7.5" x2="7" y2="7.5" /><line x1="7" y1="16.5" x2="7" y2="16.5" /></svg>);
const IcList = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><circle cx="3.5" cy="6" r="1" /><circle cx="3.5" cy="12" r="1" /><circle cx="3.5" cy="18" r="1" /></svg>);
const IcGlobe = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z" /></svg>);
const IcCheck = ({ s = 14 }: { s?: number }) => (<svg {...sv(s)} strokeWidth={2.6}><polyline points="20 6 9 17 4 12" /></svg>);

const gradBtn: React.CSSProperties = { border: "none", cursor: "pointer", background: GRAD, color: "#fff", fontWeight: 600, fontSize: 15, padding: "12px 22px", borderRadius: 12, boxShadow: "0 8px 22px rgba(124,92,255,.32)", display: "inline-flex", alignItems: "center", gap: 8 };
const ghostBtn: React.CSSProperties = { border: `1px solid ${BORDER}`, background: "#fff", cursor: "pointer", color: INK, fontWeight: 600, fontSize: 15, padding: "12px 20px", borderRadius: 12, display: "inline-flex", alignItems: "center", gap: 8 };
const chip = (c: string): React.CSSProperties => ({ fontSize: 11.5, color: c, background: `${c}14`, padding: "3px 9px", borderRadius: 999, fontWeight: 500 });

export default function HomePage() {
  const router = useRouter();
  const gamesQ = useQuery({ queryKey: ["games", "", "All"], queryFn: () => api.games("", "All") });
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.tags });

  const all = gamesQ.data?.items ?? [];
  const byPlays = useMemo(() => [...all].sort((a, b) => b.plays - a.plays), [all]);
  const featured = byPlays[0];
  const trending = byPlays.slice(0, 6);

  const [q, setQ] = useState("");
  const [tag, setTag] = useState("All");
  const chips = ["All", ...(tagsQ.data?.tags ?? [])].slice(0, 6);
  const explore = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return all.filter((g) => {
      if (tag !== "All" && !g.tags.includes(tag)) return false;
      if (ql && !`${g.title} ${g.summary} ${g.author} ${g.tags.join(" ")}`.toLowerCase().includes(ql)) return false;
      return true;
    });
  }, [all, q, tag]);

  return (
    <div style={{ background: "#fff", width: "100%", color: INK }}>
      {/* HERO */}
      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "46px 28px 30px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 40, alignItems: "center" }}>
        <div>
          <h1 style={{ fontFamily: SG, fontSize: 52, fontWeight: 800, lineHeight: 1.05, letterSpacing: "-.03em" }}>
            Turn any idea<br />into a playable<br />
            <span style={{ background: GRAD, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>AI game</span>
          </h1>
          <p style={{ fontSize: 16.5, color: GRAY, lineHeight: 1.55, margin: "20px 0 26px", maxWidth: 440 }}>
            Describe a game concept, upload assets, and let AI agents generate, package, and publish a playable experience.
          </p>
          <div style={{ display: "flex", gap: 13, flexWrap: "wrap" }}>
            <button onClick={() => router.push("/create")} style={gradBtn}><IcSparkle s={17} /> Create with AI</button>
            <button onClick={() => document.getElementById("explore")?.scrollIntoView({ behavior: "smooth" })} style={ghostBtn}><IcPlay /> Explore Games</button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 34 }}>
            {["Describe", "Upload", "Generate", "Play"].map((label, i) => (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 7, width: 74 }}>
                  <div style={{ width: 42, height: 42, borderRadius: 12, background: SOFT, border: `1px solid ${BORDER}`, display: "flex", alignItems: "center", justifyContent: "center", color: "#6d5efc" }}>
                    {[<IcChat key="a" />, <IcUpload key="b" />, <IcSparkle key="c" />, <IcPlay key="d" />][i]}
                  </div>
                  <span style={{ fontSize: 12.5, color: GRAY, fontWeight: 500 }}>{label}</span>
                </div>
                {i < 3 && <span style={{ color: "#cbd0e0", marginBottom: 22 }}>›</span>}
              </div>
            ))}
          </div>
        </div>

        {/* trending card */}
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 22, padding: 20, boxShadow: "0 20px 50px rgba(40,40,90,.08)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <span style={{ fontFamily: SG, fontWeight: 700, fontSize: 16 }}>Trending on PlayForge</span>
            <span style={{ fontSize: 13, color: "#6d5efc", fontWeight: 600, cursor: "pointer" }} onClick={() => document.getElementById("explore")?.scrollIntoView({ behavior: "smooth" })}>View all →</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 14 }}>
            {featured ? (
              <div onClick={() => router.push(`/play/${featured.id}`)} style={{ position: "relative", borderRadius: 14, overflow: "hidden", minHeight: 250, background: featured.cover, cursor: "pointer" }}>
                <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, textAlign: "center" }}>
                  <span style={{ fontFamily: SG, fontWeight: 800, fontSize: 26, color: "#fff", textShadow: "0 2px 14px rgba(0,0,0,.5)", letterSpacing: "-.01em", lineHeight: 1.05 }}>{featured.title.toUpperCase()}</span>
                </div>
                <span style={{ position: "absolute", bottom: 12, left: 12, fontFamily: "'IBM Plex Mono'", fontSize: 10.5, fontWeight: 600, color: "#fff", background: "rgba(0,0,0,.4)", padding: "4px 10px", borderRadius: 999 }}>◷ Featured</span>
              </div>
            ) : <div style={{ minHeight: 250, borderRadius: 14, background: SOFT }} />}
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {trending.slice(0, 6).map((g) => (
                <div key={g.id} onClick={() => router.push(`/games/${g.id}`)} style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
                  <div style={{ width: 38, height: 38, borderRadius: 9, flex: "none", background: g.cover }} />
                  <span style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.2, color: INK }}>{g.title}</span>
                </div>
              ))}
              {trending.length === 0 && <span style={{ fontSize: 13, color: LIGHT }}>暂无游戏</span>}
            </div>
          </div>
        </div>
      </section>

      {/* FEATURED GAME */}
      {featured && (
        <section style={{ maxWidth: 1200, margin: "0 auto", padding: "16px 28px" }}>
          <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 22, padding: 22, boxShadow: "0 8px 28px rgba(40,40,90,.05)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, fontFamily: SG, fontWeight: 700, fontSize: 15 }}><span style={{ color: "#6d5efc" }}><IcSparkle s={16} /></span> Featured Game</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1.1fr", gap: 26, alignItems: "center" }}>
              <div style={{ position: "relative", borderRadius: 16, overflow: "hidden", minHeight: 230, background: featured.cover }}>
                <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 18, textAlign: "center" }}>
                  <span style={{ fontFamily: SG, fontWeight: 800, fontSize: 30, color: "#fff", textShadow: "0 2px 16px rgba(0,0,0,.5)" }}>{featured.title.toUpperCase()}</span>
                </div>
              </div>
              <div>
                <h2 style={{ fontFamily: SG, fontSize: 30, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 8 }}>{featured.title}</h2>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, color: GRAY, marginBottom: 14 }}>
                  <div style={{ width: 22, height: 22, borderRadius: "50%", background: GRAD, color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700 }}>{featured.author_init}</div>
                  By <b style={{ color: INK }}>{featured.author}</b> <span style={{ color: "#6d5efc" }}><IcCheck s={13} /></span>
                </div>
                <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 14 }}>
                  {featured.tags.map((t) => (<span key={t} style={chip("#6d5efc")}>{t}</span>))}
                  {featured.from_create && <span style={chip("#10b981")}>AI Generated</span>}
                </div>
                <p style={{ fontSize: 15, color: "#3a3d52", lineHeight: 1.55, marginBottom: 18 }}>{featured.summary}</p>
                <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, color: LIGHT, fontFamily: "'IBM Plex Mono'" }}>▶ {featured.plays_str} Plays · {featured.date}</span>
                  <div style={{ flex: 1 }} />
                  <button onClick={() => router.push(`/play/${featured.id}`)} style={gradBtn}><IcPlay /> Play Now</button>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* EXPLORE */}
      <section id="explore" style={{ maxWidth: 1200, margin: "0 auto", padding: "30px 28px 10px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", marginBottom: 22 }}>
          <h2 style={{ fontFamily: SG, fontSize: 26, fontWeight: 700, letterSpacing: "-.02em" }}>Explore Published Games</h2>
          <div style={{ display: "flex", alignItems: "center", gap: 8, background: SOFT, border: `1px solid ${BORDER}`, borderRadius: 11, padding: "9px 13px", width: 230 }}>
            <span style={{ color: LIGHT }}><IcSearch /></span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search games…" style={{ border: "none", outline: "none", background: "none", fontSize: 14, width: "100%", color: INK }} />
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {chips.map((t) => {
              const on = tag === t;
              return <button key={t} onClick={() => setTag(t)} style={{ border: "none", cursor: "pointer", fontWeight: 600, fontSize: 13, padding: "8px 14px", borderRadius: 999, background: on ? GRAD : SOFT, color: on ? "#fff" : GRAY }}>{t}</button>;
            })}
          </div>
        </div>

        {explore.length > 0 ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(330px,1fr))", gap: 22 }}>
            {explore.map((g) => (<ExploreCard key={g.id} game={g} onOpen={() => router.push(`/games/${g.id}`)} onPlay={() => router.push(`/play/${g.id}`)} />))}
          </div>
        ) : (
          <div style={{ textAlign: "center", padding: "60px 20px", color: LIGHT, fontFamily: "'IBM Plex Mono'", fontSize: 14 }}>{gamesQ.isLoading ? "Loading games…" : "No games match."}</div>
        )}
      </section>

      {/* FROM IDEA TO PLAY */}
      <section id="how" style={{ maxWidth: 1200, margin: "0 auto", padding: "44px 28px 20px" }}>
        <h2 style={{ fontFamily: SG, fontSize: 24, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 22 }}>From Idea to Play</h2>
        <div style={{ display: "flex", gap: 10, alignItems: "stretch", flexWrap: "wrap" }}>
          {[
            { n: 1, ic: <IcChat />, t: "Describe", d: "Enter your game idea in plain language.", c: "#7c5cff" },
            { n: 2, ic: <IcUpload />, t: "Upload", d: "Add images, videos, or other assets.", c: "#5b8def" },
            { n: 3, ic: <IcSparkle />, t: "Generate", d: "AI agents build your game worlds and mechanics.", c: "#10b981" },
            { n: 4, ic: <IcPlay />, t: "Publish & Play", d: "Launch to the community instantly and enjoy!", c: "#f97316" },
          ].map((s, i, arr) => (
            <div key={s.n} style={{ display: "flex", alignItems: "center", gap: 10, flex: "1 1 220px" }}>
              <div style={{ flex: 1, background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 16, padding: 18 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <div style={{ width: 26, height: 26, borderRadius: "50%", background: s.c, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12.5, fontWeight: 700, fontFamily: SG }}>{s.n}</div>
                  <span style={{ color: s.c }}>{s.ic}</span>
                  <span style={{ fontFamily: SG, fontWeight: 700, fontSize: 15 }}>{s.t}</span>
                </div>
                <p style={{ fontSize: 13, color: GRAY, lineHeight: 1.5 }}>{s.d}</p>
              </div>
              {i < arr.length - 1 && <span style={{ color: "#cbd0e0", fontSize: 18 }}>→</span>}
            </div>
          ))}
        </div>
      </section>

      {/* FEATURE STRIP */}
      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "30px 28px 50px", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(230px,1fr))", gap: 26, borderTop: `1px solid ${BORDER}`, marginTop: 24 }}>
        {[
          { ic: <IcDb />, t: "Built for Creators", d: "Remote tunable AI agents that simplify game development." },
          { ic: <IcServer />, t: "Scalable Infrastructure", d: "Fast, reliable asset delivery & serverless game hosting." },
          { ic: <IcList />, t: "Agent Task Logs", d: "Transparent logs for every AI task and action taken." },
          { ic: <IcGlobe />, t: "Playable Everywhere", d: "Run games instantly in your browser. No installs." },
        ].map((f) => (
          <div key={f.t} style={{ display: "flex", gap: 12 }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, flex: "none", background: SOFT, border: `1px solid ${BORDER}`, display: "flex", alignItems: "center", justifyContent: "center", color: "#6d5efc" }}>{f.ic}</div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14.5, fontFamily: SG }}>{f.t}</div>
              <p style={{ fontSize: 12.5, color: GRAY, lineHeight: 1.5, marginTop: 3 }}>{f.d}</p>
            </div>
          </div>
        ))}
      </section>

      {/* FOOTER */}
      <footer style={{ borderTop: `1px solid ${BORDER}`, background: SOFT }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "40px 28px", display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr", gap: 30 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 10 }}>
              <svg width="26" height="26" viewBox="0 0 24 24"><defs><linearGradient id="fhx" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#7c5cff" /><stop offset="1" stopColor="#5b8def" /></linearGradient></defs><path d="M12 2l8.5 5v10L12 22l-8.5-5V7z" fill="url(#fhx)" /></svg>
              <span style={{ fontFamily: SG, fontWeight: 700, fontSize: 16 }}>PlayForge AI</span>
            </div>
            <p style={{ fontSize: 13, color: GRAY, lineHeight: 1.55, maxWidth: 240 }}>The AI-native platform for creating, sharing, and playing web games.</p>
          </div>
          <FooterCol title="Product" links={["Explore", "Create", "My Games"]} />
          <FooterCol title="Resources" links={["How It Works", "Blog", "Documentation"]} />
          <FooterCol title="Company" links={["About", "Careers", "Contact"]} />
        </div>
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "0 28px 28px", fontSize: 12.5, color: LIGHT, textAlign: "center" }}>© 2026 PlayForge AI. All rights reserved.</div>
      </footer>
    </div>
  );
}

function ExploreCard({ game, onOpen, onPlay }: { game: Game; onOpen: () => void; onPlay: () => void }) {
  return (
    <div onClick={onOpen} style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 16, overflow: "hidden", cursor: "pointer", boxShadow: "0 2px 10px rgba(40,40,90,.04)" }}>
      <div style={{ position: "relative", height: 150, background: game.cover }}>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 12, textAlign: "center" }}>
          <span style={{ fontFamily: SG, fontWeight: 700, fontSize: 17, color: "#fff", textShadow: "0 2px 10px rgba(0,0,0,.45)" }}>{game.title}</span>
        </div>
        {game.from_create && <span style={{ position: "absolute", top: 11, right: 11, fontFamily: "'IBM Plex Mono'", fontSize: 9.5, fontWeight: 600, color: "#16182e", background: "#ffd54a", padding: "3px 7px", borderRadius: 999 }}>✦ AI</span>}
        {game.status && game.status !== "published" && <span style={{ position: "absolute", top: 11, left: 11, fontFamily: "'IBM Plex Mono'", fontSize: 9.5, fontWeight: 600, color: "#fff", background: "rgba(0,0,0,.4)", padding: "3px 8px", borderRadius: 999 }}>{game.status === "preview" ? "预览" : "草稿"}</span>}
      </div>
      <div style={{ padding: "14px 16px 16px" }}>
        <div style={{ fontFamily: SG, fontWeight: 600, fontSize: 16.5, marginBottom: 3 }}>{game.title}</div>
        <div style={{ fontSize: 12.5, color: LIGHT, marginBottom: 9 }}>By {game.author}</div>
        <p style={{ fontSize: 13, color: GRAY, lineHeight: 1.45, marginBottom: 11, minHeight: 36 }}>{game.summary}</p>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 13 }}>
          {game.tags.slice(0, 3).map((t) => (<span key={t} style={chip("#6d5efc")}>{t}</span>))}
          <div style={{ flex: 1 }} />
          <button onClick={(e) => { e.stopPropagation(); onPlay(); }} style={{ border: `1px solid ${BORDER}`, background: "#fff", cursor: "pointer", color: "#6d5efc", fontWeight: 600, fontSize: 13, padding: "7px 14px", borderRadius: 9, display: "inline-flex", alignItems: "center", gap: 6 }}><IcPlay s={13} /> Play</button>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, paddingTop: 11, borderTop: `1px solid #f2f3f9`, fontSize: 12, color: LIGHT, fontFamily: "'IBM Plex Mono'" }}>
          <span>◷ {game.date}</span>
          <span>▶ {game.plays_str}</span>
        </div>
      </div>
    </div>
  );
}

function FooterCol({ title, links }: { title: string; links: string[] }) {
  return (
    <div>
      <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 12, color: INK }}>{title}</div>
      {links.map((l) => (<div key={l} style={{ fontSize: 13, color: GRAY, marginBottom: 9, cursor: "pointer" }}>{l}</div>))}
    </div>
  );
}
