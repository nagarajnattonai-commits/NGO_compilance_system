"use client";

import { Globe2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { availableLocales, type AppLocale } from "@/i18n/config";
import { useLocalization } from "@/i18n/client";

export default function LocaleSwitcher({
  compact = false,
  beforeChange,
}: {
  compact?: boolean;
  beforeChange?: () => boolean;
}) {
  const t = useTranslations("Settings");
  const { locale, settings, loading, switchLocale } = useLocalization();
  const options = availableLocales(settings?.locales);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function choose(locale: AppLocale) {
    if (beforeChange && !beforeChange()) return;
    setBusy(true);
    setError("");
    try { await switchLocale(locale); }
    catch { setBusy(false); setError(t("saveFailed")); }
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
        disabled={loading || busy}
        onChange={(event) => void choose(event.target.value as AppLocale)}
      >
        {options.map((item) => (
          <option key={item.code} value={item.code}>
            {compact
              ? `${item.language.toUpperCase()} · ${item.nativeLabel}`
              : `${item.nativeLabel} (${item.code})`}
          </option>
        ))}
      </select>
      {error && <span role="alert">{error}</span>}
    </label>
  );
}
