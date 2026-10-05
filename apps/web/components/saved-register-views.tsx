"use client";

import { useEffect, useRef, useState } from "react";
import { apiRequest } from "@/lib/http";

export type RegisterFilters = { query?: string; organization_id?: string | null; status?: string | null;
  assignee?: string | null; owner?: string | null; priority?: string | null; date_from?: string | null;
  date_to?: string | null; timing?: string };
type SavedView = { id: string; name: string; filters: RegisterFilters; is_default: boolean;
  sorting: { by: string; direction: string }; visible_columns: string[] };

export function requireCompatibleFilters(filters: RegisterFilters, supported: string[]) {
  for (const [key, value] of Object.entries(filters as Record<string, unknown>)) {
    if (supported.includes(key) || value == null || value === "" || value === "ALL" ||
        Array.isArray(value) && !value.length || key === "upcoming_days" && value === 30) continue;
    throw new Error(`This screen does not support the saved ${key} filter.`);
  }
}

export default function SavedRegisterViews({ scope, filters, apply, unavailable = "" }: {
  scope: "COMPLIANCES" | "TASKS" | "REPORTS"; filters: RegisterFilters;
  apply: (filters: RegisterFilters) => void; unavailable?: string;
}) {
  const [items, setItems] = useState<SavedView[]>([]), [name, setName] = useState("");
  const [makeDefault, setMakeDefault] = useState(false), [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const latestApply = useRef(apply); latestApply.current = apply;
  function restore(view: SavedView) {
    if (view.visible_columns.length || view.sorting.by !== "relevance") throw new Error("This saved view uses columns or sorting that this screen does not support.");
    latestApply.current(view.filters);
  }
  useEffect(() => {
    let active = true;
    apiRequest<SavedView[]>(`/saved-views?scope=${scope}`).then(rows => {
      if (!active) return; setItems(rows);
      const defaultView = rows.find(row => row.is_default); if (defaultView) restore(defaultView);
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "Could not load saved views"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scope]);
  async function refresh() {
    setLoading(true); setError("");
    try { setItems(await apiRequest<SavedView[]>(`/saved-views?scope=${scope}`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load saved views"); }
    finally { setLoading(false); }
  }
  async function save() {
    if (busy || !name.trim() || unavailable) return;
    setBusy(true); setError("");
    try {
      await apiRequest("/saved-views", "POST", { name: name.trim(), scope, filters,
        sorting: { by: "relevance", direction: "asc" }, visible_columns: [], is_default: makeDefault });
      setName(""); setMakeDefault(false); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save view"); }
    finally { setBusy(false); }
  }
  async function remove(view: SavedView) {
    if (busy || !window.confirm(`Delete personal saved view "${view.name}"? Records will not be deleted.`)) return;
    setBusy(true); setError("");
    try { await apiRequest(`/saved-views/${view.id}`, "DELETE"); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not delete saved view"); }
    finally { setBusy(false); }
  }
  return <section aria-label={`${scope} saved views`}>
    <div className="saved-view-bar">
      <strong>Personal saved views</strong>
      {items.map(view => <span className="saved-view-chip" key={view.id}>
        <button disabled={busy || loading} onClick={() => { setError(""); try { restore(view); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not apply view"); } }}>{view.name}{view.is_default ? " (default)" : ""}</button>
        <button disabled={busy || loading} aria-label={`Delete saved view ${view.name}`} onClick={() => void remove(view)}>×</button>
      </span>)}
      <input aria-label="Saved view name" maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder="Saved view name"/>
      <label className="saved-view-default"><input type="checkbox" checked={makeDefault} onChange={event => setMakeDefault(event.target.checked)}/>Default view</label>
      <button disabled={busy || loading || !name.trim() || !!unavailable} onClick={() => void save()}>Save current view</button>
      <button disabled={busy || loading} onClick={() => void refresh()}>Refresh saved views</button>
    </div>
    {loading && <p role="status">Loading saved views...</p>}
    {!loading && !items.length && <p>No personal views saved for this screen.</p>}
    {unavailable && <p>{unavailable}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}
