import type { Metadata } from "next";

import { BASE } from "@/lib/api";

// 单游戏 SEO/OG：服务端按 id 取 meta 生成动态标题/描述/OG 图。
// 注：docker 下 web 容器服务端访问 BASE(localhost) 可能不通，已 try/catch 优雅降级。
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const res = await fetch(`${BASE}/games/${id}`, { cache: "no-store" });
    if (!res.ok) return { title: "Game · GameWeave AI" };
    const g = await res.json();
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
