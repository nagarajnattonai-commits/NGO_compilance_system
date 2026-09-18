import {provisionPlatformOperator} from "./platform-operator";
import { test, expect } from "@playwright/test";
import { localeCookieName } from "../../i18n/config";

test("white-label editor, publishing, localization and responsive layouts", async ({
  page,
  request,
  context,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const headers = { "X-Setu-Request": "1" };
  const signup = await request.post("/api/v1/auth/signup", {
    headers,
    data: {
      name: "Brand QA",
      workspace_name: "White Label QA",
      email: "white-label-qa@example.test",
      password: "WhiteLabel-browser-QA-2026!",
    },
  });
  expect([201,409]).toContain(signup.status());
  if(signup.status()===409){
    expect((await request.post("/api/v1/auth/login",{headers,data:{email:"white-label-qa@example.test",password:"WhiteLabel-browser-QA-2026!"}})).ok()).toBeTruthy();
  }
  const user = (await (await request.get("/api/v1/auth/me")).json()).user;
  await provisionPlatformOperator(request);
  const grant = await request.put(
    `/api/v1/platform/white-label/${user.tenant_id}/entitlement`,
    { headers, data: { enabled: true } },
  );
  expect(grant.ok()).toBeTruthy();
  await context.addCookies((await request.storageState()).cookies);
  await page.goto("/settings/white-label");
  await expect(
    page.getByRole("heading", { name: "White Label", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Brand name", { exact: true })
    .fill("ABC Compliance Solutions");
  const longName =
    "ABC NGO Compliance Management Platform for Consulting Partners and NGO Networks";
  await page.getByLabel("Product name", { exact: true }).fill(longName);
  const image = await page.screenshot({
    clip: { x: 0, y: 0, width: 64, height: 64 },
  });
  for (const index of [0, 1, 2, 3, 4]) {
    const uploader = page.locator(".brand-asset-upload").nth(index);
    await uploader.locator('input[type="file"]').setInputFiles({
      name: "brand.png",
      mimeType: "image/png",
      buffer: image,
    });
    await expect(uploader.locator("img")).toBeVisible();
  }
  await expect(page.locator(".brand-preview-frame > header strong")).toHaveText(
    longName,
  );
  // Arrow-key navigation and native file drop use the same existing editor.
  await page
    .locator(".brand-editor-tabs")
    .getByRole("tab", { name: "Brand", exact: true })
    .focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page
      .locator(".brand-editor-tabs")
      .getByRole("tab", { name: "Theme", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page
    .locator(".brand-editor-tabs")
    .getByRole("tab", { name: "Login", exact: true })
    .click();
  const transfer = await page.evaluateHandle((encoded) => {
    const bytes = Uint8Array.from(atob(encoded), (character) =>
      character.charCodeAt(0),
    );
    const data = new DataTransfer();
    data.items.add(new File([bytes], "login.png", { type: "image/png" }));
    return data;
  }, image.toString("base64"));
  await page
    .locator(".brand-asset-upload")
    .first()
    .dispatchEvent("drop", { dataTransfer: transfer });
  await expect(
    page.locator(".brand-asset-upload").first().locator("img"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByText("Draft saved. Published branding is unchanged."),
  ).toBeVisible();
  expect(
    (await (await request.get("/api/v1/white-label/published")).json()).enabled,
  ).toBe(false);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await page.waitForLoadState("domcontentloaded");
  await expect(page.locator("html")).toHaveAttribute(
    "data-white-label",
    "true",
  );
  await expect(page).toHaveTitle(longName);
  await expect(page.locator(".tenant-sidebar-brand strong")).toHaveText(
    longName,
  );
  const widths = [320, 360, 375, 390, 425, 768, 1024, 1280, 1440, 1920];
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    for (const name of [
      "Brand",
      "Theme",
      "Login",
      "Domain",
      "Email",
      "Reports & Documents",
      "Support",
      "Advanced",
      "Preview",
    ]) {
      await page
        .locator(".brand-editor-tabs")
        .getByRole("tab", { name, exact: true })
        .click();
      await expect(
        page
          .locator(".brand-editor-tabs")
          .getByRole("tab", { name, exact: true }),
      ).toHaveAttribute("aria-selected", "true");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(
        overflow,
        `${width}px ${name} must not overflow horizontally`,
      ).toBeLessThanOrEqual(1);
    }
    await page.screenshot({
      path: testInfo.outputPath(`preview-${width}.png`),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const locale of ["hi-IN", "kn-IN", "mr-IN"]) {
    expect(
      (
        await request.patch("/api/v1/localization/preferences", {
          headers,
          data: { locale, timezone: "Asia/Kolkata", time_format: "12h" },
        })
      ).ok(),
    ).toBeTruthy();
    await context.addCookies([
      { name: localeCookieName, value: locale, domain: "localhost", path: "/" },
    ]);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.locator(".brand-editor-tabs")).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath(`locale-${locale}-390.png`),
      fullPage: true,
    });
  }
  await page.evaluate(() => {
    localStorage.setItem("setu-theme", "dark");
    document.documentElement.dataset.theme = "dark";
  });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({
    path: testInfo.outputPath("dark-390.png"),
    fullPage: true,
  });
  await context.addCookies([
    { name: localeCookieName, value: "en-IN", domain: "localhost", path: "/" },
  ]);
  expect(
    (
      await request.patch("/api/v1/localization/preferences", {
        headers,
        data: { locale: "en-IN", timezone: "Asia/Kolkata", time_format: "12h" },
      })
    ).ok(),
  ).toBeTruthy();
  await page.goto("/");
  await expect(page).toHaveTitle(longName);
  await expect(
    page.locator(".marketing-header .tenant-brand-copy strong"),
  ).toHaveText(longName);
  await expect(
    page.locator(".marketing-footer .tenant-brand-copy strong"),
  ).toHaveText(longName);
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
      `${width}px public branding`,
    ).toBeLessThanOrEqual(1);
    await page.screenshot({
      path: testInfo.outputPath(`public-${width}.png`),
      fullPage: true,
    });
    await page.screenshot({
      path: testInfo.outputPath(`public-viewport-${width}.png`),
    });
  }
  await page.goto("/forgot-password");
  await expect(page.locator(".auth-brand")).toHaveText(longName);
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
      `${width}px branded login`,
    ).toBeLessThanOrEqual(1);
    await page.screenshot({
      path: testInfo.outputPath(`login-brand-${width}.png`),
      fullPage: true,
    });
  }
  const report = await context.newPage();
  await report.goto("/api/v1/reports/compliance/print?locale=en-IN");
  await expect(
    report.getByRole("heading", { name: "Compliance Status Report" }),
  ).toBeVisible();
  await expect(report.locator("header")).toContainText(
    "ABC Compliance Solutions",
  );
  await report.pdf({
    path: testInfo.outputPath("branded-compliance-report.pdf"),
    printBackground: true,
  });
  await report.close();
  expect(errors).toEqual([]);
});
