"use client";
import {useState} from "react";
import {Eye,EyeOff} from "lucide-react";
import {useTranslations} from "next-intl";
import PasswordGuidance from "./password-guidance";
export default function AuthPasswordInput({value,onChange,newPassword=false,confirm=false,error=""}:{value:string;onChange:(value:string)=>void;newPassword?:boolean;confirm?:boolean;error?:string}){
 const t=useTranslations("Authentication");const [visible,setVisible]=useState(false);const [caps,setCaps]=useState(false);
 const id=confirm?"auth-confirm":"auth-password";
 return <div className="auth-password-field"><label htmlFor={id}>{t(confirm?"confirmPassword":newPassword?"newPassword":"password")}</label><span className="password-input"><input id={id} name={confirm?"confirm_password":"password"} value={value} type={visible?"text":"password"} autoComplete={newPassword||confirm?"new-password":"current-password"} maxLength={128} required onChange={e=>onChange(e.target.value)} onKeyUp={e=>setCaps(e.getModifierState("CapsLock"))} onBlur={()=>setCaps(false)} aria-invalid={!!error} aria-describedby={[error?id+"-error":"",newPassword?"password-help":""].filter(Boolean).join(" ")||undefined}/>
 <button type="button" aria-label={t(visible?"hidePassword":"showPassword")} aria-pressed={visible} onClick={()=>setVisible(!visible)}>{visible?<EyeOff size={17}/>:<Eye size={17}/>}</button></span>{error&&<small className="field-error" id={id+"-error"}>{error}</small>}{caps&&<small className="caps-warning">{t("capsLock")}</small>}{newPassword&&<PasswordGuidance password={value}/>}</div>;
}
