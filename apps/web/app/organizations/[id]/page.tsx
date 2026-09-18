import { requireSession } from "@/lib/server-auth";
import { LocalizationProvider } from "@/i18n/client";
import OrganizationProfileView from "@/components/organization-profile";
export default async function OrganizationPage({params}:{params:Promise<{id:string}>}) {
 const session=await requireSession();const {id}=await params;
 return <LocalizationProvider><OrganizationProfileView id={id} user={session.user}/></LocalizationProvider>;
}
