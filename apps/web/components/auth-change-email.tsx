"use client";
import {useState} from "react";
import Link from "next/link";
import {useTranslations} from "next-intl";
import {apiRequest} from "@/lib/http";
import AuthPasswordInput from "./auth-password-input";
import PublicLocaleSwitcher from "./public-locale-switcher";
import "@/app/auth-experience.css";
export default function AuthChangeEmail(){
 const t=useTranslations("Authentication");const [email,setEmail]=useState("");const [newEmail,setNewEmail]=useState("");const [password,setPassword]=useState("");const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 async function submit(e:React.FormEvent){e.preventDefault();if(busy)return;setBusy(true);setError("");try{await apiRequest("/auth/change-unverified-email","POST",{email,new_email:newEmail,password});setPassword("");window.location.assign("/verify-email#email="+encodeURIComponent(newEmail));}catch{setError(t("errors.validation"));setBusy(false);}}
 return <main className="auth-shell auth-experience auth-user"><div className="auth-theme-toggle"><PublicLocaleSwitcher compact/></div><section className="auth-card"><h1>{t("changeEmail")}</h1><p className="auth-description">{t("changeEmailDescription")}</p>{error&&<div role="alert" className="auth-alert error">{error}</div>}<form className="auth-form" onSubmit={submit}><fieldset disabled={busy}><label>{t("email")}<input type="email" required autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)}/></label><label>{t("newEmail")}<input type="email" required autoComplete="email" value={newEmail} onChange={e=>setNewEmail(e.target.value)}/></label><AuthPasswordInput value={password} onChange={setPassword}/><button className="auth-submit">{busy?t("working"):t("changeEmail")}</button></fieldset></form><Link href="/verify-email">{t("verificationPage")}</Link></section></main>;
}
