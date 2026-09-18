import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { AuthSession } from "./auth-types";
import { brandingRequestHeaders } from "@/branding/server";

export async function requireSession(): Promise<AuthSession> {
  const token = (await cookies()).get("setu_session")?.value;
  if (!token) redirect("/login");
  let response: Response;
  try {
    response = await fetch(`${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/auth/me`, {
      headers: { ...(await brandingRequestHeaders()), Cookie: `setu_session=${encodeURIComponent(token)}` },
      cache: "no-store", signal: AbortSignal.timeout(8000),
    });
  } catch {
    throw new Error("The authentication service is unavailable. Start the API server and try again.");
  }
  if (response.status === 401) redirect("/login?expired=1");
  if (!response.ok) throw new Error("Unable to verify your session");
  return response.json();
}

export async function requirePlatformSession(): Promise<AuthSession> {
  const session = await requireSession();
  const token = (await cookies()).get("setu_session")?.value;
  const response = await fetch(`${process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/admin/compliance-master/access`, {
    headers: { ...(await brandingRequestHeaders()), Cookie: `setu_session=${encodeURIComponent(token || "")}` },
    cache: "no-store", signal: AbortSignal.timeout(8000),
  });
  if (!response.ok || !(await response.json()).allowed) redirect("/dashboard");
  return session;
}
