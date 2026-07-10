import type { Metadata } from "next";

import { getPublicGame } from "@/lib/server-api";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const g = await getPublicGame(id);
    const images = typeof g.cover === "string" && (g.cover.startsWith("http") || g.cover.startsWith("/")) ? [g.cover] : [];
    return {
      title: `${g.title} · GameWeave AI`,
      description: g.summary,
      openGraph: { title: g.title, description: g.summary, images },
    };
  } catch {
    return { title: "Game · GameWeave AI" };
  }
}

export default function GameDetailLayout({ children }: { children: React.ReactNode }) {
  return children;
}
