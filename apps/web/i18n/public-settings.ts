import "server-only";
import { cache } from "react";
import { cookies } from "next/headers";
import { brandingRequestHeaders } from "@/branding/server";
import type { LocalizationSettings, TranslationOverride } from "@/lib/types";

// Request-scoped cache only: never share authenticated settings between tenants.
async function authenticatedLocalization<T>(path: string): Promise<T | null> {
  const token = (await cookies()).get("setu_session")?.value;
  if (!token) return null;
  try {
    const response = await fetch(
      `${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/localization/${path}`,
      {
        headers: {
          ...(await brandingRequestHeaders()),
          Cookie: `setu_session=${encodeURIComponent(token)}`,
        },
        cache: "no-store",
        signal: AbortSignal.timeout(4000),
      },
    );
    return response.ok ? await response.json() : null;
  } catch {
    // Availability of preferences must never prevent fallback page rendering.
    return null;
  }
}

export const getPublicLocalizationSettings = cache(() =>
  authenticatedLocalization<LocalizationSettings>("settings"),
);

export const getPublicTranslationOverrides = cache((locale: string) =>
  authenticatedLocalization<TranslationOverride[]>(
    `overrides?locale_code=${encodeURIComponent(locale)}`,
  ),
);
