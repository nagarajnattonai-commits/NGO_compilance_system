"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import type { Organization } from "@/lib/types";
import { PartnerControls, ProjectControls, ReviewContents, type CsrPartner as Partner, type CsrProject as Project, type CsrReview as Review } from "./csr-workflow-controls";

type Template = { id:string; name:string; version:number; items:Array<{title:string}> };
type Dashboard = { summary:Record<string,number>; partners:Partner[] };

export default function CsrManagement({ organizations, role, initialTarget }:{ organizations:Organization[]; role:string; initialTarget?:{id:string;type:string}|null }) {
  const t = useTranslations("Csr");
  const [partners,setPartners]=useState<Partner[]>([]), [projects,setProjects]=useState<Project[]>([]);
  const [templates,setTemplates]=useState<Template[]>([]), [reviews,setReviews]=useState<Review[]>([]);
  const [dashboard,setDashboard]=useState<Dashboard|null>(null), [tab,setTab]=useState("partners");
  const [error,setError]=useState(""), [message,setMessage]=useState(""), [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [reviewPartner,setReviewPartner]=useState("");
  const admin=role==="ADMIN";
  useEffect(()=>{
    if(initialTarget) setTab(initialTarget.type==="csr_project"?"projects":initialTarget.type==="due_diligence"?"reviews":"partners");
  },[initialTarget]);
  useEffect(()=>{
    if(!initialTarget) return;
    // Only elements rendered from authorized API records can be focused.
    const row=document.getElementById(`csr-record-${initialTarget.id}`);
    if(row){row.scrollIntoView({block:"center"});row.focus();}
  },[initialTarget,tab,partners,projects,reviews]);

  async function load() {
    const [partnerRows,projectRows,reviewRows]=await Promise.all([
      apiRequest<Partner[]>("/csr/partners"), apiRequest<Project[]>("/csr/projects"), apiRequest<Review[]>("/csr/reviews"),
    ]);
    setPartners(partnerRows); setProjects(projectRows); setReviews(reviewRows);
    try { setDashboard(await apiRequest<Dashboard>("/csr/dashboard")); } catch { setDashboard(null); }
    if(admin) try { setTemplates(await apiRequest<Template[]>("/csr/checklist-templates")); } catch { setTemplates([]); }
  }
  async function reload() {
    setLoading(true);setError("");
    try{await load();}catch(reason){setError(reason instanceof Error?reason.message:t("loadError"));}
    finally{setLoading(false);}
  }
  useEffect(()=>{ void reload(); },[]); // eslint-disable-line react-hooks/exhaustive-deps

  async function mutate(path:string, method:string, body:unknown):Promise<boolean> {
    setBusy(true);setError("");setMessage("");
    try{await apiRequest(path,method,body);await load();setMessage(t("saved"));return true;}
    catch(reason){setError(reason instanceof Error?reason.message:t("saveError"));return false;}
    finally{setBusy(false);}
  }

  async function submit(path:string, body:unknown, form:HTMLFormElement) {
    if(await mutate(path,"POST",body)) form.reset();
  }
  const unlinked=organizations.filter(org=>!partners.some(partner=>partner.organization_id===org.id));

  return <section className="page-section" aria-labelledby="csr-title">
    <div className="page-heading"><div><p className="eyebrow">{t("eyebrow")}</p><h1 id="csr-title">{t("title")}</h1><p>{t("subtitle")}</p></div>
      {dashboard && <a className="button secondary" href="/api/v1/csr/reports/portfolio.csv">{t("export")}</a>}</div>
    <div className="notice info"><strong>{t("operationalNotice")}</strong></div>
    {error && <p className="error-banner" role="alert">{error}<button type="button" disabled={busy||loading} onClick={()=>void reload()}>Try again</button></p>}{message && <p className="success-banner" role="status">{message}</p>}
    {loading&&<p role="status">Loading CSR records…</p>}
    {dashboard && <div className="stat-grid">{[["total_partners","partners"],["active_projects","activeProjects"],["incomplete_due_diligence","incomplete"],["partners_requiring_attention","attention"]].map(([key,label])=><article className="stat-card" key={key}><span>{t(label)}</span><strong>{dashboard.summary[key]||0}</strong></article>)}</div>}
    <div className="tabs" role="tablist">{["partners","projects","reviews",...(admin?["templates"]:[])].map(value=><button key={value} role="tab" aria-selected={tab===value} className={tab===value?"active":""} onClick={()=>setTab(value)}>{t(value)}</button>)}</div>

    {tab==="partners" && <div className="panel"><h2>{t("partnerDirectory")}</h2>
      {admin && unlinked.length>0 && <form className="inline-form" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/partners",{organization_id:data.get("organization_id"),status:"PROSPECTIVE"},form)}}>
        <label>{t("organization")}<select name="organization_id" required>{unlinked.map(org=><option value={org.id} key={org.id}>{org.name}</option>)}</select></label><button className="button primary" disabled={busy}>{t("addPartner")}</button></form>}
      {!loading&&!partners.length&&<p>No authorized CSR partners yet.</p>}
      <div className="table-wrap"><table><thead><tr><th>{t("organization")}</th><th>{t("status")}</th><th>{t("reviewStatus")}</th><th>{t("profile")}</th><th>{t("projects")}</th><th>{t("reviews")}</th></tr></thead><tbody>{partners.map(row=><tr key={row.id} id={`csr-record-${row.id}`} tabIndex={-1} aria-current={initialTarget?.id===row.id?true:undefined}><td><strong>{row.organization_name}</strong><PartnerControls partner={row} busy={busy} mutate={mutate}/></td><td>{row.status}</td><td>{row.review_status}</td><td>{row.profile_completeness}%</td><td>{row.active_projects}</td><td>{row.open_reviews}</td></tr>)}</tbody></table></div></div>}

    {tab==="projects" && <div className="panel"><h2>{t("projects")}</h2>{admin&&partners.length>0&&<form className="form-grid" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/projects",{relationship_id:data.get("relationship_id"),name:data.get("name"),code:data.get("code"),status:"PLANNED",shared_with_ngo:data.get("shared")==="on"},form)}}><label>{t("partner")}<select name="relationship_id" required>{partners.map(row=><option key={row.id} value={row.id}>{row.organization_name}</option>)}</select></label><label>{t("projectName")}<input name="name" required minLength={3}/></label><label>{t("projectCode")}<input name="code" required/></label><label><input type="checkbox" name="shared"/> {t("shareWithNgo")}</label><button className="button primary" disabled={busy}>{t("createProject")}</button></form>}
      {!loading&&!projects.length&&<p>No authorized CSR projects yet.</p>}
      <div className="table-wrap"><table><thead><tr><th>{t("projectName")}</th><th>{t("projectCode")}</th><th>{t("status")}</th><th>{t("shared")}</th></tr></thead><tbody>{projects.map(row=><tr key={row.id} id={`csr-record-${row.id}`} tabIndex={-1} aria-current={initialTarget?.id===row.id?true:undefined}><td>{row.name}<ProjectControls project={row} partner={partners.find(partner=>partner.id===row.relationship_id)} busy={busy} mutate={mutate}/></td><td>{row.code}</td><td>{row.status}</td><td>{row.shared_with_ngo?t("yes"):t("no")}</td></tr>)}</tbody></table></div></div>}

    {tab==="templates"&&admin&&<div className="panel"><h2>{t("templates")}</h2><form className="form-grid" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/checklist-templates",{name:data.get("name"),description:data.get("description"),version:1,enabled:true,items:[{category:data.get("category"),title:data.get("item"),requirement_type:"DOCUMENT",required:true,expiry_monitoring:true,share_with_ngo:true}]},form)}}><label>{t("templateName")}<input name="name" required minLength={3}/></label><label>{t("description")}<input name="description"/></label><label>{t("category")}<input name="category" required/></label><label>{t("requirement")}<input name="item" required minLength={3}/></label><button className="button primary" disabled={busy}>{t("createTemplate")}</button></form><ul className="plain-list">{templates.map(row=><li key={row.id}><strong>{row.name}</strong> · v{row.version} · {row.items.length} {t("requirements")}</li>)}</ul></div>}

    {tab==="reviews"&&<div className="panel"><h2>{t("reviews")}</h2>{admin&&partners.length>0&&templates.length>0&&<form className="form-grid" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/reviews",{relationship_id:data.get("relationship_id"),template_id:data.get("template_id"),project_id:data.get("project_id")||null,title:data.get("title"),due_date:data.get("due_date")||null,shared_with_ngo:data.get("shared")==="on"},form)}}><label>{t("partner")}<select name="relationship_id" required value={reviewPartner||partners[0].id} onChange={event=>setReviewPartner(event.target.value)}>{partners.map(row=><option key={row.id} value={row.id}>{row.organization_name}</option>)}</select></label><label>Project (optional)<select name="project_id" key={reviewPartner}><option value="">Partner-wide review</option>{projects.filter(project=>project.relationship_id===(reviewPartner||partners[0].id)).map(project=><option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label>{t("templateName")}<select name="template_id" required>{templates.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label>{t("reviewTitle")}<input name="title" required minLength={3} maxLength={200}/></label><label>Review deadline<input name="due_date" type="date"/></label><label><input type="checkbox" name="shared"/> {t("shareWithNgo")}</label><button className="button primary" disabled={busy}>{t("startReview")}</button></form>}
      {!loading&&!reviews.length&&<p>No authorized due-diligence reviews yet.</p>}
      {reviews.map(review=><article className="list-card" key={review.id} id={`csr-record-${review.id}`} tabIndex={-1} aria-current={initialTarget?.id===review.id?true:undefined}><h3>{review.title}</h3><p>{partners.find(partner=>partner.id===review.relationship_id)?.organization_name} · {projects.find(project=>project.id===review.project_id)?.name||"Partner-wide review"}</p><p>{review.status} · {review.shared_with_ngo?t("shared"):t("internal")}</p><ReviewContents review={review} busy={busy} mutate={mutate} targetId={initialTarget?.id}/></article>)}</div>}
  </section>;
}
