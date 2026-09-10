import AccountSettings from "@/components/account-settings";
import { requireSession } from "@/lib/server-auth";
export default async function AccountPage() { return <AccountSettings session={await requireSession()} />; }
