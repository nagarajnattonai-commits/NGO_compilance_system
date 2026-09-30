import { expect, test } from "@playwright/test";

const headers = { "X-Setu-Request": "1" };
const credentials = { email: "phase19-portfolio@example.test", password: "Phase19-portfolio-QA-2026!" };

test("consultant portfolio shows only authorized clients and supports client-scoped invitations", async ({ page, request, context }) => {
  expect((await request.post("/api/v1/auth/signup", { headers, data: {
    name: "Portfolio Consultant", workspace_name: "Portfolio QA", ...credentials,
  } })).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login", { headers, data: credentials })).ok()).toBeTruthy();
  const createOrganization = async (name: string) => {
    const response = await request.post("/api/v1/organizations", { headers, data: {
      name, legal_type: "TRUST", registration_number: `${name}-${Date.now()}`,
      city: "Bengaluru", pan: "", fcra_active: false, generate_compliance_plan: false,
    } });
    expect(response.status()).toBe(201);
    return (await response.json()).organization as { id: string; name: string };
  };
  const first = await createOrganization("Asha Foundation");
  await createOrganization("Seva Trust");
  await context.addCookies((await request.storageState()).cookies);

  const dashboard = { summary: {
    organizations: 2, active_compliances: 4, overdue: 1, incomplete_tasks: 3,
    under_review: 1, organizations_requiring_attention: 1,
  } };
  const client = {
    id: first.id, name: first.name, legal_type: "TRUST", status: "ACTIVE", city: "Bengaluru",
    primary_contact: "", compliance_count: 4, overdue: 1, upcoming: 2, open_tasks: 3,
    expiring_documents: 1, expiring_registrations: 0, health: "ATTENTION",
    responsible_consultant: { id: "consultant", name: "Portfolio Consultant" },
    last_activity_at: "2026-09-30T08:00:00Z",
  };
  const task = {
    id: "task-19", organization_id: first.id, organization_name: first.name,
    compliance_id: "compliance-19", compliance: "Annual return", title: "Collect filing proof",
    status: "TODO", priority: "HIGH", assignee: "Portfolio Consultant", due_at: "2026-10-10", overdue: false,
  };
  const deadline = {
    id: "compliance-19", organization_id: first.id, organization_name: first.name,
    code: "AR-19", title: "Annual return", owner: "Portfolio Consultant", status: "IN_PROGRESS",
    priority: "HIGH", deadline: "2026-10-15", days_remaining: 15,
  };
  let invitation: Record<string, unknown> | null = null;
  await page.route("**/api/v1/portfolio/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/dashboard")) await route.fulfill({ json: dashboard });
    else if (path.endsWith("/organizations")) await route.fulfill({ json: { items: [client], total: 1 } });
    else if (path.endsWith("/work-queue")) await route.fulfill({ json: { items: [task], total: 1 } });
    else await route.fulfill({ json: { items: [deadline], total: 1 } });
  });
  await page.route("**/api/v1/admin/users/invite", async (route) => {
    invitation = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 201, json: { token: "private-test-token" } });
  });

  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Portfolio", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Client portfolio" })).toBeVisible();
  await expect(page.getByText("Asha Foundation", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Collect filing proof", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "AR-19 · Annual return" })).toBeVisible();

  const invite = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "Invite a client user" }) });
  await invite.getByLabel("Full name").fill("Client Viewer");
  await invite.getByLabel("Email address").fill("client-viewer@example.test");
  await invite.getByLabel("Organization").selectOption(first.id);
  await invite.getByRole("button", { name: "Create client invitation" }).click();
  await expect(page.getByText("Client invitation created.")).toBeVisible();
  expect(invitation).toMatchObject({ role: "VIEWER", organization_ids: [first.id] });

  await page.getByRole("button", { name: "Open client" }).click();
  await expect(page.locator(".org-switcher strong")).toHaveText("Asha Foundation");
});
