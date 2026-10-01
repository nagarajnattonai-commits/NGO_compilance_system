import { expect, test } from "@playwright/test";

test("production AI and OCR providers use the existing secure integration controls", async ({ page, request, context }) => {
  const credentials = { email: "phase23-providers@example.test", password: "Phase23-providers-QA-2026!" };
  const headers = { "X-Setu-Request": "1" };
  let login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Provider QA", workspace_name: "Provider QA", ...credentials,
    } })).status()).toBe(201);
    login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  }
  expect(login.ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);

  await page.route("**/api/v1/organizations", route => route.fulfill({ json: [] }));
  await page.route("**/api/v1/integrations-management/access", route => route.fulfill({ json: {
    platform_allowed: false,
    permissions: ["integrations.tenant.view", "integrations.tenant.manage", "integrations.credentials.rotate"],
    entitlements: { ai_rag: true, document_intelligence: true },
    secret_store_writable: true, categories: ["AI", "OCR"], scopes: [], event_types: [],
  } }));
  await page.route("**/api/v1/integrations-management/tenant/connections?*", route => route.fulfill({ json: {
    items: [{ id: "ocr-connection", tenant_id: "tenant-demo", organization_id: null,
      provider_key: "openai_responses_ocr", category: "OCR", scope: "TENANT",
      display_name: "Production OCR", configuration: {}, environment: "PRODUCTION",
      status: "CONNECTED", health: "OPERATIONAL", fallback_allowed: false,
      credential_suffix: "1234", credential_configured: true, failure_count: 0, error_code: "",
      last_tested_at: null, last_success_at: null, last_error_at: null, created_at: null, updated_at: null }],
    total: 1, page: 1,
  } }));
  await page.route("**/api/v1/integrations-management/tenant/providers", route => route.fulfill({ json: [
    { key: "openai_compatible", category: "AI", enabled: true, entitlement_key: "ai_rag",
      configuration_schema: { required: ["endpoint"], properties: {
        endpoint: { type: "string", default: "https://api.openai.com/v1" },
        generation_model: { type: "string", default: "gpt-4.1-mini" },
        embedding_dimensions: { type: "integer", default: 1536, minimum: 64, maximum: 8192 },
      } } },
    { key: "openai_responses_ocr", category: "OCR", enabled: true, entitlement_key: "document_intelligence",
      configuration_schema: { properties: { model: { type: "string", default: "gpt-4.1-mini" } } } },
  ] }));

  await page.goto("/settings/integrations");
  await expect(page.getByText("Production OCR")).toBeVisible();
  await expect(page.getByText("••••1234")).toBeVisible();
  await expect(page.getByText("rotated-ocr-secret")).toHaveCount(0);
  await page.getByRole("button", { name: "Add connection" }).click();
  await expect(page.getByLabel("Generation model")).toHaveValue("gpt-4.1-mini");
  await expect(page.getByLabel("Embedding dimensions")).toHaveAttribute("max", "8192");
  await page.getByLabel("Provider", { exact: true }).selectOption("openai_responses_ocr");
  await expect(page.getByLabel("OCR model")).toHaveValue("gpt-4.1-mini");
});
