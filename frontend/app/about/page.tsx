import type { Metadata } from "next";

export const metadata: Metadata = { title: "About · PlayForge AI" };

export default function AboutPage() {
  return (
    <div style={{ maxWidth: 760, width: "100%", margin: "0 auto", padding: "48px 28px 80px" }}>
      <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 34, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 14 }}>About PlayForge AI</h1>
      <div style={{ fontSize: 15.5, color: "#3a362f", lineHeight: 1.75 }}>
        <p>
          PlayForge AI is an AI-native platform for creating, sharing, and playing web games. Describe a
          game in natural language, optionally upload reference assets, and a multi-agent pipeline
          generates a playable bundle that is published to object storage and run in a sandboxed iframe.
        </p>
        <h2>How it works</h2>
        <ol>
          <li>Sign in (email or Google / GitHub).</li>
          <li>Describe your idea in the Create console and upload references.</li>
          <li>A LangGraph pipeline plans → designs → codes → validates the game, with live logs.</li>
          <li>Preview, then publish to the home feed for the community to play.</li>
        </ol>
        <h2>Tech</h2>
        <p>Next.js + React frontend · FastAPI + Celery + LangGraph backend · PostgreSQL · Redis · S3-compatible object storage (MinIO) · Docker Compose.</p>
      </div>
    </div>
  );
}
