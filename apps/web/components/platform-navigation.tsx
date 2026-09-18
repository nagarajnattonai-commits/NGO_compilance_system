"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";

export default function PlatformNavigation() {
  const t = useTranslations("ComplianceMaster");
  const [allowed, setAllowed] = useState(false);
  useEffect(() => { apiRequest<{ allowed: boolean }>("/admin/compliance-master/access").then((result) => setAllowed(result.allowed)).catch(() => setAllowed(false)); }, []);
  if (!allowed) return null;
  return <section className="card platform-navigation"><h2>{t("platform")}</h2><nav aria-label={t("platform")}>
    <Link className="button secondary" href="/admin/compliance-master">{t("title")}</Link>
    <Link className="button secondary" href="/admin/white-label">{t("whiteLabel")}</Link>
  </nav></section>;
}
