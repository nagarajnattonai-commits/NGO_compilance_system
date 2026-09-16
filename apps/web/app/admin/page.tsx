import { redirect } from "next/navigation";
import ComplianceApp from "@/components/workspace";
import { requireSession } from "@/lib/server-auth";
import { LocalizationProvider } from "@/i18n/client";

export default async function AdminPage() {
  const session = await requireSession();
  if (session.user.role !== "ADMIN") redirect("/dashboard");
  return <LocalizationProvider><ComplianceApp user={session.user} initialView="administration" /></LocalizationProvider>;
}
