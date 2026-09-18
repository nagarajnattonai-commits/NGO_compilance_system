"use client";

import { isAppLocale, localeCookieName, type AppLocale } from "./config";
import { updateLocalizationPreference } from "@/lib/api";
import type { LocalizationSettings } from "@/lib/types";

export function persistLocaleCookie(locale: AppLocale) {
  // Storage may be blocked in private browsers. The cookie still persists choice.
  try { localStorage.setItem("setu-locale-explicit", "1"); } catch {}
  document.cookie = `${localeCookieName}=${locale};path=/;max-age=31536000;samesite=lax${window.location.protocol === "https:" ? ";secure" : ""}`;
}

export function hasExplicitLocalePreference() {
  try { if (localStorage.getItem("setu-locale-explicit") === "1") return true; } catch {}
  // A chosen cookie remains authoritative when browser storage is unavailable.
  return document.cookie.split(";").some(cookie => {
    const [name, value] = cookie.trim().split("=");
    return name === localeCookieName && isAppLocale(value);
  });
}

export async function switchPublicLocale(
  locale: AppLocale,
  settings?: LocalizationSettings | null,
) {
  if (settings) {
    await updateLocalizationPreference({
      locale,
      timezone: settings.preference.timezone,
      time_format: settings.preference.time_format,
    });
  }
  persistLocaleCookie(locale);
}
