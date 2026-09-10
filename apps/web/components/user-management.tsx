"use client";

import { useEffect, useState } from "react";
import { Copy, Users, Plus, RefreshCw } from "lucide-react";
import { apiRequest } from "@/lib/http";
import { roleLabel, type AuthUser, type InvitationResult } from "@/lib/auth-types";
import { normalizeEmail, validateEmail } from "@/lib/auth-validation";

export default function UserManagement({ currentUser }: { currentUser: AuthUser }) {
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
    catch (error) { setError(error instanceof Error ? error.message : "Could not load accounts"); }
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
    if (emailError) { setError(emailError); return; }
    setBusy(true);
    try {
      const result = await apiRequest<InvitationResult>("/admin/users/invite", "POST", { name: data.get("name"), email: normalizeEmail(inviteEmail), role: data.get("role") });
      showInvitation(result); setInviteOpen(false); setInviteEmail(""); setInviteAttempted(false); await refresh();
    } catch (error) { setError(error instanceof Error ? error.message : "Could not invite this user"); }
    finally { setBusy(false); }
  }
  async function renew(user: AuthUser) {
    setBusy(true); setError(""); setInvitation("");
    try { showInvitation(await apiRequest<InvitationResult>(`/admin/users/${user.id}/invitation`, "POST")); await refresh(); }
    catch (error) { setError(error instanceof Error ? error.message : "Could not renew invitation"); }
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
    } catch (error) { setError(error instanceof Error ? error.message : "Could not update access"); }
    finally { setBusy(false); }
  }
  const visible = users.filter((user) => `${user.name} ${user.email} ${user.role}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="card user-management">
    <div className="card-title"><div><h2><Users size={19} />User Management</h2><p>Workspace-wide login accounts. Only administrators can change access.</p></div><button className="button primary small" onClick={() => { setInviteOpen(!inviteOpen); setError(""); }}><Plus size={15} />Invite user</button></div>
    <div className="user-summary"><span><b>{users.filter((user) => user.status === "ACTIVE").length}</b> Active</span><span><b>{users.filter((user) => user.status === "INVITED").length}</b> Invited</span><span><b>{users.filter((user) => user.status === "DISABLED").length}</b> Disabled</span></div>
    {error && <div className="auth-alert error" role="alert">{error}</div>}
    {message && <div className="auth-alert success" role="status">{message}</div>}
    {invitation && <div className="invitation-result"><label>Private invitation link<input readOnly value={invitation} onFocus={(event) => event.target.select()} /></label><button className="button secondary small" onClick={async () => { try { await navigator.clipboard.writeText(invitation); setMessage("Invitation link copied. Share it only with the intended user."); } catch { setMessage("Select and copy the invitation link manually."); } }}><Copy size={14} />Copy</button><button className="text-button" onClick={() => { setInvitation(""); setMessage(""); }}>Dismiss</button></div>}
    {inviteOpen && <form className="inline-auth-form" onSubmit={invite} noValidate><h3>Invite a team member</h3><p>Admins manage the workspace and accounts. Members edit operational records. Viewers can only read records.</p><div className="user-form-grid"><label>Full name<input name="name" required minLength={2} maxLength={120} /></label><label>Email address<input name="email" type="email" inputMode="email" autoCapitalize="none" spellCheck={false} required maxLength={200} value={inviteEmail} aria-invalid={inviteAttempted && Boolean(validateEmail(inviteEmail))} aria-describedby={inviteAttempted && validateEmail(inviteEmail) ? "invite-email-error" : undefined} onChange={(event) => setInviteEmail(event.target.value)} />{inviteAttempted && validateEmail(inviteEmail) && <small className="field-error" id="invite-email-error">{validateEmail(inviteEmail)}</small>}</label><label>Workspace role<select name="role" defaultValue="MEMBER"><option value="MEMBER">Team member</option><option value="VIEWER">Read-only viewer</option><option value="ADMIN">Administrator</option></select></label></div><button disabled={busy} className="button primary">{busy ? "Creating…" : "Create invitation link"}</button></form>}
    {editing && <form className="inline-auth-form" onSubmit={saveAccess}><h3>Update access: {editing.name}</h3><p>This changes access to every organization in this workspace and signs the user out of existing sessions.</p><div className="user-form-grid"><label>Role<select name="role" defaultValue={editing.role}><option value="ADMIN">Administrator</option><option value="MEMBER">Team member</option><option value="VIEWER">Read-only viewer</option></select></label><label>Status<select name="status" defaultValue={editing.status === "INVITED" ? "DISABLED" : editing.status}>{editing.status !== "INVITED" && <option value="ACTIVE">Active</option>}<option value="DISABLED">Disabled</option></select></label></div><div className="heading-actions"><button disabled={busy} className="button primary">Confirm access change</button><button type="button" className="button secondary" onClick={() => setEditing(null)}>Cancel</button></div></form>}
    <div className="toolbar"><label className="account-search">Search users<input placeholder="Name, email or role" value={query} onChange={(event) => setQuery(event.target.value)} /></label><button className="text-button" disabled={loading} onClick={refresh}><RefreshCw size={14} />Refresh</button></div>
    <div className="users-table-scroll"><table className="users-table"><thead><tr><th>Name</th><th>Email address</th><th>Role</th><th>Status</th><th>Action</th></tr></thead><tbody>{visible.map((user) => <tr key={user.id}><td><strong>{user.name}</strong>{user.id === currentUser.id && <small>You</small>}</td><td>{user.email}</td><td>{roleLabel(user.role)}</td><td><span className={`user-status ${user.status.toLowerCase()}`}>{user.status}</span></td><td>{user.id === currentUser.id ? <span className="muted">Current account</span> : <div className="user-row-actions"><button disabled={busy} className="button secondary small" onClick={() => setEditing(user)}>Manage</button>{!user.has_password && ["INVITED", "DISABLED"].includes(user.status) && <button disabled={busy} className="text-button" onClick={() => renew(user)}>New link</button>}</div>}</td></tr>)}</tbody></table></div>
    {loading ? <p role="status">Loading accounts…</p> : !visible.length && <p>No matching accounts.</p>}
    <div className="table-footer">Showing {visible.length} of {users.length} accounts</div>
  </section>;
}
