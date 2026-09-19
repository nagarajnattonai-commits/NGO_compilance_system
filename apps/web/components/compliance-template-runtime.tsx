"use client";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import type { Compliance, ComplianceDocument } from "@/lib/types";
import type { TemplateConfiguration, WorkflowTransition } from "@/lib/compliance-master";

type Snapshot = { version: number; configuration: TemplateConfiguration; owner_required: boolean;
  available_transitions: WorkflowTransition[]; documents: { id: string; document_type: string; minimum_count: number; required: boolean; document_ids: string[] }[] };
export default function ComplianceTemplateRuntime({ item, updated }: { item: Compliance; updated: (item: Compliance) => void }) {
  const locale = useLocale(); const t = useTranslations("ComplianceMaster"); const common = useTranslations("Common");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null); const [documents, setDocuments] = useState<ComplianceDocument[]>([]);
  const [proof, setProof] = useState(""); const [reference, setReference] = useState(""); const [reason, setReason] = useState("");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; Promise.all([apiRequest<Snapshot>(`/compliances/${item.id}/template-snapshot`), apiRequest<ComplianceDocument[]>(`/documents?organization_id=${item.organization_id}`)])
    .then(([config, docs]) => { if (active) { setSnapshot(config); setDocuments(docs.filter(d=>d.storage_status==="AVAILABLE"&&!!d.current_version_id)); setError(""); } }).catch(() => { if (active) setError(t("actionFailed")); }); return () => { active = false; }; }, [item.id, item.status, item.organization_id]);
  async function transition(edge: WorkflowTransition) {
    setBusy(true); setError("");
    try { const result = await apiRequest<Compliance>(`/compliances/${item.id}/transitions`, "POST", { target_status: edge.to_state, ...(proof ? { proof_document_id: proof } : {}), ...(reference ? { submission_reference: reference } : {}), ...(reason ? { reason } : {}) }); updated(result); }
    catch (e) { setError(e instanceof Error ? e.message : t("actionFailed")); } finally { setBusy(false); }
  }
  const translation = snapshot?.configuration.translations[locale];
  return <section className="detail-section template-runtime"><h3>{t("publishedVersion", { version: snapshot?.version || 1 })}</h3>{error && <p className="auth-alert error" role="alert">{error}</p>}
    {snapshot && <><h3>{translation?.name || snapshot.configuration.name}</h3><p>{translation?.description || snapshot.configuration.description}</p><p>{translation?.instructions || snapshot.configuration.instructions}</p>
      {snapshot.owner_required && <p>{t("ownerRequired")}</p>}
      <ul>{snapshot.configuration.checklist.map((item) => <li key={item.id}>{translation?.checklist[item.id] || item.title}
        <p>{translation?.checklist_descriptions?.[item.id] || item.description}</p>
        <p>{translation?.checklist_instructions?.[item.id] || item.instructions}</p>
      </li>)}</ul>
      <h4>{t("documents")}</h4>{snapshot.documents.map((requirement) => <p key={requirement.id}>{requirement.document_ids.length >= requirement.minimum_count ? "✓" : "✕"} {requirement.document_type}: {requirement.document_ids.length} / {requirement.minimum_count} {requirement.required && t("required")}<small>{translation?.document_instructions[requirement.id] || snapshot.configuration.documents.find((d) => d.id === requirement.id)?.instructions}</small></p>)}
      {snapshot.available_transitions.length > 0 && <div className="form"><label>{t("existingEvidence")}<select value={proof} onChange={(e) => setProof(e.target.value)}><option value="">{t("select")}</option>{documents.map((document) => <option value={document.id} key={document.id}>{document.name}</option>)}</select></label>
        <label>{t("filingReference")}<input maxLength={160} value={reference} onChange={(e) => setReference(e.target.value)} /></label><label>{t("reason")}<textarea maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <div className="heading-actions">{snapshot.available_transitions.map((edge) => <button key={`${edge.from_state}:${edge.to_state}`} className="button primary" disabled={busy || (edge.required_evidence && !proof)} onClick={() => void transition(edge)}>{edge.to_state === "CANCELLED" ? t("cancelled") : common(`status.${edge.to_state}`)}</button>)}</div>
      </div>}
    </>}
  </section>;
}
