"use client";

import { useState, type FormEvent } from "react";
import { apiRequest } from "@/lib/http";
import type { ComplianceDocument, ComplianceTask } from "@/lib/types";

export type CsrPartner = { id:string; organization_id:string; organization_name:string; status:string; review_status:string; profile_completeness:number; active_projects:number; open_reviews:number; requires_attention:boolean; can_manage?:boolean; can_grant_collaborators?:boolean; shared_notes?:string; internal_notes?:string; collaboration_enabled?:boolean };
export type CsrProject = { id:string; relationship_id:string; name:string; code:string; status:string; shared_with_ngo:boolean; description?:string; internal_notes?:string };
type Evidence = { id:string; document_id?:string; document_name:string; version:number; expired?:boolean; intelligence?:{notice:string;facts:Array<{type:string;value:string;status:string}>} };
export type CsrItem = { id:string; title:string; description?:string; category?:string; requirement_type?:string; required?:boolean; status:string; response:string; reviewer_comment?:string; internal_notes?:string; allowed_statuses?:string[]; evidence:Evidence[]; tasks?:Array<{id:string;title:string;status:string}> };
export type CsrReview = { id:string; relationship_id:string; organization_id:string; project_id?:string|null; title:string; status:string; shared_with_ngo:boolean; items:CsrItem[]; disclaimer:string; can_write?:boolean; collaborator_view?:boolean; due_date?:string|null; updated_at?:string; history?:Array<{id:string;action:string;actor_name:string;summary:string;created_at:string}> };
export type CsrMutate = (path:string, method:string, body:unknown) => Promise<boolean>;

function values(event:FormEvent<HTMLFormElement>) { event.preventDefault(); return new FormData(event.currentTarget); }
const partnerStates=["PROSPECTIVE","UNDER_REVIEW","APPROVED","ACTIVE","ON_HOLD","INACTIVE"];
const projectStates=["DRAFT","PLANNED","ACTIVE","ON_HOLD","COMPLETED","CANCELLED"];

export function PartnerControls({partner,busy,mutate}:{partner:CsrPartner;busy:boolean;mutate:CsrMutate}) {
  return <>
    {partner.shared_notes && <p>{partner.shared_notes}</p>}
    {partner.can_manage && <details><summary>Edit partner</summary><form className="form-grid" key={`${partner.status}-${partner.shared_notes}-${partner.internal_notes}`} onSubmit={event=>{const data=values(event);void mutate(`/csr/partners/${partner.id}`,"PATCH",{status:data.get("status"),shared_notes:data.get("shared_notes"),internal_notes:data.get("internal_notes")});}}>
      <label>Partner status<select name="status" defaultValue={partner.status}>{partnerStates.map(status=><option key={status}>{status}</option>)}</select></label>
      <label>Shared notes<textarea name="shared_notes" maxLength={4000} defaultValue={partner.shared_notes||""}/></label>
      <label>Corporate internal notes<textarea name="internal_notes" maxLength={4000} defaultValue={partner.internal_notes||""}/></label>
      <button className="button primary" disabled={busy}>Save partner</button>
    </form></details>}
    {partner.can_grant_collaborators && <CollaboratorGrant partner={partner} busy={busy} mutate={mutate}/>}
  </>;
}

