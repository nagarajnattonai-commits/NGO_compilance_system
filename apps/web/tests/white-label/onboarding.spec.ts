import {test,expect} from "@playwright/test";
const headers={"X-Setu-Request":"1"};
test("new customer can create, save, resume, review, evaluate and finish onboarding",async({page,request,context})=>{
 const email="onboarding-browser@example.test",password="Onboarding-browser-QA-2026!";
 expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"Onboarding tester",workspace_name:"Onboarding QA",email,password}})).status()).toBe(201);expect((await request.post("/api/v1/auth/login",{headers,data:{email,password}})).ok()).toBeTruthy();await context.addCookies((await request.storageState()).cookies);
 const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
 await page.goto("/onboarding");await page.getByLabel("Organization name",{exact:true}).fill("Sample Onboarding NGO");await page.getByLabel("Registration number",{exact:true}).fill("ONBOARDING-QA");await page.getByLabel("City",{exact:true}).fill("Sample City");await page.getByRole("button",{name:"Create organization & continue",exact:true}).click();await expect(page.getByRole("heading",{name:"Organization basics",exact:true})).toBeVisible();
 await page.getByLabel("Primary contact name",{exact:true}).fill("Sample contact");await page.getByRole("button",{name:"Save & exit",exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/);await page.getByRole("link",{name:"Resume setup",exact:true}).click();await expect(page.getByLabel("Primary contact name",{exact:true})).toHaveValue("Sample contact");
 for(const step of ["Registration & tax","Compliance registrations","Financial information","Documents","Team","Review","Compliance evaluation"]){await page.getByRole("button",{name:"Save & continue",exact:true}).click();await expect(page.getByRole("heading",{name:step,exact:true})).toBeVisible();}
 await page.getByRole("button",{name:"Evaluate published templates",exact:true}).click();await expect(page.getByText("No published templates are available.",{exact:false})).toBeVisible();await page.getByRole("button",{name:"Complete setup & generate plan",exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/);await expect(page.getByRole("link",{name:"Resume setup",exact:true})).toHaveCount(0);
 const states=await (await request.get("/api/v1/onboarding")).json();expect(states[0].status).toBe("COMPLETED");expect(states[0].completed_at).toBeTruthy();expect(errors).toEqual([]);
});
