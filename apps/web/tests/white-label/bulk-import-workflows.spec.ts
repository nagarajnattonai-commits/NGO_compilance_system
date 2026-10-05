import { randomUUID } from "node:crypto";
import { expect, test as base, type Locator, type Page } from "@playwright/test";

const headers={"X-Setu-Request":"1"};
const test=base.extend<{adminReady:boolean}>({adminReady:async({request,context},use)=>{
  const credentials={email:`import-workflow-${randomUUID()}@example.test`,password:"Import-workflow-QA-2026!"};
  expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"Import Workflow Administrator",workspace_name:"Import Workflow QA",...credentials}})).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login",{headers,data:credentials})).ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);await use(true);
}});
async function open(page:Page) {
  await page.goto("/dashboard");await page.getByRole("button",{name:"Administration",exact:true}).click();
  const importer=page.getByRole("region",{name:"Bulk NGO onboarding and imports",exact:true});
  await expect(importer.getByRole("button",{name:"Upload for review",exact:true})).toBeVisible();return importer;
}
async function upload(page:Page, importer:Locator, content?:string) {
  const csv=content||`name,legal_type,registration_number,city\nWorkflow Imported NGO,TRUST,IMPORT-${randomUUID()},Pune\n`;
  await importer.getByLabel("CSV or XLSX file").setInputFiles({name:"workflow.csv",mimeType:"text/csv",buffer:Buffer.from(csv)});
  const response=page.waitForResponse(response=>response.url().endsWith("/api/v1/imports")&&response.request().method()==="POST");
  await importer.getByRole("button",{name:"Upload for review",exact:true}).click();
  const uploaded=await response;expect(uploaded.status()).toBe(201);
  await expect(importer.getByRole("button",{name:"Refresh import status",exact:true})).toBeEnabled();return uploaded.json() as Promise<{id:string}>;
}

test("import Start over cancels the backend job and retains it when cancellation fails",async({page,request,adminReady})=>{
  expect(adminReady).toBe(true);const importer=await open(page),job=await upload(page,importer);
  await page.route(`**/api/v1/imports/${job.id}/cancel`,route=>route.fulfill({status:503,json:{detail:"Temporary cancellation failure"}}));
  await importer.getByRole("button",{name:"Start over",exact:true}).click();
  await expect(importer.getByRole("alert")).toContainText("Temporary cancellation failure");
  await expect(importer.getByRole("button",{name:"Cancel import",exact:true})).toBeVisible();
  expect((await(await request.get(`/api/v1/imports/${job.id}`)).json()).status).toBe("UPLOADED");
  await page.unroute(`**/api/v1/imports/${job.id}/cancel`);
  await importer.getByRole("button",{name:"Start over",exact:true}).click();
  await expect(importer.getByRole("button",{name:"Upload for review",exact:true})).toBeVisible();
  expect((await(await request.get(`/api/v1/imports/${job.id}`)).json()).status).toBe("CANCELLED");
  await importer.getByRole("textbox",{name:"Import job ID",exact:true}).fill(job.id);
  await importer.getByRole("button",{name:"Open import",exact:true}).click();
  await expect(importer.locator(".status-pill")).toHaveText("Cancelled");
  await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toHaveCount(0);
});

test("saved import resumes mapping and duplicate resolutions and displays skipped row results",async({page,request,adminReady})=>{
  expect(adminReady).toBe(true);const registration=`EXISTING-${randomUUID()}`;
  expect((await request.post("/api/v1/organizations",{headers,data:{name:"Existing Workflow NGO",legal_type:"TRUST",registration_number:registration,city:"Pune",pan:"",fcra_active:false,generate_compliance_plan:false}})).status()).toBe(201);
  let importer=await open(page);const job=await upload(page,importer,`name,legal_type,registration_number,city\nExisting Workflow NGO,TRUST,${registration},Pune\n`);
  await importer.getByRole("button",{name:"Run dry validation",exact:true}).click();
  await expect(importer.locator(".status-pill")).toHaveText("Resolve errors");
  await importer.getByRole("combobox",{name:"Resolution for row 2",exact:true}).selectOption("SKIP");
  await importer.getByRole("button",{name:"Run dry validation",exact:true}).click();
  await expect(importer.locator(".status-pill")).toHaveText("Ready to import");
  importer=await open(page);
  await importer.getByRole("textbox",{name:"Import job ID",exact:true}).fill(job.id);await importer.getByRole("button",{name:"Open import",exact:true}).click();
  await expect(importer.getByRole("combobox",{name:"Resolution for row 2",exact:true})).toHaveValue("SKIP");
  await expect(importer.getByRole("combobox",{name:/Platform field: name/})).toHaveValue("name");
  await importer.getByRole("button",{name:"Confirm Import",exact:true}).click();
  await expect(importer.locator(".status-pill")).toHaveText("Completed");
  await expect(importer.getByRole("cell",{name:"SKIPPED",exact:true})).toBeVisible();
  await expect(importer.getByRole("link",{name:"Download result CSV",exact:true})).toHaveAttribute("href",`/api/v1/imports/${job.id}/results.csv`);
});

