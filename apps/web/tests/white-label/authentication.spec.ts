import {test,expect,type APIRequestContext} from "@playwright/test";
import {execFileSync} from "node:child_process";
import path from "node:path";
import {readFileSync} from "node:fs";
import {flattenMessages} from "../../i18n/messages";
import {localeCookieName} from "../../i18n/config";
import {provisionPlatformOperator,cleanSignupFixtureQuota} from "./platform-operator";
test.afterAll(()=>cleanSignupFixtureQuota());
test.setTimeout(60_000);
const headers={"X-Setu-Request":"1"};const password="Auth-browser-testing-QA-2026!";
async function signup(request:APIRequestContext,email:string){
 const result=await request.post("/api/v1/auth/signup",{headers,data:{name:"Authentication QA",workspace_name:"Auth QA",email,password}});
 expect(result.status()).toBe(201);return result.json();
}
function fixtureToken(email:string,purpose:"VERIFY"|"RESET"){
 const database=process.env.SETU_QA_DATABASE_URL;
 if(!database||!database.includes("setu-white-label-qa-"))throw new Error("Requires isolated QA database");
 const script=[
 "import sys","from sqlalchemy import select","from app.database import SessionLocal","from app.models import User",
 "from app.auth_models import AuthAccount","from app.auth import issue_token",
 "with SessionLocal() as db:",
 "    user=db.scalar(select(User).where(User.email==sys.argv[1]))",
 "    account=db.get(AuthAccount,user.id)",
 "    if sys.argv[2]=='VERIFY':account.verified=False;account.verification_required=True",
 "    token=issue_token(db,user,sys.argv[2],1)",
 "    db.commit()","    print(token)"
 ].join("\n");
 return execFileSync(process.env.API_PYTHON || path.resolve(process.platform==="win32"?"../api/.venv/Scripts/python.exe":"../api/.venv/bin/python"),["-c",script,email,purpose],{cwd:path.resolve("../api"),env:{...process.env,DATABASE_URL:database},windowsHide:true}).toString().trim();
}
test("user login validation, remember me, server admin denial and logout",async({page,request,context})=>{
 await signup(request,"auth-browser-login@example.test");
 const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
 await page.goto("/login");await expect(page.getByRole("heading",{name:"Welcome back",exact:true})).toBeVisible();
 await page.getByRole("button",{name:"Sign in",exact:true}).click();
 await expect(page.locator(".field-error").first()).toContainText("required");
 await page.getByLabel("Email address",{exact:true}).fill("auth-browser-login@example.test");
 await page.getByLabel("Password",{exact:true}).fill("wrong-password");
 await page.getByRole("button",{name:"Sign in",exact:true}).click();await expect(page.locator(".auth-card [role=alert]")).toContainText("Invalid email or password");
 await page.getByLabel("Password",{exact:true}).fill(password);
 await page.getByRole("button",{name:"Show password",exact:true}).click();await expect(page.getByLabel("Password",{exact:true})).toHaveAttribute("type","text");
 await page.getByLabel("Remember me",{exact:true}).check();
 await page.getByRole("button",{name:"Sign in",exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/);
 const cookie=(await context.cookies()).find(c=>c.name==="setu_session");expect(cookie?.httpOnly).toBeTruthy();expect(cookie?.expires).toBeGreaterThan(Date.now()/1000);
 await page.goto("/admin");await expect(page.getByRole("heading",{name:"Access denied"})).toBeVisible();
 await page.goto("/dashboard");await page.locator(".sidebar-account-links").getByRole("button",{name:/Sign out/i}).click();
 await expect(page).toHaveURL(/\/login$/);expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
 expect(errors).toEqual([]);
});

test("distinct platform login requires provisioned operator and has no public signup",async({page,request})=>{
 const credentials={email:"white-label-qa@example.test",password:"WhiteLabel-browser-QA-2026!"};
 let response=await request.post("/api/v1/auth/login",{headers,data:credentials});
 if(response.status()===401){response=await request.post("/api/v1/auth/signup",{headers,data:{name:"Auth Operator",workspace_name:"Auth Operator",...credentials}});expect(response.status()).toBe(201);}
 await provisionPlatformOperator(request);
 await page.goto("/admin/login");
 await expect(page.getByRole("heading",{name:"Platform Administration",exact:true})).toBeVisible();
 await expect(page.locator(".auth-product-panel")).toHaveCount(0);await expect(page.getByRole("link",{name:"Create account",exact:true})).toHaveCount(0);
 await page.getByLabel("Email address",{exact:true}).fill(credentials.email);await page.getByLabel("Password",{exact:true}).fill(credentials.password);
 await page.getByRole("button",{name:"Sign in to Admin Console",exact:true}).click();await expect(page).toHaveURL(/\/admin$/);
 await page.goto("/admin/login");await expect(page).toHaveURL(/\/admin$/);
 await page.locator(".sidebar-account-links").getByRole("button",{name:/Sign out/i}).click();await expect(page).toHaveURL(/\/admin\/login$/);
});

test("verification and reset use single-use links, clear fragments and show success",async({page,request})=>{
 const email="auth-browser-links@example.test";await signup(request,email);
 const verification=fixtureToken(email,"VERIFY");
 await page.goto("/verify-email#token="+verification);
 await expect(page).toHaveURL(/\/verify-email$/);await page.getByRole("button",{name:"Verify email",exact:true}).click();
 await expect(page.getByRole("status")).toContainText("Email verified");await expect(page.getByRole("link",{name:"Continue to sign in",exact:true})).toBeVisible();
 const reset=fixtureToken(email,"RESET");
 await page.goto("/reset-password#token="+reset);await expect(page).toHaveURL(/\/reset-password$/);
 await page.getByLabel("New password",{exact:true}).fill(password+"new");await expect(page.getByLabel("New password",{exact:true})).toHaveValue(password+"new");await page.getByLabel("Confirm password",{exact:true}).fill(password+"new");
 await page.getByRole("button",{name:"Reset password",exact:true}).click();await expect(page.getByRole("status")).toContainText("Password updated");
 await page.goto("/reset-password#token="+reset);
 await page.getByLabel("New password",{exact:true}).fill(password+"newer");await page.getByLabel("Confirm password",{exact:true}).fill(password+"newer");
 await page.getByRole("button",{name:"Reset password",exact:true}).click();await expect(page.locator(".auth-card [role=alert]")).toContainText("already used");
});

test("signup validates both steps and preserves fields across a backend outage",async({page})=>{
 await page.goto("/signup");
 await page.getByLabel("Full name",{exact:true}).fill("Signup Browser");
 await page.getByLabel("Email address",{exact:true}).fill("auth-browser-signup@example.test");
 await page.getByLabel("New password",{exact:true}).fill(password);
 await page.getByLabel("Confirm password",{exact:true}).fill(password);
 await page.getByRole("button",{name:"Continue to organization",exact:true}).click();
 await page.getByLabel("Organization name",{exact:true}).fill("Browser Trust");
 await page.getByLabel("Organization type",{exact:true}).selectOption("TRUST");
 await page.getByRole("button",{name:"Create account",exact:true}).click();await expect(page.locator(".field-error")).toContainText("Accept the terms");
 await page.getByLabel("I agree to the Terms of Service and Privacy Policy.",{exact:false}).check();
 await page.route("**/api/v1/auth/signup",route=>route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"Unavailable"})}));
 await page.getByRole("button",{name:"Create account",exact:true}).click();await expect(page.locator(".auth-card [role=alert]")).toContainText("temporarily unavailable");
 await expect(page.getByLabel("Organization name",{exact:true})).toHaveValue("Browser Trust");
 await page.getByRole("button",{name:"Back",exact:true}).click();await expect(page.getByLabel("Full name",{exact:true})).toHaveValue("Signup Browser");
});

