"use client";

import { localizedError, localizedRole } from "@/i18n/display";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  BellRing,
  Clock3,
  Eye,
  EyeOff,
  LockKeyhole,
  LogOut,
  Languages,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { apiRequest } from "@/lib/http";
import { type AuthSession, type AuthUser } from "@/lib/auth-types";
import ThemeToggle from "@/components/theme-toggle";
import PasswordGuidance from "@/components/password-guidance";
import AccountSecurity from "@/components/account-security";
import { validateNewPassword } from "@/lib/auth-validation";
import { useTranslations } from "next-intl";
import LocaleSwitcher from "@/components/locale-switcher";
import { useLocalization } from "@/i18n/client";
import { loadNotificationPreference, updateLocalizationPreference, updateNotificationPreference } from "@/lib/api";
import type { NotificationPreference } from "@/lib/types";
import { BrandIdentity, useTenantBrand } from "@/branding/client";

export default function AccountSettings({ session }: { session: AuthSession }) {
  const uiText = useTranslations();
  const t = useTranslations("Settings");
  const brand = useTenantBrand();
  const { settings, refresh } = useLocalization();
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
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [timeFormat, setTimeFormat] = useState<"12h" | "24h">("12h");
  const [notificationPreference, setNotificationPreference] = useState<NotificationPreference | null>(null);
  useEffect(() => {
    if (settings) {
      setTimezone(settings.preference.timezone);
      setTimeFormat(settings.preference.time_format);
    }
  }, [settings]);
  useEffect(() => {
    loadNotificationPreference().then(setNotificationPreference).catch(() => setError(t("notificationLoadFailed")));
  }, [t]);
  const newPasswordError = validateNewPassword(newPassword);
  const confirmPasswordError = !confirmPassword
    ? uiText("Common.interface.confirmYourNewPassword")
    : newPassword !== confirmPassword
      ? uiText("Auth.validation.passwordMismatch")
      : "";
  const detectCapsLock = (event: React.KeyboardEvent<HTMLInputElement>) =>
    setCapsLock(event.getModifierState("CapsLock"));
  async function profile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      setUser(
        await apiRequest<AuthUser>("/auth/profile", "PATCH", {
          name: data.get("name"),
          phone: data.get("phone"),
        }),
      );
      setSuccess(uiText("Common.interface.yourProfileHasBeenSaved"));
    } catch (error) {
      setError(
        localizedError(error, uiText, uiText("Common.interface.couldNotSaveProfile")),
      );
    } finally {
      setBusy(false);
    }
  }
  async function password(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPasswordAttempted(true);
    setError("");
    setSuccess("");
    if (!currentPassword || newPasswordError || confirmPasswordError) {
      setError(uiText("Common.interface.pleaseCorrectTheHighlightedPasswordFields"));
      return;
    }
    if (currentPassword === newPassword) {
      setError(
        uiText("Common.interface.chooseANewPasswordThatDiffersFromYourCurrentPassword"),
      );
      return;
    }
    setBusy(true);
    try {
      await apiRequest<void>("/auth/change-password", "POST", {
        current_password: currentPassword,
        password: newPassword,
      });
      window.location.assign("/login");
    } catch (error) {
      setError(
        localizedError(error, uiText, uiText("Common.interface.couldNotUpdatePassword")),
      );
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    setError("");
    try {
      await apiRequest<void>("/auth/logout", "POST");
      window.location.assign("/login");
    } catch (error) {
      setError(localizedError(error, uiText, uiText("Common.interface.couldNotSignOut")));
      setBusy(false);
    }
  }
  async function saveLocalization(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await updateLocalizationPreference({
        locale: settings?.preference.locale || null,
        timezone,
        time_format: timeFormat,
      });
      await refresh();
      setSuccess(t("saved"));
    } catch (error) {
      setError(
        localizedError(error, uiText, uiText("Common.interface.couldNotSaveLocalizationPreferences")),
      );
    } finally {
      setBusy(false);
    }
  }
  async function saveNotifications(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!notificationPreference) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const { user_id: _userId, updated_at: _updatedAt, ...payload } = notificationPreference;
      setNotificationPreference(await updateNotificationPreference(payload));
      setSuccess(t("notificationsSaved"));
    } catch (error) {
      setError(localizedError(error, uiText, t("notificationSaveFailed")));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="account-page">
      <header className="account-header">
        <Link href="/" className="account-brand">
          {brand.enabled ? <BrandIdentity /> : <><ShieldCheck size={26} />{uiText("Common.brand")}</>}
        </Link>
        <div className="account-header-actions">
          <Link href="/dashboard">
            <ArrowLeft size={16} />
             {uiText("Common.interface.backToDashboard")} </Link>
          <LocaleSwitcher compact />
          <ThemeToggle variant="icon" />
          <button className="button secondary" disabled={busy} onClick={logout}>
            <LogOut size={16} />
             {uiText("Common.actions.signOut")} </button>
        </div>
      </header>
      <div className="account-content">
        <span className="eyebrow">{uiText("Common.interface.homeMyAccount")}</span>
        <h1>{uiText("Common.interface.accountSettings")}</h1>
        <p className="account-intro">
          {session.workspace_name} · {localizedRole(user.role, uiText)}
        </p>
        {error && (
          <div className="auth-alert error" role="alert">
            {error}
          </div>
        )}
        {success && (
          <div className="auth-alert success" role="status">
            {success}
          </div>
        )}
        <div className="account-grid">
          <AccountSecurity />
          <section className="card">
            <div className="account-section-head">
              <UserRound size={20} />
              <h2>{uiText("Common.interface.personalInformation")}</h2>
            </div>
            <form className="auth-form" onSubmit={profile}>
              <fieldset disabled={busy}>
                <label>
                   {uiText("Auth.fullName")} <input
                    name="name"
                    required
                    minLength={2}
                    maxLength={120}
                    defaultValue={user.name}
                    autoComplete="name"
                  />
                </label>
                <label>
                   {uiText("Auth.email")} <input readOnly value={user.email} />
                  <small>{uiText("Common.interface.yourSignInEmailCannotBeChangedHere")}</small>
                </label>
                <label>
                   {uiText("Common.interface.mobileNumber")} <input
                    name="phone"
                    type="tel"
                    maxLength={30}
                    defaultValue={user.phone}
                    autoComplete="tel"
                  />
                </label>
                <label>
                   {uiText("Common.interface.role")} <input readOnly value={localizedRole(user.role, uiText)} />
                </label>
                <button className="button primary" type="submit">
                   {uiText("Common.interface.saveProfile")} </button>
              </fieldset>
            </form>
          </section>
          <section className="card">
            <div className="account-section-head">
              <BellRing size={20} />
              <h2>{t("notificationsTitle")}</h2>
            </div>
            <p className="account-intro">{t("notificationsDescription")}</p>
            {notificationPreference && <form className="auth-form" onSubmit={saveNotifications}>
              <fieldset disabled={busy}>
                {(["in_app_enabled", "email_enabled", "whatsapp_enabled"] as const).map((key) => <label key={key} className="auth-checkbox">
                  <input type="checkbox" checked={notificationPreference[key]} onChange={(event) => setNotificationPreference({ ...notificationPreference, [key]: event.target.checked })} />
                  {t(key)}
                </label>)}
                <strong>{t("notificationCategories")}</strong>
                {(["compliance_enabled", "task_enabled", "document_enabled", "system_enabled"] as const).map((key) => <label key={key} className="auth-checkbox">
                  <input type="checkbox" checked={notificationPreference[key]} onChange={(event) => setNotificationPreference({ ...notificationPreference, [key]: event.target.checked })} />
                  {t(key)}
                </label>)}
                <button className="button primary" type="submit">{t("saveNotifications")}</button>
              </fieldset>
            </form>}
          </section>
          <section className="card">
            <div className="account-section-head">
              <Languages size={20} />
              <h2>{t("title")}</h2>
            </div>
            <form className="auth-form" onSubmit={saveLocalization}>
              <fieldset disabled={busy}>
                <div className="account-language-field">
                  <span>{t("preferredLanguage")}</span>
                  <LocaleSwitcher />
                </div>
                <label>
                  {t("timezone")}
                  <span className="password-input">
                    <Clock3 size={17} />
                    <select
                      value={timezone}
                      onChange={(event) => setTimezone(event.target.value)}
                    >
                      <option value="Asia/Kolkata">Asia/Kolkata</option>
                      <option value="Asia/Dubai">Asia/Dubai</option>
                      <option value="Europe/London">Europe/London</option>
                      <option value="America/New_York">America/New_York</option>
                    </select>
                  </span>
                </label>
                <label>
                  {t("timeFormat")}
                  <select
                    value={timeFormat}
                    onChange={(event) =>
                      setTimeFormat(event.target.value as "12h" | "24h")
                    }
                  >
                    <option value="12h">{t("twelveHour")}</option>
                    <option value="24h">{t("twentyFourHour")}</option>
                  </select>
                </label>
                <button className="button primary" type="submit">
                  {t("saveChanges")}
                </button>
              </fieldset>
            </form>
          </section>
          <section className="card">
            <div className="account-section-head">
              <LockKeyhole size={20} />
              <h2>{uiText("Common.interface.changePassword")}</h2>
            </div>
            <p className="account-intro">
               {uiText("Common.interface.changingYourPasswordSignsOutEverySessionIncludingThisOne")} </p>
            <form className="auth-form" onSubmit={password} noValidate>
              <fieldset disabled={busy}>
                <label>
                   {uiText("Common.interface.currentPassword")} <span className="password-input">
                    <input
                      name="current_password"
                      type={showPassword ? "text" : "password"}
                      required
                      maxLength={128}
                      autoComplete="current-password"
                      value={currentPassword}
                      aria-invalid={passwordAttempted && !currentPassword}
                      aria-describedby={
                        passwordAttempted && !currentPassword
                          ? "current-password-error"
                          : undefined
                      }
                      onChange={(event) =>
                        setCurrentPassword(event.target.value)
                      }
                      onKeyDown={detectCapsLock}
                      onKeyUp={detectCapsLock}
                    />
                    <button
                      type="button"
                      aria-label={
                        showPassword ? uiText("Common.interface.hidePasswords") : uiText("Common.interface.showPasswords")
                      }
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                    </button>
                  </span>
                  {passwordAttempted && !currentPassword && (
                    <small className="field-error" id="current-password-error">
                       {uiText("Common.interface.enterYourCurrentPassword")} </small>
                  )}
                  {capsLock && (
                    <small className="caps-warning">{uiText("Authentication.capsLock")}</small>
                  )}
                </label>
                <label>
                   {uiText("Authentication.newPassword")} <span className="password-input">
                    <input
                      name="password"
                      type={showPassword ? "text" : "password"}
                      required
                      minLength={12}
                      maxLength={128}
                      autoComplete="new-password"
                      value={newPassword}
                      aria-invalid={
                        passwordAttempted && Boolean(newPasswordError)
                      }
                      aria-describedby="password-help"
                      onChange={(event) => setNewPassword(event.target.value)}
                      onKeyDown={detectCapsLock}
                      onKeyUp={detectCapsLock}
                    />
                    <button
                      type="button"
                      aria-label={
                        showPassword ? uiText("Common.interface.hidePasswords") : uiText("Common.interface.showPasswords")
                      }
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                    </button>
                  </span>
                  {passwordAttempted && newPasswordError && (
                    <small className="field-error">{uiText(newPassword.length < 12 ? "Authentication.validation.length" : newPassword.length > 128 ? "Authentication.validation.maximum" : newPassword !== newPassword.trim() || /[\u0000-\u001f\u007f]/.test(newPassword) ? "Authentication.validation.spacing" : "Authentication.validation.predictable")}</small>
                  )}
                  <PasswordGuidance password={newPassword} />
                </label>
                <label>
                   {uiText("Common.interface.confirmNewPassword")} <span className="password-input">
                    <input
                      name="confirm_password"
                      type={showPassword ? "text" : "password"}
                      required
                      minLength={12}
                      maxLength={128}
                      autoComplete="new-password"
                      value={confirmPassword}
                      aria-invalid={
                        passwordAttempted && Boolean(confirmPasswordError)
                      }
                      aria-describedby={
                        passwordAttempted && confirmPasswordError
                          ? "account-confirm-error"
                          : undefined
                      }
                      onChange={(event) =>
                        setConfirmPassword(event.target.value)
                      }
                      onKeyDown={detectCapsLock}
                      onKeyUp={detectCapsLock}
                    />
                    <button
                      type="button"
                      aria-label={
                        showPassword ? uiText("Common.interface.hidePasswords") : uiText("Common.interface.showPasswords")
                      }
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                    </button>
                  </span>
                  {passwordAttempted && confirmPasswordError && (
                    <small className="field-error" id="account-confirm-error">
                      {confirmPasswordError}
                    </small>
                  )}
                </label>
                <button className="button primary" type="submit">
                   {uiText("Common.interface.updatePasswordSignOut")} </button>
              </fieldset>
            </form>
          </section>
        </div>
      </div>
    </main>
  );
}
