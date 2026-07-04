import { createHash } from "node:crypto";
import { expect, type Page, type APIRequestContext } from "@playwright/test";

export const apiBase = (process.env.E2E_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export function uniqueEmail(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}@e2e.test`;
}

export function gateHeaders() {
  const password = process.env.E2E_SITE_PASSWORD || process.env.SITE_PASSWORD || "";
  if (!password) return {};
  const token = createHash("sha256").update(`gameweave-gate:v1:${password}`).digest("hex");
  return { "X-Gate-Token": token };
}

export async function register(request: APIRequestContext, displayName = "E2E Player") {
  const email = uniqueEmail("player");
  const res = await request.post(`${apiBase}/auth/register`, {
    headers: gateHeaders(),
    data: { email, password: "secret1", display_name: displayName },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return { email, token: body.token as string, user: body.user };
}

export async function signInPage(page: Page, token: string) {
  await page.addInitScript((value) => window.localStorage.setItem("pf_token", value), token);
}

export async function firstPublishedGame(request: APIRequestContext) {
  const res = await request.get(`${apiBase}/games?limit=1`, { headers: gateHeaders() });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.items.length).toBeGreaterThan(0);
  return body.items[0] as { id: string; title: string };
}