for(const locale of ["en-IN","hi-IN","kn-IN","mr-IN"]){
 test("auth pages reuse design and fit all viewport widths in "+locale,async({page,context},testInfo)=>{
  test.setTimeout(420_000);
  const read=(language:string)=>JSON.parse(readFileSync(path.resolve("messages",language,"authentication.json"),"utf8"));
  expect(Object.keys(flattenMessages(read(locale))).sort()).toEqual(Object.keys(flattenMessages(read("en-IN"))).sort());
  await context.addCookies([{name:localeCookieName,value:locale,domain:"localhost",path:"/"}]);
  const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",m=>{if(m.type()==="error")errors.push(m.text());});
  const routes=["/login","/signup","/forgot-password","/reset-password","/verify-email","/accept-invitation","/admin/login","/admin/forgot-password","/admin/reset-password","/auth/change-email"];
  for(const width of [320,360,375,390,425,768,1024,1280,1440,1920]){
   await page.setViewportSize({width,height:1000});
   for(const route of routes){await page.goto(route);await expect(page.locator(".auth-card h1")).toBeVisible();await expect(page.locator("html")).toHaveAttribute("lang",locale);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();}
  }
  await page.goto("/login");await page.locator(".theme-toggle").click();
  const colors=await page.locator(".auth-card").evaluate(element=>({background:getComputedStyle(element).backgroundColor,text:getComputedStyle(element).color}));
  expect(colors.background).not.toBe(colors.text);
  await page.screenshot({path:testInfo.outputPath("authentication-"+locale+".png"),fullPage:true});
  expect(errors).toEqual([]);
 });
}
