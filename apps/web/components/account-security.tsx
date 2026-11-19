"use client";

import { formatDateTime } from "@/i18n/format";

import { localizedError, localizedSecurityEvent } from "@/i18n/display";

import { useTranslations } from "next-intl";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { apiRequest } from "@/lib/http";
import MfaSetup from "./mfa-setup";

type Session = { id: string; current: boolean; created_at: string; expires_at: string };
type Activity = { id: string; event: string; method: string; audience: string; created_at: string };

type MfaStatus = { available: boolean; enabled: boolean; recovery_codes_remaining: number };

function TwoStepSettings() {
  const t = useTranslations("Authentication");
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [mode, setMode] = useState<"" | "setup" | "disable" | "regenerate">("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    try { setStatus(await apiRequest<MfaStatus>("/auth/mfa")); } catch { setError(t("mfa.unavailable")); }
  }
  useEffect(() => { void load(); }, []);
  function reset() { setMode(""); setCode(""); setPassword(""); setError(""); void load(); }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      if (mode === "disable") { await apiRequest("/auth/mfa/disable", "POST", { password, code }); reset(); }
      else { setCodes((await apiRequest<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes", "POST", { code })).recovery_codes); reset(); }
    } catch { setError(mode === "disable" ? t("mfa.disableFailed") : t("mfa.invalidCode")); }
    finally { setBusy(false); setCode(""); setPassword(""); }
  }
  if (!status) return error ? <p className="auth-alert error" role="alert">{error}</p> : null;
  return <div>
    <h3>{t("mfa.title")}</h3>
    {!status.available && !status.enabled && <p>{t("mfa.unavailable")}</p>}
    {status.enabled && <p>{t("mfa.statusOn")} {t("mfa.recoveryRemaining", { count: status.recovery_codes_remaining })}</p>}
    {!status.enabled && status.available && mode !== "setup" && <><p>{t("mfa.statusOff")}</p><button className="button secondary" onClick={() => setMode("setup")}>{t("mfa.start")}</button></>}
    {mode === "setup" && <MfaSetup formClass="inline-auth-form" buttonClass="button" onDone={reset} />}
    {codes.length > 0 && <div><p>{t("mfa.recoveryDescription")}</p><ul>{codes.map(item => <li key={item}><code>{item}</code></li>)}</ul><button className="button secondary" onClick={() => setCodes([])}>{t("mfa.continue")}</button></div>}
    {status.enabled && !mode && !codes.length && <p>
      <button className="button secondary" onClick={() => setMode("regenerate")}>{t("mfa.regenerate")}</button>{" "}
      <button className="button secondary" onClick={() => setMode("disable")}>{t("mfa.disable")}</button>
    </p>}
    {(mode === "disable" || mode === "regenerate") && <form className="inline-auth-form" onSubmit={submit}>
      {error && <p className="auth-alert error" role="alert">{error}</p>}
      <p>{mode === "disable" ? t("mfa.disableConfirm") : t("mfa.regenerateConfirm")}</p>
      {mode === "disable" && <label>{t("password")}<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>}
      <label>{t("mfa.code")}<input required autoComplete="one-time-code" maxLength={20} value={code} onChange={event => setCode(event.target.value)} /></label>
      <button className="button" disabled={busy}>{busy ? t("working") : mode === "disable" ? t("mfa.disable") : t("mfa.regenerate")}</button>{" "}
      <button type="button" className="button secondary" disabled={busy} onClick={reset}>{t("mfa.cancel")}</button>
    </form>}
  </div>;
}

export default function AccountSecurity() {
  const uiText = useTranslations();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    setLoading(true); setError("");
    try {
      const [active, events] = await Promise.all([
        apiRequest<Session[]>("/auth/sessions"), apiRequest<Activity[]>("/auth/security-events"),
      ]);
      setSessions(active); setActivity(events);
    } catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotLoadSecurityInformation"))); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  async function revoke(session: Session) {
    if (session.current || busy || !window.confirm(uiText("Common.interface.revokeThisOtherSignInSessionItWillLoseAccessToYourAccount"))) return;
    setBusy(true); setError("");
    try { await apiRequest(`/auth/sessions/${session.id}`, "DELETE"); await load(); }
    catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotRevokeSession"))); }
    finally { setBusy(false); }
  }
  return <section className="card" aria-label={uiText("Common.interface.accountSecurity")}>
    <div className="account-section-head"><ShieldCheck size={20}/><h2>{uiText("Common.interface.sessionsSecurityActivity")}</h2></div>
    <p>{uiText("Common.interface.signInTimesAreShownBelowDeviceAndLocationInformationIsNotAvailable")}</p>
    <TwoStepSettings />
    <button className="button secondary" disabled={loading || busy} onClick={() => void load()}>{uiText("Common.interface.refreshSecurityActivity")}</button>
    {loading && <p role="status">{uiText("Common.interface.loadingSecurityInformation")}</p>}
    {error && <p className="auth-alert error" role="alert">{error}</p>}
    {!loading && !error && <>
      <h3>{uiText("Common.interface.activeSessions")}</h3>
      {!sessions.length && <p>{uiText("Common.interface.noActiveSessionsFound")}</p>}
      <ul>{sessions.map(session => <li key={session.id}>
        <strong>{session.current ? uiText("Common.interface.currentSession") : uiText("Common.interface.otherSession")}</strong>
        <p>{uiText("Common.interface.signedIn")} {formatDateTime(session.created_at)}  {uiText("Common.interface.expires")} {formatDateTime(session.expires_at)}</p>
        {!session.current && <button className="button secondary" disabled={busy} onClick={() => void revoke(session)}>{uiText("Common.interface.revokeSession")}</button>}
      </li>)}</ul>
      <h3>{uiText("Common.interface.recentSecurityActivity")}</h3>
      {!activity.length && <p>{uiText("Common.interface.noRecentSecurityActivity")}</p>}
      <ul>{activity.map(event => <li key={event.id}>{localizedSecurityEvent(event.event, uiText)} · {event.method === "password" ? uiText("Authentication.password") : event.method === "totp" ? uiText("Authentication.mfa.title") : event.method || uiText("Common.interface.methodNotRecorded")} · {event.audience === "admin" ? uiText("Authentication.platformAdministration") : uiText("Common.interface.accountSecurity")} · {formatDateTime(event.created_at)}</li>)}</ul>
    </>}
  </section>;
}
