import "server-only";
import { cache } from "react";
import { cookies, headers } from "next/headers";
import type { PublicBrand } from "./types";
import { platformBrand } from "./theme";

export async function brandingRequestHeaders() {
  const requestHeaders = await headers();
  const host = requestHeaders.get("host") || "localhost:3000";
  let hostname = "";
  try {
    hostname = new URL(`http://${host}`).hostname
      .toLowerCase()
      .replace(/\.$/, "");
  } catch {
    /* Reject malformed hosts rather than interrupting fallback rendering. */
  }
  return {
    "X-Setu-Host": hostname,
    "X-Setu-Proxy-Key":
      process.env.BRAND_PROXY_KEY ||
      (process.env.APP_ENV !== "production" ? "setu-development-proxy" : ""),
  };
}

export const getServerBrand = cache(
  async (locale: string): Promise<PublicBrand> => {
    const token = (await cookies()).get("setu_session")?.value;
    const requestHeaders = await brandingRequestHeaders();
    const endpoint = token
      ? `/white-label/published?locale=${encodeURIComponent(locale)}`
      : `/white-label/public?hostname=${encodeURIComponent(requestHeaders["X-Setu-Host"])}&locale=${encodeURIComponent(locale)}`;
    try {
      const response = await fetch(
        `${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1${endpoint}`,
        {
          headers: {
            ...requestHeaders,
            ...(token
              ? { Cookie: `setu_session=${encodeURIComponent(token)}` }
              : {}),
          },
          cache: "no-store",
          signal: AbortSignal.timeout(4000),
        },
      );
      if (response.ok) return await response.json();
      if (token) {
        const publicResponse = await fetch(
          `${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/white-label/public?hostname=${encodeURIComponent(requestHeaders["X-Setu-Host"])}&locale=${encodeURIComponent(locale)}`,
          { cache: "no-store", signal: AbortSignal.timeout(4000) },
        );
        if (publicResponse.ok) return await publicResponse.json();
      }
    } catch {
      /* Branding availability must never break the platform fallback. */
    }
    return platformBrand;
  },
);
