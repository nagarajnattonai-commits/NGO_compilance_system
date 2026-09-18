import { test, expect } from "@playwright/test";
import { createTranslator } from "next-intl";
import { applyTranslationOverrides, messageAt, validateTranslation } from "../../i18n/overrides";
import { mergeMessages } from "../../i18n/messages";
import { availableLocales, localeCookieName } from "../../i18n/config";

test("translation overrides validate ICU and variables without altering shared dictionaries", () => {
  expect(availableLocales([
    { locale_code: "hi-IN", display_name: "हिन्दी भाषा", enabled: true, sort_order: 3 },
    { locale_code: "kn-IN", display_name: "ಕನ್ನಡ", enabled: false, sort_order: 2 },
    { locale_code: "mr-IN", display_name: "मराठी भाषा", enabled: true, sort_order: 1 },
    { locale_code: "xx-IN", display_name: "Unsupported", enabled: true, sort_order: 0 },
  ]).map(locale => [locale.code, locale.nativeLabel])).toEqual([
    ["mr-IN", "मराठी भाषा"], ["hi-IN", "हिन्दी भाषा"],
  ]);
  const base = { Common: { save: "Save", greeting: "Hello {name}", tasks: "{count, plural, one {# task} other {# tasks}}" } };
  expect(validateTranslation(base.Common.greeting, "नमस्ते {name}", "hi-IN")).toBeTruthy();
  expect(validateTranslation(base.Common.greeting, "ನಮಸ್ಕಾರ {person}", "kn-IN")).toBeFalsy();
  expect(validateTranslation(base.Common.greeting, "Hello", "en-IN")).toBeFalsy();
  expect(validateTranslation(base.Common.save, "Broken {", "en-IN")).toBeFalsy();
  expect(validateTranslation(base.Common.save, "   ", "en-IN")).toBeFalsy();
  expect(validateTranslation(base.Common.tasks, "{count, plural, one {# काम}}", "mr-IN")).toBeFalsy();
  expect(validateTranslation(base.Common.tasks, "{count} कामे", "mr-IN")).toBeFalsy();
  expect(validateTranslation(base.Common.tasks, "{count, plural, one {{count} काम} other {{count} कामे}}", "mr-IN")).toBeTruthy();
  expect(validateTranslation("Use '{name}' literally", "'{name}' असे लिहा", "mr-IN")).toBeTruthy();
  expect(validateTranslation("Welcome <strong>{name}</strong>", "<strong>{name}</strong> स्वागत है", "hi-IN")).toBeTruthy();
  expect(validateTranslation("On {date, date, short}", "{date, date, short} रोजी", "mr-IN")).toBeTruthy();
  const overrides = [
    { locale_code: "kn-IN", translation_key: "Common.save", translation_value: "ಉಳಿಸಿ" },
    { locale_code: "kn-IN", translation_key: "Common.greeting", translation_value: "Hello {wrong}" },
    { locale_code: "kn-IN", translation_key: "Common.__proto__.polluted", translation_value: "unsafe" },
    { locale_code: "kn-IN", translation_key: "Common.constructor.prototype.polluted", translation_value: "unsafe" },
    { locale_code: "kn-IN", translation_key: "Common.unknown", translation_value: "unknown" },
    { locale_code: "hi-IN", translation_key: "Common.save", translation_value: "दूसरा टेनेंट" },
  ];
  const result = applyTranslationOverrides(base, overrides, "kn-IN");
  expect(messageAt(result.messages, "Common.save")).toBe("ಉಳಿಸಿ");
  expect(messageAt(result.messages, "Common.greeting")).toBe("Hello {name}");
  expect(result.rejected).toHaveLength(4);
  expect(base.Common.save).toBe("Save");
  expect(messageAt(result.messages, "Common.unknown")).toBeUndefined();
  expect(messageAt(result.messages, "Common.__proto__.polluted")).toBeUndefined();
  expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  expect(applyTranslationOverrides(base, [], "kn-IN").messages).toEqual(base);
  expect(mergeMessages(base, { Common: { save: "", greeting: "  " } })).toEqual(base);
  const t = createTranslator({
    locale: "mr-IN",
    messages: { Common: { tasks: messageAt(result.messages, "Common.tasks")! } },
  });
  expect(t("Common.tasks", { count: 2 })).not.toContain("Common.tasks");
});

