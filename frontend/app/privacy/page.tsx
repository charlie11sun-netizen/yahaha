import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy Policy · PlayForge AI" };

export default function PrivacyPage() {
  return (
    <LegalShell title="Privacy Policy" updated="June 2026">
      <p>
        PlayForge AI is a demo platform for AI-generated web games. This page summarizes how the demo
        handles your data.
      </p>
      <h2>What we store</h2>
      <ul>
        <li>Account: email, display name, hashed password (bcrypt) or linked OAuth account id.</li>
        <li>Content: games you generate/publish, generation tasks and logs, uploaded reference assets.</li>
        <li>Activity: likes, favorites, comments, follows, play events and scores.</li>
      </ul>
      <h2>How we use it</h2>
      <p>Solely to operate the platform — authenticate you, run generation, and show community content.</p>
      <h2>Your controls</h2>
      <p>
        You can edit your profile, change your password, unpublish or delete games, and permanently
        delete your account (which removes your games, tasks and data) from your Studio settings.
      </p>
      <h2>Third parties</h2>
      <p>Optional Google / GitHub OAuth for sign-in. Object storage (S3-compatible) for game bundles.</p>
    </LegalShell>
  );
}

function LegalShell({ title, updated, children }: { title: string; updated: string; children: React.ReactNode }) {
  return (
    <div style={{ maxWidth: 760, width: "100%", margin: "0 auto", padding: "48px 28px 80px" }}>
      <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 34, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 6 }}>{title}</h1>
      <p style={{ fontFamily: "'IBM Plex Mono'", fontSize: 12.5, color: "#a8a294", marginBottom: 28 }}>Last updated {updated}</p>
      <div style={{ fontSize: 15, color: "#3a362f", lineHeight: 1.7 }}>{children}</div>
    </div>
  );
}
