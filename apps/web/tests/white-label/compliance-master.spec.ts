import { test, expect, type APIRequestContext, type BrowserContext } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { emptyTranslation, newConfiguration } from "../../lib/compliance-master";
import { flattenMessages } from "../../i18n/messages";
const headers = { "X-Setu-Request": "1" };

async function platformLogin(request: APIRequestContext, context: BrowserContext) {
  // Reuse the account: repeated duplicate signup attempts consume the production rate limit.
  const credentials = { email: "white-label-qa@example.test", password: "WhiteLabel-browser-QA-2026!" };
  const login = await request.post("/api/v1/auth/login", { headers, data: credentials });
  if (login.status() === 401) {
    const signup = await request.post("/api/v1/auth/signup", { headers, data: { name: "Master QA", workspace_name: "Template QA", ...credentials } });
    expect(signup.status()).toBe(201);
  } else expect(login.ok()).toBeTruthy();
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
  await page.getByRole("button", { name: /3.*Schedule and deadlines/ }).click();
  await page.getByLabel("Statutory deadline", { exact: true }).fill("2031-03-31");
  await page.getByRole("button", { name: /2.*Applicability/ }).click();
  await page.getByRole("button", { name: "Add rule group", exact: true }).click();
  await page.getByRole("button", { name: "Add condition", exact: true }).click();
  await page.getByLabel("Value (use internal values; lists are comma-separated)", { exact: true }).fill("TRUST");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Changes saved" })).toBeVisible();
  await page.getByRole("button", { name: "Search name, code, description, legal reference or tags", exact: true }).click();
  const sampleOrganization = page.getByLabel("Sample organization", { exact: true });
  await expect(sampleOrganization.locator("option").filter({ hasText: "Udaan" })).toHaveCount(1);
  await sampleOrganization.selectOption({ label: (await sampleOrganization.locator("option").filter({ hasText: "Udaan" }).textContent())! });
  await page.getByRole("button", { name: "Test applicability and deadline", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Applicable" })).toBeVisible();
  await page.getByRole("button", { name: /3.*Schedule and deadlines/ }).click();
  await page.getByLabel("Statutory deadline", { exact: true }).fill("2031-03-31");
  await page.getByRole("button", { name: /5.*Checklist/ }).click();
  for (const title of ["First sample check", "Second sample check", "Third sample check"]) {
    await page.getByRole("button", { name: "Add checklist item", exact: true }).click();
    await page.getByLabel("Checklist item title", { exact: true }).last().fill(title);
  }
  await page.setViewportSize({ width: 1280, height: 2400 });
  const handle = page.getByRole("button", { name: "Reorder item 1", exact: true });
  await handle.scrollIntoViewIfNeeded(); await handle.focus();
  const dragStartTop = (await handle.boundingBox())!.y;
  await page.keyboard.press("Space");
  await expect(handle).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("ArrowDown");
  await expect.poll(async () => (await handle.boundingBox())?.y ?? 0).toBeGreaterThan(dragStartTop + 1);
  await page.keyboard.press("Space");
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
  await expect(page.locator(".master-builder-panel>fieldset")).toHaveAttribute("disabled", "");
  const generated = await request.post(`/api/v1/organizations/${organizationId}/generate-plan`, { headers }); expect(generated.ok()).toBeTruthy();
  const instance = (await generated.json()).find((item: { code: string }) => item.code === "SAMPLE-BROWSER"); expect(instance.template_version_id).toBeTruthy();
  const snapshot = await request.get(`/api/v1/compliances/${instance.id}/template-snapshot`); expect((await snapshot.json()).version).toBe(1);
  await page.getByRole("button", { name: "Version history", exact: true }).click(); await expect(page.getByRole("heading", { name: "Template audit log" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("compliance-master-review.png"), fullPage: true });
  expect(errors).toEqual([]);
  expect((await request.get(`/api/v1/admin/compliance-templates/${id}`)).ok()).toBeTruthy();
});

for (const locale of ["en-IN", "hi-IN", "kn-IN", "mr-IN"]) {
test("all template builder steps and master table remain responsive in " + locale, async ({ page, request, context }, testInfo) => {
  test.setTimeout(240_000);
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
  const created = await request.post("/api/v1/admin/compliance-templates", { headers, data: { code: "SAMPLE-RESPONSIVE-" + locale.toUpperCase(), configuration } }); expect(created.status()).toBe(201);
  const row = await created.json();
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
        if (width < 768) await page.locator(".master-mobile-step select").selectOption(String(step), { timeout: 15_000 });
        else await page.locator(".master-step-nav ol button").nth(step).click();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
        expect(await page.locator(".master-builder-panel").evaluate((element) => element.getBoundingClientRect().right <= innerWidth + 1)).toBeTruthy();
      }
      if (width === 320) await page.screenshot({ path: testInfo.outputPath(`${locale}-320-builder.png`), fullPage: true });
      await page.goto("/admin/compliance-master"); await expect(page.locator(".master-table")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
    }
  expect(errors).toEqual([]);
});
}

test("tenant accounts cannot open the platform builder or write global templates", async ({ page, request, context }) => {
  const signup = await request.post("/api/v1/auth/signup", { headers, data: { name: "Tenant QA", workspace_name: "Tenant restriction QA", email: "tenant-master-qa@example.test", password: "Tenant-browser-QA-2026!" } }); expect(signup.status()).toBe(201);
  await context.addCookies((await request.storageState()).cookies);
  await page.goto("/admin/compliance-master/new"); await expect(page).toHaveURL(/\/dashboard$/);
  expect((await request.get("/api/v1/admin/compliance-templates")).status()).toBe(403);
  expect((await request.post("/api/v1/admin/compliance-templates", { headers, data: { code: "NO-ACCESS", configuration: newConfiguration() } })).status()).toBe(403);
  await page.goto("/admin"); await expect(page.locator(".platform-navigation")).toHaveCount(0);
});


test("incomplete rules, translated checklist removal and recoverable saves preserve draft data", async ({ page, request, context }) => {
  await platformLogin(request, context);
  const category = await request.post("/api/v1/admin/compliance-categories", { headers, data: { name: "Draft safety sample" } });
  expect(category.status()).toBe(201);
  const configuration = newConfiguration();
  configuration.name = "Sample editable draft";
  configuration.category_id = (await category.json()).id;
  configuration.jurisdiction = "Sample jurisdiction";
  configuration.deadline.fixed_date = "2031-03-31";
  configuration.applicability.groups = [{ id: "g", operator: "AND", conditions: [{ id: "r", field: "legal_type", operator: "EQUALS", value: "" }] }];
  configuration.checklist = [{ id: "old", title: "Obsolete sample item", description: "Description", instructions: "Instructions", required: true, responsible_role: "TENANT_ADMIN", relative_due_days: 0 }];
  configuration.translations["kn-IN"] = { ...emptyTranslation(), name: "Translated sample",
    checklist: { old: "Translated title" }, checklist_descriptions: { old: "Translated description" }, checklist_instructions: { old: "Translated instructions" } };
  const created = await request.post("/api/v1/admin/compliance-templates", { headers, data: { code: "SAMPLE-DRAFT-SAFETY", configuration } });
  expect(created.status()).toBe(201);
  const row = await created.json();
  const endpoint = "/api/v1/admin/compliance-templates/" + row.id;
  await page.goto("/admin/compliance-master/" + row.id);
  await page.getByRole("button", { name: /11.*Review and publish/ }).click();
  await page.getByRole("button", { name: "Validate configuration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Configuration needs correction" })).toBeVisible();
  await page.getByRole("button", { name: /2.*Applicability/ }).click();
  await page.getByLabel("Explicitly apply to all organizations").check();
  await page.getByRole("button", { name: /10.*Localization/ }).click();
  await page.getByLabel("Language / locale", { exact: true }).selectOption("kn-IN");
  await expect(page.getByLabel("Instructions: Obsolete sample item", { exact: true })).toHaveValue("Translated instructions");
  await page.getByRole("button", { name: /5.*Checklist/ }).click();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Changes saved" })).toBeVisible();
  const saved = await (await request.get(endpoint)).json();
  expect(saved.configuration.translations["kn-IN"].checklist).toEqual({});
  expect(saved.configuration.translations["kn-IN"].checklist_descriptions).toEqual({});
  expect(saved.configuration.translations["kn-IN"].checklist_instructions).toEqual({});
  await page.getByRole("button", { name: /11.*Review and publish/ }).click();
  await page.getByRole("button", { name: "Validate configuration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ready for review" })).toBeVisible();
  await page.getByRole("button", { name: /1.*Basic information/ }).first().click();
  await page.getByLabel("Compliance name", { exact: true }).fill("Unsaved name survives a failed request");
  await page.route("**" + endpoint, async (route) => {
    if (route.request().method() === "PATCH") await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Simulated temporary outage" }) });
    else await route.continue();
  });
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The action failed." })).toBeVisible();
  await expect(page.getByLabel("Compliance name", { exact: true })).toHaveValue("Unsaved name survives a failed request");
  await page.unroute("**" + endpoint);
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Changes saved" })).toBeVisible();
  expect((await (await request.get(endpoint)).json()).name).toBe("Unsaved name survives a failed request");
});

