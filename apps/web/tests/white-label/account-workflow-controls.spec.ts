import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { expect, request as browserRequest, test as base, type Page } from "@playwright/test";

const headers={"X-Setu-Request":"1"};
type Workspace={org:string;otherOrg:string;user:string;credentials:{email:string;password:string}};
const test=base.extend<{workspace:Workspace}>({workspace:async({request,context},use)=>{
  const marker=randomUUID(),credentials={email:`controls-${marker}@example.test`,password:"Controls-browser-QA-2026!"};
  expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"Controls Admin",workspace_name:"Controls QA",...credentials}})).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login",{headers,data:credentials})).ok()).toBeTruthy();
  const user=(await(await request.get("/api/v1/auth/me")).json()).user;
  const database=process.env.SETU_QA_DATABASE_URL;
  if(!database?.includes("setu-white-label-qa-")) throw new Error("Requires isolated controls QA database");
  const python=process.env.API_PYTHON||path.resolve(process.platform==="win32"?"../api/.venv/Scripts/python.exe":"../api/.venv/bin/python");
  execFileSync(python,["-c",["import sys","from sqlalchemy import select","from app.database import SessionLocal","from app.models import Subscription",
    "with SessionLocal() as db:","    db.scalar(select(Subscription).where(Subscription.tenant_id==sys.argv[1])).plan_name='BUSINESS'","    db.commit()"].join("\n"),user.tenant_id],{cwd:path.resolve("../api"),env:{...process.env,DATABASE_URL:database},windowsHide:true});
  async function create(resource:string,data:unknown){const response=await request.post(`/api/v1/${resource}`,{headers,data});expect(response.status(),await response.text()).toBe(201);return response.json();}
  const org=(await create("organizations",{name:"Controls NGO",legal_type:"TRUST",registration_number:marker,city:"Pune",generate_compliance_plan:false})).organization.id;
  const otherOrg=(await create("organizations",{name:"Other Controls NGO",legal_type:"TRUST",registration_number:`other-${marker}`,city:"Pune",generate_compliance_plan:false})).organization.id;
  for(const [organization_id,title] of [[org,"Controls compliance"],[otherOrg,"Other controls compliance"]]) await create("compliances",{organization_id,title,code:`CONTROL-${randomUUID().slice(0,8)}`,category:"Annual",period:"2026-27",statutory_deadline:"2030-01-01",owner_name:"Controls owner"});
  await create("tasks",{organization_id:org,title:"Controls task",due_at:"2030-01-01",assignee_user_id:user.id});
  await context.addCookies((await request.storageState()).cookies);await use({org,otherOrg,user:user.id,credentials});
}});
async function open(page:Page,name:string){await page.goto("/dashboard");await page.getByRole("button",{name,exact:true}).click();}

test("Account security lists redacted sessions, confirms revocation and recovers read failures",async({page,request,workspace})=>{
  const other=await browserRequest.newContext({baseURL:"http://localhost:3001"});
  try {
  expect((await other.post("/api/v1/auth/login",{headers,data:workspace.credentials})).ok()).toBeTruthy();
  expect(workspace.org).toBeTruthy();await page.goto("/account");const security=page.getByRole("region",{name:"Account security",exact:true});
  await expect(security.getByText("Current session",{exact:true})).toBeVisible();
  const initial=await(await request.get("/api/v1/auth/sessions")).json();expect(initial).toHaveLength(2);
  for(const session of initial) await expect(security).not.toContainText(session.id);
  page.once("dialog",dialog=>dialog.dismiss());await security.getByRole("button",{name:"Revoke session",exact:true}).click();
  expect(await(await request.get("/api/v1/auth/sessions")).json()).toHaveLength(2);
  await page.route("**/api/v1/auth/security-events",route=>route.fulfill({status:503,json:{detail:"Temporary security read failure"}}));
  await security.getByRole("button",{name:"Refresh security activity",exact:true}).click();
  await expect(security.getByRole("alert")).toHaveText("The server is unavailable. Please try again shortly.");
  await page.unroute("**/api/v1/auth/security-events");await security.getByRole("button",{name:"Refresh security activity",exact:true}).click();
  await expect(security.getByRole("button",{name:"Revoke session",exact:true})).toBeVisible();
  page.once("dialog",dialog=>dialog.accept());await security.getByRole("button",{name:"Revoke session",exact:true}).click();
  await expect(security.getByRole("button",{name:"Revoke session",exact:true})).toHaveCount(0);
  expect(await(await request.get("/api/v1/auth/sessions")).json()).toHaveLength(1);
  expect((await request.get("/api/v1/auth/me")).ok()).toBeTruthy();
  await expect(security.getByRole("heading",{name:"Recent security activity",exact:true})).toBeVisible();
  expect((await other.get("/api/v1/auth/me")).status()).toBe(401);
  } finally { await other.dispose(); }
});

