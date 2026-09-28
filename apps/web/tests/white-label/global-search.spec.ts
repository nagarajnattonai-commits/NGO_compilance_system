import { expect, test } from "@playwright/test";

const headers = { "X-Setu-Request": "1" };
const credentials = {
  email: "phase13-search@example.test",
  password: "Phase13-search-QA-2026!",
};

test("global search exposes grouped results, advanced filters and saved views", async ({ page, request, context }) => {
  let login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Phase 13 QA", workspace_name: "Phase 13 QA", ...credentials,
    } })).status()).toBe(201);
    login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  }
  expect(login.ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
  await page.goto("/dashboard");

  const search = page.getByRole("search");
  await expect(search.getByLabel("Global search")).toBeVisible();
  await search.getByLabel("Global search").fill("compliance");
  await search.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("region", { name: "Search results" })).toBeVisible();
  await search.getByRole("button", { name: "Advanced filters" }).click();
  await expect(page.getByLabel("Document expiry")).toBeVisible();
  await expect(page.getByLabel("Applicability")).toBeVisible();

  const viewName = `Upcoming ${Date.now()}`;
  await page.getByLabel("View name").fill(viewName);
  await page.getByRole("checkbox", { name: "Default" }).check();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: `${viewName} · Default`, exact: true })).toBeVisible();
});