function CollaboratorGrant({partner,busy,mutate}:{partner:CsrPartner;busy:boolean;mutate:CsrMutate}) {
  const [users,setUsers]=useState<Array<{id:string;name:string;email:string}>>([]),[loading,setLoading]=useState(false),[error,setError]=useState("");
  async function load() {
    setLoading(true);setError("");
    try {
      const rows=await apiRequest<Array<{id:string;name:string;email:string;status:string}>>("/admin/users");
      setUsers(rows.filter(user=>user.status==="ACTIVE"));
    }
    catch(reason){setError(reason instanceof Error?reason.message:"Could not load authorized users.");}
    finally{setLoading(false);}
  }
  return <details onToggle={event=>{if(event.currentTarget.open) void load();}}><summary>Grant NGO collaborator access</summary>
    <p>Only explicitly shared CSR records are available to collaborators. Existing organization access is required and is validated by the server. Viewer accounts remain read-only.</p>
    {loading&&<p role="status">Loading authorized users…</p>}{error&&<p role="alert" className="error-banner">{error}<button type="button" onClick={()=>void load()}>Try again</button></p>}
    {!loading&&!error&&!users.length&&<p>No eligible users. Configure workspace and organization access first.</p>}
    <form className="inline-form" onSubmit={event=>{const data=values(event);void mutate(`/csr/partners/${partner.id}/collaborators`,"POST",{user_id:data.get("user_id")});}}>
      <label>Collaborator<select name="user_id" required disabled={loading||!!error||!users.length}><option value="">Select authorized user</option>{users.map(user=><option key={user.id} value={user.id}>{user.name} ({user.email})</option>)}</select></label>
      <button className="button primary" disabled={busy||loading||!!error||!users.length}>Grant access</button>
    </form>
  </details>;
}

export function ProjectControls({project,partner,busy,mutate}:{project:CsrProject;partner?:CsrPartner;busy:boolean;mutate:CsrMutate}) {
  if(!partner?.can_manage) return null;
  return <details><summary>Edit project</summary><form className="form-grid" key={`${project.name}-${project.status}-${project.shared_with_ngo}`} onSubmit={event=>{const data=values(event);void mutate(`/csr/projects/${project.id}`,"PATCH",{name:data.get("name"),description:data.get("description"),status:data.get("status"),shared_with_ngo:data.get("shared")==="on"});}}>
    <label>Project name<input name="name" required minLength={3} maxLength={200} defaultValue={project.name}/></label>
    <label>Description<textarea name="description" maxLength={5000} defaultValue={project.description||""}/></label>
    <label>Project status<select name="status" defaultValue={project.status}>{projectStates.map(status=><option key={status}>{status}</option>)}</select></label>
    <label><input type="checkbox" name="shared" defaultChecked={project.shared_with_ngo}/> Share with NGO</label>
    <button className="button primary" disabled={busy}>Save project</button>
  </form></details>;
}

function ItemControls({item,review,busy,mutate}:{item:CsrItem;review:CsrReview;busy:boolean;mutate:CsrMutate}) {
  const [documents,setDocuments]=useState<ComplianceDocument[]>([]),[tasks,setTasks]=useState<ComplianceTask[]>([]),[loaded,setLoaded]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState("");
  async function loadLinks() {
    setLoading(true);setError("");setLoaded(false);
    try {
      const org=encodeURIComponent(review.organization_id);
      const [docs,taskRows]=await Promise.all([apiRequest<ComplianceDocument[]>(`/documents?organization_id=${org}`),review.collaborator_view?Promise.resolve([]):apiRequest<ComplianceTask[]>(`/tasks?organization_id=${org}`)]);
      setDocuments(docs.filter(doc=>doc.storage_status==="AVAILABLE"&&doc.current_version_id));setTasks(taskRows.filter(task=>!task.archived_at&&!item.tasks?.some(link=>link.id===task.id)));setLoaded(true);
    } catch(reason){setError(reason instanceof Error?reason.message:"Could not load authorized records.");}
    finally{setLoading(false);}
  }
  if(!review.can_write) return null;
  const availableTasks=tasks.filter(task=>!item.tasks?.some(link=>link.id===task.id));
  return <>
    <form className="form-grid" key={`${item.status}-${item.response}-${item.reviewer_comment}-${item.internal_notes}`} aria-label={`Update ${item.title}`} onSubmit={event=>{const data=values(event);void mutate(`/csr/items/${item.id}`,"PATCH",{status:data.get("status"),response:data.get("response"),...(!review.collaborator_view?{reviewer_comment:data.get("reviewer_comment"),internal_notes:data.get("internal_notes")}: {})});}}>
      <label>Checklist status<select name="status" defaultValue={item.status} required>{(item.allowed_statuses||[]).map(status=><option key={status}>{status}</option>)}</select></label>
      <label>Response<textarea name="response" maxLength={5000} defaultValue={item.response}/></label>
      {!review.collaborator_view&&<><label>Reviewer comment<textarea name="reviewer_comment" maxLength={4000} defaultValue={item.reviewer_comment||""}/></label><label>Corporate internal notes<textarea name="internal_notes" maxLength={4000} defaultValue={item.internal_notes||""}/></label></>}
      <button className="button primary" disabled={busy||!item.allowed_statuses?.length}>Save response / decision</button>
    </form>
    <details onToggle={event=>{if(event.currentTarget.open) void loadLinks();}}><summary>Link existing evidence{!review.collaborator_view?" / task":""}</summary>
      {loading&&<p role="status">Loading authorized records…</p>}{error&&<p className="error-banner" role="alert">{error}<button type="button" onClick={()=>void loadLinks()}>Try again</button></p>}
      {loaded&&<><form className="inline-form" onSubmit={event=>{const data=values(event);void mutate(`/csr/items/${item.id}/evidence`,"POST",{version_id:data.get("version_id")});}}>
        <label>Existing evidence<select name="version_id" required><option value="">Select available document version</option>{documents.map(doc=><option key={doc.id} value={doc.current_version_id!}>{doc.name} v{doc.version}</option>)}</select></label><button className="button primary" disabled={busy||!documents.length}>Link evidence</button>
      </form>{!documents.length&&<p>No available uploaded evidence for this organization.</p>}
      {!review.collaborator_view&&<><form className="inline-form" onSubmit={event=>{const data=values(event);void mutate("/csr/task-links","POST",{relationship_id:review.relationship_id,item_id:item.id,task_id:data.get("task_id")});}}>
        <label>Existing task<select name="task_id" required><option value="">Select authorized task</option>{availableTasks.map(task=><option key={task.id} value={task.id}>{task.title} ({task.status})</option>)}</select></label><button className="button primary" disabled={busy||!availableTasks.length}>Link task</button>
      </form>{!availableTasks.length&&<p>No unlinked active tasks for this organization.</p>}</>}
      </>}
    </details>
  </>;
}

