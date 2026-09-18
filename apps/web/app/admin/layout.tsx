import {headers} from "next/headers";
import {redirect} from "next/navigation";
import {requirePlatformSession} from "@/lib/server-auth";
export default async function AdminLayout({children}:{children:React.ReactNode}){
 const requestHeaders=await headers();const pathname=requestHeaders.get("x-setu-pathname")||"/admin";
 const origin=process.env.APP_ORIGIN||"http://localhost:3000";
 const hostname=new URL("http://"+(requestHeaders.get("host")||"localhost")).hostname;
 const allowed=new Set([new URL(origin).hostname,...(process.env.PLATFORM_HOSTS||"").split(",").map(value=>value.trim())]);
 if(process.env.APP_ENV!=="production"){allowed.add("localhost");allowed.add("127.0.0.1");}
 if(!allowed.has(hostname))redirect(origin+pathname);
 if(!["/admin/login","/admin/forgot-password","/admin/reset-password"].includes(pathname))await requirePlatformSession();
 return children;
}
