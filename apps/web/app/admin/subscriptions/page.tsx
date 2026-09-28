import PlatformSubscriptions from "@/components/subscriptions";
import { LocalizationProvider } from "@/i18n/client";
import { requirePlatformSession } from "@/lib/server-auth";

export default async function PlatformSubscriptionsPage() {
  await requirePlatformSession();
  return <LocalizationProvider><PlatformSubscriptions /></LocalizationProvider>;
}
