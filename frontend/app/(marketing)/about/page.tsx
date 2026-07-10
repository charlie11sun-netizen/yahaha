import type { Metadata } from "next";

import { LegalPage } from "@/app/_components/LegalPage";

export const metadata: Metadata = { title: "About - GameWeave AI" };

export default function AboutPage() {
  return (
    <LegalPage
      title="About GameWeave AI"
      lead="GameWeave AI is an AI-native platform for creating, sharing, and playing web games from natural language."
    >
      <section>
        <h2>How it works</h2>
        <ol>
          <li>Sign in with email, Google, or GitHub.</li>
          <li>Describe your game idea in the Create console and upload references.</li>
          <li>A multi-agent pipeline expands, plans, designs, codes, validates, and packages the game.</li>
          <li>Preview the sandboxed result, then publish it to the community feed.</li>
        </ol>
      </section>
      <section>
        <h2>Tech</h2>
        <p>
          Next.js and React frontend, FastAPI backend, Celery workers, LangGraph-style agent orchestration,
          PostgreSQL, Redis, S3-compatible object storage, and sandboxed browser previews.
        </p>
      </section>
    </LegalPage>
  );
}
