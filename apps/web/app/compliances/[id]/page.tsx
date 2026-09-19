import {requireSession} from "@/lib/server-auth";
import {LocalizationProvider} from "@/i18n/client";
import RuntimeDetailView from "@/components/runtime-detail";
export default async function CompliancePage({params}:{params:Promise<{id:string}>}) {
 const session=await requireSession();const {id}=await params;
 return <LocalizationProvider><RuntimeDetailView id={id} user={session.user}/></LocalizationProvider>;
}
