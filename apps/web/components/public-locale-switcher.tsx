"use client";

import { Globe2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  localeCookieName,
  supportedLocales,
  type AppLocale,
} from "@/i18n/config";

export default function PublicLocaleSwitcher({
  compact = false,
}: {
  compact?: boolean;
}) {
  const locale = useLocale();
  const t = useTranslations("Settings");
  function switchLocale(next: AppLocale) {
    localStorage.setItem("setu-locale-explicit", "1");
    document.cookie = `${localeCookieName}=${next};path=/;max-age=31536000;samesite=lax`;
    window.location.reload();
  }
  return (
    <label
      className={`locale-switcher ${compact ? "compact" : ""}`}
      title={t("preferredLanguage")}
    >
      <Globe2 size={16} aria-hidden="true" />
      <span className="sr-only">{t("preferredLanguage")}</span>
      <select
        aria-label={t("preferredLanguage")}
        value={locale}
        onChange={(event) => switchLocale(event.target.value as AppLocale)}
      >
        {supportedLocales.map((item) => (
          <option key={item.code} value={item.code}>
            {compact
              ? `${item.language.toUpperCase()} · ${item.nativeLabel}`
              : `${item.nativeLabel} (${item.code})`}
          </option>
        ))}
      </select>
    </label>
  );
}
