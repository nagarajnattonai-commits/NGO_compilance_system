import { notFound } from "next/navigation";
import IntegrationManagement from "@/components/integration-management";
export default async function Page({params}:{params:Promise<{section:string}>}){
 const {section}=await params;
 if(!["providers", "connections", "credentials", "webhooks", "logs", "health", "tenants", "audit"].includes(section))notFound();
 return <IntegrationManagement scope="platform" section={section}/>;
}
