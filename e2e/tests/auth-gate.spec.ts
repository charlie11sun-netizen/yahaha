import { expect, test } from "@playwright/test";
import { uniqueEmail } from "./helpers";

test("register, logout, and login", async ({ page }) => {
  const email = uniqueEmail("auth");

  await page.goto("/login?mode=signup");
  await page.getByLabel("Display name").fill("E2E Auth");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("secret1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/explore/);

  await page.getByRole("button", { name: "Exit" }).click();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("secret1");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/explore/);
});

test("unauthenticated create redirects to login", async ({ context, page }) => {
  await context.clearCookies();
  await page.goto("/create");
  await expect(page).toHaveURL(/\/login\?intent=create/);
});

test("password gate unlock flow", async ({ page }) => {
  const password = process.env.E2E_SITE_PASSWORD || process.env.SITE_PASSWORD;
  test.skip(!password, "SITE_PASSWORD is not configured for this run");

  await page.context().clearCookies();
  await page.goto("/create");
  await expect(page).toHaveURL(/\/gate/);
  await page.getByPlaceholder("Access password").fill(password!);
  await page.getByRole("button", { name: /unlock/i }).click();
  await expect(page).toHaveURL(/\/login\?intent=create/);
});
