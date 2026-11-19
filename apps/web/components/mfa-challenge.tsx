"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ApiError, apiRequest } from "@/lib/http";
import PublicLocaleSwitcher from "./public-locale-switcher";
import MfaSetup from "./mfa-setup";
import "@/app/auth-experience.css";

type Status = { available: boolean; enabled: boolean; verified: boolean; required: boolean };

// Only same-site paths are followed after verification.
function nextPath() {
  const value = new URLSearchParams(window.location.search).get("next") || "";
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/auth/mfa")) return "/dashboard";
  // Coming from a sign-in page means "go where that sign-in leads".
  if (value.startsWith("/admin/login")) return "/admin";
  return value.startsWith("/login") ? "/dashboard" : value;
}

export default function MfaChallenge() {
  const t = useTranslations("Authentication");
  const [status, setStatus] = useState<Status | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest<Status>("/auth/mfa").then(result => {
      if (result.verified || (!result.enabled && !result.required)) window.location.replace(nextPath());
      else setStatus(result);
    }).catch(reason => {
      if (reason instanceof ApiError && reason.status === 401) window.location.replace("/login");
      else setError(t("mfa.unavailable"));
    });
  }, [t]);

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try { await apiRequest("/auth/mfa/verify", "POST", { code }); window.location.replace(nextPath()); }
    catch (reason) { setError(reason instanceof ApiError && reason.status === 429 ? t("mfa.tooMany") : t("mfa.invalidCode")); setBusy(false); setCode(""); }
  }
  async function signOut() {
    try { await apiRequest("/auth/logout", "POST"); } finally { window.location.assign("/login"); }
  }

  const enrolling = status && !status.enabled && status.required;
  return <main className="auth-shell auth-experience auth-user">
    <div className="auth-theme-toggle"><PublicLocaleSwitcher compact /></div>
    <section className="auth-card">
      <h1>{enrolling ? t("mfa.setupTitle") : t("mfa.verifyTitle")}</h1>
      {!status && !error && <p role="status" className="auth-description">{t("working")}</p>}
      {error && <div role="alert" className="auth-alert error">{error}</div>}
      {enrolling && <><p className="auth-description">{t("mfa.setupRequired")}</p><MfaSetup onDone={() => window.location.replace(nextPath())} /></>}
      {status && status.enabled && <form className="auth-form" onSubmit={verify}>
        <fieldset disabled={busy}>
          <p className="auth-description">{t("mfa.verifyDescription")}</p>
          <label>{t("mfa.code")}<input required autoFocus inputMode="text" autoComplete="one-time-code" maxLength={20} value={code} onChange={event => setCode(event.target.value)} /></label>
          <button className="auth-submit">{busy ? t("working") : t("mfa.verify")}</button>
        </fieldset>
      </form>}
      <div className="auth-links"><a href="/login" className="auth-back" onClick={event => { event.preventDefault(); void signOut(); }}>{t("mfa.signOut")}</a></div>
    </section>
  </main>;
}
