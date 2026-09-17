import { redirect } from "next/navigation";
import { requireSession } from "@/lib/server-auth";
import { LocalizationProvider } from "@/i18n/client";
import PlatformWhiteLabel from "@/components/platform-white-label";

export default async function PlatformBrandingPage() {
  const session = await requireSession();
  const allowed = (process.env.PLATFORM_ADMIN_EMAILS || "")
    .split(",")
    .map((email) => email.trim().toLowerCase());
  if (
    session.user.role !== "ADMIN" ||
    !allowed.includes(session.user.email.toLowerCase())
  )
    redirect("/admin");
  return (
    <LocalizationProvider>
      <PlatformWhiteLabel />
    </LocalizationProvider>
  );
}
