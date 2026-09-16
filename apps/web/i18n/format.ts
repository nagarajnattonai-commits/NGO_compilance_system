import {
  defaultLocale,
  defaultTimeZone,
  isAppLocale,
  type AppLocale,
} from "./config";

export type DisplayPreferences = {
  locale?: string | null;
  timezone?: string;
  timeFormat?: "12h" | "24h";
};

export function activeLocale(preferred?: string | null): AppLocale {
  if (isAppLocale(preferred)) return preferred;
  if (
    typeof document !== "undefined" &&
    isAppLocale(document.documentElement.lang)
  )
    return document.documentElement.lang;
  return defaultLocale;
}

function dateValue(value: string | Date) {
  if (value instanceof Date) return value;
  return new Date(value.length === 10 ? `${value}T12:00:00` : value);
}

function activeTimeZone(preferred?: string) {
  return (
    preferred ||
    (typeof document !== "undefined"
      ? document.documentElement.dataset.timezone
      : undefined) ||
    defaultTimeZone
  );
}

function activeTimeFormat(preferred?: "12h" | "24h") {
  const saved =
    typeof document !== "undefined"
      ? document.documentElement.dataset.timeFormat
      : undefined;
  return preferred || (saved === "24h" ? "24h" : "12h");
}

export function formatDate(
  value: string | Date,
  preferences: DisplayPreferences = {},
) {
  return new Intl.DateTimeFormat(activeLocale(preferences.locale), {
    dateStyle: "long",
    timeZone: activeTimeZone(preferences.timezone),
  }).format(dateValue(value));
}

export function formatShortDate(
  value: string | Date,
  preferences: DisplayPreferences = {},
) {
  return new Intl.DateTimeFormat(activeLocale(preferences.locale), {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: activeTimeZone(preferences.timezone),
  }).format(dateValue(value));
}

export function formatDateTime(
  value: string | Date,
  preferences: DisplayPreferences = {},
) {
  return new Intl.DateTimeFormat(activeLocale(preferences.locale), {
    dateStyle: "medium",
    timeStyle: "short",
    hour12: activeTimeFormat(preferences.timeFormat) !== "24h",
    timeZone: activeTimeZone(preferences.timezone),
  }).format(dateValue(value));
}

export function formatRelativeDate(
  value: string | Date,
  preferences: DisplayPreferences = {},
  now = new Date(),
) {
  const difference = dateValue(value).getTime() - now.getTime();
  const days = Math.round(difference / 86_400_000);
  if (Math.abs(days) < 1)
    return new Intl.RelativeTimeFormat(activeLocale(preferences.locale), {
      numeric: "auto",
    }).format(0, "day");
  if (Math.abs(days) < 30)
    return new Intl.RelativeTimeFormat(activeLocale(preferences.locale), {
      numeric: "auto",
    }).format(days, "day");
  return new Intl.RelativeTimeFormat(activeLocale(preferences.locale), {
    numeric: "auto",
  }).format(Math.round(days / 30), "month");
}

export function formatNumber(value: number, locale?: string | null) {
  return new Intl.NumberFormat(activeLocale(locale)).format(value);
}
export function formatCurrency(
  value: number,
  currency = "INR",
  locale?: string | null,
) {
  return new Intl.NumberFormat(activeLocale(locale), {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}
export function formatPercentage(value: number, locale?: string | null) {
  return new Intl.NumberFormat(activeLocale(locale), {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}
export function localizedCollator(locale?: string | null) {
  return new Intl.Collator(activeLocale(locale), {
    sensitivity: "base",
    numeric: true,
  });
}
