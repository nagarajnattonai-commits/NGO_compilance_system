"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import IntegrationShell from "./integration-shell";
import { formatDateTime } from "@/i18n/format";
import { apiRequest, ApiError } from "@/lib/http";
import type { APIKey, Application, Webhook, IntegrationAccess } from "@/lib/integrations";

type Delivery={id:string;event_id:string;event_type:string;status:string;attempt_count:number;error_code:string;response_status:number|null};
type Usage={requests_today:number;items:Array<{id:string;route:string;status:number;duration_ms:number;created_at:string}>};
export default function DeveloperManagement({section="applications",platform=false}:{section?:string;platform?:boolean}){
 const t=useTranslations("Integrations");const [access,setAccess]=useState<IntegrationAccess|null>(null);
 const [applications,setApplications]=useState<Application[]>([]);const [keys,setKeys]=useState<APIKey[]>([]);const [hooks,setHooks]=useState<Webhook[]>([]);
 const [usage,setUsage]=useState<Usage>({requests_today:0,items:[]});const [deliveries,setDeliveries]=useState<Delivery[]>([]);const [documentation,setDocumentation]=useState<{endpoints:Record<string,string>;rate_limits:Record<string,number>}|null>(null);
 const [loading,setLoading]=useState(true);const [error,setError]=useState("");const [message,setMessage]=useState("");const [busy,setBusy]=useState(false);const [editing,setEditing]=useState(false);
 const [name,setName]=useState("");const [description,setDescription]=useState("");const [application,setApplication]=useState("");const [scopes,setScopes]=useState<string[]>(["organization.read"]);const [days,setDays]=useState(90);
 const [direction,setDirection]=useState("OUTBOUND");const [endpoint,setEndpoint]=useState("");const [events,setEvents]=useState<string[]>(["compliance.created"]);const [once,setOnce]=useState("");const [deliveryHook,setDeliveryHook]=useState("");
 const can=(permission:string)=>access?.permissions.includes(permission)??false;
 function report(problem:unknown){setError(t(problem instanceof ApiError&&problem.status===403?"errors.PERMISSION_DENIED":problem instanceof ApiError&&problem.status===429?"errors.RATE_LIMITED":"actionFailed"));}
 async function load(){setLoading(true);setError("");try{
  const current=await apiRequest<IntegrationAccess>("/integrations-management/access");setAccess(current);
  if(platform){if(!current.platform_allowed||!current.permissions.includes("integrations.platform.view")){setError(t("errors.PERMISSION_DENIED"));return;}if(section==="webhooks")setHooks(await apiRequest<Webhook[]>("/integrations-management/platform/webhooks"));
   else if(section==="usage")setUsage(await apiRequest<Usage>("/integrations-management/platform/developer/usage"));
   else if(section==="applications")setApplications(await apiRequest<Application[]>("/integrations-management/platform/developer/applications"));
   else if(section==="api-keys")setKeys(await apiRequest<APIKey[]>("/integrations-management/platform/developer/api-keys"));
   else setDocumentation(await apiRequest<typeof documentation>("/developer/documentation"));
   return;}
  if(!current.permissions.includes(section==="webhooks"?"integrations.tenant.view":"api_keys.view")){setError(t("errors.PERMISSION_DENIED"));return;}
  if(section==="webhooks")setHooks(await apiRequest<Webhook[]>("/developer/webhooks"));
  else if(section==="usage")setUsage(await apiRequest<Usage>("/developer/usage"));
  else if(section==="documentation"||section==="oauth")setDocumentation(await apiRequest<typeof documentation>("/developer/documentation"));
  else{const [apps,apiKeys]=await Promise.all([apiRequest<Application[]>("/developer/applications"),apiRequest<APIKey[]>("/developer/api-keys")]);setApplications(apps);setKeys(apiKeys);if(!application&&apps.length)setApplication(apps[0].id);}
 }catch(problem){report(problem);}finally{setLoading(false);}}
 useEffect(()=>{void load();},[section,platform]);
 // Only memory holds one-time values. Clear them when navigating away.
 useEffect(()=>{setOnce("");setEditing(false);setDeliveries([]);},[section,platform]);
 async function run(action:()=>Promise<unknown>){setBusy(true);setError("");setMessage("");try{await action();await load();setMessage(t("saved"));}catch(problem){report(problem);}finally{setBusy(false);}}
 async function submit(e:React.FormEvent){e.preventDefault();setOnce("");await run(async()=>{
  if(section==="applications")await apiRequest("/developer/applications","POST",{name,description});
  else if(section==="api-keys"){const result=await apiRequest<{key:string}>("/developer/api-keys","POST",{name,application_id:application,scopes,expires_in_days:days});setOnce(result.key);}
  else{const result=await apiRequest<{signing_secret:string}>("/developer/webhooks","POST",{name,direction,endpoint_url:direction==="OUTBOUND"?endpoint:"",event_types:events});setOnce(result.signing_secret);}
  setEditing(false);setName("");setDescription("");setEndpoint("");
 });}
 async function copy(){try{await navigator.clipboard.writeText(once);setMessage(t("copied"));}catch{setError(t("copyFailed"));}}
 const allowed=!!access&&(platform?access.platform_allowed&&can("integrations.platform.view"):can(section==="webhooks"?"integrations.tenant.view":"api_keys.view"));
 const createAllowed=!platform&&(section==="webhooks"?can("integrations.webhooks.manage")&&access?.entitlements.custom_webhooks&&access.secret_store_writable:can("api_keys.create")&&access?.entitlements.public_api);
 return <IntegrationShell scope={platform?"platform":"tenant"} developer={!platform||section!=="webhooks"} permissions={access?.permissions}><h1>{t(platform?"title":"developers")} · {t("sections."+(section==="api-keys"?"apiKeys":section))}</h1><p>{t(platform?"platformWebhookHelp":"developerHelp")}</p>
 {error&&<div role="alert">{error}<button className="button secondary" onClick={()=>void load()}>{t("retry")}</button></div>}{message&&<p role="status">{message}</p>}
 {loading?<p role="status">{t("loading")}</p>:allowed&&<>
 {once&&<section className="secret-once" aria-label={t("oneTimeSecret")}><h2>{t("oneTimeSecret")}</h2><p>{t("oneTimeHelp")}</p><code>{once}</code><div className="integration-actions"><button className="button" onClick={()=>void copy()}>{t("copy")}</button><button className="button secondary" onClick={()=>setOnce("")}>{t("dismiss")}</button></div></section>}
 {["applications","api-keys","webhooks"].includes(section)&&createAllowed&&<button className="button" disabled={busy||section==="api-keys"&&!applications.length} onClick={()=>{setEditing(true);setOnce("");setName("");}}>{t(section==="applications"?"addApplication":section==="api-keys"?"createKey":"addWebhook")}</button>}
 {!platform&&section!=="webhooks"&&!access?.entitlements.public_api&&<p>{t("apiDisabled")}</p>}
 {!platform&&section==="webhooks"&&!access?.secret_store_writable&&<p>{t("environmentHelp")}</p>}
 {editing&&<form className="integration-form" onSubmit={submit}><label>{t("displayName")}<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label>
 {section==="applications"?<label>{t("description")}<textarea maxLength={500} value={description} onChange={e=>setDescription(e.target.value)}/></label>
 :section==="api-keys"?<><label>{t("application")}<select aria-label={t("application")} required value={application} onChange={e=>setApplication(e.target.value)}>{applications.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><label>{t("expirationDays")}<input required type="number" min={1} max={365} value={days} onChange={e=>setDays(Number(e.target.value))}/></label><fieldset className="full"><legend>{t("scopes")}</legend>{access?.scopes.map(scope=><label className="check-label" key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={e=>setScopes(e.target.checked?[...scopes,scope]:scopes.filter(x=>x!==scope))}/><code>{scope}</code></label>)}</fieldset></>
 :<><label>{t("direction")}<select aria-label={t("direction")} value={direction} onChange={e=>setDirection(e.target.value)}><option value="OUTBOUND">{t("outbound")}</option><option value="INBOUND">{t("inbound")}</option></select></label>{direction==="OUTBOUND"&&<label className="full">{t("endpoint")}<input type="url" required maxLength={2000} value={endpoint} onChange={e=>setEndpoint(e.target.value)}/></label>}<fieldset className="full"><legend>{t("events")}</legend>{access?.event_types.map(event=><label className="check-label" key={event}><input type="checkbox" checked={events.includes(event)} onChange={e=>setEvents(e.target.checked?[...events,event]:events.filter(x=>x!==event))}/><code>{event}</code></label>)}</fieldset><p className="full">{t("webhookHelp")}</p></>}
 <div className="integration-actions full"><button className="button" disabled={busy||section==="api-keys"&&!scopes.length||section==="webhooks"&&!events.length}>{t("save")}</button><button type="button" className="button secondary" onClick={()=>setEditing(false)}>{t("cancel")}</button></div></form>}
 {section==="applications"?<div className="integration-grid">{applications.map(item=><article className="integration-card" key={item.id}><h2 title={item.name}>{item.name}</h2><p>{item.description}</p><code>{item.id}</code></article>)}</div>
 :section==="api-keys"?<div className="integration-grid">{keys.map(item=><article className="integration-card" key={item.id}><h2 title={item.name}>{item.name}</h2><code>{item.key_prefix}••••{item.key_suffix}</code><p><span className="integration-status">{t("keyStates."+item.status)}</span></p><p>{t("expires")}: {formatDateTime(item.expires_at)}</p><p>{t("lastUsed")}: {item.last_used_at?formatDateTime(item.last_used_at):t("never")}</p>{item.scopes.map(scope=><p key={scope}><code>{scope}</code></p>)}{!platform&&can("api_keys.revoke")&&item.status==="ACTIVE"&&<button className="button secondary" disabled={busy} onClick={()=>{if(window.confirm(t("revokeConfirm")))void run(()=>apiRequest("/developer/api-keys/"+item.id+"/revoke","POST"));}}>{t("revoke")}</button>}</article>)}</div>
 :section==="webhooks"?<><div className="integration-grid">{hooks.map(item=><article className="integration-card" key={item.id}><h2 title={item.name}>{item.name}</h2><p>{t(item.direction==="INBOUND"?"inbound":"outbound")} · {t(item.enabled?"enabled":"disabled")}</p><code>{item.inbound_path||item.endpoint_url}</code>{item.event_types.map(event=><p key={event}><code>{event}</code></p>)}{platform&&<p>{t("tenantId")}: {(item as Webhook&{tenant_id:string}).tenant_id}</p>}
 {!platform&&can("integrations.webhooks.manage")&&<div className="integration-actions"><button className="button secondary" disabled={busy} onClick={()=>void run(()=>apiRequest("/developer/webhooks/"+item.id,"PATCH",{enabled:!item.enabled}))}>{t(item.enabled?"disable":"enable")}</button>{item.direction==="OUTBOUND"&&item.enabled&&<button className="button secondary" disabled={busy} onClick={()=>void run(()=>apiRequest("/developer/webhooks/"+item.id+"/test","POST"))}>{t("testWebhook")}</button>}{can("integrations.credentials.rotate")&&<button className="button secondary" disabled={busy||!access?.secret_store_writable} onClick={()=>void run(async()=>{const result=await apiRequest<{signing_secret:string}>("/developer/webhooks/"+item.id+"/rotate","POST");setOnce(result.signing_secret);})}>{t("rotateSecret")}</button>}<button className="button secondary" disabled={busy||!access?.secret_store_writable} onClick={()=>{if(window.confirm(t("deleteConfirm")))void run(()=>apiRequest("/developer/webhooks/"+item.id,"DELETE"));}}>{t("delete")}</button></div>}
 {!platform&&can("integrations.logs.view")&&item.direction==="OUTBOUND"&&<button className="button secondary" disabled={busy} onClick={()=>void run(async()=>{setDeliveries(await apiRequest<Delivery[]>("/developer/webhooks/"+item.id+"/deliveries"));setDeliveryHook(item.name);})}>{t("deliveries")}</button>}
 </article>)}</div>{deliveryHook&&<section><h2>{t("deliveries")} · {deliveryHook}</h2><div className="integration-table"><table><thead><tr>{["requestId","events","status","attempts"].map(x=><th key={x}>{t(x)}</th>)}</tr></thead><tbody>{deliveries.map(x=><tr key={x.id}><td>{x.event_id}</td><td>{x.event_type}</td><td>{t("deliveryStates."+x.status)}{x.error_code&&<p>{t("errors."+x.error_code)}</p>}</td><td>{x.attempt_count}</td></tr>)}</tbody></table></div></section>}</>
 :section==="usage"?<><p>{t("requestsToday")}: {usage.requests_today}</p><div className="integration-table"><table><thead><tr>{["time","endpoint","status","duration"].map(x=><th key={x}>{t(x)}</th>)}</tr></thead><tbody>{usage.items.map(x=><tr key={x.id}><td>{formatDateTime(x.created_at)}</td><td><code>{x.route}</code></td><td>{x.status}</td><td>{x.duration_ms} ms</td></tr>)}</tbody></table></div></>
 :section==="oauth"?<section className="integration-card"><h2>{t("sections.oauth")}</h2><p>{t("oauthDeferred")}</p></section>
 :<section className="integration-card"><h2>{t("sections.documentation")}</h2><p>{t("documentationHelp")}</p><code>Authorization: Bearer &lt;API_KEY&gt;</code>{documentation&&Object.entries(documentation.endpoints).map(([path,scope])=><p key={path}><code>GET /api/v1/public{path}</code> · <code>{scope}</code></p>)}<p>{t("rateLimitHelp")}</p><p>{t("webhookHelp")}</p><code>sha256=HMAC_SHA256(secret, timestamp + "." + exact_body)</code><p>{t("webhookDedup")}</p></section>}
 {["applications","api-keys","webhooks"].includes(section)&&!(section==="applications"?applications.length:section==="api-keys"?keys.length:hooks.length)&&<p>{t("emptyRecords")}</p>}
 </>}</IntegrationShell>;
}
