import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { expect, test as base } from "@playwright/test";

const headers={"X-Setu-Request":"1"};
type Workspace={tenant:string;user:string;org:string;partner:string;project:string;review:string;item:string;version:string;task:string};
function fixtureRole(workspace:Workspace, role:string) {
  const database=process.env.SETU_QA_DATABASE_URL;
  if(!database?.includes("setu-white-label-qa-")) throw new Error("Requires isolated CSR QA database");
  const python=process.env.API_PYTHON||path.resolve(process.platform==="win32"?"../api/.venv/Scripts/python.exe":"../api/.venv/bin/python");
  execFileSync(python,["-c",[
    "import sys", "from sqlalchemy import select", "from app.database import SessionLocal",
    "from app.models import User, Subscription", "with SessionLocal() as db:",
    "    db.get(User,sys.argv[1]).role=sys.argv[3]",
    "    db.scalar(select(Subscription).where(Subscription.tenant_id==sys.argv[2])).plan_name='ENTERPRISE'",
    "    db.commit()",
  ].join("\n"),workspace.user,workspace.tenant,role],{cwd:path.resolve("../api"),env:{...process.env,DATABASE_URL:database},windowsHide:true});
}
const test=base.extend<{workspace:Workspace}>({workspace:async({request,context},use)=>{
  const marker=randomUUID(),credentials={email:`csr-${marker}@example.test`,password:"CSR-browser-QA-2026!"};
  expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"CSR Workflow Admin",workspace_name:"CSR Workflow QA",...credentials}})).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login",{headers,data:credentials})).ok()).toBeTruthy();
  const user=(await(await request.get("/api/v1/auth/me")).json()).user;
  const workspace:Workspace={tenant:user.tenant_id,user:user.id,org:"",partner:"",project:"",review:"",item:"",version:"",task:""};
  fixtureRole(workspace,"ADMIN");
  async function create(resource:string,data:unknown) {
    const response=await request.post(`/api/v1/${resource}`,{headers,data});
    expect(response.status(),await response.text()).toBe(201);return response.json();
  }
  workspace.org=(await create("organizations",{name:"CSR Workflow NGO",legal_type:"TRUST",registration_number:marker,city:"Pune",pan:"",fcra_active:false,generate_compliance_plan:false})).organization.id;
  workspace.partner=(await create("csr/partners",{organization_id:workspace.org,internal_notes:"Corporate private partner note"})).id;
  workspace.project=(await create("csr/projects",{relationship_id:workspace.partner,name:"CSR Workflow Project",code:`QA-${marker}`,shared_with_ngo:true})).id;
  const template=await create("csr/checklist-templates",{name:`Checklist ${marker}`,items:[{category:"Registration",title:"Registration evidence",requirement_type:"DOCUMENT",share_with_ngo:true}]});
  const review=await create("csr/reviews",{relationship_id:workspace.partner,project_id:workspace.project,template_id:template.id,title:"CSR Workflow Review",shared_with_ngo:true});
  workspace.review=review.id;workspace.item=review.items[0].id;
  // A real validated PNG is uploaded through the existing private-document API.
  const uploaded=await request.post("/api/v1/documents/upload",{headers,multipart:{metadata:JSON.stringify({request_id:randomUUID(),organization_id:workspace.org,name:"CSR registration.png",category:"CSR evidence"}),file:{name:"CSR registration.png",mimeType:"image/png",buffer:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAANUlEQVR4nO3RQQ0AAAjDwIFypCOhr/16AkZSJpeq7c7HA8wfIBMhEyETIRMhEyETIRMhE4U8n4kAwL5zJ1AAAAAASUVORK5CYII=","base64")}}});
  expect(uploaded.status(),await uploaded.text()).toBe(201);workspace.version=(await uploaded.json()).document.current_version_id;
  workspace.task=(await create("tasks",{organization_id:workspace.org,title:"CSR evidence follow-up",due_at:"2030-01-01",assignee_user_id:user.id})).id;
  await context.addCookies((await request.storageState()).cookies);await use(workspace);
}});

test("CSR existing records support edits, evidence, tasks, decisions and history through real APIs",async({page,request,workspace})=>{
  await page.goto("/dashboard?view=csr");
  await page.getByRole("button",{name:"CSR partners",exact:true}).click();
  const partner=page.locator(`#csr-record-${workspace.partner}`);
  await partner.getByText("Edit partner",{exact:true}).click();
  await partner.getByLabel("Partner status").selectOption("ACTIVE");
  await partner.getByLabel("Shared notes").fill("Shared onboarding update");
  await partner.getByRole("button",{name:"Save partner",exact:true}).click();
  await expect(partner.getByRole("cell",{name:"Active",exact:true})).toBeVisible();
  await page.getByRole("tab",{name:"Projects",exact:true}).click();
  const project=page.locator(`#csr-record-${workspace.project}`);
  await project.getByText("Edit project",{exact:true}).click();
  await project.getByLabel("Project name").fill("Updated CSR Project");
  await project.getByLabel("Project status").selectOption("ACTIVE");
  await project.getByRole("button",{name:"Save project",exact:true}).click();
  await expect(project.getByRole("cell",{name:"Active",exact:true})).toBeVisible();
  await page.getByRole("tab",{name:"Due diligence",exact:true}).click();
  const item=page.getByRole("region",{name:"Registration evidence",exact:true});
  await item.getByText("Link existing evidence / task",{exact:true}).click();
  await item.getByRole("combobox",{name:"Existing evidence",exact:true}).selectOption(workspace.version);
  await item.getByRole("button",{name:"Link evidence",exact:true}).click();
  await expect(item.getByRole("listitem").filter({hasText:"CSR registration.png v1"})).toBeVisible();
  await item.getByRole("combobox",{name:"Existing task",exact:true}).selectOption(workspace.task);
  await item.getByRole("button",{name:"Link task",exact:true}).click();
  await expect(item.getByText("CSR evidence follow-up · To do",{exact:true})).toBeVisible();
  for(const [status, label] of [["SUBMITTED","Submitted"],["UNDER_REVIEW","Under review"],["APPROVED","Approved"]]) {
    await expect(item.getByLabel("Checklist status")).toContainText(label);
    await item.getByLabel("Checklist status").selectOption(status);
    await item.getByRole("textbox",{name:"Response",exact:true}).fill("Evidence reviewed against the operational checklist");
    await item.getByRole("button",{name:"Save response / decision",exact:true}).click();
    await expect(item.locator(".status-pill")).toHaveText(label);
  }
  const review=page.locator(`#csr-record-${workspace.review}`);
  await review.getByText("Status / history",{exact:true}).click();
  await expect(review.getByText("Changed operational review item from UNDER_REVIEW to APPROVED",{exact:false})).toBeVisible();
  const saved=await(await request.get(`/api/v1/csr/reviews/${workspace.review}`)).json();
  expect(saved.status).toBe("APPROVED");expect(saved.items[0].evidence[0].version_id).toBe(workspace.version);expect(saved.items[0].tasks[0].id).toBe(workspace.task);
  await page.reload();await page.getByRole("button",{name:"CSR partners",exact:true}).click();await page.getByRole("tab",{name:"Due diligence",exact:true}).click();
  await expect(page.locator(`#csr-record-${workspace.review} .status-pill`)).toHaveText("Approved");
});

test("CSR NGO collaborators see only shared records and supported response controls",async({page,request,workspace})=>{
  await page.goto("/dashboard");await page.getByRole("button",{name:"CSR partners",exact:true}).click();
  const partner=page.locator(`#csr-record-${workspace.partner}`);
  await partner.getByText("Grant NGO collaborator access",{exact:true}).click();
  await partner.getByRole("combobox",{name:"Collaborator",exact:true}).selectOption(workspace.user);
  await partner.getByRole("button",{name:"Grant access",exact:true}).click();
  await expect(page.getByText("CSR record saved.",{exact:true})).toBeVisible();
  const templates=await(await request.get("/api/v1/csr/checklist-templates")).json();
  expect((await request.post("/api/v1/csr/reviews",{headers,data:{relationship_id:workspace.partner,template_id:templates[0].id,title:"Corporate private review",shared_with_ngo:false}})).status()).toBe(201);
  fixtureRole(workspace,"MEMBER");
  await page.reload();await page.getByRole("button",{name:"CSR partners",exact:true}).click();
  await expect(page.getByText("Edit partner",{exact:true})).toHaveCount(0);
  await expect(page.getByText("Corporate private partner note")).toHaveCount(0);
  await page.getByRole("tab",{name:"Due diligence",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Corporate private review",exact:true})).toHaveCount(0);
  const item=page.getByRole("region",{name:"Registration evidence",exact:true});
  await expect(item.getByLabel("Corporate internal notes")).toHaveCount(0);
  await expect(item.getByLabel("Checklist status")).not.toContainText("Approved");
  await item.getByRole("textbox",{name:"Response",exact:true}).fill("NGO evidence response");
  await item.getByLabel("Checklist status").selectOption("SUBMITTED");
  await item.getByRole("button",{name:"Save response / decision",exact:true}).click();
  await expect(item.locator(".status-pill")).toHaveText("Submitted");
  await expect(item.getByText("Link existing evidence / task",{exact:true})).toHaveCount(0);
});

test("CSR viewer remains read-only and failed mutations preserve safe errors",async({page,workspace})=>{
  await page.goto("/dashboard");await page.getByRole("button",{name:"CSR partners",exact:true}).click();
  await page.locator(`#csr-record-${workspace.partner}`).getByText("Edit partner",{exact:true}).click();
  await page.route(`**/api/v1/csr/partners/${workspace.partner}`,route=>route.fulfill({status:409,json:{detail:"Partner update could not be applied"}}));
  await page.getByRole("button",{name:"Save partner",exact:true}).click();
  await expect(page.locator('[aria-labelledby="csr-title"]').getByRole("alert")).toHaveText("The record state does not allow this action. Refresh and review before trying again.Try again");
  await page.unroute(`**/api/v1/csr/partners/${workspace.partner}`);
  fixtureRole(workspace,"VIEWER");await page.reload();await page.getByRole("button",{name:"CSR partners",exact:true}).click();
  await expect(page.getByText("Edit partner",{exact:true})).toHaveCount(0);await expect(page.getByText("Grant NGO collaborator access",{exact:true})).toHaveCount(0);
  await page.getByRole("tab",{name:"Due diligence",exact:true}).click();
  await expect(page.getByRole("heading",{name:"CSR Workflow Review",exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Save response / decision",exact:true})).toHaveCount(0);
  await expect(page.getByText("Link existing evidence / task",{exact:true})).toHaveCount(0);
});
