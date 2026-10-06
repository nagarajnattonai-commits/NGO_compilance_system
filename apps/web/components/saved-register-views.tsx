"use client";

import { localizedError } from "@/i18n/display";

import { useTranslations } from "next-intl";

import { useEffect, useRef, useState } from "react";
import { apiRequest } from "@/lib/http";

export type RegisterFilters = { query?: string; organization_id?: string | null; status?: string | null;
  assignee?: string | null; owner?: string | null; priority?: string | null; date_from?: string | null;
  date_to?: string | null; timing?: string };
type SavedView = { id: string; name: string; filters: RegisterFilters; is_default: boolean;
  sorting: { by: string; direction: string }; visible_columns: string[] };

export function requireCompatibleFilters(filters: RegisterFilters, supported: string[], unsupported?: (filter: string) => string) {
  for (const [key, value] of Object.entries(filters as Record<string, unknown>)) {
    if (supported.includes(key) || value == null || value === "" || value === "ALL" ||
        Array.isArray(value) && !value.length || key === "upcoming_days" && value === 30) continue;
    throw new Error(unsupported ? unsupported(key) : `This screen does not support the saved ${key} filter.`);
  }
}

export default function SavedRegisterViews({ scope, filters, apply, unavailable = "" }: {
  scope: "COMPLIANCES" | "TASKS" | "REPORTS"; filters: RegisterFilters;
  apply: (filters: RegisterFilters) => void; unavailable?: string;
}) {
  const uiText = useTranslations();
  const [items, setItems] = useState<SavedView[]>([]), [name, setName] = useState("");
  const [makeDefault, setMakeDefault] = useState(false), [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const latestApply = useRef(apply); latestApply.current = apply;
  function restore(view: SavedView) {
    if (view.visible_columns.length || view.sorting.by !== "relevance") throw new Error(uiText("Common.interface.thisSavedViewUsesColumnsOrSortingThatThisScreenDoesNotSupport"));
    latestApply.current(view.filters);
  }
  useEffect(() => {
    let active = true;
    apiRequest<SavedView[]>(`/saved-views?scope=${scope}`).then(rows => {
      if (!active) return; setItems(rows);
      const defaultView = rows.find(row => row.is_default); if (defaultView) restore(defaultView);
    }).catch(reason => { if (active) setError(localizedError(reason, uiText, uiText("Common.interface.couldNotLoadSavedViews"))); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scope]);
  async function refresh() {
    setLoading(true); setError("");
    try { setItems(await apiRequest<SavedView[]>(`/saved-views?scope=${scope}`)); }
    catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotLoadSavedViews"))); }
    finally { setLoading(false); }
  }
  async function save() {
    if (busy || !name.trim() || unavailable) return;
    setBusy(true); setError("");
    try {
      await apiRequest("/saved-views", "POST", { name: name.trim(), scope, filters,
        sorting: { by: "relevance", direction: "asc" }, visible_columns: [], is_default: makeDefault });
      setName(""); setMakeDefault(false); await refresh();
    } catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotSaveView"))); }
    finally { setBusy(false); }
  }
  async function remove(view: SavedView) {
    if (busy || !window.confirm(uiText("Common.interface.deleteSavedView", { name: view.name }))) return;
    setBusy(true); setError("");
    try { await apiRequest(`/saved-views/${view.id}`, "DELETE"); await refresh(); }
    catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotDeleteSavedView"))); }
    finally { setBusy(false); }
  }
  return <section aria-label={uiText("Common.interface.savedViewRegion", { scope: uiText(scope === "COMPLIANCES" ? "Common.nav.compliance" : scope === "TASKS" ? "Common.nav.tasks" : "Common.nav.reports") })}>
    <div className="saved-view-bar">
      <strong>{uiText("Common.interface.personalSavedViews")}</strong>
      {items.map(view => <span className="saved-view-chip" key={view.id}>
        <button disabled={busy || loading} onClick={() => { setError(""); try { restore(view); } catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotApplyView"))); } }}>{view.name}{view.is_default ? uiText("Common.interface.default") : ""}</button>
        <button disabled={busy || loading} aria-label={uiText("Common.interface.deleteViewLabel", { name: view.name })} onClick={() => void remove(view)}>×</button>
      </span>)}
      <input aria-label={uiText("Common.interface.savedViewName")} maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder={uiText("Common.interface.savedViewName")}/>
      <label className="saved-view-default"><input type="checkbox" checked={makeDefault} onChange={event => setMakeDefault(event.target.checked)}/>{uiText("Common.interface.defaultView")}</label>
      <button disabled={busy || loading || !name.trim() || !!unavailable} onClick={() => void save()}>{uiText("Common.interface.saveCurrentView")}</button>
      <button disabled={busy || loading} onClick={() => void refresh()}>{uiText("Common.interface.refreshSavedViews")}</button>
    </div>
    {loading && <p role="status">{uiText("Common.interface.loadingSavedViews")}</p>}
    {!loading && !items.length && <p>{uiText("Common.interface.noPersonalViewsSavedForThisScreen")}</p>}
    {unavailable && <p>{unavailable}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}
