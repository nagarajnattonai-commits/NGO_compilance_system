export type AuthUser = {
  id: string;
  name: string;
  email: string;
  phone: string;
  tenant_id: string;
  role: "ADMIN" | "MEMBER" | "VIEWER";
  status: "ACTIVE" | "INVITED" | "DISABLED";
  created_at: string;
  has_password: boolean;
};
export type AuthSession = { user: AuthUser; workspace_name: string };
export type InvitationResult = { user: AuthUser; token: string; expires_in_hours: number };
export const roleLabel = (role: AuthUser["role"]) => ({ ADMIN: "Administrator", MEMBER: "Team member", VIEWER: "Read-only viewer" })[role];
