import { expect, test } from "@playwright/test";
import { firstPublishedGame, register, signInPage } from "./helpers";

test("seed game iframe loads without error state", async ({ page, request }) => {
  const game = await firstPublishedGame(request);
  await page.goto(`/play/${game.id}`);

  await expect(page.getByRole("heading", { name: /could not load/i })).toHaveCount(0);
  await expect(page.locator("iframe")).toBeVisible();
  const frame = page.frameLocator("iframe").locator("body");
  await expect(frame).toBeVisible();
});

test("like and comment on a published game", async ({ page, request }) => {
  const auth = await register(request, "E2E Social");
  await signInPage(page, auth.token);
  const game = await firstPublishedGame(request);

  await page.goto(`/games/${game.id}`);
  await page.locator(".pf-detail-actions button").first().click();
  await page.getByPlaceholder("Add a comment...").fill("Great arcade loop from E2E.");
  await page.getByRole("button", { name: "Post" }).click();

  await expect(page.getByText("Great arcade loop from E2E.")).toBeVisible();
});
