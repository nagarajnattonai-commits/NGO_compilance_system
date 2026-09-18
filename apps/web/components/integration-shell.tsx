"use client";
import Link from "next/link";
import { useTranslations } from "next-intl";
import LocaleSwitcher from "./locale-switcher";
import ThemeToggle from "./theme-toggle";
import { BrandIdentity } from "@/branding/client";
import type { IntegrationScope } from "@/lib/integrations";
import "./integration-management.css";
export default function IntegrationShell({scope,developer=false,children,permissions}:{scope:IntegrationScope;developer?:boolean;children:React.ReactNode;permissions?:string[]}) {
 const t=useTranslations("Integrations");
 const base=scope==="platform"?(developer?"/admin/developers":"/admin/integrations"):developer?"/settings/developers":"/settings/integrations";
 const sections=developer?["applications","apiKeys","webhooks","usage","documentation","oauth"]:scope==="platform"?["providers","connections","credentials","webhooks","logs","health","tenants","audit"]:["connections","providers","webhooks","health","logs"];
 return <main className="account-page integration-page"><header className="account-header"><Link className="account-brand" href={scope==="platform"?"/admin":"/dashboard"}><BrandIdentity variant="compact" /></Link><LocaleSwitcher compact/><ThemeToggle variant="icon"/></header><div className="account-content"><nav className="integration-tabs" aria-label={t("navigation")}><Link href={scope==="platform"?"/admin":"/dashboard"}>{t("workspace")}</Link>{sections.filter(section=>!permissions||((section==="health")?permissions.includes("integrations.health.view"):(section==="logs"||section==="audit")?permissions.includes("integrations.logs.view"):true)).map(section=><Link key={section} href={base+"/"+(section==="apiKeys"?"api-keys":section)}>{t("sections."+section)}</Link>)}{scope==="platform"&&<Link href={developer?"/admin/integrations":"/admin/developers"}>{t(developer?"title":"developers")}</Link>}{scope==="tenant"&&<Link href={developer?"/settings/integrations":"/settings/developers"}>{t(developer?"title":"developers")}</Link>}</nav>{children}</div></main>;
}
