"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import type { Organization } from "@/lib/types";

export default function OrganizationComplianceProfile({ organizations }: { organizations: Organization[] }) {
  const t = useTranslations("ComplianceMaster"); const [open, setOpen] = useState(false);
  return <details className="card" onToggle={(event) => setOpen(event.currentTarget.open)} style={{ padding: 20 }}><summary>{t("profile")}</summary>{open && <ProfileEditor organizations={organizations} />}</details>;
}
function ProfileEditor({ organizations }: { organizations: Organization[] }) {
  const t = useTranslations("ComplianceMaster");
  const [organizationId, setOrganizationId] = useState(organizations[0]?.id || ""); const [revenue, setRevenue] = useState(""); const [period, setPeriod] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState(false); const [saved, setSaved] = useState(false); const [results, setResults] = useState<{ code: string; applicable: boolean; requires_review?: string }[]>([]);
  useEffect(() => { let active = true; setBusy(true); setSaved(false); setResults([]); if (organizationId) apiRequest<{ annual_revenue: string | number | null; revenue_period: string }>(`/organizations/${organizationId}/compliance-profile`)
    .then((profile) => { if (active) { setRevenue(profile.annual_revenue === null ? "" : String(profile.annual_revenue)); setPeriod(profile.revenue_period); setError(false); } }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setBusy(false); });
    else setBusy(false); return () => { active = false; }; }, [organizationId]);
  async function action(kind: string) {
    setBusy(true); setError(false); setSaved(false);
    try {
      if (kind === "save") { await apiRequest(`/organizations/${organizationId}/compliance-profile`, "PATCH", { annual_revenue: revenue || null, revenue_period: period }); setSaved(true); }
      if (kind === "evaluate") { const result = await apiRequest<{ results: typeof results }>(`/organizations/${organizationId}/evaluate-compliance`, "POST"); setResults(result.results); }
      if (kind === "generate" && window.confirm(t("confirmAction"))) { await apiRequest(`/organizations/${organizationId}/generate-plan`, "POST"); window.location.reload(); }
    } catch { setError(true); } finally { setBusy(false); }
  }
  return <div className="form">{error && <p className="auth-alert error" role="alert">{t("actionFailed")}</p>}{saved && <p role="status">{t("saved")}</p>}
    <label>{t("sampleOrganization")}<select value={organizationId} disabled={busy} onChange={(e) => setOrganizationId(e.target.value)}>{organizations.map((organization) => <option value={organization.id} key={organization.id}>{organization.name}</option>)}</select></label>
    <label>{t("annualRevenue")}<input type="number" min={0} step="0.01" disabled={busy} value={revenue} onChange={(e) => { setRevenue(e.target.value); setSaved(false); }} /></label><label>{t("revenuePeriod")}<input disabled={busy} maxLength={30} value={period} onChange={(e) => { setPeriod(e.target.value); setSaved(false); }} /></label>
    <div className="heading-actions"><button className="button primary" disabled={busy || !organizationId || (!!revenue && !period)} onClick={() => void action("save")}>{t("save")}</button><button className="button secondary" disabled={busy || !organizationId} onClick={() => void action("evaluate")}>{t("evaluate")}</button><button className="button secondary" disabled={busy || !organizationId} onClick={() => void action("generate")}>{t("generate")}</button></div>
    <ul>{results.map((result) => <li key={result.code}>{result.code}: {t(result.requires_review ? "requiresReview" : result.applicable ? "applicable" : "notApplicable")}</li>)}</ul>
  </div>;
}
