import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { expect, test as base, type Page } from "@playwright/test";

const headers={"X-Setu-Request":"1"};
type Workspace={org:string;otherOrg:string;user:string;tenant:string;grant:string;hidden:string;legacy:string};
const test=base.extend<{workspace:Workspace}>({workspace:async({request,context},use)=>{
  const marker=randomUUID(),credentials={email:`operations-${marker}@example.test`,password:"Operations-browser-QA-2026!"};
  expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"Operations Administrator",workspace_name:"Operations QA",...credentials}})).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login",{headers,data:credentials})).ok()).toBeTruthy();
  const user=(await(await request.get("/api/v1/auth/me")).json()).user;
  async function create(resource:string,data:unknown){const response=await request.post(`/api/v1/${resource}`,{headers,data});expect(response.status(),await response.text()).toBe(201);return response.json();}
  const org=(await create("organizations",{name:"Operations NGO",legal_type:"TRUST",registration_number:marker,city:"Pune",generate_compliance_plan:false})).organization.id;
  const otherOrg=(await create("organizations",{name:"Other Operations NGO",legal_type:"TRUST",registration_number:`other-${marker}`,city:"Pune",generate_compliance_plan:false})).organization.id;
  const grant=(await create("portfolio-records",{organization_id:org,record_type:"GRANT",title:"Existing grant",status:"ACTIVE",owner_name:"Grant contact",value_label:"Funding reference",due_at:"2030-01-01",notes:"Original notes"})).id;
  const hidden=(await create("portfolio-records",{organization_id:otherOrg,record_type:"DONOR",title:"Other organization donor"})).id;
  const legacy=(await create("portfolio-records",{organization_id:org,record_type:"CSR_PROJECT",title:"Legacy CSR reference"})).id;
  await context.addCookies((await request.storageState()).cookies);await use({org,otherOrg,user:user.id,tenant:user.tenant_id,grant,hidden,legacy});
}});
async function open(page:Page,view:"NGO operations"|"Impact modules"){
  await page.goto("/dashboard");await page.getByRole("button",{name:view,exact:true}).click();
  await expect(page.getByRole("button",{name:"Refresh records",exact:true})).toBeVisible();
}
function readOnlyRole(workspace:Workspace,role:"MEMBER"|"VIEWER"){
  const database=process.env.SETU_QA_DATABASE_URL;
  if(!database?.includes("setu-white-label-qa-")) throw new Error("Requires isolated operations QA database");
  const python=process.env.API_PYTHON||path.resolve(process.platform==="win32"?"../api/.venv/Scripts/python.exe":"../api/.venv/bin/python");
  execFileSync(python,["-c",[
    "import sys", "from sqlalchemy import select", "from app.database import SessionLocal", "from app.models import User", "from app.phase8_models import OrganizationAccess",
    "with SessionLocal() as db:","    db.get(User,sys.argv[1]).role=sys.argv[4]",
    "    access=db.scalar(select(OrganizationAccess).where(OrganizationAccess.user_id==sys.argv[1],OrganizationAccess.organization_id==sys.argv[3]))",
    "    if access: access.access_role='VIEWER'",
    "    else: db.add(OrganizationAccess(tenant_id=sys.argv[2],user_id=sys.argv[1],organization_id=sys.argv[3],access_role='VIEWER',granted_by=sys.argv[1]))",
    "    db.commit()",
  ].join("\n"),workspace.user,workspace.tenant,workspace.org,role],{cwd:path.resolve("../api"),env:{...process.env,DATABASE_URL:database},windowsHide:true});
}

