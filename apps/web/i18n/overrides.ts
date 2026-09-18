import { createTranslator } from "next-intl";
import type { ReactNode } from "react";

const unsafeParts = new Set(["__proto__", "prototype", "constructor"]);

export function messageAt(messages: Record<string, unknown>, key: string): string | undefined {
  const parts = key.split(".");
  if (parts.some(part => !part || unsafeParts.has(part))) return undefined;
  let value: unknown = messages;
  for (const part of parts) {
    if (!value || typeof value !== "object" || !Object.hasOwn(value, part)) return undefined;
    value = (value as Record<string, unknown>)[part];
  }
  return typeof value === "string" ? value : undefined;
}

function variableContract(message: string) {
  // ICU apostrophe-quoted syntax is literal text, not an argument.
  const syntax = message.replace(/'(?=[{}<>#])(?:''|[^'])*'/g, "");
  const variables = new Map<string, Set<string>>();
  for (const match of syntax.matchAll(/\{\s*([^\s{},]+)\s*(?:,\s*(number|date|time|plural|selectordinal|select)\b|\})/g)) {
    const kinds = variables.get(match[1]) || new Set<string>();
    kinds.add(match[2] || "argument");
    variables.set(match[1], kinds);
  }
  for (const match of syntax.matchAll(/<([\w]+)>/g)) {
    variables.set(match[1], new Set(["tag"]));
  }
  // Repeating a typed argument inside a branch is equivalent to ICU's # token.
  for (const kinds of variables.values()) if (kinds.size > 1) kinds.delete("argument");
  return variables;
}

export function validateTranslation(reference: string, candidate: string, locale: string): boolean {
  if (!candidate.trim()) return false;
  const expected = variableContract(reference);
  const actual = variableContract(candidate);
  if (expected.size !== actual.size) return false;
  for (const [name, kinds] of expected) {
    const translated = actual.get(name);
    if (!translated || kinds.size !== translated.size || [...kinds].some(kind => !translated.has(kind))) return false;
  }
  // Let the established i18n framework compile ICU, including plural/select syntax.
  // No second parser or localization framework is required.
  let valid = true;
  const translator = createTranslator({
    locale,
    timeZone: "UTC",
    messages: { candidate },
    onError: () => { valid = false; },
  });
  const values: Record<string, number | ((chunks: ReactNode) => ReactNode)> = {};
  for (const [name, kinds] of expected) {
    values[name] = kinds.has("tag") ? chunks => chunks : 1;
  }
  translator.rich("candidate", values);
  return valid;
}

export function applyTranslationOverrides(
  base: Record<string, unknown>,
  overrides: ReadonlyArray<{ locale_code: string; translation_key: string; translation_value: string }>,
  locale: string,
) {
  const messages = structuredClone(base);
  const rejected: string[] = [];
  for (const row of overrides) {
    if (row.locale_code !== locale) continue;
    const reference = messageAt(base, row.translation_key);
    if (reference === undefined || !validateTranslation(reference, row.translation_value, locale)) {
      rejected.push(row.translation_key);
      continue;
    }
    const parts = row.translation_key.split(".");
    let target = messages;
    for (const part of parts.slice(0, -1)) target = target[part] as Record<string, unknown>;
    target[parts[parts.length - 1]] = row.translation_value;
  }
  return { messages, rejected };
}
