import { notFound } from "next/navigation";
import IntegrationManagement from "@/components/integration-management";
export default async function Page({params}:{params:Promise<{section:string}>}){
 const {section}=await params;
 if(!["providers", "connections", "webhooks", "logs", "health"].includes(section))notFound();
 return <IntegrationManagement scope="tenant" section={section}/>;
}