test("Compliance and task personal saved views restore defaults, scope and filters",async({page,request,workspace})=>{
  await open(page,"Compliance");const compliance=page.getByRole("region",{name:"Compliance saved views",exact:true});
  await page.locator(".org-switcher").click();await page.locator(".org-menu").getByRole("button").filter({has:page.getByText("Controls NGO",{exact:true})}).click();
  await page.getByRole("textbox",{name:"Search by title, code or owner...",exact:true}).fill("Controls compliance");
  await compliance.getByRole("textbox",{name:"Saved view name",exact:true}).fill("Compliance default");
  await compliance.getByRole("checkbox",{name:"Default view",exact:true}).check();await compliance.getByRole("button",{name:"Save current view",exact:true}).click();
  await expect(compliance.getByRole("button",{name:"Compliance default (default)",exact:true})).toBeVisible();
  const saved=(await(await request.get("/api/v1/saved-views?scope=COMPLIANCES")).json())[0];expect(saved.filters.organization_id).toBe(workspace.org);expect(saved.filters.query).toBe("Controls compliance");
  await open(page,"Compliance");await expect(page.getByRole("textbox",{name:"Search by title, code or owner...",exact:true})).toHaveValue("Controls compliance");
  await expect(page.locator(".compliance-table")).not.toContainText("Other controls compliance");
  await page.getByRole("button",{name:/^Tasks \d/}).click();const tasks=page.getByRole("region",{name:"Tasks saved views",exact:true});
  await tasks.getByRole("textbox",{name:"Saved view name",exact:true}).fill("Open tasks");await tasks.getByRole("button",{name:"Save current view",exact:true}).click();
  await expect(tasks.getByRole("button",{name:"Open tasks",exact:true})).toBeVisible();
  expect((await(await request.get("/api/v1/saved-views?scope=TASKS")).json())[0].filters.status).toBe("OPEN");
  await page.getByRole("button",{name:"My tasks",exact:true}).click();await expect(tasks.getByRole("button",{name:"Save current view",exact:true})).toBeDisabled();
  await tasks.getByRole("button",{name:"Open tasks",exact:true}).click();await expect(page.getByText("Controls task",{exact:true})).toBeVisible();
  page.once("dialog",dialog=>dialog.dismiss());await tasks.getByRole("button",{name:"Delete saved view Open tasks",exact:true}).click();await expect(tasks.getByRole("button",{name:"Open tasks",exact:true})).toBeVisible();
  page.once("dialog",dialog=>dialog.accept());await tasks.getByRole("button",{name:"Delete saved view Open tasks",exact:true}).click();await expect(tasks.getByRole("button",{name:"Open tasks",exact:true})).toHaveCount(0);
});

