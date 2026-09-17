import type { PublicBrand, ThemeTokens } from "./types";

export const defaultLight: ThemeTokens = {
  primary: "#218838",
  secondary: "#173d30",
  accent: "#0f766e",
  background: "#f5f7f9",
  surface: "#ffffff",
  text: "#243746",
  muted: "#657584",
  border: "#dce3e8",
  success: "#218838",
  warning: "#946200",
  error: "#b42332",
};
export const defaultDark: ThemeTokens = {
  primary: "#78d995",
  secondary: "#0c251a",
  accent: "#5eead4",
  background: "#0b1511",
  surface: "#13231b",
  text: "#e4eee8",
  muted: "#a5b8ac",
  border: "#355144",
  success: "#78d995",
  warning: "#ffd280",
  error: "#ff929c",
};
export const platformBrand: PublicBrand = {
  enabled: false,
  version: 0,
  brand_name: "Setu NGO",
  product_name: "Setu NGO",
  short_name: "Setu",
  tagline: "Compliance and impact management",
  description: "A connected workspace for NGO compliance, evidence and impact.",
  assets: {},
  light: defaultLight,
  dark: defaultDark,
  login_background: "SOLID",
  support_email: "",
  support_phone: "",
  support_url: "",
  website_url: "",
  privacy_url: "",
  terms_url: "",
  footer_text: "",
  default_locale: "en-IN",
};
const safeHex = (value: string, fallback: string) =>
  /^#[\da-f]{6}$/i.test(value) ? value : fallback;
export function contrast(first: string, second: string) {
  const luminance = (color: string) => {
    const values = [1, 3, 5]
      .map((index) => parseInt(color.slice(index, index + 2), 16) / 255)
      .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return values.reduce(
      (sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i],
      0,
    );
  };
  const [light, dark] = [luminance(first), luminance(second)].sort(
    (a, b) => b - a,
  );
  return (light + 0.05) / (dark + 0.05);
}
export const foreground = (color: string) =>
  contrast(color, "#ffffff") >= contrast(color, "#000000")
    ? "#ffffff"
    : "#000000";
export function themeVariables(
  theme: ThemeTokens,
  dark = false,
): Record<string, string> {
  const fallback = dark ? defaultDark : defaultLight;
  const safe = Object.fromEntries(
    Object.entries(fallback).map(([key, value]) => [
      key,
      safeHex(theme[key as keyof ThemeTokens], value),
    ]),
  ) as ThemeTokens;
  return {
    ...Object.fromEntries(
      Object.entries(safe).map(([key, value]) => [`--brand-${key}`, value]),
    ),
    "--brand-primary-foreground": foreground(safe.primary),
    "--brand-secondary-foreground": foreground(safe.secondary),
  };
}
export function brandingStyles(brand: PublicBrand) {
  if (!brand.enabled) return "";
  const declarations = (theme: ThemeTokens, dark = false) =>
    Object.entries(themeVariables(theme, dark))
      .map(([key, value]) => `${key}:${value}`)
      .join(";");
  return `html[data-white-label="true"]{${declarations(brand.light)}}html[data-white-label="true"][data-theme="dark"]{${declarations(brand.dark, true)}}`;
}
