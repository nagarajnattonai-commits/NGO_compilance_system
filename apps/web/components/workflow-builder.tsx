"use client";

import { Clock3, Plus, Save, Settings2, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { apiRequest } from "../lib/http";

type Metadata = { triggers: string[]; condition_fields: string[]; action_types: string[];
  organizations: { id: string; name: string }[]; users: { id: string; name: string }[] };
type Condition = { field: string; operator: string; value: string | number | string[] };
type Action = { type: string; parameters: Record<string, unknown> };
type Definition = { id: string; name: string; description: string; organization_id: string | null;
  enabled: boolean; trigger_type: string; conditions: Condition[]; actions: Action[]; revision: number };
type Execution = { id: string; status: string; trigger_type: string; result_summary: string;
  last_error_code: string; attempt_count: number; created_at: string };
const blank = (trigger = "COMPLIANCE_CREATED"): Omit<Definition, "id" | "revision"> => ({
  name: "", description: "", organization_id: null, enabled: true, trigger_type: trigger,
  conditions: [], actions: [{ type: "SEND_NOTIFICATION", parameters: { title: "", message: "", channels: ["IN_APP"], recipient: "TENANT_ADMIN" } }],
});

export default function WorkflowBuilder({ entitled }: { entitled: boolean }) {
  const t = useTranslations("Workflow");
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [items, setItems] = useState<Definition[]>([]);
  const [draft, setDraft] = useState<Omit<Definition, "id" | "revision"> & { id?: string }>(blank());
  const [history, setHistory] = useState<Execution[]>([]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function load() {
    if (!entitled) return;
    try {
      const [meta, definitions] = await Promise.all([
        apiRequest<Metadata>("/automations/metadata"), apiRequest<Definition[]>("/automations"),
      ]); setMetadata(meta); setItems(definitions); setDraft((current) => current.id ? current : blank(meta.triggers[0]));
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("loadFailed")); }
  }
  useEffect(() => { void load(); }, [entitled]);
  if (!entitled) return <section className="card workflow-upgrade"><Settings2 size={22} /><div><h2>{t("title")}</h2><p>{t("upgrade")}</p></div></section>;
  if (!metadata) return <section className="card"><p>{error || t("loading")}</p></section>;

  function edit(item?: Definition) {
    setDraft(item ? { ...item, conditions: item.conditions.map((x) => ({ ...x })), actions: item.actions.map((x) => ({ ...x, parameters: { ...x.parameters } })) } : blank(metadata!.triggers[0]));
    setHistory([]); setError("");
  }
  async function save() {
    setBusy(true); setError("");
    try {
      await apiRequest(draft.id ? `/automations/${draft.id}` : "/automations", draft.id ? "PUT" : "POST", draft);
      await load(); edit();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("saveFailed")); }
    finally { setBusy(false); }
  }
  async function showHistory(id: string) {
    try { setHistory(await apiRequest<Execution[]>(`/automations/${id}/executions`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("loadFailed")); }
  }
  function updateCondition(index: number, patch: Partial<Condition>) {
    setDraft({ ...draft, conditions: draft.conditions.map((row, i) => i === index ? { ...row, ...patch } : row) });
  }
  function actionDefaults(type: string): Record<string, unknown> {
    if (type === "CREATE_TASK") return { title: "", due_in_days: 1, priority: "MEDIUM", assignee_user_id: metadata!.users[0]?.id || "" };
    if (type === "SEND_NOTIFICATION") return { title: "", message: "", channels: ["IN_APP"], recipient: "TENANT_ADMIN" };
    if (type === "ASSIGN_RESPONSIBLE") return { user_id: metadata!.users[0]?.id || "" };
    return { field: "priority", value: "MEDIUM" };
  }
  function updateAction(index: number, patch: Partial<Action>) {
    setDraft({ ...draft, actions: draft.actions.map((row, i) => i === index ? { ...row, ...patch } : row) });
  }
  function parameter(index: number, key: string, value: unknown) {
    updateAction(index, { parameters: { ...draft.actions[index].parameters, [key]: value } });
  }

  return <section className="workflow-builder">
    <header className="page-title"><div><span>{t("eyebrow")}</span><h2>{t("title")}</h2><p>{t("description")}</p></div>
      <button className="primary-button" type="button" onClick={() => edit()}><Plus size={15} />{t("new")}</button></header>
    {error && <p className="error-text">{error}</p>}
    <div className="workflow-layout">
      <section className="card workflow-list"><h3>{t("definitions")}</h3>{items.length === 0 && <p>{t("empty")}</p>}
        {items.map((item) => <article key={item.id}><button type="button" onClick={() => edit(item)}><strong>{item.name}</strong><small>{t(`triggers.${item.trigger_type}`)} · {item.enabled ? t("enabled") : t("disabled")}</small></button>
          <button type="button" className="icon-button" aria-label={`${t("history")} ${item.name}`} onClick={() => void showHistory(item.id)}><Clock3 size={15} /></button></article>)}</section>
      <section className="card workflow-form"><h3>{draft.id ? t("edit") : t("create")}</h3>
        <div className="workflow-grid"><label>{t("name")}<input value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label>{t("organization")}<select value={draft.organization_id || ""} onChange={(e) => setDraft({ ...draft, organization_id: e.target.value || null })}><option value="">{t("allOrganizations")}</option>{metadata.organizations.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label className="full">{t("descriptionLabel")}<textarea value={draft.description} maxLength={500} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
          <label>{t("trigger")}<select value={draft.trigger_type} onChange={(e) => setDraft({ ...draft, trigger_type: e.target.value })}>{metadata.triggers.map((value) => <option key={value} value={value}>{t(`triggers.${value}`)}</option>)}</select></label>
          <label className="check-label"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />{t("enabled")}</label></div>
        <div className="workflow-step"><header><b>2</b><strong>{t("conditions")}</strong><button type="button" onClick={() => setDraft({ ...draft, conditions: [...draft.conditions, { field: "priority", operator: "EQ", value: "HIGH" }] })}><Plus size={14} />{t("add")}</button></header>
          {draft.conditions.length === 0 && <p>{t("noConditions")}</p>}{draft.conditions.map((row, index) => <div className="workflow-row" key={index}>
            <select aria-label={t("conditionField")} value={row.field} onChange={(e) => updateCondition(index, { field: e.target.value })}>{metadata.condition_fields.map((value) => <option key={value} value={value}>{t(`fields.${value}`)}</option>)}</select>
            <select aria-label={t("operator")} value={row.operator} onChange={(e) => updateCondition(index, { operator: e.target.value })}>{["EQ", "NE", "IN", "LTE", "GTE"].map((value) => <option key={value}>{value}</option>)}</select>
            <input aria-label={t("value")} value={Array.isArray(row.value) ? row.value.join(",") : row.value} onChange={(e) => updateCondition(index, { value: row.operator === "IN" ? e.target.value.split(",").filter(Boolean) : ["LTE", "GTE"].includes(row.operator) ? Number(e.target.value) : e.target.value })} />
            <button type="button" className="icon-button" aria-label={t("remove")} onClick={() => setDraft({ ...draft, conditions: draft.conditions.filter((_, i) => i !== index) })}><Trash2 size={14} /></button></div>)}</div>
        <div className="workflow-step"><header><b>3</b><strong>{t("actions")}</strong><button type="button" onClick={() => setDraft({ ...draft, actions: [...draft.actions, { type: "SEND_NOTIFICATION", parameters: actionDefaults("SEND_NOTIFICATION") }] })}><Plus size={14} />{t("add")}</button></header>
          {draft.actions.map((row, index) => <div className="workflow-action" key={index}><div className="workflow-row"><span>{index + 1}</span><select aria-label={t("actionType")} value={row.type} onChange={(e) => updateAction(index, { type: e.target.value, parameters: actionDefaults(e.target.value) })}>{metadata.action_types.map((value) => <option key={value} value={value}>{t(`actionTypes.${value}`)}</option>)}</select>
            <button type="button" className="icon-button" aria-label={t("remove")} disabled={draft.actions.length === 1} onClick={() => setDraft({ ...draft, actions: draft.actions.filter((_, i) => i !== index) })}><Trash2 size={14} /></button></div>
            {row.type === "CREATE_TASK" && <div className="workflow-parameters"><input aria-label={t("taskTitle")} placeholder={t("taskTitle")} value={String(row.parameters.title || "")} onChange={(e) => parameter(index, "title", e.target.value)} /><input aria-label={t("dueDays")} type="number" min="0" max="365" value={Number(row.parameters.due_in_days || 0)} onChange={(e) => parameter(index, "due_in_days", Number(e.target.value))} /><select aria-label={t("responsibleUser")} value={String(row.parameters.assignee_user_id || "")} onChange={(e) => parameter(index, "assignee_user_id", e.target.value)}>{metadata.users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></div>}
            {row.type === "SEND_NOTIFICATION" && <div className="workflow-parameters"><input aria-label={t("notificationTitle")} placeholder={t("notificationTitle")} value={String(row.parameters.title || "")} onChange={(e) => parameter(index, "title", e.target.value)} /><input aria-label={t("message")} placeholder={t("message")} value={String(row.parameters.message || "")} onChange={(e) => parameter(index, "message", e.target.value)} /><select aria-label={t("channel")} value={String((row.parameters.channels as string[] || ["IN_APP"])[0])} onChange={(e) => parameter(index, "channels", [e.target.value])}><option>IN_APP</option><option>EMAIL</option><option>WHATSAPP</option></select></div>}
            {row.type === "ASSIGN_RESPONSIBLE" && <select aria-label={t("responsibleUser")} value={String(row.parameters.user_id || "")} onChange={(e) => parameter(index, "user_id", e.target.value)}>{metadata.users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>}
            {row.type === "UPDATE_FIELDS" && <div className="workflow-parameters"><select aria-label={t("field")} value={String(row.parameters.field)} onChange={(e) => updateAction(index, { parameters: { field: e.target.value, value: e.target.value === "priority" ? "MEDIUM" : "IN_PROGRESS" } })}><option value="priority">{t("fields.priority")}</option><option value="status">{t("status")}</option></select><input aria-label={t("value")} value={String(row.parameters.value)} onChange={(e) => parameter(index, "value", e.target.value)} /></div>}</div>)}</div>
        <button type="button" className="primary-button" disabled={busy || !draft.name.trim()} onClick={() => void save()}><Save size={15} />{busy ? t("saving") : t("save")}</button>
      </section>
    </div>
    {history.length > 0 && <section className="card workflow-history"><h3>{t("history")}</h3>{history.map((row) => <article key={row.id}><strong>{t(`states.${row.status}`)}</strong><span>{row.trigger_type}</span><small>{row.result_summary || row.last_error_code || new Date(row.created_at).toLocaleString()}</small></article>)}</section>}
  </section>;
}
