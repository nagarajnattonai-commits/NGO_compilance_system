import { expect, test } from "@playwright/test";
import { provisionPlatformOperator } from "./platform-operator";

const headers = { "X-Setu-Request": "1" };
const credentials = { email: "white-label-qa@example.test", password: "WhiteLabel-browser-QA-2026!" };

test("organization assistant renders grounded sources, history and provider errors", async ({ page, request, context }) => {
  let login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Phase 17 QA", workspace_name: "Phase 17 QA", ...credentials,
    } })).status()).toBe(201);
    login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  }
  expect(login.ok()).toBeTruthy();
  const tenantId = (await (await request.get("/api/v1/auth/me")).json()).user.tenant_id as string;
  const organization = await request.post("/api/v1/organizations", { headers, data: {
    name: "Phase 17 Grounded NGO", legal_type: "TRUST", registration_number: `AI-${Date.now()}`,
    city: "Bengaluru", pan: "", fcra_active: false, generate_compliance_plan: false,
  } });
  expect(organization.status()).toBe(201);
  const organizationId = (await organization.json()).organization.id as string;
  await provisionPlatformOperator(request);
  expect((await request.put(`/api/v1/platform/subscriptions/${tenantId}`, { headers, data: {
    plan_name: "ENTERPRISE", status: "ACTIVE",
  } })).ok()).toBeTruthy();
  expect((await request.post("/api/v1/auth/logout", { headers })).status()).toBe(204);
  login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  expect(login.ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);

  let answered = false;
  const conversation = {
    id: "phase17-ui-conversation", organization_id: organizationId, title: "What is overdue?",
    status: "ACTIVE", created_at: "2026-09-30T08:00:00Z", updated_at: "2026-09-30T08:01:00Z",
  };
  const userMessage = {
    id: "phase17-user-message", conversation_id: conversation.id, role: "USER", content: "What is overdue?",
    structured_sources: [], document_sources: [], proposed_actions: [], insufficient_evidence: false,
    provider: "", model: "", created_at: "2026-09-30T08:00:00Z",
  };
  const assistantMessage = {
    id: "phase17-answer", conversation_id: conversation.id, role: "ASSISTANT", content: "Grounded advisory answer.",
    structured_sources: [{ type: "compliance", id: "compliance-17", label: "AI-17 — Annual filing",
      facts: { status: "OVERDUE", statutory_deadline: "2026-10-15" } }],
    document_sources: [{ type: "evidence", document_id: "document-17", document_name: "Filing proof",
      version_id: "version-17", version: 1, organization_id: organizationId, compliance_id: "compliance-17",
      chunk_index: 0, chunk_id: "chunk-17" }],
    proposed_actions: [{ type: "PROPOSED_ACTION", description: "Review the filing evidence.", executable: false }],
    insufficient_evidence: false, provider: "test", model: "grounded", created_at: "2026-09-30T08:01:00Z",
  };
  await page.route("**/api/v1/ai/conversations**", async (route) => {
    const requestUrl = new URL(route.request().url());
    const method = route.request().method();
    if (method === "POST" && requestUrl.pathname.endsWith("/messages")) {
      const payload = route.request().postDataJSON() as { question: string };
      if (payload.question === "Provider check") {
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({
          detail: { code: "AI_NOT_CONFIGURED", message: "AI services are not configured for this workspace." },
        }) });
      } else {
        answered = true;
        await route.fulfill({ status: 200, json: assistantMessage });
      }
    } else if (method === "POST" && requestUrl.pathname.endsWith("/ai/conversations")) {
      await route.fulfill({ status: 200, json: { ...conversation, messages: [] } });
    } else if (method === "GET" && requestUrl.pathname.endsWith(`/${conversation.id}`)) {
      await route.fulfill({ status: 200, json: { ...conversation, messages: answered ? [userMessage, assistantMessage] : [] } });
    } else {
      await route.fulfill({ status: 200, json: answered ? [conversation] : [] });
    }
  });

  await page.goto("/dashboard");
  await page.locator(".org-switcher").click();
  await page.locator(".org-menu").getByRole("button", { name: /Phase 17 Grounded NGO/ }).click();
  await page.getByRole("button", { name: "Assistant", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Compliance assistant" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Compliance AI assistant" }).getByText("Phase 17 Grounded NGO", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "What is overdue?", exact: true }).click();
  await expect(page.getByText("Grounded advisory answer.", { exact: true })).toBeVisible();
  await page.getByText("Platform records used (1)").click();
  await expect(page.getByText("AI-17 — Annual filing")).toBeVisible();
  await page.getByText("Document evidence (1)").click();
  await expect(page.getByRole("listitem").filter({ hasText: "Filing proof" })).toBeVisible();
  await expect(page.locator(".assistant-proposal")).toContainText("Review the filing evidence.");
  await expect(page.getByText("AI-generated explanation, not verified legal advice.")).toBeVisible();
  await expect(page.getByRole("button", { name: /What is overdue/ })).toBeVisible();

  await page.getByRole("button", { name: "New conversation" }).click();
  await page.getByLabel("Question for the compliance assistant").fill("Provider check");
  await page.getByRole("button", { name: "Ask assistant", exact: true }).click();
  await expect(page.locator(".assistant-main .form-error")).toHaveText("AI services are not configured for this workspace.");
});
