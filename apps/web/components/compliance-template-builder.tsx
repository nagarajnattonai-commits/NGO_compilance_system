"use client";
import { useCallback, useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { apiRequest, ApiError } from "@/lib/http";
import { actOnTemplate, emptyTranslation, getTemplate, newConfiguration, pruneTemplateTranslations, templatePath, type ApplicabilityPreview, type ComplianceCategory, type ComplianceTemplate, type MasterMetadata, type TemplateConfiguration, type TemplateTranslation } from "@/lib/compliance-master";
import { supportedLocales } from "@/i18n/config";
import { formatDateTime, formatShortDate } from "@/i18n/format";
import ComplianceMasterShell from "./compliance-master-shell";
import ComplianceMasterSortable from "./compliance-master-sortable";
import { frequencies, risks } from "./compliance-master";

const steps = ["basic", "applicability", "schedule", "workflow", "checklist", "documents", "responsibility", "reminders", "risk", "localization", "review"];
const deadlineStrategies = ["FIXED_DATE", "PERIOD_END_PLUS_DAYS", "EVENT_DATE_PLUS_DAYS", "CERTIFICATE_EXPIRY_MINUS_DAYS", "FINANCIAL_YEAR_END_PLUS_DAYS"];
const inputLimits: Record<string, number> = { name: 220, jurisdiction: 100, subcategory: 100, authority: 200, legal_reference: 180, portal_url: 1000 };
function itemId() { return crypto.randomUUID(); }
function replace<T>(items: T[], index: number, value: Partial<T>): T[] { return items.map((item, i) => i === index ? { ...item, ...value } : item); }
function Field({ label, value, onChange, type = "text", multiline = false, min, max, maxLength = 4000 }: { label: string; value: string | number; onChange: (value: string) => void; type?: string; multiline?: boolean; min?: number; max?: number; maxLength?: number }) {
  return <label>{label}{multiline ? <textarea aria-label={label} rows={4} maxLength={maxLength} value={value} onChange={(e) => onChange(e.target.value)} /> : <input aria-label={label} type={type} value={value} min={min} max={max} maxLength={maxLength} onChange={(e) => onChange(e.target.value)} />}</label>;
}
function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) { return <label className="master-checkbox"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />{label}</label>; }

