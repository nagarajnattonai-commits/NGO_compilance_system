import {requireSession} from "@/lib/server-auth";
import {LocalizationProvider} from "@/i18n/client";
import OnboardingView from "@/components/onboarding";
export default async function OnboardingPage({searchParams}:{searchParams:Promise<{organization?:string}>}){
 const session=await requireSession();const {organization}=await searchParams;
 return <LocalizationProvider><OnboardingView initialId={organization} user={session.user}/></LocalizationProvider>;
}
