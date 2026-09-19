import { LocalizationProvider } from "@/i18n/client";
import { requirePlatformSession } from "@/lib/server-auth";

export default async function AutomationLayout({ children }: { children: React.ReactNode }) {
  await requirePlatformSession();
  return <LocalizationProvider>{children}</LocalizationProvider>;
}
