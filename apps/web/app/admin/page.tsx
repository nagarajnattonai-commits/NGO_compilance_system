import { redirect } from "next/navigation";
import ComplianceApp from "@/components/workspace";
import { requireSession } from "@/lib/server-auth";

export default async function AdminPage() {
  const session = await requireSession();
  if (session.user.role !== "ADMIN") redirect("/dashboard");
  return <ComplianceApp user={session.user} initialView="administration" />;
}
