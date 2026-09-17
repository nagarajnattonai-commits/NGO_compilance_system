"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import type { BrandingSettings } from "@/branding/types";
import { formatDateTime } from "@/i18n/format";
import LocaleSwitcher from "./locale-switcher";
import ThemeToggle from "./theme-toggle";

type PlatformTenant = BrandingSettings & {
  tenant_id: string;
  workspace_name: string;
};
export default function PlatformWhiteLabel() {
  const t = useTranslations("WhiteLabel");
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () =>
    apiRequest<PlatformTenant[]>("/platform/white-label").then(setTenants);
  useEffect(() => {
    refresh().catch((e: unknown) =>
      setError(e instanceof Error ? e.message : t("failed")),
    );
  }, [t]);
  async function action(path: string, method = "POST", body?: unknown) {
    if (!window.confirm(t("platformConfirm"))) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(path, method, body);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("failed"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="account-page brand-platform-page">
      <header className="account-header">
        <Link className="account-brand" href="/admin">
          {t("platformManagement")}
        </Link>
        <LocaleSwitcher compact />
        <ThemeToggle variant="icon" />
      </header>
      <div className="account-content">
        <h1>{t("platformManagement")}</h1>
        <p className="account-intro">{t("platformDescription")}</p>
        {error && (
          <p className="auth-alert error" role="alert">
            {error}
          </p>
        )}
        {!tenants.length && <p>{t("noTenants")}</p>}
        {tenants.map((tenant) => (
          <section
            className="card brand-platform-tenant"
            key={tenant.tenant_id}
          >
            <h2>{tenant.workspace_name}</h2>
            <p>
              {t("tenant")}: <code>{tenant.tenant_id}</code>
            </p>
            <p>
              {t(`states.${tenant.status}`)} · {t("activeVersion")}:{" "}
              {tenant.published_version ?? "—"} · {t("entitlement")}:{" "}
              {t(tenant.entitled ? "states.ACTIVE" : "states.DISABLED")}
            </p>
            <div className="brand-editor-actions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void action(
                    `/platform/white-label/${tenant.tenant_id}/entitlement`,
                    "PUT",
                    { enabled: !tenant.entitled },
                  )
                }
              >
                {t(
                  tenant.entitled ? "disableEntitlement" : "enableEntitlement",
                )}
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void action(
                    `/platform/white-label/${tenant.tenant_id}/action`,
                    "POST",
                    {
                      action:
                        tenant.status === "SUSPENDED" ? "RESUME" : "SUSPEND",
                    },
                  )
                }
              >
                {t(tenant.status === "SUSPENDED" ? "resume" : "suspend")}
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void action(
                    `/platform/white-label/${tenant.tenant_id}/action`,
                    "POST",
                    { action: "RESET" },
                  )
                }
              >
                {t("reset")}
              </button>
            </div>
            <div className="brand-history">
              {tenant.domains.map((domain) => (
                <div key={domain.id}>
                  <span>
                    <strong title={domain.hostname}>{domain.hostname}</strong>
                    <small>
                      {t(`states.${domain.status}`)} · {t("ssl")}:{" "}
                      {t(`states.${domain.ssl_status}`)}
                    </small>
                  </span>
                  <button
                    className="button secondary small"
                    disabled={busy}
                    onClick={() =>
                      void action(
                        `/platform/white-label/${tenant.tenant_id}/domains/${domain.id}/${domain.platform_suspended ? "resume" : "suspend"}`,
                      )
                    }
                  >
                    {t(domain.platform_suspended ? "resume" : "suspend")}
                  </button>
                </div>
              ))}
            </div>
            <details>
              <summary>{t("auditHistory")}</summary>
              <div className="brand-history">
                {tenant.audit_events.map((event, index) => (
                  <div key={`${event.created_at}-${index}`}>
                    <span>
                      <strong>{event.action}</strong>
                      <small>
                        {event.actor_name} · {formatDateTime(event.created_at)}
                      </small>
                      <small>{event.summary}</small>
                    </span>
                  </div>
                ))}
              </div>
            </details>
          </section>
        ))}
      </div>
    </main>
  );
}
