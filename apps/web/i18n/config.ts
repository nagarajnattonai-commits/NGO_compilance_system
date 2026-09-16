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

export function matchBrowserLocale(header: string | null): AppLocale {
  if (!header) return defaultLocale;
  const requested = header
    .split(",")
    .map((value) => value.split(";")[0].trim().toLowerCase());
  return (
    supportedLocales.find((locale) =>
      requested.some(
        (value) =>
          value === locale.code.toLowerCase() || value === locale.language,
      ),
    )?.code ?? defaultLocale
  );
}
