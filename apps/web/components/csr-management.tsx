"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import type { Organization } from "@/lib/types";

type Partner = { id:string; organization_id:string; organization_name:string; status:string; review_status:string; profile_completeness:number; active_projects:number; open_reviews:number; requires_attention:boolean };
type Project = { id:string; relationship_id:string; name:string; code:string; status:string; shared_with_ngo:boolean };
type Template = { id:string; name:string; version:number; items:Array<{title:string}> };
type ReviewItem = { id:string; title:string; status:string; response:string; evidence:Array<{id:string;document_name:string;version:number;intelligence?:{notice:string;facts:Array<{type:string;value:string;status:string}>}}> };
type Review = { id:string; relationship_id:string; title:string; status:string; shared_with_ngo:boolean; items:ReviewItem[]; disclaimer:string };
type Dashboard = { summary:Record<string,number>; partners:Partner[] };

export default function CsrManagement({ organizations, role }:{ organizations:Organization[]; role:string }) {
  const t = useTranslations("Csr");
  const [partners,setPartners]=useState<Partner[]>([]), [projects,setProjects]=useState<Project[]>([]);
  const [templates,setTemplates]=useState<Template[]>([]), [reviews,setReviews]=useState<Review[]>([]);
  const [dashboard,setDashboard]=useState<Dashboard|null>(null), [tab,setTab]=useState("partners");
  const [error,setError]=useState(""), [message,setMessage]=useState(""), [busy,setBusy]=useState(false);
  const admin=role==="ADMIN";

  async function load() {
    setError("");
    const [partnerRows,projectRows,reviewRows]=await Promise.all([
      apiRequest<Partner[]>("/csr/partners"), apiRequest<Project[]>("/csr/projects"), apiRequest<Review[]>("/csr/reviews"),
    ]);
    setPartners(partnerRows); setProjects(projectRows); setReviews(reviewRows);
    try { setDashboard(await apiRequest<Dashboard>("/csr/dashboard")); } catch { setDashboard(null); }
    if(admin) try { setTemplates(await apiRequest<Template[]>("/csr/checklist-templates")); } catch { setTemplates([]); }
  }
  useEffect(()=>{ void load().catch(reason=>setError(reason instanceof Error?reason.message:t("loadError"))); },[]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(path:string, body:unknown, form:HTMLFormElement) {
    setBusy(true); setError(""); setMessage("");
    try { await apiRequest(path,"POST",body); form.reset(); setMessage(t("saved")); await load(); }
    catch(reason){ setError(reason instanceof Error?reason.message:t("saveError")); }
    finally{ setBusy(false); }
  }
  const unlinked=organizations.filter(org=>!partners.some(partner=>partner.organization_id===org.id));

  return <section className="page-section" aria-labelledby="csr-title">
    <div className="page-heading"><div><p className="eyebrow">{t("eyebrow")}</p><h1 id="csr-title">{t("title")}</h1><p>{t("subtitle")}</p></div>
      {dashboard && <a className="button secondary" href="/api/v1/csr/reports/portfolio.csv">{t("export")}</a>}</div>
    <div className="notice info"><strong>{t("operationalNotice")}</strong></div>
    {error && <p className="error-banner" role="alert">{error}</p>}{message && <p className="success-banner" role="status">{message}</p>}
    {dashboard && <div className="stat-grid">{[["total_partners","partners"],["active_projects","activeProjects"],["incomplete_due_diligence","incomplete"],["partners_requiring_attention","attention"]].map(([key,label])=><article className="stat-card" key={key}><span>{t(label)}</span><strong>{dashboard.summary[key]||0}</strong></article>)}</div>}
    <div className="tabs" role="tablist">{["partners","projects","reviews",...(admin?["templates"]:[])].map(value=><button key={value} role="tab" aria-selected={tab===value} className={tab===value?"active":""} onClick={()=>setTab(value)}>{t(value)}</button>)}</div>

    {tab==="partners" && <div className="panel"><h2>{t("partnerDirectory")}</h2>
      {admin && unlinked.length>0 && <form className="inline-form" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/partners",{organization_id:data.get("organization_id"),status:"PROSPECTIVE"},form)}}>
        <label>{t("organization")}<select name="organization_id" required>{unlinked.map(org=><option value={org.id} key={org.id}>{org.name}</option>)}</select></label><button className="button primary" disabled={busy}>{t("addPartner")}</button></form>}
      <div className="table-wrap"><table><thead><tr><th>{t("organization")}</th><th>{t("status")}</th><th>{t("reviewStatus")}</th><th>{t("profile")}</th><th>{t("projects")}</th><th>{t("reviews")}</th></tr></thead><tbody>{partners.map(row=><tr key={row.id}><td><strong>{row.organization_name}</strong></td><td>{row.status}</td><td>{row.review_status}</td><td>{row.profile_completeness}%</td><td>{row.active_projects}</td><td>{row.open_reviews}</td></tr>)}</tbody></table></div></div>}

    {tab==="projects" && <div className="panel"><h2>{t("projects")}</h2>{admin&&partners.length>0&&<form className="form-grid" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/projects",{relationship_id:data.get("relationship_id"),name:data.get("name"),code:data.get("code"),status:"PLANNED",shared_with_ngo:data.get("shared")==="on"},form)}}><label>{t("partner")}<select name="relationship_id" required>{partners.map(row=><option key={row.id} value={row.id}>{row.organization_name}</option>)}</select></label><label>{t("projectName")}<input name="name" required minLength={3}/></label><label>{t("projectCode")}<input name="code" required/></label><label><input type="checkbox" name="shared"/> {t("shareWithNgo")}</label><button className="button primary" disabled={busy}>{t("createProject")}</button></form>}
      <div className="table-wrap"><table><thead><tr><th>{t("projectName")}</th><th>{t("projectCode")}</th><th>{t("status")}</th><th>{t("shared")}</th></tr></thead><tbody>{projects.map(row=><tr key={row.id}><td>{row.name}</td><td>{row.code}</td><td>{row.status}</td><td>{row.shared_with_ngo?t("yes"):t("no")}</td></tr>)}</tbody></table></div></div>}

    {tab==="templates"&&admin&&<div className="panel"><h2>{t("templates")}</h2><form className="form-grid" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/checklist-templates",{name:data.get("name"),description:data.get("description"),version:1,enabled:true,items:[{category:data.get("category"),title:data.get("item"),requirement_type:"DOCUMENT",required:true,expiry_monitoring:true,share_with_ngo:true}]},form)}}><label>{t("templateName")}<input name="name" required minLength={3}/></label><label>{t("description")}<input name="description"/></label><label>{t("category")}<input name="category" required/></label><label>{t("requirement")}<input name="item" required minLength={3}/></label><button className="button primary" disabled={busy}>{t("createTemplate")}</button></form><ul className="plain-list">{templates.map(row=><li key={row.id}><strong>{row.name}</strong> · v{row.version} · {row.items.length} {t("requirements")}</li>)}</ul></div>}

    {tab==="reviews"&&<div className="panel"><h2>{t("reviews")}</h2>{admin&&partners.length>0&&templates.length>0&&<form className="form-grid" onSubmit={event=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);void submit("/csr/reviews",{relationship_id:data.get("relationship_id"),template_id:data.get("template_id"),title:data.get("title"),shared_with_ngo:data.get("shared")==="on"},form)}}><label>{t("partner")}<select name="relationship_id" required>{partners.map(row=><option key={row.id} value={row.id}>{row.organization_name}</option>)}</select></label><label>{t("templateName")}<select name="template_id" required>{templates.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label>{t("reviewTitle")}<input name="title" required minLength={3}/></label><label><input type="checkbox" name="shared"/> {t("shareWithNgo")}</label><button className="button primary" disabled={busy}>{t("startReview")}</button></form>}
      {reviews.map(review=><article className="list-card" key={review.id}><h3>{review.title}</h3><p>{review.status} · {review.shared_with_ngo?t("shared"):t("internal")}</p>{review.items.map(item=><div key={item.id}><strong>{item.title}</strong> <span className="status-pill">{item.status}</span>{item.evidence.map(file=><small key={file.id}>{file.document_name} v{file.version}{file.intelligence?` · ${file.intelligence.notice}`:""}</small>)}</div>)}</article>)}</div>}
  </section>;
}
