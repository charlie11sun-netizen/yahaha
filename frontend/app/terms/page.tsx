import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms of Service - PlayForge AI" };

export default function TermsPage() {
  return (
    <main className="pf-legal-page">
      <article className="pf-legal-card">
        <h1>Terms of Service</h1>
        <p className="pf-legal-updated">Last updated June 2026</p>
        <div className="pf-legal-content">
          <p>This is a demonstration project. By using PlayForge AI, you agree to the following terms.</p>
          <h2>Acceptable use</h2>
          <ul>
            <li>Do not submit prompts or assets that are illegal, harmful, or infringing.</li>
            <li>Do not attempt to abuse generation, scrape, or overload the service.</li>
            <li>Generated games run in a sandboxed iframe; you are responsible for content you publish.</li>
          </ul>
          <h2>Content ownership</h2>
          <p>You retain rights to ideas and assets you submit. Generated bundles are provided as-is.</p>
          <h2>No warranty</h2>
          <p>The platform is provided as-is without warranty. AI output may be inaccurate or fail to generate.</p>
        </div>
      </article>
    </main>
  );
}
