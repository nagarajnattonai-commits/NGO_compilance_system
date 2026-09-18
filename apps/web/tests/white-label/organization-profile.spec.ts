import {test,expect} from "@playwright/test";
const headers={"X-Setu-Request":"1"};
test("organization profile edits persist, cancel protects drafts and branded layouts fit all viewports",async({page,request,context})=>{
 const email="profile-browser@example.test",password="Profile-browser-QA-2026!";
 expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"Profile tester",workspace_name:"Profile QA",email,password}})).status()).toBe(201);
 expect((await request.post("/api/v1/auth/login",{headers,data:{email,password}})).ok()).toBeTruthy();
 const created=await request.post("/api/v1/organizations",{headers,data:{name:"Sample Profile NGO",legal_type:"TRUST",registration_number:"PROFILE-QA",city:"Sample City",generate_compliance_plan:false}});expect(created.status()).toBe(201);
 const id=(await created.json()).organization.id;await context.addCookies((await request.storageState()).cookies);
 const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
 await page.goto(`/organizations/${id}`);await expect(page.getByRole("heading",{name:"Sample Profile NGO",exact:true})).toBeVisible();
 await page.getByRole("tab",{name:"Basic information",exact:true}).click();await page.getByRole("button",{name:"Edit profile",exact:true}).click();await page.getByLabel("Organization name",{exact:true}).fill("Updated Sample Profile NGO");
 page.once("dialog",d=>d.dismiss());await page.getByRole("tab",{name:"Registration",exact:true}).click();await expect(page.getByLabel("Organization name",{exact:true})).toHaveValue("Updated Sample Profile NGO");
 await page.getByRole("button",{name:"Save",exact:true}).click();await expect(page.getByRole("status").filter({hasText:"Profile saved"})).toBeVisible();
 await page.getByRole("tab",{name:"Registration",exact:true}).click();await page.getByRole("button",{name:"Edit profile",exact:true}).click();await page.getByLabel("Registration date",{exact:true}).fill("2020-01-01");await page.getByLabel("Registration authority",{exact:true}).fill("Sample authority");await page.getByRole("button",{name:"Save",exact:true}).click();await expect(page.getByRole("status").filter({hasText:"Profile saved"})).toBeVisible();
 await page.reload();await expect(page.getByRole("heading",{name:"Updated Sample Profile NGO",exact:true})).toBeVisible();
 for(const locale of ["en-IN","hi-IN","kn-IN","mr-IN"]) {
  expect((await request.patch("/api/v1/localization/preferences",{headers,data:{locale,timezone:"Asia/Kolkata",time_format:"12h"}})).ok()).toBeTruthy();await page.reload();
  for(const width of [320,768,1024,1440]){await page.setViewportSize({width,height:900});await expect(page.getByRole("heading",{name:"Updated Sample Profile NGO",exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();}
 }
 expect(errors).toEqual([]);
});
