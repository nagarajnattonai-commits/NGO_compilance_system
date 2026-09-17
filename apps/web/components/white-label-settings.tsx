"use client";

function navigateTabs(event: React.KeyboardEvent<HTMLDivElement>) {
  const buttons = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
  );
  const index = buttons.indexOf(event.target as HTMLButtonElement);
  if (
    index < 0 ||
    !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
  )
    return;
  event.preventDefault();
  const rtl = document.documentElement.dir === "rtl";
  const forward = event.key === (rtl ? "ArrowLeft" : "ArrowRight");
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? buttons.length - 1
        : (index + (forward ? 1 : -1) + buttons.length) % buttons.length;
  buttons[next].focus();
  buttons[next].click();
}

import Link from "next/link";
import { useEffect, useState, type CSSProperties } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Eye,
  Globe2,
  Palette,
  RotateCcw,
  Save,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";
import {
  addBrandDomain,
  disableBrandDomain,
  discardBrand,
  loadBranding,
  loadBrandVersion,
  primaryBrandDomain,
  publishBrand,
  removeBrandAsset,
  resetBrand,
  saveBrandDraft,
  verifyBrandDomain,
} from "@/branding/api";
import {
  assetTypes,
  type AssetType,
  type BrandConfiguration,
  type BrandingSettings,
  type TenantDomain,
  type ThemeTokens,
} from "@/branding/types";
import {
  contrast,
  defaultDark,
  defaultLight,
  themeVariables,
} from "@/branding/theme";
import { supportedLocales } from "@/i18n/config";
import { formatDateTime } from "@/i18n/format";
import { apiRequest } from "@/lib/http";
import BrandAssetUploader from "./brand-asset-uploader";

const tabs = [
  "brand",
  "theme",
  "login",
  "domain",
  "email",
  "reports",
  "support",
  "advanced",
  "preview",
] as const;
type Tab = (typeof tabs)[number];
type TextField =
  | "brand_name"
  | "product_name"
  | "legal_company_name"
  | "short_name"
  | "tagline"
  | "description"
  | "support_email"
  | "support_phone"
  | "support_url"
  | "website_url"
  | "privacy_url"
  | "terms_url"
  | "footer_text"
  | "sender_name"
  | "reply_to"
  | "email_signature"
  | "email_footer"
  | "report_footer";
const limits: Partial<Record<TextField, number>> = {
  brand_name: 160,
  product_name: 160,
  short_name: 24,
  legal_company_name: 200,
  tagline: 200,
  description: 600,
  support_email: 200,
  support_phone: 40,
  sender_name: 120,
  reply_to: 200,
  email_signature: 600,
  email_footer: 600,
  report_footer: 600,
};

