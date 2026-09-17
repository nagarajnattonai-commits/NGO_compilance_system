import { redirect } from "next/navigation";
import ComplianceApp from "@/components/workspace";
import { LocalizationProvider } from "@/i18n/client";
import { requireSession } from "@/lib/server-auth";

export default async function WhiteLabelPage() {
  const session = await requireSession();
  if (session.user.role !== "ADMIN") redirect("/dashboard");
  return (
    <LocalizationProvider>
      <ComplianceApp user={session.user} initialView="whiteLabel" />
    </LocalizationProvider>
  );
}