test("lost confirmation response recovers completed results without executing twice",async({page,request,adminReady})=>{
  expect(adminReady).toBe(true);const importer=await open(page),job=await upload(page,importer);
  await importer.getByRole("button",{name:"Run dry validation",exact:true}).click();await expect(importer.locator(".status-pill")).toHaveText("Ready to import");
  let confirmations=0;
  await page.route(`**/api/v1/imports/${job.id}/confirm`,async route=>{confirmations++;const response=await route.fetch();expect(response.ok()).toBeTruthy();await route.abort("failed");});
  await importer.getByRole("button",{name:"Confirm Import",exact:true}).click();
  await expect(importer.locator(".status-pill")).toHaveText("Completed");
  await expect(importer.getByRole("cell",{name:"CREATED",exact:true})).toBeVisible();
  await importer.getByRole("button",{name:"Refresh import status",exact:true}).click();
  await expect(importer.getByRole("button",{name:"Refresh import status",exact:true})).toBeEnabled();
  expect(confirmations).toBe(1);
  expect((await(await request.get("/api/v1/organizations")).json()).filter((org:{name:string})=>org.name==="Workflow Imported NGO")).toHaveLength(1);
  await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toHaveCount(0);
});

test("mapping edits require a new dry run and unknown backend state blocks confirmation until refreshed",async({page,adminReady})=>{
  expect(adminReady).toBe(true);const importer=await open(page),job=await upload(page,importer);
  await importer.getByRole("button",{name:"Run dry validation",exact:true}).click();await expect(importer.locator(".status-pill")).toHaveText("Ready to import");
  const mapping=importer.getByRole("combobox",{name:/Platform field: city/});
  await mapping.selectOption("");await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toBeDisabled();
  await mapping.selectOption("city");await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toBeDisabled();
  await importer.getByRole("button",{name:"Run dry validation",exact:true}).click();await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toBeEnabled();
  await page.route(`**/api/v1/imports/${job.id}`,route=>route.fulfill({status:503,json:{detail:"Temporary state read failure"}}));
  await importer.getByRole("button",{name:"Refresh import status",exact:true}).click();
  await expect(importer.getByRole("alert")).toContainText("Temporary state read failure");await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toBeDisabled();
  await page.unroute(`**/api/v1/imports/${job.id}`);await importer.getByRole("button",{name:"Refresh import status",exact:true}).click();
  await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toBeEnabled();
});

test("import results display successful and failed rows without offering a duplicate execution",async({page,request,adminReady})=>{
  expect(adminReady).toBe(true);const importer=await open(page),registration=`CONFLICT-${randomUUID()}`;
  await upload(page,importer,`name,legal_type,registration_number,city\nSuccessful Import NGO,TRUST,SUCCESS-${randomUUID()},Pune\nConflicting Import NGO,TRUST,${registration},Pune\n`);
  await importer.getByRole("button",{name:"Run dry validation",exact:true}).click();await expect(importer.locator(".status-pill")).toHaveText("Ready to import");
  expect((await request.post("/api/v1/organizations",{headers,data:{name:"Late Conflict NGO",legal_type:"TRUST",registration_number:registration,city:"Pune",pan:"",fcra_active:false,generate_compliance_plan:false}})).status()).toBe(201);
  await importer.getByRole("button",{name:"Confirm Import",exact:true}).click();
  await expect(importer.locator(".status-pill")).toHaveText("Completed with errors");
  await expect(importer.getByRole("cell",{name:"CREATED",exact:true})).toBeVisible();
  await expect(importer.getByRole("cell",{name:"FAILED",exact:true})).toBeVisible();
  await expect(importer.getByRole("button",{name:"Confirm Import",exact:true})).toHaveCount(0);
  await expect(importer.getByRole("link",{name:"Download result CSV",exact:true})).toBeVisible();
});
