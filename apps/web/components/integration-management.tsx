"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { formatDateTime } from "@/i18n/format";
import { apiRequest, ApiError } from "@/lib/http";
import IntegrationShell from "./integration-shell";
import DeveloperManagement from "./developer-management";
import { connectionStates, type Connection, type Provider, type IntegrationAccess, type IntegrationScope, type OperationLog, type TenantIntegration } from "@/lib/integrations";

export default function IntegrationManagement({scope,section="connections"}:{scope:IntegrationScope;section?:string}) {
 const t=useTranslations("Integrations");
 const [access,setAccess]=useState<IntegrationAccess|null>(null);
 const [connections,setConnections]=useState<Connection[]>([]);
 const [providers,setProviders]=useState<Provider[]>([]);
 const [logs,setLogs]=useState<OperationLog[]>([]);
 const [tenants,setTenants]=useState<TenantIntegration[]>([]);
 const [summary,setSummary]=useState<Record<string,number>>({});const [metrics,setMetrics]=useState<Array<{status:string;count:number;average_duration_ms:number}>>([]);
 const [audits,setAudits]=useState<Array<{id:string;action:string;actor_name:string;created_at:string}>>([]);
 const [loading,setLoading]=useState(true);const [error,setError]=useState("");const [message,setMessage]=useState("");const [busy,setBusy]=useState(false);
 const [page,setPage]=useState(1);const [total,setTotal]=useState(0);
 const [category,setCategory]=useState("");const [status,setStatus]=useState("");const [environment,setEnvironment]=useState("");const [tenantFilter,setTenantFilter]=useState("");
 const [editor,setEditor]=useState<Connection|"new"|null>(null);const [credential,setCredential]=useState<Connection|null>(null);
 const [providerKey,setProviderKey]=useState("");const [name,setName]=useState("");const [values,setValues]=useState<Record<string,string|number>>({});const [formEnvironment,setFormEnvironment]=useState("SANDBOX");const [fallback,setFallback]=useState(false);const [secret,setSecret]=useState("");
 const can=(permission:string)=>access?.permissions.includes(permission)??false;
 const path="/integrations-management/"+scope;
 const manageable=can("integrations."+scope+".manage");
 const provider=providers.find(item=>item.key===providerKey);
 function report(problem:unknown){setError(t(problem instanceof ApiError&&problem.status===403?"errors.PERMISSION_DENIED":problem instanceof ApiError&&problem.status===429?"errors.RATE_LIMITED":"actionFailed"));}
 async function load(){
  setLoading(true);setError("");
  try{
   const current=await apiRequest<IntegrationAccess>("/integrations-management/access");setAccess(current);
   if(!current.permissions.includes("integrations."+scope+".view")||(scope==="platform"&&!current.platform_allowed)){setError(t("errors.PERMISSION_DENIED"));return;}
   if((section==="logs"||section==="audit")&&!current.permissions.includes("integrations.logs.view")||section==="health"&&!current.permissions.includes("integrations.health.view")){setError(t("errors.PERMISSION_DENIED"));return;}
   if(section==="webhooks")return;
   const query=new URLSearchParams({page:String(page),category,status,environment,tenant_filter:tenantFilter});
   const [list,registry]=await Promise.all([apiRequest<{items:Connection[];total:number}>(path+"/connections?"+query),apiRequest<Provider[]>(path+"/providers")]);
   setConnections(list.items);setTotal(list.total);setProviders(registry);
   if(section==="health"){const health=await apiRequest<{summary:Record<string,number>;metrics:typeof metrics}>(path+"/health");setSummary(health.summary);setMetrics(health.metrics||[]);}
   if(section==="logs"){const result=await apiRequest<{items:OperationLog[];total:number}>(path+"/logs?page="+page);setLogs(result.items);setTotal(result.total);}
   if(section==="tenants")setTenants(await apiRequest<TenantIntegration[]>("/integrations-management/platform/tenants"));
   if(section==="audit")setAudits(await apiRequest<typeof audits>(path+"/audit"));
  }catch(problem){report(problem);}finally{setLoading(false);}
 }
 useEffect(()=>{void load();},[scope,section,page,category,status,environment,tenantFilter]);
 async function run(action:()=>Promise<unknown>,success="saved"){setBusy(true);setError("");setMessage("");try{const result=await action();await load();if(result&&typeof result==="object"&&"success" in result&&!result.success&&"error_code" in result){setError(t("errors."+result.error_code));}else setMessage(t(success));}catch(problem){report(problem);}finally{setBusy(false);}}
 function defaults(item:Provider|undefined){return Object.fromEntries(Object.entries(item?.configuration_schema.properties||{}).map(([field,schema])=>[field,schema.default??""]));}
 function open(connection:Connection|"new"){
  const key=connection==="new"?providers.find(item=>item.enabled)?.key||"":connection.provider_key;setProviderKey(key);setName(connection==="new"?"":connection.display_name);setValues(connection==="new"?defaults(providers.find(item=>item.key===key)):connection.configuration);
  setFormEnvironment(connection==="new"?"SANDBOX":connection.environment);setFallback(connection==="new"?false:connection.fallback_allowed);setEditor(connection);setCredential(null);setError("");
 }
 async function save(event:React.FormEvent){event.preventDefault();const body={display_name:name,environment:formEnvironment,configuration:values,fallback_allowed:fallback};
  await run(async()=>{await apiRequest(path+"/connections"+(editor==="new"?"":"/"+(editor as Connection).id),editor==="new"?"POST":"PATCH",editor==="new"?{...body,provider_key:providerKey}:body);setEditor(null);});
 }
 function statusLabel(value:string){return t("statuses."+value);}
 if(section==="webhooks")return <DeveloperManagement section="webhooks" platform={scope==="platform"}/>;
 return <IntegrationShell scope={scope} permissions={access?.permissions}><h1>{t("title")} · {t("sections."+section)}</h1><p>{t(scope==="platform"?"platformHelp":"tenantHelp")}</p>
 {error&&<div role="alert">{error}<button className="button secondary" onClick={()=>void load()}>{t("retry")}</button></div>}{message&&<p role="status">{message}</p>}
 {loading?<p role="status">{t("loading")}</p>:access&&(scope!=="platform"||access.platform_allowed)&&can("integrations."+scope+".view")&&<>
 {section==="health"&&<section><p>{t("healthRecorded")}</p><div className="integration-grid">{Object.entries(summary).map(([key,count])=><article className="integration-card" key={key}><h2>{t("healthStates."+key)}</h2><p>{count}</p></article>)}</div><h2>{t("metricsToday")}</h2><div className="integration-grid">{metrics.map(row=><article className="integration-card" key={row.status}><h3>{t("deliveryStates."+row.status)}</h3><p>{t("operationsCount")}: {row.count}</p><p>{t("averageLatency")}: {row.average_duration_ms} ms</p></article>)}</div></section>}
 {(section==="connections"||section==="credentials"||section==="health")&&<div className="integration-toolbar">
 {manageable&&section==="connections"&&<button className="button" disabled={busy||!providers.some(p=>p.enabled)} onClick={()=>open("new")}>{t("addConnection")}</button>}
 <label>{t("category")}<select aria-label={t("category")} value={category} onChange={e=>{setCategory(e.target.value);setPage(1);}}><option value="">{t("all")}</option>{access.categories.map(x=><option key={x} value={x}>{t("categories."+x)}</option>)}</select></label>
 <label>{t("status")}<select aria-label={t("status")} value={status} onChange={e=>{setStatus(e.target.value);setPage(1);}}><option value="">{t("all")}</option>{connectionStates.map(x=><option key={x} value={x}>{statusLabel(x)}</option>)}</select></label>
 <label>{t("environment")}<select aria-label={t("environment")} value={environment} onChange={e=>{setEnvironment(e.target.value);setPage(1);}}><option value="">{t("all")}</option>{["SANDBOX","PRODUCTION"].map(x=><option key={x} value={x}>{t("environments."+x)}</option>)}</select></label>
 {scope==="platform"&&<label>{t("tenantId")}<input value={tenantFilter} onChange={e=>{setTenantFilter(e.target.value);setPage(1);}}/></label>}
 </div>}
 {editor&&<form className="integration-form" onSubmit={save}><h2 className="full">{t(editor==="new"?"addConnection":"configure")}</h2>
 <label>{t("provider")}<select aria-label={t("provider")} value={providerKey} disabled={editor!=="new"} onChange={e=>{setProviderKey(e.target.value);setValues(defaults(providers.find(p=>p.key===e.target.value)));}}>{providers.filter(p=>p.enabled).map(p=><option key={p.key} value={p.key}>{t("providers."+p.key)}</option>)}</select></label>
 <label>{t("displayName")}<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label>
 <label>{t("environment")}<select aria-label={t("environment")} value={formEnvironment} onChange={e=>setFormEnvironment(e.target.value)}>{["SANDBOX","PRODUCTION"].map(x=><option key={x} value={x}>{t("environments."+x)}</option>)}</select></label>
 {provider&&Object.entries(provider.configuration_schema.properties).map(([field,schema])=><label key={field}>{t("fields."+field)}<input required={provider.configuration_schema.required?.includes(field)} aria-label={t("fields."+field)} type={schema.type==="integer"?"number":"text"} min={schema.minimum} max={schema.maximum} maxLength={schema.maxLength} value={values[field]??""} onChange={e=>setValues({...values,[field]:schema.type==="integer"?Number(e.target.value):e.target.value})}/></label>)}
 {scope==="platform"&&<label className="check-label full"><input type="checkbox" checked={fallback} onChange={e=>setFallback(e.target.checked)}/>{t("allowFallback")}</label>}
 <p className="full">{t("configurationHelp")}</p><div className="integration-actions full"><button className="button" disabled={busy}>{t("save")}</button><button type="button" className="button secondary" disabled={busy} onClick={()=>setEditor(null)}>{t("cancel")}</button></div></form>}
 {credential&&<form className="integration-form" onSubmit={async e=>{e.preventDefault();try{await run(async()=>{await apiRequest(path+"/connections/"+credential.id+"/credential","PUT",{secret});setCredential(null);});}finally{setSecret("");}}}><h2 className="full">{t("replaceCredential")} · {credential.display_name}</h2><p className="full">{t("neverRetrieve")}</p><label className="full">{t("secret")}<input type="password" aria-label={t("secret")} required maxLength={16000} autoComplete="new-password" value={secret} onChange={e=>setSecret(e.target.value)}/></label><div className="integration-actions full"><button className="button" disabled={busy}>{t("replaceCredential")}</button><button type="button" className="button secondary" onClick={()=>{setSecret("");setCredential(null);}}>{t("cancel")}</button></div></form>}
 {section==="providers"?<div className="integration-grid">{providers.map(item=><article className="integration-card" key={item.key}><h2>{t("providers."+item.key)}</h2><p>{t("categories."+item.category)}</p><p>{t(item.enabled?"enabled":"disabled")}</p><code>{item.entitlement_key}</code>{scope==="platform"&&manageable&&<div className="integration-actions"><button className="button secondary" disabled={busy} onClick={()=>void run(()=>apiRequest(path+"/providers/"+item.key,"PUT",{enabled:!item.enabled}))}>{t(item.enabled?"disable":"enable")}</button></div>}</article>)}</div>
 :section==="logs"?<div className="integration-table"><table><thead><tr>{["time","provider","operation","status","duration","requestId"].map(x=><th key={x}>{t(x)}</th>)}</tr></thead><tbody>{logs.map(x=><tr key={x.id}><td><time dateTime={formatDateTime(x.created_at)}>{formatDateTime(x.created_at)}</time></td><td>{x.provider_key}</td><td>{t("operations."+x.operation.replace(".","_"))}</td><td>{t("deliveryStates."+x.status)}{x.error_code&&<p>{t("errors."+x.error_code)}</p>}</td><td>{x.duration_ms} ms</td><td><details><summary>{x.id}</summary><p>{t("tenantId")}: {x.tenant_id||t("platform")}</p><p>{t("retries")}: {x.retry_count}</p><time>{formatDateTime(x.completed_at)}</time></details></td></tr>)}</tbody></table></div>
 :section==="tenants"?<div className="integration-grid">{tenants.map(tenant=><article className="integration-card" key={tenant.id}><h2 title={tenant.name}>{tenant.name}</h2><code>{tenant.id}</code>{Object.entries(tenant.entitlements).map(([key,enabled])=><label className="check-label" key={key}><input type="checkbox" checked={enabled} disabled={!manageable||busy} onChange={e=>void run(()=>apiRequest(path+"/tenants/"+tenant.id+"/entitlement","PUT",{feature_key:key,enabled:e.target.checked}))}/>{t("entitlements."+key)}</label>)}</article>)}</div>
 :section==="audit"?<div className="integration-table"><table><thead><tr><th>{t("time")}</th><th>{t("actor")}</th><th>{t("operation")}</th></tr></thead><tbody>{audits.map(x=><tr key={x.id}><td>{formatDateTime(x.created_at)}</td><td>{x.actor_name}</td><td>{x.action}</td></tr>)}</tbody></table></div>
 :<div className="integration-grid">{connections.map(connection=><article className="integration-card" key={connection.id}><h2 title={connection.display_name}>{connection.display_name}</h2><p>{t("providers."+connection.provider_key)} · {t("environments."+connection.environment)}</p><p>{t("scope")}: {t(connection.scope==="PLATFORM"?"platform":"tenant")} {connection.tenant_id&&<code>{connection.tenant_id}</code>}</p><span className="integration-status">{statusLabel(connection.status)}</span><p>{t("health")}: {t("healthStates."+connection.health)}</p><p>{t("lastTested")}: {connection.last_tested_at?formatDateTime(connection.last_tested_at):t("never")}</p><p>{t("failures")}: {connection.failure_count}</p>{connection.error_code&&<p>{t("errors."+connection.error_code)}</p>}{connection.credential_suffix&&<p>{t("credential")}: ••••{connection.credential_suffix}</p>}
 {manageable&&(scope==="tenant"||connection.scope==="PLATFORM")&&<div className="integration-actions"><button className="button secondary" disabled={busy} onClick={()=>open(connection)}>{t("configure")}</button>{can("integrations.credentials.rotate")&&<button className="button secondary" disabled={busy||!access.secret_store_writable} onClick={()=>{setCredential(connection);setEditor(null);setSecret("");}}>{t("replaceCredential")}</button>}<button className="button secondary" disabled={busy} onClick={()=>void run(async()=>{const result=await apiRequest<{success:boolean;error_code:string}>(path+"/connections/"+connection.id+"/test","POST");return result;},"testComplete")}>{t("testConnection")}</button>{connection.status==="CONFIGURED"&&connection.last_success_at&&<button className="button" disabled={busy} onClick={()=>void run(()=>apiRequest(path+"/connections/"+connection.id+"/activate","POST"))}>{t("activate")}</button>}<button className="button secondary" disabled={busy} onClick={()=>void run(()=>apiRequest(path+"/connections/"+connection.id+"/disconnect","POST"))}>{t("disconnect")}</button></div>}
 </article>)}</div>}
 {!connections.length&&["connections","credentials","health"].includes(section)&&<p>{t("emptyConnections")}</p>}{!access.secret_store_writable&&<p>{t("environmentHelp")}</p>}
 {["connections","credentials","health","logs"].includes(section)&&<div className="integration-actions"><button className="button secondary" disabled={page<=1||busy} onClick={()=>setPage(page-1)}>{t("previous")}</button><span>{page}</span><button className="button secondary" disabled={page*25>=total||busy} onClick={()=>setPage(page+1)}>{t("next")}</button></div>}
 </>}</IntegrationShell>;
}
