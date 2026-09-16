"use client";

import { NextIntlClientProvider, useLocale, useMessages } from "next-intl";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  loadLocalizationSettings,
  loadTranslationOverrides,
  updateLocalizationPreference,
} from "@/lib/api";
import type { LocalizationSettings, TranslationOverride } from "@/lib/types";
import {
  defaultLocale,
  defaultTimeZone,
  isAppLocale,
  localeCookieName,
  type AppLocale,
} from "./config";

type LocalizationContextValue = {
  locale: AppLocale;
  settings: LocalizationSettings | null;
  overrides: TranslationOverride[];
  loading: boolean;
  switchLocale: (locale: AppLocale) => Promise<void>;
  refresh: () => Promise<void>;
};
const LocalizationContext = createContext<LocalizationContextValue | null>(
  null,
);

function setNested(
  target: Record<string, unknown>,
  path: string,
  value: string,
) {
  const parts = path.split(".");
  let current = target;
  parts.forEach((part, index) => {
    if (index === parts.length - 1) current[part] = value;
    else {
      const child = current[part];
      current[part] =
        child && typeof child === "object"
          ? { ...(child as Record<string, unknown>) }
          : {};
      current = current[part] as Record<string, unknown>;
    }
  });
}

function readableFallback(namespace: string | undefined, key: string) {
  const source =
    key.split(".").pop() || namespace?.split(".").pop() || "Text unavailable";
  return source
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

export function LocalizationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const requestLocale = useLocale();
  const baseMessages = useMessages();
  const locale = isAppLocale(requestLocale) ? requestLocale : defaultLocale;
  const [settings, setSettings] = useState<LocalizationSettings | null>(null);
  const [overrides, setOverrides] = useState<TranslationOverride[]>([]);
  const [loading, setLoading] = useState(true);
  async function refresh() {
    const nextSettings = await loadLocalizationSettings();
    setSettings(nextSettings);
    setOverrides(await loadTranslationOverrides());
  }
  useEffect(() => {
    refresh()
      .then(() => setLoading(false))
      .catch(() => setLoading(false));
  }, [locale]);
  useEffect(() => {
    if (!settings) return;
    document.documentElement.dataset.timezone = settings.preference.timezone;
    document.documentElement.dataset.timeFormat =
      settings.preference.time_format;
    const explicit = localStorage.getItem("setu-locale-explicit") === "1";
    const tenantDefault = settings.locales.find(
      (item) => item.enabled && item.is_default,
    )?.locale_code;
    const resolved =
      settings.preference.locale || (!explicit ? tenantDefault : null);
    if (isAppLocale(resolved) && resolved !== locale) {
      document.cookie = `${localeCookieName}=${resolved};path=/;max-age=31536000;samesite=lax`;
      window.location.reload();
    }
  }, [settings, locale]);
  const messages = useMemo(() => {
    const merged = JSON.parse(JSON.stringify(baseMessages)) as Record<
      string,
      unknown
    >;
    overrides
      .filter((item) => item.locale_code === locale)
      .forEach((item) =>
        setNested(merged, item.translation_key, item.translation_value),
      );
    return merged;
  }, [baseMessages, locale, overrides]);
  async function switchLocale(nextLocale: AppLocale) {
    const preference = settings?.preference;
    await updateLocalizationPreference({
      locale: nextLocale,
      timezone: preference?.timezone || defaultTimeZone,
      time_format: preference?.time_format || "12h",
    });
    localStorage.setItem("setu-locale-explicit", "1");
    document.cookie = `${localeCookieName}=${nextLocale};path=/;max-age=31536000;samesite=lax`;
    window.location.reload();
  }
  return (
    <LocalizationContext.Provider
      value={{ locale, settings, overrides, loading, switchLocale, refresh }}
    >
      <NextIntlClientProvider
        locale={locale}
        messages={messages}
        timeZone={settings?.preference.timezone || defaultTimeZone}
        onError={(error) => console.warn("Localization fallback used", error)}
        getMessageFallback={({ namespace, key }) =>
          readableFallback(namespace, key)
        }
      >
        {children}
      </NextIntlClientProvider>
    </LocalizationContext.Provider>
  );
}

export function useLocalization() {
  const context = useContext(LocalizationContext);
  if (!context) throw new Error("LocalizationProvider is missing");
  return context;
}
