"use client";

import { Globe2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { usePublicLocalization } from "@/i18n/public-client";
import { switchPublicLocale } from "@/i18n/public-preference";
import {
  availableLocales,
  type AppLocale,
} from "@/i18n/config";

export default function PublicLocaleSwitcher({
  compact = false,
}: {
  compact?: boolean;
}) {
  const locale = useLocale();
  const t = useTranslations("Settings");
  const notice = useTranslations("Marketing.navigation");
  const settings = usePublicLocalization();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const languages = availableLocales(settings?.locales);
  async function switchLocale(next: AppLocale) {
    setBusy(true);
    setError("");
    try {
      await switchPublicLocale(next, settings);
      window.location.reload();
    } catch {
      setBusy(false);
      setError(notice("selectionFailed"));
    }
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
        disabled={busy}
        onChange={(event) => switchLocale(event.target.value as AppLocale)}
      >
        {languages.map((item) => (
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
