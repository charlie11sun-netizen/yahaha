"use client";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";

const ORANGE = "#ff6b35";

function navLink(color: string): React.CSSProperties {
  return { border: "none", background: "none", cursor: "pointer", fontSize: 14.5, fontWeight: 600, color, padding: "6px 4px" };
}

export default function Nav() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const goCreate = () => router.push(user ? "/create" : "/login?intent=create");

  return (
    <nav
      style={{
        position: "sticky", top: 0, zIndex: 40, height: 64, display: "flex", alignItems: "center", gap: 24,
        padding: "0 28px", background: "rgba(250,248,243,.85)", backdropFilter: "blur(12px)",
        borderBottom: "1px solid #e8e3d8",
      }}
    >
      <div onClick={() => router.push("/")} style={{ display: "flex", alignItems: "center", gap: 11, cursor: "pointer", marginRight: 6 }}>
        <div style={{ width: 32, height: 32, borderRadius: 9, background: ORANGE, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 4px 12px rgba(255,107,53,.35)" }}>
          <div style={{ width: 0, height: 0, borderLeft: "9px solid #181613", borderTop: "6px solid transparent", borderBottom: "6px solid transparent", marginLeft: 3 }} />
        </div>
        <span style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 19, letterSpacing: "-.02em" }}>PlayForge</span>
      </div>
      <button onClick={() => router.push("/")} style={navLink(path === "/" ? "#181613" : "#7a756c")}>Explore</button>
      <button onClick={goCreate} style={navLink(path === "/create" ? "#181613" : "#7a756c")}>Create</button>
      <div style={{ flex: 1 }} />
      {user ? (
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <button onClick={goCreate} style={{ border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 600, fontSize: 14, padding: "9px 16px", borderRadius: 10, boxShadow: "0 4px 12px rgba(255,107,53,.3)", whiteSpace: "nowrap" }}>+ New game</button>
          <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "4px 4px 4px 12px", border: "1px solid #e8e3d8", borderRadius: 999, background: "#fff" }}>
            <div onClick={() => router.push("/me")} title="个人主页" style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
              <span style={{ fontSize: 13.5, fontWeight: 600 }}>{user.name}</span>
              <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#181613", color: "#faf8f3", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 13, fontFamily: "'Space Grotesk'" }}>{user.init}</div>
            </div>
            <button onClick={() => { logout(); router.push("/"); }} title="Sign out" style={{ border: "none", background: "none", cursor: "pointer", color: "#7a756c", fontSize: 13, padding: "0 6px 0 2px" }}>Exit</button>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button onClick={() => router.push("/login")} style={{ border: "1px solid #e8e3d8", background: "#fff", cursor: "pointer", fontWeight: 600, fontSize: 14, padding: "9px 16px", borderRadius: 10, color: "#181613" }}>Log in</button>
          <button onClick={() => router.push("/login?mode=signup")} style={{ border: "none", cursor: "pointer", background: "#181613", color: "#faf8f3", fontWeight: 600, fontSize: 14, padding: "9px 16px", borderRadius: 10 }}>Sign up</button>
        </div>
      )}
    </nav>
  );
}
