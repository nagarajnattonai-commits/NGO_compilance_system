"use client";

import { useEffect, useState } from "react";
import { Check, LockKeyhole, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import type { Subscription, SubscriptionPlan } from "@/lib/types";

type Plan = SubscriptionPlan;
type PlatformTenant = {
  tenant_id: string;
  workspace_name: string;
  subscription: Omit<Subscription, "usage" | "features" | "feature_access" | "plans"> | null;
  history: { id: string; actor_name: string; summary: string; created_at: string }[];
};
type Draft = { plan_name: string; status: string; period_start: string; period_end: string; cancel_at_period_end: boolean };
const statuses = ["ACTIVE", "TRIAL", "PAST_DUE", "CANCELLED", "SUSPENDED", "DISABLED"];
function dateAfter(days: number) { const value = new Date(); value.setDate(value.getDate() + days); return value.toISOString().slice(0, 10); }
function planName(t: (key: string) => string, key: string) {
  try { return t(`plans.${key}`); } catch { return key; }
}

function PlanUsage({ label, value, limit, unit = "" }: { label: string; value: number; limit: number | null; unit?: string }) {
  const t = useTranslations("Subscriptions");
  if (limit === null) return <div className="subscription-usage"><div><span>{label}</span><strong>{value}{unit} / Not assigned</strong></div></div>;
  const percentage = limit > 0 ? Math.min(100, Math.round(value / limit * 100)) : 100;
  return (
    <div className="subscription-usage">
      <div><span>{label}</span><strong>{value}{unit} / {limit}{unit}</strong></div>
      <progress max={100} value={percentage} aria-label={`${label}: ${value} / ${limit}${unit}`} />
      {value >= limit && <small className="subscription-upgrade-required"><LockKeyhole size={13} />{t("limitReached")}</small>}
    </div>
  );
}

export function TenantSubscription({ subscription }: { subscription: Subscription }) {
  const t = useTranslations("Subscriptions");
  const plans = subscription.plans || [];
  const usage = subscription.usage || { users: 0, organizations: 0, integrations: 0, storage_bytes: 0, storage_gb: 0 };
  const entitled = new Set(Object.entries(subscription.feature_access || {}).filter(([, enabled]) => enabled).map(([key]) => key));
  const allEntitlements = [...new Set(plans.flatMap((plan) => plan.entitlements))].sort();
  const activePlan = plans.find((plan) => plan.key === subscription.plan_name);
  return (
    <div className="page subscription-page">
      <header className="page-heading">
        <div><span className="eyebrow">{t("eyebrow")}</span><h1>{t("title")}</h1><p>{t("description")}</p></div>
        <span className={`status status-${subscription.status.toLowerCase()}`}><i />{subscription.configured === false ? "Plan not assigned" : t(`statuses.${subscription.status}`)}</span>
      </header>
      <div className="admin-summary subscription-summary">
        <div><span>{t("currentPlan")}</span><strong>{subscription.configured === false ? "Legacy workspace" : planName(t, subscription.plan_name)}</strong><small>{activePlan ? t(`planDescriptions.${subscription.plan_name}`) : t("legacyPlan")}</small></div>
        <div><span>{t("periodStart")}</span><strong>{subscription.period_start || "—"}</strong><small>{t("periodEnd")}: {subscription.period_end || "—"}</small></div>
        <div><span>{t("cancellation")}</span><strong>{t(subscription.cancel_at_period_end ? "scheduled" : "notScheduled")}</strong><small>{subscription.cancel_at_period_end ? t("accessUntilPeriodEnd") : t("contactAdmin")}</small></div>
        <div><span>{t("limits")}</span><strong>{t("planLimits")}</strong><small>{t("serverEnforced")}</small></div>
      </div>
      <section className="card subscription-usage-panel">
        <header className="card-title"><div><h2>{t("usageTitle")}</h2><p>{t("usageDescription")}</p></div></header>
        <div className="subscription-usage-grid">
          <PlanUsage label={t("users")} value={usage.users} limit={subscription.user_limit} />
          <PlanUsage label={t("organizations")} value={usage.organizations} limit={subscription.organization_limit} />
          <PlanUsage label={t("integrations")} value={usage.integrations} limit={subscription.integration_limit ?? (subscription.configured === false ? null : 0)} />
          <PlanUsage label={t("storage")} value={usage.storage_gb} limit={subscription.storage_limit_gb} unit=" GB" />
        </div>
      </section>
      <section className="card subscription-features">
        <header className="card-title"><div><h2>{t("featuresTitle")}</h2><p>{t("featuresDescription")}</p></div></header>
        <ul>{(activePlan?.features || []).map((feature) => (
          <li key={feature}><Check size={16} /><span>{t(`features.${feature}`)}</span></li>
        ))}</ul>
        {allEntitlements.length > 0 && <div className="subscription-entitlements">
          {allEntitlements.map((feature) => (
            <div key={feature} className={entitled.has(feature) ? "entitlement-enabled" : "entitlement-locked"}>
              {entitled.has(feature) ? <Check size={15} /> : <LockKeyhole size={15} />}
              <span>{t(`features.${feature}`)}</span>
              {!entitled.has(feature) && <small>{t("upgradeRequired")}</small>}
            </div>
          ))}
        </div>}
        <p className="plan-note">{t("noPaymentCollection")}</p>
      </section>
      <section className="subscription-plan-grid" aria-label={t("plansTitle")}>
        {plans.map((plan) => (
          <article className={`card subscription-plan-option${plan.key === subscription.plan_name ? " current" : ""}`} key={plan.key}>
            <header><h2>{planName(t, plan.key)}</h2>{plan.key === subscription.plan_name && <span>{t("currentPlan")}</span>}</header>
            <p>{t(`planDescriptions.${plan.key}`)}</p>
            <ul>{plan.features.map((feature) => <li key={feature}>{t(`features.${feature}`)}</li>)}</ul>
            <small>{t("contactAdmin")}</small>
          </article>
        ))}
      </section>
      <section className="card subscription-history">
        <header className="card-title"><div><h2>{t("historyTitle")}</h2><p>{t("historyDescription")}</p></div></header>
        {!subscription.history?.length ? <p>{t("noHistory")}</p> : <ul>{subscription.history.map((event) => (
          <li key={event.id}><strong>{event.summary}</strong><span>{event.actor_name}</span><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time></li>
        ))}</ul>}
      </section>
    </div>
  );
}

export default function PlatformSubscriptions() {
  const t = useTranslations("Subscriptions");
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  async function refresh() {
    const result = await apiRequest<{items: PlatformTenant[]; plans: Plan[]}>("/platform/subscriptions");
    setTenants(result.items);
    setPlans(result.plans);
    setDrafts(Object.fromEntries(result.items.map((row) => [row.tenant_id, {
      plan_name: row.subscription?.plan_name || "STARTER",
      status: row.subscription?.status || "ACTIVE",
      period_start: row.subscription?.period_start || dateAfter(0),
      period_end: row.subscription?.period_end || dateAfter(30),
      cancel_at_period_end: row.subscription?.cancel_at_period_end || false,
    }])));
  }
  useEffect(() => { refresh().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : t("loadError"))); }, []);
  async function save(tenantId: string) {
    const draft = drafts[tenantId];
    if (!draft || busy) return;
    setBusy(tenantId); setError("");
    try {
      await apiRequest(`/platform/subscriptions/${encodeURIComponent(tenantId)}`, "PUT", {
        plan_name: draft.plan_name, status: draft.status,
        period_start: draft.period_start || null, period_end: draft.period_end,
        cancel_at_period_end: draft.cancel_at_period_end,
      });
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("saveFailed")); }
    finally { setBusy(null); }
  }
  function change(tenantId: string, key: keyof Draft, value: string | boolean) {
    setDrafts((current) => ({ ...current, [tenantId]: { ...current[tenantId], [key]: value } }));
  }
  return (
    <main className="account-content platform-subscriptions-page">
      <header className="page-heading"><div><span className="eyebrow">{t("platformEyebrow")}</span><h1>{t("platformTitle")}</h1><p>{t("platformDescription")}</p></div></header>
      {error && <p className="auth-alert error" role="alert">{error}</p>}
      {!tenants.length && <p>{t("noTenants")}</p>}
      <div className="platform-subscription-list">{tenants.map((tenant) => {
        const draft = drafts[tenant.tenant_id];
        if (!draft) return null;
        return (
          <section className="card platform-subscription-row" key={tenant.tenant_id}>
            <header><div><h2>{tenant.workspace_name}</h2><code>{tenant.tenant_id}</code></div>
              {tenant.subscription && <span className={`status status-${tenant.subscription.status.toLowerCase()}`}><i />{t(`statuses.${tenant.subscription.status}`)}</span>}
            </header>
            <div className="platform-subscription-fields">
              <label>{t("plan")}<select value={draft.plan_name} onChange={(event) => change(tenant.tenant_id, "plan_name", event.target.value)}>{plans.map((plan) => <option value={plan.key} key={plan.key}>{planName(t, plan.key)}</option>)}</select></label>
              <label>{t("status")}<select value={draft.status} onChange={(event) => change(tenant.tenant_id, "status", event.target.value)}>{statuses.map((status) => <option value={status} key={status}>{t(`statuses.${status}`)}</option>)}</select></label>
              <label>{t("periodStart")}<input type="date" value={draft.period_start} onChange={(event) => change(tenant.tenant_id, "period_start", event.target.value)} /></label>
              <label>{t("periodEnd")}<input type="date" required value={draft.period_end} onChange={(event) => change(tenant.tenant_id, "period_end", event.target.value)} /></label>
              <label className="subscription-cancel-toggle"><input type="checkbox" checked={draft.cancel_at_period_end} onChange={(event) => change(tenant.tenant_id, "cancel_at_period_end", event.target.checked)} />{t("cancelAtPeriodEnd")}</label>
              <button type="button" className="button primary" disabled={busy !== null} onClick={() => void save(tenant.tenant_id)}><Save size={16} />{busy === tenant.tenant_id ? t("saving") : t("savePlan")}</button>
            </div>
            {!!tenant.history.length && <details className="platform-subscription-history"><summary>{t("historyTitle")}</summary><ul>{tenant.history.map((event) => <li key={event.id}><strong>{event.summary}</strong><span>{event.actor_name}</span><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time></li>)}</ul></details>}
          </section>
        );
      })}</div>
    </main>
  );
}
