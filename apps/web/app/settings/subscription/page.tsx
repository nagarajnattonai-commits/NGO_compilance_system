import ComplianceApp from "@/components/workspace";
import { LocalizationProvider } from "@/i18n/client";
import { requireSession } from "@/lib/server-auth";

export default async function SubscriptionPage() {
  const session = await requireSession();
  return <LocalizationProvider><ComplianceApp user={session.user} initialView="subscription" /></LocalizationProvider>;
}