export function ReviewContents({review,busy,mutate,targetId}:{review:CsrReview;busy:boolean;mutate:CsrMutate;targetId?:string}) {
  return <>
    <p>{review.disclaimer}</p>{review.due_date&&<p>Due: {review.due_date}</p>}
    {!review.items.length&&<p>No shared checklist items are available.</p>}
    {review.items.map(item=><section className="list-card" key={item.id} aria-label={item.title} id={`csr-record-${item.id}`} tabIndex={-1} aria-current={targetId===item.id?true:undefined}>
      <h4>{item.title} <span className="status-pill">{item.status}</span></h4><p>{item.category} · {item.requirement_type} · {item.required?"Required":"Optional"}</p>{item.description&&<p>{item.description}</p>}
      {item.response&&<p>Response: {item.response}</p>}{item.reviewer_comment&&<p>Reviewer comment: {item.reviewer_comment}</p>}
      <h5>Evidence</h5>{!item.evidence.length&&<p>No evidence linked.</p>}<ul className="plain-list">{item.evidence.map(file=><li key={file.id}>{file.document_id?<a href={`/dashboard?view=documents&record=${encodeURIComponent(file.document_id)}`}>{file.document_name}</a>:file.document_name} v{file.version}{file.expired?" · Expired":""}{file.intelligence?` · ${file.intelligence.notice}`:""}</li>)}</ul>
      <h5>Tasks</h5>{!item.tasks?.length&&<p>No tasks linked.</p>}<ul className="plain-list">{item.tasks?.map(task=><li key={task.id}><a href={`/dashboard?view=tasks&record=${encodeURIComponent(task.id)}`}>{task.title}</a> · {task.status}</li>)}</ul>
      <ItemControls item={item} review={review} busy={busy} mutate={mutate}/>
    </section>)}
    <details><summary>Status / history</summary><ul className="plain-list">{review.history?.map(event=><li key={event.id}><time dateTime={event.created_at}>{event.created_at}</time> · {event.actor_name} · {event.summary}</li>)}</ul>{!review.history?.length&&<p>No review history yet.</p>}</details>
  </>;
}
