import { expect, test } from "@playwright/test";
import { register, signInPage } from "./helpers";

test("switch a game back to an earlier version from Studio", async ({ page, request }) => {
  const auth = await register(request, "E2E Versioner");
  await signInPage(page, auth.token);

  await page.goto("/create");
  await page.getByLabel("Game idea").fill("A compact puzzle game with glowing tiles and a timer.");
  await page.getByRole("button", { name: "Generate Game" }).click();
  await expect(page.getByRole("button", { name: "Play Preview" })).toBeVisible({ timeout: 90_000 });

  await page.getByLabel("What should change?").fill("Make the game react faster, but keep the same core rules.");
  const firstTaskUrl = page.url();
  await page.getByRole("button", { name: "Apply feedback to this version" }).click();
  await expect(page).not.toHaveURL(firstTaskUrl);
  await expect(page.getByRole("button", { name: "Play Preview" })).toBeVisible({ timeout: 90_000 });

  await page.goto("/me?section=games");
  const versionsButton = page.getByRole("button", { name: "Versions", exact: true });
  await expect(versionsButton).toHaveCount(1);
  await versionsButton.click();
  await expect(page.getByRole("group", { name: "Version v2", exact: true })).toBeVisible();

  const v1Row = page.getByRole("group", { name: "Version v1", exact: true });
  await expect(v1Row).toBeVisible();
  await v1Row.getByRole("button", { name: "Activate" }).click();
  await expect(v1Row.getByRole("button", { name: "Current" })).toBeVisible();
});
