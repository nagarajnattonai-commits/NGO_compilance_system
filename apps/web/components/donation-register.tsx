"use client";

import { localizedError } from "@/i18n/display";
import { formatCurrency, formatShortDate } from "@/i18n/format";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { apiRequest } from "@/lib/http";
import type { AuthUser } from "@/lib/auth-types";
import type { ComplianceDocument } from "@/lib/types";

type Account = { id: string; label: string; bank_name: string; last_four: string; kind: string; active: boolean };
type Donor = { id: string; name: string; donor_type: string; id_type: string; has_identity: boolean; is_foreign_source: boolean; id_masked?: string; address?: string; email?: string; phone?: string };
type Donation = {
  id: string; donor_id: string; donor_name: string; received_on: string; financial_year: string; amount_paise: number; currency: string;
  mode: string; donation_type: string; purpose: string; reference: string; bank_account_label: string; fcra_flag: boolean; status: string;
  created_by_name: string; confirmed_by: string; reversal_reason: string; receipt: { receipt_number: string; issued_on: string } | null; warnings: string[];
};
type Certificate = { id: string; donor_name: string; amount_paise: number; certificate_number: string; status: string; sent_on: string | null };
type Statement = {
  financial_year: string; due_on: string;
  totals: { confirmed_count: number; confirmed_paise: number; draft_count: number; reversed_count: number; foreign_count: number; cash_above_limit: number };
  donor_issues: Array<{ donor_id: string; donor_name: string; missing: string[] }>;
  statement: { id: string; status: string; filed_on: string | null; acknowledgement_number: string; document_id: string | null } | null;
  certificates: Certificate[];
};

const tabs = ["donations", "donors", "statement", "accounts"] as const;
const modes = ["BANK_TRANSFER", "UPI", "CHEQUE", "CARD", "CASH", "IN_KIND"];
const donationTypes = ["GENERAL", "CORPUS", "SPECIFIC_GRANT"];
const donorTypes = ["INDIVIDUAL", "COMPANY", "TRUST", "FOREIGN_SOURCE", "ANONYMOUS", "OTHER"];
const accountKinds = ["DOMESTIC", "FCRA_DESIGNATED", "FCRA_UTILISATION"];

function currentYear(day = new Date()) {
  const start = day.getMonth() >= 3 ? day.getFullYear() : day.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}
const money = (paise: number, currency = "INR") => formatCurrency(paise / 100, currency);

