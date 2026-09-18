import Link from "next/link";
import {getTranslations} from "next-intl/server";
export default async function Page({searchParams}:{searchParams:Promise<{admin?:string}>}){
 const t=await getTranslations("Authentication");const admin=(await searchParams).admin;
 return <main className="workspace-loading"><h1>{t("accessDenied")}</h1><p>{t(admin?"errors.admin":"errors.denied")}</p><Link className="button primary" href={admin?"/login":"/dashboard"}>{t(admin?"userSignIn":"returnDashboard")}</Link></main>;
}
