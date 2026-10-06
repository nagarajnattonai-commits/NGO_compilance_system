import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { expect, test as base } from "@playwright/test";

const headers = { "X-Setu-Request": "1" };
type Workspace = { tenant: string; user: string; organization: string };
const test = base.extend<{ workspace: Workspace }>({
  workspace: async ({ request, context }, use) => {
    const marker = randomUUID();
    const credentials = { email: `workflow-${marker}@example.test`, password: "Workflow-browser-QA-2026!" };
    expect((await request.post("/api/v1/auth/signup", { headers, data: {
      name: "Workflow Administrator", workspace_name: "Workflow QA", ...credentials,
    } })).status()).toBe(201);
    expect((await request.post("/api/v1/auth/login", { headers, data: credentials })).ok()).toBeTruthy();
    const user = (await (await request.get("/api/v1/auth/me")).json()).user;
    const created = await request.post("/api/v1/organizations", { headers, data: {
      name: "Workflow NGO", legal_type: "TRUST", registration_number: marker, city: "Pune",
      pan: "", fcra_active: false, generate_compliance_plan: false,
    } });
    expect(created.status()).toBe(201);
    const organization = (await created.json()).organization.id as string;
    await context.addCookies((await request.storageState()).cookies);
    await use({ tenant: user.tenant_id, user: user.id, organization });
  },
});

function fixtureDatabase(tenant: string, statements: string[]) {
  const database = process.env.SETU_QA_DATABASE_URL;
  if (!database?.includes("setu-white-label-qa-")) throw new Error("Requires isolated QA database");
  const python = process.env.API_PYTHON || path.resolve(process.platform === "win32" ? "../api/.venv/Scripts/python.exe" : "../api/.venv/bin/python");
  execFileSync(python, ["-c", [
    "import sys", "from sqlalchemy import select, delete", "from app.database import SessionLocal",
    "from app.models import Subscription, IntegrationConnection", "tenant=sys.argv[1]",
    "with SessionLocal() as db:", ...statements.map(line => "    " + line), "    db.commit()",
  ].join("\n"), tenant], { cwd: path.resolve("../api"), env: { ...process.env, DATABASE_URL: database }, windowsHide: true });
}

