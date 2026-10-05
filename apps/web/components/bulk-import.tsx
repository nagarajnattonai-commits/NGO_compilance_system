"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";

type ImportType = "ORGANIZATIONS" | "REGISTRATIONS" | "INVITATIONS" | "TASK_ASSIGNMENTS";
type FieldSchema = { required: string[]; optional: string[] };
type Issue = { field: string; message: string; candidates?: Array<{ id: string; name: string }> };
type Row = { row_number: number; status: string; resolution: string; errors: Issue[]; warnings: Issue[]; created_entity_id?: string };
type Job = {
  id: string; import_type: ImportType; status: string; filename: string; headers: string[]; mapping: Record<string, string>;
  suggested_mapping?: Record<string, string>; total_rows: number; valid_rows: number; invalid_rows: number;
  warnings: number; created: number; mapped: number; skipped: number; failed: number; revision: number; rows?: Row[];
};
type Resolution = { action: "CREATE" | "MAP" | "SKIP"; organization_id?: string };

async function uploadFile(type: ImportType, file: File): Promise<Job> {
  const data = new FormData(); data.set("import_type", type); data.set("file", file);
  const response = await fetch("/api/v1/imports", { method: "POST", credentials: "same-origin", headers: { "X-Setu-Request": "1" }, body: data });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail || `Upload failed (${response.status})`);
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
    event.preventDefault(); if (!file || !schema) return;
    setBusy(true); setError("");
    try {
      const created = await uploadFile(type, file);
      setJob(created); setMapping(created.suggested_mapping || {}); setResolutions({});
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("uploadError")); }
    finally { setBusy(false); }
  }
  async function validate() {
    if (!job || !schema) return; setBusy(true); setError("");
    try {
      const checked = await apiRequest<Job>(`/imports/${job.id}/validate`, "POST", {
        expected_revision: job.revision, mapping: Object.fromEntries(Object.entries(mapping).filter(([, value]) => value)), resolutions,
      });
      setJob(checked);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("validationError")); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!job || job.status !== "READY") return; setBusy(true); setError("");
    try { setJob(await apiRequest<Job>(`/imports/${job.id}/confirm`, "POST", { expected_revision: job.revision, confirmation: "CONFIRM IMPORT" })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("importError")); }
    finally { setBusy(false); }
  }
  function resolve(row: Row, action: Resolution["action"], organizationId?: string) {
    setResolutions((current) => ({ ...current, [String(row.row_number)]: { action, ...(organizationId ? { organization_id: organizationId } : {}) } }));
  }

  const fields = schema ? [...schema.required, ...schema.optional] : [];
  const completed = job && ["COMPLETED", "COMPLETED_WITH_ERRORS"].includes(job.status);
  return <section className="card" aria-label={t("title")}>
    <div className="report-section-heading"><div><h2>{t("title")}</h2><p>{t("description")}</p></div>{job && <span className="status-pill">{t(`statuses.${job.status}`)}</span>}</div>
    <ol className="organization-records" aria-label={t("workflow")}><li>{t("steps.upload")}</li><li>{t("steps.map")}</li><li>{t("steps.validate")}</li><li>{t("steps.review")}</li><li>{t("steps.confirm")}</li><li>{t("steps.results")}</li></ol>
    {error && <div className="report-error" role="alert">{error}</div>}
    {schemaLoading && <p role="status">Loading import fields...</p>}
    {schemaError && <div className="report-error" role="alert">{schemaError}<button type="button" className="button secondary" onClick={() => setSchemaAttempt((value) => value + 1)}>Try again</button></div>}
    {!job && <form className="report-filters" onSubmit={upload}>
      <label>{t("importType")}<select value={type} onChange={(event) => { setType(event.target.value as ImportType); setFile(null); }}>
        {(["ORGANIZATIONS", "REGISTRATIONS", "INVITATIONS", "TASK_ASSIGNMENTS"] as ImportType[]).map((value) => <option value={value} key={value}>{t(`types.${value}`)}</option>)}
      </select></label>
      <label>{t("file")}<input type="file" required accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>
      <a className="button secondary" href={`/api/v1/imports/templates/${type}`}>{t("downloadTemplate")}</a>
      <button className="button primary" disabled={busy || !file || !schema}>{busy ? t("uploading") : t("upload")}</button>
    </form>}

    {job && !completed && <>
      <section><h3>{t("mapping")}</h3><p>{t("mappingHelp")}</p><div className="report-filters">{fields.map((field) => <label key={field}>{t("fieldLabel", { field })}{schema?.required.includes(field) ? " *" : ""}<select value={mapping[field] || ""} onChange={(event) => setMapping((current) => ({ ...current, [field]: event.target.value }))}><option value="">{t("unmapped")}</option>{job.headers.map((header) => <option key={header} value={header}>{header}</option>)}</select></label>)}</div></section>
      {job.rows && <section><h3>{t("review")}</h3><div className="report-metrics"><article className="report-metric"><span>{t("total")}</span><strong>{job.total_rows}</strong></article><article className="report-metric"><span>{t("valid")}</span><strong>{job.valid_rows}</strong></article><article className="report-metric"><span>{t("invalid")}</span><strong>{job.invalid_rows}</strong></article><article className="report-metric"><span>{t("warnings")}</span><strong>{job.warnings}</strong></article></div>
        <div className="report-table-scroll"><table className="report-table"><thead><tr><th>{t("row")}</th><th>{t("result")}</th><th>{t("issues")}</th><th>{t("resolution")}</th></tr></thead><tbody>{job.rows.map((row) => {
          const candidates = row.warnings.flatMap((warning) => warning.candidates || []);
          return <tr key={row.row_number}><td>{row.row_number}</td><td>{row.status}</td><td>{[...row.errors, ...row.warnings].map((issue, index) => <p key={index}>{issue.field}: {issue.message}</p>)}</td><td>{candidates.length ? <div><select aria-label={t("resolutionFor", { row: row.row_number })} value={resolutions[String(row.row_number)]?.action || ""} onChange={(event) => resolve(row, event.target.value as Resolution["action"])}><option value="">{t("chooseResolution")}</option><option value="MAP">{t("map")}</option><option value="SKIP">{t("skip")}</option><option value="CREATE">{t("create")}</option></select>{resolutions[String(row.row_number)]?.action === "MAP" && <select aria-label={t("existingOrganizationFor", { row: row.row_number })} value={resolutions[String(row.row_number)]?.organization_id || ""} onChange={(event) => resolve(row, "MAP", event.target.value)}><option value="">{t("chooseExisting")}</option>{candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select>}</div> : "—"}</td></tr>;
        })}</tbody></table></div>
      </section>}
      <div className="heading-actions"><button type="button" className="button secondary" disabled={busy || !schema} onClick={() => void validate()}>{busy ? t("working") : t("validate")}</button><button type="button" className="button primary" disabled={busy || !schema || job.status !== "READY"} onClick={() => void confirm()}>{t("confirmImport")}</button><button type="button" className="text-button" onClick={() => { setJob(null); setFile(null); setError(""); }}>{t("startOver")}</button></div>
    </>}

    {completed && <section><h3>{t("results")}</h3><div className="report-metrics">{(["created", "mapped", "skipped", "failed"] as const).map((key) => <article className="report-metric" key={key}><span>{t(key)}</span><strong>{job[key]}</strong></article>)}</div><div className="heading-actions"><a className="button secondary" href={`/api/v1/imports/${job.id}/results.csv`}>{t("downloadResults")}</a><button className="button primary" type="button" onClick={() => window.location.reload()}>{t("refreshWorkspace")}</button></div></section>}
  </section>;
}
