"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {useTranslations} from "next-intl";
import {apiRequest} from "@/lib/http";
import {contentUrl} from "@/lib/evidence";
import type {AuthUser} from "@/lib/auth-types";
import type {RuntimeDetail, Evaluation} from "@/lib/runtime";
import type {Compliance} from "@/lib/types";
import OrganizationShell from "./organization-shell";
import ComplianceTemplateRuntime from "./compliance-template-runtime";

export default function RuntimeDetailView({id,user}:{id:string;user:AuthUser}) {
 const t=useTranslations("Runtime"), common=useTranslations("Common"), roles=useTranslations("ComplianceMaster");
 const [detail,setDetail]=useState<RuntimeDetail|null>(null),[candidates,setCandidates]=useState<{id:string;name:string;role:string}[]>([]);
 const [owner,setOwner]=useState(""),[reason,setReason]=useState(""),[overrideReason,setOverrideReason]=useState(""),[decision,setDecision]=useState("FORCE_APPLICABLE");
 const [busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState(""),[nextId,setNextId]=useState("");
 const allowed=user.role==="ADMIN";
 async function load(){try{const [d,m]=await Promise.all([apiRequest<RuntimeDetail>(`/compliances/${id}/runtime-detail`),apiRequest<typeof candidates>(`/compliances/${id}/owner-candidates`)]);setDetail(d);setCandidates(m);setOwner(d.owner?.owner_id||"");}catch(e){setError(e instanceof Error?e.message:t("error"));}}
 useEffect(()=>{void load();},[id]);
 async function act(action:()=>Promise<unknown>){setBusy(true);setError("");setMessage("");try{await action();await load();setMessage(t("saved"));}catch(e){setError(e instanceof Error?e.message:t("error"));}finally{setBusy(false);}}
 return <OrganizationShell><h1>{detail?.compliance.title||t("title")}</h1>{error&&<p className="auth-alert error" role="alert">{error}<button className="text-button" onClick={()=>{setError("");void load();}}>{t("retry")}</button></p>}{message&&<p role="status">{message}</p>}{!detail&&!error&&<p role="status">{t("loading")}</p>}{detail&&<>
 <section className="organization-panel"><dl className="runtime-facts">
 <dt>{t("organization")}</dt><dd><Link href={`/organizations/${detail.organization.id}`}>{detail.organization.name}</Link></dd>
 <dt>{t("status")}</dt><dd>{common(`status.${detail.compliance.status}`)}</dd><dt>{t("priority")}</dt><dd>{detail.compliance.priority}</dd>
 <dt>{t("risk")}</dt><dd>{detail.snapshot?.configuration.risk_level||detail.compliance.risk_note}</dd>
 <dt>{t("deadline")}</dt><dd>{detail.compliance.statutory_deadline}</dd><dt>{t("target")}</dt><dd>{detail.compliance.internal_target}</dd>
 <dt>{t("version")}</dt><dd>{detail.snapshot?.version||t("noRecords")}</dd><dt>{t("cycle")}</dt><dd>{detail.snapshot?.cycle||detail.compliance.period}</dd>
 <dt>{t("owner")}</dt><dd>{detail.owner_required?t("ownerRequired"):detail.owner?.name}</dd>
 {detail.owner&&<><dt>{t("assignedBy")}</dt><dd>{candidates.find(c=>c.id===detail.owner?.assigned_by)?.name||t("system")}</dd><dt>{t("assignedAt")}</dt><dd>{detail.owner.assigned_at}</dd></>}
 </dl>{allowed&&<form className="organization-form" onSubmit={e=>{e.preventDefault();void act(()=>apiRequest(`/compliances/${id}/owner`,"POST",{owner_id:owner,expected_owner_id:detail.owner?.owner_id||null,reason}));}}><label>{t("owner")}<select required value={owner} onChange={e=>setOwner(e.target.value)}><option value="">{t("select")}</option>{candidates.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label>{t("reason")}<input required minLength={3} maxLength={500} value={reason} onChange={e=>setReason(e.target.value)}/></label><button className="button primary" disabled={busy}>{t("assign")}</button></form>}</section>
 {detail.snapshot&&<section className="organization-panel"><h2>{t("applicability")}</h2><p>{t("historySafety")}</p>{detail.requires_reevaluation&&<p role="status">{t("stale")}</p>}{allowed&&<button className="button secondary" disabled={busy} onClick={()=>void act(()=>apiRequest<{results:Evaluation[]}>(`/organizations/${detail.organization.id}/evaluate-compliance`,"POST"))}>{t("reevaluate")}</button>}
 {detail.override&&<p>{t("override")}: {t(detail.override.decision)} ? {detail.override.reason} ({detail.override.created_at})</p>}<details><summary>{t("overrideHistory")}</summary><ul>{detail.override_history.map(o=><li key={o.id}>{t(o.decision)} ? {o.reason} ? {o.created_at}</li>)}</ul></details>
 <ul className="organization-records">{detail.decisions.map(d=><li key={d.id}><p>{t("rule")}: {t(d.rule_result)} ? {t("effective")}: {t(d.effective_result)} ? {t(d.comparison)}</p><p>{d.reason} ? {t("evaluatedAt")}: {d.evaluated_at}</p><p>{t("evaluatedBy")}: {candidates.find(c=>c.id===d.evaluated_by)?.name||t("system")}</p><small>{t("factsHash")}: {d.facts_hash}</small><details><summary>{t("explanations")}</summary>{d.explanations.groups.map(g=><ul key={g.id}>{g.conditions.map(c=><li key={c.id}>{c.field}: {t("actual")} {JSON.stringify(c.actual)} / {t("expected")} {JSON.stringify(c.expected)} ? {t(c.satisfied===null?"unknown":c.satisfied?"yes":"no")}</li>)}</ul>)}</details></li>)}</ul>
 {allowed&&<form className="organization-form" onSubmit={e=>{e.preventDefault();void act(()=>apiRequest(`/organizations/${detail.organization.id}/templates/${detail.snapshot!.definition_id}/override`,"POST",{decision,reason:overrideReason,expected_override_id:detail.override?.id||null}));}}><label>{t("override")}<select value={decision} onChange={e=>setDecision(e.target.value)}>{["FORCE_APPLICABLE","FORCE_NOT_APPLICABLE","CLEAR_OVERRIDE"].map(d=><option key={d} value={d}>{t(d)}</option>)}</select></label><label>{t("reason")}<textarea required minLength={5} maxLength={1000} value={overrideReason} onChange={e=>setOverrideReason(e.target.value)}/></label><button className="button primary" disabled={busy}>{t("saveOverride")}</button></form>}
 </section>}
 <section className="organization-panel"><h2>{t("tasks")}</h2><ul className="organization-records">{detail.tasks.map(task=><li key={task.id}>{task.title} ? {t(task.status==="DONE"?"taskDoneStatus":task.status==="IN_PROGRESS"?"taskInProgressStatus":"taskTodoStatus")} ? {task.due_at} ? {task.assignee_name}{user.role!=="VIEWER"&&<button className="button secondary" disabled={busy} onClick={()=>void act(()=>apiRequest(`/tasks/${task.id}`,"PATCH",{status:task.status==="DONE"?"TODO":"DONE"}))}>{t(task.status==="DONE"?"todo":"done")}</button>}</li>)}</ul><Link href={`/organizations/${detail.organization.id}`}>{t("documents")}</Link>
 {detail.snapshot?<ComplianceTemplateRuntime item={detail.compliance} updated={()=>void load()}/>:<p>{t("templateMissing")}</p>}</section>
 <section className="organization-panel"><h2>{t("submissions")}</h2><ul className="organization-records">{detail.submissions.map(s=><li key={s.id}>{t("reference")}: {s.reference} ? {s.submitted_at}{detail.evidence_links.filter(l=>l.submission_id===s.id).map(l=><p key={l.id}><a href={contentUrl(l.document_id,l.version_id)}>{t("download")}</a></p>)}</li>)}</ul>{!detail.submissions.length&&<p>{t("noRecords")}</p>}</section>
 <section className="organization-panel"><h2>{t("reminders")}</h2><ul className="organization-records">{detail.reminders.map(r=><li key={r.id}>{roles(`roles.${r.configuration.recipient_role}`)} ? {r.configuration.text} ? {t("scheduled")}: {r.scheduled_for} ? {r.sent_at?`${t("sent")}: ${r.sent_at}`:t("pending")}</li>)}</ul></section>
 <section className="organization-panel"><h2>{t("workflow")}</h2><ul className="organization-records">{detail.audit.filter(a=>a.action==="STATUS_CHANGED").map(a=><li key={a.id}>{a.summary} ? {a.actor_name} ? {a.created_at}</li>)}</ul><h2>{t("audit")}</h2><ul className="organization-records">{detail.audit.map(a=><li key={a.id}>{a.action} ? {a.summary} ? {a.actor_name} ? {a.created_at}</li>)}</ul></section>
 {allowed&&detail.snapshot&&<section className="organization-panel"><button className="button primary" disabled={busy} onClick={()=>void act(async()=>{const result=await apiRequest<{compliance:Compliance}>(`/compliances/${id}/next-cycle`,"POST");setNextId(result.compliance.id);})}>{t("nextCycle")}</button>{nextId&&<p role="status"><Link href={`/compliances/${nextId}`}>{t("nextReady")}</Link></p>}</section>}
 </>}</OrganizationShell>;
}
