import type { Metadata } from "next";
import Script from "next/script";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { localeMetadata } from "@/i18n/config";
import { getServerBrand } from "@/branding/server";
import { TenantBrandProvider } from "@/branding/client";
import { brandingStyles } from "@/branding/theme";
import "./globals.css";
import "./reference-theme.css";
import "./auth.css";
import "./theme.css";
import "./branding.css";

const themeBootScript = `(function(){try{var saved=localStorage.getItem('setu-theme');var preferred=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.dataset.theme=saved==='light'||saved==='dark'?saved:preferred;}catch(error){document.documentElement.dataset.theme='light';}})();`;

export async function generateMetadata(): Promise<Metadata> {
  const brand = await getServerBrand(await getLocale());
  return {
    title: { default: brand.enabled ? brand.product_name : "Setu — NGO Operating System", template: `%s | ${brand.product_name}` },
    description: brand.description,
    ...(brand.assets.FAVICON ? { icons: { icon: brand.assets.FAVICON, apple: brand.assets.FAVICON } } : {}),
  };
}

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await getLocale();
  const brand = await getServerBrand(locale);
  const metadata = localeMetadata(
    locale as Parameters<typeof localeMetadata>[0],
  );
  return (
    <html
      lang={locale}
      dir={metadata.direction}
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      data-white-label={brand.enabled ? "true" : undefined}
    >
      <body suppressHydrationWarning>
        {brand.enabled && <style id="setu-brand-tokens" dangerouslySetInnerHTML={{ __html: brandingStyles(brand) }} />}
        <NextIntlClientProvider><TenantBrandProvider brand={brand}>{children}</TenantBrandProvider></NextIntlClientProvider>
        <Script id="setu-theme" strategy="beforeInteractive">
          {themeBootScript}
        </Script>
      </body>
    </html>
  );
}
