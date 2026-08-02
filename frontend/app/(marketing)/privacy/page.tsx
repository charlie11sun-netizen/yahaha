import type { Metadata } from "next";

import { LegalPage } from "@/app/_components/LegalPage";

export const metadata: Metadata = { title: "Privacy Policy - GameWeave AI" };

export default function PrivacyPage() {
  return (
    <LegalShell title="Privacy Policy" updated="June 2026">
      <p>
        GameWeave AI is a demo platform for AI-generated web games. This page summarizes how the demo handles your data.
      </p>
      <h2>What we store</h2>
      <ul>
        <li>Account data: email, display name, hashed password, or linked OAuth account id.</li>
        <li>Content data: generated games, generation tasks, logs, and uploaded reference assets.</li>
        <li>Activity data: likes, favorites, comments, follows, play events, and scores.</li>
      </ul>
      <h2>How we use it</h2>
      <p>We use this data to authenticate users, run generation, show community content, and operate the platform.</p>
      <h2>Your controls</h2>
      <p>
        You can edit your profile, change your password, unpublish or delete games, and delete your account from Studio settings.
      </p>
      <h2>Third parties</h2>
      <p>Optional Google and GitHub OAuth can be used for sign-in. Game bundles are stored in S3-compatible object storage.</p>
    </LegalShell>
  );
}
const LegalShell = LegalPage;
