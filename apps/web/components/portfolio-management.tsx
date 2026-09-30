"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import { formatShortDate } from "@/i18n/format";
import type { Membership, Organization } from "@/lib/types";

type Summary = Record<string, number>;
type Dashboard = { summary: Summary };
type Client = {
  id: string; name: string; legal_type: string; status: string; city: string; primary_contact: string;
  compliance_count: number; overdue: number; upcoming: number; open_tasks: number;
  expiring_documents: number; expiring_registrations: number; health: string;
  responsible_consultant: { id: string; name: string } | null; last_activity_at: string;
};
type Task = {
  id: string; organization_id: string; organization_name: string; compliance_id: string | null;
  compliance: string; title: string; status: string; priority: string; assignee: string;
  due_at: string; overdue: boolean;
};
type Deadline = {
  id: string; organization_id: string; organization_name: string; code: string; title: string;
  owner: string; status: string; priority: string; deadline: string; days_remaining: number;
};
type Page<T> = { items: T[]; total: number };

export default function PortfolioManagement({
  organizations, memberships, role, onOpenClient, onOpenCompliance,
}: {
  organizations: Organization[]; memberships: Membership[]; role: string;
  onOpenClient: (id: string) => void; onOpenCompliance: (id: string) => void;
}) {
  const t = useTranslations("Portfolio");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [clients, setClients] = useState<Page<Client> | null>(null);
  const [tasks, setTasks] = useState<Page<Task> | null>(null);
  const [deadlines, setDeadlines] = useState<Page<Deadline> | null>(null);
  const [query, setQuery] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [timing, setTiming] = useState("ALL");
  const [attention, setAttention] = useState(false);
  const [selectedTasks, setSelectedTasks] = useState<string[]>([]);
  const [assignee, setAssignee] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadDirectory(search = query, needsAttention = attention) {
    const params = new URLSearchParams({ q: search, attention: String(needsAttention), sort_by: needsAttention ? "overdue" : "name", direction: needsAttention ? "desc" : "asc" });
    setClients(await apiRequest<Page<Client>>(`/portfolio/organizations?${params}`));
  }
  async function loadOperational(org = organizationId, window = timing) {
    const taskParams = new URLSearchParams({ timing: window });
    const deadlineParams = new URLSearchParams();
    if (org) { taskParams.set("organization_id", org); deadlineParams.set("organization_id", org); }
    const [queue, due] = await Promise.all([
      apiRequest<Page<Task>>(`/portfolio/work-queue?${taskParams}`),
      apiRequest<Page<Deadline>>(`/portfolio/deadlines?${deadlineParams}`),
    ]);
    setTasks(queue); setDeadlines(due); setSelectedTasks([]);
  }
  useEffect(() => {
    let active = true;
    Promise.all([
      apiRequest<Dashboard>("/portfolio/dashboard"),
      apiRequest<Page<Client>>("/portfolio/organizations"),
      apiRequest<Page<Task>>("/portfolio/work-queue"),
      apiRequest<Page<Deadline>>("/portfolio/deadlines"),
    ]).then(([overview, directory, queue, due]) => {
      if (active) { setDashboard(overview); setClients(directory); setTasks(queue); setDeadlines(due); }
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : t("loadError")); });
    return () => { active = false; };
  }, [t]);

  async function refreshDirectory(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await loadDirectory(); } catch (reason) { setError(reason instanceof Error ? reason.message : t("loadError")); }
    finally { setBusy(false); }
  }
  async function reassign() {
    if (!selectedTasks.length || !assignee) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await apiRequest("/portfolio/bulk/tasks/assignee", "POST", { target_ids: selectedTasks, assignee_user_id: assignee });
      setMessage(t("assignmentSaved", { count: selectedTasks.length }));
      await loadOperational();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("assignmentError")); }
    finally { setBusy(false); }
  }
  async function invite(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      await apiRequest("/admin/users/invite", "POST", {
        name: form.get("name"), email: form.get("email"), role: form.get("role"), organization_ids: [form.get("organization_id")],
      });
      setMessage(t("inviteSaved")); event.currentTarget.reset();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("inviteError")); }
    finally { setBusy(false); }
  }

  if (error && !dashboard) return <div className="report-error" role="alert">{error}</div>;
  if (!dashboard || !clients || !tasks || !deadlines) return <div className="report-loading" aria-busy="true">{t("loading")}</div>;
  const metrics: Array<[string, number]> = [
    ["organizations", dashboard.summary.organizations || 0], ["activeCompliances", dashboard.summary.active_compliances || 0],
    ["overdue", dashboard.summary.overdue || 0], ["incompleteTasks", dashboard.summary.incomplete_tasks || 0],
    ["underReview", dashboard.summary.under_review || 0], ["attention", dashboard.summary.organizations_requiring_attention || 0],
  ];
  const activeMembers = memberships.filter((member) => member.status === "ACTIVE" && member.role !== "VIEWER");
  return <section className="management-dashboard" aria-label={t("title")}>
    <div className="page-heading"><div><span className="eyebrow">{t("eyebrow")}</span><h1>{t("title")}</h1><p>{t("description")}</p></div></div>
    {error && <div className="report-error" role="alert">{error}</div>}
    {message && <div className="auth-alert success" role="status">{message}</div>}
    <div className="report-metrics">{metrics.map(([key, value]) => <article className="report-metric" key={key}><span>{t(`metrics.${key}`)}</span><strong>{value}</strong></article>)}</div>

    <section className="card report-organization-panel">
      <div className="report-section-heading"><div><h2>{t("clients")}</h2><p>{t("clientsHelp", { count: clients.total })}</p></div></div>
      <form className="report-filters" onSubmit={refreshDirectory}>
        <label>{t("search")}<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("searchPlaceholder")} /></label>
        <label><span>{t("attentionOnly")}</span><select value={attention ? "yes" : "no"} onChange={(event) => setAttention(event.target.value === "yes")}><option value="no">{t("allClients")}</option><option value="yes">{t("needsAttention")}</option></select></label>
        <button className="button secondary" disabled={busy}>{t("apply")}</button>
      </form>
      <div className="report-table-scroll"><table className="report-table"><thead><tr><th>{t("client")}</th><th>{t("health")}</th><th>{t("consultant")}</th><th>{t("compliances")}</th><th>{t("overdue")}</th><th>{t("openTasks")}</th><th>{t("expiring")}</th><th>{t("activity")}</th><th>{t("action")}</th></tr></thead>
        <tbody>{clients.items.map((client) => <tr key={client.id}><td><Link href={`/organizations/${client.id}`}><strong>{client.name}</strong></Link><br /><small>{client.legal_type} · {client.city}</small></td><td>{t(`healthValues.${client.health}`)}</td><td>{client.responsible_consultant?.name || t("unassigned")}</td><td>{client.compliance_count}</td><td>{client.overdue}</td><td>{client.open_tasks}</td><td>{client.expiring_documents + client.expiring_registrations}</td><td>{formatShortDate(client.last_activity_at)}</td><td><button className="report-record-link" type="button" onClick={() => onOpenClient(client.id)}>{t("openClient")}</button></td></tr>)}</tbody>
      </table></div>{!clients.items.length && <p className="muted">{t("emptyClients")}</p>}
    </section>

    <section className="card report-deadline-panel">
      <div className="report-section-heading"><div><h2>{t("workQueue")}</h2><p>{t("workQueueHelp", { count: tasks.total })}</p></div></div>
      <div className="report-filters">
        <label>{t("organization")}<select value={organizationId} onChange={(event) => { const value = event.target.value; setOrganizationId(value); void loadOperational(value, timing); }}><option value="">{t("allClients")}</option>{organizations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>{t("dueWindow")}<select value={timing} onChange={(event) => { const value = event.target.value; setTiming(value); void loadOperational(organizationId, value); }}>{["ALL", "OVERDUE", "TODAY", "WEEK", "MONTH"].map((value) => <option key={value} value={value}>{t(`timing.${value}`)}</option>)}</select></label>
        {role !== "VIEWER" && <><label>{t("assignTo")}<select value={assignee} onChange={(event) => setAssignee(event.target.value)}><option value="">{t("chooseConsultant")}</option>{activeMembers.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label><button type="button" className="button secondary" disabled={busy || !selectedTasks.length || !assignee} onClick={() => void reassign()}>{t("assignSelected", { count: selectedTasks.length })}</button></>}
      </div>
      <div className="report-table-scroll"><table className="report-table"><thead><tr>{role !== "VIEWER" && <th>{t("select")}</th>}<th>{t("task")}</th><th>{t("organization")}</th><th>{t("compliance")}</th><th>{t("assignee")}</th><th>{t("due")}</th><th>{t("status")}</th></tr></thead><tbody>{tasks.items.map((task) => <tr key={task.id}>{role !== "VIEWER" && <td><input type="checkbox" aria-label={t("selectTask", { title: task.title })} checked={selectedTasks.includes(task.id)} onChange={(event) => setSelectedTasks((items) => event.target.checked ? [...items, task.id] : items.filter((id) => id !== task.id))} /></td>}<td><strong>{task.title}</strong><br /><small>{task.priority}</small></td><td>{task.organization_name}</td><td>{task.compliance || "—"}</td><td>{task.assignee || t("unassigned")}</td><td>{formatShortDate(task.due_at)}</td><td>{task.overdue ? t("overdue") : task.status}</td></tr>)}</tbody></table></div>
    </section>

    <section className="card report-deadline-panel"><div className="report-section-heading"><div><h2>{t("deadlines")}</h2><p>{t("deadlinesHelp", { count: deadlines.total })}</p></div></div><div className="report-table-scroll"><table className="report-table"><thead><tr><th>{t("compliance")}</th><th>{t("organization")}</th><th>{t("owner")}</th><th>{t("due")}</th><th>{t("daysRemaining")}</th><th>{t("status")}</th></tr></thead><tbody>{deadlines.items.map((item) => <tr key={item.id}><td><button className="report-record-link" type="button" onClick={() => onOpenCompliance(item.id)}>{item.code} · {item.title}</button></td><td>{item.organization_name}</td><td>{item.owner || t("unassigned")}</td><td>{formatShortDate(item.deadline)}</td><td>{item.days_remaining}</td><td>{item.status}</td></tr>)}</tbody></table></div></section>

    {role === "ADMIN" && <section className="card"><div className="report-section-heading"><div><h2>{t("inviteClientUser")}</h2><p>{t("inviteHelp")}</p></div></div><form className="report-filters" onSubmit={invite}><label>{t("name")}<input name="name" required minLength={2} maxLength={120} /></label><label>{t("email")}<input name="email" type="email" required maxLength={200} /></label><label>{t("organization")}<select name="organization_id" required defaultValue=""><option value="" disabled>{t("chooseClient")}</option>{organizations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>{t("access")}<select name="role" defaultValue="VIEWER"><option value="VIEWER">{t("viewer")}</option><option value="MEMBER">{t("contributor")}</option></select></label><button className="button primary" disabled={busy}>{t("invite")}</button></form></section>}
  </section>;
}
