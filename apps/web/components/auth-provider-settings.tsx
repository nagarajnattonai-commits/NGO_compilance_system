"use client";
import {useEffect,useState} from "react";
import {useTranslations} from "next-intl";
import Link from "next/link";
import {apiRequest} from "@/lib/http";
type Policy={client_id:string;user_enabled:boolean;signup_enabled:boolean;admin_enabled:boolean;credential_configured:boolean;redirect_uri:string;secret_store_writable:boolean};
export default function AuthProviderSettings(){
 const t=useTranslations("Authentication");const [policy,setPolicy]=useState<Policy|null>(null);const [secret,setSecret]=useState("");const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [success,setSuccess]=useState("");
 useEffect(()=>{apiRequest<Policy>("/admin/auth/providers/google").then(setPolicy).catch(()=>setError(t("errors.unavailable")));},[t]);
 async function save(e:React.FormEvent){e.preventDefault();if(!policy||busy)return;setBusy(true);setError("");setSuccess("");try{setPolicy(await apiRequest<Policy>("/admin/auth/providers/google","PUT",{client_id:policy.client_id,user_enabled:policy.user_enabled,signup_enabled:policy.signup_enabled,admin_enabled:policy.admin_enabled,...(secret?{secret}:{})}));setSuccess(t("saved"));}catch{setError(t("errors.unavailable"));}finally{setSecret("");setBusy(false);}}
 return <main className="account-content"><Link href="/admin">{t("returnDashboard")}</Link><h1>{t("providerSettings")}</h1>{error&&<div role="alert" className="auth-alert error">{error}</div>}{success&&<div role="status">{success}</div>}{policy&&<form className="auth-form" onSubmit={save}><fieldset disabled={busy}><label>{t("clientId")}<input value={policy.client_id} onChange={e=>setPolicy({...policy,client_id:e.target.value})}/></label><label>{t("clientSecret")}<input type="password" autoComplete="off" disabled={!policy.secret_store_writable} value={secret} onChange={e=>setSecret(e.target.value)}/></label><p><code>{policy.redirect_uri}</code></p>{(["user_enabled","signup_enabled","admin_enabled"] as const).map((key,index)=><label key={key} className="auth-checkbox"><input type="checkbox" checked={policy[key]} onChange={e=>setPolicy({...policy,[key]:e.target.checked})}/>{t(["userGoogle","signupGoogle","adminGoogle"][index])}</label>)}<button className="button primary">{t("save")}</button></fieldset></form>}</main>;
}
