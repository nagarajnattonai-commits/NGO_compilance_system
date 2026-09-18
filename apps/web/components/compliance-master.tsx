"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Plus, Search } from "lucide-react";
import { apiRequest } from "@/lib/http";
import { actOnTemplate, templatePath, type ComplianceCategory, type ComplianceTemplate, type TemplateList } from "@/lib/compliance-master";
import { formatDateTime, formatNumber } from "@/i18n/format";
import ComplianceMasterShell from "./compliance-master-shell";

export const frequencies = ["ONE_TIME", "MONTHLY", "QUARTERLY", "HALF_YEARLY", "ANNUAL", "CUSTOM", "EVENT_BASED"];
export const templateStatuses = ["DRAFT", "UNDER_REVIEW", "APPROVED", "PUBLISHED", "ARCHIVED"];
export const risks = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

export default function ComplianceMaster() {
  const t = useTranslations("ComplianceMaster");
  const locale = useLocale();
  const [data, setData] = useState<TemplateList | null>(null);
  const [categories, setCategories] = useState<ComplianceCategory[]>([]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState("updated_at");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [categoryName, setCategoryName] = useState("");
  const [permissions, setPermissions] = useState<string[]>([]);
  const can = (action: string) => permissions.includes("compliance_master." + action);
  const requestNumber = useRef(0);
  const refreshCategories = useCallback(() => apiRequest<ComplianceCategory[]>("/admin/compliance-categories").then(setCategories), []);
  const refresh = useCallback(async () => {
    const number = ++requestNumber.current;
    const params = new URLSearchParams({ search: query, page: String(page), sort, order, page_size: "20" });
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
    setLoading(true);
    try { const result = await apiRequest<TemplateList>(`${templatePath}?${params}`); if (number === requestNumber.current) { setData(result); setError(""); } }
    catch { if (number === requestNumber.current) setError(t("failed")); } finally { if (number === requestNumber.current) setLoading(false); }
  }, [query, page, sort, order, filters, t]);
  useEffect(() => { const timer = setTimeout(() => { setQuery(search); setPage(1); }, 300); return () => clearTimeout(timer); }, [search]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { apiRequest<{ permissions: string[] }>("/admin/compliance-master/access").then((access) => setPermissions(access.permissions)).catch(() => setPermissions([])); }, []);
  useEffect(() => { refreshCategories().catch(() => setError(t("failed"))); }, [refreshCategories, t]);
  async function action(row: ComplianceTemplate, name: string) {
    if (!window.confirm(t("confirmAction"))) return;
    setBusy(true); setError("");
    try {
      if (name === "clone") {
        const code = window.prompt(t("newCode"));
        if (!code) return;
        const source = await apiRequest<ComplianceTemplate>(`${templatePath}/${row.id}`);
        await apiRequest(`${templatePath}/${row.id}/clone`, "POST", { code, configuration: source.configuration, change_summary: t("cloneSummary") });
      } else {
        const summary = name === "new-version" ? window.prompt(t("changeSummary")) : "";
        if (name === "new-version" && !summary) return;
        await actOnTemplate(row, name, summary || "");
      }
      await refresh();
    } catch { setError(t("actionFailed")); } finally { setBusy(false); }
  }
  function filter(key: string, value: string) { setFilters((old) => ({ ...old, [key]: value })); setPage(1); }
  async function saveCategory(row?: ComplianceCategory) {
    setBusy(true); setError("");
    try {
      await apiRequest(`/admin/compliance-categories${row ? `/${row.id}` : ""}`, row ? "PATCH" : "POST", row ? { name: row.name, enabled: row.enabled, sort_order: row.sort_order } : { name: categoryName, sort_order: categories.length });
      setCategoryName(""); await refreshCategories(); await refresh();
    } catch { setError(t("actionFailed")); } finally { setBusy(false); }
  }
  return <ComplianceMasterShell><div className="master-heading"><div><h1>{t("title")}</h1><p className="account-intro">{t("intro")}</p></div>
    {can("create") && <Link className="button primary" href="/admin/compliance-master/new"><Plus size={18} />{t("create")}</Link>}</div>
    {error && <div className="auth-alert error" role="alert">{error} <button className="text-button" onClick={() => void refresh()}>{t("retry")}</button></div>}
    <section className="master-kpis" aria-label={t("summary")}>
      {["total", "PUBLISHED", "DRAFT", "UNDER_REVIEW", "ARCHIVED"].map((state) => <div className="card" key={state}><span>{t(state === "total" ? "total" : `states.${state}`)}</span><strong>{formatNumber(state === "total" ? Object.values(data?.counts || {}).reduce((a, b) => a + b, 0) : data?.counts[state] || 0, locale)}</strong></div>)}
    </section>
    <section className="card master-filters"><label className="master-search"><Search size={17} /><span className="sr-only">{t("search")}</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("search")} /></label>
      <div className="master-form-grid">
        <label>{t("status")}<select aria-label={t("status")} value={filters.status || ""} onChange={(e) => filter("status", e.target.value)}><option value="">{t("all")}</option>{templateStatuses.map((value) => <option key={value} value={value}>{t(`states.${value}`)}</option>)}</select></label>
        <label>{t("category")}<select aria-label={t("category")} value={filters.category_id || ""} onChange={(e) => filter("category_id", e.target.value)}><option value="">{t("all")}</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label>{t("frequency")}<select aria-label={t("frequency")} value={filters.frequency || ""} onChange={(e) => filter("frequency", e.target.value)}><option value="">{t("all")}</option>{frequencies.map((value) => <option key={value} value={value}>{t(`frequencies.${value}`)}</option>)}</select></label>
        <label>{t("risk")}<select aria-label={t("risk")} value={filters.risk_level || ""} onChange={(e) => filter("risk_level", e.target.value)}><option value="">{t("all")}</option>{risks.map((value) => <option key={value} value={value}>{t(`risks.${value}`)}</option>)}</select></label>
        {["jurisdiction", "organization_type", "version", "updated_from", "updated_to"].map((key) => <label key={key}>{t(key)}<input type={key.startsWith("updated_") ? "date" : key === "version" ? "number" : "text"} min={key === "version" ? 1 : undefined} value={filters[key] || ""} onChange={(e) => filter(key, e.target.value)} /></label>)}
        <label>{t("sort")}<select aria-label={t("sort")} value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>{["name", "code", "category", "updated_at", "version", "status"].map((key) => <option key={key} value={key}>{t(key)}</option>)}</select></label>
        <label>{t("order")}<select aria-label={t("order")} value={order} onChange={(e) => setOrder(e.target.value)}><option value="asc">{t("ascending")}</option><option value="desc">{t("descending")}</option></select></label>
      </div><button className="button secondary" onClick={() => { setFilters({}); setSearch(""); setPage(1); }}>{t("clear")}</button>
    </section>
    <section className="card"><div className="master-table-scroll" role="region" aria-label={t("title")} tabIndex={0}><table className="master-table"><thead><tr>{["name", "code", "category", "jurisdiction", "organization_type", "frequency", "version", "status", "updated_at", "updatedBy", "actions"].map((key) => <th key={key} scope="col">{t(key)}</th>)}</tr></thead><tbody>
      {data?.items.map((row) => <tr key={row.id}>
        <td><Link className="master-truncate" title={row.name} href={`/admin/compliance-master/${row.id}`}>{row.name || t("untitled")}</Link></td><td><code>{row.code}</code></td><td><span className="master-truncate" title={row.category}>{row.category}</span></td><td>{row.jurisdiction}</td><td>{row.organization_types === "ALL" ? t("all") : row.organization_types === "RULES" ? t("configuredRules") : row.organization_types}</td><td>{t(`frequencies.${row.frequency}`)}</td><td>v{row.version}{row.current_version && row.current_version !== row.version && <small>{t("publishedVersion", { version: row.current_version })}</small>}</td><td>{t(`states.${row.status}`)}</td><td>{formatDateTime(row.updated_at, { locale })}</td><td>{row.updated_by}</td><td>
          <details className="master-row-actions"><summary>{t("actions")}</summary><div>
            <Link href={`/admin/compliance-master/${row.id}`}>{t(can("edit") && row.status === "DRAFT" ? "edit" : "view")}</Link>
            <Link href={`/admin/compliance-master/${row.id}#review`}>{t("preview")}</Link>
            <Link href={`/admin/compliance-master/${row.id}#history`}>{t("history")}</Link>
            {can("clone") && <button disabled={busy} onClick={() => void action(row, "clone")}>{t("clone")}</button>}
            {can("edit") && row.status === "DRAFT" && <button disabled={busy} onClick={() => void action(row, "submit-review")}>{t("submit")}</button>}
            {can("review") && row.status === "UNDER_REVIEW" && <button disabled={busy} onClick={() => void action(row, "approve")}>{t("approve")}</button>}
            {can("publish") && row.status === "APPROVED" && <button disabled={busy} onClick={() => void action(row, "publish")}>{t("publish")}</button>}
            {can("version") && ["PUBLISHED", "ARCHIVED"].includes(row.status) && <button disabled={busy} onClick={() => void action(row, "new-version")}>{t("newVersion")}</button>}
            {can("archive") && row.status !== "ARCHIVED" && <button disabled={busy} onClick={() => void action(row, "archive")}>{t("archive")}</button>}
          </div></details>
        </td></tr>)}
    </tbody></table></div>
      {loading && <p role="status">{t("loading")}</p>}
      {!loading && !data?.items.length && <div className="master-empty"><h2>{t("empty")}</h2><p>{t("emptyDescription")}</p></div>}
      <div className="master-pagination"><span>{t("results", { count: data?.total || 0 })}</span><button className="button secondary" disabled={page === 1 || loading} onClick={() => setPage(page - 1)}>{t("previous")}</button><span>{formatNumber(page, locale)}</span><button className="button secondary" disabled={loading || page * 20 >= (data?.total || 0)} onClick={() => setPage(page + 1)}>{t("next")}</button></div>
    </section>
    <details className="card master-category-editor"><summary>{t("categories")}</summary><div className="master-form-grid"><label>{t("category")}<input maxLength={60} value={categoryName} onChange={(e) => setCategoryName(e.target.value)} /></label><button className="button primary" disabled={!can("create") || !categoryName.trim() || busy} onClick={() => void saveCategory()}>{t("add")}</button></div>
      {categories.map((row, index) => <div className="master-category-row" key={row.id}><label><span className="sr-only">{t("name")}</span><input maxLength={60} value={row.name} onChange={(e) => setCategories((old) => old.map((c, i) => i === index ? { ...c, name: e.target.value } : c))} /></label><label>{t("order")}<input type="number" min={0} value={row.sort_order} onChange={(e) => setCategories((old) => old.map((c, i) => i === index ? { ...c, sort_order: Number(e.target.value) } : c))} /></label><label className="master-checkbox"><input type="checkbox" checked={row.enabled} onChange={(e) => setCategories((old) => old.map((c, i) => i === index ? { ...c, enabled: e.target.checked } : c))} />{t("enabled")}</label><button className="button secondary" disabled={!can("edit") || busy || !row.name.trim()} onClick={() => void saveCategory(row)}>{t("save")}</button></div>)}
    </details>
  </ComplianceMasterShell>;
}
