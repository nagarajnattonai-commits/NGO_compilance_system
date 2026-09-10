import ComplianceApp from "@/components/workspace";
import { requireSession } from "@/lib/server-auth";

export default async function DashboardPage() {
  const session = await requireSession();
  return <ComplianceApp user={session.user} />;
}
