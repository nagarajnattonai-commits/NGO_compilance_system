import AuthForm from "@/components/auth-form";
import {redirectAuthenticated} from "@/lib/server-auth";
import {getTranslations} from "next-intl/server";
export async function generateMetadata(){const t=await getTranslations("Authentication");return {title:t("titles.login"),referrer:"no-referrer" as const};}
export default async function Page(){await redirectAuthenticated(false);return <AuthForm mode="login"/>;}
