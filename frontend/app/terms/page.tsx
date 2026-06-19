import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms of Service · PlayForge AI" };

export default function TermsPage() {
  return (
    <div style={{ maxWidth: 760, width: "100%", margin: "0 auto", padding: "48px 28px 80px" }}>
      <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 34, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 6 }}>Terms of Service</h1>
      <p style={{ fontFamily: "'IBM Plex Mono'", fontSize: 12.5, color: "#a8a294", marginBottom: 28 }}>Last updated June 2026</p>
      <div style={{ fontSize: 15, color: "#3a362f", lineHeight: 1.7 }}>
        <p>This is a demonstration project. By using PlayForge AI you agree to the following.</p>
        <h2>Acceptable use</h2>
        <ul>
          <li>Do not submit prompts or assets that are illegal, harmful, or infringing.</li>
          <li>Do not attempt to abuse generation, scrape, or overload the service.</li>
          <li>Generated games run in a sandboxed iframe; you are responsible for content you publish.</li>
        </ul>
        <h2>Content ownership</h2>
        <p>You retain rights to ideas and assets you submit. Generated bundles are provided as-is.</p>
        <h2>No warranty</h2>
        <p>The platform is provided “as is” without warranty. AI output may be inaccurate or fail to generate.</p>
      </div>
    </div>
  );
}
