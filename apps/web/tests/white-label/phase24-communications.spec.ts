import { expect, test } from "@playwright/test";

test("tenant communication operations show safe delivery state and permit an audited retry", async ({ page, request, context }) => {
  const headers = { "X-Setu-Request": "1" };
  const credentials = { email: "phase24-communications@example.test", password: "Phase24-communications-QA-2026!" };
  let login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Communication QA", workspace_name: "Communication QA", ...credentials,
    } })).status()).toBe(201);
    login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  }
  expect(login.ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);

  await page.route("**/api/v1/integrations-management/access", route => route.fulfill({ json: {
    platform_allowed: false,
    permissions: ["integrations.tenant.view", "integrations.tenant.manage"],
    entitlements: { custom_email: true, whatsapp_notifications: true },
    secret_store_writable: true, categories: ["COMMUNICATION"], scopes: [], event_types: [],
  } }));
  await page.route("**/api/v1/integrations-management/tenant/connections?*", route => route.fulfill({ json: {
    items: [], total: 0, page: 1,
  } }));
  await page.route("**/api/v1/integrations-management/tenant/providers", route => route.fulfill({ json: [] }));
  await page.route("**/api/v1/organizations", route => route.fulfill({ json: [] }));
  await page.route("**/api/v1/admin/notification-deliveries?*", route => route.fulfill({ json: [{
    id: "delivery-qa", notification_id: "notification-qa", user_id: "user-qa",
    channel: "WHATSAPP", recipient: "***9999", locale: "en-IN", template_key: "deadline_notice",
    status: "FAILED", attempt_count: 3, provider: "meta_whatsapp", provider_message_id: "wamid.qa",
    event: "compliance.deadline_approaching", next_retry_at: null, error_code: "PROVIDER_UNAVAILABLE",
    queued_at: "2026-10-01T08:00:00Z", sent_at: null, delivered_at: null, read_at: null,
    failed_at: "2026-10-01T08:01:00Z", created_at: "2026-10-01T08:00:00Z",
  }] }));
  let retried = false;
  await page.route("**/api/v1/admin/notification-deliveries/delivery-qa/retry", route => {
    retried = true;
    return route.fulfill({ status: 202, json: { status: "QUEUED" } });
  });

  await page.goto("/settings/integrations/deliveries");
  await expect(page.getByRole("heading", { name: /Delivery Operations/ })).toBeVisible();
  await expect(page.getByText("***9999")).toBeVisible();
  await expect(page.getByText(/provider is unavailable/i)).toBeVisible();
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect.poll(() => retried).toBeTruthy();
  await expect(page.getByRole("status")).toContainText("Delivery retry queued");
});
