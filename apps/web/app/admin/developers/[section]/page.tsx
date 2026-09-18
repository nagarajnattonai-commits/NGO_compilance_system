import {notFound} from "next/navigation";
import DeveloperManagement from "@/components/developer-management";
export default async function Page({params}:{params:Promise<{section:string}>}){
 const {section}=await params;
 if(!["applications","api-keys","usage","documentation","oauth","webhooks"].includes(section))notFound();
 return <DeveloperManagement platform section={section}/>;
}