test("dashboard ignores disabled preferences, invalid overrides, and resets live translations", async ({ page, request, context }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  const headers = { "X-Setu-Request": "1" };
  const signup = await request.post("/api/v1/auth/signup", {
    headers,
    data: { name: "Localization Reliability", workspace_name: "Localization Reliability", email: "locale-reliability@example.test", password: "Locale-reliability-QA-2026!" },
  });
  expect(signup.status()).toBe(201);
  expect((await request.patch("/api/v1/localization/preferences", {
    headers, data: { locale: "kn-IN", timezone: "UTC", time_format: "24h" },
  })).ok()).toBeTruthy();
  const settings = await (await request.get("/api/v1/localization/settings")).json();
  expect((await request.put("/api/v1/localization/locales", {
    headers,
    data: settings.locales.map((item: {locale_code: string; display_name: string; sort_order: number}) => ({
      locale_code: item.locale_code, display_name: item.display_name, sort_order: item.sort_order,
      enabled: item.locale_code !== "kn-IN", is_default: item.locale_code === "en-IN",
    })),
  })).ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
  await context.addCookies([{ name: localeCookieName, value: "kn-IN", domain: "localhost", path: "/" }]);
  let dashboardLoads = 0;
  page.on("request", req => { if (req.resourceType() === "document" && req.url().includes("/dashboard")) dashboardLoads++; });
  await page.goto("/dashboard");
  await expect(page.locator("html")).toHaveAttribute("lang", "en-IN");
  await expect(page.locator("html")).toHaveAttribute("data-timezone", "UTC");
  // A short controlled observation catches the former unconditional reload loop.
  let observations = 0;
  await expect.poll(() => ++observations >= 5 ? dashboardLoads : 0, { intervals: [100, 300, 500], timeout: 3000 }).toBe(1);
  expect((await request.patch("/api/v1/localization/preferences", {
    headers, data: { locale: "hi-IN", timezone: "UTC", time_format: "24h" },
  })).ok()).toBeTruthy();
  for (const [key, value] of [
    ["Common.nav.dashboard", "अनुपालन अवलोकन"],
    ["Common.nav.tasks", "Broken {"],
    ["Common.items", "{count, plural, one {# कार्य}}"],
    ["Common.__proto__.polluted", "unsafe"],
  ]) {
    expect((await request.put("/api/v1/localization/overrides", {
      headers, data: { locale_code: "hi-IN", translation_key: key, translation_value: value },
    })).ok()).toBeTruthy();
  }
  await page.goto("/settings/localization/translations");
  await expect(page.locator("html")).toHaveAttribute("lang", "hi-IN");
  await expect(page.locator(".sidebar")).toContainText("अनुपालन अवलोकन");
  await expect(page.locator(".sidebar")).not.toContainText("Broken {");
  const row = page.locator(".translation-row").filter({ has: page.locator("code", { hasText: /^Common.nav.dashboard$/ }) });
  await expect(row).toBeVisible();
  await row.locator("button").last().click();
  await expect(page.locator(".sidebar")).not.toContainText("अनुपालन अवलोकन");
  await expect(page.locator(".sidebar")).toContainText("डैशबोर्ड");
  await row.locator("button").first().click();
  await row.locator("textarea").fill("Broken {");
  const writes: string[] = [];
  page.on("request", req => { if (req.method() === "PUT" && req.url().includes("/localization/overrides")) writes.push(req.url()); });
  await row.locator("button").first().click();
  await expect(page.locator(".auth-alert")).toContainText("वैध अनुवाद");
  expect(writes).toEqual([]);
  await row.locator("textarea").fill("नया अवलोकन");
  await row.locator("button").first().click();
  await expect(page.locator(".sidebar")).toContainText("नया अवलोकन");
  expect(await page.evaluate(() => ({} as Record<string, unknown>).polluted)).toBeUndefined();
  expect(errors).toEqual([]);
});

test("explicit locale survives blocked browser storage and preference-save failures are announced", async ({ page, context, request }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await context.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new DOMException("Storage blocked", "SecurityError"); };
    Storage.prototype.setItem = () => { throw new DOMException("Storage blocked", "SecurityError"); };
  });
  const headers = { "X-Setu-Request": "1" };
  expect((await request.post("/api/v1/auth/signup", {
    headers,
    data: { name: "Private Browser QA", workspace_name: "Private Browser QA", email: "locale-private-browser@example.test", password: "Locale-private-browser-QA-2026!" },
  })).status()).toBe(201);
  await context.addCookies((await request.storageState()).cookies);
  await context.addCookies([{ name: localeCookieName, value: "hi-IN", domain: "localhost", path: "/" }]);
  await page.goto("/dashboard");
  await expect(page.locator("html")).toHaveAttribute("lang", "hi-IN");
  await expect(page.locator(".locale-switcher select")).toBeEnabled();
  await page.route("**/api/v1/localization/preferences", route =>
    route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"Temporary failure"}' }),
  );
  await page.locator(".locale-switcher select").selectOption("mr-IN");
  await expect(page.locator(".locale-switcher [role=alert]")).toContainText("सहेज नहीं सके");
  await expect(page.locator(".locale-switcher select")).toBeEnabled();
  await expect(page.locator("html")).toHaveAttribute("lang", "hi-IN");
  await page.unroute("**/api/v1/localization/preferences");
  await page.locator(".locale-switcher select").selectOption("mr-IN");
  await expect(page.locator("html")).toHaveAttribute("lang", "mr-IN");
  const settings = await (await request.get("/api/v1/localization/settings")).json();
  expect(settings.preference.locale).toBe("mr-IN");
  expect(errors).toEqual([]);
});
