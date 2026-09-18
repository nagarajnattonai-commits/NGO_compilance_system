import { test, expect } from "@playwright/test";
import { supportedLocales, localeCookieName, matchBrowserLocale } from "../../i18n/config";
import { flattenMessages } from "../../i18n/messages";
import { readFile } from "node:fs/promises";
import path from "node:path";

const dictionary = async (locale: string) =>
  JSON.parse(await readFile(path.join(process.cwd(), "messages", locale, "marketing.json"), "utf8"));

test("public dictionaries are complete and render in the selected language before hydration", async ({ request }) => {
  expect(matchBrowserLocale("kn-IN,hi-IN;q=0.8,en-IN;q=0.5")).toBe("kn-IN");
  expect(matchBrowserLocale("en-IN;q=0.3,mr;q=0.9")).toBe("mr-IN");
  expect(matchBrowserLocale("hi;q=0,kn-US;q=0.8")).toBe("kn-IN");
  expect(matchBrowserLocale("ta-IN,fr-FR;q=0.8")).toBe("en-IN");
  const english = flattenMessages(await dictionary("en-IN"));
  const keys = Object.keys(english).filter(key => key.startsWith("Marketing."));
  expect(keys.length).toBeGreaterThan(290);
  for (const locale of supportedLocales) {
    const messages = flattenMessages(await dictionary(locale.code));
    expect(keys.filter(key => !messages[key]?.trim())).toEqual([]);
    // ICU variables must be preserved in every language.
    for (const key of keys) {
      const variables = (text: string) => [...text.matchAll(/\{(\w+)[,}]/g)].map(match => match[1]).sort();
      expect(variables(messages[key]), key).toEqual(variables(english[key]));
    }
    const response = await request.get("/", {
      headers: { Cookie: `${localeCookieName}=${locale.code}` },
    });
    expect(response.ok()).toBeTruthy();
    const html = await response.text();
    expect(html).toContain(`lang="${locale.code}"`);
    expect(html).toContain(messages["Marketing.everyObligation"]);
    expect(html).toContain(messages["Marketing.complianceOperations"]);
    expect(html).toContain(messages["Marketing.navigation.home"]);
  }
});