test("Reports saved filters persist and unsupported categories cannot be silently omitted",async({page,request,workspace})=>{
  await open(page,"Reports");const views=page.getByRole("region",{name:"Reports saved views",exact:true});const filters=page.locator(".report-filters");
  await filters.getByRole("combobox",{name:"Organization",exact:true}).selectOption(workspace.org);
  await filters.getByRole("combobox",{name:"Priority / risk",exact:true}).selectOption("HIGH");
  await views.getByRole("textbox",{name:"Saved view name",exact:true}).fill("Report high priority");await views.getByRole("button",{name:"Save current view",exact:true}).click();
  await expect(views.getByRole("button",{name:"Report high priority",exact:true})).toBeVisible();
  await filters.getByRole("combobox",{name:"Priority / risk",exact:true}).selectOption("");await views.getByRole("button",{name:"Report high priority",exact:true}).click();
  await expect(filters.getByRole("combobox",{name:"Priority / risk",exact:true})).toHaveValue("HIGH");
  expect((await(await request.get("/api/v1/saved-views?scope=REPORTS")).json())[0].filters.priority).toBe("HIGH");
  await filters.getByRole("combobox",{name:"Compliance type",exact:true}).selectOption("Annual");
  await views.getByRole("textbox",{name:"Saved view name",exact:true}).fill("Unsupported category");await expect(views.getByRole("button",{name:"Save current view",exact:true})).toBeDisabled();
  await expect(views).toContainText("Category is not supported");
});

test("Workflow task priority is saved and restored through the existing definition API",async({page,request,workspace})=>{
  await open(page,"Integrations");const builder=page.locator(".workflow-builder");
  await builder.locator(".workflow-form").getByRole("textbox",{name:"Name",exact:true}).fill("Priority workflow");
  await builder.getByRole("combobox",{name:"Organization",exact:true}).selectOption(workspace.org);
  await builder.getByRole("combobox",{name:"Action type",exact:true}).selectOption("CREATE_TASK");
  await builder.getByRole("textbox",{name:"Task title",exact:true}).fill("Created by workflow");
  await builder.getByRole("combobox",{name:"Task priority",exact:true}).selectOption("CRITICAL");
  await builder.getByRole("combobox",{name:"Responsible user",exact:true}).selectOption(workspace.user);
  await builder.getByRole("button",{name:"Save workflow",exact:true}).click();
  await expect(builder.locator(".workflow-list")).toContainText("Priority workflow");
  const definition=(await(await request.get("/api/v1/automations")).json())[0];expect(definition.actions[0].parameters.priority).toBe("CRITICAL");
  await builder.locator(".workflow-list article").getByRole("button").first().click();await expect(builder.getByRole("combobox",{name:"Task priority",exact:true})).toHaveValue("CRITICAL");
});

test("late workflow metadata preserves an in-progress user draft",async({page,workspace})=>{
  let metadataReads=0;
  let releaseLate:()=>void=()=>undefined;
  const lateCompletion=new Promise<void>(resolve=>{releaseLate=resolve;});
  await page.route("**/api/v1/automations/metadata",async route=>{
    const read=++metadataReads;
    const response=await route.fetch();
    if(read>1) await lateCompletion;
    await route.fulfill({response});
  });
  try {
    await open(page,"Integrations");
    const form=page.locator(".workflow-form");
    await expect.poll(()=>metadataReads).toBeGreaterThan(1);
    await form.getByRole("textbox",{name:"Name",exact:true}).fill("Preserve my draft");
    await form.getByRole("textbox",{name:"Description",exact:true}).fill("User-entered description");
    await form.getByRole("combobox",{name:"Organization",exact:true}).selectOption(workspace.org);
    const completion=page.waitForResponse(response=>response.url().endsWith("/automations/metadata")&&response.ok());
    releaseLate();await completion;
    await expect(form.getByRole("textbox",{name:"Name",exact:true})).toHaveValue("Preserve my draft");
    await expect(form.getByRole("textbox",{name:"Description",exact:true})).toHaveValue("User-entered description");
    await expect(form.getByRole("combobox",{name:"Organization",exact:true})).toHaveValue(workspace.org);
    await expect(form.getByRole("button",{name:"Save workflow",exact:true})).toBeEnabled();
  } finally { releaseLate(); }
});
