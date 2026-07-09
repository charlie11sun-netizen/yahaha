"use client";

import { StudioContent } from "./StudioContent";
import { StudioSidebar } from "./StudioSidebar";
import { StudioStats } from "./StudioStats";
import type { StudioController } from "../_lib/use-studio-controller";

export function StudioDashboard({ studio }: { studio: StudioController }) {
  const { drafts, published, router, section, switchSection, tasks, totalPlays, user } = studio;

  return (
    <main className="px-5 py-8 sm:px-8 lg:px-10">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8">
        <header>
          <h1 className="font-display text-4xl font-semibold tracking-normal text-slate-950 sm:text-5xl">My Studio</h1>
          <p className="mt-3 max-w-2xl text-base leading-7 text-slate-600">
            Manage your games, generation tasks, drafts, and account.
          </p>
        </header>

        <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
          <StudioSidebar
            onCreate={() => router.push("/create")}
            onEditProfile={() => switchSection("settings")}
            onSwitchSection={switchSection}
            section={section}
            user={user}
          />

          <section className="flex min-w-0 flex-col gap-6">
            <StudioStats
              draftCount={drafts.length}
              publishedCount={published.length}
              taskCount={tasks.length}
              totalPlays={totalPlays}
            />
            <StudioContent studio={studio} />
          </section>
        </div>
      </div>
    </main>
  );
}
