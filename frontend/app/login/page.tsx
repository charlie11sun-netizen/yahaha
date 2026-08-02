"use client";

import { AlertCircle, Box, Code2, Loader2, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { OAuthProviders, User } from "@/lib/types";

function Field({ children, label }: { children: ReactNode; label: string }) {
  return (
    <label className="grid gap-2 text-sm font-semibold text-slate-700">
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
  const rawNext = params.get("next");
  const next = rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : null;
  const postLoginTarget = next || (intent === "create" ? "/create" : "/explore");
  const [mode, setMode] = useState<"login" | "signup">(params.get("mode") === "signup" ? "signup" : "login");
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");
  const [providers, setProviders] = useState<OAuthProviders>({ _demo: false });
  const isSignup = mode === "signup";

  useEffect(() => {
    api.oauthProviders().then(setProviders).catch(() => setProviders({ _demo: false }));
  }, []);

  const done = (user: User) => {
    setSession(user);
    flash(`Signed in as ${user.name}`);
    router.push(postLoginTarget);
  };

  useEffect(() => {
    if (params.get("oauth") !== "success") return;
    api
      .me()
      .then((user) => {
        setSession(user);
        flash(`Signed in as ${user.name}`);
        router.replace(postLoginTarget);
      })
      .catch(() => {
        setErr("OAuth sign-in failed");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    if (submitting) return;
    setErr("");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return setErr("Enter a valid email address.");
    if (pass.length < 6) return setErr("Password must be at least 6 characters.");
    if (isSignup && !name.trim()) return setErr("Pick a display name.");
    setSubmitting(true);
    try {
      const result = isSignup ? await api.register(email, pass, name.trim()) : await api.login(email, pass);
      done(result.user);
    } catch (error) {
      setErr(error instanceof ApiError ? error.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const oauth = async (provider: string) => {
    if (providers[provider]) {
      window.location.href = api.oauthStartUrl(provider);
      return;
    }
    if (!providers._demo) {
      setErr(`${provider === "google" ? "Google" : "GitHub"} sign-in is not configured.`);
      return;
    }
    try {
      const result = await api.oauthDemo(provider);
      setSession(result.user);
      flash(`Connected via ${provider} OAuth (demo)`);
      router.push(intent === "create" ? "/create" : "/");
    } catch {
      setErr("OAuth demo failed");
    }
  };

  return (
    <main className="flex min-h-[calc(100vh-61px)] items-center justify-center px-5 py-12 sm:px-8 lg:px-10">
      <Card className="grid w-full max-w-5xl overflow-hidden rounded-lg border-slate-200/80 bg-white/95 py-0 shadow-2xl shadow-slate-900/10 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="flex min-h-[460px] flex-col justify-between bg-slate-950 p-7 text-white sm:p-10">
          <div className="space-y-10">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-lg bg-white text-indigo-600 shadow-lg shadow-indigo-500/20">
                <Box size={22} />
              </span>
              <strong className="font-display text-lg font-semibold tracking-normal">GameWeave AI</strong>
            </div>
            <div className="max-w-md space-y-4">
              <h1 className="font-display text-4xl font-semibold tracking-normal sm:text-5xl">
                {isSignup ? "Create your studio" : "Welcome back"}
              </h1>
              <p className="text-base leading-7 text-slate-300">
                Sign in to generate, publish, save, and tune browser games from one GameWeave workspace.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3 pt-10 text-sm font-semibold text-slate-100">
            <span className="inline-flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3 py-2">
              <Sparkles size={17} />
              Multi-agent generation
            </span>
            <span className="rounded-lg border border-white/15 bg-white/10 px-3 py-2">Sandboxed previews</span>
            <span className="rounded-lg border border-white/15 bg-white/10 px-3 py-2">One-click publishing</span>
          </div>
        </section>

        <CardContent className="px-6 py-8 sm:px-10 sm:py-10">
          <form
            className="mx-auto flex max-w-md flex-col gap-6"
            aria-label={isSignup ? "Create account" : "Log in"}
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="space-y-2">
              <h2 className="font-display text-3xl font-semibold tracking-normal text-slate-950">
                {isSignup ? "Create account" : "Log in"}
              </h2>
              <p className="text-sm leading-6 text-slate-600">
                {isSignup ? "Start building playable ideas in minutes." : "Continue to your GameWeave studio."}
              </p>
            </div>

            <div className="grid gap-3">
              <Button className="h-11 justify-start rounded-lg" onClick={() => void oauth("google")} type="button" variant="outline">
                <span className="flex size-6 items-center justify-center rounded-full bg-slate-950 text-xs font-bold text-white">G</span>
                Continue with Google
              </Button>
              <Button className="h-11 justify-start rounded-lg" onClick={() => void oauth("github")} type="button" variant="outline">
                <Code2 size={17} />
                Continue with GitHub
              </Button>
            </div>

            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-xs font-bold uppercase tracking-[0.18em] text-slate-400">
              <span className="h-px bg-slate-200" />
              OR EMAIL
              <span className="h-px bg-slate-200" />
            </div>

            <div className="grid gap-4">
              {isSignup ? (
                <Field label="Display name">
                  <Input onChange={(event) => setName(event.target.value)} placeholder="Ada Lovelace" value={name} />
                </Field>
              ) : null}
              <Field label="Email">
                <Input onChange={(event) => setEmail(event.target.value)} placeholder="you@studio.com" value={email} />
              </Field>
              <Field label="Password">
                <Input onChange={(event) => setPass(event.target.value)} placeholder="At least 6 characters" type="password" value={pass} />
              </Field>
            </div>

            {err ? (
              <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                {err}
              </div>
            ) : null}

            <Button className="h-11 rounded-lg" disabled={submitting} type="submit">
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Please wait..." : isSignup ? "Create account" : "Log in"}
            </Button>

            <div className="flex flex-wrap items-center justify-center gap-2 text-sm text-slate-600">
              {isSignup ? "Already have an account?" : "New to GameWeave?"}
              <Button
                className="h-auto px-0 py-0 font-semibold"
                onClick={() => {
                  setMode(isSignup ? "login" : "signup");
                  setErr("");
                }}
                type="button"
                variant="link"
              >
                {isSignup ? "Log in" : "Create one"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-[calc(100vh-61px)] items-center justify-center px-5 py-12">
          <Loader2 className="size-6 animate-spin text-indigo-600" />
        </main>
      }
    >
      <LoginInner />
    </Suspense>
  );
}
