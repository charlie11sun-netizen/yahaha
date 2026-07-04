import type { FullConfig } from "@playwright/test";

async function waitForReady(url: string) {
  const deadline = Date.now() + 120_000;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
      lastError = `${res.status} ${res.statusText}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError}`);
}

export default async function globalSetup(_config: FullConfig) {
  const apiBase = process.env.E2E_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  await waitForReady(`${apiBase.replace(/\/$/, "")}/health/ready`);
}