function BrandPreview({
  configuration,
  settings,
  dark,
}: {
  configuration: BrandConfiguration;
  settings: BrandingSettings;
  dark: boolean;
}) {
  const t = useTranslations("WhiteLabel");
  const locale = useLocale();
  const [screen, setScreen] = useState<
    "dashboard" | "login" | "email" | "report"
  >("dashboard");
  const selected =
    screen === "login"
      ? configuration.assets.LOGIN_LOGO
      : screen === "report"
        ? configuration.assets.REPORT_LOGO
        : dark
          ? configuration.assets.DARK_LOGO
          : configuration.assets.LIGHT_LOGO;
  const logoId = selected || configuration.assets.PRIMARY_LOGO;
  const logo = settings.assets.find((asset) => asset.id === logoId)?.url;
  const theme = dark ? configuration.dark : configuration.light;
  const tagline =
    configuration.localized_taglines[locale] || configuration.tagline;
  return (
    <aside className="card brand-live-preview">
      <div className="card-title">
        <div>
          <h2>
            <Eye size={17} /> {t("livePreview")}
          </h2>
          <p>{t("previewHelp")}</p>
        </div>
        <span className="brand-preview-badge">{t("previewMode")}</span>
      </div>
      <div
        className="brand-preview-switch"
        role="tablist"
        aria-label={t("livePreview")}
        onKeyDown={navigateTabs}
      >
        {(["dashboard", "login", "email", "report"] as const).map((name) => (
          <button
            type="button"
            role="tab"
            aria-selected={screen === name}
            key={name}
            onClick={() => setScreen(name)}
          >
            {t(`previewScreens.${name}`)}
          </button>
        ))}
      </div>
      <div
        className="brand-preview-frame"
        data-preview-theme={dark ? "dark" : "light"}
        style={themeVariables(theme, dark) as CSSProperties}
      >
        <header>
          {logo ? (
            <img src={logo} alt={configuration.brand_name} />
          ) : (
            <ShieldCheck size={26} />
          )}
          <strong title={configuration.product_name}>
            {configuration.product_name || t("title")}
          </strong>
        </header>
        {screen === "dashboard" && (
          <div className="brand-preview-dashboard">
            <nav>
              <span>{t("previewScreens.dashboard")}</span>
              <span>{t("previewCompliance")}</span>
              <span>{t("previewScreens.report")}</span>
            </nav>
            <section>
              <small>{t("providerIdentity")}</small>
              <h3 title={tagline}>{tagline}</h3>
              <article>
                <strong>{t("clientIdentity")}</strong>
                <p>{t("identityHelp")}</p>
                <button type="button" disabled>
                  {t("sampleButton")}
                </button>
              </article>
            </section>
          </div>
        )}
        {screen === "login" && (
          <section className="brand-preview-login">
            <h3>{t("welcome")}</h3>
            <p>{tagline}</p>
            <label>
              {t("previewEmail")}
              <input disabled value="member@example.org" readOnly />
            </label>
            <label>
              {t("previewPassword")}
              <input disabled value="••••••••••••" readOnly />
            </label>
            <button type="button" disabled>
              {t("sampleButton")}
            </button>
          </section>
        )}
        {screen === "email" && (
          <section className="brand-preview-message">
            <small>
              {configuration.sender_name || configuration.brand_name}
            </small>
            <h3>{t("sampleEmailSubject")}</h3>
            <p>{t("sampleEmailBody")}</p>
            <p>{configuration.email_signature}</p>
            <footer>
              {configuration.email_footer || configuration.footer_text}
              <br />
              {configuration.support_email}
            </footer>
          </section>
        )}
        {screen === "report" && (
          <section className="brand-preview-message">
            <small>
              {t("providerIdentity")}: {configuration.brand_name}
            </small>
            <h3>{t("sampleReport")}</h3>
            <p>{t("clientIdentity")}</p>
            <div className="brand-preview-report-row">
              <span>{t("previewCompliance")}</span>
              <strong>{t("states.ACTIVE")}</strong>
            </div>
            <footer>
              {configuration.report_footer || configuration.footer_text}
              <br />
              {configuration.support_email}
            </footer>
          </section>
        )}
      </div>
    </aside>
  );
}

