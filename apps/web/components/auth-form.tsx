"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {ArrowLeft,ShieldCheck,LockKeyhole,ChevronRight,CheckCircle2} from "lucide-react";
import {useTranslations} from "next-intl";
import {apiRequest,ApiError} from "@/lib/http";
import {normalizeEmail,validateEmail,validateNewPassword} from "@/lib/auth-validation";
import {BrandLogo,useTenantBrand} from "@/branding/client";
import PublicLocaleSwitcher from "./public-locale-switcher";
import ThemeToggle from "./theme-toggle";
import "@/app/auth-experience.css";
import AuthPasswordInput from "./auth-password-input";

export type AuthMode="login"|"admin-login"|"signup"|"forgot-password"|"admin-forgot-password"|"reset-password"|"admin-reset-password"|"accept-invitation"|"verify-email"|"google-complete"|"google-link";
type Options={terms_url:string;privacy_url:string;organization_types:string[];providers:{google:{user:boolean;signup:boolean;admin:boolean}}};
export default function AuthForm({mode}:{mode:AuthMode}){
 const t=useTranslations("Authentication");const brand=useTenantBrand();
 const admin=mode.startsWith("admin-");const login=mode==="login"||mode==="admin-login";
 const forgot=mode.endsWith("forgot-password");const reset=mode.endsWith("reset-password");
 const invitation=mode==="accept-invitation";const signup=mode==="signup";const verify=mode==="verify-email";
 const tokenPage=reset||invitation||verify||mode==="google-complete"||mode==="google-link";
 const [email,setEmail]=useState("");const [password,setPassword]=useState("");const [confirm,setConfirm]=useState("");
 const [name,setName]=useState("");const [workspace,setWorkspace]=useState("");const [phone,setPhone]=useState("");
 const [organizationType,setOrganizationType]=useState("");const [terms,setTerms]=useState(false);
 const [step,setStep]=useState(1);const [token,setToken]=useState("");const [googleTicket,setGoogleTicket]=useState("");
 const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [success,setSuccess]=useState("");
 const [attempted,setAttempted]=useState(false);const [options,setOptions]=useState<Options|null>(null);
 const [existingInvitation,setExistingInvitation]=useState(false);
 const [verificationNeeded,setVerificationNeeded]=useState(false);
 useEffect(()=>{
  function capture(){
   const query=new URLSearchParams(window.location.search);const fragment=new URLSearchParams(window.location.hash.slice(1));
   const incoming=fragment.get("token")||"";
   if(tokenPage&&incoming){
    setToken(incoming);setSuccess("");setError("");setPassword("");setConfirm("");setAttempted(false);
    if(invitation)apiRequest<{existing_account:boolean}>("/auth/invitation-info","POST",{token:incoming}).then(value=>setExistingInvitation(value.existing_account)).catch(()=>setError(t("errors.link")));
   }
   if(signup&&fragment.get("google"))setGoogleTicket(fragment.get("google")||"");
   if(verify&&fragment.get("email"))setEmail(fragment.get("email")||"");
   if(fragment.toString())window.history.replaceState(null,"",window.location.pathname+window.location.search);
   if(query.has("expired"))setError(t("errors.expired"));
   if(query.has("oauth"))setError(t("errors.google"));
  }
  capture();window.addEventListener("hashchange",capture);
  apiRequest<Options>("/auth/options").then(setOptions).catch(()=>setOptions(null));
  return ()=>window.removeEventListener("hashchange",capture);
 },[mode,tokenPage,signup,verify,invitation,t]);
 function passwordError(value:string){
  if(login||mode==="google-link"||existingInvitation)return value?"":t("validation.required");
  const invalid=validateNewPassword(value);
  if(!invalid)return "";
  if(value.length<12)return t("validation.length");
  if(value.length>128)return t("validation.maximum");
  if(value!==value.trim()||/[\u0000-\u001f\u007f]/.test(value))return t("validation.spacing");
  return t("validation.predictable");
 }
 const emailError=(!tokenPage&&!(signup&&googleTicket))?(!email.trim()?t("validation.required"):validateEmail(email)?t("validation.email"):""):"";
 const pwError=(!forgot&&!verify&&mode!=="google-complete"&&!googleTicket)?passwordError(password):"";
 const confirmError=(signup||reset||invitation&&!existingInvitation)&&!googleTicket&&password!==confirm?t("validation.confirm"):"";
 const accountError=signup&&name.trim().length<2?t("validation.name"):"";
 const organizationError=signup&&workspace.trim().length<2?t("validation.organization"):"";
 const signin=admin?"/admin/login":"/login";
 function failure(error:unknown){
  const status=error instanceof ApiError?error.status:0;
  if(error instanceof Error&&error.message==="EMAIL_NOT_VERIFIED"){setVerificationNeeded(true);return t("errors.unverified");}
  if(status===429)return t("errors.rate");
  if(status===401)return t("errors.credentials");
  if(status===403)return t(admin?"errors.admin":"errors.denied");
  if(status===400)return t("errors.link");
  if(status===409)return t("errors.duplicate");
  if(status===422)return t("errors.validation");
  return t(status>=500?"errors.unavailable":"errors.network");
 }
 async function enterWorkspace(){
  const memberships=await apiRequest<Array<{id:string}>>("/auth/workspaces");
  window.location.assign(admin?"/admin":memberships.length>1?"/select-workspace":"/dashboard");
 }
 async function submit(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();if(busy)return;setAttempted(true);setError("");setSuccess("");
  if(emailError||pwError||confirmError||accountError){setError(t("errors.fields"));return;}
  if(signup&&step===1){setStep(2);setAttempted(false);return;}
  if(signup&&(organizationError||!organizationType||!terms)){setError(t("errors.fields"));return;}
  if(tokenPage&&!token){setError(t("errors.link"));return;}
  setBusy(true);
  try{
   if(login){const data=new FormData(event.currentTarget);await apiRequest(admin?"/admin/auth/login":"/auth/login","POST",{email:normalizeEmail(email),password,remember:data.has("remember")});setPassword("");await enterWorkspace();}
   else if(signup){
    const fields={name:name.trim(),workspace_name:workspace.trim(),organization_type:organizationType,phone,terms_accepted:terms};
    if(googleTicket){await apiRequest("/auth/google/signup","POST",{...fields,token:googleTicket});setGoogleTicket("");await enterWorkspace();}
    else{await apiRequest("/auth/signup","POST",{...fields,email:normalizeEmail(email),password,verify_email:true});setPassword("");setConfirm("");window.location.assign("/verify-email#email="+encodeURIComponent(normalizeEmail(email)));}
   }else if(forgot){await apiRequest(admin?"/admin/auth/forgot-password":"/auth/forgot-password","POST",{email:normalizeEmail(email)});setSuccess(t("resetSent"));}
   else if(verify){await apiRequest("/auth/verify-email","POST",{token});setToken("");setSuccess(t("verified"));}
   else if(mode==="google-complete"){await apiRequest("/auth/google/complete","POST",{token});setToken("");await enterWorkspace();}
   else if(mode==="google-link"){await apiRequest("/auth/google/link","POST",{token,password});setToken("");setPassword("");await enterWorkspace();}
   else if(invitation&&existingInvitation){await apiRequest("/auth/accept-workspace-invitation","POST",{token,password});setToken("");setPassword("");await enterWorkspace();}
   else{await apiRequest(invitation?"/auth/accept-invitation":admin?"/admin/auth/reset-password":"/auth/reset-password","POST",{token,password});setToken("");setPassword("");setConfirm("");setSuccess(t(invitation?"invitationSuccess":"resetSuccess"));}
  }catch(error){setError(failure(error));}finally{setBusy(false);}
 }
 async function resend(){
  if(busy)return;setError("");setSuccess("");
  if(validateEmail(email)||!email){setError(t("validation.email"));return;}
  setBusy(true);
  try{await apiRequest("/auth/resend-verification","POST",{email:normalizeEmail(email)});setSuccess(t("verificationSent"));}
  catch(error){setError(failure(error));}finally{setBusy(false);}
 }
 const key=admin?mode.slice(6):mode;
 const titleKey=admin&&login?"adminLogin":key==="google-complete"?"complete":key==="google-link"?"linkGoogle":key.replaceAll("-","_");
 const googleAvailable=options?.providers.google[admin?"admin":signup?"signup":"user"];
 const showGoogle=(login||signup)&&!googleTicket;
 const masked=email?email.slice(0,1)+"***@"+email.split("@")[1]:"";
 const finished=Boolean(success)&&(reset||invitation||verify&&success===t("verified"));
 return <main className={"auth-shell auth-experience "+(admin?"auth-admin":"auth-user")} style={!admin&&brand.enabled&&brand.login_background==="IMAGE"&&brand.assets.LOGIN_BACKGROUND?{backgroundImage:"url("+JSON.stringify(brand.assets.LOGIN_BACKGROUND)+")",backgroundSize:"cover",backgroundPosition:"center"}:undefined}>
  <div className="auth-theme-toggle"><PublicLocaleSwitcher compact/><ThemeToggle variant="icon"/></div>
  <div className={"auth-layout "+((login&&!admin||signup)?"auth-layout-product":"")}>
   {(login&&!admin||signup)&&<aside className="auth-product-panel">
    <ShieldCheck size={34} aria-hidden="true"/><h2>{brand.enabled?brand.product_name:t("productTitle")}</h2>
    <p>{brand.enabled?brand.tagline:t("productDescription")}</p>
    <ul><li>{t("benefits.compliance")}</li><li>{t("benefits.evidence")}</li><li>{t("benefits.team")}</li></ul>
   </aside>}
   <section className="auth-card" aria-labelledby="auth-title">
    <Link href="/" className="auth-logo" aria-label={admin?"Setu NGO":brand.product_name}>{!admin&&brand.enabled?<BrandLogo variant="login"/>:<ShieldCheck size={30}/>}</Link>
    <p className="auth-brand" title={admin?"Setu NGO":brand.product_name}>{admin?"Setu NGO":brand.product_name}</p>
    {admin&&<p className="auth-admin-label"><LockKeyhole size={14}/>{t("platformAdministration")}</p>}
    <h1 id="auth-title">{t("titles."+titleKey)}</h1><p className="auth-description">{t("descriptions."+titleKey)}</p>
    {error&&<div className="auth-alert error" role="alert">{error}</div>}
    {success&&<div className="auth-alert success" role="status"><CheckCircle2 size={16}/>{success}</div>}
    {showGoogle&&<><button type="button" className="google-auth-button" disabled={busy||!googleAvailable} onClick={()=>{setBusy(true);window.location.assign("/api/v1/auth/google?audience="+(admin?"admin":"user")+"&intent="+(signup?"signup":"login"));}}>
     <img src="/google-g.png" width="20" height="20" alt="" aria-hidden="true"/>{t("google")}</button>
     {!googleAvailable&&<p className="auth-provider-notice">{t("googleUnavailable")}</p>}
     <div className="auth-divider"><span>{t("orEmail")}</span></div></>}
    {verify&&!token&&!finished?<div className="auth-verification">
      {masked&&<p>{t("verificationAddress",{email:masked})}</p>}
      <label>{t("email")}<input type="email" autoComplete="email" value={email} onChange={event=>setEmail(event.target.value)}/></label>
      <button className="button primary" disabled={busy} onClick={()=>void resend()}>{busy?t("sending"):t("resend")}</button>
      <Link href="/auth/change-email">{t("changeEmail")}</Link>
     </div>:!finished&&<form className="auth-form" noValidate onSubmit={submit} aria-busy={busy}>
      <fieldset disabled={busy}>
       {signup&&<ol className="auth-steps" aria-label={t("signupSteps")}><li aria-current={step===1?"step":undefined}>{t("yourAccount")}</li><li aria-current={step===2?"step":undefined}>{t("organization")}</li></ol>}
       {signup&&step===1&&<label>{t("fullName")}<input aria-label={t("fullName")} autoComplete="name" value={name} maxLength={120} onChange={e=>setName(e.target.value)} aria-invalid={attempted&&!!accountError}/>{attempted&&accountError&&<small className="field-error">{accountError}</small>}</label>}
       {!tokenPage&&!(signup&&(step===2||googleTicket))&&<label>{t("email")}<input aria-label={t("email")} type="email" autoComplete="username" inputMode="email" autoCapitalize="none" spellCheck={false} value={email} maxLength={200} onChange={e=>setEmail(e.target.value)} aria-invalid={attempted&&!!emailError} aria-describedby={attempted&&emailError?"auth-email-error":undefined}/>{attempted&&emailError&&<small id="auth-email-error" className="field-error">{emailError}</small>}</label>}
       {!forgot&&!verify&&mode!=="google-complete"&&!(signup&&(step===2||googleTicket))&&<AuthPasswordInput value={password} onChange={setPassword} newPassword={signup||reset||invitation&&!existingInvitation} error={attempted?pwError:""}/>}
       {(signup&&step===1||reset||invitation&&!existingInvitation)&&!googleTicket&&<AuthPasswordInput value={confirm} onChange={setConfirm} confirm error={attempted?confirmError:""}/>}
       {signup&&step===2&&<>
        <label>{t("organizationName")}<input aria-label={t("organizationName")} autoComplete="organization" value={workspace} maxLength={160} onChange={e=>setWorkspace(e.target.value)} aria-invalid={attempted&&!!organizationError}/>{attempted&&organizationError&&<small className="field-error">{organizationError}</small>}</label>
        <label>{t("organizationType")}<select aria-label={t("organizationType")} value={organizationType} onChange={e=>setOrganizationType(e.target.value)} aria-invalid={attempted&&!organizationType}><option value="">{t("chooseType")}</option>{options?.organization_types.map(type=><option key={type} value={type}>{t("types."+type.replaceAll(" ","_"))}</option>)}</select></label>
        <label>{t("phone")}<span className="optional">{t("optional")}</span><input type="tel" autoComplete="tel" value={phone} maxLength={30} onChange={e=>setPhone(e.target.value)}/></label>
        <label className="auth-checkbox"><input type="checkbox" checked={terms} onChange={e=>setTerms(e.target.checked)}/><span>{t("terms")} {(brand.terms_url||options?.terms_url)&&<a href={brand.terms_url||options?.terms_url}>{t("termsLink")}</a>} {(brand.privacy_url||options?.privacy_url)&&<a href={brand.privacy_url||options?.privacy_url}>{t("privacyLink")}</a>}</span></label>
        {attempted&&!terms&&<small className="field-error">{t("validation.terms")}</small>}
       </>}
       {login&&<div className="auth-options"><label className="auth-checkbox"><input type="checkbox" name="remember"/>{t("remember")}</label><Link href={admin?"/admin/forgot-password":"/forgot-password"}>{t("forgot")}</Link></div>}
       <button className="auth-submit" type="submit">{busy?t(login?"signingIn":signup?"creating":"working"):signup&&step===1?t("next"):t(login?admin?"adminSignIn":"signIn":signup?"create":forgot?"sendReset":verify?"verify":mode==="google-link"?"link":mode==="google-complete"?"continue":invitation?"accept":"reset")}{signup&&step===1&&<ChevronRight size={16}/>}</button>
       {signup&&step===2&&<button type="button" className="button secondary" onClick={()=>{setStep(1);setAttempted(false);}}>{t("back")}</button>}
      </fieldset>
     </form>}
    {verificationNeeded&&<div className="auth-verification"><button className="button secondary" disabled={busy} onClick={()=>void resend()}>{t("resend")}</button><Link href="/verify-email">{t("verificationPage")}</Link></div>}
    <nav className="auth-links">
     {login&&!admin&&<p>{t("newHere")} <Link href="/signup">{t("create")}</Link></p>}
     {login&&<Link href={admin?"/login":"/admin/login"}><LockKeyhole size={13}/>{t(admin?"userSignIn":"adminSignInLink")}</Link>}
     {!login&&<Link href={signin}><ArrowLeft size={14}/>{t("backToSignIn")}</Link>}
     {finished&&<Link className="button primary" href={signin}>{t("continueSignIn")}</Link>}
    </nav>
   </section>
  </div>
  <footer className="auth-footer">{admin?"Setu NGO":brand.footer_text||brand.brand_name}<nav className="tenant-legal-links">{brand.support_url&&!admin&&<a href={brand.support_url}>{t("support")}</a>}{brand.terms_url&&!admin&&<a href={brand.terms_url}>{t("termsLink")}</a>}{brand.privacy_url&&!admin&&<a href={brand.privacy_url}>{t("privacyLink")}</a>}</nav></footer>
 </main>;
}
