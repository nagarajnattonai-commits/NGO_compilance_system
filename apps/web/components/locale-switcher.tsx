"use client";

import { Globe2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { supportedLocales, type AppLocale } from "@/i18n/config";
import { useLocalization } from "@/i18n/client";

export default function LocaleSwitcher({
  compact = false,
}: {
  compact?: boolean;
}) {
  const t = useTranslations("Settings");
  const { locale, settings, loading, switchLocale } = useLocalization();
  const enabledCodes = settings?.locales
    .filter((item) => item.enabled)
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((item) => item.locale_code);
  const options = supportedLocales.filter(
    (item) => !enabledCodes || enabledCodes.includes(item.code),
  );
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
        disabled={loading}
        onChange={(event) => void switchLocale(event.target.value as AppLocale)}
      >
        {options.map((item) => (
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
