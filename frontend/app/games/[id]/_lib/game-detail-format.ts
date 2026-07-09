import type { CSSProperties } from "react";

export function coverBackground(cover?: string | null): CSSProperties {
  if (!cover) return { background: "linear-gradient(135deg,#101844,#4f7dff)" };
  if (cover.startsWith("/") || cover.startsWith("http://") || cover.startsWith("https://")) {
    return { backgroundImage: `url("${cover}")` };
  }
  return { background: cover };
}
