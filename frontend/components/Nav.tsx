"use client";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";

const GRAD = "linear-gradient(135deg,#7c5cff,#5b8def)";

function navLink(active: boolean): React.CSSProperties {
  return { border: "none", background: "none", cursor: "pointer", fontSize: 14.5, fontWeight: 500, color: active ? "#16182e" : "#6b7280", padding: "6px 4px" };
}
const gradBtn: React.CSSProperties = { border: "none", cursor: "pointer", background: GRAD, color: "#fff", fontWeight: 600, fontSize: 14, padding: "10px 18px", borderRadius: 10, boxShadow: "0 6px 16px rgba(124,92,255,.32)", whiteSpace: "nowrap" };

function Hexagon() {
  return (
    <svg width="30" height="30" viewBox="0 0 24 24" aria-hidden>
      <defs><linearGradient id="hx" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#7c5cff" /><stop offset="1" stopColor="#5b8def" /></linearGradient></defs>
      <path d="M12 2l8.5 5v10L12 22l-8.5-5V7z" fill="url(#hx)" />
      <path d="M12 7l4 2.4v4.8L12 16.6l-4-2.4V9.4z" fill="#fff" opacity=".9" />
    </svg>
  );
}

export default function Nav() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const goCreate = () => router.push(user ? "/create" : "/login?intent=create");

  return (
    <nav style={{ position: "sticky", top: 0, zIndex: 40, height: 66, display: "flex", alignItems: "center", gap: 24, padding: "0 32px", background: "rgba(255,255,255,.9)", backdropFilter: "blur(12px)", borderBottom: "1px solid #eef0f6" }}>
      <div onClick={() => router.push("/")} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", marginRight: 6 }}>
        <Hexagon />
        <span style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 18, letterSpacing: "-.01em", color: "#16182e" }}>PlayForge AI</span>
      </div>
      <button onClick={() => router.push("/")} style={navLink(path === "/")}>Explore</button>
      <button onClick={goCreate} style={navLink(path === "/create")}>Create</button>
      <button onClick={() => router.push(user ? "/me" : "/login")} style={navLink(path === "/me")}>My Games</button>
      <button onClick={() => router.push("/#how")} style={navLink(false)}>How It Works</button>
      <div style={{ flex: 1 }} />
      {user ? (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div onClick={() => router.push("/me")} title="个人主页" style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
            <span style={{ fontSize: 13.5, fontWeight: 600, color: "#16182e" }}>{user.name}</span>
            <div style={{ width: 32, height: 32, borderRadius: "50%", background: GRAD, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 13, fontFamily: "'Space Grotesk'" }}>{user.init}</div>
          </div>
          <button onClick={() => { logout(); router.push("/"); }} title="Sign out" style={{ border: "none", background: "none", cursor: "pointer", color: "#9ca3af", fontSize: 13 }}>Exit</button>
          <button onClick={goCreate} style={gradBtn}>✦ Start Creating</button>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={() => router.push("/login")} style={{ border: "1px solid #e3e5ef", background: "#fff", cursor: "pointer", fontWeight: 600, fontSize: 14, padding: "9px 18px", borderRadius: 10, color: "#16182e" }}>Log in</button>
          <button onClick={() => router.push("/login?mode=signup")} style={gradBtn}>✦ Start Creating</button>
        </div>
      )}
    </nav>
  );
}
