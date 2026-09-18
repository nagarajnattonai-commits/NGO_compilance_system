"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {useTranslations} from "next-intl";
import {listOnboarding,type OnboardingState} from "@/lib/onboarding";
export default function OnboardingBanner({canManage}:{canManage:boolean}){
 const t=useTranslations("Onboarding");const [state,setState]=useState<OnboardingState|null|undefined>(undefined);
 useEffect(()=>{if(canManage)listOnboarding().then(rows=>setState(rows.find(r=>r.status==="IN_PROGRESS")||(!rows.length?null:undefined))).catch(()=>setState(undefined));},[canManage]);
 if(!canManage||state===undefined)return null;
 return <aside className="card" style={{padding:20,margin:"16px 0"}}><strong>{t(state?"continueSetup":"startSetup")}</strong><p>{t("bannerHelp")}</p><Link className="button primary" href={"/onboarding"+(state?"?organization="+encodeURIComponent(state.organization_id):"")}>{t(state?"resume":"startSetup")}</Link></aside>;
}
