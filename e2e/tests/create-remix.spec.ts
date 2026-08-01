import { expect, test } from "@playwright/test";
import { firstPublishedGame, holdAuthHydration, register, signInPage } from "./helpers";

test("create mock pipeline to preview and publish", async ({ page, request }) => {
  test.setTimeout(120_000);
  const auth = await register(request, "E2E Creator");
  await signInPage(page, auth.session);

  await page.goto("/create");
  await page.getByLabel("Game idea").fill("A neon lane runner with coins, drones, and a 45 second survival goal.");
  await page.getByRole("button", { name: "Start building", exact: true }).click();

  await expect(page).toHaveURL(/\/create\?task=/);
  await expect(page.getByRole("button", { name: "Play Preview" })).toBeVisible({ timeout: 90_000 });
  const previewPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Play Preview" }).click();
  const preview = await previewPromise;
  await expect(preview.locator("iframe")).toBeVisible({ timeout: 30_000 });
  await preview.close();

  await page.bringToFront();
  await page.getByRole("button", { name: "Publish to Home" }).click();
  await expect(page).toHaveURL(/\/explore/);
  await expect(page.getByText(/published$/)).toBeVisible();
});

test("detail remix button opens a prefilled create flow", async ({ page, request }) => {
  const auth = await register(request, "E2E Remixer");
  await signInPage(page, auth.session);
  const source = await firstPublishedGame(request);
  const releaseAuth = await holdAuthHydration(page);

  await page.goto(`/games/${source.id}`);
  const remixButton = page.getByRole("button", { name: "Remix", exact: true });
  await expect(remixButton).toBeDisabled();
  releaseAuth();
  await remixButton.click();
  await expect(page).toHaveURL(new RegExp(`/create\\?remix=${source.id}`));
  await expect(page.getByRole("heading", { name: `Remix ${source.title}` })).toBeVisible();
  await expect(page.getByLabel("Game idea")).toHaveValue(/Remix/);
  expect(await page.getByLabel("Game idea").inputValue()).toContain(source.title);
});
