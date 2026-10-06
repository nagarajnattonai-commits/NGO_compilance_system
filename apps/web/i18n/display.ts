import { ApiError } from "@/lib/http";

type Translator = {
  (key: string, values?: Record<string, string | number>): string;
  has(key: string): boolean;
};

// Translate known display codes only; custom/user-entered labels stay intact.
export function localizedStatus(value: string, t: Translator) {
  const key = `Common.status.${value}`;
  return t.has(key) ? t(key) : value;
}

export function localizedRole(value: string, t: Translator) {
  const key = ({ ADMIN: "Marketing.administrator", MEMBER: "Marketing.teamMember", VIEWER: "Marketing.readOnlyViewer" } as Record<string, string>)[value];
  return key ? t(key) : value;
}

export function localizedSecurityEvent(value: string, t: Translator) {
  const keys: Record<string, string> = {
    LOGIN_SUCCESS: "Common.interface.securityLoginSuccess", ADMIN_LOGIN_SUCCESS: "Common.interface.securityLoginSuccess", GOOGLE_LOGIN: "Common.interface.securityLoginSuccess",
    LOGIN_FAILED: "Common.interface.securityLoginFailure", ADMIN_LOGIN_FAILED: "Common.interface.securityLoginFailure",
    LOGOUT: "Common.interface.securityLogout", PASSWORD_CHANGED: "Common.interface.securityPasswordChange",
    PASSWORD_RESET_COMPLETED: "Common.interface.securityPasswordReset", SESSION_REVOKED: "Common.interface.securitySessionRevoked",
    EMAIL_VERIFIED: "Authentication.verified", INVITATION_ACCEPTED: "Authentication.invitationSuccess",
  };
  return t(keys[value] || "Common.interface.securityOther");
}

// API contracts and error codes remain untouched. Only safe UI text changes.
export function localizedError(reason: unknown, t: Translator, fallback: string) {
  if (!(reason instanceof ApiError)) return reason instanceof Error ? reason.message : fallback;
  if (reason.message === "AI services are not configured for this workspace.") return t("Common.interface.aiNotConfigured");
  const status = reason.status;
  const key = status === 0 ? "requestNetwork" : status === 401 ? "requestSession"
    : status === 403 ? "requestDenied" : status === 404 ? "requestMissing"
    : status === 409 ? "requestConflict" : status === 429 ? "requestRate"
    : status >= 500 ? "requestUnavailable" : "requestValidation";
  return t(`Common.interface.${key}`);
}