export default function DonationRegister({ organizationId, user, documents }: { organizationId: string; user: AuthUser; documents: ComplianceDocument[] }) {
  const uiText = useTranslations();
  const t = useTranslations("Donations");
  const [tab, setTab] = useState<(typeof tabs)[number]>("donations");
  const [year, setYear] = useState(currentYear());
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [donors, setDonors] = useState<Donor[]>([]);
  const [donations, setDonations] = useState<Donation[]>([]);
  const [statement, setStatement] = useState<Statement | null>(null);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const canWrite = user.role !== "VIEWER";
  const admin = user.role === "ADMIN";
  const start = Number(year.slice(0, 4));
  const years = Array.from({ length: 6 }, (_, index) => currentYear(new Date(Number(currentYear().slice(0, 4)) - index, 6, 1)));
  const scope = `organization_id=${encodeURIComponent(organizationId)}`;

  async function load() {
    setError("");
    try {
      const [accountRows, donorRows, donationRows, summary] = await Promise.all([
        apiRequest<Account[]>(`/donations/bank-accounts?${scope}`),
        apiRequest<Donor[]>(`/donations/donors?${scope}&q=${encodeURIComponent(query)}`),
        apiRequest<Donation[]>(`/donations?${scope}&financial_year=${year}`),
        apiRequest<Statement>(`/donations/statement?${scope}&financial_year=${year}`),
      ]);
      setAccounts(accountRows); setDonors(donorRows); setDonations(donationRows); setStatement(summary);
    } catch (reason) { setError(localizedError(reason, uiText, t("loadError"))); }
  }
  useEffect(() => { void load(); }, [organizationId, year]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(path: string, method: string, body?: unknown, done = t("saved")): Promise<boolean> {
    setBusy(true); setError(""); setMessage("");
    try { await apiRequest(path, method, body); await load(); setMessage(done); return true; }
    catch (reason) { setError(localizedError(reason, uiText, t("saveError"))); return false; }
    finally { setBusy(false); }
  }
  function submit(event: FormEvent<HTMLFormElement>, path: string, build: (data: FormData) => unknown) {
    event.preventDefault();
    const form = event.currentTarget;
    void act(path, "POST", build(new FormData(form))).then((saved) => { if (saved) form.reset(); });
  }
  async function reveal(donor: Donor) {
    setError("");
    try {
      const result = await apiRequest<{ id_number: string }>(`/donations/donors/${donor.id}/reveal-identity`, "POST");
      setRevealed((items) => ({ ...items, [donor.id]: result.id_number }));
    } catch (reason) { setError(localizedError(reason, uiText, t("saveError"))); }
  }
  async function issueReceipt(donation: Donation) {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await apiRequest<{ receipt_warning: string | null }>(`/donations/${donation.id}/receipt`, "POST", {});
      await load();
      if (result.receipt_warning) setError(t(`warnings.${result.receipt_warning}`)); else setMessage(t("receiptIssued"));
    } catch (reason) { setError(localizedError(reason, uiText, t("saveError"))); }
    finally { setBusy(false); }
  }
  function reverse(donation: Donation) {
    const reason = window.prompt(t("reversePrompt"));
    if (reason && reason.trim().length >= 5) void act(`/donations/${donation.id}/reverse`, "POST", { reason: reason.trim() });
    else if (reason !== null) setError(t("reverseReasonShort"));
  }
  const text = (data: FormData, key: string) => String(data.get(key) || "").trim();
  const paise = (value: string) => Math.round(Number(value) * 100);
  const orgDocuments = documents.filter((item) => item.organization_id === organizationId);

  return <div className="donation-register">
    <div className="notice info"><strong>{t("rulesNotice")}</strong></div>
    {error && <p className="auth-alert error" role="alert">{error}</p>}
    {message && <p className="auth-alert success" role="status">{message}</p>}
    <div className="organization-form">
      <label>{t("financialYear")}<select value={year} onChange={(event) => setYear(event.target.value)}>{years.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
    </div>
    <nav className="organization-tabs" role="tablist" aria-label={t("title")}>{tabs.map((value) => <button key={value} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>{t(`tabs.${value}`)}</button>)}</nav>

    {tab === "donations" && <section aria-labelledby="donations-heading">
      <h3 id="donations-heading">{t("donationsFor", { year })}</h3>
      {canWrite && donors.length > 0 && <form onSubmit={(event) => submit(event, "/donations", (data) => ({
        organization_id: organizationId, donor_id: text(data, "donor_id"), received_on: text(data, "received_on"), amount_paise: paise(text(data, "amount")),
        currency: text(data, "currency") || "INR", mode: text(data, "mode"), donation_type: text(data, "donation_type"),
        bank_account_id: text(data, "bank_account_id") || null, purpose: text(data, "purpose"), reference: text(data, "reference"),
      }))}>
        <div className="organization-form">
          <label>{t("donor")}<select name="donor_id" required>{donors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>{t("receivedOn")}<input name="received_on" type="date" required min={`${start}-04-01`} max={`${start + 1}-03-31`} /></label>
          <label>{t("amount")}<input name="amount" type="number" min="0.01" step="0.01" required inputMode="decimal" /></label>
          <label>{t("currency")}<input name="currency" defaultValue="INR" pattern="[A-Z]{3}" maxLength={3} /></label>
          <label>{t("mode")}<select name="mode">{modes.map((value) => <option key={value} value={value}>{t(`modes.${value}`)}</option>)}</select></label>
          <label>{t("donationType")}<select name="donation_type">{donationTypes.map((value) => <option key={value} value={value}>{t(`types.${value}`)}</option>)}</select></label>
          <label>{t("bankAccount")}<select name="bank_account_id"><option value="">{t("noAccount")}</option>{accounts.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.label} · {t(`accountKinds.${item.kind}`)}</option>)}</select></label>
          <label>{t("purpose")}<input name="purpose" maxLength={300} /></label>
          <label>{t("reference")}<input name="reference" maxLength={120} /></label>
        </div>
        <div className="organization-actions"><button className="button primary" disabled={busy}>{t("recordDonation")}</button></div>
      </form>}
      {canWrite && !donors.length && <p>{t("addDonorFirst")}</p>}
      <div className="report-table-scroll"><table className="report-table"><thead><tr><th>{t("receivedOn")}</th><th>{t("donor")}</th><th>{t("amount")}</th><th>{t("mode")}</th><th>{t("status")}</th><th>{t("receipt")}</th><th>{t("checks")}</th><th>{t("actions")}</th></tr></thead>
        <tbody>{donations.map((item) => <tr key={item.id}>
          <td>{formatShortDate(item.received_on)}</td>
          <td><strong>{item.donor_name}</strong>{item.fcra_flag && <><br /><small>{t("foreignContribution")}</small></>}</td>
          <td>{money(item.amount_paise, item.currency)}<br /><small>{t(`types.${item.donation_type}`)}</small></td>
          <td>{t(`modes.${item.mode}`)}{item.bank_account_label && <><br /><small>{item.bank_account_label}</small></>}</td>
          <td><span>{t(`statuses.${item.status}`)}</span><br /><small>{item.status === "REVERSED" ? item.reversal_reason : item.confirmed_by ? t("confirmedBy", { name: item.confirmed_by }) : t("recordedBy", { name: item.created_by_name })}</small></td>
          <td>{item.receipt ? item.receipt.receipt_number : "—"}</td>
          <td>{item.warnings.length ? <ul className="plain-list">{item.warnings.map((code) => <li key={code}>{t(`warnings.${code}`)}</li>)}</ul> : t("noIssues")}</td>
          <td>{canWrite && <div className="organization-actions">
            {item.status === "DRAFT" && <><button type="button" className="text-button" disabled={busy} onClick={() => void act(`/donations/${item.id}/confirm`, "POST")}>{t("confirm")}</button>
              <button type="button" className="text-button" disabled={busy} onClick={() => { if (window.confirm(t("deleteDraftConfirm"))) void act(`/donations/${item.id}`, "DELETE"); }}>{t("deleteDraft")}</button></>}
            {item.status === "CONFIRMED" && !item.receipt && <button type="button" className="text-button" disabled={busy} onClick={() => void issueReceipt(item)}>{t("issueReceipt")}</button>}
            {item.status === "CONFIRMED" && admin && <button type="button" className="text-button" disabled={busy} onClick={() => reverse(item)}>{t("reverse")}</button>}
          </div>}</td>
        </tr>)}</tbody></table></div>
      {!donations.length && <p className="muted">{t("emptyDonations")}</p>}
    </section>}

    {tab === "donors" && <section aria-labelledby="donors-heading">
      <h3 id="donors-heading">{t("tabs.donors")}</h3>
      <form className="organization-form" onSubmit={(event) => { event.preventDefault(); void load(); }}>
        <label>{t("search")}<input value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} /></label>
      </form>
      {canWrite && <form onSubmit={(event) => submit(event, "/donations/donors", (data) => ({
        organization_id: organizationId, name: text(data, "name"), donor_type: text(data, "donor_type"), id_type: text(data, "id_type"),
        id_number: text(data, "id_number"), address: text(data, "address"), email: text(data, "email"), phone: text(data, "phone"),
        is_foreign_source: data.get("is_foreign_source") === "on", consent_to_contact: data.get("consent_to_contact") === "on",
      }))}>
        <div className="organization-form">
          <label>{t("donorName")}<input name="name" required minLength={2} maxLength={200} /></label>
          <label>{t("donorType")}<select name="donor_type">{donorTypes.map((value) => <option key={value} value={value}>{t(`donorTypes.${value}`)}</option>)}</select></label>
          <label>{t("idType")}<select name="id_type"><option value="NONE">{t("idTypes.NONE")}</option><option value="PAN">PAN</option><option value="AADHAAR">Aadhaar</option></select></label>
          <label>{t("idNumber")}<input name="id_number" maxLength={20} autoComplete="off" /></label>
          <label>{t("address")}<input name="address" maxLength={500} /></label>
          <label>{t("email")}<input name="email" type="email" maxLength={200} /></label>
          <label>{t("phone")}<input name="phone" type="tel" maxLength={30} /></label>
          <label><span><input name="is_foreign_source" type="checkbox" /> {t("foreignSource")}</span></label>
          <label><span><input name="consent_to_contact" type="checkbox" /> {t("consentToContact")}</span></label>
        </div>
        <p className="muted">{t("identityHelp")}</p>
        <div className="organization-actions"><button className="button primary" disabled={busy}>{t("addDonor")}</button></div>
      </form>}
      <div className="report-table-scroll"><table className="report-table"><thead><tr><th>{t("donorName")}</th><th>{t("donorType")}</th><th>{t("identity")}</th><th>{t("contact")}</th></tr></thead>
        <tbody>{donors.map((item) => <tr key={item.id}>
          <td><strong>{item.name}</strong>{item.is_foreign_source && <><br /><small>{t("foreignSource")}</small></>}</td>
          <td>{t(`donorTypes.${item.donor_type}`)}</td>
          <td>{item.has_identity ? <>{item.id_type === "PAN" ? "PAN" : "Aadhaar"} {revealed[item.id] || item.id_masked || ""}{admin && !revealed[item.id] && <> <button type="button" className="text-button" onClick={() => void reveal(item)}>{t("reveal")}</button></>}</> : t("identityMissing")}</td>
          <td>{item.email || ""}{item.phone ? <><br />{item.phone}</> : null}{item.address === "" && <><br /><small>{t("addressMissing")}</small></>}</td>
        </tr>)}</tbody></table></div>
      {!donors.length && <p className="muted">{t("emptyDonors")}</p>}
    </section>}

    {tab === "statement" && statement && <section aria-labelledby="statement-heading">
      <h3 id="statement-heading">{t("statementTitle", { year })}</h3>
      <p>{t("statementHelp", { date: formatShortDate(statement.due_on) })}</p>
      <div className="report-metrics">
        {([["confirmedTotal", money(statement.totals.confirmed_paise)], ["confirmedCount", statement.totals.confirmed_count], ["draftCount", statement.totals.draft_count],
          ["reversedCount", statement.totals.reversed_count], ["foreignCount", statement.totals.foreign_count], ["cashAboveLimit", statement.totals.cash_above_limit]] as Array<[string, string | number]>)
          .map(([key, value]) => <article className="report-metric" key={key}><span>{t(`totals.${key}`)}</span><strong>{value}</strong></article>)}
      </div>
      {statement.totals.draft_count > 0 && <p className="auth-alert error">{t("draftsPending", { count: statement.totals.draft_count })}</p>}
      <h4>{t("donorGaps")}</h4>
      {statement.donor_issues.length ? <ul className="plain-list">{statement.donor_issues.map((item) => <li key={item.donor_id}><strong>{item.donor_name}</strong>: {item.missing.map((code) => t(`missing.${code}`)).join(", ")}</li>)}</ul> : <p>{t("noGaps")}</p>}
      {!statement.statement && canWrite && <div className="organization-actions"><button type="button" className="button primary" disabled={busy} onClick={() => void act("/donations/statement", "POST", { organization_id: organizationId, financial_year: year })}>{t("prepareStatement")}</button></div>}
      {statement.statement && <>
        <p>{t("statementStatus")}: {t(`statuses.${statement.statement.status}`)}{statement.statement.acknowledgement_number && ` · ${statement.statement.acknowledgement_number}`}</p>
        {canWrite && statement.statement.status !== "FILED" && <form onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget);
          void act(`/donations/statement/${statement.statement!.id}`, "PATCH", { status: "FILED", filed_on: text(data, "filed_on"), acknowledgement_number: text(data, "acknowledgement_number"), document_id: text(data, "document_id") || null }); }}>
          <div className="organization-form">
            <label>{t("filedOn")}<input name="filed_on" type="date" required /></label>
            <label>{t("acknowledgement")}<input name="acknowledgement_number" required maxLength={80} /></label>
            <label>{t("acknowledgementDocument")}<select name="document_id"><option value="">{t("noDocument")}</option>{orgDocuments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          </div>
          <div className="organization-actions"><button className="button primary" disabled={busy}>{t("markFiled")}</button></div>
        </form>}
        {statement.statement.status === "FILED" && <>
          <h4>{t("certificates")}</h4>
          <p className="muted">{t("certificatesHelp")}</p>
          <div className="report-table-scroll"><table className="report-table"><thead><tr><th>{t("donor")}</th><th>{t("amount")}</th><th>{t("certificateNumber")}</th><th>{t("status")}</th></tr></thead>
            <tbody>{statement.certificates.map((item) => <tr key={item.id}><td>{item.donor_name}</td><td>{money(item.amount_paise)}</td>
              <td colSpan={2}>{canWrite ? <form className="organization-actions" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget);
                void act(`/donations/certificates/${item.id}`, "PATCH", { certificate_number: text(data, "certificate_number"), status: text(data, "status") }); }}>
                <input name="certificate_number" aria-label={t("certificateNumber")} defaultValue={item.certificate_number} maxLength={80} />
                <select name="status" aria-label={t("status")} defaultValue={item.status}>{["PENDING", "ISSUED", "SENT"].map((value) => <option key={value} value={value}>{t(`certificateStatus.${value}`)}</option>)}</select>
                <button className="button secondary" disabled={busy}>{t("save")}</button></form>
                : <>{item.certificate_number || "—"} · {t(`certificateStatus.${item.status}`)}</>}</td></tr>)}</tbody></table></div>
          {!statement.certificates.length && <p className="muted">{t("noCertificates")}</p>}
        </>}
      </>}
    </section>}

    {tab === "accounts" && <section aria-labelledby="accounts-heading">
      <h3 id="accounts-heading">{t("tabs.accounts")}</h3>
      <p className="muted">{t("accountsHelp")}</p>
      {canWrite && <form onSubmit={(event) => submit(event, "/donations/bank-accounts", (data) => ({
        organization_id: organizationId, label: text(data, "label"), bank_name: text(data, "bank_name"), last_four: text(data, "last_four"), kind: text(data, "kind"),
      }))}>
        <div className="organization-form">
          <label>{t("accountLabel")}<input name="label" required minLength={2} maxLength={120} /></label>
          <label>{t("bankName")}<input name="bank_name" maxLength={120} /></label>
          <label>{t("lastFour")}<input name="last_four" pattern="[0-9]{4}" maxLength={4} inputMode="numeric" /></label>
          <label>{t("accountKind")}<select name="kind">{accountKinds.map((value) => <option key={value} value={value}>{t(`accountKinds.${value}`)}</option>)}</select></label>
        </div>
        <div className="organization-actions"><button className="button primary" disabled={busy}>{t("addAccount")}</button></div>
      </form>}
      <ul className="organization-records">{accounts.map((item) => <li key={item.id}>
        <strong>{item.label}</strong> · {t(`accountKinds.${item.kind}`)}{item.bank_name && ` · ${item.bank_name}`}{item.last_four && ` · ••${item.last_four}`}{!item.active && ` · ${t("inactive")}`}
        {canWrite && <button type="button" className="text-button" disabled={busy} onClick={() => void act(`/donations/bank-accounts/${item.id}`, "PATCH", { active: !item.active })}>{item.active ? t("deactivate") : t("activate")}</button>}
      </li>)}</ul>
      {!accounts.length && <p className="muted">{t("emptyAccounts")}</p>}
    </section>}
  </div>;
}
