"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";

const ORANGE = "#ff6b35";
const inputStyle: React.CSSProperties = { width: "100%", border: "1px solid #e8e3d8", borderRadius: 11, padding: "12px 14px", fontSize: 14.5, outline: "none", background: "#fff" };
const oauthBtn: React.CSSProperties = { display: "flex", alignItems: "center", justifyContent: "center", gap: 10, border: "1px solid #e8e3d8", background: "#fff", cursor: "pointer", fontWeight: 600, fontSize: 14.5, padding: 12, borderRadius: 11, color: "#181613" };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 13 }}>
      <label style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: "#5c574e", marginBottom: 6 }}>{label}</label>
      {children}
    </div>
  );
}

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { setSession } = useAuth();
  const flash = useToast();

  const intent = params.get("intent");
  const [mode, setMode] = useState<"login" | "signup">(params.get("mode") === "signup" ? "signup" : "login");
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const isSignup = mode === "signup";

  const done = (token: string, user: { name: string }) => {
    setSession(token, user as never);
    flash(`Signed in as ${user.name}`);
    router.push(intent === "create" ? "/create" : "/");
  };

  const submit = async () => {
    setErr("");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return setErr("Enter a valid email address.");
    if (pass.length < 6) return setErr("Password must be at least 6 characters.");
    if (isSignup && !name.trim()) return setErr("Pick a display name.");
    try {
      const r = isSignup ? await api.register(email, pass, name.trim()) : await api.login(email, pass);
      done(r.token, r.user);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Something went wrong");
    }
  };

  const oauth = async (provider: string) => {
    try {
      const r = await api.oauthDemo(provider);
      setSession(r.token, r.user);
      flash(`Connected via ${provider} OAuth`);
      router.push(intent === "create" ? "/create" : "/");
    } catch {
      setErr("OAuth demo failed");
    }
  };

  return (
    <div style={{ flex: 1, display: "flex", alignItems: "stretch", minHeight: "calc(100vh - 64px)" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "52px 56px", background: "#181613", color: "#faf8f3", position: "relative", overflow: "hidden" }}>
        <div style={{ position: "absolute", width: 380, height: 380, borderRadius: "50%", background: "radial-gradient(circle,rgba(255,107,53,.5),transparent 68%)", top: -120, right: -100 }} />
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 11 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: ORANGE, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: 0, height: 0, borderLeft: "10px solid #181613", borderTop: "7px solid transparent", borderBottom: "7px solid transparent", marginLeft: 3 }} />
          </div>
          <span style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 20 }}>PlayForge</span>
        </div>
        <div style={{ position: "relative" }}>
          <h2 style={{ fontFamily: "'Space Grotesk'", fontSize: 38, fontWeight: 700, lineHeight: 1.1, letterSpacing: "-.02em", marginBottom: 16 }}>Where ideas<br />become arcades.</h2>
          <p style={{ fontSize: 16, color: "#b8b2a6", lineHeight: 1.55, maxWidth: 380 }}>Join thousands of creators turning prompts into playable games. No engine. No code. Just vibes.</p>
        </div>
        <div style={{ position: "relative", fontFamily: "'IBM Plex Mono'", fontSize: 12, color: "#6f6a60", letterSpacing: ".04em" }}>SESSION-BACKED · OAUTH-READY</div>
      </div>
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 24px" }}>
        <div style={{ width: "100%", maxWidth: 380 }}>
          <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 28, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 6 }}>{isSignup ? "Create your account" : "Welcome back"}</h1>
          <p style={{ fontSize: 14.5, color: "#7a756c", marginBottom: 26 }}>{isSignup ? "Start building games in minutes." : "Log in to create and publish."}</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 11, marginBottom: 18 }}>
            <button onClick={() => oauth("google")} style={oauthBtn}><span style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, color: "#4285F4" }}>G</span> Continue with Google</button>
            <button onClick={() => oauth("github")} style={oauthBtn}><span style={{ fontWeight: 700 }}>◐</span> Continue with GitHub</button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18 }}>
            <div style={{ flex: 1, height: 1, background: "#e8e3d8" }} />
            <span style={{ fontSize: 12, color: "#a8a294", fontFamily: "'IBM Plex Mono'" }}>OR EMAIL</span>
            <div style={{ flex: 1, height: 1, background: "#e8e3d8" }} />
          </div>
          {isSignup && (
            <Field label="Display name"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Lovelace" style={inputStyle} /></Field>
          )}
          <Field label="Email"><input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@studio.com" style={inputStyle} /></Field>
          <Field label="Password"><input value={pass} onChange={(e) => setPass(e.target.value)} type="password" placeholder="••••••••" style={inputStyle} /></Field>
          {err && <div style={{ fontSize: 13, color: "#e2483d", marginBottom: 8, fontWeight: 500 }}>{err}</div>}
          <button onClick={submit} style={{ width: "100%", border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 15.5, padding: 14, borderRadius: 11, marginTop: 8, boxShadow: "0 8px 20px rgba(255,107,53,.3)" }}>{isSignup ? "Create account" : "Log in"}</button>
          <div style={{ textAlign: "center", marginTop: 18, fontSize: 14, color: "#7a756c" }}>
            {isSignup ? "Already have an account? " : "New to PlayForge? "}
            <button onClick={() => { setMode(isSignup ? "login" : "signup"); setErr(""); }} style={{ border: "none", background: "none", cursor: "pointer", color: ORANGE, fontWeight: 600, fontSize: 14 }}>{isSignup ? "Log in" : "Create one"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
