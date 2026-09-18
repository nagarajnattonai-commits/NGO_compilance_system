import AuthForm from "@/components/auth-form";
import {getTranslations} from "next-intl/server";
export async function generateMetadata(){const t=await getTranslations("Authentication");return {title:t("titles.linkGoogle"),referrer:"no-referrer" as const};}
export default async function Page(){return <AuthForm mode="google-link"/>;}
