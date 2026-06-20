"use client";

import { Box, Code2, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="pf-auth-field">
      <span>{label}</span>
      {children}
    </label>
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
  const [providers, setProviders] = useState<Record<string, boolean>>({});
  const isSignup = mode === "signup";

  useEffect(() => {
    api.oauthProviders().then(setProviders).catch(() => setProviders({}));
  }, []);

  const done = (token: string, user: { name: string }) => {
    setSession(token, user as never);
    flash(`Signed in as ${user.name}`);
    router.push(intent === "create" ? "/create" : "/");
  };

  useEffect(() => {
    const token = params.get("token");
    if (!token) return;
    localStorage.setItem("pf_token", token);
    api
      .me()
      .then((user) => {
        setSession(token, user);
        flash(`Signed in as ${user.name}`);
        router.replace(intent === "create" ? "/create" : "/");
      })
      .catch(() => {
        localStorage.removeItem("pf_token");
        setErr("OAuth sign-in failed");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    setErr("");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return setErr("Enter a valid email address.");
    if (pass.length < 6) return setErr("Password must be at least 6 characters.");
    if (isSignup && !name.trim()) return setErr("Pick a display name.");
    try {
      const result = isSignup ? await api.register(email, pass, name.trim()) : await api.login(email, pass);
      done(result.token, result.user);
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : "Something went wrong");
    }
  };

  const oauth = async (provider: string) => {
    if (providers[provider]) {
      window.location.href = api.oauthStartUrl(provider);
      return;
    }
    try {
      const result = await api.oauthDemo(provider);
      setSession(result.token, result.user);
      flash(`Connected via ${provider} OAuth (demo)`);
      router.push(intent === "create" ? "/create" : "/");
    } catch {
      setErr("OAuth demo failed");
    }
  };

  return (
    <div className="pf-auth-page">
      <section className="pf-auth-panel">
        <div className="pf-auth-brand">
          <span>
            <Box size={22} />
          </span>
          <strong>PlayForge AI</strong>
        </div>
        <div className="pf-auth-copy">
          <h1>{isSignup ? "Create your studio" : "Welcome back"}</h1>
          <p>
            Sign in to generate, publish, save, and tune browser games from one PlayForge workspace.
          </p>
        </div>
        <div className="pf-auth-proof">
          <span>
            <Sparkles size={17} />
            Multi-agent generation
          </span>
          <span>Sandboxed previews</span>
          <span>One-click publishing</span>
        </div>
      </section>

      <section className="pf-auth-card" aria-label={isSignup ? "Create account" : "Log in"}>
        <h2>{isSignup ? "Create account" : "Log in"}</h2>
        <p>{isSignup ? "Start building playable ideas in minutes." : "Continue to your PlayForge studio."}</p>

        <div className="pf-auth-oauth">
          <button onClick={() => oauth("google")} type="button">
            <span>G</span>
            Continue with Google
          </button>
          <button onClick={() => oauth("github")} type="button">
            <Code2 size={17} />
            Continue with GitHub
          </button>
        </div>

        <div className="pf-auth-divider">
          <span />
          <em>OR EMAIL</em>
          <span />
        </div>

        {isSignup ? (
          <Field label="Display name">
            <input onChange={(event) => setName(event.target.value)} placeholder="Ada Lovelace" value={name} />
          </Field>
        ) : null}
        <Field label="Email">
          <input onChange={(event) => setEmail(event.target.value)} placeholder="you@studio.com" value={email} />
        </Field>
        <Field label="Password">
          <input onChange={(event) => setPass(event.target.value)} placeholder="At least 6 characters" type="password" value={pass} />
        </Field>

        {err ? <div className="pf-auth-error">{err}</div> : null}

        <button className="pf-auth-submit" onClick={submit} type="button">
          {isSignup ? "Create account" : "Log in"}
        </button>

        <div className="pf-auth-switch">
          {isSignup ? "Already have an account?" : "New to PlayForge?"}
          <button
            onClick={() => {
              setMode(isSignup ? "login" : "signup");
              setErr("");
            }}
            type="button"
          >
            {isSignup ? "Log in" : "Create one"}
          </button>
        </div>
      </section>
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
