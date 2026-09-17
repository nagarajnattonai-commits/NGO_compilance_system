"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import type { PublicBrand } from "./types";
import { brandingStyles, platformBrand } from "./theme";

const BrandContext = createContext<PublicBrand>(platformBrand);
export function TenantBrandProvider({
  brand,
  children,
}: {
  brand: PublicBrand;
  children: React.ReactNode;
}) {
  const [snapshot, setSnapshot] = useState(brand);
  useEffect(() => {
    let lastCheck = 0;
    let pending = false;
    const refresh = async () => {
      // Public/auth pages must not make an authenticated request. A root layout
      // persists during navigation, so recheck on focus without a render-time
      // window branch or automatic reload that would discard an unsaved draft.
      if (
        !/^\/(dashboard|settings|admin)(?:\/|$)/.test(
          window.location.pathname,
        ) ||
        window.location.pathname === "/admin/login" ||
        document.visibilityState !== "visible" ||
        pending ||
        Date.now() - lastCheck < 30_000
      )
        return;
      lastCheck = Date.now();
      pending = true;
      try {
        const response = await fetch("/api/v1/white-label/published", {
          credentials: "same-origin",
          cache: "no-store",
        });
        if (!response.ok) return;
        const next: PublicBrand = await response.json();
        if (
          next.enabled !== snapshot.enabled ||
          next.version !== snapshot.version
        ) {
          document.documentElement.dataset.whiteLabel = next.enabled
            ? "true"
            : "false";
          let tokens = document.getElementById("setu-brand-tokens");
          if (!tokens) {
            tokens = document.createElement("style");
            tokens.id = "setu-brand-tokens";
            document.head.append(tokens);
          }
          tokens.textContent = brandingStyles(next);
          document.title = document.title.replace(
            snapshot.product_name,
            next.product_name,
          );
          document
            .querySelectorAll<HTMLLinkElement>(
              'link[rel="icon"], link[rel="apple-touch-icon"]',
            )
            .forEach((icon) => {
              if (next.assets.FAVICON) icon.href = next.assets.FAVICON;
              else if (
                icon
                  .getAttribute("href")
                  ?.startsWith("/api/v1/white-label/assets/")
              )
                icon.remove();
            });
          if (
            next.assets.FAVICON &&
            !document.querySelector('link[rel="icon"]')
          ) {
            const icon = document.createElement("link");
            icon.rel = "icon";
            icon.href = next.assets.FAVICON;
            document.head.append(icon);
          }
          setSnapshot(next);
        }
      } catch {
        /* Keep the current stable snapshot on transient API failure. */
      } finally {
        pending = false;
      }
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [snapshot.enabled, snapshot.version, snapshot.product_name]);
  return (
    <BrandContext.Provider value={snapshot}>{children}</BrandContext.Provider>
  );
}
export const useTenantBrand = () => useContext(BrandContext);

export function BrandLogo({
  variant = "primary",
}: {
  variant?: "primary" | "compact" | "login" | "report";
}) {
  const brand = useTenantBrand();
  const [failed, setFailed] = useState<string[]>([]);
  const assets = brand.assets;
  const primary = assets.PRIMARY_LOGO;
  const source =
    variant === "compact"
      ? assets.COMPACT_LOGO || primary
      : variant === "login"
        ? assets.LOGIN_LOGO || primary
        : variant === "report"
          ? assets.REPORT_LOGO || primary
          : primary;
  const light = variant === "primary" ? assets.LIGHT_LOGO || source : source;
  const dark =
    variant === "primary"
      ? assets.DARK_LOGO || source
      : assets.DARK_LOGO || source;
  const usableLight = light && !failed.includes(light);
  const usableDark = dark && !failed.includes(dark);
  if (!brand.enabled || (!usableLight && !usableDark))
    return <ShieldCheck size={25} aria-hidden="true" />;
  const fail = (url: string) => setFailed((current) => [...current, url]);
  return (
    <span className="tenant-logo-images">
      {usableLight ? (
        <img
          className="tenant-logo-light"
          src={light}
          alt={brand.brand_name}
          onError={() => fail(light)}
        />
      ) : (
        <ShieldCheck className="tenant-logo-light" size={25} />
      )}
      {usableDark ? (
        <img
          className="tenant-logo-dark"
          src={dark}
          alt={brand.brand_name}
          onError={() => fail(dark)}
        />
      ) : (
        <ShieldCheck className="tenant-logo-dark" size={25} />
      )}
    </span>
  );
}

export function BrandIdentity({
  variant = "primary",
}: {
  variant?: "primary" | "compact" | "login";
}) {
  const brand = useTenantBrand();
  const t = useTranslations("Common");
  const product = brand.enabled ? brand.product_name : t("brand");
  const tagline = brand.enabled ? brand.tagline : t("tagline");
  return (
    <span className="tenant-brand-identity" title={product}>
      <span className="tenant-brand-logo">
        {variant === "primary" ? (
          <>
            <span className="tenant-brand-full-logo">
              <BrandLogo />
            </span>
            <span className="tenant-brand-compact-logo">
              <BrandLogo variant="compact" />
            </span>
          </>
        ) : (
          <BrandLogo variant={variant} />
        )}
      </span>
      <span className="tenant-brand-copy">
        <strong>{product}</strong>
        <small title={tagline}>{tagline}</small>
      </span>
    </span>
  );
}
