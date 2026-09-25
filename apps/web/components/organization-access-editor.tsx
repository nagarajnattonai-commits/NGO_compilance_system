"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { AuthUser } from "@/lib/auth-types";
import type { OrganizationAccess } from "@/lib/types";
import { apiRequest } from "@/lib/http";
import { grantOrganizationAccess, loadOrganizationAccess, revokeOrganizationAccess } from "@/lib/api";

export default function OrganizationAccessEditor({ id }: { id: string }) {
  const t = useTranslations("Organization");
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [rows, setRows] = useState<OrganizationAccess[]>([]);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<OrganizationAccess["access_role"]>("CONTRIBUTOR");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const [accounts, access] = await Promise.all([
        apiRequest<AuthUser[]>("/admin/users"),
        loadOrganizationAccess(id),
      ]);
      const eligible = accounts.filter((item) => item.status === "ACTIVE" && item.role !== "ADMIN");
      setUsers(eligible);
      setRows(access);
      setUserId((current) => current || eligible[0]?.id || "");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t("error"));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void refresh(); }, [id]);

  async function grant(event: React.FormEvent) {
    event.preventDefault();
    if (!userId) return;
    setBusy(true);
    try {
      await grantOrganizationAccess(id, userId, role);
      await refresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t("error"));
      setBusy(false);
    }
  }

  async function revoke(row: OrganizationAccess) {
    setBusy(true);
    try {
      await revokeOrganizationAccess(id, row.user_id);
      await refresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t("error"));
      setBusy(false);
    }
  }

  return <section>
    <h3>{t("organizationAccess")}</h3>
    <p>{t("organizationAccessHelp")}</p>
    {error && <p className="auth-alert error" role="alert">{error}</p>}
    <ul className="organization-records">
      {rows.filter((row) => row.status === "ACTIVE").map((row) => <li key={row.id}>
        <span>{row.user_name} · {row.user_email} · {t(`accessRole.${row.access_role}`)}</span>
        <button className="text-button" disabled={busy} onClick={() => void revoke(row)}>{t("revokeAccess")}</button>
      </li>)}
    </ul>
    {!busy && !rows.some((row) => row.status === "ACTIVE") && <p>{t("noOrganizationAccess")}</p>}
    <form className="organization-form" onSubmit={(event) => void grant(event)}>
      <label>{t("loginAccount")}
        <select required value={userId} disabled={busy} onChange={(event) => setUserId(event.target.value)}>
          <option value="">{t("selectAccount")}</option>
          {users.map((user) => <option key={user.id} value={user.id}>{user.name} · {user.email}</option>)}
        </select>
      </label>
      <label>{t("accessScope")}
        <select value={role} disabled={busy} onChange={(event) => setRole(event.target.value as OrganizationAccess["access_role"])}>
          {(["VIEWER", "CONTRIBUTOR", "MANAGER"] as const).map((value) => <option key={value} value={value}>{t(`accessRole.${value}`)}</option>)}
        </select>
      </label>
      <div className="organization-actions"><button className="button primary" disabled={busy || !userId}>{t("grantAccess")}</button></div>
    </form>
  </section>;
}
