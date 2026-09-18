import {test,expect,type APIRequestContext,type BrowserContext} from "@playwright/test";
import {readFileSync} from "node:fs";
import path from "node:path";
import {flattenMessages} from "../../i18n/messages";
const headers={"X-Setu-Request":"1"};
async function login(request:APIRequestContext,context:BrowserContext,locale="en-IN"){
 const credentials={email:"white-label-qa@example.test",password:"WhiteLabel-browser-QA-2026!"};
 const response=await request.post("/api/v1/auth/login",{headers,data:credentials});
 if(response.status()===401)expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"Integration QA",workspace_name:"Integration QA",...credentials}})).status()).toBe(201);
 else expect(response.ok()).toBeTruthy();
 expect((await request.patch("/api/v1/localization/preferences",{headers,data:{locale,timezone:"Asia/Kolkata",time_format:"12h"}})).ok()).toBeTruthy();
 await context.addCookies((await request.storageState()).cookies);
 const me=await request.get("/api/v1/auth/me");return (await me.json()).user.tenant_id as string;
}
async function grant(request:APIRequestContext,tenant:string,key:string){
 expect((await request.put("/api/v1/integrations-management/platform/tenants/"+tenant+"/entitlement",{headers,data:{feature_key:key,enabled:true}})).ok()).toBeTruthy();
}
async function seed(request:APIRequestContext,tenant:string,name:string){
 await grant(request,tenant,"custom_email");
 const result=await request.post("/api/v1/integrations-management/tenant/connections",{headers,data:{provider_key:"smtp",display_name:name,configuration:{host:"mail.example.org",port:465,username:"mailer",from_address:"notify@example.org"}}});
 expect(result.status()).toBe(201);return (await result.json()).id as string;
}

test("integration setup, safe credential state, API key shown once and revocation",async({page,request,context})=>{
 const tenant=await login(request,context);await grant(request,tenant,"custom_email");await grant(request,tenant,"public_api");
 const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",m=>{if(m.type()==="error")errors.push(m.text());});
 await page.goto("/settings/integrations");
 await page.getByRole("button",{name:"Add connection",exact:true}).click();
 await page.getByLabel("Display name",{exact:true}).fill("Browser branded email");
 await page.getByLabel("SMTP host",{exact:true}).fill("mail.example.org");
 await page.getByLabel("Username",{exact:true}).fill("mailer");
 await page.getByLabel("Verified sender email",{exact:true}).fill("notify@example.org");
 await page.getByRole("button",{name:"Save",exact:true}).click();
 const card=page.locator(".integration-card").filter({has:page.getByRole("heading",{name:"Browser branded email",exact:true})});
 await expect(card).toBeVisible();await expect(card.getByRole("button",{name:"Replace credential",exact:true})).toBeDisabled();
 await expect(card.getByRole("button",{name:"Activate",exact:true})).toHaveCount(0);
 await card.getByRole("button",{name:"Test connection",exact:true}).click();
 await expect(page.locator(".integration-page [role=alert]")).toContainText("Configure server-side credentials before testing.");
 await page.goto("/settings/developers");
 await page.getByRole("button",{name:"Add application",exact:true}).click();
 await page.getByLabel("Display name",{exact:true}).fill("Browser ERP");
 await page.getByRole("button",{name:"Save",exact:true}).click();
 await expect(page.getByRole("heading",{name:"Browser ERP",exact:true})).toBeVisible();
 await page.goto("/settings/developers/api-keys");
 await page.getByRole("button",{name:"Create API key",exact:true}).click();
 await page.getByLabel("Display name",{exact:true}).fill("Browser scoped key");
 await page.getByLabel("Application",{exact:true}).selectOption({label:"Browser ERP"});
 await page.getByRole("button",{name:"Save",exact:true}).click();
 const once=page.getByRole("region",{name:"One-time secret",exact:true});
 await expect(once).toBeVisible();const raw=await once.locator("code").textContent();expect(raw).toMatch(/^setu_/);
 await page.getByRole("button",{name:"Dismiss",exact:true}).click();await expect(once).toHaveCount(0);
 await page.reload();await expect(page.locator(".integration-page")).not.toContainText(raw!);
 const keyCard=page.locator(".integration-card").filter({has:page.getByRole("heading",{name:"Browser scoped key",exact:true})});
 page.once("dialog",dialog=>dialog.accept());await keyCard.getByRole("button",{name:"Revoke",exact:true}).click();
 await expect(keyCard).toContainText("Revoked");
 expect(errors).toEqual([]);
});

