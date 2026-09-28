import { expect, test } from "@playwright/test";
import { provisionPlatformOperator } from "./platform-operator";

const headers = { "X-Setu-Request": "1" };
const credentials = {
  email: "white-label-qa@example.test",
  password: "WhiteLabel-browser-QA-2026!",
};

test("platform plan assignment appears in the tenant subscription view with audit history", async ({ page, request, context }) => {
  let login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Subscription QA", workspace_name: "Subscription QA", ...credentials,
    } })).status()).toBe(201);
  }
  await provisionPlatformOperator(request);
  expect((await request.patch("/api/v1/localization/preferences", { headers, data: {
    locale: "en-IN", timezone: "Asia/Kolkata", time_format: "12h",
  } })).ok()).toBeTruthy();
  const tenantId = (await (await request.get("/api/v1/auth/me")).json()).user.tenant_id as string;
  await context.addCookies((await request.storageState()).cookies);

  await page.goto("/admin/subscriptions");
  const tenant = page.locator(".platform-subscription-row").filter({ hasText: tenantId });
  await expect(tenant).toBeVisible();
  await tenant.getByLabel("Plan").selectOption("BUSINESS");
  await tenant.getByRole("button", { name: "Save plan", exact: true }).click();
  await expect(tenant.getByLabel("Plan")).toHaveValue("BUSINESS");
  await tenant.getByText("Plan change history", { exact: true }).click();
  await expect(tenant).toContainText("BUSINESS");

  expect((await request.post("/api/v1/auth/logout", { headers })).status()).toBe(204);
  login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  expect(login.ok()).toBeTruthy();
  await context.clearCookies();
  await context.addCookies((await request.storageState()).cookies);
  await page.goto("/settings/subscription");
  await expect(page.getByRole("heading", { name: "Subscription and plan", exact: true })).toBeVisible();
  await expect(page.getByText("Business", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Plan change history", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
});
