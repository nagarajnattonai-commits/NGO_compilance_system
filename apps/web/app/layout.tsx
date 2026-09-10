import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import "./reference-theme.css";
import "./auth.css";
import "./theme.css";

const themeBootScript = `(function(){try{var saved=localStorage.getItem('setu-theme');var preferred=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.dataset.theme=saved==='light'||saved==='dark'?saved:preferred;}catch(error){document.documentElement.dataset.theme='light';}})();`;

export const metadata: Metadata = {
  title: "Setu — NGO Operating System",
  description: "A connected management workspace for NGO compliance, evidence, tasks and portfolio health.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning data-scroll-behavior="smooth">
      <body>{children}<Script id="setu-theme" strategy="beforeInteractive">{themeBootScript}</Script></body>
    </html>
  );
}
