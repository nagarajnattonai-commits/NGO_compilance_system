import { expect, test } from "@playwright/test";
import { provisionPlatformOperator } from "./platform-operator";

const headers = { "X-Setu-Request": "1" };
const credentials = { email: "white-label-qa@example.test", password: "WhiteLabel-browser-QA-2026!" };

test("workspace admin creates and edits a structured automation workflow", async ({ page, request, context }) => {
  let login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Phase 14 QA", workspace_name: "Phase 14 QA", ...credentials,
    } })).status()).toBe(201);
    login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  }
  expect(login.ok()).toBeTruthy();
  const tenantId = (await (await request.get("/api/v1/auth/me")).json()).user.tenant_id as string;
  await provisionPlatformOperator(request);
  expect((await request.put(`/api/v1/platform/subscriptions/${tenantId}`, { headers, data: {
    plan_name: "BUSINESS", status: "ACTIVE",
  } })).ok()).toBeTruthy();
  expect((await request.post("/api/v1/auth/logout", { headers })).status()).toBe(204);
  login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  expect(login.ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Integrations", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Workflow automation", exact: true })).toBeVisible();
  await page.locator(".workflow-form").getByRole("textbox", { name: "Name", exact: true }).fill(`Deadline workflow ${Date.now()}`);
  await page.getByLabel("Trigger").selectOption("DEADLINE_APPROACHING");
  await page.getByLabel("Notification title").fill("Deadline approaching");
  await page.getByLabel("Message").fill("Please prepare the filing evidence.");
  await page.getByRole("button", { name: "Save workflow", exact: true }).click();
  await expect(page.locator(".workflow-list")).toContainText("Deadline workflow");
  await page.locator(".workflow-list article").first().locator("button").first().click();
  await page.getByLabel("Description").fill("Updated safely");
  await page.getByRole("button", { name: "Save workflow", exact: true }).click();
  await expect(page.locator(".workflow-list")).toContainText("Deadline workflow");
});
