import { expect, test } from "@playwright/test";

const headers = { "X-Setu-Request": "1" };
const credentials = { email: "phase20-import@example.test", password: "Phase20-import-QA-2026!" };

test("bulk onboarding requires dry-run review and explicit confirmation", async ({ page, request, context }) => {
  expect((await request.post("/api/v1/auth/signup", { headers, data: {
    name: "Import Administrator", workspace_name: "Import QA", ...credentials,
  } })).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login", { headers, data: credentials })).ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
  const registration = `UI-IMPORT-${Date.now()}`;
  const csv = `name,legal_type,registration_number,city,contact_email\nUI Imported NGO,TRUST,${registration},Pune,client@example.test\n`;

  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Administration", exact: true }).click();
  const importer = page.getByRole("region", { name: "Bulk NGO onboarding and imports" });
  await expect(importer.getByRole("heading", { name: "Bulk NGO onboarding and imports" })).toBeVisible();
  await importer.getByLabel("CSV or XLSX file").setInputFiles({ name: "organizations.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await importer.getByRole("button", { name: "Upload for review" }).click();
  await expect(importer.getByText("Uploaded", { exact: true })).toBeVisible();
  await expect(importer.getByRole("button", { name: "Confirm Import" })).toBeDisabled();

  const before = await request.get("/api/v1/organizations");
  expect((await before.json()).some((item: { registration_number: string }) => item.registration_number === registration)).toBeFalsy();
  await importer.getByRole("button", { name: "Run dry validation" }).click();
  await expect(importer.getByText("Ready to import", { exact: true })).toBeVisible();
  await expect(importer.getByText("Valid rows", { exact: true }).locator("..")).toContainText("1");
  await importer.getByRole("button", { name: "Confirm Import" }).click();
  await expect(importer.getByText("Completed", { exact: true })).toBeVisible();
  await expect(importer.getByRole("link", { name: "Download result CSV" })).toBeVisible();

  const after = await request.get("/api/v1/organizations");
  expect((await after.json()).some((item: { registration_number: string }) => item.registration_number === registration)).toBeTruthy();
});
