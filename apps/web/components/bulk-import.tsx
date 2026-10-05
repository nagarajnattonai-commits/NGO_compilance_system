"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";

type ImportType = "ORGANIZATIONS" | "REGISTRATIONS" | "INVITATIONS" | "TASK_ASSIGNMENTS";
type FieldSchema = { required: string[]; optional: string[] };
type Issue = { field: string; message: string; candidates?: Array<{ id: string; name: string }> };
type Row = { row_number: number; status: string; resolution: string; errors: Issue[]; warnings: Issue[]; created_entity_id?: string; existing_organization_id?: string|null };
type Job = {
  id: string; import_type: ImportType; status: string; filename: string; headers: string[]; mapping: Record<string, string>;
  suggested_mapping?: Record<string, string>; total_rows: number; valid_rows: number; invalid_rows: number;
  warnings: number; created: number; mapped: number; skipped: number; failed: number; revision: number; rows?: Row[];
  created_at?: string; updated_at?: string;
};
type Resolution = { action: "CREATE" | "MAP" | "SKIP"; organization_id?: string };

async function uploadFile(type: ImportType, file: File): Promise<Job> {
  const data = new FormData(); data.set("import_type", type); data.set("file", file);
  const response = await fetch("/api/v1/imports", { method: "POST", credentials: "same-origin", headers: { "X-Setu-Request": "1" }, body: data });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(response.status >= 500 ? "The server is unavailable. Please try again shortly." : typeof body.detail === "string" ? body.detail : `Upload failed (${response.status})`);
  }
  return response.json() as Promise<Job>;
}

