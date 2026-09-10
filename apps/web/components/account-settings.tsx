"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Eye, EyeOff, LockKeyhole, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { apiRequest } from "@/lib/http";
import { roleLabel, type AuthSession, type AuthUser } from "@/lib/auth-types";
import ThemeToggle from "@/components/theme-toggle";
import PasswordGuidance from "@/components/password-guidance";
import { validateNewPassword } from "@/lib/auth-validation";

export default function AccountSettings({ session }: { session: AuthSession }) {
  const [user, setUser] = useState(session.user);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [passwordAttempted, setPasswordAttempted] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const newPasswordError = validateNewPassword(newPassword);
  const confirmPasswordError = !confirmPassword ? "Confirm your new password." : newPassword !== confirmPassword ? "Passwords do not match." : "";
  const detectCapsLock = (event: React.KeyboardEvent<HTMLInputElement>) => setCapsLock(event.getModifierState("CapsLock"));
  async function profile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    setBusy(true); setError(""); setSuccess("");
    try { setUser(await apiRequest<AuthUser>("/auth/profile", "PATCH", { name: data.get("name"), phone: data.get("phone") })); setSuccess("Your profile has been saved."); }
    catch (error) { setError(error instanceof Error ? error.message : "Could not save profile"); }
    finally { setBusy(false); }
  }
  async function password(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPasswordAttempted(true);
    setError(""); setSuccess("");
    if (!currentPassword || newPasswordError || confirmPasswordError) { setError("Please correct the highlighted password fields."); return; }
    if (currentPassword === newPassword) { setError("Choose a new password that differs from your current password."); return; }
    setBusy(true);
    try { await apiRequest<void>("/auth/change-password", "POST", { current_password: currentPassword, password: newPassword }); window.location.assign("/login"); }
    catch (error) { setError(error instanceof Error ? error.message : "Could not update password"); }
    finally { setBusy(false); }
  }
  async function logout() {
    setBusy(true); setError("");
    try { await apiRequest<void>("/auth/logout", "POST"); window.location.assign("/login"); }
    catch (error) { setError(error instanceof Error ? error.message : "Could not sign out"); setBusy(false); }
  }
  return <main className="account-page"><header className="account-header"><Link href="/" className="account-brand"><ShieldCheck size={26} />Setu NGO</Link><Link href="/"><ArrowLeft size={16} />Back to dashboard</Link><ThemeToggle variant="icon" /><button className="button secondary" disabled={busy} onClick={logout}><LogOut size={16} />Sign out</button></header><div className="account-content"><span className="eyebrow">Home / My account</span><h1>Account Settings</h1><p className="account-intro">{session.workspace_name} · {roleLabel(user.role)}</p>
    {error && <div className="auth-alert error" role="alert">{error}</div>}{success && <div className="auth-alert success" role="status">{success}</div>}
    <div className="account-grid"><section className="card"><div className="account-section-head"><UserRound size={20} /><h2>Personal information</h2></div><form className="auth-form" onSubmit={profile}><fieldset disabled={busy}><label>Full name<input name="name" required minLength={2} maxLength={120} defaultValue={user.name} autoComplete="name" /></label><label>Email address<input readOnly value={user.email} /><small>Your sign-in email cannot be changed here.</small></label><label>Mobile number<input name="phone" type="tel" maxLength={30} defaultValue={user.phone} autoComplete="tel" /></label><label>Role<input readOnly value={roleLabel(user.role)} /></label><button className="button primary" type="submit">Save profile</button></fieldset></form></section>
    <section className="card"><div className="account-section-head"><LockKeyhole size={20} /><h2>Change password</h2></div><p className="account-intro">Changing your password signs out every session, including this one.</p><form className="auth-form" onSubmit={password} noValidate><fieldset disabled={busy}><label>Current password<span className="password-input"><input name="current_password" type={showPassword ? "text" : "password"} required maxLength={128} autoComplete="current-password" value={currentPassword} aria-invalid={passwordAttempted && !currentPassword} aria-describedby={passwordAttempted && !currentPassword ? "current-password-error" : undefined} onChange={(event) => setCurrentPassword(event.target.value)} onKeyDown={detectCapsLock} onKeyUp={detectCapsLock} /><button type="button" aria-label={showPassword ? "Hide passwords" : "Show passwords"} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></span>{passwordAttempted && !currentPassword && <small className="field-error" id="current-password-error">Enter your current password.</small>}{capsLock && <small className="caps-warning">Caps Lock is on.</small>}</label><label>New password<span className="password-input"><input name="password" type={showPassword ? "text" : "password"} required minLength={12} maxLength={128} autoComplete="new-password" value={newPassword} aria-invalid={passwordAttempted && Boolean(newPasswordError)} aria-describedby="password-help" onChange={(event) => setNewPassword(event.target.value)} onKeyDown={detectCapsLock} onKeyUp={detectCapsLock} /><button type="button" aria-label={showPassword ? "Hide passwords" : "Show passwords"} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></span>{passwordAttempted && newPasswordError && <small className="field-error">{newPasswordError}</small>}<PasswordGuidance password={newPassword} /></label><label>Confirm new password<span className="password-input"><input name="confirm_password" type={showPassword ? "text" : "password"} required minLength={12} maxLength={128} autoComplete="new-password" value={confirmPassword} aria-invalid={passwordAttempted && Boolean(confirmPasswordError)} aria-describedby={passwordAttempted && confirmPasswordError ? "account-confirm-error" : undefined} onChange={(event) => setConfirmPassword(event.target.value)} onKeyDown={detectCapsLock} onKeyUp={detectCapsLock} /><button type="button" aria-label={showPassword ? "Hide passwords" : "Show passwords"} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></span>{passwordAttempted && confirmPasswordError && <small className="field-error" id="account-confirm-error">{confirmPasswordError}</small>}</label><button className="button primary" type="submit">Update password & sign out</button></fieldset></form></section></div>
  </div></main>;
}
