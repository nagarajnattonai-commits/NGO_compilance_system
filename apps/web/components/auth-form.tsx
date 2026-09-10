"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Eye, EyeOff, ShieldCheck, ArrowLeft, LockKeyhole } from "lucide-react";
import { apiRequest } from "@/lib/http";
import type { AuthUser } from "@/lib/auth-types";
import ThemeToggle from "@/components/theme-toggle";
import PasswordGuidance from "@/components/password-guidance";
import { normalizeEmail, validateEmail, validateNewPassword } from "@/lib/auth-validation";

type Mode = "login" | "admin-login" | "signup" | "forgot-password" | "reset-password" | "accept-invitation";
const titles: Record<Mode, string> = {
  login: "Sign In", "admin-login": "Admin Sign In", signup: "Create Your Account",
  "forgot-password": "Forgot Password?", "reset-password": "Set a New Password", "accept-invitation": "Join Your Workspace",
};
const descriptions: Record<Mode, string> = {
  login: "Welcome back to your NGO compliance workspace.",
  "admin-login": "Sign in with your workspace administrator account.",
  signup: "Create a workspace and become its administrator.",
  "forgot-password": "Enter your account email to request a reset link.",
  "reset-password": "Choose a new password to get back to your workspace.",
  "accept-invitation": "Set your password to accept your team invitation.",
};

