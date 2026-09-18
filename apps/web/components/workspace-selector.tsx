"use client";
import {useEffect,useState} from "react";
import {useTranslations} from "next-intl";
import {apiRequest} from "@/lib/http";
export default function WorkspaceSelector(){
 const t=useTranslations("Authentication");const [items,setItems]=useState<Array<{id:string;name:string;role:string}>>([]);const [error,setError]=useState("");const [busy,setBusy]=useState(false);
 useEffect(()=>{apiRequest<Array<{id:string;name:string;role:string}>>("/auth/workspaces").then(setItems).catch(()=>setError(t("errors.unavailable")));},[t]);
 async function choose(id:string){if(busy)return;setBusy(true);setError("");try{await apiRequest("/auth/workspace","POST",{tenant_id:id});window.location.assign("/dashboard");}catch{setError(t("errors.denied"));setBusy(false);}}
 return <section className="account-content"><h1>{t("selectWorkspace")}</h1><p>{t("workspaceDescription")}</p>{error&&<div role="alert">{error}</div>}<div className="account-grid">{items.map(item=><button key={item.id} className="button secondary" disabled={busy} onClick={()=>void choose(item.id)}>{item.name}</button>)}</div></section>;
}