export default function ComplianceTemplateBuilder({ id }: { id?: string }) {
  const t = useTranslations("ComplianceMaster");
  const common = useTranslations("Common");
  const locale = useLocale();
  const router = useRouter();
  const [navigating, startNavigation] = useTransition();
  const [configuration, setConfiguration] = useState<TemplateConfiguration>(newConfiguration);
  const [row, setRow] = useState<ComplianceTemplate | null>(null);
  const [code, setCode] = useState("");
  const [summary, setSummary] = useState("");
  const [categories, setCategories] = useState<ComplianceCategory[]>([]);
  const [metadata, setMetadata] = useState<MasterMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState("");
  const [notice, setNotice] = useState("");
  const [validation, setValidation] = useState<{ valid: boolean; errors: string[]; warnings: string[] } | null>(null);
  const [organizations, setOrganizations] = useState<{ id: string; name: string; tenant_id: string }[]>([]);
  const [organizationSearch, setOrganizationSearch] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [asOf, setAsOf] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [preview, setPreview] = useState<ApplicabilityPreview | null>(null);
  const [editingLocale, setEditingLocale] = useState("en-IN");
  const [showHistory, setShowHistory] = useState(false);
  const can = (action: string) => metadata?.permissions.includes("compliance_master." + action) ?? false;
  const readOnly = (row !== null && row.status !== "DRAFT") || !can(row ? "edit" : "create");
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [allCategories, meta, template] = await Promise.all([apiRequest<ComplianceCategory[]>("/admin/compliance-categories"), apiRequest<MasterMetadata>("/admin/compliance-master/metadata"), id ? getTemplate(id) : Promise.resolve(null)]);
      setCategories(allCategories); setMetadata(meta);
      if (template) { setRow(template); setConfiguration(template.configuration); setCode(template.code); setSummary(template.change_summary); }
      else { const initial = newConfiguration(); initial.category_id = allCategories.find((c) => c.enabled)?.id || ""; setConfiguration(initial); }
      setDirty(false);
    } catch { setError("failed"); } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { void refresh(); if (window.location.hash === "#review") setStep(10); if (window.location.hash === "#history") { setStep(10); setShowHistory(true); } }, [refresh]);
  useEffect(() => { const handler = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); }; window.addEventListener("beforeunload", handler); return () => window.removeEventListener("beforeunload", handler); }, [dirty]);
  function update(patch: Partial<TemplateConfiguration>) { setConfiguration((old) => pruneTemplateTranslations({ ...old, ...patch })); setDirty(true); setValidation(null); setPreview(null); setNotice(""); }
  function changeError(reason: unknown) { setError(reason instanceof ApiError && reason.status === 409 ? "conflict" : reason instanceof ApiError && reason.status === 403 ? "denied" : "actionFailed"); setDetail(reason instanceof Error ? reason.message : ""); }
  function roleSelect(label: string, value: string, onChange: (value: string) => void) { return <label>{label}<select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>{metadata?.roles.map((role) => <option key={role} value={role}>{t(`roles.${role}`)}</option>)}</select></label>; }
  async function save() {
    setBusy(true); setError(""); setDetail("");
    try {
      const saved = await apiRequest<ComplianceTemplate>(id ? `${templatePath}/${id}` : templatePath, id ? "PATCH" : "POST", { ...(id ? { expected_revision: row?.revision } : { code }), configuration, change_summary: summary || t("initialSummary") });
      setRow(saved); setConfiguration(saved.configuration); setCode(saved.code); setDirty(false); setNotice("saved");
      if (!id) startNavigation(() => router.replace(`/admin/compliance-master/${saved.id}`));
    } catch (reason) { changeError(reason); } finally { setBusy(false); }
  }
  async function action(name: string) {
    if (!row || dirty) { setError("saveFirst"); return; }
    if (name !== "validate" && !window.confirm(t("confirmAction"))) return;
    setBusy(true); setError(""); setDetail("");
    try {
      if (name === "validate") setValidation(await apiRequest(`${templatePath}/${row.id}/validate`, "POST"));
      else {
        const changeSummary = ["new-version", "request-changes"].includes(name) ? window.prompt(t("changeSummary")) : "";
        if (["new-version", "request-changes"].includes(name) && !changeSummary) return;
        const saved = await actOnTemplate(row, name, changeSummary || "");
        setRow(saved); setConfiguration(saved.configuration); setSummary(saved.change_summary); setDirty(false); setNotice("saved"); setShowHistory(false);
      }
    } catch (reason) { changeError(reason); } finally { setBusy(false); }
  }
  async function findOrganizations() {
    setBusy(true); setError("");
    try { setOrganizations(await apiRequest(`/admin/compliance-master/organizations?search=${encodeURIComponent(organizationSearch)}`)); }
    catch (reason) { changeError(reason); } finally { setBusy(false); }
  }
  async function testApplicability() {
    if (!row) { setError("saveFirst"); return; }
    setBusy(true); setError("");
    try { setPreview(await apiRequest(`${templatePath}/${row.id}/test-applicability`, "POST", { organization_id: organizationId, configuration, ...(asOf ? { as_of: asOf } : {}), ...(eventDate ? { event_date: eventDate } : {}) })); }
    catch (reason) { changeError(reason); } finally { setBusy(false); }
  }
  const translated: TemplateTranslation = { ...emptyTranslation(), ...configuration.translations[editingLocale] };
  const missingTranslation = editingLocale !== "en-IN" && (
    !translated.name || (configuration.description && !translated.description) || (configuration.instructions && !translated.instructions) ||
    configuration.checklist.some((item) => !translated.checklist[item.id] || (item.description && !translated.checklist_descriptions[item.id]) || (item.instructions && !translated.checklist_instructions[item.id])) ||
    configuration.documents.some((item) => item.instructions && !translated.document_instructions[item.id]) ||
    configuration.reminders.some((item) => item.text && !translated.reminder_text[item.id])
  );
  function translate(patch: Partial<TemplateTranslation>) { update({ translations: { ...configuration.translations, [editingLocale]: { ...translated, ...patch } } }); }
  function removeButton(onClick: () => void) { return <button type="button" className="button secondary" onClick={onClick}>{t("remove")}</button>; }
  const a = configuration.applicability;
  const workflow = configuration.workflow;
  return <ComplianceMasterShell dirty={dirty}><div className="master-heading"><div><h1>{row ? row.configuration.name || t("untitled") : t("create")}</h1><p>{code}{row && <> · v{row.version} · {t(`states.${row.status}`)}</>}</p></div><div className="master-actions">
    {!readOnly && <button className="button primary" disabled={busy || loading || navigating} onClick={() => void save()}>{t(busy || navigating ? "saving" : "saveDraft")}</button>}
    {can("version") && row && ["PUBLISHED", "ARCHIVED"].includes(row.status) && <button className="button secondary" disabled={busy} onClick={() => void action("new-version")}>{t("newVersion")}</button>}
  </div></div>
    <p className="master-policy">{t("policy")}</p>
    {notice && <p className="auth-alert" role="status">{t(notice)}</p>}
    {error && <div className="auth-alert error" role="alert"><p>{t(error)}</p>{detail && <details><summary>{t("details")}</summary><p>{detail}</p></details>}{error === "failed" && <button onClick={() => void refresh()}>{t("retry")}</button>}</div>}
    {loading || navigating ? <p role="status">{t("loading")}</p> : <div className="master-builder-layout">
      <nav className="master-step-nav" aria-label={t("steps")}>
        <label className="master-mobile-step">{t("steps")}<select aria-label={t("steps")} value={step} onChange={(e) => setStep(Number(e.target.value))}>{steps.map((key, index) => <option key={key} value={index}>{index + 1}. {t(`stepsList.${key}`)}</option>)}</select></label>
        <ol>{steps.map((key, index) => <li key={key}><button aria-current={step === index ? "step" : undefined} onClick={() => setStep(index)}><span>{index + 1}</span>{t(`stepsList.${key}`)}</button></li>)}</ol>
      </nav><section className="card master-builder-panel"><h2>{t(`stepsList.${steps[step]}`)}</h2>
        {readOnly && <p>{t("immutable")}</p>}
        <fieldset disabled={readOnly || busy}><legend className="sr-only">{t(`stepsList.${steps[step]}`)}</legend>
          {step === 0 && <div className="master-form-grid">
            <Field label={t("name")} value={configuration.name} maxLength={220} onChange={(name) => update({ name })} />
            <label>{t("code")}<input aria-label={t("code")} value={code} disabled={!!id} maxLength={40} onChange={(e) => { setCode(e.target.value.toUpperCase()); setDirty(true); }} /><small>{t("codeHelp")}</small></label>
            <label>{t("category")}<select aria-label={t("category")} value={configuration.category_id} onChange={(e) => update({ category_id: e.target.value })}><option value="">{t("select")}</option>{categories.filter((c) => c.enabled || c.id === configuration.category_id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
            {(["subcategory", "jurisdiction", "authority", "legal_reference", "portal_url"] as const).map((key) => <Field key={key} label={t(key)} value={configuration[key]} type={key === "portal_url" ? "url" : "text"} maxLength={inputLimits[key]} onChange={(value) => update({ [key]: value })} />)}
            {(["description", "purpose", "instructions", "internal_notes"] as const).map((key) => <Field key={key} label={t(key)} multiline value={configuration[key]} onChange={(value) => update({ [key]: value })} />)}
            <Field label={t("tags")} value={configuration.tags.join(", ")} onChange={(value) => update({ tags: value.split(",").map((s) => s.trim()).filter(Boolean) })} /><Field label={t("changeSummary")} maxLength={500} multiline value={summary} onChange={(value) => { setSummary(value); setDirty(true); }} />
          </div>}
          {step === 1 && <>
            <Check label={t("matchAll")} checked={a.match_all} onChange={(match_all) => update({ applicability: { ...a, match_all, groups: match_all ? [] : a.groups } })} />
            {!a.match_all && <><label>{t("combineGroups")}<select aria-label={t("combineGroups")} value={a.operator} onChange={(e) => update({ applicability: { ...a, operator: e.target.value as "AND" | "OR" } })}><option value="AND">{t("and")}</option><option value="OR">{t("or")}</option></select></label>
              <ComplianceMasterSortable disabled={readOnly} items={a.groups} onChange={(groups) => update({ applicability: { ...a, groups } })} render={(group, groupIndex) => <>
                <div className="master-form-grid"><label>{t("combineConditions")}<select aria-label={t("combineConditions")} value={group.operator} onChange={(e) => update({ applicability: { ...a, groups: replace(a.groups, groupIndex, { operator: e.target.value as "AND" | "OR" }) } })}><option value="AND">{t("and")}</option><option value="OR">{t("or")}</option></select></label>{removeButton(() => update({ applicability: { ...a, groups: a.groups.filter((_, i) => i !== groupIndex) } }))}</div>
                <ComplianceMasterSortable disabled={readOnly} items={group.conditions} onChange={(conditions) => update({ applicability: { ...a, groups: replace(a.groups, groupIndex, { conditions }) } })} render={(condition, conditionIndex) => {
                  const change = (value: Partial<typeof condition>) => update({ applicability: { ...a, groups: replace(a.groups, groupIndex, { conditions: replace(group.conditions, conditionIndex, value) }) } });
                  const datatype = metadata?.fields[condition.field] || "text";
                  return <div className="master-form-grid"><label>{t("field")}<select aria-label={t("field")} value={condition.field} onChange={(e) => change({ field: e.target.value, operator: "EQUALS", value: metadata?.fields[e.target.value] === "boolean" ? true : null })}>{Object.keys(metadata?.fields || {}).map((field) => <option value={field} key={field}>{t(`fields.${field}`)}</option>)}</select></label>
                    <label>{t("operator")}<select aria-label={t("operator")} value={condition.operator} onChange={(e) => change({ operator: e.target.value, value: e.target.value.startsWith("IS_") ? null : ["IN", "NOT_IN"].includes(e.target.value) ? [] : datatype === "boolean" ? true : null })}>{metadata?.operators[datatype]?.map((op) => <option value={op} key={op}>{t(`operators.${op}`)}</option>)}</select></label>
                    {!condition.operator.startsWith("IS_") && (datatype === "boolean" ? <label>{t("value")}<select aria-label={t("value")} value={String(condition.value)} onChange={(e) => change({ value: e.target.value === "true" })}><option value="true">{t("yes")}</option><option value="false">{t("no")}</option></select></label> : <Field label={t("value")} type={datatype === "number" ? "number" : datatype === "date" ? "date" : "text"} maxLength={200} value={Array.isArray(condition.value) ? condition.value.join(", ") : String(condition.value ?? "")} onChange={(value) => change({ value: ["IN", "NOT_IN"].includes(condition.operator) ? value.split(",").map((s) => s.trim()).filter(Boolean) : datatype === "number" ? value === "" ? null : Number(value) : value })} />)}
                    {removeButton(() => update({ applicability: { ...a, groups: replace(a.groups, groupIndex, { conditions: group.conditions.filter((_, i) => i !== conditionIndex) }) } }))}
                  </div>;
                }} />
                <button type="button" className="button secondary" onClick={() => update({ applicability: { ...a, groups: replace(a.groups, groupIndex, { conditions: [...group.conditions, { id: itemId(), field: "legal_type", operator: "EQUALS", value: "" }] }) } })}>{t("addCondition")}</button>
              </>} />
              <button type="button" className="button secondary" onClick={() => update({ applicability: { ...a, groups: [...a.groups, { id: itemId(), operator: "AND", conditions: [] }] } })}>{t("addGroup")}</button>
            </>}
          </>}
          {step === 2 && <div className="master-form-grid">
            <label>{t("frequency")}<select aria-label={t("frequency")} value={configuration.recurrence.frequency} onChange={(e) => update({ recurrence: { ...configuration.recurrence, frequency: e.target.value } })}>{frequencies.map((value) => <option key={value} value={value}>{t(`frequencies.${value}`)}</option>)}</select></label>
            <Field label={t("anchorDate")} type="date" value={configuration.recurrence.anchor_date || ""} onChange={(value) => update({ recurrence: { ...configuration.recurrence, anchor_date: value || null } })} />
            {configuration.recurrence.frequency === "CUSTOM" && <Field label={t("intervalMonths")} type="number" min={1} max={120} value={configuration.recurrence.interval_months} onChange={(value) => update({ recurrence: { ...configuration.recurrence, interval_months: Number(value) } })} />}
            <Field label={t("fiscalStartMonth")} type="number" min={1} max={12} value={configuration.recurrence.fiscal_start_month} onChange={(value) => update({ recurrence: { ...configuration.recurrence, fiscal_start_month: Number(value) } })} />
            <label>{t("deadlineStrategy")}<select aria-label={t("deadlineStrategy")} value={configuration.deadline.strategy} onChange={(e) => update({ deadline: { ...configuration.deadline, strategy: e.target.value } })}>{deadlineStrategies.map((value) => <option key={value} value={value}>{t(`deadlines.${value}`)}</option>)}</select></label>
            {configuration.deadline.strategy === "FIXED_DATE" ? <Field label={t("statutoryDeadline")} type="date" value={configuration.deadline.fixed_date || ""} onChange={(value) => update({ deadline: { ...configuration.deadline, fixed_date: value || null } })} /> : <Field label={t("offsetDays")} type="number" min={0} max={3660} value={configuration.deadline.offset_days} onChange={(value) => update({ deadline: { ...configuration.deadline, offset_days: Number(value) } })} />}
            {configuration.deadline.strategy === "CERTIFICATE_EXPIRY_MINUS_DAYS" && <Field label={t("documentType")} maxLength={80} value={configuration.deadline.document_type} onChange={(document_type) => update({ deadline: { ...configuration.deadline, document_type } })} />}
            <Field label={t("internalLead")} type="number" min={0} max={3660} value={configuration.deadline.internal_lead_days} onChange={(value) => update({ deadline: { ...configuration.deadline, internal_lead_days: Number(value) } })} />
            <p className="master-wide">{t("deadlineHelp")}</p>
          </div>}
          {step === 3 && <>
            <ComplianceMasterSortable disabled={readOnly} items={workflow.stages} onChange={(stages) => update({ workflow: { ...workflow, stages } })} render={(stage, index) => <div className="master-form-grid"><label>{t("state")}<select aria-label={t("state")} value={stage.state} onChange={(e) => update({ workflow: { ...workflow, stages: replace(workflow.stages, index, { state: e.target.value }) } })}>{metadata?.states.map((state) => <option key={state} value={state}>{state === "CANCELLED" ? t("cancelled") : common(`status.${state}`)}</option>)}</select></label><Field label={t("displayLabel")} maxLength={120} value={stage.label} onChange={(label) => update({ workflow: { ...workflow, stages: replace(workflow.stages, index, { label }) } })} />{removeButton(() => update({ workflow: { ...workflow, stages: workflow.stages.filter((_, i) => i !== index) } }))}</div>} />
            <button className="button secondary" type="button" onClick={() => update({ workflow: { ...workflow, stages: [...workflow.stages, { id: itemId(), state: "UNDER_REVIEW", label: "" }] } })}>{t("addStage")}</button><h3>{t("transitions")}</h3>
            {workflow.transitions.map((edge, index) => <div key={index} className="master-sortable-card master-form-grid">
              {(["from_state", "to_state"] as const).map((key) => <label key={key}>{t(key)}<select aria-label={t(key)} value={edge[key]} onChange={(e) => update({ workflow: { ...workflow, transitions: replace(workflow.transitions, index, { [key]: e.target.value }) } })}>{workflow.stages.map((stage) => <option value={stage.state} key={stage.id}>{stage.label || (stage.state === "CANCELLED" ? t("cancelled") : common(`status.${stage.state}`))}</option>)}</select></label>)}
              <fieldset className="master-role-options"><legend>{t("allowedRoles")}</legend>{metadata?.roles.map((role) => <Check key={role} label={t(`roles.${role}`)} checked={edge.allowed_roles.includes(role)} onChange={(selected) => update({ workflow: { ...workflow, transitions: replace(workflow.transitions, index, { allowed_roles: selected ? [...edge.allowed_roles, role] : edge.allowed_roles.filter((r) => r !== role) }) } })} />)}</fieldset>
              <Check label={t("requiredEvidence")} checked={edge.required_evidence} onChange={(required_evidence) => update({ workflow: { ...workflow, transitions: replace(workflow.transitions, index, { required_evidence }) } })} /><Check label={t("requiredApproval")} checked={edge.required_approval} onChange={(required_approval) => update({ workflow: { ...workflow, transitions: replace(workflow.transitions, index, { required_approval }) } })} />
              {removeButton(() => update({ workflow: { ...workflow, transitions: workflow.transitions.filter((_, i) => i !== index) } }))}
            </div>)}
            <button className="button secondary" type="button" onClick={() => update({ workflow: { ...workflow, transitions: [...workflow.transitions, { from_state: workflow.stages[0]?.state || "NOT_STARTED", to_state: workflow.stages.at(-1)?.state || "COMPLETED", allowed_roles: ["TENANT_ADMIN"], required_evidence: false, required_approval: false }] } })}>{t("addTransition")}</button>
          </>}
          {step === 4 && <><ComplianceMasterSortable disabled={readOnly} items={configuration.checklist} onChange={(checklist) => update({ checklist })} render={(item, index) => <div className="master-form-grid">
            <Field label={t("itemTitle")} maxLength={220} value={item.title} onChange={(title) => update({ checklist: replace(configuration.checklist, index, { title }) })} />
            {(["description", "instructions"] as const).map((key) => <Field key={key} label={t(key)} maxLength={2000} multiline value={item[key]} onChange={(value) => update({ checklist: replace(configuration.checklist, index, { [key]: value }) })} />)}
            {roleSelect(t("responsibleRole"), item.responsible_role, (responsible_role) => update({ checklist: replace(configuration.checklist, index, { responsible_role }) }))}
            <Field label={t("relativeDue")} type="number" min={-3660} max={0} value={item.relative_due_days} onChange={(value) => update({ checklist: replace(configuration.checklist, index, { relative_due_days: Number(value) }) })} /><Check label={t("required")} checked={item.required} onChange={(required) => update({ checklist: replace(configuration.checklist, index, { required }) })} />{removeButton(() => update({ checklist: configuration.checklist.filter((_, i) => i !== index) }))}
          </div>} /><button className="button secondary" type="button" onClick={() => update({ checklist: [...configuration.checklist, { id: itemId(), title: "", description: "", instructions: "", required: true, responsible_role: configuration.responsibility.owner_role, relative_due_days: 0 }] })}>{t("addItem")}</button></>}
          {step === 5 && <><p>{t("documentHelp")}</p><ComplianceMasterSortable disabled={readOnly} items={configuration.documents} onChange={(documents) => update({ documents })} render={(item, index) => <div className="master-form-grid">
            <Field label={t("documentType")} maxLength={80} value={item.document_type} onChange={(document_type) => update({ documents: replace(configuration.documents, index, { document_type }) })} /><Field label={t("minimumCount")} type="number" min={1} max={100} value={item.minimum_count} onChange={(value) => update({ documents: replace(configuration.documents, index, { minimum_count: Number(value) }) })} />
            <Field label={t("instructions")} maxLength={2000} multiline value={item.instructions} onChange={(instructions) => update({ documents: replace(configuration.documents, index, { instructions }) })} /><Check label={t("required")} checked={item.required} onChange={(required) => update({ documents: replace(configuration.documents, index, { required }) })} /><Check label={t("mustBeValid")} checked={item.must_be_valid} onChange={(must_be_valid) => update({ documents: replace(configuration.documents, index, { must_be_valid }) })} />{removeButton(() => update({ documents: configuration.documents.filter((_, i) => i !== index) }))}
          </div>} /><button className="button secondary" type="button" onClick={() => update({ documents: [...configuration.documents, { id: itemId(), document_type: "", required: true, minimum_count: 1, must_be_valid: true, instructions: "" }] })}>{t("addDocument")}</button></>}
          {step === 6 && <div className="master-form-grid">{(["owner_role", "fallback_role", "reviewer_role", "approver_role"] as const).map((key) => <div key={key}>{roleSelect(t(key), configuration.responsibility[key], (value) => update({ responsibility: { ...configuration.responsibility, [key]: value } }))}</div>)}<p className="master-wide">{t("ownerHelp")}</p></div>}
          {step === 7 && <><p>{t("reminderHelp")}</p><ComplianceMasterSortable disabled={readOnly} items={configuration.reminders} onChange={(reminders) => update({ reminders })} render={(item, index) => <div className="master-form-grid">
            <Field label={t("reminderOffset")} type="number" min={-3660} max={3660} value={item.offset_days} onChange={(value) => update({ reminders: replace(configuration.reminders, index, { offset_days: Number(value) }) })} />{roleSelect(t("recipientRole"), item.recipient_role, (recipient_role) => update({ reminders: replace(configuration.reminders, index, { recipient_role }) }))}
            <Field label={t("escalationLevel")} type="number" min={0} max={10} value={item.escalation_level} onChange={(value) => update({ reminders: replace(configuration.reminders, index, { escalation_level: Number(value) }) })} /><label>{t("channel")}<select aria-label={t("channel")} value={item.channel} onChange={() => undefined}><option value="IN_APP">{t("inApp")}</option></select></label>
            <Field label={t("reminderText")} maxLength={2000} multiline value={item.text} onChange={(text) => update({ reminders: replace(configuration.reminders, index, { text }) })} /><Check label={t("enabled")} checked={item.enabled} onChange={(enabled) => update({ reminders: replace(configuration.reminders, index, { enabled }) })} />{removeButton(() => update({ reminders: configuration.reminders.filter((_, i) => i !== index) }))}
          </div>} /><button className="button secondary" type="button" onClick={() => update({ reminders: [...configuration.reminders, { id: itemId(), offset_days: 0, channel: "IN_APP", recipient_role: configuration.responsibility.owner_role, escalation_level: 0, enabled: true, text: "" }] })}>{t("addReminder")}</button></>}
          {step === 8 && <div className="master-form-grid">{(["risk_level", "priority"] as const).map((key) => <label key={key}>{t(key === "risk_level" ? "risk" : "priority")}<select aria-label={t(key === "risk_level" ? "risk" : "priority")} value={configuration[key]} onChange={(e) => update({ [key]: e.target.value })}>{risks.map((value) => <option key={value} value={value}>{t(`risks.${value}`)}</option>)}</select></label>)}<p className="master-wide">{t("riskHelp")}</p></div>}
          {step === 9 && <><label>{t("locale")}<select aria-label={t("locale")} value={editingLocale} onChange={(e) => setEditingLocale(e.target.value)}>{supportedLocales.map((language) => <option key={language.code} value={language.code}>{language.nativeLabel}</option>)}</select></label><p>{t("translationHelp")}</p>{missingTranslation && <p role="status">{t("missingTranslation")}</p>}<div className="master-form-grid">
            {(["name", "description", "instructions"] as const).map((key) => <Field key={key} label={t(key)} maxLength={key === "name" ? 220 : 4000} multiline={key !== "name"} value={editingLocale === "en-IN" ? configuration[key] : translated[key]} onChange={(value) => editingLocale === "en-IN" ? update({ [key]: value }) : translate({ [key]: value })} />)}
            {configuration.checklist.map((item, index) => <Field key={item.id} label={`${t("itemTitle")}: ${item.title}`} maxLength={220} value={editingLocale === "en-IN" ? item.title : translated.checklist[item.id] || ""} onChange={(value) => editingLocale === "en-IN" ? update({ checklist: replace(configuration.checklist, index, { title: value }) }) : translate({ checklist: { ...translated.checklist, [item.id]: value } })} />)}
            {configuration.checklist.flatMap((item, index) => (["description", "instructions"] as const).map((key) => {
              const mapping = key === "description" ? "checklist_descriptions" : "checklist_instructions";
              return <Field key={item.id + "-" + key} label={t(key) + ": " + item.title} multiline maxLength={2000}
                value={editingLocale === "en-IN" ? item[key] : translated[mapping][item.id] || ""}
                onChange={(value) => editingLocale === "en-IN" ? update({ checklist: replace(configuration.checklist, index, { [key]: value }) }) : translate({ [mapping]: { ...translated[mapping], [item.id]: value } })} />;
            }))}
            {configuration.documents.map((item, index) => <Field key={item.id} label={`${t("instructions")}: ${item.document_type}`} multiline maxLength={2000} value={editingLocale === "en-IN" ? item.instructions : translated.document_instructions[item.id] || ""} onChange={(value) => editingLocale === "en-IN" ? update({ documents: replace(configuration.documents, index, { instructions: value }) }) : translate({ document_instructions: { ...translated.document_instructions, [item.id]: value } })} />)}
            {configuration.reminders.map((item, index) => <Field key={item.id} label={`${t("reminderText")}: ${index + 1}`} multiline maxLength={2000} value={editingLocale === "en-IN" ? item.text : translated.reminder_text[item.id] || ""} onChange={(value) => editingLocale === "en-IN" ? update({ reminders: replace(configuration.reminders, index, { text: value }) }) : translate({ reminder_text: { ...translated.reminder_text, [item.id]: value } })} />)}
          </div></>}
          {step === 10 && <div id="review"><dl className="master-summary">{["name", "jurisdiction", "legal_reference", "authority", "description"].map((key) => <div key={key}><dt>{t(key)}</dt><dd>{configuration[key as "name"] || "—"}</dd></div>)}<div><dt>{t("frequency")}</dt><dd>{t(`frequencies.${configuration.recurrence.frequency}`)}</dd></div><div><dt>{t("deadlineStrategy")}</dt><dd>{t(`deadlines.${configuration.deadline.strategy}`)} {configuration.deadline.fixed_date && formatShortDate(configuration.deadline.fixed_date, { locale })}</dd></div><div><dt>{t("internalLead")}</dt><dd>{configuration.deadline.internal_lead_days}</dd></div><div><dt>{t("workflow")}</dt><dd>{workflow.stages.map((stage) => stage.label || (stage.state === "CANCELLED" ? t("cancelled") : common(`status.${stage.state}`))).join(" → ")}</dd></div><div><dt>{t("risk")}</dt><dd>{t(`risks.${configuration.risk_level}`)}</dd></div></dl>
            {(["applicability", "checklist", "documents", "responsibility", "reminders", "translations"] as const).map((key) => <details key={key}><summary>{t(key)}</summary><pre className="master-json">{JSON.stringify(configuration[key], null, 2)}</pre></details>)}
          </div>}
        </fieldset>
        {[1, 2, 10].includes(step) && <section className="master-preview"><h3>{t("testApplicability")}</h3><div className="master-form-grid"><Field label={t("organizationSearch")} value={organizationSearch} onChange={setOrganizationSearch} /><button type="button" className="button secondary" disabled={busy} onClick={() => void findOrganizations()}>{t("search")}</button><label>{t("sampleOrganization")}<select aria-label={t("sampleOrganization")} value={organizationId} onChange={(e) => setOrganizationId(e.target.value)}><option value="">{t("select")}</option>{organizations.map((organization) => <option key={organization.id} value={organization.id}>{organization.name} · {organization.tenant_id}</option>)}</select></label><Field label={t("asOf")} type="date" value={asOf} onChange={setAsOf} /><Field label={t("eventDate")} type="date" value={eventDate} onChange={setEventDate} /></div><button type="button" className="button secondary" disabled={busy || !organizationId} onClick={() => void testApplicability()}>{t("testApplicability")}</button>
          {preview && <div role="status"><strong>{t(preview.requires_review ? "requiresReview" : preview.applicable ? "applicable" : "notApplicable")}</strong>{preview.groups.flatMap((group) => group.conditions.map((condition) => <p key={`${group.id}:${condition.id}`}>{condition.satisfied === null ? "?" : condition.satisfied ? "✓" : "✕"} {t(`fields.${condition.field}`)} · {t(`operators.${condition.operator}`)} · {String(condition.actual)} / {String(condition.expected)}</p>))}{preview.schedule && <dl><dt>{t("statutoryDeadline")}</dt><dd>{formatShortDate(preview.schedule.statutory_deadline, { locale })}</dd><dt>{t("internalTarget")}</dt><dd>{formatShortDate(preview.schedule.internal_target, { locale })}</dd></dl>}{preview.requires_review && <p>{t("requiresReview")}: {preview.requires_review}</p>}</div>}
        </section>}
        {step === 10 && <>
          <div className="master-actions"><button className="button secondary" disabled={busy || !row || dirty} onClick={() => void action("validate")}>{t("validate")}</button>
            {can("edit") && row?.status === "DRAFT" && <button className="button primary" disabled={busy || dirty} onClick={() => void action("submit-review")}>{t("submit")}</button>}
            {can("review") && row?.status === "UNDER_REVIEW" && <button className="button primary" disabled={busy} onClick={() => void action("approve")}>{t("approve")}</button>}
            {can("review") && row && ["UNDER_REVIEW", "APPROVED"].includes(row.status) && <button className="button secondary" disabled={busy} onClick={() => void action("request-changes")}>{t("requestChanges")}</button>}
            {can("publish") && row?.status === "APPROVED" && <button className="button primary" disabled={busy} onClick={() => void action("publish")}>{t("publish")}</button>}
            {can("archive") && row && row.status !== "ARCHIVED" && <button className="button secondary" disabled={busy || dirty} onClick={() => void action("archive")}>{t("archive")}</button>}
          </div>
          {validation && <div role={validation.valid ? "status" : "alert"}><h3>{t(validation.valid ? "valid" : "invalid")}</h3><ul>{validation.errors.map((message) => <li key={message}>{message}</li>)}</ul><p>{t("translationHelp")}</p><p>{t("policy")}</p></div>}
          {row && <section id="history"><button className="button secondary" onClick={() => setShowHistory(!showHistory)}>{t("history")}</button>{showHistory && <VersionHistory id={row.id} />}</section>}
        </>}
        <footer className="master-builder-footer"><button className="button secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>{t("previous")}</button><span>{step + 1} / {steps.length}</span><button className="button secondary" disabled={step === steps.length - 1} onClick={() => setStep(step + 1)}>{t("next")}</button></footer>
      </section>
    </div>}
  </ComplianceMasterShell>;
}

function VersionHistory({ id }: { id: string }) {
  const t = useTranslations("ComplianceMaster"); const locale = useLocale();
  const [versions, setVersions] = useState<ComplianceTemplate[]>([]); const [error, setError] = useState(false);
  const [events, setEvents] = useState<{ id: string; actor_name: string; action: string; summary: string; created_at: string }[]>([]);
  const [before, setBefore] = useState(1); const [after, setAfter] = useState(1); const [comparison, setComparison] = useState<unknown>(null);
  useEffect(() => { apiRequest<ComplianceTemplate[]>(`${templatePath}/${id}/versions`).then((items) => { setVersions(items); setBefore(items.at(-1)?.version || 1); setAfter(items[0]?.version || 1); }).catch(() => setError(true)); }, [id]);
  useEffect(() => { apiRequest<typeof events>(`${templatePath}/${id}/audit`).then(setEvents).catch(() => setError(true)); }, [id]);
  return <div className="master-history">{error && <p role="alert">{t("failed")}</p>}{versions.map((version) => <details key={version.version}><summary>v{version.version} · {t(`states.${version.status}`)} · {formatDateTime(version.created_at, { locale })}</summary><p>{version.change_summary}</p><p>{version.created_by} · {version.published_by}</p><HistoricalConfiguration id={id} version={version.version} /></details>)}<div className="master-form-grid">{[["before", before, setBefore], ["after", after, setAfter]].map(([label, value, setter]) => <label key={String(label)}>{t(String(label))}<select aria-label={t(String(label))} value={Number(value)} onChange={(e) => (setter as (value: number) => void)(Number(e.target.value))}>{versions.map((item) => <option key={item.version} value={item.version}>v{item.version}</option>)}</select></label>)}<button className="button secondary" onClick={() => { apiRequest(`${templatePath}/${id}/compare?before=${before}&after=${after}`).then(setComparison).catch(() => setError(true)); }}>{t("compare")}</button></div>{comparison !== null && <pre className="master-json">{JSON.stringify(comparison, null, 2)}</pre>}<h3>{t("audit")}</h3>{events.map((event) => <p key={event.id}>{event.action} · {event.actor_name} · {formatDateTime(event.created_at, { locale })}<small>{event.summary}</small></p>)}</div>;
}
function HistoricalConfiguration({ id, version }: { id: string; version: number }) {
  const t = useTranslations("ComplianceMaster"); const [configuration, setConfiguration] = useState<unknown>(null); const [error, setError] = useState(false);
  return <div><button className="button secondary" onClick={() => { getTemplate(id, version).then((row) => setConfiguration(row.configuration)).catch(() => setError(true)); }}>{t("view")}</button>{error && <p role="alert">{t("failed")}</p>}{configuration !== null && <pre className="master-json">{JSON.stringify(configuration, null, 2)}</pre>}</div>;
}