test("operations create, detail, edit, status and delete persist through existing APIs",async({page,request,workspace})=>{
  await open(page,"NGO operations");await page.getByRole("button",{name:"Add operational record",exact:true}).click();
  let dialog=page.getByRole("dialog");
  await dialog.getByRole("combobox",{name:"Organization",exact:true}).selectOption(workspace.org);
  await dialog.getByRole("textbox",{name:"Title / person / subject",exact:true}).fill("Workflow membership");
  await dialog.getByRole("textbox",{name:"Responsible person / contact",exact:true}).fill("Original owner");
  await dialog.getByRole("textbox",{name:"Fee / transaction",exact:true}).fill("Reference only");
  await dialog.getByLabel("Valid until",{exact:true}).fill("2030-01-01");
  await dialog.getByRole("button",{name:"Add membership",exact:true}).click();
  await page.getByRole("button",{name:"View Workflow membership",exact:true}).click();
  dialog=page.getByRole("dialog");await dialog.getByRole("button",{name:"Edit record",exact:true}).click();
  await dialog.getByRole("textbox",{name:"Record title",exact:true}).fill("Updated membership");
  await dialog.getByRole("textbox",{name:"Responsible person / contact",exact:true}).fill("Updated owner");
  await dialog.getByRole("textbox",{name:"Recorded status",exact:true}).fill("RECORDED");
  await dialog.getByLabel("Date",{exact:true}).fill("");
  await dialog.getByRole("textbox",{name:"Notes",exact:true}).fill("Updated membership notes");
  await dialog.getByRole("button",{name:"Save record",exact:true}).click();
  await expect(page.getByRole("button",{name:"View Updated membership",exact:true})).toBeVisible();
  await page.getByRole("combobox",{name:"Status for Updated membership",exact:true}).selectOption("VERIFIED");
  await expect(page.getByRole("combobox",{name:"Status for Updated membership",exact:true})).toBeEnabled();
  let rows=await(await request.get("/api/v1/portfolio-records")).json();
  const saved=rows.find((row:{title:string})=>row.title==="Updated membership");
  expect(saved.status).toBe("VERIFIED");expect(saved.owner_name).toBe("Updated owner");expect(saved.due_at).toBeNull();expect(saved.notes).toBe("Updated membership notes");
  await page.getByRole("textbox",{name:"Search operational records",exact:true}).fill("Updated owner");
  await page.getByRole("combobox",{name:"Operations status filter",exact:true}).selectOption("VERIFIED");
  await expect(page.getByRole("button",{name:"View Updated membership",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"View Updated membership",exact:true}).click();
  page.once("dialog",dialog=>dialog.accept());await page.getByRole("dialog").getByRole("button",{name:"Delete record",exact:true}).click();
  await expect(page.getByRole("button",{name:"View Updated membership",exact:true})).toHaveCount(0);
  rows=await(await request.get("/api/v1/portfolio-records")).json();expect(rows.some((row:{id:string})=>row.id===saved.id)).toBe(false);
});

test("impact detail editing, safe retry, scoped filtering and refresh use backend state",async({page,request,workspace})=>{
  await open(page,"Impact modules");await page.getByRole("button",{name:"View Existing grant",exact:true}).click();
  const dialog=page.getByRole("dialog");await dialog.getByRole("button",{name:"Edit record",exact:true}).click();
  await dialog.getByRole("textbox",{name:"Record title",exact:true}).fill("Updated grant");
  await dialog.getByRole("textbox",{name:"Responsible person / contact",exact:true}).fill("New grant owner");
  await dialog.getByRole("textbox",{name:"Value / reference",exact:true}).fill("Updated reference");
  await dialog.getByRole("textbox",{name:"Recorded status",exact:true}).fill("REVIEWED");
  await dialog.getByLabel("Date",{exact:true}).fill("");
  await page.route(`**/api/v1/portfolio-records/${workspace.grant}`,route=>route.fulfill({status:503,json:{detail:"Temporary update failure"}}));
  await dialog.getByRole("button",{name:"Save record",exact:true}).click();await expect(dialog.getByRole("alert")).toHaveText("The server is unavailable. Please try again shortly.");
  await expect(dialog.getByRole("textbox",{name:"Record title",exact:true})).toHaveValue("Updated grant");
  await page.unroute(`**/api/v1/portfolio-records/${workspace.grant}`);await dialog.getByRole("button",{name:"Save record",exact:true}).click();
  await expect(page.getByRole("button",{name:"View Updated grant",exact:true})).toBeVisible();
  await page.route("**/api/v1/portfolio-records",route=>route.fulfill({status:503,json:{detail:"Temporary refresh failure"}}));
  await page.getByRole("button",{name:"Refresh records",exact:true}).click();
  await expect(page.locator(".page").getByRole("alert")).toHaveText("The server is unavailable. Please try again shortly.");
  await expect(page.getByRole("button",{name:"View Updated grant",exact:true})).toBeVisible();
  await page.unroute("**/api/v1/portfolio-records");
  await page.locator(".org-switcher").click();await page.locator(".org-menu").getByRole("button").filter({has:page.getByText("Operations NGO",{exact:true})}).click();
  await expect(page.getByRole("button",{name:"View Other organization donor",exact:true})).toHaveCount(0);
  await page.getByRole("textbox",{name:"Search impact records",exact:true}).fill("New grant owner");
  await page.getByRole("combobox",{name:"Impact status filter",exact:true}).selectOption("REVIEWED");
  await expect(page.getByRole("button",{name:"View Updated grant",exact:true})).toBeVisible();
  expect((await request.patch(`/api/v1/portfolio-records/${workspace.grant}`,{headers,data:{notes:"Refreshed backend notes"}})).ok()).toBeTruthy();
  await page.getByRole("button",{name:"Refresh records",exact:true}).click();
  await expect(page.getByText("Refreshed backend notes",{exact:true})).toBeVisible();
  const saved=(await(await request.get("/api/v1/portfolio-records")).json()).find((row:{id:string})=>row.id===workspace.grant);
  expect(saved.due_at).toBeNull();expect(saved.value_label).toBe("Updated reference");
  await page.getByRole("textbox",{name:"Search impact records",exact:true}).fill("");await page.getByRole("combobox",{name:"Impact status filter",exact:true}).selectOption("");
  await page.getByRole("button",{name:"View Legacy CSR reference",exact:true}).click();
  await expect(page.getByRole("dialog").getByRole("button",{name:"Edit record",exact:true})).toHaveCount(0);
  await expect(page.getByRole("dialog").getByRole("button",{name:"Delete record",exact:true})).toHaveCount(0);
});

test("organization read-only and Viewer roles cannot edit and cannot see unrelated records",async({page,request,workspace})=>{
  readOnlyRole(workspace,"MEMBER");await open(page,"Impact modules");
  await expect(page.getByRole("button",{name:"View Other organization donor",exact:true})).toHaveCount(0);
  await page.getByRole("button",{name:"View Existing grant",exact:true}).click();
  await expect(page.getByRole("dialog").getByRole("button",{name:"Edit record",exact:true})).toHaveCount(0);
  await expect(page.getByRole("dialog").getByRole("button",{name:"Delete record",exact:true})).toHaveCount(0);
  expect((await request.patch(`/api/v1/portfolio-records/${workspace.grant}`,{headers,data:{notes:"Unauthorized"}})).status()).toBe(403);
  expect((await request.get(`/api/v1/portfolio-records?organization_id=${workspace.otherOrg}`)).status()).toBe(403);
  readOnlyRole(workspace,"VIEWER");await open(page,"Impact modules");
  await expect(page.getByRole("button",{name:"Add record",exact:true})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"NGO operations",exact:true})).toHaveCount(0);
  await page.getByRole("button",{name:"View Existing grant",exact:true}).click();
  await expect(page.getByRole("dialog").getByRole("button",{name:"Edit record",exact:true})).toHaveCount(0);
});

