"use client";

import { localizedError } from "@/i18n/display";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Download, FileText } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import SavedRegisterViews, { requireCompatibleFilters } from "./saved-register-views";
import type { Organization } from "@/lib/types";
import { activeLocale, formatPercentage, formatShortDate } from "@/i18n/format";

const priorities = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;
const horizons = [7, 30, 60, 90] as const;

type ChartPoint = { status?: string; month?: string; count: number; value?: string };
type OrganizationSummary = {
  organization_id: string;
  organization_name: string;
  total_applicable: number;
  completed: number;
  pending: number;
  overdue: number;
  upcoming: number;
  completion_percentage: number;
  task_total: number;
  task_completed: number;
  task_completion_percentage: number;
  documents_expiring: number;
};
type Analytics = {
  summary: {
    total: number; completed: number; in_progress: number; overdue: number;
    upcoming: number; requires_review: number; not_applicable: number; cancelled: number;
    tasks_due: number; overdue_tasks: number; documents_expiring: number;
    filing_completion_percentage: number; high_risk: number; open: number; completion_rate: number;
  };
  upcoming_deadlines: Array<{
    compliance_id: string; organization_id: string; organization_name: string;
    code: string; compliance: string; owner: string; due_date: string;
    days_remaining: number; status: string; priority: string;
  }>;
  organization_summaries: OrganizationSummary[];
  charts: {
    status_distribution: ChartPoint[];
    monthly_deadline_trend: ChartPoint[];
    completion_trend: ChartPoint[];
    overdue_trend: ChartPoint[];
    task_status_distribution: ChartPoint[];
    organization_comparison: OrganizationSummary[];
  };
  filters: { organizations: Array<{ id: string; name: string }>; categories: string[]; owners: string[]; statuses: string[] };
};
type FilterValues = {
  organization_id: string;
  category: string;
  status: string;
  owner: string;
  priority: string;
  date_from: string;
  date_to: string;
};
type ReportRow = {
  organization_id: string; organization_name: string; compliance_id: string;
  code: string; title: string; category: string; period: string; priority: string;
  owner: string; deadline: string; internal_target: string | null; status: string;
  applicability: string;
  tasks: Array<{ id: string; title: string; due_date: string; status: string; priority: string; owner: string }>;
  checklist: Array<{ task_id: string; title: string; required: boolean; status: string; due_date: string | null }>;
  evidence: Array<{ name: string; category: string; version: number; uploaded_at: string; expiry_at: string | null; source: string }>;
  evidence_coverage: { available_count: number; requirements: Array<{ document_type: string; required: boolean; minimum_count: number; covered_count: number; satisfied: boolean }> };
  reviews: Array<{ revision: number; decision: string; submitted_by: string; submitted_at: string; reviewed_by: string | null; reviewed_at: string | null }>;
  approvals: Array<{ revision: number; decision: string; target_status: string; requested_by: string; requested_at: string; approved_by: string | null; decided_at: string | null }>;
  filing: { reference: string; proof_type: string; channel: string; filed_at: string | null; filed_by: string; proof_name: string | null; proof_version: number | null } | null;
  completion: { status: string; progress: number; completed: boolean };
  audit_timeline: Array<{ action: string; actor: string; summary: string; occurred_at: string }>;
};

function queryString(filters: FilterValues, horizon?: number) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  if (horizon) params.set("horizon_days", String(horizon));
  return params.toString();
}

function statusLabel(status: string, translate: (key: string) => string) {
  try {
    return translate(status);
  } catch {
    return status.replaceAll("_", " ").toLowerCase();
  }
}

function ChartPanel({ title, points }: { title: string; points: ChartPoint[] }) {
  const t = useTranslations("Reports");
  const tStatus = useTranslations("Common.status");
  const max = Math.max(1, ...points.map((point) => point.count));
  return (
    <section className="card report-chart-panel">
      <h3>{title}</h3>
      {points.length ? (
        <div className="report-bars">
          {points.map((point, index) => {
            const key = point.status || point.month || "";
            const label = point.status ? statusLabel(point.status, tStatus) : key;
            return (
              <div className="report-bar-row" key={`${key}-${index}`} title={`${label}: ${point.count}`}>
                <span>{label}</span>
                <div className="report-bar-track"><i style={{ width: `${(point.count / max) * 100}%` }} /></div>
                <strong>{point.value || point.count}</strong>
              </div>
            );
          })}
        </div>
      ) : <p className="muted">{t("empty")}</p>}
    </section>
  );
}

