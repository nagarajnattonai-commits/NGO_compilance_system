"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import LocaleSwitcher from "./locale-switcher";
import ThemeToggle from "./theme-toggle";
import { apiRequest } from "@/lib/http";
import "./integration-management.css";

type Job = {
  id: string;
  tenant_id: string;
  tenant_name: string;
  job_type: string;
  entity_type: string;
  entity_id: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  scheduled_for: string;
  completed_at: string | null;
  next_attempt_at: string | null;
  last_error_code: string;
  duration_ms: number;
  correlation_id: string;
};
type Metrics = {
  processed: number;
  succeeded: number;
  failed: number;
  retried: number;
  dead_letter: number;
  pending: number;
  average_duration_ms: number;
  oldest_queue_age_seconds: number;
};

export default function AutomationOperations() {
  const t = useTranslations("Automation");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [status, setStatus] = useState("");
  const [jobType, setJobType] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const query = new URLSearchParams({ page: String(page), page_size: "25" });
      if (status) query.set("status", status);
      if (jobType) query.set("job_type", jobType);
      const [result, summary] = await Promise.all([
        apiRequest<{ items: Job[]; total: number }>(`/admin/automation/jobs?${query}`),
        apiRequest<Metrics>("/admin/automation/metrics"),
      ]);
      setJobs(result.items);
      setTotal(result.total);
      setMetrics(summary);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : t("loadFailed"));
    } finally {
      setBusy(false);
    }
  }, [jobType, page, status, t]);

  useEffect(() => { void load(); }, [load]);
  const types = [...new Set(jobs.map((job) => job.job_type))].sort();
  const format = (value: string | null) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : t("none");

  return <main className="account-page integration-page">
    <header className="account-header">
      <Link className="account-brand" href="/admin">{t("platform")}</Link>
      <LocaleSwitcher compact />
      <ThemeToggle variant="icon" />
    </header>
    <div className="account-content">
      <nav className="master-breadcrumb" aria-label={t("navigation")}><Link href="/admin">{t("platform")}</Link><span aria-hidden="true">/</span><span>{t("title")}</span></nav>
      <h1>{t("title")}</h1><p>{t("description")}</p>
      {error && <div role="alert" className="auth-alert error">{error}<button className="text-button" onClick={() => void load()}>{t("retry")}</button></div>}
      {metrics && <section className="integration-grid" aria-label={t("metrics")}>
        {(["processed", "succeeded", "failed", "retried", "dead_letter", "pending"] as const).map((key) => <article className="integration-card" key={key}><h2>{t(`metric.${key}`)}</h2><p>{metrics[key]}</p></article>)}
        <article className="integration-card"><h2>{t("metric.averageDuration")}</h2><p>{metrics.average_duration_ms} ms</p></article>
        <article className="integration-card"><h2>{t("metric.queueAge")}</h2><p>{metrics.oldest_queue_age_seconds} s</p></article>
      </section>}
      <div className="integration-toolbar">
        <label>{t("status")}<select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">{t("all")}</option>{["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "RETRY", "DEAD_LETTER", "CANCELLED"].map((value) => <option key={value} value={value}>{t(`state.${value}`)}</option>)}</select></label>
        <label>{t("jobType")}<select value={jobType} onChange={(event) => { setJobType(event.target.value); setPage(1); }}><option value="">{t("all")}</option>{types.map((value) => <option key={value}>{value}</option>)}</select></label>
        <button className="button secondary" disabled={busy} onClick={() => void load()}>{t("refresh")}</button>
      </div>
      <div className="integration-table"><table><thead><tr>{["jobType", "status", "tenant", "entity", "scheduled", "attempts", "lastError", "duration", "nextRetry", "actions"].map((key) => <th key={key}>{t(key)}</th>)}</tr></thead><tbody>
        {jobs.map((job) => <tr key={job.id}><td>{job.job_type}<small><br />{job.correlation_id}</small></td><td>{t(`state.${job.status}`)}</td><td>{job.tenant_name || job.tenant_id}</td><td>{job.entity_type}<br /><small>{job.entity_id || t("none")}</small></td><td>{format(job.scheduled_for)}</td><td>{job.attempt_count}/{job.max_attempts}</td><td>{job.last_error_code || t("none")}</td><td>{job.duration_ms} ms</td><td>{format(job.next_attempt_at)}</td><td>{["FAILED", "DEAD_LETTER", "CANCELLED"].includes(job.status) && <button className="button secondary" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { await apiRequest(`/admin/automation/jobs/${job.id}/retry`, "POST"); await load(); } catch (problem) { setError(problem instanceof Error ? problem.message : t("retryFailed")); setBusy(false); } }}>{t("retry")}</button>}</td></tr>)}
      </tbody></table></div>
      {!jobs.length && !busy && <p>{t("empty")}</p>}
      <div className="integration-actions"><button className="button secondary" disabled={page <= 1 || busy} onClick={() => setPage((value) => value - 1)}>{t("previous")}</button><span>{page}</span><button className="button secondary" disabled={page * 25 >= total || busy} onClick={() => setPage((value) => value + 1)}>{t("next")}</button></div>
    </div>
  </main>;
}
