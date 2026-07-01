// Site-wide access gate helpers, shared by the Edge middleware and the Node
// route handler. Keep this file dependency-free and runtime-agnostic: it must
// run in BOTH runtimes, so it relies only on Web Crypto (globalThis.crypto),
// which is available in the Edge runtime and in Node 18+.

export const GATE_COOKIE = "pf_gate";
// JS-readable twin of the gate token. The page gate uses the httpOnly GATE_COOKIE;
// this one lets the API client read the token and forward it to the cross-origin
// backend as an X-Gate-Token header (cookies don't ride along cross-origin).
export const GATE_TOKEN_COOKIE = "pf_gate_token";

/**
 * The site access password, read at runtime from a server-only env var.
 * NEVER name this NEXT_PUBLIC_* — that would inline it into the client bundle.
 */
export function sitePassword(): string {
  return process.env.SITE_PASSWORD?.trim() ?? "";
}

/**
 * The gate is active only when a password is configured. With no password set
 * the site stays open — local dev is unaffected and you opt in per deployment.
 */
export function gateEnabled(): boolean {
  if (process.env.GAMEWEAVE_DISABLE_GATE === "1") return false;
  return sitePassword().length > 0;
}

/**
 * Opaque cookie value proving the holder knew the password, without ever
 * storing the password itself. SHA-256 is not reversible and the token is not
 * forgeable without knowing the secret, so a stolen cookie can't reveal it.
 */
export async function gateToken(password: string): Promise<string> {
  const data = new TextEncoder().encode(`gameweave-gate:v1:${password}`);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/** Length-aware constant-time compare, so matches don't leak via timing. */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
