"use client";
import Link from "next/link";
import { useTranslations } from "next-intl";
import LocaleSwitcher from "./locale-switcher";
import ThemeToggle from "./theme-toggle";

export default function ComplianceMasterShell({ children, dirty = false }: { children: React.ReactNode; dirty?: boolean }) {
  const t = useTranslations("ComplianceMaster");
  function leave(event: React.MouseEvent) { if (dirty && !window.confirm(t("unsaved"))) event.preventDefault(); }
  return <main className="account-page compliance-master-page"><header className="account-header">
    <Link className="account-brand" href="/admin" onClick={leave}>{t("platform")}</Link>
    <LocaleSwitcher compact beforeChange={() => !dirty || window.confirm(t("unsaved"))} /><ThemeToggle variant="icon" />
  </header><div className="account-content"><nav className="master-breadcrumb" aria-label={t("navigation")}>
    <Link href="/admin" onClick={leave}>{t("platform")}</Link><span aria-hidden="true">/</span><Link href="/admin/compliance-master" onClick={leave}>{t("title")}</Link>
  </nav>{children}</div></main>;
}
