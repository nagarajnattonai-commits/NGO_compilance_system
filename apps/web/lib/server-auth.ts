import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { AuthSession } from "./auth-types";
import { brandingRequestHeaders } from "@/branding/server";

export async function requireSession(loginPath = "/login"): Promise<AuthSession> {
  const token = (await cookies()).get("setu_session")?.value;
  if (!token) redirect(loginPath);
  let response: Response;
  try {
    response = await fetch(`${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/auth/me`, {
      headers: { ...(await brandingRequestHeaders()), Cookie: `setu_session=${encodeURIComponent(token)}` },
      cache: "no-store", signal: AbortSignal.timeout(8000),
    });
  } catch {
    throw new Error("The authentication service is unavailable. Start the API server and try again.");
  }
  if (response.status === 401) redirect(loginPath+"?expired=1");
  if (response.status === 403) redirect("/access-denied");
  if (!response.ok) throw new Error("Unable to verify your session");
  return response.json();
}

export async function requirePlatformSession(): Promise<AuthSession> {
  const session = await requireSession("/admin/login");
  const token = (await cookies()).get("setu_session")?.value;
  const response = await fetch(`${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/admin/auth/access`, {
    headers: { ...(await brandingRequestHeaders()), Cookie: `setu_session=${encodeURIComponent(token || "")}` },
    cache: "no-store", signal: AbortSignal.timeout(8000),
  });
  if (!response.ok || !(await response.json()).allowed) redirect("/access-denied?admin=1");
  return session;
}


export async function redirectAuthenticated(admin=false) {
  const token=(await cookies()).get("setu_session")?.value;
  if(!token)return;
  try {
    const response=await fetch((process.env.API_INTERNAL_URL||"http://127.0.0.1:8000")+(admin?"/api/v1/admin/auth/access":"/api/v1/auth/me"),{
      headers:{...(await brandingRequestHeaders()),Cookie:"setu_session="+encodeURIComponent(token)},cache:"no-store",signal:AbortSignal.timeout(4000)
    });
    if(!response.ok)return;
    if(admin&&!(await response.json()).allowed)return;
  } catch { return; }
  redirect(admin?"/admin":"/dashboard");
}
