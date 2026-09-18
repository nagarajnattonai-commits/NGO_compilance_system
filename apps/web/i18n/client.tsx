"use client";

import { NextIntlClientProvider, useLocale, useMessages } from "next-intl";
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  loadLocalizationSettings,
  loadTranslationOverrides,
} from "@/lib/api";
import type { LocalizationSettings, TranslationOverride } from "@/lib/types";
import {
  defaultLocale,
  defaultTimeZone,
  isAppLocale,
  type AppLocale,
} from "./config";
import { loadMessages } from "./messages";
import { applyTranslationOverrides } from "./overrides";
import { usePublicLocalization } from "./public-client";
import { hasExplicitLocalePreference, persistLocaleCookie, switchPublicLocale } from "./public-preference";

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
  const initialSettings = usePublicLocalization();
  const [settings, setSettings] = useState<LocalizationSettings | null>(initialSettings);
  const [applicationMessages, setApplicationMessages] = useState<Record<string, unknown> | null>(null);
  const [overrides, setOverrides] = useState<TranslationOverride[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshVersion = useRef(0);
  async function refresh() {
    const version = ++refreshVersion.current;
    const [nextSettings, nextOverrides, dictionary] = await Promise.all([
      loadLocalizationSettings(), loadTranslationOverrides(), loadMessages(locale),
    ]);
    if (version !== refreshVersion.current) return;
    setSettings(nextSettings);
    setOverrides(nextOverrides);
    setApplicationMessages(dictionary);
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
    const explicit = hasExplicitLocalePreference();
    const tenantDefault = settings.locales.find(
      (item) => item.enabled && item.is_default,
    )?.locale_code;
    const preferred = settings.locales.find(item =>
      item.enabled && item.locale_code === settings.preference.locale,
    )?.locale_code;
    const currentEnabled = settings.locales.some(item => item.enabled && item.locale_code === locale);
    const resolved = preferred || (!explicit || !currentEnabled ? tenantDefault : null);
    if (isAppLocale(resolved) && resolved !== locale) {
      persistLocaleCookie(resolved);
      window.location.reload();
    }
  }, [settings, locale]);
  const messages = useMemo(() => {
    if (!applicationMessages) return baseMessages;
    const result = applyTranslationOverrides(applicationMessages, overrides, locale);
    if (result.rejected.length) console.warn("Ignored invalid localization override keys", result.rejected);
    return result.messages;
  }, [applicationMessages, baseMessages, locale, overrides]);
  async function switchLocale(nextLocale: AppLocale) {
    // Never overwrite regional settings merely because preference loading is slow.
    await switchPublicLocale(nextLocale, settings || await loadLocalizationSettings());
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