test("legacy Connect directs to managed setup without attempting activation", async ({ page, workspace }) => {
  fixtureDatabase(workspace.tenant, ["db.add(IntegrationConnection(tenant_id=tenant,provider='Legacy SMTP',category='EMAIL',status='AVAILABLE',description='Legacy capability'))"]);
  let directActivation = false;
  page.on("request", request => { if (request.method() === "PATCH" && /\/api\/v1\/integrations\//.test(request.url())) directActivation = true; });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Integrations", exact: true }).click();
  const card = page.locator(".integration-grid article").filter({ has: page.getByRole("heading", { name: "Legacy SMTP" }) });
  await expect(card.getByRole("link", { name: "Connect", exact: true })).toHaveAttribute("href", "/settings/integrations");
  await card.getByRole("link", { name: "Connect", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/integrations$/);
  await expect(page.getByRole("button", { name: "Add connection", exact: true })).toBeVisible();
  expect(directActivation).toBe(false);
});

test("dashboard reminders use backend preferences and preserve other account options", async ({ page, request, workspace }) => {
  expect(workspace.organization).toBeTruthy();
  const original = { in_app_enabled: true, email_enabled: false, whatsapp_enabled: true,
    compliance_enabled: false, task_enabled: false, document_enabled: false, system_enabled: false };
  expect((await request.patch("/api/v1/notification-preferences", { headers, data: original })).ok()).toBeTruthy();
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const modal = page.getByRole("dialog");
  const reminders = modal.getByRole("checkbox", { name: /Compliance and deadline reminders/ });
  await expect(reminders).not.toBeChecked();
  await expect(modal.getByRole("checkbox", { name: /Weekly portfolio digest/ })).toBeDisabled();
  await reminders.check();
  await modal.getByRole("button", { name: "Save preferences" }).click();
  await expect(modal).not.toBeVisible();
  const saved = await (await request.get("/api/v1/notification-preferences")).json();
  for (const [key, value] of Object.entries(original)) expect(saved[key]).toBe(key === "compliance_enabled" ? true : value);
  // Saved browser values cannot override the backend on reload.
  await page.evaluate(() => localStorage.setItem("setu-workspace-preferences", JSON.stringify({ emailReminders: false, weeklyDigest: true, leadDays: 9 })));
  await page.reload();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("checkbox", { name: /Compliance and deadline reminders/ })).toBeChecked();
});

test("reminder load failure shows retry without allowing an unsourced save", async ({ page, workspace }) => {
  expect(workspace.organization).toBeTruthy();
  let serviceAvailable = false;
  await page.route("**/api/v1/notification-preferences", route => {
    // Keep the outage deterministic across Strict Mode's initial reads until retry.
    if (!serviceAvailable && route.request().method() === "GET") return route.fulfill({ status: 503, json: { detail: "Notification service is unavailable" } });
    return route.continue();
  });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const modal = page.getByRole("dialog");
  await expect(modal.getByRole("alert")).toHaveText("The server is unavailable. Please try again shortly.Try again");
  await expect(modal.getByRole("button", { name: "Save preferences" })).toBeDisabled();
  serviceAvailable = true;
  await modal.getByRole("button", { name: "Try again" }).click();
  await expect(modal.getByRole("button", { name: "Save preferences" })).toBeEnabled();
});

test("task and document search results open existing detail controls", async ({ page, request, workspace }) => {
  const taskTitle = "Navigation proof task", documentTitle = "Navigation proof document";
  expect((await request.post("/api/v1/tasks", { headers, data: { organization_id: workspace.organization,
    compliance_id: null, title: taskTitle, due_at: "2027-01-10", priority: "HIGH", assignee_user_id: workspace.user } })).status()).toBe(201);
  expect((await request.post("/api/v1/documents", { headers, data: { organization_id: workspace.organization,
    compliance_id: null, name: documentTitle, category: "Proof", file_type: "PDF", size_label: "1 KB", expiry_at: null, uploaded_by: "QA" } })).status()).toBe(201);
  for (const title of [taskTitle, documentTitle]) {
    await page.goto("/dashboard");
    await page.getByRole("search").getByLabel("Global search").fill(title);
    await page.getByRole("search").getByRole("button", { name: "Search", exact: true }).click();
    await page.getByRole("region", { name: "Search results" }).getByRole("link", { name: new RegExp(title) }).click();
    await expect(page.getByRole("dialog")).toContainText(title);
    await expect(page).toHaveURL(/\/dashboard\?view=(tasks|documents)&record=/);
  }
  await page.goto("/dashboard?view=tasks&record=unauthorized-record");
  await expect(page.getByRole("heading", { name: "Tasks and ownership", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("CSR search results select and focus authorized existing tabs and records", async ({ page, request, workspace }) => {
  fixtureDatabase(workspace.tenant, ["row=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant))", "row.plan_name='ENTERPRISE'"]);
  const partnerResponse = await request.post("/api/v1/csr/partners", { headers, data: { organization_id: workspace.organization, status: "PROSPECTIVE" } });
  expect(partnerResponse.status()).toBe(201);
  const partner = await partnerResponse.json();
  const projectResponse = await request.post("/api/v1/csr/projects", { headers, data: { relationship_id: partner.id, name: "Navigation CSR project", code: "NAV-CSR", status: "PLANNED", shared_with_ngo: true } });
  expect(projectResponse.status()).toBe(201);
  const project = await projectResponse.json();
  const templateResponse = await request.post("/api/v1/csr/checklist-templates", { headers, data: { name: "Navigation review", version: 1, enabled: true, items: [{ category: "Proof", title: "Navigation review evidence", requirement_type: "DOCUMENT", required: true, share_with_ngo: true }] } });
  expect(templateResponse.status()).toBe(201);
  const template = await templateResponse.json();
  const reviewResponse = await request.post("/api/v1/csr/reviews", { headers, data: { relationship_id: partner.id, template_id: template.id, title: "Navigation due diligence", shared_with_ngo: true } });
  expect(reviewResponse.status()).toBe(201);
  const review = await reviewResponse.json();
  for (const [type, title, id, tab] of [
    ["csr_partner", "Workflow NGO", partner.id, "Partners"],
    ["csr_project", "Navigation CSR project", project.id, "Projects"],
    ["due_diligence", "Navigation review evidence", review.items[0].id, "Due diligence"],
  ]) {
    await page.goto("/dashboard");
    await page.getByRole("search").getByLabel("Global search").fill(title);
    await page.getByRole("search").getByRole("button", { name: "Search", exact: true }).click();
    const result = page.getByRole("region", { name: "Search results" }).locator(`a[href*="type=${type}"]`);
    await result.click();
    await expect(page.locator(`#csr-record-${id}`)).toHaveAttribute("aria-current", "true");
    await expect(page.locator(`#csr-record-${id}`)).toBeFocused();
    await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
  }
});

test("import schema failures show safe errors and retry the existing import flow", async ({ page, workspace }) => {
  expect(workspace.organization).toBeTruthy();
  let schemaAvailable = false;
  await page.route("**/api/v1/imports/schema/ORGANIZATIONS", route => {
    if (!schemaAvailable) return route.fulfill({ status: 503, json: { detail: "Import schema is unavailable" } });
    return route.continue();
  });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Administration", exact: true }).click();
  const importer = page.getByRole("region", { name: "Bulk NGO onboarding and imports" });
  await expect(importer.getByRole("alert")).toHaveText("The server is unavailable. Please try again shortly.Try again");
  await importer.getByLabel("CSV or XLSX file").setInputFiles({ name: "organizations.csv", mimeType: "text/csv", buffer: Buffer.from(`name,legal_type,registration_number,city\nRetry NGO,TRUST,RETRY-${randomUUID()},Pune\n`) });
  await expect(importer.getByRole("button", { name: "Upload for review" })).toBeDisabled();
  schemaAvailable = true;
  await importer.getByRole("button", { name: "Try again" }).click();
  await expect(importer.getByRole("button", { name: "Upload for review" })).toBeEnabled();
  await importer.getByRole("button", { name: "Upload for review" }).click();
  await expect(importer.getByRole("button", { name: "Confirm Import" })).toBeDisabled();
  await importer.getByRole("button", { name: "Run dry validation" }).click();
  await expect(importer.getByRole("button", { name: "Confirm Import" })).toBeEnabled();
});

test("legacy tenants without a subscription load the workspace without paid entitlements", async ({ page, request, workspace }) => {
  fixtureDatabase(workspace.tenant, ["db.execute(delete(Subscription).where(Subscription.tenant_id==tenant))"]);
  const response = await request.get("/api/v1/subscription");
  expect(response.status()).toBe(200);
  const subscription = await response.json();
  expect(subscription.configured).toBe(false);
  expect(Object.values(subscription.feature_access).every(value => value === false)).toBe(true);
  await page.goto("/dashboard");
  await expect(page.getByRole("search").getByLabel("Global search")).toBeVisible();
  await page.getByRole("button", { name: "Subscription", exact: true }).click();
  await expect(page.getByText("Legacy workspace", { exact: true })).toBeVisible();
  await expect(page.getByText("Plan not assigned", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Unable to load workspace" })).toHaveCount(0);
});
