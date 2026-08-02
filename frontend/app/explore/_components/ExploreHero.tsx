import { ArrowRight, Gamepad2, Sparkles } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ShowcaseCard } from "./ExplorePanels";
import { SHELL, flowSteps, type HomeGame } from "../_lib/explore-data";

export function ExploreHero({
  featured,
  trending,
}: {
  featured?: HomeGame;
  trending: HomeGame[];
}) {
  return (
    <section className={cn(SHELL, "grid items-center gap-12 pt-14 pb-10 lg:grid-cols-[0.92fr_1.08fr] lg:pt-20 lg:pb-16")}>
      <div className="[animation:pf-rise-in_0.6s_var(--pf-ease)_both]">
        <Badge variant="secondary" className="gap-1.5 rounded-full border border-violet-200/70 bg-white/70 px-3 py-1.5 text-violet-700 backdrop-blur">
          <Sparkles className="size-3.5" />
          AI-native game platform
        </Badge>
        <h1 className="mt-5 font-display text-[2.75rem] leading-[1.04] font-bold tracking-tight text-slate-950 sm:text-6xl">
          Turn any idea into a{" "}
          <span className="bg-gradient-to-r from-violet-600 via-indigo-500 to-blue-500 bg-clip-text text-transparent">
            playable AI game
          </span>
        </h1>
        <p className="mt-5 max-w-md text-[15px] leading-relaxed text-slate-600">
          Describe a game concept, upload assets, and let AI agents generate, package, and publish a
          playable experience in seconds.
        </p>

        <div className="mt-7 flex flex-wrap gap-3">
          <Button
            asChild
            size="lg"
            className="bg-gradient-to-r from-violet-600 to-blue-500 text-white shadow-lg shadow-violet-500/30 transition-all hover:-translate-y-0.5 hover:shadow-xl hover:shadow-violet-500/40"
          >
            <Link href="/create"><Sparkles className="size-4" />Create with AI</Link>
          </Button>
          <Button
            asChild
            size="lg"
            variant="outline"
            className="border-slate-200 bg-white/70 backdrop-blur transition-all hover:-translate-y-0.5"
          >
            <a href="#explore"><Gamepad2 className="size-4.5" />Explore Games</a>
          </Button>
        </div>

        <div className="mt-9 flex flex-wrap items-center gap-x-3 gap-y-4">
          {flowSteps.map((step, index) => (
            <div key={step.title} className="flex items-center gap-3">
              <div className="flex flex-col items-center gap-2 text-center">
                <div className={cn("flex size-12 items-center justify-center rounded-2xl bg-gradient-to-br text-white shadow-md", step.tint)}>
                  <step.icon className="size-5" />
                </div>
                <span className="text-xs font-semibold text-slate-700">
                  {index === flowSteps.length - 1 ? "Play" : step.title}
                </span>
              </div>
              {index < flowSteps.length - 1 && <ArrowRight className="size-4 text-slate-300" />}
            </div>
          ))}
        </div>
      </div>

      {featured ? (
        <ShowcaseCard featured={featured} trending={trending} />
      ) : (
        <div aria-hidden className="h-[420px] animate-pulse rounded-3xl border border-slate-200 bg-white/60" />
      )}
    </section>
  );
}
