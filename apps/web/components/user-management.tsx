"use client";

import { localizedError, localizedRole, localizedStatus } from "@/i18n/display";

import { useTranslations } from "next-intl";

import { useEffect, useState } from "react";
import { Copy, Users, Plus, RefreshCw } from "lucide-react";
import { apiRequest } from "@/lib/http";
import { type AuthUser, type InvitationResult } from "@/lib/auth-types";
import { normalizeEmail, validateEmail } from "@/lib/auth-validation";

export default function UserManagement({ currentUser }: { currentUser: AuthUser }) {
  const uiText = useTranslations();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invitation, setInvitation] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<AuthUser | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteAttempted, setInviteAttempted] = useState(false);
  async function refresh() {
    setLoading(true); setError("");
    try { setUsers(await apiRequest<AuthUser[]>("/admin/users")); }
    catch (error) { setError(localizedError(error, uiText, uiText("Common.interface.couldNotLoadAccounts"))); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);

  function showInvitation(result: InvitationResult) {
    setInvitation(`${window.location.origin}/accept-invitation#token=${result.token}`);
    setMessage("Invitation created. Share this private, single-use link with the intended recipient. It expires in 48 hours; no email has been sent.");
  }
  async function invite(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setInviteAttempted(true); setError(""); setInvitation("");
    const data = new FormData(event.currentTarget);
    const emailError = validateEmail(inviteEmail);
    if (emailError) { setError(uiText(inviteEmail.trim() ? "Authentication.validation.email" : "Authentication.validation.required")); return; }
    setBusy(true);
    try {
      const result = await apiRequest<InvitationResult>("/admin/users/invite", "POST", { name: data.get("name"), email: normalizeEmail(inviteEmail), role: data.get("role") });
      showInvitation(result); setInviteOpen(false); setInviteEmail(""); setInviteAttempted(false); await refresh();
    } catch (error) { setError(localizedError(error, uiText, uiText("Common.interface.couldNotInviteThisUser"))); }
    finally { setBusy(false); }
  }
  async function renew(user: AuthUser) {
    setBusy(true); setError(""); setInvitation("");
    try { showInvitation(await apiRequest<InvitationResult>(`/admin/users/${user.id}/invitation`, "POST")); await refresh(); }
    catch (error) { setError(localizedError(error, uiText, uiText("Common.interface.couldNotRenewInvitation"))); }
    finally { setBusy(false); }
  }
  async function saveAccess(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      await apiRequest<AuthUser>(`/admin/users/${editing.id}`, "PATCH", { role: data.get("role"), status: data.get("status") });
      setEditing(null); setMessage("Account access updated. The user’s previous sessions have been revoked."); await refresh();
    } catch (error) { setError(localizedError(error, uiText, uiText("Common.interface.couldNotUpdateAccess"))); }
    finally { setBusy(false); }
  }
  const visible = users.filter((user) => `${user.name} ${user.email} ${user.role}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="card user-management">
    <div className="card-title"><div><h2><Users size={19} />{uiText("Common.interface.userManagement")}</h2><p>{uiText("Common.interface.workspaceWideLoginAccountsOnlyAdministratorsCanChangeAccess")}</p></div><button className="button primary small" onClick={() => { setInviteOpen(!inviteOpen); setError(""); }}><Plus size={15} />{uiText("Common.interface.inviteUser")}</button></div>
    <div className="user-summary"><span><b>{users.filter((user) => user.status === "ACTIVE").length}</b>  {uiText("Common.status.ACTIVE")}</span><span><b>{users.filter((user) => user.status === "INVITED").length}</b>  {uiText("Marketing.invited")}</span><span><b>{users.filter((user) => user.status === "DISABLED").length}</b>  {uiText("Integrations.statuses.DISABLED")}</span></div>
    {error && <div className="auth-alert error" role="alert">{error}</div>}
    {message && <div className="auth-alert success" role="status">{message}</div>}
    {invitation && <div className="invitation-result"><label>{uiText("Common.interface.privateInvitationLink")}<input readOnly value={invitation} onFocus={(event) => event.target.select()} /></label><button className="button secondary small" onClick={async () => { try { await navigator.clipboard.writeText(invitation); setMessage("Invitation link copied. Share it only with the intended user."); } catch { setMessage("Select and copy the invitation link manually."); } }}><Copy size={14} />{uiText("Integrations.copy")}</button><button className="text-button" onClick={() => { setInvitation(""); setMessage(""); }}>{uiText("Integrations.dismiss")}</button></div>}
    {inviteOpen && <form className="inline-auth-form" onSubmit={invite} noValidate><h3>{uiText("Common.interface.inviteATeamMember")}</h3><p>{uiText("Common.interface.adminsManageTheWorkspaceAndAccountsMembersEditOperationalRecordsViewersCanOnlyReadRecords")}</p><div className="user-form-grid"><label>{uiText("Auth.fullName")}<input name="name" required minLength={2} maxLength={120} /></label><label>{uiText("Auth.email")}<input name="email" type="email" inputMode="email" autoCapitalize="none" spellCheck={false} required maxLength={200} value={inviteEmail} aria-invalid={inviteAttempted && Boolean(validateEmail(inviteEmail))} aria-describedby={inviteAttempted && validateEmail(inviteEmail) ? "invite-email-error" : undefined} onChange={(event) => setInviteEmail(event.target.value)} />{inviteAttempted && validateEmail(inviteEmail) && <small className="field-error" id="invite-email-error">{uiText("Authentication.validation.email")}</small>}</label><label>{uiText("Common.interface.workspaceRole")}<select name="role" defaultValue="MEMBER"><option value="MEMBER">{uiText("Marketing.teamMember")}</option><option value="VIEWER">{uiText("Marketing.readOnlyViewer")}</option><option value="ADMIN">{uiText("Marketing.administrator")}</option></select></label></div><button disabled={busy} className="button primary">{busy ? uiText("Common.interface.creating") : uiText("Common.interface.createInvitationLink")}</button></form>}
    {editing && <form className="inline-auth-form" onSubmit={saveAccess}><h3>{uiText("Common.interface.updateAccess")} {editing.name}</h3><p>{uiText("Common.interface.thisChangesAccessToEveryOrganizationInThisWorkspaceAndSignsTheUserOutOfExistingSessions")}</p><div className="user-form-grid"><label>{uiText("Common.interface.role")}<select name="role" defaultValue={editing.role}><option value="ADMIN">{uiText("Marketing.administrator")}</option><option value="MEMBER">{uiText("Marketing.teamMember")}</option><option value="VIEWER">{uiText("Marketing.readOnlyViewer")}</option></select></label><label>{uiText("ComplianceMaster.status")}<select name="status" defaultValue={editing.status === "INVITED" ? "DISABLED" : editing.status}>{editing.status !== "INVITED" && <option value="ACTIVE">{uiText("Common.status.ACTIVE")}</option>}<option value="DISABLED">{uiText("Integrations.statuses.DISABLED")}</option></select></label></div><div className="heading-actions"><button disabled={busy} className="button primary">{uiText("Common.interface.confirmAccessChange")}</button><button type="button" className="button secondary" onClick={() => setEditing(null)}>{uiText("Common.actions.cancel")}</button></div></form>}
    <div className="toolbar"><label className="account-search">{uiText("Common.interface.searchUsers")}<input placeholder={uiText("Common.interface.nameEmailOrRole")} value={query} onChange={(event) => setQuery(event.target.value)} /></label><button className="text-button" disabled={loading} onClick={refresh}><RefreshCw size={14} />{uiText("Common.interface.refresh")}</button></div>
    <div className="users-table-scroll"><table className="users-table"><thead><tr><th>{uiText("Workflow.name")}</th><th>{uiText("Auth.email")}</th><th>{uiText("Common.interface.role")}</th><th>{uiText("ComplianceMaster.status")}</th><th>{uiText("Portfolio.action")}</th></tr></thead><tbody>{visible.map((user) => <tr key={user.id}><td><strong>{user.name}</strong>{user.id === currentUser.id && <small>{uiText("Common.interface.you")}</small>}</td><td>{user.email}</td><td>{localizedRole(user.role, uiText)}</td><td><span className={`user-status ${user.status.toLowerCase()}`}>{localizedStatus(user.status, uiText)}</span></td><td>{user.id === currentUser.id ? <span className="muted">{uiText("Common.interface.currentAccount")}</span> : <div className="user-row-actions"><button disabled={busy} className="button secondary small" onClick={() => setEditing(user)}>{uiText("Common.interface.manage")}</button>{!user.has_password && ["INVITED", "DISABLED"].includes(user.status) && <button disabled={busy} className="text-button" onClick={() => renew(user)}>{uiText("Common.interface.newLink")}</button>}</div>}</td></tr>)}</tbody></table></div>
    {loading ? <p role="status">{uiText("Common.interface.loadingAccounts")}</p> : !visible.length && <p>{uiText("Common.interface.noMatchingAccounts")}</p>}
    <div className="table-footer">{uiText("Common.interface.rowCount", { shown: visible.length, total: users.length })}</div>
  </section>;
}
