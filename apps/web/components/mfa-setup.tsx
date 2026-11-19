"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";

type Setup = { secret: string; otpauth_uri: string };

// Shared by the sign-in check and account settings: start, confirm a code, then show recovery codes once.
export default function MfaSetup({ onDone, formClass = "auth-form", buttonClass = "auth-submit" }: { onDone: () => void; formClass?: string; buttonClass?: string }) {
  const t = useTranslations("Authentication");
  const [setup, setSetup] = useState<Setup | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function start() {
    setBusy(true); setError("");
    try { setSetup(await apiRequest<Setup>("/auth/mfa/setup", "POST")); }
    catch { setError(t("mfa.unavailable")); }
    finally { setBusy(false); }
  }
  async function enable(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try { setCodes((await apiRequest<{ recovery_codes: string[] }>("/auth/mfa/enable", "POST", { code })).recovery_codes); setSetup(null); }
    catch { setError(t("mfa.invalidCode")); }
    finally { setBusy(false); setCode(""); }
  }

  if (codes.length) return <div>
    <h2>{t("mfa.recoveryTitle")}</h2>
    <p className="auth-description">{t("mfa.recoveryDescription")}</p>
    <ul aria-label={t("mfa.recoveryTitle")}>{codes.map(item => <li key={item}><code>{item}</code></li>)}</ul>
    <button type="button" className={buttonClass} onClick={onDone}>{t("mfa.continue")}</button>
  </div>;

  if (!setup) return <div>
    {error && <div role="alert" className="auth-alert error">{error}</div>}
    <p className="auth-description">{t("mfa.setupDescription")}</p>
    <button type="button" className={buttonClass} disabled={busy} onClick={() => void start()}>{busy ? t("working") : t("mfa.start")}</button>
  </div>;

  return <form className={formClass} onSubmit={enable}>
    {error && <div role="alert" className="auth-alert error">{error}</div>}
    <fieldset disabled={busy}>
      <p className="auth-description">{t("mfa.secretHelp")}</p>
      <label>{t("mfa.secretLabel")}<input readOnly value={setup.secret} onFocus={event => event.currentTarget.select()} /></label>
      <a href={setup.otpauth_uri}>{t("mfa.openApp")}</a>
      <label>{t("mfa.code")}<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" maxLength={8} value={code} onChange={event => setCode(event.target.value)} /></label>
      <button className={buttonClass}>{busy ? t("working") : t("mfa.enable")}</button>
    </fieldset>
  </form>;
}
