import AccountSettings from "@/components/account-settings";
import { LocalizationProvider } from "@/i18n/client";
import { requireSession } from "@/lib/server-auth";
export default async function AccountPage() {
  return (
    <LocalizationProvider>
      <AccountSettings session={await requireSession()} />
    </LocalizationProvider>
  );
}
