import { test, expect, type APIRequestContext, type BrowserContext } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { newConfiguration } from "../../lib/compliance-master";
import { flattenMessages } from "../../i18n/messages";
const headers = { "X-Setu-Request": "1" };

async function platformLogin(request: APIRequestContext, context: BrowserContext) {
  const signup = await request.post("/api/v1/auth/signup", { headers, data: { name: "Master QA", workspace_name: "Template QA", email: "white-label-qa@example.test", password: "WhiteLabel-browser-QA-2026!" } });
  if (signup.status() === 409) expect((await request.post("/api/v1/auth/login", { headers, data: { email: "white-label-qa@example.test", password: "WhiteLabel-browser-QA-2026!" } })).ok()).toBeTruthy();
  else expect(signup.status()).toBe(201);
  expect((await request.patch("/api/v1/localization/preferences", { headers, data: { locale: "en-IN", timezone: "Asia/Kolkata", time_format: "12h" } })).ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
}

test("platform builder, rule preview, keyboard and pointer D&D, governance and snapshots", async ({ page, request, context }, testInfo) => {
  await platformLogin(request, context);
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message)); page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const category = await request.post("/api/v1/admin/compliance-categories", { headers, data: { name: "Sample browser category" } }); expect(category.status()).toBe(201);
  const organization = await request.post("/api/v1/organizations", { headers, data: { name: "Sample Browser Trust", legal_type: "TRUST", registration_number: "SAMPLE-QA", city: "Sample city", generate_compliance_plan: false } }); expect(organization.status()).toBe(201);
  const organizationId = (await organization.json()).organization.id;
  await page.goto("/admin/compliance-master/new");
  await page.getByLabel("Compliance name", { exact: true }).fill("Sample browser governance review");
  await page.locator('input[maxlength="40"]').fill("SAMPLE-BROWSER");
  await page.getByLabel("Jurisdiction", { exact: true }).fill("Sample jurisdiction");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/compliance-master\/[a-f0-9-]+$/);
  await expect(page.locator(".master-builder-panel")).toBeVisible();
  const id = page.url().split("/").at(-1)!;
  await page.getByRole("button", { name: /2.*Applicability/ }).click();
  await page.getByRole("button", { name: "Add rule group", exact: true }).click();
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Value (use internal values; lists are comma-separated)", { exact: true }).fill("TRUST");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Changes saved" })).toBeVisible();
  await page.getByRole("button", { name: "Search name, code, description, legal reference or tags", exact: true }).click();
  await page.getByLabel("Sample organization", { exact: true }).selectOption({ label: (await page.getByLabel("Sample organization", { exact: true }).locator("option").allTextContents()).find((text) => text.includes("Udaan"))! });
  await page.getByRole("button", { name: "Test applicability and deadline", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Applicable" })).toBeVisible();
  await page.getByRole("button", { name: /3.*Schedule and deadlines/ }).click();
  await page.getByLabel("Statutory deadline", { exact: true }).fill("2031-03-31");
  await page.getByRole("button", { name: /5.*Checklist/ }).click();
  for (const title of ["First sample check", "Second sample check", "Third sample check"]) {
    await page.getByRole("button", { name: "Add checklist item", exact: true }).click();
    await page.getByLabel("Checklist item title", { exact: true }).last().fill(title);
  }
  const handle = page.getByRole("button", { name: "Reorder item 1", exact: true }); await handle.focus(); await page.keyboard.press("Space"); await page.keyboard.press("ArrowDown"); await page.keyboard.press("Space");
  await expect(page.getByLabel("Checklist item title", { exact: true }).first()).toHaveValue("Second sample check");
  await page.setViewportSize({ width: 1280, height: 2400 });
  await page.locator(".master-builder-panel").scrollIntoViewIfNeeded();
  const handles = page.locator(".master-drag"); const first = await handles.first().boundingBox(); const third = await handles.nth(2).boundingBox();
  expect(first).not.toBeNull(); expect(third).not.toBeNull();
  await page.mouse.move(first!.x + 22, first!.y + 22); await page.mouse.down(); await page.mouse.move(first!.x + 32, first!.y + 22, { steps: 4 }); await page.mouse.move(third!.x + 22, third!.y + 22, { steps: 20 }); await page.mouse.up();
  await expect(page.getByLabel("Checklist item title", { exact: true }).first()).not.toHaveValue("Second sample check");
  await page.getByRole("button", { name: /10.*Localization/ }).click();
  await page.getByLabel("Language / locale", { exact: true }).selectOption("kn-IN");
  await page.getByLabel("Compliance name", { exact: true }).fill("ಮಾದರಿ ಆಡಳಿತ ಪರಿಶೀಲನೆ");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await page.getByRole("button", { name: /11.*Review and publish/ }).click();
  await page.getByRole("button", { name: "Validate configuration", exact: true }).click(); await expect(page.getByRole("heading", { name: "Ready for review", exact: true })).toBeVisible();
  page.on("dialog", (dialog) => dialog.accept());
  for (const action of ["Submit for review", "Approve", "Publish"]) { await page.getByRole("button", { name: action, exact: true }).click(); }
  await expect(page.getByRole("button", { name: "Create new version", exact: true })).toBeVisible();
  await expect(page.locator(".master-builder-panel>fieldset")).toBeDisabled();
  const generated = await request.post(`/api/v1/organizations/${organizationId}/generate-plan`, { headers }); expect(generated.ok()).toBeTruthy();
  const instance = (await generated.json()).find((item: { code: string }) => item.code === "SAMPLE-BROWSER"); expect(instance.template_version_id).toBeTruthy();
  const snapshot = await request.get(`/api/v1/compliances/${instance.id}/template-snapshot`); expect((await snapshot.json()).version).toBe(1);
  await page.getByRole("button", { name: "Version history", exact: true }).click(); await expect(page.getByRole("heading", { name: "Template audit log" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("compliance-master-review.png"), fullPage: true });
  expect(errors).toEqual([]);
  expect((await request.get(`/api/v1/admin/compliance-templates/${id}`)).ok()).toBeTruthy();
});

test("all template builder steps and master table remain responsive in four locales", async ({ page, request, context }, testInfo) => {
  test.setTimeout(420_000);
  await platformLogin(request, context);
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message)); page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const categories = await request.get("/api/v1/admin/compliance-categories"); const list = await categories.json();
  let categoryId = list[0]?.id;
  if (!categoryId) categoryId = (await (await request.post("/api/v1/admin/compliance-categories", { headers, data: { name: "Responsive sample" } })).json()).id;
  const configuration = newConfiguration(); configuration.name = "Long sample compliance template name for multilingual mobile layout verification"; configuration.category_id = categoryId; configuration.jurisdiction = "Sample jurisdiction";
  configuration.applicability.match_all = true; configuration.deadline.fixed_date = "2031-03-31";
  configuration.checklist = [{ id: "qa-check", title: "Sample checklist with a deliberately long user-facing title", description: "", instructions: "", required: true, responsible_role: "TENANT_ADMIN", relative_due_days: -1 }];
  configuration.documents = [{ id: "qa-doc", document_type: "Sample evidence", required: true, minimum_count: 1, must_be_valid: true, instructions: "" }];
  configuration.reminders = [{ id: "qa-remind", offset_days: -1, channel: "IN_APP", recipient_role: "TENANT_ADMIN", escalation_level: 0, enabled: true, text: "" }];
  const created = await request.post("/api/v1/admin/compliance-templates", { headers, data: { code: "SAMPLE-RESPONSIVE", configuration } }); expect(created.status()).toBe(201);
  const row = await created.json();
  for (const locale of ["en-IN", "hi-IN", "kn-IN", "mr-IN"]) {
    await page.goto("about:blank");
    const english = flattenMessages(JSON.parse(readFileSync(path.resolve("messages/en-IN/compliance-master.json"), "utf8")));
    const selected = flattenMessages(JSON.parse(readFileSync(path.resolve(`messages/${locale}/compliance-master.json`), "utf8")));
    expect(Object.keys(selected).sort()).toEqual(Object.keys(english).sort());
    expect(Object.values(selected).every((value) => value.trim())).toBeTruthy();
    expect((await request.patch("/api/v1/localization/preferences", { headers, data: { locale, timezone: "Asia/Kolkata", time_format: "12h" } })).ok()).toBeTruthy();
    await context.addCookies([{ name: "SETU_LOCALE", value: locale, domain: "localhost", path: "/" }]);
    for (const width of [320, 360, 375, 390, 425, 768, 1024, 1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 }); await page.goto(`/admin/compliance-master/${row.id}`);
      await expect(page.locator(".master-builder-panel")).toBeVisible();
      for (let step = 0; step < 11; step++) {
        if (width < 768) await page.locator(".master-mobile-step select").selectOption(String(step));
        else await page.locator(".master-step-nav ol button").nth(step).click();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
        expect(await page.locator(".master-builder-panel").evaluate((element) => element.getBoundingClientRect().right <= innerWidth + 1)).toBeTruthy();
      }
      if (width === 320) await page.screenshot({ path: testInfo.outputPath(`${locale}-320-builder.png`), fullPage: true });
      await page.goto("/admin/compliance-master"); await expect(page.locator(".master-table")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
    }
  }
  expect(errors).toEqual([]);
});

test("tenant accounts cannot open the platform builder or write global templates", async ({ page, request, context }) => {
  const signup = await request.post("/api/v1/auth/signup", { headers, data: { name: "Tenant QA", workspace_name: "Tenant restriction QA", email: "tenant-master-qa@example.test", password: "Tenant-browser-QA-2026!" } }); expect(signup.status()).toBe(201);
  await context.addCookies((await request.storageState()).cookies);
  await page.goto("/admin/compliance-master/new"); await expect(page).toHaveURL(/\/dashboard$/);
  expect((await request.get("/api/v1/admin/compliance-templates")).status()).toBe(403);
  expect((await request.post("/api/v1/admin/compliance-templates", { headers, data: { code: "NO-ACCESS", configuration: newConfiguration() } })).status()).toBe(403);
  await page.goto("/admin"); await expect(page.locator(".platform-navigation")).toHaveCount(0);
});
