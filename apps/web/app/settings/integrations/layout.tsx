import { redirect } from "next/navigation";
import { LocalizationProvider } from "@/i18n/client";
import { requireSession } from "@/lib/server-auth";
export default async function Layout({children}:{children:React.ReactNode}) {
 const session=await requireSession();
 if(session.user.role!=="ADMIN")redirect("/dashboard");

 return <LocalizationProvider>{children}</LocalizationProvider>;
}
