"use client";

import { formatDateTime } from "@/i18n/format";

import { localizedError, localizedSecurityEvent } from "@/i18n/display";

import { useTranslations } from "next-intl";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { apiRequest } from "@/lib/http";

type Session = { id: string; current: boolean; created_at: string; expires_at: string };
type Activity = { id: string; event: string; method: string; audience: string; created_at: string };

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
      <ul>{activity.map(event => <li key={event.id}>{localizedSecurityEvent(event.event, uiText)} · {event.method === "password" ? uiText("Authentication.password") : event.method || uiText("Common.interface.methodNotRecorded")} · {event.audience === "admin" ? uiText("Authentication.platformAdministration") : uiText("Common.interface.accountSecurity")} · {formatDateTime(event.created_at)}</li>)}</ul>
    </>}
  </section>;
}
