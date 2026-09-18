import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";
import {
  defaultLocale,
  isAppLocale,
  localeCookieName,
  matchBrowserLocale,
} from "./config";
import { loadMessages } from "./messages";
import { applyTranslationOverrides } from "./overrides";
import {
  getPublicLocalizationSettings,
  getPublicTranslationOverrides,
} from "./public-settings";

export default getRequestConfig(async () => {
  const cookieLocale = (await cookies()).get(localeCookieName)?.value;
  const settings = await getPublicLocalizationSettings();
  const enabled = settings?.locales.filter((item) => item.enabled);
  const preference = settings?.preference.locale;
  const tenantDefault = enabled?.find((item) => item.is_default)?.locale_code;
  const permitted = (value: string | null | undefined) =>
    isAppLocale(value) && (!enabled || enabled.some((item) => item.locale_code === value));
  const candidate = permitted(preference)
    ? preference
    : permitted(cookieLocale)
      ? cookieLocale
      : permitted(tenantDefault)
        ? tenantDefault
        : matchBrowserLocale((await headers()).get("accept-language"));
  const locale = isAppLocale(candidate) && permitted(candidate) ? candidate : defaultLocale;
  try {
    const base = await loadMessages(locale);
    const overrides = await getPublicTranslationOverrides(locale);
    const { messages, rejected } = applyTranslationOverrides(base, overrides || [], locale);
    if (rejected.length) console.warn("Ignored invalid localization override keys", rejected);
    return {
      locale,
      messages,
      timeZone: settings?.preference.timezone || "Asia/Kolkata",
      now: new Date(),
    };
  } catch {
    return {
      locale: defaultLocale,
      messages: await loadMessages(defaultLocale),
      timeZone: "Asia/Kolkata",
      now: new Date(),
    };
  }
});
