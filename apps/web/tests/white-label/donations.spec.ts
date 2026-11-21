import { test, expect } from "@playwright/test";
import { cleanSignupFixtureQuota } from "./platform-operator";
test.afterAll(() => cleanSignupFixtureQuota());
const headers = { "X-Setu-Request": "1" };

test("donation register records, confirms and receipts a donation and prepares the yearly statement", async ({ page, request, context }, testInfo) => {
  cleanSignupFixtureQuota();
  const email = "donations-browser@example.test", password = "Donations-browser-QA-2026!";
  expect((await request.post("/api/v1/auth/signup", { headers, data: { name: "Donations tester", workspace_name: "Donations QA", email, password } })).status()).toBe(201);
  expect((await request.post("/api/v1/auth/login", { headers, data: { email, password } })).ok()).toBeTruthy();
  const created = await request.post("/api/v1/organizations", { headers, data: { name: "Sample Donations NGO", legal_type: "TRUST", registration_number: "DONATIONS-QA", city: "Sample City", generate_compliance_plan: false } });
  expect(created.status()).toBe(201);
  const id = (await created.json()).organization.id;
  await context.addCookies((await request.storageState()).cookies);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/organizations/${id}`);
  await page.getByRole("tab", { name: "Donations", exact: true }).click();
  await expect(page.getByText("pending review by a chartered accountant", { exact: false })).toBeVisible();

  await page.getByRole("tab", { name: "Bank accounts", exact: true }).click();
  await page.getByLabel("Account name", { exact: true }).fill("Main savings");
  await page.getByLabel("Last 4 digits", { exact: true }).fill("4321");
  await page.getByRole("button", { name: "Add account", exact: true }).click();
  await expect(page.getByText("Main savings", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "Donors", exact: true }).click();
  await page.getByLabel("Donor name", { exact: true }).fill("Asha Sample");
  await page.getByRole("combobox", { name: /^Identity number type/ }).selectOption("PAN");
  await page.getByLabel("PAN or Aadhaar", { exact: true }).fill("ABCPA1234Z");
  await page.getByLabel("Address", { exact: true }).fill("4 Sample Lane, Pune");
  await page.getByRole("button", { name: "Add donor", exact: true }).click();
  await expect(page.getByText("PAN ••••••234Z", { exact: false })).toBeVisible();
  await expect(page.getByText("ABCPA1234Z")).toHaveCount(0);
  await page.getByRole("button", { name: "Reveal", exact: true }).click();
  await expect(page.getByText("ABCPA1234Z", { exact: false })).toBeVisible();

  await page.getByRole("tablist", { name: "Donations" }).getByRole("tab", { name: "Donations", exact: true }).click();
  const today = new Date().toISOString().slice(0, 10);
  await page.getByLabel("Received on", { exact: true }).fill(today);
  await page.getByLabel("Amount", { exact: true }).fill("2500");
  await page.getByRole("combobox", { name: /^Received in/ }).selectOption({ label: "Main savings · Domestic" });
  await page.getByRole("button", { name: "Record donation", exact: true }).click();
  const row = page.locator("tr").filter({ hasText: "Asha Sample" });
  await expect(row.getByText("Draft", { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(row.getByText("Confirmed", { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "Issue receipt", exact: true }).click();
  await expect(row.getByText(/RCPT\/\d{4}-\d{2}\/0001/)).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "80G registration is not active and verified" })).toBeVisible();

  await page.getByRole("tab", { name: "Yearly statement", exact: true }).click();
  await expect(page.getByText("Confirmed donations", { exact: true })).toBeVisible();
  await expect(page.getByText("Every donor has an identity number and address.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Prepare statement and create tasks", exact: true }).click();
  await expect(page.getByRole("button", { name: "Mark as filed", exact: true })).toBeVisible();

  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${width}px must not overflow`).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`donations-${width}.png`), fullPage: true });
  }
  expect(errors).toEqual([]);
});
