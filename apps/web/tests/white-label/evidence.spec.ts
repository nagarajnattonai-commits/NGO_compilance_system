import {test,expect} from "@playwright/test";
import path from "node:path";
import {readFileSync} from "node:fs";
const headers={"X-Setu-Request":"1"};
test("private evidence uploads original bytes, renews, retains downloads and archives without deleting history",async({page,request,context})=>{
 const email="evidence-browser@example.test",password="Evidence-browser-QA-2026!";
 expect((await request.post("/api/v1/auth/signup",{headers,data:{name:"Evidence tester",workspace_name:"Evidence QA",email,password}})).status()).toBe(201);expect((await request.post("/api/v1/auth/login",{headers,data:{email,password}})).ok()).toBeTruthy();
 const created=await request.post("/api/v1/organizations",{headers,data:{name:"Sample Evidence NGO",legal_type:"TRUST",registration_number:"EVIDENCE-QA",city:"Sample City",generate_compliance_plan:false}});expect(created.status()).toBe(201);const id=(await created.json()).organization.id;
 await context.addCookies((await request.storageState()).cookies);const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
 await page.goto(`/organizations/${id}`);await page.getByRole("tab",{name:"Documents",exact:true}).click();
 await page.getByLabel("Choose file",{exact:true}).setInputFiles(path.resolve("tests/fixtures/proof.png"));await page.getByLabel("Document category / required type",{exact:true}).fill("Sample Certificate");await page.getByLabel("Expiry date",{exact:true}).fill("2030-01-01");await page.getByRole("button",{name:"Upload original file",exact:true}).click();
 await expect(page.getByRole("status").filter({hasText:"Original file stored"})).toBeVisible();await page.getByRole("button",{name:/proof.png.*Sample Certificate.*Available/}).click();
 await expect(page.getByRole("heading",{name:"File version history",exact:true})).toBeVisible();await expect(page.getByText(/Scan status: Not scanned/)).toBeVisible();
 const docs=await (await request.get(`/api/v1/documents?organization_id=${id}`)).json();const doc=docs[0];expect(await (await request.get(`/api/v1/documents/${doc.id}/content`)).body()).toEqual(readFileSync(path.resolve("tests/fixtures/proof.png")));
 const downloadPromise=page.waitForEvent("download");await page.getByRole("link",{name:"Download original",exact:true}).first().click();expect((await downloadPromise).suggestedFilename()).toBe("proof.png");
 await page.getByRole("button",{name:"Preview image",exact:true}).click();await expect(page.getByRole("img",{name:"proof.png",exact:true})).toBeVisible();await page.getByRole("button",{name:"Close preview",exact:true}).click();
 const renewal=page.locator("form").filter({has:page.getByRole("button",{name:"Upload renewal / new version",exact:true})});await renewal.getByLabel("Choose file",{exact:true}).setInputFiles(path.resolve("tests/fixtures/proof-renewed.png"));await renewal.getByLabel("Expiry date",{exact:true}).fill("2031-01-01");await renewal.getByRole("button",{name:"Upload renewal / new version",exact:true}).click();await expect(page.getByText("Version 2: proof-renewed.png",{exact:true})).toBeVisible();
 const bundle=await (await request.get(`/api/v1/documents/${doc.id}/files`)).json();expect(bundle.files).toHaveLength(2);expect(await (await request.get(`/api/v1/documents/${doc.id}/content?version_id=${bundle.files[1].version_id}`)).body()).toEqual(readFileSync(path.resolve("tests/fixtures/proof.png")));
 page.once("dialog",d=>d.accept());await page.getByRole("button",{name:"Archive document",exact:true}).click();await expect(page.getByRole("button",{name:"Restore document",exact:true})).toBeVisible();expect((await request.get(`/api/v1/documents/${doc.id}/files`)).ok()).toBeTruthy();
 for(const width of [320,768,1024,1440]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();}
 expect(errors).toEqual([]);
});
