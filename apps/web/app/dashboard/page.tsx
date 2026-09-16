import ComplianceApp from "@/components/workspace";
import { requireSession } from "@/lib/server-auth";
import { LocalizationProvider } from "@/i18n/client";

export default async function DashboardPage() {
  const session = await requireSession();
  return <LocalizationProvider><ComplianceApp user={session.user} /></LocalizationProvider>;
}
