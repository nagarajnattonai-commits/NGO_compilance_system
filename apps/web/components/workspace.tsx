"use client";

import { localizedError, localizedRole, localizedStatus } from "@/i18n/display";

import {
  AlertTriangle,
  ArrowRight,
  Bell,
  Building2,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  Clock3,
  Download,
  FileText,
  FolderOpen,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Menu,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Upload,
  Users,
  X,
  Bot,
  HandHeart,
  PlugZap,
  RefreshCw,
  BadgeCheck,
  Banknote,
  CalendarCheck,
  Mail,
  Megaphone,
  Newspaper,
  Trash2,
  Languages,
  Palette,
  CreditCard,
  BriefcaseBusiness,
} from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import GlobalSearch from "./global-search";
import WorkflowBuilder from "./workflow-builder";
import SavedRegisterViews, { requireCompatibleFilters } from "./saved-register-views";
import {
  addComplianceComment,
  addTaskAttachment,
  addTaskComment,
  archiveTaskAttachment,
  createCompliance,
  createOrganization,
  createPortfolioRecord,
  createTask,
  deletePortfolioRecord,
  inviteMember,
  loadComplianceComments,
  loadEligibleAssignees,
  loadNotificationPreference,
  loadTaskAttachments,
  loadTaskComments,
  loadWorkspace,
  markNotificationRead,
  patchPortfolioRecord,
  patchTask,
  runAutomation,
  transitionCompliance,
  updateNotificationPreference,
} from "@/lib/api";
import Link from "next/link";
import OnboardingBanner from "./onboarding-banner";
import {DocumentUploadForm,DocumentFileDetail} from "./document-library";
import {contentUrl} from "@/lib/evidence";
import { apiRequest } from "@/lib/http";
import { type AuthUser } from "@/lib/auth-types";
import UserManagement from "@/components/user-management";
import type {
  AuditEvent,
  Compliance,
  ComplianceComment,
  ComplianceDefinition,
  ComplianceDocument,
  ComplianceTask,
  EligibleAssignee,
  IntegrationConnection,
  Membership,
  Notification,
  NotificationPreference,
  Organization,
  PortfolioRecord,
  Subscription,
  TaskAttachment,
  TaskComment,
} from "@/lib/types";
import ThemeToggle from "@/components/theme-toggle";
import { normalizeEmail, validateEmail } from "@/lib/auth-validation";
import LocaleSwitcher from "@/components/locale-switcher";
import {
  activeLocale,
  formatDateTime,
  formatShortDate,
  localizedCollator,
} from "@/i18n/format";
import LocalizationAdmin from "@/components/localization-admin";
import WhiteLabelSettings from "@/components/white-label-settings";
import PlatformNavigation from "@/components/platform-navigation";
import ComplianceTemplateRuntime from "@/components/compliance-template-runtime";
import { ManagementDashboard, ManagementReports } from "@/components/reporting";
import { ComplianceNotificationMessage, ComplianceNotificationTitle } from "@/components/compliance-notification";
import OrganizationComplianceProfile from "@/components/organization-compliance-profile";
import { BrandIdentity, useTenantBrand } from "@/branding/client";
import { TenantSubscription } from "@/components/subscriptions";
import ComplianceAssistant from "@/components/compliance-assistant";
import PortfolioManagement from "@/components/portfolio-management";
import BulkImport from "@/components/bulk-import";
import CsrManagement from "@/components/csr-management";

import { isOpenCompliance } from "@/lib/compliance-states";

const UserContext = createContext<AuthUser | null>(null);
function useCurrentUser() {
  const user = useContext(UserContext);
  if (!user) throw new Error("Sign-in context is missing");
  return user;
}

type View =
  | "overview"
  | "portfolio"
  | "csr"
  | "compliance"
  | "tasks"
  | "calendar"
  | "documents"
  | "reports"
  | "programmes"
  | "operations"
  | "assistant"
  | "integrations"
  | "administration"
  | "localization"
  | "subscription"
  | "whiteLabel";

const nav = [
  { id: "overview" as View, labelKey: "dashboard", icon: LayoutDashboard },
  { id: "portfolio" as View, labelKey: "portfolio", icon: BriefcaseBusiness },
  { id: "csr" as View, labelKey: "csrPortfolio", icon: HandHeart },
  { id: "compliance" as View, labelKey: "compliance", icon: ClipboardCheck },
  { id: "tasks" as View, labelKey: "tasks", icon: ListChecks },
  { id: "calendar" as View, labelKey: "calendar", icon: CalendarDays },
  { id: "documents" as View, labelKey: "documents", icon: FolderOpen },
  { id: "reports" as View, labelKey: "reports", icon: Gauge },
  { id: "programmes" as View, labelKey: "impact", icon: HandHeart },
  { id: "operations" as View, labelKey: "operations", icon: Megaphone },
  { id: "assistant" as View, labelKey: "assistant", icon: Bot },
  { id: "integrations" as View, labelKey: "integrations", icon: PlugZap },
  { id: "administration" as View, labelKey: "administration", icon: Users },
  { id: "localization" as View, labelKey: "localization", icon: Languages },
  { id: "subscription" as View, labelKey: "subscription", icon: CreditCard },
  { id: "whiteLabel" as View, labelKey: "whiteLabel", icon: Palette },
];

const statusLabels: Record<string, string> = {
  NOT_STARTED: "Not started",
  IN_PROGRESS: "In progress",
  UNDER_REVIEW: "Under review",
  PLANNED: "Planned",
  CHANGES_REQUESTED: "Changes requested",
  READY_TO_FILE: "Ready to file",
  FILED: "Filed",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
  NOT_APPLICABLE: "Not applicable",
  ON_HOLD: "On hold",
  OVERDUE: "Overdue",
};

function niceDate(value: string | null, compact = false) {
  if (!value) return "—";
  return formatShortDate(value).replace(compact ? /\s+\d{4}$/ : /$^/, "");
}

function initials(name: string) {
  return name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2);
}

