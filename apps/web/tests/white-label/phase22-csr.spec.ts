import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test } from "@playwright/test";

const headers = { "X-Setu-Request": "1" };
const credentials = { email: "phase22-csr@example.test", password: "Phase22-csr-QA-2026!" };

test("CSR partner workspace supports partner, project and due-diligence operations", async ({ page, request, context }) => {
  expect((await request.post("/api/v1/auth/signup", { headers, data: {
    name: "CSR Administrator", workspace_name: "CSR QA", ...credentials,
  } })).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login", { headers, data: credentials })).ok()).toBeTruthy();
  const tenantId = (await (await request.get("/api/v1/auth/me")).json()).user.tenant_id as string;
  const organizationResponse = await request.post("/api/v1/organizations", { headers, data: {
    name: "Saksham Foundation", legal_type: "TRUST", registration_number: `CSR-${Date.now()}`,
    city: "Pune", pan: "", fcra_active: false, generate_compliance_plan: false,
  } });
  const organization = (await organizationResponse.json()).organization as { id:string; name:string };

  const database = process.env.SETU_QA_DATABASE_URL;
  if (!database?.includes("setu-white-label-qa-")) throw new Error("CSR QA requires an isolated database");
  const python = process.env.API_PYTHON || path.resolve(process.platform === "win32" ? "../api/.venv/Scripts/python.exe" : "../api/.venv/bin/python");
  const script = [
    "from sqlalchemy import select", "from app.database import SessionLocal",
    "from app.models import Subscription", "with SessionLocal() as db:",
    `    row=db.scalar(select(Subscription).where(Subscription.tenant_id=='${tenantId}'))`,
    "    row.plan_name='ENTERPRISE'", "    db.commit()",
  ].join("\n");
  execFileSync(python, ["-c", script], { cwd:path.resolve("../api"), env:{...process.env,DATABASE_URL:database}, windowsHide:true });
  await context.addCookies((await request.storageState()).cookies);

  const partners: Array<Record<string,unknown>> = [];
  const projects: Array<Record<string,unknown>> = [];
  const templates: Array<Record<string,unknown>> = [];
  const reviews: Array<Record<string,unknown>> = [];
  await page.route("**/api/v1/csr/**", async route => {
    const url = new URL(route.request().url()), method = route.request().method();
    const data = route.request().postDataJSON() as Record<string,unknown> | null;
    if (url.pathname.endsWith("/dashboard")) return route.fulfill({json:{summary:{total_partners:partners.length,active_projects:projects.length,incomplete_due_diligence:reviews.length,partners_requiring_attention:0},partners}});
    if (url.pathname.endsWith("/partners")) {
      if (method === "POST") partners.push({id:"partner-1",organization_id:organization.id,organization_name:organization.name,status:"PROSPECTIVE",review_status:"NOT_STARTED",profile_completeness:60,active_projects:0,open_reviews:0,requires_attention:false});
      return route.fulfill({status:method === "POST" ? 201 : 200,json:method === "POST" ? partners[0] : partners});
    }
    if (url.pathname.endsWith("/projects")) {
      if (method === "POST") projects.push({id:"project-1",...data,status:"PLANNED"});
      return route.fulfill({status:method === "POST" ? 201 : 200,json:method === "POST" ? projects[0] : projects});
    }
    if (url.pathname.endsWith("/checklist-templates")) {
      if (method === "POST") templates.push({id:"template-1",...data});
      return route.fulfill({status:method === "POST" ? 201 : 200,json:method === "POST" ? templates[0] : templates});
    }
    if (url.pathname.endsWith("/reviews")) {
      if (method === "POST") reviews.push({id:"review-1",...data,status:"NOT_STARTED",items:[{id:"item-1",title:"Registration evidence",status:"NOT_STARTED",response:"",evidence:[]}],disclaimer:"Operational due diligence status"});
      return route.fulfill({status:method === "POST" ? 201 : 200,json:method === "POST" ? reviews[0] : reviews});
    }
    return route.fulfill({status:404,json:{detail:"Not found"}});
  });

  await page.goto("/dashboard");
  await page.getByRole("button", {name:"CSR partners", exact:true}).click();
  await expect(page.getByRole("heading", {name:"NGO partner management"})).toBeVisible();
  await expect(page.getByText("Statuses support operational review and do not constitute legal compliance certification.")).toBeVisible();
  await page.getByRole("button", {name:"Add NGO partner"}).click();
  await expect(page.getByText("Saksham Foundation", {exact:true})).toBeVisible();
  await page.getByRole("tab", {name:"Projects"}).click();
  await page.getByLabel("Project name").fill("Education programme");
  await page.getByLabel("Project code").fill("EDU-01");
  await page.getByRole("button", {name:"Create project"}).click();
  await expect(page.getByText("Education programme", {exact:true})).toBeVisible();
  await page.getByRole("tab", {name:"Checklist templates"}).click();
  await page.getByLabel("Template name").fill("Partner onboarding");
  await page.getByLabel("Category").fill("Registration");
  await page.getByLabel("Requirement").fill("Registration evidence");
  await page.getByRole("button", {name:"Create template"}).click();
  await expect(page.getByText(/Partner onboarding/)).toBeVisible();
  await page.getByRole("tab", {name:"Due diligence"}).click();
  await page.getByLabel("Review title").fill("Initial due diligence");
  await page.getByRole("button", {name:"Start review"}).click();
  await expect(page.getByRole("heading", {name:"Initial due diligence"})).toBeVisible();
});
