"use client";

import { localizedError } from "@/i18n/display";

import { Bookmark, LoaderCircle, Search, SlidersHorizontal, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "../lib/http";

type Organization = { id: string; name: string };
type Compliance = { id: string; title: string; organization_id: string };
type SearchItem = {
  id: string; type: string; title: string; organization: string;
  status: string; subtitle: string; date: string | null; url: string;
};
type SearchResponse = {
  total: number;
  groups: Record<string, SearchItem[]>;
};
type Filters = {
  query: string; types: string[]; organization_id: string | null; compliance_id: string | null;
  status: string | null; priority: string | null; owner: string | null; assignee: string | null;
  date_from: string | null; date_to: string | null; timing: "ALL" | "OVERDUE" | "UPCOMING";
  document_expiry: "ALL" | "EXPIRED" | "EXPIRING" | "NO_EXPIRY";
  applicability: "ALL" | "APPLICABLE" | "NOT_APPLICABLE" | "REQUIRES_REVIEW";
  upcoming_days: number;
};
type SavedView = {
  id: string; name: string; filters: Filters;
  sorting: { by: string; direction: string }; is_default: boolean;
};

const emptyFilters: Filters = {
  query: "", types: [], organization_id: null, compliance_id: null, status: null,
  priority: null, owner: null, assignee: null, date_from: null, date_to: null,
  timing: "ALL", document_expiry: "ALL", applicability: "ALL", upcoming_days: 30,
};
const groupOrder = ["organizations", "compliances", "tasks", "documents", "registrations", "filings", "csr_partners", "csr_projects", "due_diligence"];
const searchType = (group: string) => group === "due_diligence" ? group : group.endsWith("ies") ? `${group.slice(0, -3)}y` : group.slice(0, -1);

function setOrNull(value: string) { return value || null; }

export default function GlobalSearch({ organizations, compliances }: { organizations: Organization[]; compliances: Compliance[] }) {
  const uiText = useTranslations();
  const t = useTranslations("GlobalSearch");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [open, setOpen] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [viewName, setViewName] = useState("");
  const [sortBy, setSortBy] = useState("relevance");
  const [sortDirection, setSortDirection] = useState("asc");
  const [makeDefault, setMakeDefault] = useState(false);

  useEffect(() => {
    apiRequest<SavedView[]>("/saved-views?scope=GLOBAL_SEARCH")
      .then((rows) => {
        setSavedViews(rows);
        const defaultView = rows.find((row) => row.is_default);
        if (defaultView) {
          setFilters({ ...emptyFilters, ...defaultView.filters });
          setSortBy(defaultView.sorting.by);
          setSortDirection(defaultView.sorting.direction);
        }
      })
      .catch(() => undefined);
  }, []);

  async function search(event?: FormEvent) {
    event?.preventDefault();
    setOpen(true); setLoading(true); setError("");
    const params = new URLSearchParams();
    if (filters.query.trim()) params.set("q", filters.query.trim());
    if (filters.types.length) params.set("types", filters.types.join(","));
    Object.entries(filters).forEach(([key, value]) => {
      if (["query", "types", "timing", "document_expiry", "applicability", "upcoming_days"].includes(key)) return;
      if (value) params.set(key, String(value));
    });
    params.set("timing", filters.timing); params.set("document_expiry", filters.document_expiry);
    params.set("applicability", filters.applicability); params.set("upcoming_days", String(filters.upcoming_days));
    params.set("sort_by", sortBy); params.set("sort_direction", sortDirection);
    try { setResults(await apiRequest<SearchResponse>(`/search?${params}`)); }
    catch (reason) { setError(localizedError(reason, uiText, t("error"))); }
    finally { setLoading(false); }
  }

  async function saveView() {
    if (!viewName.trim()) return;
    try {
      const saved = await apiRequest<SavedView>("/saved-views", "POST", {
        name: viewName.trim(), scope: "GLOBAL_SEARCH", filters,
        sorting: { by: sortBy, direction: sortDirection }, visible_columns: [], is_default: makeDefault,
      });
      setSavedViews((current) => [...current.map((row) => makeDefault ? { ...row, is_default: false } : row), saved]);
      setViewName(""); setMakeDefault(false); setError("");
    } catch (reason) { setError(localizedError(reason, uiText, t("error"))); }
  }

  async function removeView(id: string) {
    try { await apiRequest(`/saved-views/${id}`, "DELETE"); setSavedViews((rows) => rows.filter((row) => row.id !== id)); }
    catch (reason) { setError(localizedError(reason, uiText, t("error"))); }
  }

  function applyView(view: SavedView) {
    setFilters({ ...emptyFilters, ...view.filters }); setSortBy(view.sorting.by);
    setSortDirection(view.sorting.direction); setAdvanced(true); setOpen(true);
  }

  function update<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  return <div className="global-search-wrap">
    <form className="header-search" role="search" onSubmit={search}>
      <Search size={16} />
      <input aria-label={t("label")} placeholder={t("placeholder")} value={filters.query}
        onFocus={() => setOpen(true)} onChange={(event) => update("query", event.target.value)} />
      <button type="button" className="search-filter-trigger" aria-label={t("advanced")}
        onClick={() => { setOpen(true); setAdvanced(!advanced); }}><SlidersHorizontal size={15} /></button>
      <button type="submit">{t("go")}</button>
    </form>
    {open && <section className="global-search-panel" aria-label={t("results")}>
      <div className="global-search-panel-head">
        <strong>{t("title")}</strong>
        <button type="button" className="icon-button" aria-label={t("close")} onClick={() => setOpen(false)}><X size={17} /></button>
      </div>
      {advanced && <div className="global-search-filters">
        <label>{t("organization")}<select value={filters.organization_id || ""} onChange={(e) => update("organization_id", setOrNull(e.target.value))}>
          <option value="">{t("all")}</option>{organizations.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label>{t("groups.compliances")}<select value={filters.compliance_id || ""} onChange={(e) => update("compliance_id", setOrNull(e.target.value))}>
          <option value="">{t("all")}</option>{compliances.filter((row) => !filters.organization_id || row.organization_id === filters.organization_id).map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></label>
        <label>{t("type")}<select value={filters.types[0] || ""} onChange={(e) => update("types", e.target.value ? [e.target.value] : [])}>
          <option value="">{t("all")}</option>{groupOrder.map((type) => <option key={type} value={searchType(type)}>{t(`groups.${type}`)}</option>)}</select></label>
        <label>{t("status")}<input value={filters.status || ""} onChange={(e) => update("status", setOrNull(e.target.value))} /></label>
        <label>{t("priority")}<select value={filters.priority || ""} onChange={(e) => update("priority", setOrNull(e.target.value))}>
          <option value="">{t("all")}</option><option value="HIGH">{uiText("Common.priority.HIGH")}</option><option value="MEDIUM">{uiText("Common.priority.MEDIUM")}</option><option value="LOW">{uiText("Common.priority.LOW")}</option></select></label>
        <label>{t("owner")}<input value={filters.owner || ""} onChange={(e) => update("owner", setOrNull(e.target.value))} /></label>
        <label>{t("assignee")}<input value={filters.assignee || ""} onChange={(e) => update("assignee", setOrNull(e.target.value))} /></label>
        <label>{t("from")}<input type="date" value={filters.date_from || ""} onChange={(e) => update("date_from", setOrNull(e.target.value))} /></label>
        <label>{t("to")}<input type="date" value={filters.date_to || ""} onChange={(e) => update("date_to", setOrNull(e.target.value))} /></label>
        <label>{t("deadline")}<select value={filters.timing} onChange={(e) => update("timing", e.target.value as Filters["timing"])}>
          <option value="ALL">{t("all")}</option><option value="OVERDUE">{t("overdue")}</option><option value="UPCOMING">{t("upcoming")}</option></select></label>
        <label>{t("expiry")}<select value={filters.document_expiry} onChange={(e) => update("document_expiry", e.target.value as Filters["document_expiry"])}>
          <option value="ALL">{t("all")}</option><option value="EXPIRED">{t("expired")}</option><option value="EXPIRING">{t("expiring")}</option><option value="NO_EXPIRY">{t("noExpiry")}</option></select></label>
        <label>{t("applicability")}<select value={filters.applicability} onChange={(e) => update("applicability", e.target.value as Filters["applicability"])}>
          <option value="ALL">{t("all")}</option><option value="APPLICABLE">{t("applicable")}</option><option value="NOT_APPLICABLE">{t("notApplicable")}</option><option value="REQUIRES_REVIEW">{t("review")}</option></select></label>
        <label>{t("sort")}<select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
          <option value="relevance">{t("relevance")}</option><option value="title">{t("titleSort")}</option><option value="date">{t("dateSort")}</option><option value="status">{t("status")}</option></select></label>
        <button type="button" className="primary-button search-apply" onClick={() => void search()}>{t("apply")}</button>
      </div>}
      <div className="saved-view-bar">
        <Bookmark size={15} /><span>{t("savedViews")}</span>
        {savedViews.map((view) => <span className="saved-view-chip" key={view.id}>
          <button type="button" onClick={() => applyView(view)}>{view.name}{view.is_default ? ` · ${t("default")}` : ""}</button>
          <button type="button" aria-label={`${t("delete")} ${view.name}`} onClick={() => void removeView(view.id)}><Trash2 size={12} /></button>
        </span>)}
        <input aria-label={t("viewName")} placeholder={t("viewName")} value={viewName} onChange={(e) => setViewName(e.target.value)} />
        <label className="saved-view-default"><input type="checkbox" checked={makeDefault} onChange={(e) => setMakeDefault(e.target.checked)} />{t("default")}</label>
        <button type="button" onClick={() => void saveView()} disabled={!viewName.trim()}>{t("save")}</button>
      </div>
      <div className="global-search-results">
        {loading && <p className="search-state"><LoaderCircle className="spin" size={18} />{t("loading")}</p>}
        {!loading && error && <p className="search-state error-text">{error}</p>}
        {!loading && !error && results?.total === 0 && <p className="search-state">{t("empty")}</p>}
        {!loading && !error && results && groupOrder.map((group) => results.groups[group]?.length ? <div className="search-result-group" key={group}>
          <h4>{t(`groups.${group}`)}</h4>
          {results.groups[group].map((item) => <a href={item.url} key={`${item.type}-${item.id}`}>
            <span><strong>{item.title}</strong><small>{item.organization}{item.subtitle ? ` · ${item.subtitle}` : ""}</small></span>
            <span className="search-result-meta"><b>{item.status}</b>{item.date && <small>{item.date}</small>}</span>
          </a>)}
        </div> : null)}
        {!loading && !error && !results && <p className="search-state">{t("hint")}</p>}
      </div>
    </section>}
  </div>;
}