function downloadText(
  filename: string,
  content: string,
  type = "text/plain;charset=utf-8",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function dateInput(daysFromToday: number) {
  const date = new Date();
  date.setDate(date.getDate() + daysFromToday);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function documentReceipt(doc: ComplianceDocument) {
  if (doc.current_version_id && doc.storage_status === "AVAILABLE") window.location.assign(contentUrl(doc.id));
}

function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("Common.status");
  const label = t.has(status)
    ? t(status)
    : statusLabels[status] || status.replaceAll("_", " ");
  return (
    <span className={`status status-${status.toLowerCase()}`} title={label}>
      <i />
      {label}
    </span>
  );
}

function Avatar({ name, label }: { name: string; label?: string }) {
  return (
    <div className="avatar" title={name}>
      {label || initials(name)}
    </div>
  );
}

function AppLogo() {
  const t = useTranslations("Common");
  const brand = useTenantBrand();
  if (brand.enabled) return <div className="brand tenant-sidebar-brand"><BrandIdentity /></div>;
  return (
    <div className="brand">
      <div className="brand-mark">
        <ShieldCheck size={25} />
      </div>
      <div>
        <strong>{t("brand")}</strong>
        <small>{t("tagline")}</small>
      </div>
    </div>
  );
}

export default function ComplianceApp({
  user,
  initialView = "overview",
  platformAdmin = false,
}: {
  user: AuthUser;
  initialView?: View;
  platformAdmin?: boolean;
}) {
  const uiText = useTranslations();
  const tCommon = useTranslations("Common");
  const tAuth = useTranslations("Authentication");
  const tBrand = useTranslations("WhiteLabel");
  const [view, setView] = useState<View>(initialView);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [selectedOrg, setSelectedOrg] = useState("all");
  const [orgMenu, setOrgMenu] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedCompliance, setSelectedCompliance] =
    useState<Compliance | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [showNewTask, setShowNewTask] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [showNewOrganization, setShowNewOrganization] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const [uploadComplianceId, setUploadComplianceId] = useState<string | null>(
    null,
  );
  const [panel, setPanel] = useState<
    "guide" | "help" | "settings" | "notifications" | null
  >(null);
  const [defaultLeadDays, setDefaultLeadDays] = useState(7);
  const [toast, setToast] = useState("");
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [compliances, setCompliances] = useState<Compliance[]>([]);
  const [tasks, setTasks] = useState<ComplianceTask[]>([]);
  const [documents, setDocuments] = useState<ComplianceDocument[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [complianceDefinitions, setComplianceDefinitions] = useState<
    ComplianceDefinition[]
  >([]);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [portfolioRecords, setPortfolioRecords] = useState<PortfolioRecord[]>(
    [],
  );
  const [integrations, setIntegrations] = useState<IntegrationConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [signingOut, setSigningOut] = useState(false);
  const [brandDirty, setBrandDirty] = useState(false);
  const [searchTarget, setSearchTarget] = useState<{ id: string; type: string } | null>(null);

  useEffect(() => {
    if (loading || platformAdmin) return;
    const params = new URLSearchParams(window.location.search);
    const targetView = params.get("view");
    if (targetView === "tasks" || targetView === "documents" ||
        targetView === "csr" && subscription?.feature_access?.csr_partner_management === true) {
      setView(targetView);
      const id = params.get("record");
      if (id) setSearchTarget({ id, type: params.get("type") || "" });
    }
  }, [loading, platformAdmin, subscription]);

  useEffect(() => {
    if (platformAdmin) {
      setLoading(false);
    } else loadWorkspace(user.role === "ADMIN")
      .then((data) => {
        setOrganizations(data.organizations);
        setCompliances(data.compliances);
        setTasks(data.tasks);
        setDocuments(data.documents);
        setNotifications(data.notifications);
        setAuditEvents(data.auditEvents);
        setComplianceDefinitions(data.complianceDefinitions);
        setMemberships(data.memberships);
        setSubscription(data.subscription);
        setPortfolioRecords(data.portfolioRecords);
        setIntegrations(data.integrations);
      })
      .catch((error) =>
        setLoadError(
          localizedError(error, uiText, uiText("Common.interface.unableToLoadWorkspace")),
        ),
      )
      .finally(() => setLoading(false));
    try {
      const saved = JSON.parse(
        localStorage.getItem("setu-workspace-preferences") || "null",
      ) as { leadDays?: number } | null;
      if (saved?.leadDays) setDefaultLeadDays(saved.leadDays);
    } catch {
      /* Ignore invalid local demo preferences. */
    }
  }, [user.role, platformAdmin]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 2800);
    return () => clearTimeout(timer);
  }, [toast]);

  const org = organizations.find((item) => item.id === selectedOrg);
  const scopedCompliances = compliances.filter(
    (item) => selectedOrg === "all" || item.organization_id === selectedOrg,
  );
  const scopedTasks = tasks.filter(
    (item) => selectedOrg === "all" || item.organization_id === selectedOrg,
  );
  const scopedDocuments = documents.filter(
    (item) => selectedOrg === "all" || item.organization_id === selectedOrg,
  );
  const scopedPortfolioRecords = portfolioRecords.filter(
    (item) => selectedOrg === "all" || item.organization_id === selectedOrg,
  );
  const unread = notifications.filter((item) => !item.is_read).length;

  function go(next: View) {
    if (view === "whiteLabel" && brandDirty && !window.confirm(tBrand("unsavedConfirm"))) return;
    setView(next);
    setSearchTarget(null);
    setMobileMenu(false);
    setSearch("");
    setPanel(null);
  }
  function showToast(message: string) {
    setToast(message);
  }
  function openUpload(complianceId: string | null = null) {
    setUploadComplianceId(complianceId);
    setShowUpload(true);
  }
  async function toggleTask(task: ComplianceTask) {
    if (user.role === "VIEWER") {
      showToast("Your account has read-only access");
      return;
    }
    try {
      const updated = await patchTask(
        task.id,
        task.status === "DONE" ? "TODO" : "DONE",
      );
      setTasks((items) =>
        items.map((item) => (item.id === task.id ? updated : item)),
      );
      showToast(
        updated.status === "DONE" ? uiText("Common.interface.taskMarkedComplete") : uiText("Common.interface.taskReopened"),
      );
    } catch (error) {
      showToast(
        localizedError(error, uiText, uiText("Common.interface.couldNotUpdateTask")),
      );
    }
  }
  async function readNotice(id: string) {
    try {
      await markNotificationRead(id);
      setNotifications((rows) =>
        rows.map((notice) =>
          notice.id === id ? { ...notice, is_read: true } : notice,
        ),
      );
    } catch (error) {
      showToast(
        localizedError(error, uiText, uiText("Common.interface.couldNotMarkNotificationRead")),
      );
    }
  }
  async function logout() {
    if (brandDirty && !window.confirm(tBrand("unsavedConfirm"))) return;
    setSigningOut(true);
    try {
      await apiRequest<void>("/auth/logout", "POST");
      window.location.assign(window.location.pathname.startsWith("/admin")?"/admin/login":"/login");
    } catch (error) {
      showToast(localizedError(error, uiText, uiText("Common.interface.couldNotSignOut")));
      setSigningOut(false);
    }
  }
  async function updateStatus(
    item: Compliance,
    status: string,
    reason?: string,
    submissionReference?: string,
  ) {
    try {
      const updated = await transitionCompliance(item, {
        target_status: status,
        reason: reason || undefined,
        submission_reference: submissionReference || undefined,
      });
      setCompliances((items) =>
        items.map((row) => (row.id === item.id ? updated : row)),
      );
      setSelectedCompliance((current) =>
        current?.id === item.id ? updated : current,
      );
      showToast(uiText("Common.interface.statusChanged", { status: localizedStatus(status, uiText) }));
    } catch (error) {
      showToast(
        localizedError(error, uiText, uiText("Common.interface.couldNotUpdateThisCompliance")),
      );
    }
  }

  if (loading)
    return (
      <main className="workspace-loading" role="status">
        <ShieldCheck size={32} />
        <p>{tCommon("loading")}</p>
      </main>
    );
  if (loadError || (!subscription && !platformAdmin))
    return (
      <main className="workspace-loading">
        <h1>{uiText("Common.interface.unableToLoadWorkspace")}</h1>
        <p role="alert">{loadError || uiText("Common.interface.subscriptionUnavailable")}</p>
        <button
          className="button primary"
          onClick={() => window.location.reload()}
        >
           {uiText("Common.actions.tryAgain")} </button>
        <Link href="/account">{uiText("Common.interface.accountSettingsLabel")}</Link>
      </main>
    );

  return (
    <UserContext.Provider value={user}>
      <div className={`app-shell ${user.role === "VIEWER" ? "read-only" : ""}`}>
        <aside className={`sidebar ${mobileMenu ? "sidebar-open" : ""}`}>
          <div className="sidebar-top">
            <AppLogo />
            <button
              className="mobile-close"
              aria-label={uiText("Marketing.navigation.closeNavigation")}
              onClick={() => setMobileMenu(false)}
            >
              <X size={19} />
            </button>
          </div>
          <p className="nav-label">{tCommon("mainNavigation")}</p>
          <nav aria-label={tCommon("mainNavigation")}>
            {nav
              .filter(
                (item) => platformAdmin ? item.id === "administration" :
                  item.id === "portfolio" ? organizations.length > 1 :
                  item.id === "csr" ? subscription?.feature_access?.csr_partner_management === true :
                    !["operations", "administration", "localization", "whiteLabel"].includes(item.id) || user.role === "ADMIN",
              )
              .map(({ id, labelKey, icon: Icon }) => (
                <button
                  key={id}
                  title={tCommon(`nav.${labelKey}`)}
                  className={view === id ? "active" : ""}
                  aria-current={view === id ? "page" : undefined}
                  onClick={() => go(id)}
                >
                  <Icon size={18} />
                  <span>{tCommon(`nav.${labelKey}`)}</span>
                  {id === "tasks" ? (
                    <em>
                      {scopedTasks.filter((t) => t.status !== "DONE").length}
                    </em>
                  ) : (
                    id !== "overview" && (
                      <ChevronRight className="nav-chevron" size={14} />
                    )
                  )}
                </button>
              ))}
          </nav>
          <div className="sidebar-spacer" />
          <div className="help-card">
            <Sparkles size={17} />
            <strong>{uiText("Common.interface.complianceTip")}</strong>
            <p>
               {uiText("Common.interface.setInternalTargetsAtLeast7DaysBeforeStatutoryDeadlines")} </p>
            <button
              onClick={() => {
                setPanel("guide");
                setMobileMenu(false);
              }}
            >
               {uiText("Common.interface.viewGuide")} <ArrowRight size={14} />
            </button>
          </div>
          <nav className="secondary-nav">
            <button
              onClick={() => {
                setPanel("help");
                setMobileMenu(false);
              }}
            >
              <CircleHelp size={18} />
              <span>{uiText("Common.interface.helpCentre")}</span>
            </button>
            <button
              onClick={() => {
                setPanel("settings");
                setMobileMenu(false);
              }}
            >
              <Settings size={18} />
              <span>{uiText("Common.interface.settings")}</span>
            </button>
          </nav>
          <div className="account">
            <Avatar name={user.name} />
            <div>
              <strong>{user.name}</strong>
              <small>{localizedRole(user.role, uiText)}</small>
            </div>
          </div>
          <div className="sidebar-account-links">
            <Link href="/account">{uiText("Common.interface.myAccountPassword")}</Link>
            <Link href="/select-workspace">{tAuth("selectWorkspace")}</Link>
            <button disabled={signingOut} onClick={logout}>
              {signingOut ? uiText("Common.interface.signingOut") : uiText("Common.actions.signOut")}
            </button>
          </div>
        </aside>

        {mobileMenu && (
          <button
            className="scrim"
            aria-label={uiText("Common.interface.closeMenu")}
            onClick={() => setMobileMenu(false)}
          />
        )}
        <main className="main">
          {!platformAdmin && <OnboardingBanner canManage={user.role==="ADMIN"}/>}
          <header className="topbar">
            <button
              className="menu-button"
              aria-label={uiText("Marketing.navigation.openNavigation")}
              aria-expanded={mobileMenu}
              onClick={() => setMobileMenu(true)}
            >
              <Menu size={20} />
            </button>
            <div className="org-switcher-wrap">
              <button
                className="org-switcher"
                onClick={() => setOrgMenu(!orgMenu)}
              >
                <span className="org-icon">
                  <Building2 size={17} />
                </span>
                <span>
                  <small>{tCommon("viewing")}</small>
                  <strong>{org?.name || tCommon("allOrganizations")}</strong>
                </span>
                <ChevronDown size={16} />
              </button>
              {orgMenu && (
                <div className="org-menu">
                  <button
                    onClick={() => {
                      setSelectedOrg("all");
                      setOrgMenu(false);
                    }}
                  >
                    <span className="org-mini all">
                      <Building2 size={15} />
                    </span>
                    <span>
                      <strong>{tCommon("allOrganizations")}</strong>
                      <small>{uiText("Common.interface.portfolioView")}</small>
                    </span>
                    {selectedOrg === "all" && <Check size={16} />}
                  </button>
                  {organizations.map((item) => (
                    <button
                      key={item.id}
                      onClick={() => {
                        setSelectedOrg(item.id);
                        setOrgMenu(false);
                      }}
                    >
                      <span className="org-mini">{item.name[0]}</span>
                      <span>
                        <strong>{item.name}</strong>
                        <small>
                          {item.legal_type} · {item.city}
                        </small>
                      </span>
                      {selectedOrg === item.id && <Check size={16} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <span className="admin-context">
              <ShieldCheck size={16} />
              <span>
                 {uiText("Common.interface.nGOManagement")}<small>{localizedRole(user.role, uiText)}  {uiText("Common.interface.workspace")}</small>
              </span>
            </span>
            <div className="top-actions">
              <GlobalSearch organizations={organizations} compliances={compliances} />
              <LocaleSwitcher compact />
              <ThemeToggle variant="icon" />
              <div className="notification-wrap">
                <button
                  className="icon-button"
                  aria-label={uiText("Common.interface.openNotifications")}
                  onClick={() => setNotificationOpen(!notificationOpen)}
                >
                  <Bell size={19} />
                  {unread > 0 && <b>{unread}</b>}
                </button>
                {notificationOpen && (
                  <NotificationPanel
                    items={notifications}
                    onRead={readNotice}
                    onReadAll={() => {
                      void Promise.all(
                        notifications
                          .filter((notice) => !notice.is_read)
                          .map((notice) => readNotice(notice.id)),
                      );
                    }}
                    onViewAll={() => {
                      setNotificationOpen(false);
                      setPanel("notifications");
                    }}
                  />
                )}
              </div>
              <Link
                href="/account"
                className="top-avatar"
                aria-label={uiText("Common.interface.openAccountSettings")}
              >
                <Avatar name={user.name} />
                <span>
                  {user.name}
                  <small>{localizedRole(user.role, uiText)}</small>
                </span>
                <ChevronDown size={14} />
              </Link>
            </div>
          </header>

          {user.role === "VIEWER" && (
            <div className="readonly-banner">{tCommon("readOnly")}</div>
          )}
          {view === "overview" && (
            <Overview
              compliances={scopedCompliances}
              tasks={scopedTasks}
              organizationId={selectedOrg === "all" ? undefined : selectedOrg}
              audits={auditEvents}
              orgName={org?.name}
              go={go}
              toggleTask={toggleTask}
              setShowNew={setShowNew}
              openUpload={openUpload}
              onSelectCompliance={(id) => {
                const item = scopedCompliances.find((compliance) => compliance.id === id);
                if (item) setSelectedCompliance(item);
              }}
            />
          )}
          {view === "portfolio" && organizations.length > 1 && (
            <PortfolioManagement
              organizations={organizations}
              memberships={memberships}
              role={user.role}
              onOpenClient={(id) => { setSelectedOrg(id); go("overview"); }}
              onOpenCompliance={(id) => {
                const item = compliances.find((compliance) => compliance.id === id);
                if (item) { setSelectedOrg(item.organization_id); setSelectedCompliance(item); }
              }}
            />
          )}
          {view === "csr" && subscription?.feature_access?.csr_partner_management === true && (
            <CsrManagement organizations={organizations} role={user.role} initialTarget={searchTarget} />
          )}
          {view === "compliance" && (
            <ComplianceView
              currentOrg={selectedOrg} selectOrg={setSelectedOrg}
              items={scopedCompliances}
              organizations={organizations}
              search={search}
              setSearch={setSearch}
              selectCompliance={setSelectedCompliance}
              setShowNew={setShowNew}
            />
          )}
          {view === "tasks" && (
            <TasksView
              currentOrg={selectedOrg} selectOrg={setSelectedOrg} organizations={organizations}
              initialRecordId={searchTarget?.id}
              items={scopedTasks}
              compliances={compliances}
              documents={documents}
              toggleTask={toggleTask}
              taskUpdated={(updated) => setTasks((rows) => rows.map((row) => row.id === updated.id ? updated : row))}
              setShowNewTask={setShowNewTask}
            />
          )}
          {view === "calendar" && (
            <CalendarView
              items={scopedCompliances}
              selectCompliance={setSelectedCompliance}
            />
          )}
          {view === "documents" && (
            <DocumentsView
              initialRecordId={searchTarget?.id}
              items={scopedDocuments}
              organizations={organizations}
              openUpload={openUpload}
              showToast={showToast}
              updateDocument={(document) =>
                setDocuments((rows) =>
                  rows.map((row) => (row.id === document.id ? document : row)),
                )
              }
            />
          )}
          {view === "reports" && (
            <ManagementReports
              key={selectedOrg}
              organizations={selectedOrg === "all" ? organizations : organizations.filter((item) => item.id === selectedOrg)}
              initialOrganizationId={selectedOrg === "all" ? undefined : selectedOrg}
              onSelectCompliance={(id) => {
                const item = scopedCompliances.find((compliance) => compliance.id === id);
                if (item) setSelectedCompliance(item);
              }}
              advancedReporting={subscription?.feature_access?.advanced_reporting === true}
            />
          )}
          {view === "programmes" && (
            <ProgrammesView
              items={scopedPortfolioRecords}
              organizations={organizations}
              currentOrg={selectedOrg}
              readOnly={user.role === "VIEWER"}
              onUpdate={(item) => setPortfolioRecords(rows=>rows.map(row=>row.id===item.id?item:row))}
              onDelete={(id) => setPortfolioRecords(rows=>rows.filter(row=>row.id!==id))}
              onRefresh={async()=>setPortfolioRecords(await apiRequest<PortfolioRecord[]>("/portfolio-records"))}
              onCreate={(item) => {
                setPortfolioRecords((rows) => [item, ...rows]);
                showToast(`${item.title} added`);
              }}
            />
          )}
          {view === "operations" && user.role === "ADMIN" && (
            <OperationsView
              items={scopedPortfolioRecords}
              organizations={organizations}
              currentOrg={selectedOrg}
              onRefresh={async()=>setPortfolioRecords(await apiRequest<PortfolioRecord[]>("/portfolio-records"))}
              onCreate={(item) => {
                setPortfolioRecords((rows) => [item, ...rows]);
                showToast(`${item.title} added`);
              }}
              onUpdate={(item) => {
                setPortfolioRecords((rows) =>
                  rows.map((row) => (row.id === item.id ? item : row)),
                );
                showToast(`${item.title} updated`);
              }}
              onDelete={(id) => {
                setPortfolioRecords((rows) =>
                  rows.filter((row) => row.id !== id),
                );
                showToast("Record deleted");
              }}
            />
          )}
          {view === "assistant" && (
            <ComplianceAssistant
              organization={org}
              entitled={subscription?.feature_access?.ai_rag === true}
              readOnly={user.role === "VIEWER"}
            />
          )}
          {view === "integrations" && (
            <><IntegrationLinks /><IntegrationsView
              items={integrations}
              isAdmin={user.role === "ADMIN"}
              onAutomation={(result) => {
                showToast(
                  uiText("Common.interface.automationComplete", { alerts: result.overdue_compliances + result.overdue_tasks + result.upcoming + result.expiring_documents, recurring: result.recurring_created }),
                );
                void loadWorkspace(true).then((data) => {
                  setCompliances(data.compliances);
                  setTasks(data.tasks);
                  setDocuments(data.documents);
                  setNotifications(data.notifications);
                  setAuditEvents(data.auditEvents);
                });
              }}
            />{user.role === "ADMIN" && <WorkflowBuilder entitled={subscription?.feature_access?.advanced_automation === true} />}</>
          )}
          {view === "administration" && platformAdmin && <PlatformNavigation />}
          {view === "administration" && user.role === "ADMIN" && subscription && !platformAdmin && (
            <>
              <AdministrationView
                organizations={organizations}
                compliances={compliances}
                definitions={complianceDefinitions}
                memberships={memberships}
                subscription={subscription}
                setShowNewOrganization={setShowNewOrganization}
                setShowInvite={setShowInvite}
              />
              <BulkImport />
            </>
          )}
          {view === "localization" && user.role === "ADMIN" && (
            <LocalizationAdmin />
          )}
          {view === "subscription" && subscription && <TenantSubscription subscription={subscription} />}
          {view === "whiteLabel" && user.role === "ADMIN" && (
            <WhiteLabelSettings onDirtyChange={setBrandDirty} />
          )}
        </main>

        {selectedCompliance && (
          <ComplianceDrawer
            item={selectedCompliance}
            templateUpdated={(updated) => { setSelectedCompliance(updated); setCompliances((rows) => rows.map((row) => row.id === updated.id ? updated : row)); }}
            org={organizations.find(
              (o) => o.id === selectedCompliance.organization_id,
            )}
            relatedTasks={tasks.filter(
              (t) => t.compliance_id === selectedCompliance.id,
            )}
            relatedDocs={documents.filter(
              (d) => d.compliance_id === selectedCompliance.id,
            )}
            close={() => setSelectedCompliance(null)}
            updateStatus={updateStatus}
            toggleTask={toggleTask}
            attachEvidence={() => {
              const id = selectedCompliance.id;
              setSelectedCompliance(null);
              openUpload(id);
            }}
            showToast={showToast}
          />
        )}
        {showNew && (
          <NewComplianceModal
            organizations={organizations}
            currentOrg={selectedOrg}
            leadDays={defaultLeadDays}
            close={() => setShowNew(false)}
            onCreate={(item) => {
              setCompliances((rows) => [item, ...rows]);
              setShowNew(false);
              showToast("Compliance added to the register");
            }}
          />
        )}
        {showNewTask && (
          <NewTaskModal
            organizations={organizations}
            compliances={compliances}
            currentOrg={selectedOrg}
            close={() => setShowNewTask(false)}
            onCreate={(item) => {
              setTasks((rows) => [item, ...rows]);
              setShowNewTask(false);
              showToast("Task assigned successfully");
            }}
          />
        )}
        {showUpload && (
          <UploadModal
            organizations={organizations}
            compliances={compliances}
            currentOrg={
              uploadComplianceId
                ? compliances.find((item) => item.id === uploadComplianceId)
                    ?.organization_id || selectedOrg
                : selectedOrg
            }
            initialComplianceId={uploadComplianceId}
            close={() => {
              setShowUpload(false);
              setUploadComplianceId(null);
            }}
            onUpload={(doc) => {
              setDocuments((rows) => [doc, ...rows]);
              setShowUpload(false);
              setUploadComplianceId(null);
              showToast("Document metadata saved");
            }}
          />
        )}
        {showNewOrganization && (
          <NewOrganizationModal
            close={() => setShowNewOrganization(false)}
            onCreate={({ organization, generated_compliances }) => {
              setOrganizations((rows) =>
                [...rows, organization].sort((a, b) =>
                  a.name.localeCompare(b.name),
                ),
              );
              setCompliances((rows) => [...generated_compliances, ...rows]);
              setSelectedOrg(organization.id);
              setShowNewOrganization(false);
              showToast(
                `${organization.name} onboarded with ${generated_compliances.length} planned obligations`,
              );
            }}
          />
        )}
        {showInvite && (
          <InviteMemberModal
            organizations={organizations}
            close={() => setShowInvite(false)}
            onCreate={(member) => {
              setMemberships((rows) => [...rows, member]);
              setShowInvite(false);
              showToast(uiText("Common.interface.invitationCreated", { email: member.email }));
            }}
          />
        )}
        {panel === "guide" && (
          <GuideModal close={() => setPanel(null)} go={go} />
        )}
        {panel === "help" && <HelpModal close={() => setPanel(null)} go={go} />}
        {panel === "settings" && (
          <SettingsModal
            close={() => setPanel(null)}
            onSave={(leadDays) => {
              setDefaultLeadDays(leadDays);
              setPanel(null);
              showToast("Workspace preferences saved");
            }}
          />
        )}
        {panel === "notifications" && (
          <NotificationCenter
            items={notifications}
            close={() => setPanel(null)}
            onRead={readNotice}
          />
        )}
        {toast && (
          <div className="toast" role="status">
            <CheckCircle2 size={18} />
            {toast}
          </div>
        )}
      </div>
    </UserContext.Provider>
  );
}

function PageHeading({
  eyebrow,
  title,
  text,
  action,
}: {
  eyebrow?: string;
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {action}
    </div>
  );
}

function Overview({
  compliances,
  tasks,
  audits,
  orgName,
  go,
  toggleTask,
  setShowNew,
  openUpload,
  organizationId,
  onSelectCompliance,
}: {
  compliances: Compliance[];
  tasks: ComplianceTask[];
  audits: AuditEvent[];
  orgName?: string;
  go: (v: View) => void;
  toggleTask: (t: ComplianceTask) => void;
  setShowNew: (v: boolean) => void;
  openUpload: () => void;
  organizationId?: string;
  onSelectCompliance: (id: string) => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Dashboard");
  const openItems = compliances.filter((item) => isOpenCompliance(item.status));
  const risk = openItems.filter((item) =>
    ["HIGH", "CRITICAL"].includes(item.priority),
  ).length;
  const today = dateInput(0);
  const overdue = openItems.filter(
    (item) => item.statutory_deadline < today,
  ).length;
  const openTasks = tasks.filter((task) => task.status !== "DONE");
  return (
    <div className="page reference-dashboard">
      <PageHeading
        eyebrow={uiText("Common.interface.homeTrail", { page: t("adminTitle") })}
        title={
          useCurrentUser().role === "ADMIN" ? t("adminTitle") : t("teamTitle")
        }
        text={orgName ? `${t("totalCompliances")}: ${orgName}` : t("welcome")}
        action={
          <div className="heading-actions">
            <button className="button secondary" onClick={openUpload}>
              <Upload size={16} />
              {t("addEvidence")}
            </button>
            <button className="button primary" onClick={() => setShowNew(true)}>
              <Plus size={16} />
              {t("addCompliance")}
            </button>
          </div>
        }
      />
      <ManagementDashboard organizationId={organizationId} onSelectCompliance={onSelectCompliance} />
      <section className="card admin-notice">
        <div className="notice-heading">
          <Bell size={17} />
          <h2>{uiText("Common.interface.complianceNotice")}</h2>
        </div>
        <div className="notice-body">
          <span className="notice-symbol">
            <AlertTriangle size={20} />
          </span>
          <div>
            <strong>
              {risk
                ? uiText("Common.interface.riskAttention", { count: risk })
                : uiText("Common.interface.noHighPriorityObligationsPending")}
            </strong>
            <p>
              {overdue
                ? uiText("Common.interface.overdueNotice", { count: overdue })
                : uiText("Common.interface.keepEvidenceUpToDateAndReviewInternalTargetsBeforeTheStatutoryDeadlines")}
            </p>
          </div>
          <button
            className="button secondary small"
            onClick={() => go("compliance")}
          >
             {uiText("Common.interface.openRegister")} <ArrowRight size={14} />
          </button>
        </div>
      </section>
      <div className="dashboard-grid">
        <section className="card task-card">
          <CardTitle
            title={uiText("Common.interface.assignedTasks")}
            sub={uiText("Common.interface.openAssignments", { count: openTasks.length })}
            action={
              <button className="text-button" onClick={() => go("tasks")}>
                 {uiText("Common.actions.viewAll")} <ChevronRight size={15} />
              </button>
            }
          />
          <div className="task-list">
            {[...openTasks, ...tasks.filter((task) => task.status === "DONE")]
              .slice(0, 5)
              .map((task) => (
                <div
                  className={
                    task.status === "DONE" ? "task-row done" : "task-row"
                  }
                  key={task.id}
                >
                  <button
                    className="task-check"
                    aria-label={`${task.status === "DONE" ? "Reopen" : uiText("Marketing.complete")} ${task.title}`}
                    aria-pressed={task.status === "DONE"}
                    onClick={() => toggleTask(task)}
                  >
                    {task.status === "DONE" && <Check size={14} />}
                  </button>
                  <div>
                    <strong>{task.title}</strong>
                    <span>
                       {uiText("Portfolio.due")} {niceDate(task.due_at, true)} · {task.assignee_name}
                    </span>
                  </div>
                  <Avatar
                    name={task.assignee_name}
                    label={task.assignee_initials}
                  />
                </div>
              ))}
          </div>
          {!tasks.length && (
            <EmptyState
              icon={<ListChecks />}
              title={uiText("Tasks.emptyTitle")}
              text={uiText("Common.interface.createAnAssignmentFromTheTasksPage")}
            />
          )}
        </section>
        <section className="card activity-card">
          <CardTitle
            title={t("recentActivity")}
            sub={uiText("Common.interface.latestRecordedChanges")}
          />
          <div className="activity-list">
            {audits.slice(0, 4).map((event, index) => (
              <div className="activity-row" key={event.id}>
                <div className={`activity-icon activity-${index % 3}`}>
                  {event.entity_type === "Document" ? (
                    <FileText size={15} />
                  ) : event.entity_type === "Task" ? (
                    <Check size={15} />
                  ) : (
                    <ArrowRight size={15} />
                  )}
                </div>
                <div>
                  <p>
                    <strong>{event.actor_name}</strong>{" "}
                    {event.summary.charAt(0).toLowerCase() +
                      event.summary.slice(1)}
                  </p>
                  <span>{formatDateTime(event.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
          {!audits.length && (
            <p className="muted">{uiText("Common.interface.noActivityHasBeenRecordedYet")}</p>
          )}
        </section>
      </div>
    </div>
  );
}

function CardTitle({
  title,
  sub,
  action,
}: {
  title: string;
  sub: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="card-title">
      <div>
        <h2>{title}</h2>
        <p>{sub}</p>
      </div>
      {action}
    </div>
  );
}

function ComplianceView({
  currentOrg, selectOrg,
  items,
  organizations,
  search,
  setSearch,
  selectCompliance,
  setShowNew,
}: {
  currentOrg: string; selectOrg: (id: string) => void;
  items: Compliance[];
  organizations: Organization[];
  search: string;
  setSearch: (v: string) => void;
  selectCompliance: (c: Compliance) => void;
  setShowNew: (v: boolean) => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Compliance");
  const [filter, setFilter] = useState("ALL");
  const [pageSize, setPageSize] = useState(10);
  const [pagination, setPagination] = useState({ key: "", page: 1 });
  const visible = items.filter(
    (item) =>
      (filter === "ALL" || item.status === filter) &&
      `${item.title} ${item.code} ${item.owner_name}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const queryKey = `${filter}|${search}|${items.map((item) => item.id).join(",")}`;
  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize));
  const page =
    pagination.key === queryKey ? Math.min(pagination.page, pageCount) : 1;
  const pageItems = visible.slice((page - 1) * pageSize, page * pageSize);
  return (
    <div className="page">
      <PageHeading
        title={t("title")}
        text={t("description")}
        action={
          <button className="button primary" onClick={() => setShowNew(true)}>
            <Plus size={17} />
            {t("add")}
          </button>
        }
      />
      <div className="toolbar">
        <label className="entries-control">
          {t("status")}{" "}
          <select
            aria-label={t("title")}
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPagination({ key: queryKey, page: 1 });
            }}
          >
            {[10, 25, 50].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <div className="search-box">
          <Search size={17} />
          <input
            aria-label={t("searchPlaceholder")}
            id="global-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("searchPlaceholder")}
          />
        </div>
        <div className="filter-tabs">
          {[
            "ALL",
            "NOT_STARTED",
            "IN_PROGRESS",
            "UNDER_REVIEW",
            "COMPLETED",
            "CANCELLED",
            "NOT_APPLICABLE",
          ].map((item) => (
            <button
              className={filter === item ? "active" : ""}
              onClick={() => setFilter(item)}
              key={item}
            >
              {item === "ALL" ? uiText("ComplianceMaster.all") : <StatusBadge status={item} />}
            </button>
          ))}
        </div>
      </div>
      <SavedRegisterViews scope="COMPLIANCES" filters={{query:search,status:filter==="ALL"?null:filter,organization_id:currentOrg==="all"?null:currentOrg}}
        apply={saved=>{
          requireCompatibleFilters(saved,["query","status","organization_id"], filter => uiText("Common.interface.unsupportedFilter", { filter }));
          if(saved.organization_id&&!organizations.some(org=>org.id===saved.organization_id)) throw new Error(uiText("Common.interface.savedOrganizationIsNoLongerAccessible"));
          selectOrg(saved.organization_id||"all");setSearch(saved.query||"");setFilter(saved.status||"ALL");
        }}/>
      <section className="table-card">
        <div className="data-table compliance-table">
          <div className="table-head">
            <span>{t("obligation")}</span>
            <span>{t("organization")}</span>
            <span>{t("deadline")}</span>
            <span>{t("owner")}</span>
            <span>{t("status")}</span>
            <span />
          </div>
          {pageItems.map((item) => (
            <button
              className="table-row"
              key={item.id}
              onClick={() => selectCompliance(item)}
            >
              <span className="primary-cell">
                <i
                  className={`category-icon category-${item.category.toLowerCase().replace(" ", "-")}`}
                >
                  {item.code.slice(0, 2)}
                </i>
                <span>
                  <strong title={item.title}>{item.title}</strong>
                  <small>
                    {item.code} · {item.period}
                  </small>
                </span>
              </span>
              <span>
                <strong>
                  {
                    organizations.find((o) => o.id === item.organization_id)
                      ?.name
                  }
                </strong>
                <small>{item.category}</small>
              </span>
              <span>
                <strong>{niceDate(item.statutory_deadline)}</strong>
                <small>
                  {item.internal_target
                    ? uiText("Common.interface.targetNamed", { date: niceDate(item.internal_target, true) })
                    : uiText("Common.interface.noInternalTarget")}
                </small>
              </span>
              <span className="owner-cell">
                <Avatar name={item.owner_name} label={item.owner_initials} />
                <span>{item.owner_name}</span>
              </span>
              <span>
                <StatusBadge status={item.status} />
              </span>
              <span>
                <ChevronRight size={17} />
              </span>
            </button>
          ))}
        </div>
        {visible.length === 0 && (
          <EmptyState
            icon={<Search />}
            title={t("emptyTitle")}
            text={t("emptyText")}
          />
        )}
        <div className="table-footer">
          <span>
             {uiText("Common.interface.showing")} {visible.length ? (page - 1) * pageSize + 1 : 0}  {uiText("Common.interface.to")}{" "}
            {Math.min(page * pageSize, visible.length)}  {uiText("Common.interface.of")} {visible.length}{" "}
             {uiText("Common.interface.entries")} </span>
          <nav className="table-pagination" aria-label={uiText("Common.interface.compliancePages")}>
            <button
              disabled={page <= 1}
              onClick={() => setPagination({ key: queryKey, page: page - 1 })}
            >
               {uiText("ComplianceMaster.previous")} </button>
            <span aria-current="page">
              {page} / {pageCount}
            </span>
            <button
              disabled={page >= pageCount}
              onClick={() => setPagination({ key: queryKey, page: page + 1 })}
            >
               {uiText("ComplianceMaster.next")} </button>
          </nav>
        </div>
      </section>
    </div>
  );
}

function TasksView({
  currentOrg, selectOrg, organizations,
  initialRecordId,
  items,
  compliances,
  documents,
  toggleTask,
  taskUpdated,
  setShowNewTask,
}: {
  currentOrg:string; selectOrg:(id:string)=>void; organizations:Organization[];
  initialRecordId?: string;
  items: ComplianceTask[];
  compliances: Compliance[];
  documents: ComplianceDocument[];
  toggleTask: (t: ComplianceTask) => void;
  taskUpdated: (task: ComplianceTask) => void;
  setShowNewTask: (v: boolean) => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Tasks");
  const common = useTranslations("Common");
  const user = useCurrentUser();
  const [tab, setTab] = useState("OPEN");
  const [assignee, setAssignee] = useState("ALL");
  const [selectedTask, setSelectedTask] = useState<ComplianceTask | null>(null);
  useEffect(() => {
    if (initialRecordId) setSelectedTask(items.find((item) => item.id === initialRecordId) || null);
  }, [initialRecordId, items]);
  const assignees = [...new Set(items.map((item) => item.assignee_name))].sort(
    localizedCollator().compare,
  );
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const weekEnd = new Date(today);
  weekEnd.setDate(weekEnd.getDate() + 7);
  const dueThisWeek = items.filter(
    (item) =>
      item.status !== "DONE" &&
      new Date(`${item.due_at}T12:00:00`) >= today &&
      new Date(`${item.due_at}T12:00:00`) <= weekEnd,
  ).length;
  const todayKey = new Date().toISOString().slice(0, 10);
  const visible = items.filter((item) => {
    const matchesTab = tab === "ALL" ||
      (tab === "MINE" && item.assignee_user_id === user.id) ||
      (tab === "TODAY" && item.status !== "DONE" && item.due_at === todayKey) ||
      (tab === "OVERDUE" && item.status !== "DONE" && item.due_at < todayKey) ||
      (tab === "DONE" && item.status === "DONE") ||
      (tab === "OPEN" && item.status !== "DONE");
    return matchesTab && (assignee === "ALL" || item.assignee_name === assignee);
  });
  return (
    <>
      <div className="page">
        <PageHeading
          title={t("title")}
          text={t("description")}
          action={
            <button
              className="button primary"
              onClick={() => setShowNewTask(true)}
            >
              <Plus size={17} />
              {t("add")}
            </button>
          }
        />
        <div className="task-stats">
          <div>
            <span>{t("open")}</span>
            <strong>{items.filter((i) => i.status !== "DONE").length}</strong>
          </div>
          <div>
            <span>{t("dueDate")}</span>
            <strong>{dueThisWeek}</strong>
          </div>
          <div>
            <span>{common("priority.HIGH")}</span>
            <strong>
              {
                items.filter(
                  (i) =>
                    ["HIGH", "CRITICAL"].includes(i.priority) &&
                    i.status !== "DONE",
                ).length
              }
            </strong>
          </div>
          <div>
            <span>{t("completed")}</span>
            <strong>{items.filter((i) => i.status === "DONE").length}</strong>
          </div>
        </div>
        <div className="toolbar task-toolbar">
          <div className="filter-tabs">
            {["OPEN", "MINE", "TODAY", "OVERDUE", "DONE", "ALL"].map((item) => (
              <button
                key={item}
                className={tab === item ? "active" : ""}
                onClick={() => setTab(item)}
              >
                {item === "OPEN"
                  ? t("open")
                  : item === "MINE"
                    ? t("myTasks")
                    : item === "TODAY"
                      ? t("dueToday")
                      : item === "OVERDUE"
                        ? t("overdue")
                  : item === "DONE"
                    ? t("completed")
                    : common("items", { count: items.length })}
              </button>
            ))}
          </div>
          <label className="filter-select">
            <Users size={16} />
            <select
              aria-label={t("assignee")}
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="ALL">{t("assignee")}</option>
              {assignees.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <ChevronDown size={14} />
          </label>
        </div>
        <SavedRegisterViews scope="TASKS" filters={{organization_id:currentOrg==="all"?null:currentOrg,
          status:tab==="DONE"?"DONE":tab==="ALL"?null:"OPEN",timing:tab==="OVERDUE"?"OVERDUE":"ALL",assignee:assignee==="ALL"?null:assignee}}
          unavailable={["MINE","TODAY"].includes(tab)?uiText("Common.interface.myTasksAndTodayAreRelativeViewsAndCannotBeSavedFaithfullyWithTheCurrentSavedViewContract"):""}
          apply={saved=>{
            requireCompatibleFilters(saved,["status","timing","assignee","organization_id"], filter => uiText("Common.interface.unsupportedFilter", { filter }));
            if(saved.organization_id&&!organizations.some(org=>org.id===saved.organization_id)) throw new Error(uiText("Common.interface.savedOrganizationIsNoLongerAccessible"));
            if(saved.status&&!['OPEN','DONE'].includes(saved.status)||saved.timing&&!['ALL','OVERDUE'].includes(saved.timing)||saved.timing==='OVERDUE'&&saved.status==='DONE') throw new Error(uiText("Common.interface.thisTaskViewUsesUnsupportedStatusOrTimingFilters"));
            selectOrg(saved.organization_id||"all");setAssignee(saved.assignee||"ALL");setTab(saved.timing==="OVERDUE"?"OVERDUE":saved.status==="DONE"?"DONE":saved.status?"OPEN":"ALL");
          }}/>
        <section className="card task-page-list">
          {visible.map((task) => {
            const compliance = compliances.find(
              (c) => c.id === task.compliance_id,
            );
            return (
              <div
                className={`task-page-row ${task.status === "DONE" ? "done" : ""}`}
                key={task.id}
              >
                <button
                  className="large-check"
                  aria-label={`${task.status === "DONE" ? common("status.OPEN") : common("status.COMPLETED")} ${task.title}`}
                  onClick={() => toggleTask(task)}
                >
                  {task.status === "DONE" && <Check size={16} />}
                </button>
                <div className="task-page-main">
                  <strong title={task.title}>{task.title}</strong>
                  <span title={compliance?.title}>
                    {compliance?.title || t("linkedCompliance")}
                  </span>
                </div>
                <span
                  className={`priority-pill ${task.priority.toLowerCase()}`}
                >
                  {common(`priority.${task.priority}`)}
                </span>
                <div className="due-cell">
                  <Clock3 size={15} />
                  <span>
                    {t("dueDate")} {niceDate(task.due_at)}
                  </span>
                </div>
                <div className="task-assignee">
                  <Avatar
                    name={task.assignee_name}
                    label={task.assignee_initials}
                  />
                  <span title={task.assignee_name}>{task.assignee_name}</span>
                </div>
                <button
                  className="icon-button plain"
                  aria-label={uiText("Common.interface.viewNamed", { name: task.title })}
                  onClick={() => setSelectedTask(task)}
                >
                  <MoreHorizontal size={18} />
                </button>
              </div>
            );
          })}
          {visible.length === 0 && (
            <EmptyState
              icon={<ListChecks />}
              title={t("emptyTitle")}
              text={t("emptyText")}
            />
          )}
        </section>
      </div>
      {selectedTask && (
        <TaskDetailsModal
          task={selectedTask}
          compliance={compliances.find(
            (item) => item.id === selectedTask.compliance_id,
          )}
          documents={documents.filter((document) => document.organization_id === selectedTask.organization_id)}
          taskUpdated={(updated) => { setSelectedTask(updated); taskUpdated(updated); }}
          close={() => setSelectedTask(null)}
        />
      )}
    </>
  );
}

function CalendarView({
  items,
  selectCompliance,
}: {
  items: Compliance[];
  selectCompliance: (c: Compliance) => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Calendar");
  items = items.filter((item) => isOpenCompliance(item.status));
  const now = new Date();
  const [month, setMonth] = useState(
    () => new Date(now.getFullYear(), now.getMonth(), 1),
  );
  const dateKey = (date: Date) =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const monthKey = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`;
  const firstOffset = (month.getDay() + 6) % 7;
  const gridStart = new Date(month);
  gridStart.setDate(1 - firstOffset);
  const days = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + index);
    return date;
  });
  const monthItems = items
    .filter((item) => item.statutory_deadline.startsWith(monthKey))
    .sort((a, b) => a.statutory_deadline.localeCompare(b.statutory_deadline));
  const monthLabel = new Intl.DateTimeFormat(activeLocale(), {
    month: "long",
    year: "numeric",
  }).format(month);
  const weekdayLabels = Array.from({ length: 7 }, (_, index) =>
    new Intl.DateTimeFormat(activeLocale(), { weekday: "short" }).format(
      new Date(2024, 0, index + 1),
    ),
  );

  function exportCalendar() {
    const escape = (value: string) =>
      value
        .replaceAll("\\", "\\\\")
        .replaceAll(",", "\\,")
        .replaceAll(";", "\\;")
        .replaceAll("\n", "\\n");
    const events = items.flatMap((item) => {
      const statutory = [
        `BEGIN:VEVENT`,
        `UID:${item.id}-statutory@setu.local`,
        `DTSTART;VALUE=DATE:${item.statutory_deadline.replaceAll("-", "")}`,
        `SUMMARY:${escape(`${item.code}: ${item.title}`)}`,
        `DESCRIPTION:${escape(`Statutory deadline · ${item.owner_name} · ${item.period}`)}`,
        `END:VEVENT`,
      ].join("\r\n");
      const target = item.internal_target
        ? [
            `BEGIN:VEVENT`,
            `UID:${item.id}-target@setu.local`,
            `DTSTART;VALUE=DATE:${item.internal_target.replaceAll("-", "")}`,
            `SUMMARY:${escape(`Internal target: ${item.title}`)}`,
            `DESCRIPTION:${escape(`${item.code} · ${item.owner_name}`)}`,
            `END:VEVENT`,
          ].join("\r\n")
        : null;
      return target ? [statutory, target] : [statutory];
    });
    downloadText(
      "setu-compliance-calendar.ics",
      [
        `BEGIN:VCALENDAR`,
        `VERSION:2.0`,
        `PRODID:-//Setu//NGO Compliance//EN`,
        ...events,
        `END:VCALENDAR`,
      ].join("\r\n"),
      "text/calendar;charset=utf-8",
    );
  }

  return (
    <div className="page">
      <PageHeading
        title={t("title")}
        text={t("description")}
        action={
          <button className="button secondary" onClick={exportCalendar}>
            <Download size={17} />
            {t("export")}
          </button>
        }
      />
      <div className="calendar-layout">
        <section className="card calendar-card">
          <div className="calendar-head">
            <button
              className="icon-button plain"
              aria-label={t("previousMonth")}
              onClick={() =>
                setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))
              }
            >
              <ChevronDown className="rotate-90" size={18} />
            </button>
            <h2>{monthLabel}</h2>
            <button
              className="icon-button plain"
              aria-label={t("nextMonth")}
              onClick={() =>
                setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))
              }
            >
              <ChevronRight size={18} />
            </button>
            <button
              className="button secondary small today"
              onClick={() =>
                setMonth(new Date(now.getFullYear(), now.getMonth(), 1))
              }
            >
              {t("today")}
            </button>
          </div>
          <div className="weekdays">
            {weekdayLabels.map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
          <div className="month-grid">
            {days.map((date) => {
              const key = dateKey(date);
              const statutory = items.filter(
                (item) => item.statutory_deadline === key,
              );
              const targets = items.filter(
                (item) => item.internal_target === key,
              );
              return (
                <div
                  key={key}
                  className={`${date.getMonth() !== month.getMonth() ? "outside" : ""} ${key === dateKey(now) ? "today-cell" : ""}`}
                >
                  <span>{date.getDate()}</span>
                  {statutory.map((item) => (
                    <button
                      key={`${item.id}-deadline`}
                      title={item.title}
                      onClick={() => selectCompliance(item)}
                      className={`calendar-event ${item.priority.toLowerCase()}`}
                    >
                      <i />
                      {item.code}
                    </button>
                  ))}
                  {targets.map((item) => (
                    <button
                      key={`${item.id}-target`}
                      title={`${t("internalTarget")}: ${item.title}`}
                      onClick={() => selectCompliance(item)}
                      className="calendar-event target"
                    >
                      <i />
                      {item.code}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        </section>
        <aside className="card agenda">
          <CardTitle
            title={t("agenda", {
              month: new Intl.DateTimeFormat(activeLocale(), {
                month: "long",
              }).format(month),
            })}
            sub={t("deadlines", { count: monthItems.length })}
          />
          <div className="agenda-list">
            {monthItems.map((item) => (
              <button onClick={() => selectCompliance(item)} key={item.id}>
                <div className="date-tile">
                  <strong>{Number(item.statutory_deadline.slice(8))}</strong>
                  <span>
                    {new Intl.DateTimeFormat(activeLocale(), {
                      month: "short",
                    }).format(new Date(`${item.statutory_deadline}T12:00:00`))}
                  </span>
                </div>
                <div>
                  <strong>{item.title}</strong>
                  <span>
                    {item.code} · {item.owner_name}
                  </span>
                  <StatusBadge status={item.status} />
                </div>
              </button>
            ))}
            {monthItems.length === 0 && (
              <EmptyState
                icon={<CalendarDays />}
                title={t("emptyTitle")}
                text={t("emptyText")}
              />
            )}
          </div>
          <div className="calendar-legend">
            <span>
              <i className="critical" />
               {uiText("Common.interface.criticalHighRisk")} </span>
            <span>
              <i className="medium" />
               {uiText("Common.interface.normalDeadline")} </span>
            <span>
              <i className="target" />
              {t("internalTarget")}
            </span>
          </div>
        </aside>
      </div>
    </div>
  );
}

function DocumentsView({
  initialRecordId,
  items,
  organizations,
  openUpload,
  showToast,
  updateDocument,
}: {
  initialRecordId?: string;
  items: ComplianceDocument[];
  organizations: Organization[];
  openUpload: () => void;
  showToast: (message: string) => void;
  updateDocument: (document: ComplianceDocument) => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Documents");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("ALL");
  const [selectedDoc, setSelectedDoc] = useState<ComplianceDocument | null>(
    null,
  );
  useEffect(() => {
    if (initialRecordId) setSelectedDoc(items.find((item) => item.id === initialRecordId) || null);
  }, [initialRecordId, items]);
  const categories = [...new Set(items.map((item) => item.category))].sort(
    localizedCollator().compare,
  );
  const visible = items.filter(
    (doc) =>
      doc.name.toLowerCase().includes(search.toLowerCase()) &&
      (category === "ALL" || doc.category === category),
  );
  return (
    <>
      <div className="page">
        <PageHeading
          title={t("title")}
          text={t("description")}
          action={
            <button className="button primary" onClick={() => openUpload()}>
              <Upload size={17} />
              {t("upload")}
            </button>
          }
        />
        <div className="document-summary">
          <div>
            <FolderOpen />
            <span>
              {t("documentCount", { count: items.length })}
            </span>
          </div>
          <div>
            <ShieldCheck />
            <span>
              <strong>{t("version")}</strong> {t("versionedHistory")}
            </span>
          </div>
          <div>
            <AlertTriangle />
            <span>
              {t("expiryTracked", { count: items.filter((i) => i.expiry_at).length })}
            </span>
          </div>
        </div>
        <div className="toolbar">
          <div className="search-box">
            <Search size={17} />
            <input
              id="document-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label={t("search")}
              placeholder={t("search")}
            />
          </div>
          <label className="filter-select">
            <FolderOpen size={16} />
            <select
              aria-label={t("category")}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="ALL">{t("allCategories")}</option>
              {categories.map((item) => (
                <option value={item} key={item}>
                  {item}
                </option>
              ))}
            </select>
            <ChevronDown size={14} />
          </label>
        </div>
        <section className="table-card">
          <div className="data-table document-table">
            <div className="table-head">
              <span>{t("document")}</span>
              <span>{t("organization")}</span>
              <span>{t("category")}</span>
              <span>{t("expiry")}</span>
              <span>{t("uploadedBy")}</span>
              <span />
            </div>
            {visible.map((doc) => (
              <div className="table-row" key={doc.id}>
                <span className="primary-cell">
                  <i className="file-icon">
                    <FileText size={19} />
                  </i>
                  <span>
                    <strong>{doc.name}</strong>
                    <small>
                      {doc.file_type} · {doc.size_label} · v{doc.version}
                    </small>
                  </span>
                </span>
                <span>
                  <strong>
                    {
                      organizations.find((o) => o.id === doc.organization_id)
                        ?.name
                    }
                  </strong>
                  <small>{t("authorizedAccess")}</small>
                </span>
                <span>
                  <span className="category-pill">{doc.category}</span>
                </span>
                <span>
                  <strong>{niceDate(doc.expiry_at)}</strong>
                  <small>
                    {doc.expiry_at ? t("reminderActive") : t("noExpiry")}
                  </small>
                </span>
                <span className="owner-cell">
                  <Avatar name={doc.uploaded_by} />
                  <span>{doc.uploaded_by}</span>
                </span>
                <span>
                  <button
                    className="icon-button plain"
                    aria-label={uiText("Common.interface.viewNamed", { name: doc.name })}
                    onClick={() => setSelectedDoc(doc)}
                  >
                    <MoreHorizontal size={18} />
                  </button>
                </span>
              </div>
            ))}
          </div>
          {visible.length === 0 && (
            <EmptyState
              icon={<FolderOpen />}
              title={t("emptyTitle")}
              text={t("emptyText")}
            />
          )}
        </section>
      </div>
      {selectedDoc && (
        <DocumentDetailsModal
          doc={selectedDoc}
          organization={organizations.find(
            (item) => item.id === selectedDoc.organization_id,
          )}
          close={() => setSelectedDoc(null)}
          download={() => {
            documentReceipt(selectedDoc);
            showToast("Document record downloaded");
          }}
          onVersion={(updated) => {
            setSelectedDoc(updated);
            updateDocument(updated);
            showToast(uiText("Common.interface.versionAdded", { version: updated.version }));
          }}
        />
      )}
    </>
  );
}

function AdministrationView({
  organizations,
  compliances,
  definitions,
  memberships,
  subscription,
  setShowNewOrganization,
  setShowInvite,
}: {
  organizations: Organization[];
  compliances: Compliance[];
  definitions: ComplianceDefinition[];
  memberships: Membership[];
  subscription: Subscription;
  setShowNewOrganization: (value: boolean) => void;
  setShowInvite: (value: boolean) => void;
}) {
  const uiText = useTranslations();
  const activeMembers = memberships.filter(
    (member) => member.status !== "INACTIVE",
  ).length;
  return (
    <div className="page">
      <PageHeading
        eyebrow={uiText("Common.interface.tenantControls")}
        title={uiText("Common.nav.administration")}
        text={uiText("Common.interface.onboardNGOsManageWorkspaceAccountsReviewRulesAndMonitorPlanLimits")}
        action={
          <div className="heading-actions">
            <button
              className="button secondary"
              onClick={() => setShowInvite(true)}
            >
              <Users size={17} />
               {uiText("Common.interface.addResponsibility")} </button>
            <button
              className="button primary"
              onClick={() => setShowNewOrganization(true)}
            >
              <Plus size={17} />
               {uiText("Common.interface.addOrganization")} </button>
          </div>
        }
      />
      <UserManagement currentUser={useCurrentUser()} />
      <PlatformNavigation />
      <OrganizationComplianceProfile organizations={organizations} />
      <div className="admin-summary">
        <div>
          <span>{uiText("Subscriptions.currentPlan")}</span>
          <strong>{subscription.plan_name}</strong>
          <small>
            {subscription.status.toLowerCase()}  {uiText("Common.interface.through")}{" "}
            {niceDate(subscription.period_end)}
          </small>
        </div>
        <div>
          <span>{uiText("GlobalSearch.groups.organizations")}</span>
          <strong>
            {organizations.length} / {subscription.organization_limit ?? uiText("Common.interface.notAssigned")}
          </strong>
          <small>{uiText("Common.interface.consultantPortfolioCapacity")}</small>
        </div>
        <div>
          <span>{uiText("Common.interface.members")}</span>
          <strong>
            {activeMembers} / {subscription.user_limit ?? uiText("Common.interface.notAssigned")}
          </strong>
          <small>
            {memberships.filter((member) => member.status === "INVITED").length}{" "}
             {uiText("Common.interface.invitationsPending")} </small>
        </div>
        <div>
          <span>{uiText("Common.interface.activeRules")}</span>
          <strong>{definitions.length}</strong>
          <small>{uiText("Common.interface.versionedCatalogueEntries")}</small>
        </div>
      </div>
      <div className="admin-grid">
        <section className="card admin-organizations">
          <CardTitle
            title={uiText("GlobalSearch.groups.organizations")}
            sub={uiText("Common.interface.legalEntitiesTenant")}
            action={
              <button
                className="text-button"
                onClick={() => setShowNewOrganization(true)}
              >
                 {uiText("Common.interface.addOrganization")} <Plus size={15} />
              </button>
            }
          />
          <div className="organization-cards">
            {organizations.map((organization) => {
              const rows = compliances.filter(
                (item) => item.organization_id === organization.id,
              );
              const risk = rows.filter(
                (item) =>
                  isOpenCompliance(item.status) &&
                  ["HIGH", "CRITICAL"].includes(item.priority),
              ).length;
              return (
                <article key={organization.id}>
                  <span className="org-mini">{organization.name[0]}</span>
                  <div>
                    <Link href={`/organizations/${organization.id}`}><strong>{organization.name}</strong></Link>
                    <small>
                      {organization.legal_type} · {organization.city}
                    </small>
                    <p>{organization.registration_number}</p>
                  </div>
                  <div className="org-card-stats">
                    <b>
                      {rows.length}
                      <small>{uiText("Common.interface.obligations")}</small>
                    </b>
                    <b className={risk ? "risk" : "safe"}>
                      {risk}
                      <small>{uiText("Common.interface.highRisk")}</small>
                    </b>
                  </div>
                  <StatusBadge status={organization.status} />
                </article>
              );
            })}
          </div>
        </section>
        <section className="card plan-card">
          <CardTitle
            title={uiText("Common.interface.planEntitlements")}
            sub={uiText("Common.interface.serverLimits")}
          />
          <div className="plan-name">
            <ShieldCheck size={22} />
            <div>
              <strong>{subscription.plan_name}</strong>
              <span>{uiText("Common.interface.coreCompliancePortfolioManagementReports")}</span>
            </div>
          </div>
          <UsageBar
            label={uiText("Common.interface.organization")}
            value={organizations.length}
            limit={subscription.organization_limit}
          />
          <UsageBar
            label={uiText("Common.interface.members")}
            value={activeMembers}
            limit={subscription.user_limit}
          />
          <UsageBar
            label={uiText("Common.interface.storageAllocation")}
            value={0}
            limit={subscription.storage_limit_gb}
            suffix=" GB"
          />
          <p className="plan-note">
             {uiText("Common.interface.changingPlansNeverDeletesOrganizationRecordsOrEvidenceHistory")} </p>
        </section>
        <section className="card team-card">
          <CardTitle
            title={uiText("Common.interface.responsibilityDirectory")}
            sub={uiText("Common.interface.legacyPlanning")}
            action={
              <button
                className="text-button"
                onClick={() => setShowInvite(true)}
              >
                 {uiText("Common.interface.addResponsibility")} <Plus size={15} />
              </button>
            }
          />
          <div className="team-list">
            {memberships.map((member) => (
              <div key={member.id}>
                <Avatar name={member.name} />
                <span>
                  <strong>{member.name}</strong>
                  <small>{member.email}</small>
                </span>
                <span className="role-pill">
                  {member.role.replaceAll("_", " ")}
                </span>
                <span>
                  <strong>
                    {member.organization_id
                      ? organizations.find(
                          (organization) =>
                            organization.id === member.organization_id,
                        )?.name
                      : uiText("Common.allOrganizations")}
                  </strong>
                  <small>{member.status.toLowerCase()}</small>
                </span>
              </div>
            ))}
          </div>
        </section>
        <section className="card rules-card">
          <CardTitle
            title={uiText("Common.interface.complianceCatalogue")}
            sub={uiText("Common.interface.activeOnboardingRules")}
          />
          <div className="rule-list">
            {definitions.map((definition) => (
              <div key={definition.id}>
                <i>{definition.code.slice(0, 2)}</i>
                <span>
                  <strong>{definition.title}</strong>
                  <small>
                    {definition.category}  {uiText("Common.interface.ruleV")}{definition.rule_version}
                  </small>
                </span>
                <span>
                  <b>
                    {definition.requires_fcra
                      ? uiText("Common.interface.fcraOnly")
                      : definition.applicable_legal_types.replaceAll(",", ", ")}
                  </b>
                  <small>
                     {uiText("Common.interface.target")} {definition.internal_lead_days}  {uiText("Common.interface.daysEarly")} </small>
                </span>
                <span
                  className={`priority-pill ${definition.priority.toLowerCase()}`}
                >
                  {definition.priority}
                </span>
              </div>
            ))}
          </div>
          <p className="rule-disclaimer">
             {uiText("Common.interface.catalogueDatesAreConfigurableDemonstrationDataAndRequireQualifiedDomainValidationBeforeProductionUse")} </p>
        </section>
      </div>
    </div>
  );
}

function UsageBar({
  label,
  value,
  limit,
  suffix = "",
}: {
  label: string;
  value: number;
  limit: number | null;
  suffix?: string;
}) {
  const uiText = useTranslations();
  const percent = limit === null ? 0 : Math.min(100, Math.round((value / Math.max(1, limit)) * 100));
  return (
    <div className="usage-row">
      <div>
        <span>{label}</span>
        <strong>
          {value}
          {suffix}  {uiText("Common.interface.of")} {limit ?? uiText("Common.interface.notAssigned")}
          {suffix}
        </strong>
      </div>
      <div>
        <i style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function NotificationPanel({
  items,
  onRead,
  onReadAll,
  onViewAll,
}: {
  items: Notification[];
  onRead: (id: string) => void;
  onReadAll: () => void;
  onViewAll: () => void;
}) {
  const uiText = useTranslations();
  return (
    <div className="notification-panel">
      <div className="panel-head">
        <div>
          <strong>{uiText("Settings.notificationsTitle")}</strong>
          <span>{items.filter((i) => !i.is_read).length}  {uiText("Common.interface.unread")}</span>
        </div>
        <button
          onClick={onReadAll}
          disabled={items.every((item) => item.is_read)}
        >
           {uiText("Common.interface.markAllRead")} </button>
      </div>
      {items.slice(0, 4).map((item) => (
        <button
          className={item.is_read ? "read" : ""}
          onClick={() => onRead(item.id)}
          key={item.id}
        >
          <span className={`notice-icon ${item.kind.toLowerCase()}`}>
            {item.kind === "WARNING" ? (
              <AlertTriangle size={16} />
            ) : item.kind === "DOCUMENT" ? (
              <FileText size={16} />
            ) : (
              <ClipboardCheck size={16} />
            )}
          </span>
          <span>
            <strong><ComplianceNotificationTitle item={item} /></strong>
            <small><ComplianceNotificationMessage item={item} /></small>
            <em>{niceDate(item.created_at)}</em>
          </span>
          {!item.is_read && <i />}
        </button>
      ))}
      <button className="panel-foot" onClick={onViewAll}>
         {uiText("Common.interface.viewAllNotifications")} </button>
    </div>
  );
}

function ComplianceDrawer({
  item,
  templateUpdated,
  org,
  relatedTasks,
  relatedDocs,
  close,
  updateStatus,
  toggleTask,
  attachEvidence,
  showToast,
}: {
  item: Compliance;
  templateUpdated: (item: Compliance) => void;
  org?: Organization;
  relatedTasks: ComplianceTask[];
  relatedDocs: ComplianceDocument[];
  close: () => void;
  updateStatus: (
    item: Compliance,
    status: string,
    reason?: string,
    submissionReference?: string,
  ) => Promise<void>;
  toggleTask: (task: ComplianceTask) => void;
  attachEvidence: () => void;
  showToast: (message: string) => void;
}) {
  const uiText = useTranslations();
  const runtimeLabel = useTranslations("Runtime")("open");
  const cancelLabel = useTranslations("Common")("status.CANCELLED");
  const [transition, setTransition] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [submissionReference, setSubmissionReference] = useState("");
  const [saving, setSaving] = useState(false);
  const actions: Record<
    string,
    {
      status: string;
      label: string;
      needsReason?: boolean;
      needsReference?: boolean;
      secondary?: { status: string; label: string; needsReason?: boolean };
    }
  > = {
    PLANNED: {
      status: "IN_PROGRESS",
      label: uiText("Common.interface.startWork"),
      secondary: {
        status: "NOT_APPLICABLE",
        label: uiText("Common.interface.markNotApplicable"),
        needsReason: true,
      },
    },
    NOT_STARTED: {
      status: "IN_PROGRESS",
      label: uiText("Common.interface.startWork"),
      secondary: {
        status: "NOT_APPLICABLE",
        label: uiText("Common.interface.markNotApplicable"),
        needsReason: true,
      },
    },
    IN_PROGRESS: {
      status: "UNDER_REVIEW",
      label: uiText("Common.interface.sendForReview"),
      secondary: {
        status: "ON_HOLD",
        label: uiText("Common.interface.placeOnHold"),
        needsReason: true,
      },
    },
    UNDER_REVIEW: {
      status: "READY_TO_FILE",
      label: uiText("Common.interface.approveForFiling"),
      secondary: {
        status: "CHANGES_REQUESTED",
        label: uiText("Common.interface.requestChanges"),
        needsReason: true,
      },
    },
    CHANGES_REQUESTED: { status: "IN_PROGRESS", label: uiText("Common.interface.resumeWork") },
    READY_TO_FILE: {
      status: "FILED",
      label: uiText("Common.interface.recordFiling"),
      needsReference: true,
      secondary: {
        status: "CHANGES_REQUESTED",
        label: uiText("Common.interface.requestChanges"),
        needsReason: true,
      },
    },
    FILED: { status: "COMPLETED", label: uiText("Common.interface.completeCompliance") },
    COMPLETED: {
      status: "IN_PROGRESS",
      label: uiText("Common.interface.reopenCompliance"),
      needsReason: true,
    },
    ON_HOLD: { status: "IN_PROGRESS", label: uiText("Common.interface.resumeWork"), secondary: { status: "CANCELLED", label: cancelLabel, needsReason: true } },
    NOT_APPLICABLE: {
      status: "IN_PROGRESS",
      label: uiText("Common.interface.reopenAsApplicable"),
      needsReason: true,
    },
    OVERDUE: {
      status: "IN_PROGRESS",
      label: uiText("Common.interface.recordRecoveryWork"),
      secondary: {
        status: "ON_HOLD",
        label: uiText("Common.interface.placeOnHold"),
        needsReason: true,
      },
    },
  };
  const action = item.template_version_id ? undefined : actions[item.status];
  const selected: {
    status: string;
    label: string;
    needsReason?: boolean;
    needsReference?: boolean;
  } | null =
    transition === action?.status
      ? action
      : action?.secondary && transition === action.secondary.status
        ? action.secondary
        : null;

  async function run(status: string, needsInput = false) {
    if (needsInput) {
      setTransition(status);
      setReason("");
      setSubmissionReference("");
      return;
    }
    setSaving(true);
    await updateStatus(item, status);
    setSaving(false);
  }
  async function confirmTransition() {
    if (!transition || !selected) return;
    setSaving(true);
    await updateStatus(
      item,
      transition,
      reason.trim() || undefined,
      submissionReference.trim() || undefined,
    );
    setSaving(false);
    setTransition(null);
  }

  return (
    <>
      <button
        className="drawer-scrim"
        aria-label={uiText("Common.interface.closeComplianceDetails")}
        onClick={close}
      />
      <aside className="drawer">
        <div className="drawer-head">
          <div>
            <span>
              {item.code} · {item.period}
            </span>
            <h2>{item.title}</h2>
          </div>
          <button
            className="icon-button plain"
            aria-label={uiText("Common.interface.closeComplianceDetails")}
            onClick={close}
          >
            <X size={20} />
          </button>
        </div>
        <div className="drawer-body">
          <div className="drawer-status">
            <StatusBadge status={item.status} />
            <span className={`priority-pill ${item.priority.toLowerCase()}`}>
              {item.priority}  {uiText("Common.interface.priority")} </span>
          </div>
          <Link className="button secondary" href={`/compliances/${item.id}`}>{runtimeLabel}</Link>
          {item.template_version_id && <ComplianceTemplateRuntime item={item} updated={templateUpdated} />}
          <div className="progress-block">
            <div>
              <span>{uiText("Common.interface.preparationProgress")}</span>
              <strong>{item.progress}%</strong>
            </div>
            <div className="progress-track">
              <b style={{ width: `${item.progress}%` }} />
            </div>
          </div>
          {item.risk_note && (
            <div className="risk-note">
              <AlertTriangle size={17} />
              <div>
                <strong>{uiText("Common.interface.attentionNeeded")}</strong>
                <p>{item.risk_note}</p>
              </div>
            </div>
          )}
          <section className="detail-section">
            <h3>{uiText("Common.interface.keyDetails")}</h3>
            <div className="detail-grid">
              <div>
                <span>{uiText("Authentication.organization")}</span>
                <strong>{org?.name}</strong>
              </div>
              <div>
                <span>{uiText("ComplianceMaster.category")}</span>
                <strong>{item.category}</strong>
              </div>
              <div>
                <span>{uiText("ComplianceMaster.statutoryDeadline")}</span>
                <strong>{niceDate(item.statutory_deadline)}</strong>
              </div>
              <div>
                <span>{uiText("Calendar.internalTarget")}</span>
                <strong>{niceDate(item.internal_target)}</strong>
              </div>
              <div>
                <span>{uiText("Common.interface.accountableOwner")}</span>
                <strong className="owner-detail">
                  <Avatar name={item.owner_name} label={item.owner_initials} />
                  {item.owner_name}
                </strong>
              </div>
              <div>
                <span>{uiText("ComplianceMaster.legal_reference")}</span>
                <strong>{item.legal_reference}</strong>
              </div>
            </div>
          </section>
          <section className="detail-section">
            <div className="section-title">
              <h3>{uiText("ComplianceMaster.checklist")}</h3>
              <span>
                {relatedTasks.filter((task) => task.status === "DONE").length}/
                {relatedTasks.length}  {uiText("Common.interface.complete")} </span>
            </div>
            {relatedTasks.length ? (
              relatedTasks.map((task) => (
                <div className="drawer-list" key={task.id}>
                  <button
                    aria-label={
                      task.status === "DONE"
                        ? uiText("Common.interface.reopenNamed", { name: task.title })
                        : uiText("Common.interface.completeNamed", { name: task.title })
                    }
                    onClick={() => toggleTask(task)}
                    className={task.status === "DONE" ? uiText("Common.interface.complete") : ""}
                  >
                    {task.status === "DONE" && <Check size={13} />}
                  </button>
                  <div>
                    <strong>{task.title}</strong>
                    <small>
                      {task.assignee_name}  {uiText("Common.interface.dueLabel")} {niceDate(task.due_at, true)}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="muted">{uiText("Common.interface.noTasksLinkedYet")}</p>
            )}
          </section>
          <section className="detail-section">
            <div className="section-title">
              <h3>{uiText("Common.interface.evidence")}</h3>
              <span>{relatedDocs.length}  {uiText("Common.interface.files")}</span>
            </div>
            {relatedDocs.map((doc) => (
              <div className="drawer-list document" key={doc.id}>
                <span>
                  <FileText size={16} />
                </span>
                <div>
                  <strong>{doc.name}</strong>
                  <small>
                     {uiText("Common.interface.version")} {doc.version} · {doc.size_label}
                  </small>
                </div>
                <button
                  aria-label={uiText("Common.interface.downloadNamed", { name: doc.name })}
                  onClick={() => {
                    documentReceipt(doc);
                    showToast("Document record downloaded");
                  }}
                >
                  <Download size={16} />
                </button>
              </div>
            ))}
            <button className="upload-evidence" onClick={attachEvidence}>
              <Upload size={18} />
               {uiText("Common.interface.attachRequiredEvidence")} </button>
          </section>
          <ComplianceDiscussion complianceId={item.id} />
          {transition && selected && (
            <section className="transition-form">
              <strong>{selected.label}</strong>
              {"needsReason" in selected && selected.needsReason && (
                <label>
                  <span>{uiText("Common.interface.reason")}</span>
                  <textarea
                    autoFocus
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder={uiText("Common.interface.recordTheReasonForTheAuditTrail")}
                  />
                </label>
              )}
              {"needsReference" in selected && selected.needsReference && (
                <label>
                  <span>{uiText("Common.interface.submissionOrAcknowledgementReference")}</span>
                  <input
                    autoFocus
                    value={submissionReference}
                    onChange={(event) =>
                      setSubmissionReference(event.target.value)
                    }
                    placeholder={uiText("Common.interface.eGPortalAcknowledgementNumber")}
                  />
                </label>
              )}
              <div>
                <button
                  className="button secondary small"
                  onClick={() => setTransition(null)}
                >
                   {uiText("Common.actions.cancel")} </button>
                <button
                  className="button primary small"
                  disabled={
                    saving ||
                    ("needsReason" in selected && selected.needsReason
                      ? reason.trim().length < 3
                      : submissionReference.trim().length < 2)
                  }
                  onClick={confirmTransition}
                >
                  {saving ? uiText("Common.actions.saving") : uiText("Common.interface.confirm")}
                </button>
              </div>
            </section>
          )}
        </div>
        <div className="drawer-foot">
          <button className="button secondary" onClick={close}>
             {uiText("Common.actions.close")} </button>
          {action?.secondary && (
            <button
              className="button secondary"
              disabled={saving}
              onClick={() =>
                void run(
                  action.secondary!.status,
                  Boolean(action.secondary!.needsReason),
                )
              }
            >
              {action.secondary.label}
            </button>
          )}
          {action && (
            <button
              className="button primary"
              disabled={saving}
              onClick={() =>
                void run(
                  action.status,
                  Boolean(action.needsReason || action.needsReference),
                )
              }
            >
              {action.label}
            </button>
          )}
        </div>
      </aside>
    </>
  );
}

function ComplianceDiscussion({ complianceId }: { complianceId: string }) {
  const uiText = useTranslations();
  const currentUser = useCurrentUser();
  const [comments, setComments] = useState<ComplianceComment[]>([]);
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<ComplianceComment["kind"]>("COMMENT");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    loadComplianceComments(complianceId)
      .then(setComments)
      .catch(() => setError(uiText("Common.interface.discussionHistoryIsUnavailable")));
  }, [complianceId]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const created = await addComplianceComment(complianceId, body, kind);
      setComments((rows) => [created, ...rows]);
      setBody("");
    } catch (reason) {
      setError(
        localizedError(reason, uiText, uiText("Common.interface.couldNotSaveComment")),
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="detail-section discussion">
      <div className="section-title">
        <h3>{uiText("Common.interface.discussionAndExceptions")}</h3>
        <span>{comments.length}  {uiText("Common.interface.entries")}</span>
      </div>
      {comments.slice(0, 5).map((comment) => (
        <div className="discussion-entry" key={comment.id}>
          <Avatar name={comment.author_name} />
          <div>
            <strong>
              {comment.author_name}
              <span>{comment.kind.replaceAll("_", " ")}</span>
            </strong>
            <p>{comment.body}</p>
            <small>
              {formatDateTime(comment.created_at)}
            </small>
          </div>
        </div>
      ))}
      {currentUser.role !== "VIEWER" && (
        <form onSubmit={submit}>
          <select
            aria-label={uiText("Common.interface.entryType")}
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as ComplianceComment["kind"])
            }
          >
            <option value="COMMENT">{uiText("Common.interface.comment")}</option>
            <option value="CORRECTION">{uiText("Common.interface.correctionRequest")}</option>
            <option value="EXCEPTION">{uiText("Common.interface.exception")}</option>
            <option value="RECOVERY_PLAN">{uiText("Common.interface.recoveryPlan")}</option>
          </select>
          <textarea
            aria-label={uiText("Common.interface.discussionEntry")}
            required
            minLength={2}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder={uiText("Common.interface.recordContextACorrectionRequestExceptionOrRecoveryPlan")}
          />
          <button className="button primary small" disabled={saving}>
            {saving ? uiText("Common.actions.saving") : uiText("Common.interface.addEntry")}
          </button>
        </form>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function GuideModal({
  close,
  go,
}: {
  close: () => void;
  go: (view: View) => void;
}) {
  const uiText = useTranslations();
  return (
    <Modal
      title={uiText("Common.interface.complianceWorkflowGuide")}
      text={uiText("Common.interface.aSimpleOperatingRhythmForEveryObligation")}
      close={close}
    >
      <div className="modal-content">
        <div className="guide-steps">
          <div>
            <span>1</span>
            <div>
              <strong>{uiText("Common.interface.registerTheObligation")}</strong>
              <p>
                 {uiText("Common.interface.chooseTheNGODeadlineAccountableOwnerCategoryAndRiskPriority")} </p>
            </div>
          </div>
          <div>
            <span>2</span>
            <div>
              <strong>{uiText("Common.interface.assignPreparationTasks")}</strong>
              <p>
                 {uiText("Common.interface.breakTheObligationIntoClearEvidenceReviewAndFilingActions")} </p>
            </div>
          </div>
          <div>
            <span>3</span>
            <div>
              <strong>{uiText("Common.interface.attachEvidence")}</strong>
              <p>
                 {uiText("Common.interface.linkEachDocumentRecordToItsOrganizationAndComplianceItem")} </p>
            </div>
          </div>
          <div>
            <span>4</span>
            <div>
              <strong>{uiText("Common.interface.reviewAndComplete")}</strong>
              <p>
                 {uiText("Common.interface.sendPreparedWorkForReviewApproveItAndRetainTheAuditTrail")} </p>
            </div>
          </div>
        </div>
        <div className="modal-actions">
          <button className="button secondary" onClick={() => go("documents")}>
             {uiText("Common.interface.openEvidenceLibrary")} </button>
          <button className="button primary" onClick={() => go("compliance")}>
             {uiText("Common.interface.openComplianceRegister")} </button>
        </div>
      </div>
    </Modal>
  );
}

function HelpModal({
  close,
  go,
}: {
  close: () => void;
  go: (view: View) => void;
}) {
  const uiText = useTranslations();
  return (
    <Modal
      title={uiText("Common.interface.helpCentre")}
      text={uiText("Common.interface.quickAnswersForTheSetuDemonstrationWorkspace")}
      close={close}
    >
      <div className="modal-content">
        <div className="help-topics">
          <section>
            <ClipboardCheck size={19} />
            <div>
              <strong>{uiText("Compliance.title")}</strong>
              <p>
                 {uiText("Common.interface.searchFilterAndOpenAnObligationToManageItsReviewLifecycle")} </p>
            </div>
            <button onClick={() => go("compliance")}>
               {uiText("Common.actions.open")} <ArrowRight size={14} />
            </button>
          </section>
          <section>
            <ListChecks size={19} />
            <div>
              <strong>{uiText("Common.nav.tasks")}</strong>
              <p>
                 {uiText("Common.interface.createAssignmentsFilterByOwnerAndMarkChecklistWorkComplete")} </p>
            </div>
            <button onClick={() => go("tasks")}>
               {uiText("Common.actions.open")} <ArrowRight size={14} />
            </button>
          </section>
          <section>
            <FolderOpen size={19} />
            <div>
              <strong>{uiText("Common.interface.evidenceDocuments")}</strong>
              <p>
                 {uiText("Common.interface.registerDocumentMetadataAndLinkEvidenceToAnObligation")} </p>
            </div>
            <button onClick={() => go("documents")}>
               {uiText("Common.actions.open")} <ArrowRight size={14} />
            </button>
          </section>
          <section>
            <Gauge size={19} />
            <div>
              <strong>{uiText("Common.nav.reports")}</strong>
              <p>{uiText("Common.interface.reviewPortfolioHealthAndExportACSVManagementReport")}</p>
            </div>
            <button onClick={() => go("reports")}>
               {uiText("Common.actions.open")} <ArrowRight size={14} />
            </button>
          </section>
        </div>
        <div className="form-info">
          <CircleHelp size={17} />
           {uiText("Common.interface.thisIsALocalMVPActualFileStorageAndProductionSignInArePlannedBackendIntegrations")} </div>
        <div className="modal-actions">
          <button className="button primary" onClick={close}>
             {uiText("Common.status.DONE")} </button>
        </div>
      </div>
    </Modal>
  );
}

function SettingsModal({
  close,
  onSave,
}: {
  close: () => void;
  onSave: (leadDays: number) => void;
}) {
  const uiText = useTranslations();
  const [preference, setPreference] = useState<NotificationPreference | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [leadDays, setLeadDays] = useState(7);
  async function load() {
    setLoading(true); setError("");
    try { setPreference(await loadNotificationPreference()); }
    catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotLoadNotificationPreferences"))); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    void load();
    try {
      const saved = localStorage.getItem("setu-workspace-preferences");
      if (!saved) return;
      const value = JSON.parse(saved) as {
        leadDays?: number;
      };
      setLeadDays(value.leadDays ?? 7);
    } catch {
      /* Ignore invalid local demo preferences. */
    }
  }, []);
  async function save() {
    if (!preference) return;
    setSaving(true); setError("");
    try {
      setPreference(await updateNotificationPreference({ compliance_enabled: preference.compliance_enabled }));
      try { localStorage.setItem("setu-workspace-preferences", JSON.stringify({ leadDays })); }
      catch { /* Backend notification preferences remain saved when browser storage is unavailable. */ }
      onSave(leadDays);
    } catch (reason) { setError(localizedError(reason, uiText, uiText("Common.interface.couldNotSaveNotificationPreferences"))); }
    finally { setSaving(false); }
  }
  return (
    <Modal
      title={uiText("Common.interface.workspaceSettings")}
      text={uiText("Common.interface.configureYourNotificationPreferencesAndLocalInternalLeadTime")}
      close={close}
    >
      <div className="modal-content">
        {loading && <p role="status">{uiText("Common.interface.loadingNotificationPreferences")}</p>}
        {error && <p className="form-error" role="alert">{error}<button className="text-button" disabled={loading || saving} onClick={() => void load()}>{uiText("Common.actions.tryAgain")}</button></p>}
        <div className="settings-list">
          <label className="setting-row">
            <span>
              <strong>{uiText("Common.interface.complianceAndDeadlineReminders")}</strong>
              <small>{uiText("Common.interface.receiveComplianceAlertsThroughYourConfiguredNotificationChannels")}</small>
            </span>
            <input
              type="checkbox"
              disabled={loading || saving || !preference}
              checked={preference?.compliance_enabled ?? false}
              onChange={(e) => setPreference((current) => current ? { ...current, compliance_enabled: e.target.checked } : current)}
            />
          </label>
          <label className="setting-row">
            <span>
              <strong>{uiText("Common.interface.weeklyPortfolioDigest")}</strong>
              <small>{uiText("Common.interface.weeklyDigestDeliveryIsNotAvailable")}</small>
            </span>
            <input
              type="checkbox"
              checked={false}
              disabled
            />
          </label>
          <label className="setting-row stacked">
            <span>
              <strong>{uiText("Common.interface.defaultInternalLeadTime")}</strong>
              <small>{uiText("Common.interface.daysBeforeTheStatutoryDeadline")}</small>
            </span>
            <input
              type="number"
              min="1"
              max="60"
              disabled={saving}
              value={leadDays}
              onChange={(e) =>
                setLeadDays(Math.min(60, Math.max(1, Number(e.target.value))))
              }
            />
          </label>
        </div>
        <div className="form-info">
          <Settings size={17} />
           {uiText("Common.interface.notificationPreferencesAreSavedToYourAccountInternalLeadTimeIsLocalToThisBrowser")} <Link href="/account">{uiText("Common.interface.manageNotificationChannels")}</Link>
        </div>
        <div className="modal-actions">
          <button className="button secondary" disabled={saving} onClick={close}>
             {uiText("Common.actions.cancel")} </button>
          <button className="button primary" disabled={loading || saving || !preference} onClick={() => void save()}>
            {saving ? uiText("Common.actions.saving") : uiText("Common.interface.savePreferences")}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function NotificationCenter({
  items,
  close,
  onRead,
}: {
  items: Notification[];
  close: () => void;
  onRead: (id: string) => void;
}) {
  const uiText = useTranslations();
  return (
    <Modal
      title={uiText("Common.interface.notificationCentre")}
      text={`${items.filter((item) => !item.is_read).length} unread updates across your workspace.`}
      close={close}
    >
      <div className="modal-content">
        <div className="notification-center-list">
          {items.map((item) => (
            <button
              className={item.is_read ? "read" : ""}
              key={item.id}
              onClick={() => onRead(item.id)}
            >
              <span className={`notice-icon ${item.kind.toLowerCase()}`}>
                {item.kind === "WARNING" ? (
                  <AlertTriangle size={16} />
                ) : item.kind === "DOCUMENT" ? (
                  <FileText size={16} />
                ) : (
                  <ClipboardCheck size={16} />
                )}
              </span>
              <span>
                <strong><ComplianceNotificationTitle item={item} /></strong>
                <small><ComplianceNotificationMessage item={item} /></small>
                <em>{niceDate(item.created_at)}</em>
              </span>
              {!item.is_read && <i />}
            </button>
          ))}
        </div>
        <div className="modal-actions">
          <button className="button primary" onClick={close}>
             {uiText("Common.status.DONE")} </button>
        </div>
      </div>
    </Modal>
  );
}

function TaskDetailsModal({
  task,
  compliance,
  documents,
  taskUpdated,
  close,
}: {
  task: ComplianceTask;
  compliance?: Compliance;
  documents: ComplianceDocument[];
  taskUpdated: (task: ComplianceTask) => void;
  close: () => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Tasks");
  const common = useTranslations("Common");
  const [assignees, setAssignees] = useState<EligibleAssignee[]>([]);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [attachments, setAttachments] = useState<TaskAttachment[]>([]);
  const [assigneeId, setAssigneeId] = useState(task.assignee_user_id || "");
  const [taskStatus, setTaskStatus] = useState(task.status);
  const [priority, setPriority] = useState(task.priority);
  const [dueAt, setDueAt] = useState(task.due_at);
  const [comment, setComment] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      loadEligibleAssignees(task.organization_id),
      loadTaskComments(task.id),
      loadTaskAttachments(task.id),
    ]).then(([users, taskComments, taskAttachments]) => {
      setAssignees(users);
      setComments(taskComments);
      setAttachments(taskAttachments);
    }).catch(() => setError(t("loadError")));
  }, [task.id, task.organization_id, t]);

  async function save() {
    setBusy(true);
    setError("");
    try {
      const updated = await patchTask(task.id, {
        status: taskStatus,
        priority,
        due_at: dueAt,
        ...(assigneeId ? { assignee_user_id: assigneeId } : {}),
      });
      taskUpdated(updated);
    } catch (requestError) {
      setError(localizedError(requestError, uiText, t("updateError")));
    } finally {
      setBusy(false);
    }
  }

  async function submitComment(event: React.FormEvent) {
    event.preventDefault();
    if (!comment.trim()) return;
    setBusy(true);
    try {
      const row = await addTaskComment(task.id, comment.trim());
      setComments((items) => [...items, row]);
      setComment("");
    } catch (requestError) {
      setError(localizedError(requestError, uiText, t("commentError")));
    } finally {
      setBusy(false);
    }
  }

  async function attach() {
    if (!documentId) return;
    setBusy(true);
    try {
      const row = await addTaskAttachment(task.id, documentId);
      setAttachments((items) => items.some((item) => item.id === row.id) ? items : [row, ...items]);
      setDocumentId("");
    } catch (requestError) {
      setError(localizedError(requestError, uiText, t("attachmentError")));
    } finally {
      setBusy(false);
    }
  }

  async function removeAttachment(linkId: string) {
    setBusy(true);
    try {
      await archiveTaskAttachment(task.id, linkId);
      setAttachments((items) => items.filter((item) => item.id !== linkId));
    } catch (requestError) {
      setError(localizedError(requestError, uiText, t("attachmentError")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={task.title}
      text={t("details")}
      close={close}
    >
      <div className="modal-content">
        {error && <div className="form-error" role="alert"><AlertTriangle size={16}/>{error}</div>}
        <div className="detail-grid modal-detail-grid">
          <label><span>{t("status")}</span><select value={taskStatus} onChange={(event) => setTaskStatus(event.target.value)}><option value="TODO">{t("todo")}</option><option value="IN_PROGRESS">{t("inProgress")}</option><option value="DONE">{t("completed")}</option></select></label>
          <label><span>{t("priority")}</span><select value={priority} onChange={(event) => setPriority(event.target.value)}>{["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((value) => <option key={value} value={value}>{common(`priority.${value}`)}</option>)}</select></label>
          <label><span>{t("dueDate")}</span><input type="date" value={dueAt} onChange={(event) => setDueAt(event.target.value)}/></label>
          <label><span>{t("assignee")}</span><select value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}>{assignees.map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}</select></label>
          <div className="wide">
            <span>{t("linkedCompliance")}</span>
            <strong>{compliance?.title || t("standalone")}</strong>
          </div>
        </div>
        <section className="detail-section">
          <h3>{t("comments")}</h3>
          {comments.length ? <ul className="organization-records">{comments.map((row) => <li key={row.id}><strong>{row.author_name}</strong><p>{row.body}</p><small>{formatDateTime(row.created_at)}</small></li>)}</ul> : <p className="muted">{t("noComments")}</p>}
          <form className="form-row" onSubmit={(event) => void submitComment(event)}><input value={comment} maxLength={4000} placeholder={t("commentPlaceholder")} onChange={(event) => setComment(event.target.value)}/><button className="button secondary" disabled={busy || !comment.trim()}>{t("addComment")}</button></form>
        </section>
        <section className="detail-section">
          <h3>{t("attachments")}</h3>
          {attachments.length ? <ul className="organization-records">{attachments.map((row) => <li key={row.id}><span>{row.name}</span><button className="text-button" disabled={busy} onClick={() => void removeAttachment(row.id)}>{t("remove")}</button></li>)}</ul> : <p className="muted">{t("noAttachments")}</p>}
          <div className="form-row"><select aria-label={t("selectDocument")} value={documentId} onChange={(event) => setDocumentId(event.target.value)}><option value="">{t("selectDocument")}</option>{documents.filter((document) => document.storage_status === "AVAILABLE").map((document) => <option key={document.id} value={document.id}>{document.name}</option>)}</select><button className="button secondary" disabled={busy || !documentId} onClick={() => void attach()}>{t("attach")}</button></div>
        </section>
        <div className="modal-actions">
          <button className="button secondary" onClick={close}>
            {t("close")}
          </button>
          <button className="button primary" disabled={busy} onClick={() => void save()}>{busy ? t("saving") : t("save")}</button>
        </div>
      </div>
    </Modal>
  );
}

function DocumentDetailsModal({doc,organization,close,onVersion}:{doc:ComplianceDocument;organization?:Organization;close:()=>void;download:()=>void;onVersion:(document:ComplianceDocument)=>void}) {
  const t=useTranslations("Evidence");const user=useCurrentUser();
  return <Modal title={doc.name} text={t("private")} close={close}><div className="modal-content"><DocumentFileDetail doc={doc} organization={organization} canUpload={user.role!=="VIEWER"} canManage={user.role==="ADMIN"} onUpdate={onVersion}/></div></Modal>;
}

function NewTaskModal({
  organizations,
  compliances,
  currentOrg,
  close,
  onCreate,
}: {
  organizations: Organization[];
  compliances: Compliance[];
  currentOrg: string;
  close: () => void;
  onCreate: (item: ComplianceTask) => void;
}) {
  const uiText = useTranslations();
  const t = useTranslations("Tasks");
  const [title, setTitle] = useState("");
  const [org, setOrg] = useState(
    currentOrg === "all" ? organizations[0]?.id : currentOrg,
  );
  const [complianceId, setComplianceId] = useState("");
  const [dueAt, setDueAt] = useState(() => dateInput(7));
  const [priority, setPriority] = useState("MEDIUM");
  const [assignees, setAssignees] = useState<EligibleAssignee[]>([]);
  const [assigneeId, setAssigneeId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const availableCompliances = compliances.filter(
    (item) => item.organization_id === org && isOpenCompliance(item.status),
  );
  useEffect(() => {
    if (!org) return;
    loadEligibleAssignees(org).then((rows) => {
      setAssignees(rows);
      setAssigneeId((current) => rows.some((row) => row.id === current) ? current : rows[0]?.id || "");
    }).catch((requestError) => setError(localizedError(requestError, uiText, t("loadError"))));
  }, [org, t]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !org || !assigneeId || saving) return;
    setSaving(true);
    setError("");
    try {
      const item = await createTask({
        organization_id: org,
        compliance_id: complianceId || null,
        title: title.trim(),
        due_at: dueAt,
        priority,
        assignee_user_id: assigneeId,
      });
      onCreate(item);
    } catch (requestError) {
      setError(
        localizedError(requestError, uiText, t("updateError")),
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title={t("createTitle")}
      text={t("createHelp")}
      close={close}
    >
      <form onSubmit={submit} className="form">
        <label>
          <span>{t("taskTitle")}</span>
          <input
            autoFocus
            required
            minLength={3}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("taskPlaceholder")}
          />
        </label>
        <div className="form-row">
          <label>
            <span>{t("organization")}</span>
            <select
              required
              value={org}
              onChange={(e) => {
                setOrg(e.target.value);
                setComplianceId("");
              }}
            >
              {organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t("dueDate")}</span>
            <input
              type="date"
              required
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
            />
          </label>
        </div>
        <label>
          <span>{t("linkedCompliance")}</span>
          <select
            value={complianceId}
            onChange={(e) => setComplianceId(e.target.value)}
          >
            <option value="">{t("standalone")}</option>
            {availableCompliances.map((item) => (
              <option value={item.id} key={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <div className="form-row">
          <label>
            <span>{t("assignee")}</span>
            <select required value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}>
              {assignees.map((assignee) => <option key={assignee.id} value={assignee.id}>{assignee.name}</option>)}
            </select>
          </label>
          <label>
            <span>{t("priority")}</span>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="MEDIUM">{uiText("Common.priority.MEDIUM")}</option>
              <option value="HIGH">{uiText("Common.priority.HIGH")}</option>
              <option value="CRITICAL">{uiText("Common.priority.CRITICAL")}</option>
              <option value="LOW">{uiText("Common.priority.LOW")}</option>
            </select>
          </label>
        </div>
        {error && (
          <div className="form-error" role="alert">
            <AlertTriangle size={16} />
            {error}
          </div>
        )}
        <div className="form-info">
          <ShieldCheck size={17} />
          {t("auditHelp")}
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
            {t("cancel")}
          </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? t("creating") : t("create")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function NewComplianceModal({
  organizations,
  currentOrg,
  leadDays,
  close,
  onCreate,
}: {
  organizations: Organization[];
  currentOrg: string;
  leadDays: number;
  close: () => void;
  onCreate: (item: Compliance) => void;
}) {
  const uiText = useTranslations();
  const currentUser = useCurrentUser();
  const [title, setTitle] = useState("");
  const [org, setOrg] = useState(
    currentOrg === "all" ? organizations[0]?.id : currentOrg,
  );
  const [deadline, setDeadline] = useState(() => dateInput(30));
  const [category, setCategory] = useState("General");
  const [priority, setPriority] = useState("MEDIUM");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !org || saving) return;
    setSaving(true);
    setError("");
    const target = new Date(`${deadline}T12:00:00`);
    target.setDate(target.getDate() - leadDays);
    try {
      const item = await createCompliance({
        organization_id: org,
        code: `CUSTOM-${Date.now().toString().slice(-6)}`,
        title: title.trim(),
        category,
        period: "FY 2026-27",
        statutory_deadline: deadline,
        internal_target: target.toISOString().slice(0, 10),
        priority,
        owner_name: currentUser.name,
        owner_initials: initials(currentUser.name),
        legal_reference: "Internal compliance plan",
      });
      onCreate(item);
    } catch (requestError) {
      setError(
        localizedError(requestError, uiText, uiText("Common.interface.couldNotAddThisCompliance")),
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title={uiText("Compliance.add")}
      text={uiText("Common.interface.createATrackedObligationWithAClearOwnerAndDeadline")}
      close={close}
    >
      <form onSubmit={submit} className="form">
        <label>
          <span>{uiText("Common.interface.complianceTitle")}</span>
          <input
            autoFocus
            required
            minLength={3}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={uiText("Common.interface.eGAnnualActivityReport")}
          />
        </label>
        <div className="form-row">
          <label>
            <span>{uiText("Authentication.organization")}</span>
            <select
              required
              value={org}
              onChange={(e) => setOrg(e.target.value)}
            >
              {organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{uiText("ComplianceMaster.statutoryDeadline")}</span>
            <input
              type="date"
              required
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
            />
          </label>
        </div>
        <div className="form-row">
          <label>
            <span>{uiText("ComplianceMaster.category")}</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="General">{uiText("Common.interface.general")}</option>
              <option>Income Tax</option>
              <option>FCRA</option>
              <option>GST</option>
              <option value="Labour">{uiText("Common.interface.labour")}</option>
              <option value="Governance">{uiText("Common.interface.governance")}</option>
            </select>
          </label>
          <label>
            <span>{uiText("Compliance.priority")}</span>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="MEDIUM">{uiText("Common.priority.MEDIUM")}</option>
              <option value="HIGH">{uiText("Common.priority.HIGH")}</option>
              <option value="CRITICAL">{uiText("Common.priority.CRITICAL")}</option>
              <option value="LOW">{uiText("Common.priority.LOW")}</option>
            </select>
          </label>
        </div>
        <label>
          <span>{uiText("Compliance.owner")}</span>
          <input value={currentUser.name} readOnly />
        </label>
        {error && (
          <div className="form-error" role="alert">
            <AlertTriangle size={16} />
            {error}
          </div>
        )}
        <div className="form-info">
          <ShieldCheck size={17} />
           {uiText("Common.interface.thisActionWillBeRecordedInTheAuditHistoryTheInternalTargetIsSet")} {leadDays}  {uiText("Common.interface.daysEarlyLabel")} </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
             {uiText("Common.actions.cancel")} </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? uiText("Common.interface.adding") : uiText("Common.interface.addToRegister")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function UploadModal({organizations,compliances,currentOrg,initialComplianceId,close,onUpload}:{organizations:Organization[];compliances:Compliance[];currentOrg:string;initialComplianceId:string|null;close:()=>void;onUpload:(doc:ComplianceDocument)=>void}) {
 const t=useTranslations("Evidence"),user=useCurrentUser();
 return <Modal title={t("upload")} text={t("private")} close={close}><div className="modal-content"><DocumentUploadForm organizations={organizations} compliances={compliances} initialOrg={currentOrg==="all"?undefined:currentOrg} initialCompliance={initialComplianceId||undefined} onUpload={onUpload} disabled={user.role==="VIEWER"}/></div></Modal>;
}

function NewOrganizationModal({
  close,
  onCreate,
}: {
  close: () => void;
  onCreate: (result: {
    organization: Organization;
    generated_compliances: Compliance[];
  }) => void;
}) {
  const uiText = useTranslations();
  const [name, setName] = useState("");
  const [legalType, setLegalType] = useState("TRUST");
  const [registrationNumber, setRegistrationNumber] = useState("");
  const [city, setCity] = useState("");
  const [pan, setPan] = useState("");
  const [fcraActive, setFcraActive] = useState(false);
  const [generatePlan, setGeneratePlan] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      onCreate(
        await createOrganization({
          name: name.trim(),
          legal_type: legalType,
          registration_number: registrationNumber.trim(),
          city: city.trim(),
          pan: pan.trim().toUpperCase(),
          fcra_active: fcraActive,
          generate_compliance_plan: generatePlan,
        }),
      );
    } catch (requestError) {
      setError(
        localizedError(requestError, uiText, uiText("Common.interface.couldNotOnboardThisOrganization")),
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title={uiText("Common.interface.onboardOrganization")}
      text={uiText("Common.interface.createTheLegalEntityProfileAndGenerateARuleBasedCompliancePlan")}
      close={close}
    >
      <form className="form" onSubmit={submit}>
        <label>
          <span>{uiText("Authentication.organizationName")}</span>
          <input
            autoFocus
            required
            minLength={3}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={uiText("Common.interface.eGSevaCommunityFoundation")}
          />
        </label>
        <div className="form-row">
          <label>
            <span>{uiText("Common.interface.legalStructure")}</span>
            <select
              value={legalType}
              onChange={(event) => setLegalType(event.target.value)}
            >
              <option value="TRUST">{uiText("Authentication.types.TRUST")}</option>
              <option value="SOCIETY">{uiText("Authentication.types.SOCIETY")}</option>
              <option value="SECTION 8">{uiText("Authentication.types.SECTION_8")}</option>
            </select>
          </label>
          <label>
            <span>{uiText("ComplianceMaster.fields.city")}</span>
            <input
              required
              minLength={2}
              value={city}
              onChange={(event) => setCity(event.target.value)}
              placeholder="Mumbai"
            />
          </label>
        </div>
        <label>
          <span>{uiText("ComplianceMaster.fields.registration_number")}</span>
          <input
            required
            minLength={2}
            value={registrationNumber}
            onChange={(event) => setRegistrationNumber(event.target.value)}
            placeholder={uiText("Common.interface.legalRegistrationIdentifier")}
          />
        </label>
        <div className="form-row">
          <label>
            <span>{uiText("ComplianceMaster.fields.pan")}</span>
            <input
              maxLength={20}
              value={pan}
              onChange={(event) => setPan(event.target.value)}
              placeholder={uiText("Authentication.optional")}
            />
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={fcraActive}
              onChange={(event) => setFcraActive(event.target.checked)}
            />
            <span>
              <strong>{uiText("ComplianceMaster.fields.fcra_active")}</strong>
              <small>{uiText("Common.interface.includeFCRASpecificRuleCandidates")}</small>
            </span>
          </label>
        </div>
        <label className="checkbox-field full">
          <input
            type="checkbox"
            checked={generatePlan}
            onChange={(event) => setGeneratePlan(event.target.checked)}
          />
          <span>
            <strong>{uiText("Common.interface.generateInitialCompliancePlan")}</strong>
            <small>
               {uiText("Common.interface.evaluateActiveRuleVersionsAgainstThisOrganizationProfile")} </small>
          </span>
        </label>
        {error && (
          <div className="form-error" role="alert">
            <AlertTriangle size={16} />
            {error}
          </div>
        )}
        <div className="form-info">
          <ShieldCheck size={17} />
           {uiText("Common.interface.generatedDeadlinesRemainReviewableConfigurationAndMustBeValidatedBeforeProductionUse")} </div>
        <div className="modal-actions">
          <button
            className="button secondary"
            type="button"
            onClick={close}
            disabled={saving}
          >
             {uiText("Common.actions.cancel")} </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? uiText("Common.interface.onboardingProgress") : uiText("Common.interface.onboardOrganization")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function InviteMemberModal({
  organizations,
  close,
  onCreate,
}: {
  organizations: Organization[];
  close: () => void;
  onCreate: (member: Membership) => void;
}) {
  const uiText = useTranslations();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("COMPLIANCE_OFFICER");
  const [organizationId, setOrganizationId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [attempted, setAttempted] = useState(false);
  const emailError = validateEmail(email);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    setAttempted(true);
    if (emailError) {
      setError(uiText(email.trim() ? "Authentication.validation.email" : "Authentication.validation.required"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      onCreate(
        await inviteMember({
          name: name.trim(),
          email: normalizeEmail(email),
          role,
          organization_id: organizationId || null,
        }),
      );
    } catch (requestError) {
      setError(
        localizedError(requestError, uiText, uiText("Common.interface.couldNotCreateThisInvitation")),
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title={uiText("Common.interface.addResponsibility")}
      text={uiText("Common.interface.grantARoleAtTenantOrOrganizationScope")}
      close={close}
    >
      <form className="form" onSubmit={submit} noValidate>
        <div className="form-row">
          <label>
            <span>{uiText("Auth.fullName")}</span>
            <input
              autoFocus
              required
              minLength={2}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            <span>{uiText("Integrations.categories.EMAIL")}</span>
            <input
              type="email"
              inputMode="email"
              autoCapitalize="none"
              spellCheck={false}
              required
              maxLength={200}
              value={email}
              aria-invalid={attempted && Boolean(emailError)}
              aria-describedby={
                attempted && emailError
                  ? "responsibility-email-error"
                  : undefined
              }
              onChange={(event) => setEmail(event.target.value)}
            />
            {attempted && emailError && (
              <small className="field-error" id="responsibility-email-error">
                {uiText(email.trim() ? "Authentication.validation.email" : "Authentication.validation.required")}
              </small>
            )}
          </label>
        </div>
        <label>
          <span>{uiText("Common.interface.role")}</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            <option value="TENANT_ADMIN">{uiText("Common.interface.tenantAdmin")}</option>
            <option value="ORGANIZATION_ADMIN">{uiText("Common.interface.organizationAdmin")}</option>
            <option value="COMPLIANCE_OFFICER">{uiText("ComplianceMaster.roles.COMPLIANCE_OFFICER")}</option>
            <option value="ACCOUNTANT">{uiText("ComplianceMaster.roles.ACCOUNTANT")}</option>
            <option value="AUDITOR">{uiText("ComplianceMaster.roles.AUDITOR")}</option>
            <option value="CONSULTANT">{uiText("ComplianceMaster.roles.CONSULTANT")}</option>
            <option value="MANAGEMENT">{uiText("ComplianceMaster.roles.MANAGEMENT")}</option>
            <option value="VIEWER">{uiText("ComplianceMaster.roles.VIEWER")}</option>
          </select>
        </label>
        <label>
          <span>{uiText("Integrations.organizationScope")}</span>
          <select
            value={organizationId}
            onChange={(event) => setOrganizationId(event.target.value)}
          >
            <option value="">{uiText("Common.interface.allOrganizationsInTenant")}</option>
            {organizations.map((organization) => (
              <option key={organization.id} value={organization.id}>
                {organization.name}
              </option>
            ))}
          </select>
        </label>
        {error && (
          <div className="form-error" role="alert">
            <AlertTriangle size={16} />
            {error}
          </div>
        )}
        <div className="form-info">
          <ShieldCheck size={17} />
           {uiText("Common.interface.theInvitationRoleAndScopeAreAuditLoggedAccessIsDeniedOutsideTheSelectedScope")} </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
             {uiText("Common.actions.cancel")} </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? uiText("Common.interface.creating") : uiText("Common.interface.createInvitation")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const impactRecordTypes = [
  "GRANT",
  "DONOR",
  "CSR_PROJECT",
  "VOLUNTEER",
] as const;
type ImpactRecordType = (typeof impactRecordTypes)[number];
const programmeLabels: Partial<Record<PortfolioRecord["record_type"], string>> =
  {
    GRANT: "Common.interface.grants",
    DONOR: "Common.interface.donors",
    CSR_PROJECT: "Common.interface.cSRProjects",
    VOLUNTEER: "Common.interface.volunteers",
  };
function isImpactRecord(
  item: PortfolioRecord,
): item is PortfolioRecord & { record_type: ImpactRecordType } {
  return impactRecordTypes.includes(item.record_type as ImpactRecordType);
}

function ProgrammesView({
  items,
  organizations,
  currentOrg,
  readOnly,
  onCreate,
  onUpdate, onDelete, onRefresh,
}: {
  items: PortfolioRecord[];
  organizations: Organization[];
  currentOrg: string;
  readOnly: boolean;
  onCreate: (item: PortfolioRecord) => void;
  onUpdate: (item: PortfolioRecord) => void;
  onDelete: (id:string) => void;
  onRefresh: () => Promise<void>;
}) {
  const uiText = useTranslations();
  const [tab, setTab] = useState<"ALL" | PortfolioRecord["record_type"]>("ALL");
  const [showNewRecord, setShowNewRecord] = useState(false);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [query,setQuery]=useState(""),[statusFilter,setStatusFilter]=useState("");
  const [refreshing,setRefreshing]=useState(false),[refreshError,setRefreshError]=useState("");
  const selectedRecord=items.find(item=>item.id===selectedId);
  const impactItems = items.filter(isImpactRecord);
  const visible = impactItems.filter(
    (item) => (tab === "ALL" || item.record_type === tab) && (!statusFilter||item.status===statusFilter) &&
      `${item.title} ${item.owner_name} ${item.value_label} ${item.notes} ${item.status}`.toLowerCase().includes(query.trim().toLowerCase()),
  );
  return (
    <>
      <div className="page">
        <PageHeading
          eyebrow={uiText("Common.interface.expansionModules")}
          title={uiText("Common.interface.impactPortfolio")}
          text={uiText("Common.interface.trackGrantDonorAndVolunteerRecordsAlongsideComplianceManageCSRWorkflowsInCSRPartners")}
          action={
            !readOnly && (
              <button
                className="button primary"
                onClick={() => setShowNewRecord(true)}
              >
                <Plus size={17} />
                 {uiText("Common.interface.addRecord")} </button>
            )
          }
        />
        <p className="notice info">{uiText("Common.interface.theseAreOperationalRecordsNotAccountingPaymentsOrAttendanceSystemsOwnerAndValueFieldsAreDescriptiveText")} <Link href="/dashboard?view=csr">{uiText("Common.interface.manageCSRInCSRPartners")}</Link>{uiText("Common.interface.existingGenericCSRRecordsAreRetainedForReferenceOnly")}</p>
        <div className="toolbar"><label className="search-box"><Search size={16}/><input aria-label={uiText("Common.interface.searchImpactRecords")} value={query} onChange={event=>setQuery(event.target.value)} placeholder={uiText("Common.interface.searchImpactRecordsLabel")}/></label><label>{uiText("Common.interface.statusFilter")}<select aria-label={uiText("Common.interface.impactStatusFilter")} value={statusFilter} onChange={event=>setStatusFilter(event.target.value)}><option value="">{uiText("Reports.allStatuses")}</option>{Array.from(new Set(impactItems.map(item=>item.status))).sort().map(status=><option key={status} value={status}>{localizedStatus(status, uiText)}</option>)}</select></label><button className="button secondary" disabled={refreshing} onClick={async()=>{setRefreshing(true);setRefreshError("");try{await onRefresh();}catch(reason){setRefreshError(localizedError(reason, uiText, uiText("Common.interface.couldNotRefreshRecords")));}finally{setRefreshing(false);}}}>{uiText("Common.interface.refreshRecords")}</button></div>
        {refreshing&&<p role="status">{uiText("Common.interface.loadingRecords")}</p>}{refreshError&&<p className="form-error" role="alert">{refreshError}</p>}
        <div className="module-metrics">
          {(
            Object.keys(programmeLabels) as PortfolioRecord["record_type"][]
          ).map((type) => (
            <button
              key={type}
              onClick={() => setTab(type)}
              className={tab === type ? "active" : ""}
            >
              <strong>
                {items.filter((item) => item.record_type === type).length}
              </strong>
              <span>{uiText(programmeLabels[type]!)}</span>
            </button>
          ))}
        </div>
        <div className="toolbar">
          <div className="filter-tabs">
            <button
              className={tab === "ALL" ? "active" : ""}
              onClick={() => setTab("ALL")}
            >
               {uiText("ComplianceMaster.all")} </button>
            {(
              Object.keys(programmeLabels) as PortfolioRecord["record_type"][]
            ).map((type) => (
              <button
                key={type}
                className={tab === type ? "active" : ""}
                onClick={() => setTab(type)}
              >
                {uiText(programmeLabels[type]!)}
              </button>
            ))}
          </div>
        </div>
        <section className="table-card">
          <div className="impact-list">
            {visible.map((item) => (
              <article key={item.id}>
                <i>
                  <HandHeart size={19} />
                </i>
                <div>
                  <span>{uiText(programmeLabels[item.record_type]!)}</span>
                  <h3>{item.title}</h3>
                  <p>{item.notes || uiText("Common.interface.noNotesRecorded")}</p>
                </div>
                <div>
                  <StatusBadge status={item.status} />
                  <strong>{item.value_label || "—"}</strong>
                  <small>
                    {
                      organizations.find(
                        (org) => org.id === item.organization_id,
                      )?.name
                    }
                  </small>
                </div>
                <div>
                  <strong>{item.owner_name}</strong>
                  <small>
                    {item.due_at
                      ? uiText("Common.interface.dueNamed", { date: niceDate(item.due_at) })
                      : uiText("Common.interface.noDueDate")}
                  </small>
                  <button className="button secondary" onClick={()=>setSelectedId(item.id)} aria-label={uiText("Common.interface.viewNamed", { name: item.title })}>{uiText("Common.interface.viewRecord")}</button>
                </div>
              </article>
            ))}
          </div>
          {!visible.length && (
            <EmptyState
              icon={<HandHeart />}
              title={uiText("Common.interface.noRecordsInThisModule")}
              text={uiText("Common.interface.addARecordToBeginManagingThisImpactPortfolio")}
            />
          )}
        </section>
      </div>
      {showNewRecord && (
        <NewPortfolioRecordModal
          organizations={organizations}
          currentOrg={currentOrg}
          close={() => setShowNewRecord(false)}
          onCreate={(item) => {
            onCreate(item);
            setShowNewRecord(false);
          }}
        />
      )}
      {selectedRecord&&<PortfolioRecordDetail item={selectedRecord} organizations={organizations} readOnly={readOnly||selectedRecord.record_type==="CSR_PROJECT"} close={()=>setSelectedId(null)} onUpdate={onUpdate} onDelete={onDelete}/>}
    </>
  );
}

function NewPortfolioRecordModal({
  organizations,
  currentOrg,
  close,
  onCreate,
}: {
  organizations: Organization[];
  currentOrg: string;
  close: () => void;
  onCreate: (item: PortfolioRecord) => void;
}) {
  const uiText = useTranslations();
  const currentUser = useCurrentUser();
  const [recordType, setRecordType] =
    useState<PortfolioRecord["record_type"]>("GRANT");
  const [organizationId, setOrganizationId] = useState(
    currentOrg === "all" ? organizations[0]?.id || "" : currentOrg,
  );
  const [title, setTitle] = useState("");
  const [valueLabel, setValueLabel] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [notes, setNotes] = useState("");
  const [ownerName,setOwnerName]=useState(currentUser.name),[status,setStatus]=useState("ACTIVE");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      onCreate(
        await createPortfolioRecord({
          organization_id: organizationId,
          record_type: recordType,
          title,
          status,
          owner_name: ownerName.trim(),
          value_label: valueLabel,
          due_at: dueAt || null,
          notes,
        }),
      );
    } catch (reason) {
      setError(
        localizedError(reason, uiText, uiText("Common.interface.couldNotCreateRecord")),
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal
      title={uiText("Common.interface.addImpactRecord")}
      text={uiText("Common.interface.createATenantScopedGrantDonorOrVolunteerTrackingRecordCSRIsManagedInCSRPartners")}
      close={close}
    >
      <form className="form" onSubmit={submit}>
        <div className="form-row">
          <label>
            <span>{uiText("Settings.module")}</span>
            <select
              value={recordType}
              onChange={(event) =>
                setRecordType(
                  event.target.value as PortfolioRecord["record_type"],
                )
              }
            >
              {(
                Object.keys(programmeLabels).filter(type=>type!=="CSR_PROJECT") as PortfolioRecord["record_type"][]
              ).map((type) => (
                <option value={type} key={type}>
                  {uiText(programmeLabels[type]!)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{uiText("Authentication.organization")}</span>
            <select
              required
              value={organizationId}
              onChange={(event) => setOrganizationId(event.target.value)}
            >
              {organizations.map((org) => (
                <option value={org.id} key={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          <span>{uiText("Common.interface.recordTitle")}</span>
          <input
            autoFocus
            required
            minLength={2}
            maxLength={220}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={uiText("Common.interface.programmeRelationshipOrEngagementName")}
          />
        </label>
        <div className="form-row">
          <label><span>{uiText("Common.interface.responsiblePersonContact")}</span><input required minLength={2} maxLength={120} value={ownerName} onChange={event=>setOwnerName(event.target.value)}/></label>
          <label><span>{uiText("Common.interface.recordedStatus")}</span><input required minLength={2} maxLength={30} value={status} onChange={event=>setStatus(event.target.value)}/></label>
        </div>
        <div className="form-row">
          <label>
            <span>{uiText("Common.interface.valueOrScale")}</span>
            <input
              maxLength={80}
              value={valueLabel}
              onChange={(event) => setValueLabel(event.target.value)}
              placeholder={uiText("Common.interface.eGINR10LakhOr20Volunteers")}
            />
          </label>
          <label>
            <span>{uiText("Common.interface.milestoneDate")}</span>
            <input
              type="date"
              value={dueAt}
              onChange={(event) => setDueAt(event.target.value)}
            />
          </label>
        </div>
        <label>
          <span>{uiText("Common.interface.notes")}</span>
          <textarea
            maxLength={2000}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder={uiText("Common.interface.objectivesReportingNeedsStewardshipOrDeliveryNotes")}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={close}>
             {uiText("Common.actions.cancel")} </button>
          <button className="button primary" disabled={saving}>
            {saving ? uiText("Common.actions.saving") : uiText("Common.interface.addRecord")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function PortfolioRecordDetail({item,organizations,readOnly,close,onUpdate,onDelete}:{item:PortfolioRecord;organizations:Organization[];readOnly:boolean;close:()=>void;onUpdate:(item:PortfolioRecord)=>void;onDelete:(id:string)=>void}) {
  const uiText = useTranslations();
  const [editing,setEditing]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState("");
  const [title,setTitle]=useState(item.title),[owner,setOwner]=useState(item.owner_name),[status,setStatus]=useState(item.status),[value,setValue]=useState(item.value_label),[due,setDue]=useState(item.due_at||""),[notes,setNotes]=useState(item.notes);
  async function save(event:React.FormEvent){
    event.preventDefault();if(saving||readOnly||!item.can_edit) return;setSaving(true);setError("");
    try{onUpdate(await patchPortfolioRecord(item.id,{title:title.trim(),owner_name:owner.trim(),status:status.trim(),value_label:value.trim(),due_at:due||null,notes:notes.trim()}));close();}
    catch(reason){setError(localizedError(reason, uiText, uiText("Common.interface.couldNotUpdateRecord")));}
    finally{setSaving(false);}
  }
  async function remove(){
    if(saving||readOnly||!item.can_delete||!window.confirm(uiText("Common.interface.deleteRecordConfirm", { title: item.title }))) return;setSaving(true);setError("");
    try{await deletePortfolioRecord(item.id);onDelete(item.id);close();}catch(reason){setError(localizedError(reason, uiText, uiText("Common.interface.couldNotDeleteRecord")));}finally{setSaving(false);}
  }
  return <Modal title={editing?uiText("Common.interface.editOperationalRecord"):uiText("Common.interface.recordDetails")} text={uiText("Common.interface.recordTrackingOnlyStatusChangesDoNotSettleFundsDeliverMessagesPublishContentOrGenerateDocuments")} close={()=>{if(!saving) close();}}>
    <p>{uiText("Common.interface.organization")} {organizations.find(org=>org.id===item.organization_id)?.name||uiText("Common.interface.organization")}  {uiText("Common.interface.type")} {item.record_type}</p>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {editing?<form className="form" onSubmit={save}>
      <label>{uiText("Common.interface.recordTitle")}<input required minLength={2} maxLength={220} value={title} onChange={event=>setTitle(event.target.value)}/></label>
      <label>{uiText("Common.interface.responsiblePersonContact")}<input required minLength={2} maxLength={120} value={owner} onChange={event=>setOwner(event.target.value)}/></label>
      <label>{uiText("Common.interface.recordedStatus")}<input required minLength={2} maxLength={30} value={status} onChange={event=>setStatus(event.target.value)}/></label>
      <label>{uiText("Common.interface.valueReference")}<input maxLength={80} value={value} onChange={event=>setValue(event.target.value)}/></label>
      <label>{uiText("GlobalSearch.dateSort")}<input type="date" value={due} onChange={event=>setDue(event.target.value)}/></label>
      <label>{uiText("Common.interface.notes")}<textarea maxLength={2000} value={notes} onChange={event=>setNotes(event.target.value)}/></label>
      <div className="modal-actions"><button type="button" className="button secondary" disabled={saving} onClick={()=>setEditing(false)}>{uiText("Common.interface.cancelEdit")}</button><button className="button primary" disabled={saving}>{saving?uiText("Common.actions.saving"):uiText("Common.interface.saveRecord")}</button></div>
    </form>:<><h3>{item.title}</h3><p>{uiText("Common.interface.status")} {item.status}</p><p>{uiText("Common.interface.ownerContact")} {item.owner_name}</p><p>{uiText("Common.interface.valueReferenceLabel")} {item.value_label||uiText("Common.interface.notRecorded")}</p><p>{uiText("Common.interface.date")} {item.due_at?niceDate(item.due_at):uiText("Common.interface.notRecorded")}</p><p>{item.notes||uiText("Common.interface.noNotesRecorded")}</p><p>{uiText("Common.interface.created")} {formatDateTime(item.created_at)}  {uiText("Common.interface.updated")} {formatDateTime(item.updated_at)}</p><div className="modal-actions">{!readOnly&&item.can_edit&&<button className="button primary" onClick={()=>setEditing(true)}>{uiText("Common.interface.editRecord")}</button>}{!readOnly&&item.can_delete&&<button className="button secondary" disabled={saving} onClick={()=>void remove()}>{uiText("Common.interface.deleteRecord")}</button>}</div></>}
  </Modal>;
}

const operationGroups = [
  "People",
  "Fundraising",
  "Engagement",
  "Publishing",
] as const;
type OperationGroup = (typeof operationGroups)[number];
const operationModules = [
  "MEMBERSHIP",
  "VOLUNTEER",
  "VOLUNTEER_ACTIVITY",
  "MANAGEMENT_MEMBER",
  "CSR_PROJECT",
  "DONATION",
  "CAMPAIGN",
  "SPONSOR",
  "EVENT",
  "MESSAGE",
  "INQUIRY",
  "CERTIFICATE",
  "DOCUMENT_TEMPLATE",
  "NEWS",
  "GALLERY_ITEM",
  "TESTIMONIAL",
  "TRAINING_VIDEO",
  "CONTENT_PAGE",
] as const;
type OperationalRecordType = (typeof operationModules)[number];
type OperationMeta = {
  label: string;
  singular: string;
  group: OperationGroup;
  description: string;
  defaultStatus: string;
  statuses: string[];
  valueLabel: string;
  dateLabel: string;
};
const operationMeta: Record<OperationalRecordType, OperationMeta> = {
  MEMBERSHIP: {
    label: "Common.interface.memberships",
    singular: "membership",
    group: "People",
    description: "Common.interface.applicationFeeReferenceAndValidityRecords",
    defaultStatus: "PENDING",
    statuses: ["PENDING", "VERIFIED", "BLOCKED", "EXPIRED"],
    valueLabel: "Common.interface.feeTransaction",
    dateLabel: "Common.interface.validUntil",
  },
  VOLUNTEER: {
    label: "Common.interface.volunteers",
    singular: "volunteer",
    group: "People",
    description: "Common.interface.applicationsApprovalsAndValidity",
    defaultStatus: "PENDING",
    statuses: ["PENDING", "ACTIVE", "APPROVED", "REJECTED", "EXPIRED"],
    valueLabel: "Common.interface.locationID",
    dateLabel: "Common.interface.validUntil",
  },
  VOLUNTEER_ACTIVITY: {
    label: "Common.interface.volunteerActivities",
    singular: "activity",
    group: "People",
    description: "Common.interface.activityHoursAndEventReferencesNoAttendanceSystem",
    defaultStatus: "LOGGED",
    statuses: ["LOGGED", "APPROVED", "REJECTED"],
    valueLabel: "Common.interface.hoursEvent",
    dateLabel: "Common.interface.activityDate",
  },
  MANAGEMENT_MEMBER: {
    label: "Common.interface.managementBody",
    singular: "management member",
    group: "People",
    description: "Common.interface.boardMemberDepartmentAndRoleReferenceRecords",
    defaultStatus: "ACTIVE",
    statuses: ["ACTIVE", "INACTIVE"],
    valueLabel: "Common.interface.roleDepartment",
    dateLabel: "Common.interface.termEnd",
  },
  CSR_PROJECT: {
    label: "Common.interface.projectsFunds",
    singular: "project",
    group: "Fundraising",
    description: "Common.interface.legacyProjectReferencesManageCSRInCSRPartners",
    defaultStatus: "ACTIVE",
    statuses: ["DRAFT", "ACTIVE", "ON_TRACK", "COMPLETED", "ON_HOLD"],
    valueLabel: "Common.interface.targetRaised",
    dateLabel: "Common.interface.endDate",
  },
  DONATION: {
    label: "Common.interface.donations",
    singular: "donation",
    group: "Fundraising",
    description: "Common.interface.donorAmountAndTransactionReferenceRecords",
    defaultStatus: "PENDING",
    statuses: ["PENDING", "VERIFIED", "APPROVED", "REJECTED"],
    valueLabel: "Common.interface.amountTransaction",
    dateLabel: "Common.interface.donationDate",
  },
  CAMPAIGN: {
    label: "Common.interface.crowdfunding",
    singular: "campaign",
    group: "Fundraising",
    description: "Common.interface.campaignGoalAndProgressReferencesRecordOnly",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "ACTIVE", "CLOSED"],
    valueLabel: "Common.interface.goalRaised",
    dateLabel: "Common.interface.closingDate",
  },
  SPONSOR: {
    label: "Common.interface.sponsors",
    singular: "sponsor",
    group: "Fundraising",
    description: "Common.interface.sponsorIdentityWebsiteAndPriority",
    defaultStatus: "ACTIVE",
    statuses: ["ACTIVE", "INACTIVE"],
    valueLabel: "Common.interface.websitePriority",
    dateLabel: "Common.interface.reviewDate",
  },
  EVENT: {
    label: "Common.interface.events",
    singular: "event",
    group: "Engagement",
    description: "Common.interface.dateLocationAndCapacityReferencesNoRegistrationSystem",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "COMPLETED", "CANCELLED"],
    valueLabel: "Common.interface.locationCapacity",
    dateLabel: "Common.interface.eventDate",
  },
  MESSAGE: {
    label: "Common.interface.messages",
    singular: "message",
    group: "Engagement",
    description: "Common.interface.messageAndAudienceReferencesNoMessageDelivery",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "SENT", "FAILED"],
    valueLabel: "Common.interface.audienceChannel",
    dateLabel: "Common.interface.sendDate",
  },
  INQUIRY: {
    label: "Common.interface.inquiries",
    singular: "inquiry",
    group: "Engagement",
    description: "Common.interface.categoryUrgencyStatusAndAdminNotes",
    defaultStatus: "OPEN",
    statuses: ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"],
    valueLabel: "Common.interface.categoryUrgency",
    dateLabel: "Common.interface.followUpDate",
  },
  CERTIFICATE: {
    label: "Common.interface.certificates",
    singular: "certificate",
    group: "Publishing",
    description: "Common.interface.certificateReferencesNoGenerationOrEmailDelivery",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "ISSUED", "EMAILED", "REVOKED"],
    valueLabel: "Common.interface.recipientNumber",
    dateLabel: "Common.interface.issueDate",
  },
  DOCUMENT_TEMPLATE: {
    label: "Common.interface.documentTemplates",
    singular: "template",
    group: "Publishing",
    description: "Common.interface.templateDescriptionsNoDocumentGeneration",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Common.interface.brandDocumentType",
    dateLabel: "Common.interface.reviewDate",
  },
  NEWS: {
    label: "Common.interface.newsUpdates",
    singular: "article",
    group: "Publishing",
    description: "Common.interface.announcementRecordsNoPublicPublishing",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Common.interface.slugCategory",
    dateLabel: "Common.interface.publishDate",
  },
  GALLERY_ITEM: {
    label: "Common.interface.gallery",
    singular: "gallery item",
    group: "Publishing",
    description: "Common.interface.imageAndVideoReferencesNoPublicPublishing",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Common.interface.imageVideo",
    dateLabel: "Common.interface.publishDate",
  },
  TESTIMONIAL: {
    label: "Common.interface.testimonials",
    singular: "testimonial",
    group: "Publishing",
    description: "Common.interface.reviewContentStarsAndDisplayPriority",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "INACTIVE"],
    valueLabel: "Common.interface.roleStars",
    dateLabel: "Common.interface.publishDate",
  },
  TRAINING_VIDEO: {
    label: "Common.interface.training",
    singular: "training video",
    group: "Publishing",
    description: "Common.interface.memberTrainingVideosAndResources",
    defaultStatus: "ACTIVE",
    statuses: ["ACTIVE", "INACTIVE"],
    valueLabel: "Common.interface.videoURLCategory",
    dateLabel: "Common.interface.reviewDate",
  },
  CONTENT_PAGE: {
    label: "Common.interface.websiteContent",
    singular: "content page",
    group: "Publishing",
    description: "Common.interface.aboutObjectivesLegalContactAndSliderContent",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Common.interface.pageSection",
    dateLabel: "Common.interface.publishDate",
  },
};
function isOperationalRecord(
  item: PortfolioRecord,
): item is PortfolioRecord & { record_type: OperationalRecordType } {
  return operationModules.includes(item.record_type as OperationalRecordType);
}

function OperationsView({
  items,
  organizations,
  currentOrg,
  onCreate,
  onUpdate,
  onDelete,
  onRefresh,
}: {
  items: PortfolioRecord[];
  organizations: Organization[];
  currentOrg: string;
  onCreate: (item: PortfolioRecord) => void;
  onUpdate: (item: PortfolioRecord) => void;
  onDelete: (id: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const uiText = useTranslations();
  const [group, setGroup] = useState<OperationGroup>("People");
  const [module, setModule] = useState<OperationalRecordType | "ALL">("ALL");
  const [query, setQuery] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [selectedId,setSelectedId]=useState<string|null>(null),[statusFilter,setStatusFilter]=useState("");
  const selectedRecord=items.find(item=>item.id===selectedId);
  const operationalItems = items.filter(isOperationalRecord);
  const groupModules = operationModules.filter(
    (type) => operationMeta[type].group === group,
  );
  const visible = operationalItems.filter(
    (item) =>
      operationMeta[item.record_type].group === group &&
      (module === "ALL" || item.record_type === module) &&
      (!statusFilter||item.status===statusFilter) &&
      `${item.title} ${item.owner_name} ${item.notes} ${item.value_label}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  async function changeStatus(
    item: PortfolioRecord & { record_type: OperationalRecordType },
    nextStatus: string,
  ) {
    setWorking(item.id);
    setError("");
    try {
      onUpdate(await patchPortfolioRecord(item.id, { status: nextStatus }));
    } catch (reason) {
      setError(
        localizedError(reason, uiText, uiText("Common.interface.couldNotUpdateRecord")),
      );
    } finally {
      setWorking("");
    }
  }
  async function remove(item: PortfolioRecord) {
    if (!window.confirm(uiText("Common.interface.deleteRecordConfirm", { title: item.title })))
      return;
    setWorking(item.id);
    setError("");
    try {
      await deletePortfolioRecord(item.id);
      onDelete(item.id);
    } catch (reason) {
      setError(
        localizedError(reason, uiText, uiText("Common.interface.couldNotDeleteRecord")),
      );
    } finally {
      setWorking("");
    }
  }
  return (
    <>
      <div className="page operations-page">
        <PageHeading
          eyebrow={uiText("Common.interface.referencePortalParity")}
          title={uiText("Common.interface.nGOOperationsCentre")}
          text={uiText("Common.interface.trackMembershipFundraisingEngagementAndContentRecordsInYourOrganizationScopedWorkspace")}
          action={
            <button className="button primary" disabled={module==="CSR_PROJECT"} onClick={() => setShowNew(true)}>
              <Plus size={17} />
               {uiText("Common.interface.addOperationalRecord")} </button>
          }
        />
        <p className="notice info">{uiText("Common.interface.statusesAreRecordedLabelsNotEnforcedApprovalsSENTPUBLISHEDISSUEDAndVERIFIEDDoNotSendMessagesPublishContentGenerateCertificatesOrSettleFundsTheseRecordsAreNotAnAccountingOrAttendanceSystem")} <Link href="/dashboard?view=csr">{uiText("Common.interface.manageCSRInCSRPartners")}</Link>{uiText("Common.interface.genericCSRRecordsAreReferenceOnly")}</p>
        <div className="operations-hero">
          <div>
            <span>
              <Sparkles size={14} />
               {uiText("Common.interface.unifiedControlRoom")} </span>
            <h2>{uiText("Common.interface.fromFirstInquiryToVerifiedImpact")}</h2>
            <p>
               {uiText("Common.interface.everyOperationalRecordBelongsToAnOrganizationSupportsAReviewStatusAndIsIncludedInTheAuditTrail")} </p>
          </div>
          <div>
            <strong>{operationalItems.length}</strong>
            <span>{uiText("Common.interface.operationalRecords")}</span>
          </div>
        </div>
        <div className="operation-groups">
          {operationGroups.map((item) => (
            <button
              key={item}
              className={group === item ? "active" : ""}
              onClick={() => {
                setGroup(item);
                setModule("ALL");
              }}
            >
              {item === "People" ? (
                <Users />
              ) : item === "Fundraising" ? (
                <Banknote />
              ) : item === "Engagement" ? (
                <Mail />
              ) : (
                <Newspaper />
              )}
              <span>{uiText(`Common.interface.${item.toLowerCase()}`)}</span>
              <strong>
                {
                  operationalItems.filter(
                    (record) =>
                      operationMeta[record.record_type].group === item,
                  ).length
                }
              </strong>
            </button>
          ))}
        </div>
        <div className="operation-module-grid">
          {groupModules.map((type) => (
            <button
              key={type}
              className={module === type ? "active" : ""}
              onClick={() => setModule(module === type ? "ALL" : type)}
            >
              <i>
                {type === "DONATION" ? (
                  <Banknote />
                ) : type === "EVENT" ? (
                  <CalendarCheck />
                ) : type === "CERTIFICATE" ? (
                  <BadgeCheck />
                ) : (
                  <Megaphone />
                )}
              </i>
              <span>
                <strong>{uiText(operationMeta[type].label)}</strong>
                <small>{uiText(operationMeta[type].description)}</small>
              </span>
              <b>
                {
                  operationalItems.filter((item) => item.record_type === type)
                    .length
                }
              </b>
            </button>
          ))}
        </div>
        <div className="toolbar">
          <label className="search-box">
            <Search size={16} />
            <input
              aria-label={uiText("Common.interface.searchOperationalRecords")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={uiText("Common.interface.searchGroup", { group: uiText("Common.interface."+group.toLowerCase()) })}
            />
          </label>
          <label>{uiText("Common.interface.statusFilter")}<select aria-label={uiText("Common.interface.operationsStatusFilter")} value={statusFilter} onChange={event=>setStatusFilter(event.target.value)}><option value="">{uiText("Reports.allStatuses")}</option>{Array.from(new Set(operationalItems.map(item=>item.status))).sort().map(status=><option key={status} value={status}>{localizedStatus(status, uiText)}</option>)}</select></label>
          <button className="button secondary" disabled={!!working} onClick={async()=>{setWorking("refresh");setError("");try{await onRefresh();}catch(reason){setError(localizedError(reason, uiText, uiText("Common.interface.couldNotRefreshRecords")));}finally{setWorking("");}}}>{uiText("Common.interface.refreshRecords")}</button>
          <div className="filter-tabs">
            <button
              className={module === "ALL" ? "active" : ""}
              onClick={() => setModule("ALL")}
            >
               {uiText("ComplianceMaster.all")} {group}
            </button>
            {groupModules.map((type) => (
              <button
                key={type}
                className={module === type ? "active" : ""}
                onClick={() => setModule(type)}
              >
                {uiText(operationMeta[type].label)}
              </button>
            ))}
          </div>
        </div>
        {error && (
          <div className="form-error" role="alert">
            <AlertTriangle size={16} />
            {error}
          </div>
        )}
        {working==="refresh"&&<p role="status">{uiText("Common.interface.loadingRecords")}</p>}
        <section className="table-card operations-table">
          <div className="table-head">
            <span>{uiText("Common.interface.record")}</span>
            <span>{uiText("Authentication.organization")}</span>
            <span>{uiText("Common.interface.valueReference")}</span>
            <span>{uiText("GlobalSearch.dateSort")}</span>
            <span>{uiText("ComplianceMaster.status")}</span>
            <span>{uiText("ComplianceMaster.actions")}</span>
          </div>
          {visible.map((item) => (
            <div className="table-row" key={item.id}>
              <span>
                <small>{uiText(operationMeta[item.record_type].label)}</small>
                <strong>{item.title}</strong>
                <em>{item.notes || uiText("Common.interface.noNotesRecorded")}</em>
              </span>
              <span>
                <strong>
                  {organizations.find(
                    (organization) => organization.id === item.organization_id,
                  )?.name || uiText("Common.interface.organization")}
                </strong>
                <small>{item.owner_name}</small>
              </span>
              <span>
                <strong>{item.value_label || "—"}</strong>
                <small>{uiText(operationMeta[item.record_type].valueLabel)}</small>
              </span>
              <span>
                <strong>{item.due_at ? niceDate(item.due_at) : "—"}</strong>
                <small>{uiText(operationMeta[item.record_type].dateLabel)}</small>
              </span>
              <span>
                <select
                  aria-label={uiText("Common.interface.statusNamed", { name: item.title })}
                  value={item.status}
                  disabled={!!working||!item.can_edit||item.record_type==="CSR_PROJECT"}
                  onChange={(event) =>
                    void changeStatus(item, event.target.value)
                  }
                >
                  {Array.from(new Set([item.status,...operationMeta[item.record_type].statuses])).map((status) => (
                    <option key={status} value={status}>{localizedStatus(status, uiText)}</option>
                  ))}
                </select>
              </span>
              <span>
                <button className="button secondary" aria-label={uiText("Common.interface.viewNamed", { name: item.title })} onClick={()=>setSelectedId(item.id)}>{uiText("ComplianceMaster.view")}</button>
                {item.can_delete&&item.record_type!=="CSR_PROJECT"&&
                <button
                  className="icon-button plain danger"
                  aria-label={uiText("Common.interface.deleteNamed", { name: item.title })}
                  disabled={!!working}
                  onClick={() => void remove(item)}
                >
                  <Trash2 size={16} />
                </button>}
              </span>
            </div>
          ))}
          {!visible.length && (
            <EmptyState
              icon={<Megaphone />}
              title={uiText("Common.interface.emptyRecords", { module: module === "ALL" ? uiText(`Common.interface.${group.toLowerCase()}`) : uiText(operationMeta[module].label) })}
              text={uiText("Common.interface.addTheFirstOperationalRecordItWillBeStoredSecurelyUnderTheSelectedOrganization")}
            />
          )}
        </section>
      </div>
      {showNew && (
        <NewOperationModal
          organizations={organizations}
          currentOrg={currentOrg}
          initialType={module === "ALL" ? groupModules.find(type=>type!=="CSR_PROJECT")! : module}
          close={() => setShowNew(false)}
          onCreate={(item) => {
            onCreate(item);
            setShowNew(false);
            setGroup(
              operationMeta[item.record_type as OperationalRecordType].group,
            );
            setModule(item.record_type as OperationalRecordType);
          }}
        />
      )}
      {selectedRecord&&<PortfolioRecordDetail item={selectedRecord} organizations={organizations} readOnly={selectedRecord.record_type==="CSR_PROJECT"} close={()=>setSelectedId(null)} onUpdate={onUpdate} onDelete={onDelete}/>}
    </>
  );
}

function NewOperationModal({
  organizations,
  currentOrg,
  initialType,
  close,
  onCreate,
}: {
  organizations: Organization[];
  currentOrg: string;
  initialType: OperationalRecordType;
  close: () => void;
  onCreate: (item: PortfolioRecord) => void;
}) {
  const uiText = useTranslations();
  const currentUser = useCurrentUser();
  const [recordType, setRecordType] =
    useState<OperationalRecordType>(initialType);
  const [organizationId, setOrganizationId] = useState(
    currentOrg === "all" ? organizations[0]?.id || "" : currentOrg,
  );
  const [title, setTitle] = useState("");
  const [ownerName, setOwnerName] = useState(currentUser.name);
  const [valueLabel, setValueLabel] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const meta = operationMeta[recordType];
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      onCreate(
        await createPortfolioRecord({
          organization_id: organizationId,
          record_type: recordType,
          title: title.trim(),
          status: meta.defaultStatus,
          owner_name: ownerName.trim(),
          value_label: valueLabel.trim(),
          due_at: dueAt || null,
          notes: notes.trim(),
        }),
      );
    } catch (reason) {
      setError(
        localizedError(reason, uiText, uiText("Common.interface.couldNotCreateRecord")),
      );
      setSaving(false);
    }
  }
  return (
    <Modal
      title={uiText("Common.interface.addOperationalRecord")}
      text={uiText("Common.interface.createASecureTenantScopedOperationalRecordWithAReviewableStatus")}
      close={close}
    >
      <form className="form" onSubmit={submit}>
        <div className="form-row">
          <label>
            <span>{uiText("Settings.module")}</span>
            <select
              value={recordType}
              onChange={(event) =>
                setRecordType(event.target.value as OperationalRecordType)
              }
            >
              {operationGroups.map((item) => (
                <optgroup key={item} label={uiText(`Common.interface.${item.toLowerCase()}`)}>
                  {operationModules
                    .filter((type) => operationMeta[type].group === item && type!=="CSR_PROJECT")
                    .map((type) => (
                      <option value={type} key={type}>
                        {uiText(operationMeta[type].label)}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label>
            <span>{uiText("Authentication.organization")}</span>
            <select
              required
              value={organizationId}
              onChange={(event) => setOrganizationId(event.target.value)}
            >
              {organizations.map((organization) => (
                <option value={organization.id} key={organization.id}>
                  {organization.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          <span>{uiText("Common.interface.titlePersonSubject")}</span>
          <input
            autoFocus
            required
            minLength={2}
            maxLength={220}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={uiText("Common.interface.nameRecord")}
          />
        </label>
        <div className="form-row">
          <label>
            <span>{uiText("Common.interface.responsiblePersonContact")}</span>
            <input
              required
              minLength={2}
              maxLength={120}
              value={ownerName}
              onChange={(event) => setOwnerName(event.target.value)}
            />
          </label>
          <label>
            <span>{uiText(meta.valueLabel)}</span>
            <input
              maxLength={80}
              value={valueLabel}
              onChange={(event) => setValueLabel(event.target.value)}
              placeholder={uiText(meta.valueLabel)}
            />
          </label>
        </div>
        <label>
          <span>{uiText(meta.dateLabel)}</span>
          <input
            type="date"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
          />
        </label>
        <label>
          <span>{uiText("Common.interface.detailsAndInternalNotes")}</span>
          <textarea
            maxLength={2000}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder={uiText(meta.description)}
          />
        </label>
        {error && (
          <div className="form-error" role="alert">
            <AlertTriangle size={16} />
            {error}
          </div>
        )}
        <div className="form-info">
          <ShieldCheck size={17} />
           {uiText("Common.interface.initialStatus")} {meta.defaultStatus.replaceAll("_", " ")}{uiText("Common.interface.youCanUpdateTheRecordedStatusFromTheOperationsTableThisDoesNotExecuteAnExternalWorkflow")} </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
             {uiText("Common.actions.cancel")} </button>
          <button
            className="button primary"
            disabled={saving || !organizationId}
          >
            {saving ? uiText("Common.actions.saving") : uiText(`Common.interface.addRecordType.${recordType}`)}
          </button>
        </div>
      </form>
    </Modal>
  );
}

type AutomationResult = {
  overdue_compliances: number;
  overdue_tasks: number;
  upcoming: number;
  expiring_documents: number;
  recurring_created: number;
};
function IntegrationsView({
  items,
  isAdmin,
  onAutomation,
}: {
  items: IntegrationConnection[];
  isAdmin: boolean;
  onAutomation: (result: AutomationResult) => void;
}) {
  const uiText = useTranslations();
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  async function automate() {
    setWorking("automation");
    setError("");
    try {
      onAutomation(await runAutomation());
    } catch (reason) {
      setError(
        localizedError(reason, uiText, uiText("Common.interface.automationRunFailed")),
      );
    } finally {
      setWorking("");
    }
  }
  return (
    <div className="page">
      <PageHeading
        eyebrow={uiText("Common.interface.providerAbstraction")}
        title={uiText("Common.interface.integrationsAndAutomation")}
        text={uiText("Common.interface.manageExternalCapabilityReadinessWithoutCouplingComplianceDataToASingleVendor")}
        action={
          isAdmin && (
            <button
              className="button primary"
              disabled={working === "automation"}
              onClick={() => void automate()}
            >
              <RefreshCw size={17} />
              {working === "automation" ? uiText("Common.interface.running") : uiText("Common.interface.runDailyAutomation")}
            </button>
          )
        }
      />
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="integration-grid">
        {items.map((item) => (
          <article key={item.id}>
            <div>
              <i>
                <PlugZap size={19} />
              </i>
              <span>{item.category}</span>
            </div>
            <h2>{item.provider}</h2>
            <p>{item.description}</p>
            <footer>
              <StatusBadge status={item.status} />
              {isAdmin ? (
                <Link
                  className="button secondary small"
                  href="/settings/integrations"
                >
                  {item.status === "CONNECTED" ? uiText("Common.interface.manageConnection") : uiText("Common.interface.connect")}
                </Link>
              ) : (
                <small>{uiText("Common.interface.adminManaged")}</small>
              )}
            </footer>
          </article>
        ))}
      </div>
      <section className="automation-note">
        <ShieldCheck size={21} />
        <div>
          <h2>{uiText("Common.interface.idempotentDailyOperations")}</h2>
          <p>
             {uiText("Common.interface.theManualRunUsesTheSameSafeWorkflowIntendedForASchedulerItFlagsOverdueObligationsCreatesTaskAndExpiryAlertsOnceAndRollsCompletedRecurringObligationsIntoTheNextAnnualCycleWithoutChangingHistoricalRecords")} </p>
        </div>
      </section>
    </div>
  );
}

function Modal({
  title,
  text,
  close,
  children,
}: {
  title: string;
  text: string;
  close: () => void;
  children: React.ReactNode;
}) {
  const uiText = useTranslations();
  return (
    <>
      <button
        className="modal-scrim"
        aria-label={uiText("Common.interface.closeNamed", { name: title })}
        onClick={close}
      />
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div>
            <h2>{title}</h2>
            <p>{text}</p>
          </div>
          <button
            className="icon-button plain"
            aria-label={uiText("Common.interface.closeNamed", { name: title })}
            onClick={close}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </>
  );
}
function EmptyState({
  icon,
  title,
  text,
}: {
  icon: React.ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="empty-state">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function IntegrationLinks(){
 const t=useTranslations("Integrations");
 return <nav className="integration-actions" aria-label={t("navigation")}><Link className="button secondary" href="/settings/integrations">{t("title")}</Link><Link className="button secondary" href="/settings/developers">{t("developers")}</Link></nav>;
}
