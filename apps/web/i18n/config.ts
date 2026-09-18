export const supportedLocales = [
  {
    code: "en-IN",
    language: "en",
    country: "IN",
    label: "English",
    nativeLabel: "English",
    direction: "ltr",
  },
  {
    code: "hi-IN",
    language: "hi",
    country: "IN",
    label: "Hindi",
    nativeLabel: "हिन्दी",
    direction: "ltr",
  },
  {
    code: "kn-IN",
    language: "kn",
    country: "IN",
    label: "Kannada",
    nativeLabel: "ಕನ್ನಡ",
    direction: "ltr",
  },
  {
    code: "mr-IN",
    language: "mr",
    country: "IN",
    label: "Marathi",
    nativeLabel: "मराठी",
    direction: "ltr",
  },
] as const;

export type AppLocale = (typeof supportedLocales)[number]["code"];
export const defaultLocale: AppLocale = "en-IN";
export const localeCookieName = "SETU_LOCALE";
export const defaultTimeZone = "Asia/Kolkata";

export function isAppLocale(
  value: string | null | undefined,
): value is AppLocale {
  return supportedLocales.some((locale) => locale.code === value);
}

export function localeMetadata(code: AppLocale) {
  return (
    supportedLocales.find((locale) => locale.code === code) ??
    supportedLocales[0]
  );
}

export function availableLocales(configuration?: ReadonlyArray<{
  locale_code: string;
  display_name: string;
  enabled: boolean;
  sort_order: number;
}> | null) {
  if (!configuration) return supportedLocales.map(locale => ({ ...locale }));
  return [...configuration]
    .filter(item => item.enabled && isAppLocale(item.locale_code))
    .sort((a, b) => a.sort_order - b.sort_order)
    .map(item => ({
      ...localeMetadata(item.locale_code as AppLocale),
      nativeLabel: item.display_name,
    }));
}

export function matchBrowserLocale(header: string | null): AppLocale {
  if (!header) return defaultLocale;
  const requested = header
    .split(",")
    .map((value, index) => {
      const [tag, ...parameters] = value.trim().toLowerCase().split(";");
      const quality = parameters.find(parameter => parameter.trim().startsWith("q="));
      const weight = quality ? Number(quality.trim().slice(2)) : 1;
      return { tag, index, weight };
    })
    .filter(item => Number.isFinite(item.weight) && item.weight > 0 && item.weight <= 1)
    .sort((a, b) => b.weight - a.weight || a.index - b.index);
  for (const { tag } of requested) {
    const locale = supportedLocales.find(
      locale => locale.code.toLowerCase() === tag || locale.language === tag.split("-")[0],
    );
    if (locale) return locale.code;
  }
  return defaultLocale;
}
