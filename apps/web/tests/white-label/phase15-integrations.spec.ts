import { expect, test } from "@playwright/test";

test("integration scope and failed webhook delivery retry use the existing management UI", async ({ page, request, context }) => {
  const credentials = { email: "phase15-integrations@example.test", password: "Phase15-integrations-QA-2026!" };
  const headers = { "X-Setu-Request": "1" };
  let login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Integration QA", workspace_name: "Integration QA", ...credentials,
    } })).status()).toBe(201);
    login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  }
  expect(login.ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
  await page.route("**/api/v1/organizations", route => route.fulfill({ json: [{ id: "org-qa", name: "QA organization" }] }));
  await page.route("**/api/v1/integrations-management/access", route => route.fulfill({ json: {
    platform_allowed: false, permissions: ["integrations.tenant.view", "integrations.tenant.manage",
      "integrations.webhooks.manage", "integrations.logs.view"], entitlements: { custom_webhooks: true },
    secret_store_writable: true, categories: ["EMAIL"], scopes: [], event_types: ["task.created"],
  } }));
  await page.route("**/api/v1/integrations-management/tenant/connections?*", route => route.fulfill({ json: { items: [], total: 0 } }));
  await page.route("**/api/v1/integrations-management/tenant/providers", route => route.fulfill({ json: [{
    key: "smtp", category: "EMAIL", enabled: true, entitlement_key: "custom_email",
    configuration_schema: { properties: {}, required: [] },
  }] }));
  await page.goto("/settings/integrations");
  await page.getByRole("button", { name: "Add connection" }).click();
  await expect(page.getByLabel("Organization scope")).toBeVisible();
  await page.getByLabel("Organization scope").selectOption("org-qa");
  await expect(page.getByLabel("Organization scope")).toHaveValue("org-qa");

  let retried = false;
  await page.route("**/api/v1/developer/webhooks", route => route.fulfill({ json: [{ id: "hook-qa", name: "QA hook",
    direction: "OUTBOUND", endpoint_url: "https://hooks.example.org/events", organization_id: "org-qa",
    event_types: ["task.created"], enabled: true, inbound_path: null }] }));
  await page.route("**/api/v1/developer/webhooks/hook-qa/deliveries", route => route.fulfill({ json: [{
    id: "delivery-qa", event_id: "event-qa", event_type: "task.created", status: retried ? "QUEUED" : "FAILED",
    attempt_count: retried ? 0 : 5, error_code: "", response_status: null, last_attempt_at: null,
  }] }));
  await page.route("**/api/v1/developer/webhooks/hook-qa/deliveries/delivery-qa/retry", route => {
    retried = true;
    return route.fulfill({ status: 202, json: { id: "delivery-qa", status: "QUEUED" } });
  });
  await page.goto("/settings/developers/webhooks");
  await expect(page.getByText("QA organization")).toBeVisible();
  await page.getByRole("button", { name: "Deliveries" }).click();
  await page.getByRole("button", { name: "Retry delivery" }).click();
  await expect(page.getByText("Queued", { exact: true })).toBeVisible();
  expect(retried).toBeTruthy();
});