test("platform actions follow the permissions exposed by the server", async ({ page, request, context }) => {
  await platformLogin(request, context);
  await page.route("**/api/v1/admin/compliance-master/access", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { allowed: true, permissions: ["compliance_master.view"] } });
  });
  await page.goto("/admin/compliance-master");
  await expect(page.locator(".master-table")).toBeVisible();
  await expect(page.getByRole("link", { name: "Create compliance template", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Clone template", exact: true })).toHaveCount(0);
  await page.route("**/api/v1/admin/compliance-master/metadata", async (route) => {
    const response = await route.fetch();
    const metadata = await response.json();
    await route.fulfill({ response, json: { ...metadata, permissions: ["compliance_master.view"] } });
  });
  const listing = await (await request.get("/api/v1/admin/compliance-templates")).json();
  expect(listing.items.length).toBeGreaterThan(0);
  await page.goto("/admin/compliance-master/" + listing.items[0].id);
  await expect(page.locator(".master-builder-panel>fieldset")).toHaveAttribute("disabled", "");
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Create new version", exact: true })).toHaveCount(0);
});


test("touch drag handles reorder checklist items on a mobile viewport", async ({ request, browser }) => {
  const mobile = await browser.newContext({ baseURL: "http://localhost:3001", hasTouch: true, isMobile: true, viewport: { width: 390, height: 2200 } });
  try {
    await platformLogin(request, mobile);
    const categories = await (await request.get("/api/v1/admin/compliance-categories")).json();
    const configuration = newConfiguration();
    configuration.name = "Sample touch ordering";
    configuration.category_id = categories[0].id;
    configuration.jurisdiction = "Sample jurisdiction";
    configuration.applicability.match_all = true;
    configuration.deadline.fixed_date = "2031-03-31";
    configuration.checklist = ["First touch sample", "Second touch sample"].map((title, index) => ({
      id: "touch-" + index, title, description: "", instructions: "", required: true, responsible_role: "TENANT_ADMIN", relative_due_days: 0,
    }));
    const created = await request.post("/api/v1/admin/compliance-templates", { headers, data: { code: "SAMPLE-TOUCH", configuration } });
    expect(created.status()).toBe(201);
    const row = await created.json();
    const page = await mobile.newPage();
    await page.goto("/admin/compliance-master/" + row.id);
    await page.locator(".master-mobile-step select").selectOption("4");
    const handles = page.locator(".master-drag");
    const first = await handles.first().boundingBox();
    const second = await handles.nth(1).boundingBox();
    expect(first).not.toBeNull(); expect(second).not.toBeNull();
    const session = await mobile.newCDPSession(page);
    const finger = (x: number, y: number) => ({ x, y, id: 0, radiusX: 5, radiusY: 5, force: 1 });
    await session.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [finger(first!.x + 22, first!.y + 22)] });
    await expect(handles.first()).toHaveAttribute("aria-pressed", "true");
    await session.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [finger(second!.x + 22, second!.y + 22)] });
    await expect.poll(async () => (await handles.first().boundingBox())?.y ?? 0).toBeGreaterThan(first!.y + 1);
    await session.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect(page.getByLabel("Checklist item title", { exact: true }).first()).toHaveValue("Second touch sample");
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Changes saved" })).toBeVisible();
    const saved = await (await request.get("/api/v1/admin/compliance-templates/" + row.id)).json();
    expect(saved.configuration.checklist[0].title).toBe("Second touch sample");
    await expect(page.locator(".master-builder-panel")).toHaveCSS("touch-action", "auto");
  } finally {
    await mobile.close();
  }
});
