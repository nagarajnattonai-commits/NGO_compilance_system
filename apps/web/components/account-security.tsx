"use client";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { apiRequest } from "@/lib/http";

type Session = { id: string; current: boolean; created_at: string; expires_at: string };
type Activity = { id: string; event: string; method: string; audience: string; created_at: string };

export default function AccountSecurity() {
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
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load security information"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  async function revoke(session: Session) {
    if (session.current || busy || !window.confirm("Revoke this other sign-in session? It will lose access to your account.")) return;
    setBusy(true); setError("");
    try { await apiRequest(`/auth/sessions/${session.id}`, "DELETE"); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not revoke session"); }
    finally { setBusy(false); }
  }
  return <section className="card" aria-label="Account security">
    <div className="account-section-head"><ShieldCheck size={20}/><h2>Sessions &amp; security activity</h2></div>
    <p>Sign-in times are shown below. Device and location information is not available.</p>
    <button className="button secondary" disabled={loading || busy} onClick={() => void load()}>Refresh security activity</button>
    {loading && <p role="status">Loading security information...</p>}
    {error && <p className="auth-alert error" role="alert">{error}</p>}
    {!loading && !error && <>
      <h3>Active sessions</h3>
      {!sessions.length && <p>No active sessions found.</p>}
      <ul>{sessions.map(session => <li key={session.id}>
        <strong>{session.current ? "Current session" : "Other session"}</strong>
        <p>Signed in: {new Date(session.created_at).toLocaleString()} · Expires: {new Date(session.expires_at).toLocaleString()}</p>
        {!session.current && <button className="button secondary" disabled={busy} onClick={() => void revoke(session)}>Revoke session</button>}
      </li>)}</ul>
      <h3>Recent security activity</h3>
      {!activity.length && <p>No recent security activity.</p>}
      <ul>{activity.map(event => <li key={event.id}>{event.event.replaceAll("_", " ")} · {event.method || "Method not recorded"} · {event.audience} · {new Date(event.created_at).toLocaleString()}</li>)}</ul>
    </>}
  </section>;
}