export function ManagementDashboard({
  organizationId,
  onSelectCompliance,
}: {
  organizationId?: string;
  onSelectCompliance: (id: string) => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Reports");
  const tStatus = useTranslations("Common.status");
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState("");
  const [horizon, setHorizon] = useState<(typeof horizons)[number]>(30);

  useEffect(() => {
    let current = true;
    const params = new URLSearchParams({ horizon_days: String(horizon) });
    if (organizationId) params.set("organization_id", organizationId);
    apiRequest<Analytics>(`/reports/analytics?${params}`).then((result) => {
      if (current) { setData(result); setError(""); }
    }).catch((reason) => {
      if (current) setError(localizedError(reason, uiText, t("loadError")));
    });
    return () => { current = false; };
  }, [organizationId, horizon, t]);

  if (error) return <div className="report-error" role="alert">{error}</div>;
  if (!data) return <div className="report-loading" aria-busy="true">{t("loading")}</div>;
  const summary = data.summary;
  const metrics: Array<[string, number | string]> = [
    ["totalCompliances", summary.total], ["completed", summary.completed],
    ["inProgress", summary.in_progress], ["overdue", summary.overdue],
    ["upcoming", summary.upcoming], ["requiresReview", summary.requires_review],
    ["notApplicable", summary.not_applicable], ["cancelled", summary.cancelled],
    ["tasksDue", summary.tasks_due], ["overdueTasks", summary.overdue_tasks],
    ["documentsExpiring", summary.documents_expiring],
    ["filingCompletion", formatPercentage(summary.filing_completion_percentage / 100)],
  ];

  return (
    <section className="management-dashboard" aria-label={t("managementDashboard")}>
      <div className="report-metrics">
        {metrics.map(([key, value]) => (
          <article className="report-metric" key={key}>
            <span>{t(`metrics.${key}`)}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </div>
      <section className="card report-deadline-panel">
        <div className="report-section-heading">
          <div><h2>{t("upcomingDeadlines")}</h2><p>{t("deadlineWindow")}</p></div>
          <div className="segmented-control" role="group" aria-label={t("deadlineWindow")}>
            {horizons.map((days) => (
              <button type="button" key={days} aria-pressed={horizon === days} onClick={() => setHorizon(days)}>
                {t("days", { count: days })}
              </button>
            ))}
          </div>
        </div>
        {data.upcoming_deadlines.length ? (
          <div className="report-table-scroll"><table className="report-table">
            <thead><tr><th>{t("compliance")}</th><th>{t("organization")}</th><th>{t("owner")}</th><th>{t("deadline")}</th><th>{t("daysRemaining")}</th><th>{t("status")}</th><th>{t("priority")}</th></tr></thead>
            <tbody>{data.upcoming_deadlines.map((item) => (
              <tr key={item.compliance_id}>
                <td><button className="report-record-link" type="button" onClick={() => onSelectCompliance(item.compliance_id)}>{item.code} · {item.compliance}</button></td>
                <td><Link href={`/organizations/${item.organization_id}`}>{item.organization_name}</Link></td>
                <td>{item.owner}</td><td>{formatShortDate(item.due_date)}</td>
                <td>{item.days_remaining}</td><td>{statusLabel(item.status, tStatus)}</td><td>{item.priority}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <p className="muted">{t("empty")}</p>}
      </section>
      <div className="report-chart-grid">
        <ChartPanel title={t("statusBreakdown")} points={data.charts.status_distribution} />
        <ChartPanel title={t("monthlyDeadlineTrend")} points={data.charts.monthly_deadline_trend} />
        <ChartPanel title={t("completionTrend")} points={data.charts.completion_trend} />
        <ChartPanel title={t("overdueTrend")} points={data.charts.overdue_trend} />
        <ChartPanel title={t("taskStatusDistribution")} points={data.charts.task_status_distribution} />
        {data.organization_summaries.length > 1 && (
          <section className="card report-chart-panel">
            <h3>{t("organizationComparison")}</h3>
            <div className="report-bars">{data.charts.organization_comparison.map((item) => (
              <div className="report-bar-row" key={item.organization_id}>
                <Link href={`/organizations/${item.organization_id}`}>{item.organization_name}</Link>
                <div className="report-bar-track"><i style={{ width: `${item.completion_percentage}%` }} /></div>
                <strong>{formatPercentage(item.completion_percentage / 100)}</strong>
              </div>
            ))}</div>
          </section>
        )}
      </div>
      <section className="card report-organization-panel">
        <h2>{t("organizationPerformance")}</h2>
        <div className="report-table-scroll"><table className="report-table">
          <thead><tr><th>{t("organization")}</th><th>{t("totalApplicable")}</th><th>{t("metrics.completed")}</th><th>{t("pending")}</th><th>{t("metrics.overdue")}</th><th>{t("metrics.upcoming")}</th><th>{t("completionRate")}</th><th>{t("taskCompletion")}</th><th>{t("metrics.documentsExpiring")}</th></tr></thead>
          <tbody>{data.organization_summaries.map((item) => (
            <tr key={item.organization_id}>
              <td><Link href={`/organizations/${item.organization_id}`}>{item.organization_name}</Link></td>
              <td>{item.total_applicable}</td><td>{item.completed}</td><td>{item.pending}</td><td>{item.overdue}</td><td>{item.upcoming}</td>
              <td>{formatPercentage(item.completion_percentage / 100)}</td>
              <td>{item.task_completed}/{item.task_total} · {formatPercentage(item.task_completion_percentage / 100)}</td>
              <td>{item.documents_expiring}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
    </section>
  );
}

export function ManagementReports({
  organizations,
  initialOrganizationId,
  onSelectCompliance,
  advancedReporting = false,
}: {
  organizations: Organization[];
  initialOrganizationId?: string;
  onSelectCompliance: (id: string) => void;
  advancedReporting?: boolean;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Reports");
  const tSubscriptions = useTranslations("Subscriptions");
  const tStatus = useTranslations("Common.status");
  const [filters, setFilters] = useState<FilterValues>({
    organization_id: initialOrganizationId || "", category: "", status: "", owner: "",
    priority: "", date_from: "", date_to: "",
  });
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const pageSize = 50;

  useEffect(() => {
    let current = true;
    const query = new URLSearchParams(queryString(filters));
    query.set("limit", String(pageSize));
    query.set("offset", String(page * pageSize));
    const suffix = `?${query.toString()}`;
    setLoading(true);
    Promise.all([
      apiRequest<Analytics>(`/reports/analytics${suffix}`),
      apiRequest<{ rows: ReportRow[]; total: number }>(`/reports/compliance${suffix}`),
    ]).then(([summary, report]) => {
      if (current) { setAnalytics(summary); setRows(report.rows); setTotalRows(report.total); setError(""); }
    }).catch((reason) => {
      if (current) setError(localizedError(reason, uiText, t("loadError")));
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [filters, page, t]);

  function updateFilter(key: keyof FilterValues, value: string) {
    setPage(0);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  const query = queryString(filters);
  const printQuery = new URLSearchParams(query);
  printQuery.set("locale", activeLocale());
  const csvUrl = `/api/v1/reports/compliance.csv${query ? `?${query}` : ""}`;
  const printUrl = `/api/v1/reports/compliance/print?${printQuery.toString()}`;

  return (
    <div className="page management-reports">
      <div className="page-heading"><div><h1>{t("title")}</h1><p>{t("description")}</p></div>
        <div className="report-export-actions">
          {advancedReporting ? <>
            <a className="button secondary" href={printUrl} target="_blank" rel="noopener noreferrer"><FileText size={16} />{t("printPdf")}</a>
            <a className="button primary" href={csvUrl} download><Download size={16} />{t("exportCsv")}</a>
          </> : <span className="subscription-upgrade-required"><FileText size={16} />{tSubscriptions("upgradeRequired")}</span>}
        </div>
      </div>
      <SavedRegisterViews scope="REPORTS" filters={{organization_id:filters.organization_id||null,status:filters.status||null,
        owner:filters.owner||null,priority:filters.priority||null,date_from:filters.date_from||null,date_to:filters.date_to||null}}
        unavailable={filters.category?uiText("Common.interface.categoryIsNotSupportedByTheSavedViewContractClearItBeforeSavingThisReportView"):""}
        apply={saved=>{
          requireCompatibleFilters(saved,["organization_id","status","owner","priority","date_from","date_to"], filter => uiText("Common.interface.unsupportedFilter", { filter }));
          if(saved.organization_id&&!organizations.some(org=>org.id===saved.organization_id)) throw new Error(uiText("Common.interface.savedOrganizationIsNoLongerAccessible"));
          setPage(0);setFilters({organization_id:saved.organization_id||"",category:"",status:saved.status||"",owner:saved.owner||"",priority:saved.priority||"",date_from:saved.date_from||"",date_to:saved.date_to||""});
        }}/>
      <section className="report-filters" aria-label={t("filters")}>
        <label>{t("organization")}<select value={filters.organization_id} onChange={(event) => updateFilter("organization_id", event.target.value)}>
          <option value="">{t("allOrganizations")}</option>{organizations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label>{t("category")}<select value={filters.category} onChange={(event) => updateFilter("category", event.target.value)}>
          <option value="">{t("allCategories")}</option>{analytics?.filters.categories.map((item) => <option key={item} value={item}>{item}</option>)}
        </select></label>
        <label>{t("status")}<select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
          <option value="">{t("allStatuses")}</option>{analytics?.filters.statuses.map((item) => <option key={item} value={item}>{statusLabel(item, tStatus)}</option>)}
        </select></label>
        <label>{t("owner")}<select value={filters.owner} onChange={(event) => updateFilter("owner", event.target.value)}>
          <option value="">{t("allOwners")}</option>{analytics?.filters.owners.map((item) => <option key={item} value={item}>{item}</option>)}
        </select></label>
        <label>{t("priority")}<select value={filters.priority} onChange={(event) => updateFilter("priority", event.target.value)}>
          <option value="">{t("allPriorities")}</option>{priorities.map((item) => <option key={item} value={item}>{uiText(`Common.priority.${item}`)}</option>)}
        </select></label>
        <label>{t("dateFrom")}<input type="date" value={filters.date_from} onChange={(event) => updateFilter("date_from", event.target.value)} /></label>
        <label>{t("dateTo")}<input type="date" value={filters.date_to} onChange={(event) => updateFilter("date_to", event.target.value)} /></label>
      </section>
      {error && <div className="report-error" role="alert">{error}</div>}
      {loading && <div className="report-loading" aria-busy="true">{t("loading")}</div>}
      {analytics && <>
        <div className="report-metrics report-summary-metrics">
          <article className="report-metric"><span>{t("metrics.totalCompliances")}</span><strong>{analytics.summary.total}</strong></article>
          <article className="report-metric"><span>{t("completionRate")}</span><strong>{formatPercentage(analytics.summary.completion_rate / 100)}</strong></article>
          <article className="report-metric"><span>{t("riskSummary")}</span><strong>{analytics.summary.high_risk}</strong></article>
          <article className="report-metric"><span>{t("metrics.overdue")}</span><strong>{analytics.summary.overdue}</strong></article>
        </div>
        <div className="report-chart-grid">
          <ChartPanel title={t("statusBreakdown")} points={analytics.charts.status_distribution} />
          <ChartPanel title={t("monthlyDeadlineTrend")} points={analytics.charts.monthly_deadline_trend} />
          <ChartPanel title={t("completionTrend")} points={analytics.charts.completion_trend} />
          <ChartPanel title={t("overdueTrend")} points={analytics.charts.overdue_trend} />
          <ChartPanel title={t("taskStatusDistribution")} points={analytics.charts.task_status_distribution} />
          {analytics.organization_summaries.length > 1 && <ChartPanel title={t("organizationComparison")} points={analytics.organization_summaries.map((item) => ({ status: item.organization_name, count: item.completion_percentage, value: formatPercentage(item.completion_percentage / 100) }))} />}
        </div>
        <section className="card report-detail-panel">
          <div className="report-section-heading"><div><h2>{t("detailedComplianceReport")}</h2><p>{t("records", { count: totalRows })}</p></div></div>
          {rows.length ? <div className="report-table-scroll"><table className="report-table report-detail-table">
            <thead><tr><th>{t("organization")}</th><th>{t("compliance")}</th><th>{t("applicability")}</th><th>{t("owner")}</th><th>{t("deadline")}</th><th>{t("priority")}</th><th>{t("status")}</th><th>{t("completion")}</th><th>{t("details")}</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.compliance_id}>
              <td><Link href={`/organizations/${row.organization_id}`}>{row.organization_name}</Link></td>
              <td><button className="report-record-link" type="button" onClick={() => onSelectCompliance(row.compliance_id)}>{row.code} · {row.title}</button></td>
              <td>{row.applicability}</td><td>{row.owner}</td><td>{formatShortDate(row.deadline)}</td><td>{row.priority}</td>
              <td>{statusLabel(row.status, tStatus)}</td><td>{formatPercentage(row.completion.progress / 100)}</td>
              <td className="report-details-cell"><details><summary>{t("details")}</summary>
                <div className="report-detail-content">
                  <section><h3>{t("tasksAndChecklist")}</h3>{[...row.tasks.map((item) => `${item.title} · ${item.status} · ${item.due_date}`), ...row.checklist.map((item) => `${item.title || item.task_id} · ${item.status} · ${item.required ? t("required") : t("optional")}`)].map((item) => <p key={item}>{item}</p>)}</section>
                  <section><h3>{t("evidenceCoverage")}</h3><p>{t("availableEvidence", { count: row.evidence_coverage.available_count })}</p>{row.evidence_coverage.requirements.map((item) => <p key={item.document_type}>{item.document_type}: {item.covered_count}/{item.minimum_count} · {item.satisfied ? t("satisfied") : t("outstanding")}</p>)}{row.evidence.map((item) => <p key={`${item.name}-${item.version}`}>{item.category}: {item.name} v{item.version}</p>)}</section>
                  <section><h3>{t("reviewAndApproval")}</h3>{row.reviews.map((item) => <p key={`review-${item.revision}`}>{t("reviewRevision", { revision: item.revision })}: {item.decision} · {item.reviewed_by || item.submitted_by}</p>)}{row.approvals.map((item) => <p key={`approval-${item.revision}`}>{t("approvalRevision", { revision: item.revision })}: {item.decision} · {item.approved_by || item.requested_by}</p>)}{row.filing && <p>{t("filingProof")}: {row.filing.reference} · {row.filing.proof_name || t("noProofFile")} v{row.filing.proof_version || "—"}</p>}</section>
                  <section><h3>{t("auditTimeline")}</h3>{row.audit_timeline.map((item, index) => <p key={`${item.action}-${item.occurred_at}-${index}`}>{formatShortDate(item.occurred_at)} · {item.actor} · {item.action}: {item.summary}</p>)}</section>
                </div>
              </details></td>
            </tr>)}</tbody>
          </table></div> : <p className="muted">{t("empty")}</p>}
          {totalRows > pageSize && <div className="report-pagination">
            <button type="button" className="button secondary small" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>{t("previous")}</button>
            <span>{page * pageSize + 1}–{Math.min(totalRows, (page + 1) * pageSize)} / {totalRows}</span>
            <button type="button" className="button secondary small" disabled={(page + 1) * pageSize >= totalRows} onClick={() => setPage((value) => value + 1)}>{t("next")}</button>
          </div>}
        </section>
      </>}
    </div>
  );
}