test("public menu stays above hero, remains clickable, and fits all language/device sizes", async ({ page, context }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const locale of supportedLocales) {
    await context.addCookies([{ name: localeCookieName, value: locale.code, domain: "localhost", path: "/" }]);
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", locale.code);
    for (const width of [320, 360, 375, 390, 425, 768, 915, 1024, 1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(() => window.scrollTo(0, 0));
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${locale.code} / ${width}`).toBeTruthy();
      if (width <= 1100) {
        await page.locator(".public-nav-toggle").click();
        const nav = page.locator("#public-navigation");
        await expect(nav).toBeVisible();
        expect(await page.evaluate(() => {
          const nav = document.querySelector("#public-navigation")!;
          const box = nav.getBoundingClientRect();
          return box.left >= 0 && box.right <= innerWidth && box.bottom <= innerHeight + 1
            && nav.contains(document.elementFromPoint(box.left + box.width / 2, box.top + 120));
        })).toBeTruthy();
        await nav.locator('[aria-controls="about-navigation"]').click();
        await expect(nav.locator("#about-navigation")).toBeVisible();
        await nav.locator("#about-navigation a").first().click();
        await expect(page).toHaveURL(/#platform$/);
        await expect(nav).not.toBeVisible();
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.locator(".public-nav-toggle").click();
        if (width === 915 || width === 375) {
          await page.screenshot({ path: testInfo.outputPath(`${locale.code}-menu-${width}.png`) });
        }
        await page.keyboard.press("Escape");
        await expect(nav).not.toBeVisible();
        expect(await page.evaluate(() => document.body.style.overflow)).not.toBe("hidden");
      }
      await page.locator(".language-trigger").click();
      const panel = page.locator("#language-options");
      await expect(panel).toBeVisible();
      const bounds = await panel.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
      await page.keyboard.press("Escape");
      await expect(panel).not.toBeVisible();
    }
  }
  // Actual language selection, persistence, route/hash preservation and theme.
  await page.setViewportSize({ width: 915, height: 900 });
  await page.goto("/#certificates");
  await page.locator(".language-trigger").click();
  await page.locator("#language-options button").filter({ hasText: "ಕನ್ನಡ" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "kn-IN");
  await expect(page).toHaveURL(/#certificates$/);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "kn-IN");
  await page.evaluate(() => { localStorage.setItem("setu-theme", "dark"); });
  await page.reload();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.locator(".public-nav-toggle").click();
  await page.screenshot({ path: testInfo.outputPath("kn-IN-dark-menu.png") });
  await expect(page.locator("#public-navigation")).toHaveCSS("background-color", "rgb(13, 28, 21)");
  expect(errors).toEqual([]);
});

test("public language changes respect tenant configuration, saved preferences, overrides and independent timezone", async ({ page, request, context }) => {
  const headers = { "X-Setu-Request": "1" };
  const signup = await request.post("/api/v1/auth/signup", {
    headers,
    data: { name: "Locale QA", workspace_name: "Locale QA", email: "locale-public-qa@example.test", password: "Locale-browser-QA-2026!" },
  });
  expect(signup.status()).toBe(201);
  expect((await request.patch("/api/v1/localization/preferences", {
    headers, data: { locale: "kn-IN", timezone: "Asia/Dubai", time_format: "24h" },
  })).ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
  // Server must prefer stored user choice over a stale English cookie.
  await context.addCookies([{ name: localeCookieName, value: "en-IN", domain: "localhost", path: "/" }]);
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "kn-IN");
  await page.locator(".language-trigger").click();
  await page.locator("#language-options button").filter({ hasText: "हिन्दी" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "hi-IN");
  const settings = await (await request.get("/api/v1/localization/settings")).json();
  expect(settings.preference).toMatchObject({ locale: "hi-IN", timezone: "Asia/Dubai", time_format: "24h" });
  expect((await request.put("/api/v1/localization/overrides", {
    headers, data: { locale_code: "hi-IN", translation_key: "Marketing.navigation.home", translation_value: "हमारा मुख्यपृष्ठ" },
  })).ok()).toBeTruthy();
  await page.reload();
  await expect(page.locator('#public-navigation > a[href="#home"]')).toHaveText("हमारा मुख्यपृष्ठ");
  const locales = settings.locales.map((item: { locale_code: string; display_name: string; sort_order: number }) => ({
    locale_code: item.locale_code, display_name: item.locale_code === "mr-IN" ? "मराठी भाषा" : item.display_name,
    enabled: item.locale_code !== "kn-IN", is_default: item.locale_code === "mr-IN",
    sort_order: item.locale_code === "mr-IN" ? 0 : item.sort_order + 1,
  }));
  expect((await request.put("/api/v1/localization/locales", { headers, data: locales })).ok()).toBeTruthy();
  expect((await request.patch("/api/v1/localization/preferences", {
    headers, data: { locale: null, timezone: "Asia/Dubai", time_format: "24h" },
  })).ok()).toBeTruthy();
  await context.clearCookies({ name: localeCookieName });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "mr-IN");
  await page.locator(".language-trigger").click();
  await expect(page.locator("#language-options button").first()).toContainText("मराठी भाषा");
  await expect(page.locator("#language-options")).not.toContainText("ಕನ್ನಡ");
  // A disabled locale cookie cannot bypass workspace language policy.
  await context.addCookies([{ name: localeCookieName, value: "kn-IN", domain: "localhost", path: "/" }]);
  await page.goto("/forgot-password");
  await expect(page.locator("html")).toHaveAttribute("lang", "mr-IN");
  await page.locator(".locale-switcher select").selectOption("hi-IN");
  await expect(page.locator("html")).toHaveAttribute("lang", "hi-IN");
  const authPreference = await (await request.get("/api/v1/localization/settings")).json();
  expect(authPreference.preference).toMatchObject({ locale: "hi-IN", timezone: "Asia/Dubai", time_format: "24h" });
  const anonymous = await page.request.get("/", { headers: { Cookie: `${localeCookieName}=hi-IN`, "Accept-Language": "hi-IN" } });
  const anonymousHtml = await anonymous.text();
  expect(anonymousHtml).toContain('lang="hi-IN"');
  expect(anonymousHtml).toContain(">होम<");
  expect(anonymousHtml).not.toContain("हमारा मुख्यपृष्ठ");
});