export default function AuthForm({ mode }: { mode: Mode }) {
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [attempted, setAttempted] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const isLogin = mode === "login" || mode === "admin-login";
  const isToken = mode === "reset-password" || mode === "accept-invitation";
  const newPassword = mode === "signup" || isToken;
  const emailError = isToken ? "" : validateEmail(email);
  const passwordError = mode === "forgot-password" ? "" : isLogin ? (password ? "" : "Enter your password.") : validateNewPassword(password);
  const confirmError = newPassword && password !== confirmPassword ? "Passwords do not match." : newPassword && !confirmPassword ? "Confirm your new password." : "";
  const showFieldError = (field: string, message: string) => Boolean(message && (attempted || touched[field]));
  const touch = (field: string) => setTouched((fields) => ({ ...fields, [field]: true }));
  const detectCapsLock = (event: React.KeyboardEvent<HTMLInputElement>) => setCapsLock(event.getModifierState("CapsLock"));
  useEffect(() => {
    if (isToken) {
      const suppliedToken = new URLSearchParams(window.location.hash.slice(1)).get("token");
      if (suppliedToken) setToken(suppliedToken);
      // Keep bearer tokens out of browser history and referrer URLs after capture.
      window.history.replaceState(null, "", window.location.pathname);
    }
    if (new URLSearchParams(window.location.search).has("expired")) setError("Your session has ended. Please sign in again.");
  }, [isToken]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAttempted(true);
    setError(""); setSuccess("");
    const data = new FormData(event.currentTarget);
    const value = (name: string) => String(data.get(name) || "");
    if (emailError || passwordError || confirmError) { setError("Please correct the highlighted fields before continuing."); return; }
    if (isToken && !token) { setError("Open the full invitation or reset link you received. This page is missing a valid token."); return; }
    setBusy(true);
    try {
      if (isLogin) {
        const user = await apiRequest<AuthUser>("/auth/login", "POST", { email: normalizeEmail(email), password, remember: data.has("remember"), admin_only: mode === "admin-login" });
        window.location.assign(user.role === "ADMIN" ? "/admin" : "/dashboard");
      } else if (mode === "signup") {
        await apiRequest<AuthUser>("/auth/signup", "POST", { name: value("name"), email: normalizeEmail(email), phone: value("phone"), workspace_name: value("workspace_name"), password });
        window.location.assign("/admin");
      } else if (mode === "forgot-password") {
        const result = await apiRequest<{ message: string }>("/auth/forgot-password", "POST", { email: normalizeEmail(email) });
        setSuccess(result.message);
      } else {
        await apiRequest<void>(`/auth/${mode}`, "POST", { token, password });
        setToken(""); setSuccess(mode === "accept-invitation" ? "Your account is ready. Sign in to join your team." : "Password updated. All previous sessions have been signed out.");
      }
    } catch (error) { setError(error instanceof Error ? error.message : "Something went wrong. Try again."); }
    finally { setBusy(false); }
  }

  return <main className="auth-shell">
    <ThemeToggle className="auth-theme-toggle" />
    <section className={`auth-card ${mode === "signup" ? "auth-card-signup" : ""}`}>
      <Link href="/" className="auth-logo" aria-label="Setu public website"><ShieldCheck size={32} /></Link>
      <p className="auth-brand">SETU NGO</p>
      <h1>{titles[mode]}</h1><p className="auth-description">{descriptions[mode]}</p>
      {error && <div className="auth-alert error" role="alert">{error}</div>}
      {success && <div className="auth-alert success" role="status">{success}</div>}
      {!(isToken && success) && <form className="auth-form" onSubmit={submit} noValidate>
        <fieldset disabled={busy}>
          {mode === "signup" && <><label>Full name<input name="name" autoComplete="name" required minLength={2} maxLength={120} placeholder="Enter your full name" /></label><label>Workspace name<input name="workspace_name" autoComplete="organization" required minLength={2} maxLength={160} placeholder="Your NGO or consulting firm" /></label><label>Mobile number <span className="optional">(optional)</span><input name="phone" type="tel" autoComplete="tel" maxLength={30} placeholder="Enter your mobile number" /></label></>}
          {!isToken && <label>Email address<input name="email" type="email" inputMode="email" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={200} placeholder="you@organization.org" value={email} aria-invalid={showFieldError("email", emailError)} aria-describedby={showFieldError("email", emailError) ? "email-error" : undefined} onChange={(event) => setEmail(event.target.value)} onBlur={() => touch("email")} />{showFieldError("email", emailError) && <small className="field-error" id="email-error">{emailError}</small>}</label>}
          {mode !== "forgot-password" && <label>{newPassword ? "New password" : "Password"}<span className="password-input"><input name="password" type={showPassword ? "text" : "password"} autoComplete={newPassword ? "new-password" : "current-password"} required minLength={newPassword ? 12 : 1} maxLength={128} placeholder={newPassword ? "Create a strong password" : "Enter your password"} value={password} aria-invalid={showFieldError("password", passwordError)} aria-describedby={newPassword ? "password-help" : showFieldError("password", passwordError) ? "password-error" : undefined} onChange={(event) => setPassword(event.target.value)} onBlur={() => { touch("password"); setCapsLock(false); }} onKeyDown={detectCapsLock} onKeyUp={detectCapsLock} /><button type="button" aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></span>{showFieldError("password", passwordError) && <small className="field-error" id="password-error">{passwordError}</small>}{capsLock && <small className="caps-warning">Caps Lock is on.</small>}{newPassword && <PasswordGuidance password={password} />}</label>}
          {newPassword && <label>Confirm password<span className="password-input"><input name="confirm_password" type={showPassword ? "text" : "password"} autoComplete="new-password" required minLength={12} maxLength={128} placeholder="Re-enter your password" value={confirmPassword} aria-invalid={showFieldError("confirm", confirmError)} aria-describedby={showFieldError("confirm", confirmError) ? "confirm-error" : undefined} onChange={(event) => setConfirmPassword(event.target.value)} onBlur={() => touch("confirm")} onKeyDown={detectCapsLock} onKeyUp={detectCapsLock} /><button type="button" aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></span>{showFieldError("confirm", confirmError) && <small className="field-error" id="confirm-error">{confirmError}</small>}</label>}
          {isLogin && <div className="auth-options"><label className="auth-checkbox"><input type="checkbox" name="remember" />Keep me signed in for 30 days</label></div>}
          <button className="auth-submit" type="submit">{busy ? "Please wait…" : isLogin ? "Sign In" : mode === "signup" ? "Create Account" : mode === "forgot-password" ? "Send Reset Link" : mode === "accept-invitation" ? "Accept Invitation" : "Update Password"}</button>
        </fieldset>
      </form>}
      <div className="auth-links">
        {isLogin && <><p>Don’t have an account? <Link href="/signup">Create an account</Link></p><Link href="/forgot-password">Forgot password?</Link><Link className="portal-link" href={mode === "admin-login" ? "/login" : "/admin/login"}><LockKeyhole size={13} />{mode === "admin-login" ? "Team member sign in" : "Administrator sign in"}</Link></>}
        {mode === "signup" && <p>Already have an account? <Link href="/login">Sign in</Link></p>}
        {!isLogin && mode !== "signup" && <Link className="auth-back" href="/login"><ArrowLeft size={14} />Back to sign in</Link>}
        <Link className="auth-back" href="/"><ArrowLeft size={14} />Explore the Setu website</Link>
      </div>
    </section>
    <footer className="auth-footer">Setu NGO Compliance System<span>One workspace. Every obligation accounted for.</span></footer>
  </main>;
}
