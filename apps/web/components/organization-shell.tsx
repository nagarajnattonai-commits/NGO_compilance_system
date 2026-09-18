"use client";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { BrandIdentity } from "@/branding/client";
import LocaleSwitcher from "./locale-switcher";
import ThemeToggle from "./theme-toggle";
import "./organization-profile.css";
export default function OrganizationShell({children}:{children:React.ReactNode}) {
 const t=useTranslations("Organization");
 return <main className="account-page organization-page"><header className="account-header"><Link className="account-brand" href="/dashboard"><BrandIdentity variant="compact"/></Link><Link href="/dashboard">{t("workspace")}</Link><LocaleSwitcher compact/><ThemeToggle variant="icon"/></header><div className="account-content">{children}</div></main>;
}
