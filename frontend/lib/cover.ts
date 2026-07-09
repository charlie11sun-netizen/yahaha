import type { CSSProperties } from "react";

export const DEFAULT_COVER_BACKGROUND = "linear-gradient(135deg,#101844,#4f7dff)";
export const STUDIO_COVER_BACKGROUND = "linear-gradient(135deg, #101844, #4f7dff 52%, #8be8f1)";

function normalizedCover(cover?: string | null) {
  return cover?.trim() || "";
}

function cssUrl(source: string) {
  return `url("${source.replace(/"/g, '\\"')}")`;
}

export function coverImageSource(cover?: string | null) {
  const source = normalizedCover(cover);
  if (!source) return null;
  return source.startsWith("/") || source.startsWith("http://") || source.startsWith("https://") ? source : null;
}

export function coverBackgroundStyle(
  cover?: string | null,
  fallback: string = DEFAULT_COVER_BACKGROUND,
): CSSProperties {
  const source = normalizedCover(cover);
  if (!source) return { background: fallback };
  const imageSource = coverImageSource(source);
  return imageSource ? { backgroundImage: cssUrl(imageSource) } : { background: source };
}

export function coverBackgroundValue(cover?: string | null, fallback: string = DEFAULT_COVER_BACKGROUND) {
  const source = normalizedCover(cover);
  if (!source) return fallback;
  const imageSource = coverImageSource(source);
  return imageSource ? `${cssUrl(imageSource)} center / cover` : source;
}
