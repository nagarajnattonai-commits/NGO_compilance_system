import type { AppLocale } from "./config";

export const messageModules = [
  "common",
  "dashboard",
  "compliance",
  "calendar",
  "tasks",
  "documents",
  "reports",
  "settings",
  "auth",
  "whiteLabel",
  "marketing",
  "complianceMaster",
  "integrations",
] as const;
export type MessageModule = (typeof messageModules)[number];

const loaders = {
  "en-IN": () =>
    Promise.all([
      import("../messages/en-IN/common.json"),
      import("../messages/en-IN/dashboard.json"),
      import("../messages/en-IN/compliance.json"),
      import("../messages/en-IN/calendar.json"),
      import("../messages/en-IN/tasks.json"),
      import("../messages/en-IN/documents.json"),
      import("../messages/en-IN/reports.json"),
      import("../messages/en-IN/settings.json"),
      import("../messages/en-IN/auth.json"),
      import("../messages/en-IN/white-label.json"),
      import("../messages/en-IN/marketing.json"),
      import("../messages/en-IN/compliance-master.json"),
      import("../messages/en-IN/integrations.json"),
    ]),
  "hi-IN": () =>
    Promise.all([
      import("../messages/hi-IN/common.json"),
      import("../messages/hi-IN/dashboard.json"),
      import("../messages/hi-IN/compliance.json"),
      import("../messages/hi-IN/calendar.json"),
      import("../messages/hi-IN/tasks.json"),
      import("../messages/hi-IN/documents.json"),
      import("../messages/hi-IN/reports.json"),
      import("../messages/hi-IN/settings.json"),
      import("../messages/hi-IN/auth.json"),
      import("../messages/hi-IN/white-label.json"),
      import("../messages/hi-IN/marketing.json"),
      import("../messages/hi-IN/compliance-master.json"),
      import("../messages/hi-IN/integrations.json"),
    ]),
  "kn-IN": () =>
    Promise.all([
      import("../messages/kn-IN/common.json"),
      import("../messages/kn-IN/dashboard.json"),
      import("../messages/kn-IN/compliance.json"),
      import("../messages/kn-IN/calendar.json"),
      import("../messages/kn-IN/tasks.json"),
      import("../messages/kn-IN/documents.json"),
      import("../messages/kn-IN/reports.json"),
      import("../messages/kn-IN/settings.json"),
      import("../messages/kn-IN/auth.json"),
      import("../messages/kn-IN/white-label.json"),
      import("../messages/kn-IN/marketing.json"),
      import("../messages/kn-IN/compliance-master.json"),
      import("../messages/kn-IN/integrations.json"),
    ]),
  "mr-IN": () =>
    Promise.all([
      import("../messages/mr-IN/common.json"),
      import("../messages/mr-IN/dashboard.json"),
      import("../messages/mr-IN/compliance.json"),
      import("../messages/mr-IN/calendar.json"),
      import("../messages/mr-IN/tasks.json"),
      import("../messages/mr-IN/documents.json"),
      import("../messages/mr-IN/reports.json"),
      import("../messages/mr-IN/settings.json"),
      import("../messages/mr-IN/auth.json"),
      import("../messages/mr-IN/white-label.json"),
      import("../messages/mr-IN/marketing.json"),
      import("../messages/mr-IN/compliance-master.json"),
      import("../messages/mr-IN/integrations.json"),
    ]),
} satisfies Record<
  AppLocale,
  () => Promise<Array<{ default: Record<string, unknown> }>>
>;

export async function loadMessages(locale: AppLocale) {
  const selected = await loadLocaleMessages(locale);
  if (locale === "en-IN") return selected;
  const english = await loadLocaleMessages("en-IN");
  return mergeMessages(english, selected);
}

export async function loadLocaleMessages(locale: AppLocale) {
  const modules = await loaders[locale]();
  return Object.assign(
    {},
    ...modules.map((module) => module.default),
  ) as Record<string, unknown>;
}

export function mergeMessages(
  fallback: Record<string, unknown>,
  translated: Record<string, unknown>,
): Record<string, unknown> {
  const merged = { ...fallback };
  Object.entries(translated).forEach(([key, value]) => {
    const base = fallback[key];
    if (typeof value === "string" && !value.trim() && typeof base === "string") return;
    merged[key] =
      value && typeof value === "object" && base && typeof base === "object"
        ? mergeMessages(
            base as Record<string, unknown>,
            value as Record<string, unknown>,
          )
        : value;
  });
  return merged;
}

export function flattenMessages(
  value: Record<string, unknown>,
  prefix = "",
  output: Record<string, string> = {},
) {
  Object.entries(value).forEach(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof child === "string") output[path] = child;
    else if (child && typeof child === "object")
      flattenMessages(child as Record<string, unknown>, path, output);
  });
  return output;
}