test("impact creation exposes descriptive fields without duplicating CSR workflows",async({page,request,workspace})=>{
  await open(page,"Impact modules");await page.getByRole("button",{name:"Add record",exact:true}).click();
  const dialog=page.getByRole("dialog");
  await expect(dialog.getByRole("combobox",{name:"Module",exact:true}).locator("option[value=CSR_PROJECT]")).toHaveCount(0);
  await dialog.getByRole("combobox",{name:"Organization",exact:true}).selectOption(workspace.org);
  await dialog.getByRole("combobox",{name:"Module",exact:true}).selectOption("DONOR");
  await dialog.getByRole("textbox",{name:"Record title",exact:true}).fill("Created donor");
  await dialog.getByRole("textbox",{name:"Responsible person / contact",exact:true}).fill("Donor contact");
  await dialog.getByRole("textbox",{name:"Recorded status",exact:true}).fill("RECORDED");
  await dialog.getByRole("textbox",{name:"Value or scale",exact:true}).fill("Descriptive reference");
  await dialog.getByRole("textbox",{name:"Notes",exact:true}).fill("Donor notes");
  await dialog.getByRole("button",{name:"Add record",exact:true}).click();
  await expect(page.getByRole("button",{name:"View Created donor",exact:true})).toBeVisible();
  const saved=(await(await request.get("/api/v1/portfolio-records")).json()).find((row:{title:string})=>row.title==="Created donor");
  expect(saved.record_type).toBe("DONOR");expect(saved.organization_id).toBe(workspace.org);expect(saved.owner_name).toBe("Donor contact");expect(saved.status).toBe("RECORDED");expect(saved.value_label).toBe("Descriptive reference");expect(saved.notes).toBe("Donor notes");
});
