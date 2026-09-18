import { requirePlatformSession } from "@/lib/server-auth";
import { LocalizationProvider } from "@/i18n/client";
import "./compliance-master.css";

export default async function ComplianceMasterLayout({ children }: { children: React.ReactNode }) {
  await requirePlatformSession();
  return <LocalizationProvider>{children}</LocalizationProvider>;
}