export default function WhiteLabelSettings({
  onDirtyChange,
}: {
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const t = useTranslations("WhiteLabel");
  const [settings, setSettings] = useState<BrandingSettings | null>(null);
  const [configuration, setConfiguration] = useState<BrandConfiguration | null>(
    null,
  );
  const [tab, setTab] = useState<Tab>("brand");
  const [dark, setDark] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [hostname, setHostname] = useState("");
  const [platformAdmin, setPlatformAdmin] = useState(false);
  const dirty =
    !!settings &&
    !!configuration &&
    JSON.stringify(configuration) !== JSON.stringify(settings.configuration);
  useEffect(() => {
    loadBranding()
      .then((data) => {
        setSettings(data);
        setConfiguration(data.configuration);
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : t("failed")),
      );
    apiRequest<{ allowed: boolean }>("/platform/white-label/access")
      .then((result) => setPlatformAdmin(result.allowed))
      .catch(() => {});
  }, []);
  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    const navigation = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement).closest?.(
        "a[href]",
      ) as HTMLAnchorElement | null;
      if (
        !anchor ||
        anchor.getAttribute("href")?.startsWith("#") ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        anchor.target === "_blank"
      )
        return;
      if (!window.confirm(t("unsavedConfirm"))) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", navigation, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", navigation, true);
    };
  }, [dirty, t]);
  async function perform(
    operation: () => Promise<BrandingSettings>,
    message: string,
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await operation();
      setSettings(result);
      setConfiguration(result.configuration);
      setNotice(message);
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : t("failed"));
      return null;
    } finally {
      setBusy(false);
    }
  }
  function field(key: TextField, multiline = false) {
    if (!configuration) return null;
    const props = {
      value: configuration[key],
      maxLength: limits[key] || 500,
      onChange: (
        event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
      ) => setConfiguration({ ...configuration, [key]: event.target.value }),
      required: ["brand_name", "product_name", "short_name"].includes(key),
    };
    return (
      <label
        className={multiline ? "brand-field full" : "brand-field"}
        key={key}
      >
        {t(`fields.${key}`)}
        {multiline ? (
          <textarea {...props} rows={3} />
        ) : (
          <input
            {...props}
            type={
              key.endsWith("_url")
                ? "url"
                : key.endsWith("email") || key === "reply_to"
                  ? "email"
                  : "text"
            }
          />
        )}
      </label>
    );
  }
  const enabled = !!settings?.entitled && settings.status !== "SUSPENDED";
  const invalidTheme =
    configuration &&
    [configuration.light, configuration.dark].some((theme) =>
      Object.values(theme).some((value) => !/^#[\da-f]{6}$/i.test(value)),
    );
  const invalidRequired =
    !configuration?.brand_name.trim() ||
    !configuration?.product_name.trim() ||
    !configuration?.short_name.trim();
  const warningThemes =
    configuration && !invalidTheme
      ? ["light", "dark"].filter((mode) => {
          const theme = configuration[mode as "light" | "dark"];
          return (
            contrast(theme.text, theme.surface) < 4.5 ||
            contrast(theme.text, theme.background) < 4.5 ||
            contrast(theme.muted, theme.surface) < 4.5 ||
            contrast(theme.primary, theme.surface) < 4.5
          );
        })
      : [];
  function uploader(type: AssetType) {
    if (!settings || !configuration) return null;
    return (
      <BrandAssetUploader
        key={type}
        type={type}
        asset={settings.assets.find(
          (asset) => asset.id === configuration.assets[type],
        )}
        disabled={!enabled || busy}
        onUpload={(asset) => {
          setSettings((current) =>
            current
              ? { ...current, assets: [...current.assets, asset] }
              : current,
          );
          setConfiguration((current) =>
            current
              ? { ...current, assets: { ...current.assets, [type]: asset.id } }
              : current,
          );
          setNotice(t("assetDraftHelp"));
        }}
        onRemove={() => {
          setConfiguration((current) => {
            if (!current) return current;
            const next = { ...current.assets };
            delete next[type];
            return {
              ...current,
              assets: next,
              ...(type === "LOGIN_BACKGROUND"
                ? { login_background: "SOLID" as const }
                : {}),
            };
          });
        }}
        onError={setError}
      />
    );
  }
  async function domainAction(operation: () => Promise<TenantDomain | void>) {
    if (!settings) return;
    setBusy(true);
    setError("");
    try {
      await operation();
      const result = await loadBranding();
      setSettings((current) =>
        current
          ? {
              ...current,
              domains: result.domains,
              audit_events: result.audit_events,
            }
          : current,
      );
      setNotice(t("domainUpdated"));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("failed"));
    } finally {
      setBusy(false);
    }
  }
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice(t("copied"));
    } catch {
      setError(t("copyHelp"));
    }
  }
  if (!settings || !configuration)
    return (
      <div className="page">
        <h1>{t("title")}</h1>
        {error ? (
          <p role="alert">{error}</p>
        ) : (
          <p role="status">{t("loading")}</p>
        )}
      </div>
    );

  return (
    <div className="page white-label-settings">
      <div className="page-heading">
        <div>
          <span className="eyebrow">{t("tenantSettings")}</span>
          <h1>{t("title")}</h1>
          <p>{t("description")}</p>
        </div>
        <div className="brand-editor-actions">
          <button
            type="button"
            className="button secondary"
            disabled={
              !enabled || busy || invalidTheme || invalidRequired || !dirty
            }
            onClick={() =>
              void perform(
                () => saveBrandDraft(configuration, settings.revision),
                t("draftSaved"),
              )
            }
          >
            <Save size={16} />
            {t("saveDraft")}
          </button>
          <button
            type="button"
            className="button primary"
            disabled={
              !enabled ||
              busy ||
              dirty ||
              !settings.draft_version ||
              !!warningThemes?.length
            }
            onClick={async () => {
              if (!window.confirm(t("publishConfirm"))) return;
              const result = await perform(
                () => publishBrand(settings.revision),
                t("published"),
              );
              if (result) window.location.reload();
            }}
          >
            <UploadCloud size={16} />
            {t("publish")}
          </button>
        </div>
      </div>
      <div className="brand-status-line">
        <span className={`status status-${settings.status.toLowerCase()}`}>
          {t(`states.${settings.status}`)}
        </span>
        <span>
          {t("activeVersion")}: {settings.published_version ?? "—"}
        </span>
        <span>
          {t("draftVersion")}: {settings.draft_version ?? "—"}
        </span>
        {dirty && <strong>{t("unsaved")}</strong>}
      </div>
      {!enabled && (
        <div className="auth-alert error" role="status">
          <AlertTriangle size={18} />
          {settings.status === "SUSPENDED"
            ? t("suspendedHelp")
            : t("entitlementHelp")}
        </div>
      )}
      {error && (
        <div className="auth-alert error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="auth-alert success" role="status">
          <CheckCircle2 size={17} />
          {notice}
        </div>
      )}
      {invalidTheme && (
        <div className="auth-alert error" role="alert">
          {t("hexValidation")}
        </div>
      )}
      {!!warningThemes?.length && (
        <div className="auth-alert error" role="alert">
          {t("contrastWarning")}{" "}
          {warningThemes.map((mode) => t(mode)).join(", ")}
        </div>
      )}
      <div
        className="brand-editor-tabs"
        role="tablist"
        aria-label={t("title")}
        onKeyDown={navigateTabs}
      >
        {tabs.map((name) => (
          <button
            type="button"
            role="tab"
            aria-controls={`brand-panel-${name}`}
            aria-selected={tab === name}
            id={`brand-tab-${name}`}
            key={name}
            onClick={() => setTab(name)}
          >
            {t(`tabs.${name}`)}
          </button>
        ))}
      </div>
      <div
        className={`brand-editor-layout ${tab === "preview" ? "preview-only" : ""}`}
      >
        {tab !== "preview" && (
          <section
            className="card brand-editor-panel"
            role="tabpanel"
            id={`brand-panel-${tab}`}
            aria-labelledby={`brand-tab-${tab}`}
          >
            <h2>{t(`tabs.${tab}`)}</h2>
            <fieldset disabled={!enabled || busy}>
              {tab === "brand" && (
                <>
                  <p className="brand-help">{t("identityHelp")}</p>
                  <div className="brand-form-grid">
                    {(
                      [
                        "brand_name",
                        "product_name",
                        "legal_company_name",
                        "short_name",
                        "tagline",
                      ] as TextField[]
                    ).map((key) => field(key))}
                    {field("description", true)}
                  </div>
                  <div className="brand-assets-grid">
                    {assetTypes
                      .filter(
                        (type) =>
                          ![
                            "LOGIN_LOGO",
                            "LOGIN_BACKGROUND",
                            "REPORT_LOGO",
                          ].includes(type),
                      )
                      .map(uploader)}
                  </div>
                </>
              )}
              {tab === "theme" && (
                <>
                  <label className="brand-field">
                    {t("preset")}
                    <select
                      value={configuration.preset}
                      onChange={(event) => {
                        const preset = event.target
                          .value as BrandConfiguration["preset"];
                        const primary = {
                          DEFAULT: defaultLight.primary,
                          PROFESSIONAL: "#0f766e",
                          MINIMAL: "#303030",
                          CORPORATE: "#1d4ed8",
                          CUSTOM: configuration.light.primary,
                        }[preset];
                        setConfiguration({
                          ...configuration,
                          preset,
                          light: { ...defaultLight, primary },
                          dark: { ...defaultDark },
                        });
                      }}
                    >
                      {(
                        [
                          "DEFAULT",
                          "PROFESSIONAL",
                          "MINIMAL",
                          "CORPORATE",
                          "CUSTOM",
                        ] as const
                      ).map((name) => (
                        <option value={name} key={name}>
                          {t(`presets.${name}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="brand-theme-switch">
                    <button
                      type="button"
                      className="button secondary"
                      aria-pressed={!dark}
                      onClick={() => setDark(false)}
                    >
                      {t("light")}
                    </button>
                    <button
                      type="button"
                      className="button secondary"
                      aria-pressed={dark}
                      onClick={() => setDark(true)}
                    >
                      {t("dark")}
                    </button>
                  </div>
                  <div className="brand-colors-grid">
                    {Object.keys(defaultLight).map((name) => {
                      const key = name as keyof ThemeTokens;
                      const mode = dark ? "dark" : "light";
                      const value = configuration[mode][key];
                      return (
                        <label className="brand-color-field" key={key}>
                          <span>{t(`colors.${key}`)}</span>
                          <span>
                            <input
                              type="color"
                              aria-label={t(`colors.${key}`)}
                              value={
                                /^#[\da-f]{6}$/i.test(value)
                                  ? value
                                  : defaultLight[key]
                              }
                              onChange={(event) =>
                                setConfiguration({
                                  ...configuration,
                                  preset: "CUSTOM",
                                  [mode]: {
                                    ...configuration[mode],
                                    [key]: event.target.value,
                                  },
                                })
                              }
                            />
                            <input
                              aria-label={`${t(`colors.${key}`)} HEX`}
                              value={value}
                              maxLength={7}
                              onChange={(event) =>
                                setConfiguration({
                                  ...configuration,
                                  preset: "CUSTOM",
                                  [mode]: {
                                    ...configuration[mode],
                                    [key]: event.target.value,
                                  },
                                })
                              }
                            />
                            <button
                              type="button"
                              title={t("resetColor")}
                              aria-label={`${t("resetColor")} ${t(`colors.${key}`)}`}
                              onClick={() =>
                                setConfiguration({
                                  ...configuration,
                                  [mode]: {
                                    ...configuration[mode],
                                    [key]: (dark ? defaultDark : defaultLight)[
                                      key
                                    ],
                                  },
                                })
                              }
                            >
                              <RotateCcw size={14} />
                            </button>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                  <p className="brand-help">{t("contrastHelp")}</p>
                </>
              )}
              {tab === "login" && (
                <>
                  <div className="brand-form-grid">
                    {field("tagline")}
                    {field("privacy_url")}
                    {field("terms_url")}
                    {field("support_url")}
                    <label className="brand-field">
                      {t("loginBackground")}
                      <select
                        value={configuration.login_background}
                        onChange={(event) =>
                          setConfiguration({
                            ...configuration,
                            login_background: event.target.value as
                              "SOLID" | "IMAGE",
                          })
                        }
                      >
                        <option value="SOLID">{t("solid")}</option>
                        <option value="IMAGE">{t("image")}</option>
                      </select>
                    </label>
                  </div>
                  <div className="brand-assets-grid">
                    {uploader("LOGIN_LOGO")}
                    {uploader("LOGIN_BACKGROUND")}
                  </div>
                </>
              )}
              {tab === "email" && (
                <>
                  <p className="brand-help">
                    <ShieldCheck size={17} />
                    {t("senderHelp")}
                  </p>
                  <div className="brand-form-grid">
                    {field("sender_name")}
                    {field("reply_to")}
                    {field("support_email")}
                    {field("website_url")}
                    {field("email_signature", true)}
                    {field("email_footer", true)}
                  </div>
                  <p className="brand-help">{t("emailLocaleHelp")}</p>
                </>
              )}
              {tab === "reports" && (
                <>
                  <p className="brand-help">{t("reportHelp")}</p>
                  {uploader("REPORT_LOGO")}
                  <div className="brand-form-grid">
                    {field("report_footer", true)}
                    <label className="switch-field">
                      <input
                        type="checkbox"
                        checked={configuration.report_generated_by}
                        onChange={(event) =>
                          setConfiguration({
                            ...configuration,
                            report_generated_by: event.target.checked,
                          })
                        }
                      />
                      {t("fields.report_generated_by")}
                    </label>
                  </div>
                  <a
                    className="button secondary"
                    href="/api/v1/reports/compliance/print"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t("publishedReport")}
                  </a>
                </>
              )}
              {tab === "support" && (
                <div className="brand-form-grid">
                  {(
                    [
                      "support_email",
                      "support_phone",
                      "support_url",
                      "website_url",
                      "privacy_url",
                      "terms_url",
                    ] as TextField[]
                  ).map((key) => field(key))}
                  {field("footer_text", true)}
                </div>
              )}
              {tab === "domain" && (
                <>
                  <p className="brand-help">{t("domainHelp")}</p>
                  <div className="brand-domain-add">
                    <label className="brand-field">
                      {t("hostname")}
                      <input
                        value={hostname}
                        maxLength={253}
                        placeholder="portal.example.org"
                        onChange={(event) => setHostname(event.target.value)}
                      />
                    </label>
                    <button
                      type="button"
                      className="button primary"
                      disabled={!hostname.trim()}
                      onClick={() =>
                        void domainAction(async () => {
                          const result = await addBrandDomain(hostname);
                          setHostname("");
                          return result;
                        })
                      }
                    >
                      <Globe2 size={16} />
                      {t("addDomain")}
                    </button>
                  </div>
                  <div className="brand-domain-list">
                    {settings.domains.map((domain) => (
                      <article className="brand-domain-card" key={domain.id}>
                        <div>
                          <strong title={domain.hostname}>
                            {domain.hostname}
                          </strong>
                          <span className="status">
                            {t(`states.${domain.status}`)}
                          </span>
                          {domain.is_primary && (
                            <small>{t("primaryDomain")}</small>
                          )}
                        </div>
                        <p>
                          {t("ssl")}: {t(`states.${domain.ssl_status}`)}
                        </p>
                        <dl>
                          {[
                            [t("txtName"), domain.txt_name],
                            [t("txtValue"), domain.txt_value],
                            [
                              t("cnameTarget"),
                              domain.cname_target || t("providerRequired"),
                            ],
                          ].map(([label, value]) => (
                            <div key={label}>
                              <dt>{label}</dt>
                              <dd>
                                <code>{value}</code>
                                <button
                                  type="button"
                                  aria-label={`${t("copy")} ${label}`}
                                  onClick={() => void copy(value)}
                                >
                                  <Copy size={16} />
                                </button>
                              </dd>
                            </div>
                          ))}
                        </dl>
                        <div className="brand-editor-actions">
                          <button
                            type="button"
                            className="button secondary small"
                            onClick={() =>
                              void domainAction(() =>
                                verifyBrandDomain(domain.id),
                              )
                            }
                          >
                            {t("verifyDomain")}
                          </button>
                          <button
                            type="button"
                            className="button secondary small"
                            disabled={
                              domain.status !== "ACTIVE" || domain.is_primary
                            }
                            onClick={() =>
                              void domainAction(() =>
                                primaryBrandDomain(domain.id),
                              )
                            }
                          >
                            {t("makePrimary")}
                          </button>
                          <button
                            type="button"
                            className="button secondary small"
                            disabled={domain.status === "DISABLED"}
                            onClick={() => {
                              if (window.confirm(t("disableDomainConfirm")))
                                void domainAction(() =>
                                  disableBrandDomain(domain.id),
                                );
                            }}
                          >
                            {t("disable")}
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                  <p className="brand-help">{t("sslHelp")}</p>
                </>
              )}
              {tab === "advanced" && (
                <>
                  <h3>{t("localizedTaglines")}</h3>
                  <div className="brand-form-grid">
                    {supportedLocales.map((locale) => (
                      <label className="brand-field" key={locale.code}>
                        {locale.nativeLabel}
                        <input
                          value={
                            configuration.localized_taglines[locale.code] || ""
                          }
                          maxLength={200}
                          onChange={(event) => {
                            const values = {
                              ...configuration.localized_taglines,
                            };
                            if (event.target.value)
                              values[locale.code] = event.target.value;
                            else delete values[locale.code];
                            setConfiguration({
                              ...configuration,
                              localized_taglines: values,
                            });
                          }}
                        />
                      </label>
                    ))}
                  </div>
                  <p className="brand-help">{t("brandLocaleHelp")}</p>
                  <Link
                    className="button secondary"
                    href="/settings/localization"
                  >
                    {t("localizationSettings")}
                  </Link>
                  <h3>{t("versionHistory")}</h3>
                  <div className="brand-history">
                    {settings.history.map((version) => (
                      <div key={version.version}>
                        <span>
                          <strong>
                            {t("version")} {version.version}
                          </strong>
                          <small>
                            {version.created_by} ·{" "}
                            {formatDateTime(version.created_at)}
                          </small>
                          {version.published_by && (
                            <small>
                              {t("publishedBy")}: {version.published_by}
                            </small>
                          )}
                        </span>
                        <button
                          type="button"
                          className="button secondary small"
                          onClick={async () => {
                            setBusy(true);
                            try {
                              setConfiguration(
                                await loadBrandVersion(version.version),
                              );
                              setNotice(t("historyDraftHelp"));
                            } catch (e) {
                              setError(
                                e instanceof Error ? e.message : t("failed"),
                              );
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          {t("restoreDraft")}
                        </button>
                      </div>
                    ))}
                  </div>
                  <h3>{t("unusedAssets")}</h3>
                  <div className="brand-history">
                    {settings.assets
                      .filter(
                        (asset) =>
                          !Object.values(configuration.assets).includes(
                            asset.id,
                          ),
                      )
                      .map((asset) => (
                        <div key={asset.id}>
                          <span>
                            {t(`assets.${asset.asset_type}`)} · {asset.width} ×{" "}
                            {asset.height}
                          </span>
                          <button
                            type="button"
                            className="button secondary small"
                            onClick={async () => {
                              if (!window.confirm(t("removeAssetConfirm")))
                                return;
                              setBusy(true);
                              try {
                                await removeBrandAsset(asset.id);
                                setSettings({
                                  ...settings,
                                  assets: settings.assets.filter(
                                    (row) => row.id !== asset.id,
                                  ),
                                });
                              } catch (e) {
                                setError(
                                  e instanceof Error ? e.message : t("failed"),
                                );
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            {t("remove")}
                          </button>
                        </div>
                      ))}
                  </div>
                  <div className="brand-editor-actions">
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => {
                        if (window.confirm(t("discardConfirm")))
                          void perform(
                            () => discardBrand(settings.revision),
                            t("discarded"),
                          );
                      }}
                    >
                      {t("discard")}
                    </button>
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => {
                        if (window.confirm(t("resetConfirm")))
                          void perform(
                            () => resetBrand(settings.revision),
                            t("resetDraft"),
                          );
                      }}
                    >
                      <RotateCcw size={16} />
                      {t("restoreDefaults")}
                    </button>
                  </div>
                </>
              )}
            </fieldset>
            {platformAdmin && (
              <Link className="brand-platform-link" href="/admin/white-label">
                <Palette size={16} />
                {t("platformManagement")}
              </Link>
            )}
          </section>
        )}
        <div
          className="brand-preview-column"
          role={tab === "preview" ? "tabpanel" : undefined}
          id={tab === "preview" ? "brand-panel-preview" : undefined}
          aria-labelledby={tab === "preview" ? "brand-tab-preview" : undefined}
        >
          <div className="brand-theme-switch">
            <button
              type="button"
              className="button secondary small"
              aria-pressed={!dark}
              onClick={() => setDark(false)}
            >
              {t("light")}
            </button>
            <button
              type="button"
              className="button secondary small"
              aria-pressed={dark}
              onClick={() => setDark(true)}
            >
              {t("dark")}
            </button>
          </div>
          <BrandPreview
            configuration={configuration}
            settings={settings}
            dark={dark}
          />
        </div>
      </div>
    </div>
  );
}
