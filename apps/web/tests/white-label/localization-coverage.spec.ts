import { expect, test } from "@playwright/test";
import { createTranslator } from "next-intl";
import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { readFile } from "node:fs/promises";
import { supportedLocales, localeCookieName } from "../../i18n/config";
import { flattenMessages, messageModules, mergeMessages } from "../../i18n/messages";
import { validateTranslation } from "../../i18n/overrides";
import { formatCurrency, formatDateTime, formatNumber, formatPercentage, formatShortDate } from "../../i18n/format";
import { localizedError, localizedRole, localizedStatus } from "../../i18n/display";
import { ApiError } from "../../lib/http";

async function readLocaleMessages(locale: string) {
  const modules = await Promise.all(messageModules.map(async module => {
    const filename = module.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`);
    return JSON.parse(await readFile(path.join(process.cwd(), "messages", locale, `${filename}.json`), "utf8"));
  }));
  return Object.assign({}, ...modules) as Record<string, unknown>;
}

async function resolvedMessages(locale: string) {
  // Runtime-loaded dictionaries are intentionally untyped, as in the application provider.
  return mergeMessages(await readLocaleMessages("en-IN"), await readLocaleMessages(locale)) as Record<string, any>;
}

test("all application dictionaries preserve canonical keys and ICU contracts", async () => {
  const english = flattenMessages(await readLocaleMessages("en-IN"));
  expect(Object.keys(english).length).toBeGreaterThan(1500);
  for (const locale of supportedLocales) {
    const translated = flattenMessages(await readLocaleMessages(locale.code));
    expect(Object.keys(english).filter(key => !translated[key]?.trim()), locale.code).toEqual([]);
    for (const [key, reference] of Object.entries(english)) {
      expect(validateTranslation(reference, translated[key], locale.code), `${locale.code}: ${key}`).toBeTruthy();
    }
    for (const namespace of ["Portfolio.title", "PortfolioImport.title", "Csr.title", "Common.interface.accountSecurity"]) {
      if (locale.code !== "en-IN") expect(translated[namespace]).not.toBe(english[namespace]);
    }
  }
});

test("English fallback, interpolation and regional formatters use unchanged values", async () => {
  const merged = mergeMessages({ Common: { label: "Save", greeting: "Hello {name}" } }, { Common: { label: "" } });
  expect(merged).toEqual({ Common: { label: "Save", greeting: "Hello {name}" } });
  const value = "2026-10-06T08:15:00Z";
  for (const { code } of supportedLocales) {
    const t = createTranslator({ locale: code, messages: await resolvedMessages(code) });
    expect(t("Common.interface.deleteSavedView", { name: "User's NGO view" })).toContain("User's NGO view");
    expect(t("Portfolio.clientsHelp", { count: 3 })).not.toMatch(/Portfolio\.|\{count\}/);
    expect(formatNumber(1234567, code)).toBe(new Intl.NumberFormat(code).format(1234567));
    expect(formatCurrency(1234567.5, "INR", code)).toBe(new Intl.NumberFormat(code, { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(1234567.5));
    expect(formatPercentage(0.375, code)).toBe(new Intl.NumberFormat(code, { style: "percent", maximumFractionDigits: 1 }).format(0.375));
    expect(formatShortDate(value, { locale: code, timezone: "UTC" })).toBe(new Intl.DateTimeFormat(code, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(value)));
    expect(formatDateTime(value, { locale: code, timezone: "UTC", timeFormat: "24h" })).toBe(new Intl.DateTimeFormat(code, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC", hour12: false }).format(new Date(value)));
  }
  expect(value).toBe("2026-10-06T08:15:00Z");
});

test("display translation retains custom content and never changes API codes", async () => {
  for (const { code } of supportedLocales) {
    const t = createTranslator({ locale: code, messages: await resolvedMessages(code) });
    expect(localizedStatus("APPROVED", t)).toBe(t("Common.status.APPROVED"));
    expect(localizedStatus("User-defined record state", t)).toBe("User-defined record state");
    expect(localizedRole("VIEWER", t)).toBe(t("Marketing.readOnlyViewer"));
    expect(localizedError(new ApiError("Private provider error details", 503), t, "fallback")).toBe(t("Common.interface.requestUnavailable"));
    expect(localizedError(new ApiError("Private provider error details", 403), t, "fallback")).toBe(t("Common.interface.requestDenied"));
    expect(localizedError(new ApiError("Private provider error details", 409), t, "fallback")).toBe(t("Common.interface.requestConflict"));
    expect(localizedError(new ApiError("AI services are not configured for this workspace.", 503), t, "fallback")).toBe(t("Common.interface.aiNotConfigured"));
    const original = new ApiError("Original API validation detail", 409);
    localizedError(original, t, "fallback");
    expect(original.status).toBe(409);
    expect(original.message).toBe("Original API validation detail");
  }
});

for (const { code } of supportedLocales) {
  test(`${code}: public, login, workspace and critical registers retain selected locale`, async ({ page, request, context }) => {
    const t = createTranslator({ locale: code, messages: await resolvedMessages(code) });
    const marker = randomUUID(), password = "Localization-journey-QA-2026!";
    const email = `locale-${marker}@example.test`, headers = { "X-Setu-Request": "1" };
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error" || /MISSING_MESSAGE|INVALID_MESSAGE/.test(message.text())) errors.push(message.text()); });
    await context.addCookies([{ name: localeCookieName, value: code, domain: "localhost", path: "/" }]);
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", code);
    await expect(page.locator("#public-navigation")).toContainText(t("Marketing.navigation.home"));
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: t("Authentication.titles.login"), exact: true })).toBeVisible();
    expect((await request.post("/api/v1/auth/signup", { headers, data: { name: "Locale Administrator", workspace_name: "Locale Workspace", email, password } })).status()).toBe(201);
    const user = (await (await request.get("/api/v1/auth/me")).json()).user;
    const database = process.env.SETU_QA_DATABASE_URL;
    if (!database?.includes("setu-white-label-qa-")) throw new Error("Requires disposable localization QA database");
    const python = process.env.API_PYTHON || path.resolve(process.platform === "win32" ? "../api/.venv/Scripts/python.exe" : "../api/.venv/bin/python");
    execFileSync(python, ["-c", ["import sys", "from sqlalchemy import select", "from app.database import SessionLocal", "from app.models import Subscription", "with SessionLocal() as db:", "    db.scalar(select(Subscription).where(Subscription.tenant_id==sys.argv[1])).plan_name='BUSINESS'", "    db.commit()"].join("\n"), user.tenant_id], { cwd: path.resolve("../api"), env: { ...process.env, DATABASE_URL: database }, windowsHide: true });
    const orgResponse = await request.post("/api/v1/organizations", { headers, data: { name: "Untranslated NGO name", legal_type: "TRUST", registration_number: marker, city: "Pune", generate_compliance_plan: false } });
    expect(orgResponse.status()).toBe(201);
    const org = (await orgResponse.json()).organization.id;
    expect((await request.post("/api/v1/compliances", { headers, data: { organization_id: org, title: "Untranslated obligation", code: `LOC-${marker.slice(0,8)}`, category: "Annual", period: "2026-27", statutory_deadline: "2030-01-01", owner_name: "User-entered owner" } })).status()).toBe(201);
    expect((await request.post("/api/v1/tasks", { headers, data: { organization_id: org, title: "Untranslated task", due_at: "2030-01-01", assignee_user_id: user.id } })).status()).toBe(201);
    // Real UI login; this browser has no tenant session until these credentials succeed.
    await page.getByLabel(t("Authentication.email"), { exact: true }).fill(email);
    await page.getByLabel(t("Authentication.password"), { exact: true }).fill(password);
    await page.getByRole("button", { name: t("Authentication.signIn"), exact: true }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: t("Dashboard.adminTitle"), exact: true })).toBeVisible({ timeout: 30000 });
    const selector = page.locator(".top-actions .locale-switcher select");
    await expect(selector).toBeEnabled();
    // Persist through the existing backend preference API, then reload/navigation.
    const alternate = code === "en-IN" ? "hi-IN" : "en-IN";
    await selector.selectOption(alternate);
    await expect(page.locator("html")).toHaveAttribute("lang", alternate);
    await expect(selector).toBeEnabled();
    await selector.selectOption(code);
    await expect(page.locator("html")).toHaveAttribute("lang", code);
    await page.reload();
    await expect(selector).toHaveValue(code);
    expect((await (await page.request.get("/api/v1/localization/settings")).json()).preference.locale).toBe(code);
    await page.goto(`/organizations/${org}`);
    await expect(page.locator("html")).toHaveAttribute("lang", code);
    await expect(page.locator("main")).toContainText("Untranslated NGO name");
    for (const [view, title, record] of [
      ["compliance", "Compliance.title", "Untranslated obligation"],
      ["tasks", "Tasks.title", "Untranslated task"],
      ["documents", "Documents.title", ""],
      ["reports", "Reports.title", ""],
      ["subscription", "Subscriptions.title", ""],
    ]) {
      await page.goto("/dashboard");
      await expect(page.getByRole("heading", { name: t("Dashboard.adminTitle"), exact: true })).toBeVisible({ timeout: 30000 });
      const navigationLabel = t(`Common.nav.${view}`);
      await page.locator(".sidebar").getByRole("button", { name: view === "tasks" ? new RegExp(`^${navigationLabel}(?:\\s|$)`) : navigationLabel, exact: view !== "tasks" }).click();
      await expect(page.getByRole("heading", { name: t(title), exact: true })).toBeVisible({ timeout: 30000 });
      await expect(page.locator("html")).toHaveAttribute("lang", code);
      if (record) await expect(page.locator("main")).toContainText(record);
      await expect(page.locator("main")).not.toContainText(/(?:Common|Compliance|Tasks|Reports|Documents)\.[A-Za-z]+/);
      for (const width of [390, 1280]) {
        await page.setViewportSize({ width, height: 900 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${code} / ${view} / ${width}`).toBeTruthy();
      }
    }
    await page.goto("/account");
    await expect(page.getByRole("region", { name: t("Common.interface.accountSecurity"), exact: true })).toContainText(t("Common.interface.currentSession"));
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${code} / ${width}`).toBeTruthy();
    }
    expect(errors).toEqual([]);
  });
}
