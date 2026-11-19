import MfaChallenge from "@/components/mfa-challenge";
import {getTranslations} from "next-intl/server";
export async function generateMetadata(){const t=await getTranslations("Authentication");return {title:t("mfa.title"),referrer:"no-referrer" as const};}
export default function Page(){return <MfaChallenge/>;}