export default function BulkImport() {
  const t = useTranslations("PortfolioImport");
  const [type, setType] = useState<ImportType>("ORGANIZATIONS");
  const [schema, setSchema] = useState<FieldSchema | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [resolutions, setResolutions] = useState<Record<string, Resolution>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [schemaError, setSchemaError] = useState("");
  const [schemaLoading, setSchemaLoading] = useState(true);
  const [schemaAttempt, setSchemaAttempt] = useState(0);
  const [reopenId, setReopenId] = useState("");
  const [dirty, setDirty] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const requestInFlight = useRef(false);

  function adopt(value:Job) {
    setJob(value);setType(value.import_type);setReopenId(value.id);
    setMapping(Object.keys(value.mapping).length ? value.mapping : value.suggested_mapping || {});
    setResolutions(Object.fromEntries((value.rows||[]).filter(row=>["CREATE","MAP","SKIP"].includes(row.resolution)).map(row=>[String(row.row_number),{action:row.resolution as Resolution["action"],...(row.existing_organization_id?{organization_id:row.existing_organization_id}:{})}])));
    setDirty(false);setUncertain(false);
  }
  async function readJob(id:string):Promise<Job> {
    // Retrieval enforces expiry; results supplies persisted mapping and row outcomes.
    await apiRequest<Job>(`/imports/${encodeURIComponent(id)}`);
    return apiRequest<Job>(`/imports/${encodeURIComponent(id)}/results`);
  }
  function begin() {
    if(requestInFlight.current) return false;
    requestInFlight.current=true;setBusy(true);return true;
  }
  function finish() {requestInFlight.current=false;setBusy(false);}
  async function refresh(id=job?.id) {
    if(!id||!begin()) return;setError("");
    try{adopt(await readJob(id));}
    catch(reason){setUncertain(true);setError(reason instanceof Error?reason.message:t("validationError"));}
    finally{finish();}
  }
  async function recover(id:string, reason:unknown, fallback:string) {
    setError(reason instanceof Error?reason.message:fallback);setUncertain(true);
    // Never retry a write automatically after an ambiguous response.
    try{adopt(await readJob(id));}catch{/* Explicit refresh remains available. */}
  }
  useEffect(()=>{
    if(!job||!["IMPORTING","VALIDATING"].includes(job.status)) return;
    const timer=window.setInterval(()=>void refresh(job.id),5000);
    return ()=>window.clearInterval(timer);
  },[job?.id,job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let active = true;
    setSchema(null); setSchemaError(""); setSchemaLoading(true);
    apiRequest<FieldSchema & { import_type: string }>(`/imports/schema/${type}`)
      .then((value) => { if (active) setSchema(value); })
      .catch((reason) => { if (active) setSchemaError(reason instanceof Error ? reason.message : t("validationError")); })
      .finally(() => { if (active) setSchemaLoading(false); });
    return () => { active = false; };
  }, [type, schemaAttempt]); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(event: React.FormEvent) {
    event.preventDefault(); if (!file || !schema || !begin()) return;
    setError("");
    try {
      const created = await uploadFile(type, file);
      adopt(created);
      try{adopt({...await readJob(created.id),suggested_mapping:created.suggested_mapping});}
      catch(reason){setUncertain(true);setError(reason instanceof Error?reason.message:t("uploadError"));}
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("uploadError")); }
    finally { finish(); }
  }
  async function validate() {
    if (!job || !schema || uncertain || !["UPLOADED","VALIDATION_FAILED","READY","FAILED"].includes(job.status) || !begin()) return; setError("");
    try {
      const checked = await apiRequest<Job>(`/imports/${job.id}/validate`, "POST", {
        expected_revision: job.revision, mapping: Object.fromEntries(Object.entries(mapping).filter(([, value]) => value)), resolutions,
      });
      adopt(checked);
    } catch (reason) { await recover(job.id,reason,t("validationError")); }
    finally { finish(); }
  }
  async function confirm() {
    if (!job || job.status !== "READY" || dirty || uncertain || !begin()) return; setError("");
    try { adopt(await apiRequest<Job>(`/imports/${job.id}/confirm`, "POST", { expected_revision: job.revision, confirmation: "CONFIRM IMPORT" })); }
    catch (reason) { await recover(job.id,reason,t("importError")); }
    finally { finish(); }
  }
  async function cancel(startOver=false) {
    if(!job||!begin()) return;setError("");
    try{
      if(!["CANCELLED","COMPLETED","COMPLETED_WITH_ERRORS"].includes(job.status)) adopt(await apiRequest<Job>(`/imports/${job.id}/cancel`,"POST"));
      if(startOver){setJob(null);setFile(null);setMapping({});setResolutions({});setDirty(false);setUncertain(false);}
    }catch(reason){await recover(job.id,reason,"The import could not be cancelled. Refresh its status before continuing.");}
    finally{finish();}
  }
  function resolve(row: Row, action: Resolution["action"], organizationId?: string) {
    setDirty(true);
    setResolutions((current) => ({ ...current, [String(row.row_number)]: { action, ...(organizationId ? { organization_id: organizationId } : {}) } }));
  }

  const fields = schema ? [...schema.required, ...schema.optional] : [];
  const completed = job && ["COMPLETED", "COMPLETED_WITH_ERRORS"].includes(job.status);
  const editable = !!job && ["UPLOADED","VALIDATION_FAILED","READY","FAILED"].includes(job.status);
  return <section className="card" aria-label={t("title")}>
    <div className="report-section-heading"><div><h2>{t("title")}</h2><p>{t("description")}</p></div>{job && <span className="status-pill">{t(`statuses.${job.status}`)}</span>}</div>
    <ol className="organization-records" aria-label={t("workflow")}><li>{t("steps.upload")}</li><li>{t("steps.map")}</li><li>{t("steps.validate")}</li><li>{t("steps.review")}</li><li>{t("steps.confirm")}</li><li>{t("steps.results")}</li></ol>
    {error && <div className="report-error" role="alert">{error}</div>}
    {uncertain && <p role="status">The backend state must be refreshed before further validation or confirmation. No import is retried automatically.</p>}
    {schemaLoading && <p role="status">Loading import fields...</p>}
    {schemaError && <div className="report-error" role="alert">{schemaError}<button type="button" className="button secondary" onClick={() => setSchemaAttempt((value) => value + 1)}>Try again</button></div>}
    {!job && <form className="report-filters" onSubmit={upload}>
      <label>{t("importType")}<select disabled={busy} value={type} onChange={(event) => { setType(event.target.value as ImportType); setFile(null); }}>
        {(["ORGANIZATIONS", "REGISTRATIONS", "INVITATIONS", "TASK_ASSIGNMENTS"] as ImportType[]).map((value) => <option value={value} key={value}>{t(`types.${value}`)}</option>)}
      </select></label>
      <label>{t("file")}<input type="file" disabled={busy} required accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>
      <a className="button secondary" href={`/api/v1/imports/templates/${type}`}>{t("downloadTemplate")}</a>
      <button className="button primary" disabled={busy || !file || !schema}>{busy ? t("uploading") : t("upload")}</button>
    </form>}
    {!job && <form className="report-filters" aria-label="Open existing import" onSubmit={event=>{event.preventDefault();void refresh(reopenId.trim());}}>
      <label>Import job ID<input value={reopenId} required maxLength={36} disabled={busy} onChange={event=>setReopenId(event.target.value)}/></label><button className="button secondary" disabled={busy||!reopenId.trim()}>Open import</button>
      <p>Use a saved job ID to reopen an import in this workspace. Unfinished jobs expire after seven days. Recent job listing is not currently available.</p>
    </form>}
    {job && <div><p>File: {job.filename} · Import job ID: <code>{job.id}</code></p><button className="button secondary" type="button" disabled={busy} onClick={()=>void refresh()}>Refresh import status</button><p>Refresh reloads the saved mapping and resolutions. Unsaved edits will be discarded.</p></div>}
    {job?.status==="CANCELLED"&&<p>This import is cancelled and cannot be resumed. Uploading the identical file can return this cancelled job until it expires.</p>}
    {job?.status==="IMPORTING"&&<p role="status">Importing. Status is refreshed automatically. Do not submit another confirmation.</p>}

    {job && <>
      {editable&&<section><h3>{t("mapping")}</h3><p>{t("mappingHelp")}</p><div className="report-filters">{fields.map((field) => <label key={field}>{t("fieldLabel", { field })}{schema?.required.includes(field) ? " *" : ""}<select disabled={busy||uncertain} value={mapping[field] || ""} onChange={(event) => {setDirty(true);setMapping((current) => ({ ...current, [field]: event.target.value }));}}><option value="">{t("unmapped")}</option>{job.headers.map((header) => <option key={header} value={header}>{header}</option>)}</select></label>)}</div></section>}
      {job.rows && <section><h3>{t("review")}</h3><div className="report-metrics"><article className="report-metric"><span>{t("total")}</span><strong>{job.total_rows}</strong></article><article className="report-metric"><span>{t("valid")}</span><strong>{job.valid_rows}</strong></article><article className="report-metric"><span>{t("invalid")}</span><strong>{job.invalid_rows}</strong></article><article className="report-metric"><span>{t("warnings")}</span><strong>{job.warnings}</strong></article></div>
        <div className="report-table-scroll"><table className="report-table"><thead><tr><th>{t("row")}</th><th>{t("result")}</th><th>{t("issues")}</th><th>{t("resolution")}</th></tr></thead><tbody>{job.rows.map((row) => {
          const candidates = row.warnings.flatMap((warning) => warning.candidates || []);
          return <tr key={row.row_number}><td>{row.row_number}</td><td>{row.status}</td><td>{[...row.errors, ...row.warnings].map((issue, index) => <p key={index}>{issue.field}: {issue.message}</p>)}</td><td>{editable&&candidates.length ? <div><select disabled={busy||uncertain} aria-label={t("resolutionFor", { row: row.row_number })} value={resolutions[String(row.row_number)]?.action || ""} onChange={(event) => resolve(row, event.target.value as Resolution["action"])}><option value="">{t("chooseResolution")}</option><option value="MAP">{t("map")}</option><option value="SKIP">{t("skip")}</option><option value="CREATE">{t("create")}</option></select>{resolutions[String(row.row_number)]?.action === "MAP" && <select disabled={busy||uncertain} aria-label={t("existingOrganizationFor", { row: row.row_number })} value={resolutions[String(row.row_number)]?.organization_id || ""} onChange={(event) => resolve(row, "MAP", event.target.value)}><option value="">{t("chooseExisting")}</option>{candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select>}</div> : row.resolution||"—"}</td></tr>;
        })}</tbody></table></div>
      </section>}
      {dirty&&editable&&<p role="status">Mapping or resolutions changed. Run dry validation again before confirming.</p>}
      <div className="heading-actions">{editable&&<><button type="button" className="button secondary" disabled={busy || !schema || uncertain} onClick={() => void validate()}>{busy ? t("working") : t("validate")}</button><button type="button" className="button primary" disabled={busy || !schema || job.status !== "READY" || dirty || uncertain} onClick={() => void confirm()}>{t("confirmImport")}</button></>}{!["IMPORTING","CANCELLED","COMPLETED","COMPLETED_WITH_ERRORS"].includes(job.status)&&<button type="button" className="button secondary" disabled={busy} onClick={()=>void cancel()}>Cancel import</button>}<button type="button" className="text-button" disabled={busy||job.status==="IMPORTING"} onClick={() => void cancel(true)}>{t("startOver")}</button></div>
    </>}

    {completed && <section><h3>{t("results")}</h3><div className="report-metrics">{(["created", "mapped", "skipped", "failed"] as const).map((key) => <article className="report-metric" key={key}><span>{t(key)}</span><strong>{job[key]}</strong></article>)}</div><div className="heading-actions"><a className="button secondary" href={`/api/v1/imports/${job.id}/results.csv`}>{t("downloadResults")}</a><button className="button primary" type="button" onClick={() => window.location.reload()}>{t("refreshWorkspace")}</button></div></section>}
  </section>;
}