test("integration save outage preserves non-secret form and permits retry",async({page,request,context})=>{
 const tenant=await login(request,context);await grant(request,tenant,"custom_email");
 await page.goto("/settings/integrations");await page.getByRole("button",{name:"Add connection",exact:true}).click();
 await page.getByLabel("Display name",{exact:true}).fill("Retry connection");
 await page.getByLabel("SMTP host",{exact:true}).fill("mail.example.org");
 await page.getByLabel("Username",{exact:true}).fill("mailer");
 await page.getByLabel("Verified sender email",{exact:true}).fill("notify@example.org");
 await page.route("**/api/v1/integrations-management/tenant/connections",route=>route.request().method()==="POST"?route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"Temporary failure"})}):route.continue());
 await page.getByRole("button",{name:"Save",exact:true}).click();
 await expect(page.locator(".integration-page [role=alert]")).toContainText("The action failed.");
 await expect(page.getByLabel("Display name",{exact:true})).toHaveValue("Retry connection");
 await page.unroute("**/api/v1/integrations-management/tenant/connections");
 await page.getByRole("button",{name:"Save",exact:true}).click();
 await expect(page.getByRole("heading",{name:"Retry connection",exact:true})).toBeVisible();
});

test("integration backend denies unapproved platform access and forged tenant requests",async({request,context})=>{
 await login(request,context);
 expect((await request.get("/api/v1/integrations-management/tenant/connections",{headers:{"X-Tenant-ID":"forged-workspace"}})).status()).toBe(403);
 const other=await request.post("/api/v1/auth/signup",{headers,data:{name:"Other integration user",workspace_name:"Other integration workspace",email:"integration-other@example.test",password:"Other-integration-QA-2026!"}});
 expect(other.status()).toBe(201);
 await context.addCookies((await request.storageState()).cookies);
 expect((await request.get("/api/v1/integrations-management/platform/providers")).status()).toBe(403);
 expect((await request.get("/api/v1/integrations-management/platform/developer/api-keys")).status()).toBe(403);
});

for(const locale of ["en-IN","hi-IN","kn-IN","mr-IN"]){
 test("integration pages and configuration form fit all required widths in "+locale,async({page,request,context})=>{
  test.setTimeout(480_000);
  const tenant=await login(request,context,locale);
  await seed(request,tenant,"Responsive connection "+locale);
  const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",m=>{if(m.type()==="error")errors.push(m.text());});
  const modules=(language:string)=>JSON.parse(readFileSync(path.resolve("messages",language,"integrations.json"),"utf8"));
  expect(Object.keys(flattenMessages(modules(locale))).sort()).toEqual(Object.keys(flattenMessages(modules("en-IN"))).sort());
  expect(JSON.stringify(modules(locale))).not.toContain("??");
  if(locale!=="en-IN")expect(modules(locale).Integrations.title).not.toBe("Integrations");
  const routes=["/admin/integrations/providers","/admin/integrations/credentials","/admin/integrations/health","/admin/integrations/logs","/admin/integrations/tenants","/admin/developers/api-keys","/settings/developers/webhooks","/settings/developers/documentation","/settings/developers/usage","/settings/developers/oauth"];
  for(const width of [320,360,375,390,425,768,1024,1280,1440,1920]){
   await page.setViewportSize({width,height:1000});
   for(const route of routes){
    await page.goto(route);await expect(page.locator(".integration-page h1")).toBeVisible();
    await expect(page.locator(".integration-page [role=status]").filter({hasText:/Loading/})).toHaveCount(0);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy();
   }
   await page.goto("/settings/integrations");
   const card=page.locator(".integration-card").filter({has:page.getByRole("heading",{name:"Responsive connection "+locale,exact:true})});
   await expect(card).toBeVisible();await card.locator("button").first().click();
   await expect(page.locator(".integration-form")).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy();
  }
  expect(errors).toEqual([]);
 });
}
