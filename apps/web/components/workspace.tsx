"use client";

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
} from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  addComplianceComment,
  askAssistant,
  createCompliance,
  createDocument,
  createDocumentVersion,
  createOrganization,
  createPortfolioRecord,
  createTask,
  deletePortfolioRecord,
  inviteMember,
  loadComplianceComments,
  loadDocumentVersions,
  loadWorkspace,
  markNotificationRead,
  patchIntegration,
  patchPortfolioRecord,
  patchTask,
  runAutomation,
  transitionCompliance,
} from "@/lib/api";
import Link from "next/link";
import OnboardingBanner from "./onboarding-banner";
import { apiRequest } from "@/lib/http";
import { roleLabel, type AuthUser } from "@/lib/auth-types";
import UserManagement from "@/components/user-management";
import type {
  AssistantAnswer,
  AuditEvent,
  Compliance,
  ComplianceComment,
  ComplianceDefinition,
  ComplianceDocument,
  ComplianceTask,
  DocumentVersion,
  IntegrationConnection,
  Membership,
  Notification,
  Organization,
  PortfolioRecord,
  Subscription,
} from "@/lib/types";
import ThemeToggle from "@/components/theme-toggle";
import { normalizeEmail, validateEmail } from "@/lib/auth-validation";
import LocaleSwitcher from "@/components/locale-switcher";
import {
  activeLocale,
  formatDateTime,
  formatPercentage,
  formatShortDate,
  localizedCollator,
} from "@/i18n/format";
import LocalizationAdmin from "@/components/localization-admin";
import WhiteLabelSettings from "@/components/white-label-settings";
import PlatformNavigation from "@/components/platform-navigation";
import ComplianceTemplateRuntime from "@/components/compliance-template-runtime";
import { ComplianceNotificationMessage, ComplianceNotificationTitle } from "@/components/compliance-notification";
import OrganizationComplianceProfile from "@/components/organization-compliance-profile";
import { BrandIdentity, useTenantBrand } from "@/branding/client";

import { countsTowardCompletion, isOpenCompliance } from "@/lib/compliance-states";

const UserContext = createContext<AuthUser | null>(null);
function useCurrentUser() {
  const user = useContext(UserContext);
  if (!user) throw new Error("Sign-in context is missing");
  return user;
}

type View =
  | "overview"
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
  | "whiteLabel";

const nav = [
  { id: "overview" as View, labelKey: "dashboard", icon: LayoutDashboard },
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

function csvCell(value: string | number | null | undefined) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function dateInput(daysFromToday: number) {
  const date = new Date();
  date.setDate(date.getDate() + daysFromToday);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function documentReceipt(doc: ComplianceDocument) {
  downloadText(
    `${doc.name.replace(/\.[^.]+$/, "")}-record.json`,
    JSON.stringify(doc, null, 2),
    "application/json",
  );
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
}: {
  user: AuthUser;
  initialView?: View;
}) {
  const tCommon = useTranslations("Common");
  const tAuth = useTranslations("Authentication");
  const tBrand = useTranslations("WhiteLabel");
  const [view, setView] = useState<View>(initialView);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [selectedOrg, setSelectedOrg] = useState("all");
  const [orgMenu, setOrgMenu] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [headerSearch, setHeaderSearch] = useState("");
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

  useEffect(() => {
    loadWorkspace(user.role === "ADMIN")
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
          error instanceof Error ? error.message : "Unable to load workspace",
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
  }, [user.role]);

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
        updated.status === "DONE" ? "Task marked complete" : "Task reopened",
      );
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "Could not update task",
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
        error instanceof Error
          ? error.message
          : "Could not mark notification read",
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
      showToast(error instanceof Error ? error.message : "Could not sign out");
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
      showToast(`Status updated to ${statusLabels[status]}`);
    } catch (error) {
      showToast(
        error instanceof Error
          ? error.message
          : "Could not update this compliance",
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
  if (loadError || !subscription)
    return (
      <main className="workspace-loading">
        <h1>Unable to load workspace</h1>
        <p role="alert">{loadError || "Subscription is unavailable"}</p>
        <button
          className="button primary"
          onClick={() => window.location.reload()}
        >
          Try again
        </button>
        <Link href="/account">Account settings</Link>
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
              aria-label="Close navigation"
              onClick={() => setMobileMenu(false)}
            >
              <X size={19} />
            </button>
          </div>
          <p className="nav-label">{tCommon("mainNavigation")}</p>
          <nav aria-label={tCommon("mainNavigation")}>
            {nav
              .filter(
                (item) =>
                  !["operations", "administration", "localization", "whiteLabel"].includes(
                    item.id,
                  ) || user.role === "ADMIN",
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
            <strong>Compliance tip</strong>
            <p>
              Set internal targets at least 7 days before statutory deadlines.
            </p>
            <button
              onClick={() => {
                setPanel("guide");
                setMobileMenu(false);
              }}
            >
              View guide <ArrowRight size={14} />
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
              <span>Help centre</span>
            </button>
            <button
              onClick={() => {
                setPanel("settings");
                setMobileMenu(false);
              }}
            >
              <Settings size={18} />
              <span>Settings</span>
            </button>
          </nav>
          <div className="account">
            <Avatar name={user.name} />
            <div>
              <strong>{user.name}</strong>
              <small>{roleLabel(user.role)}</small>
            </div>
          </div>
          <div className="sidebar-account-links">
            <Link href="/account">My account & password</Link>
            <Link href="/select-workspace">{tAuth("selectWorkspace")}</Link>
            <button disabled={signingOut} onClick={logout}>
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </aside>

        {mobileMenu && (
          <button
            className="scrim"
            aria-label="Close menu"
            onClick={() => setMobileMenu(false)}
          />
        )}
        <main className="main">
          <OnboardingBanner canManage={user.role==="ADMIN"}/>
          <header className="topbar">
            <button
              className="menu-button"
              aria-label="Open navigation"
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
                      <small>Portfolio view</small>
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
                NGO management<small>{roleLabel(user.role)} workspace</small>
              </span>
            </span>
            <div className="top-actions">
              <form
                className="header-search"
                role="search"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (view === "whiteLabel" && brandDirty && !window.confirm(tBrand("unsavedConfirm"))) return;
                  setView("compliance");
                  setSearch(headerSearch);
                  setMobileMenu(false);
                }}
              >
                <Search size={16} />
                <input
                  aria-label={tCommon("actions.search")}
                  placeholder={`${tCommon("actions.search")}...`}
                  value={headerSearch}
                  onChange={(event) => setHeaderSearch(event.target.value)}
                />
                <button type="submit">Go!</button>
              </form>
              <LocaleSwitcher compact />
              <ThemeToggle variant="icon" />
              <div className="notification-wrap">
                <button
                  className="icon-button"
                  aria-label="Open notifications"
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
                aria-label="Open account settings"
              >
                <Avatar name={user.name} />
                <span>
                  {user.name}
                  <small>{roleLabel(user.role)}</small>
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
              documents={scopedDocuments}
              organizations={organizations}
              audits={auditEvents}
              orgName={org?.name}
              go={go}
              selectCompliance={setSelectedCompliance}
              toggleTask={toggleTask}
              setShowNew={setShowNew}
              openUpload={openUpload}
            />
          )}
          {view === "compliance" && (
            <ComplianceView
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
              items={scopedTasks}
              compliances={compliances}
              toggleTask={toggleTask}
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
            <ReportsView
              compliances={scopedCompliances}
              organizations={
                selectedOrg === "all"
                  ? organizations
                  : organizations.filter((item) => item.id === selectedOrg)
              }
              showToast={showToast}
            />
          )}
          {view === "programmes" && (
            <ProgrammesView
              items={scopedPortfolioRecords}
              organizations={organizations}
              currentOrg={selectedOrg}
              readOnly={user.role === "VIEWER"}
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
            <AssistantView
              organizationId={selectedOrg === "all" ? undefined : selectedOrg}
            />
          )}
          {view === "integrations" && (
            <><IntegrationLinks /><IntegrationsView
              items={integrations}
              isAdmin={user.role === "ADMIN"}
              onUpdate={(updated) =>
                setIntegrations((rows) =>
                  rows.map((row) => (row.id === updated.id ? updated : row)),
                )
              }
              onAutomation={(result) => {
                showToast(
                  `Automation complete: ${result.overdue_compliances + result.overdue_tasks + result.upcoming + result.expiring_documents} alerts, ${result.recurring_created} recurring items`,
                );
                void loadWorkspace(true).then((data) => {
                  setCompliances(data.compliances);
                  setTasks(data.tasks);
                  setDocuments(data.documents);
                  setNotifications(data.notifications);
                  setAuditEvents(data.auditEvents);
                });
              }}
            /></>
          )}
          {view === "administration" && user.role === "ADMIN" && (
            <AdministrationView
              organizations={organizations}
              compliances={compliances}
              definitions={complianceDefinitions}
              memberships={memberships}
              subscription={subscription}
              setShowNewOrganization={setShowNewOrganization}
              setShowInvite={setShowInvite}
            />
          )}
          {view === "localization" && user.role === "ADMIN" && (
            <LocalizationAdmin />
          )}
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
              showToast(`Invitation created for ${member.email}`);
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
  documents,
  organizations,
  audits,
  orgName,
  go,
  selectCompliance,
  toggleTask,
  setShowNew,
  openUpload,
}: {
  compliances: Compliance[];
  tasks: ComplianceTask[];
  documents: ComplianceDocument[];
  organizations: Organization[];
  audits: AuditEvent[];
  orgName?: string;
  go: (v: View) => void;
  selectCompliance: (c: Compliance) => void;
  toggleTask: (t: ComplianceTask) => void;
  setShowNew: (v: boolean) => void;
  openUpload: () => void;
}) {
  const t = useTranslations("Dashboard");
  const openItems = compliances.filter((item) => isOpenCompliance(item.status));
  const eligibleItems = compliances.filter((item) => countsTowardCompletion(item.status));
  const completed = compliances.filter(
    (item) => item.status === "COMPLETED",
  ).length;
  const active = compliances.filter((item) =>
    ["IN_PROGRESS", "UNDER_REVIEW", "READY_TO_FILE", "FILED"].includes(
      item.status,
    ),
  ).length;
  const risk = openItems.filter((item) =>
    ["HIGH", "CRITICAL"].includes(item.priority),
  ).length;
  const rate = eligibleItems.length
    ? Math.round((completed / eligibleItems.length) * 100)
    : 0;
  const today = dateInput(0);
  const overdue = openItems.filter(
    (item) => item.statutory_deadline < today,
  ).length;
  const deadlines = [...openItems]
    .sort((a, b) => a.statutory_deadline.localeCompare(b.statutory_deadline))
    .slice(0, 5);
  const openTasks = tasks.filter((task) => task.status !== "DONE");
  const expiredEvidence = documents.filter(
    (document) => document.expiry_at && document.expiry_at < today,
  ).length;
  return (
    <div className="page reference-dashboard">
      <PageHeading
        eyebrow={`Home / ${t("adminTitle")}`}
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
      <div className="metric-grid">
        <Metric
          label={t("totalCompliances")}
          value={compliances.length}
          note={orgName || t("organizations", { count: organizations.length })}
          icon={<ClipboardCheck size={26} />}
          tone="purple"
          onClick={() => go("compliance")}
        />
        <Metric
          label={t("openTasks")}
          value={openTasks.length}
          note={t("completed", {
            count: tasks.filter((task) => task.status === "DONE").length,
          })}
          icon={<ListChecks size={26} />}
          tone="pink"
          onClick={() => go("tasks")}
        />
        <Metric
          label={t("evidenceRecords")}
          value={documents.length}
          note={`${expiredEvidence} expired records`}
          icon={<FolderOpen size={26} />}
          tone="cyan"
          onClick={() => go("documents")}
        />
        <Metric
          label={t("complianceHealth")}
          value={formatPercentage(rate / 100)}
          note={t("completed", { count: completed })}
          icon={<CheckCircle2 size={26} />}
          tone="gold"
          onClick={() => go("reports")}
        />
      </div>
      <div className="statistics-grid">
        <section className="card statistics-card">
          <CardTitle
            title="Compliance Statistics"
            sub="Status of the selected portfolio"
            action={
              <button className="text-button" onClick={() => go("reports")}>
                View report <ChevronRight size={14} />
              </button>
            }
          />
          <div className="statistics-values">
            <div>
              <span>Total obligations</span>
              <strong className="stat-blue">{compliances.length}</strong>
            </div>
            <div>
              <span>In progress / filing</span>
              <strong className="stat-purple">{active}</strong>
            </div>
            <div>
              <span>Completed</span>
              <strong className="stat-green">{completed}</strong>
            </div>
            <div>
              <span>Overdue</span>
              <strong className="stat-red">{overdue}</strong>
            </div>
          </div>
        </section>
        <section className="card statistics-card">
          <CardTitle
            title="Task & Evidence Statistics"
            sub="Work and supporting records"
            action={
              <button className="text-button" onClick={() => go("documents")}>
                View evidence <ChevronRight size={14} />
              </button>
            }
          />
          <div className="statistics-values">
            <div>
              <span>Open tasks</span>
              <strong className="stat-blue">{openTasks.length}</strong>
            </div>
            <div>
              <span>Finished tasks</span>
              <strong className="stat-green">
                {tasks.length - openTasks.length}
              </strong>
            </div>
            <div>
              <span>Evidence records</span>
              <strong className="stat-purple">{documents.length}</strong>
            </div>
            <div>
              <span>Expired records</span>
              <strong className="stat-amber">{expiredEvidence}</strong>
            </div>
          </div>
        </section>
      </div>
      <section className="card admin-notice">
        <div className="notice-heading">
          <Bell size={17} />
          <h2>Compliance Notice</h2>
        </div>
        <div className="notice-body">
          <span className="notice-symbol">
            <AlertTriangle size={20} />
          </span>
          <div>
            <strong>
              {risk
                ? `${risk} high-priority obligations need attention`
                : "No high-priority obligations pending"}
            </strong>
            <p>
              {overdue
                ? `${overdue} open obligations are past their statutory deadline. Review their filing status and supporting evidence.`
                : "Keep evidence up to date and review internal targets before the statutory deadlines."}
            </p>
          </div>
          <button
            className="button secondary small"
            onClick={() => go("compliance")}
          >
            Open register <ArrowRight size={14} />
          </button>
        </div>
      </section>
      <div className="dashboard-grid">
        <section className="card upcoming-card">
          <CardTitle
            title={t("priorityDeadlines")}
            sub="Earliest open statutory dates, including overdue items"
            action={
              <button className="text-button" onClick={() => go("calendar")}>
                Calendar <ChevronRight size={15} />
              </button>
            }
          />
          <div className="deadline-list">
            {deadlines.map((item) => (
              <button key={item.id} onClick={() => selectCompliance(item)}>
                <div
                  className={`date-tile ${item.statutory_deadline < today ? "date-overdue" : ""}`}
                >
                  <strong>
                    {new Date(`${item.statutory_deadline}T12:00:00`).getDate()}
                  </strong>
                  <span>
                    {new Date(
                      `${item.statutory_deadline}T12:00:00`,
                    ).toLocaleString(activeLocale(), { month: "short" })}
                  </span>
                </div>
                <div className="deadline-main">
                  <strong>{item.title}</strong>
                  <span>
                    {
                      organizations.find(
                        (org) => org.id === item.organization_id,
                      )?.name
                    }{" "}
                    · {niceDate(item.statutory_deadline)}
                  </span>
                </div>
                <StatusBadge status={item.status} />
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
          {!deadlines.length && (
            <EmptyState
              icon={<CalendarDays />}
              title="No pending deadlines"
              text="New obligations will appear here."
            />
          )}
        </section>
        <section className="card task-card">
          <CardTitle
            title="Assigned Tasks"
            sub={`${openTasks.length} open assignments in this view`}
            action={
              <button className="text-button" onClick={() => go("tasks")}>
                View all <ChevronRight size={15} />
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
                    aria-label={`${task.status === "DONE" ? "Reopen" : "Complete"} ${task.title}`}
                    aria-pressed={task.status === "DONE"}
                    onClick={() => toggleTask(task)}
                  >
                    {task.status === "DONE" && <Check size={14} />}
                  </button>
                  <div>
                    <strong>{task.title}</strong>
                    <span>
                      Due {niceDate(task.due_at, true)} · {task.assignee_name}
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
              title="No tasks yet"
              text="Create an assignment from the Tasks page."
            />
          )}
        </section>
        <section className="card activity-card">
          <CardTitle
            title={t("recentActivity")}
            sub="Latest recorded changes across all organizations"
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
            <p className="muted">No activity has been recorded yet.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  note,
  icon,
  tone,
  onClick,
}: {
  label: string;
  value: number | string;
  note: string;
  icon: React.ReactNode;
  tone: string;
  onClick: () => void;
}) {
  return (
    <button className={`metric-card metric-${tone}`} onClick={onClick}>
      <span className="metric-icon">{icon}</span>
      <span className="metric-content">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{note}</small>
      </span>
      <ChevronRight className="metric-arrow" size={18} />
    </button>
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
  items,
  organizations,
  search,
  setSearch,
  selectCompliance,
  setShowNew,
}: {
  items: Compliance[];
  organizations: Organization[];
  search: string;
  setSearch: (v: string) => void;
  selectCompliance: (c: Compliance) => void;
  setShowNew: (v: boolean) => void;
}) {
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
              {item === "ALL" ? "All" : <StatusBadge status={item} />}
            </button>
          ))}
        </div>
      </div>
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
                    ? `Target ${niceDate(item.internal_target, true)}`
                    : "No internal target"}
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
            Showing {visible.length ? (page - 1) * pageSize + 1 : 0} to{" "}
            {Math.min(page * pageSize, visible.length)} of {visible.length}{" "}
            entries
          </span>
          <nav className="table-pagination" aria-label="Compliance pages">
            <button
              disabled={page <= 1}
              onClick={() => setPagination({ key: queryKey, page: page - 1 })}
            >
              Previous
            </button>
            <span aria-current="page">
              {page} / {pageCount}
            </span>
            <button
              disabled={page >= pageCount}
              onClick={() => setPagination({ key: queryKey, page: page + 1 })}
            >
              Next
            </button>
          </nav>
        </div>
      </section>
    </div>
  );
}

function TasksView({
  items,
  compliances,
  toggleTask,
  setShowNewTask,
}: {
  items: ComplianceTask[];
  compliances: Compliance[];
  toggleTask: (t: ComplianceTask) => void;
  setShowNewTask: (v: boolean) => void;
}) {
  const t = useTranslations("Tasks");
  const common = useTranslations("Common");
  const [tab, setTab] = useState("OPEN");
  const [assignee, setAssignee] = useState("ALL");
  const [selectedTask, setSelectedTask] = useState<ComplianceTask | null>(null);
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
  const visible = items.filter(
    (item) =>
      (tab === "ALL" ||
        (tab === "DONE" ? item.status === "DONE" : item.status !== "DONE")) &&
      (assignee === "ALL" || item.assignee_name === assignee),
  );
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
            {["OPEN", "DONE", "ALL"].map((item) => (
              <button
                key={item}
                className={tab === item ? "active" : ""}
                onClick={() => setTab(item)}
              >
                {item === "OPEN"
                  ? t("open")
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
                  aria-label={`View ${task.title}`}
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
          close={() => setSelectedTask(null)}
          toggleTask={() => {
            toggleTask(selectedTask);
            setSelectedTask(null);
          }}
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
              Critical/high risk
            </span>
            <span>
              <i className="medium" />
              Normal deadline
            </span>
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
  items,
  organizations,
  openUpload,
  showToast,
  updateDocument,
}: {
  items: ComplianceDocument[];
  organizations: Organization[];
  openUpload: () => void;
  showToast: (message: string) => void;
  updateDocument: (document: ComplianceDocument) => void;
}) {
  const t = useTranslations("Documents");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("ALL");
  const [selectedDoc, setSelectedDoc] = useState<ComplianceDocument | null>(
    null,
  );
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
                    aria-label={`View ${doc.name}`}
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
            showToast(`Version ${updated.version} added to document history`);
          }}
        />
      )}
    </>
  );
}

function ReportsView({
  compliances,
  organizations,
  showToast,
}: {
  compliances: Compliance[];
  organizations: Organization[];
  showToast: (message: string) => void;
}) {
  const t = useTranslations("Reports");
  const eligibleItems = compliances.filter((c) => countsTowardCompletion(c.status));
  const categories = [...new Set(eligibleItems.map((c) => c.category))];
  function exportReport() {
    const header = [
      "Code",
      "Compliance",
      "Organization",
      "Category",
      "Period",
      "Deadline",
      "Internal target",
      "Owner",
      "Priority",
      "Status",
      "Progress",
    ];
    const rows = compliances.map((item) => [
      item.code,
      item.title,
      organizations.find((org) => org.id === item.organization_id)?.name ||
        item.organization_id,
      item.category,
      item.period,
      item.statutory_deadline,
      item.internal_target,
      item.owner_name,
      item.priority,
      statusLabels[item.status] || item.status,
      item.progress,
    ]);
    downloadText(
      "setu-compliance-report.csv",
      [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n"),
      "text/csv;charset=utf-8",
    );
    showToast("Compliance report exported");
  }
  return (
    <div className="page">
      <PageHeading
        title={t("title")}
        text={t("description")}
        action={
          <div className="report-export-actions"><a className="button secondary" href={`/api/v1/reports/compliance/print?locale=${encodeURIComponent(activeLocale())}${organizations.length === 1 ? `&organization_id=${encodeURIComponent(organizations[0].id)}` : ""}`} target="_blank" rel="noopener noreferrer"><FileText size={17} />{t("printPdf")}</a><button className="button primary" onClick={exportReport}>
            <Download size={17} />
            {t("exportCsv")}
          </button></div>
        }
      />
      <div className="report-banner">
        <div>
          <span className="eyebrow">Portfolio health</span>
          <h2>
            Most obligations are moving, but evidence collection is the
            bottleneck.
          </h2>
          <p>
            {
              compliances.filter(
                (c) =>
                  ["HIGH", "CRITICAL"].includes(c.priority) &&
                  isOpenCompliance(c.status),
              ).length
            }{" "}
            high-risk items across{" "}
            {new Set(compliances.map((c) => c.organization_id)).size}{" "}
            organizations need management attention.
          </p>
        </div>
        <div className="report-score">
          <strong>
            {Math.round(
              eligibleItems.reduce((sum, c) => sum + c.progress, 0) /
                Math.max(1, eligibleItems.length),
            )}
          </strong>
          <span>Health score</span>
          <small>out of 100</small>
        </div>
      </div>
      <div className="report-grid">
        <section className="card">
          <CardTitle
            title="Progress by category"
            sub="Average completion of active obligations"
          />
          <div className="bar-chart">
            {categories.map((category) => {
              const rows = eligibleItems.filter((c) => c.category === category);
              const value = Math.round(
                rows.reduce((sum, c) => sum + c.progress, 0) / rows.length,
              );
              return (
                <div key={category}>
                  <span>{category}</span>
                  <div>
                    <b style={{ width: `${value}%` }} />
                  </div>
                  <strong>{formatPercentage(value / 100)}</strong>
                </div>
              );
            })}
          </div>
        </section>
        <section className="card">
          <CardTitle title="Organization health" sub="Portfolio comparison" />
          <div className="org-health">
            {organizations.map((org) => {
              const rows = eligibleItems.filter(
                (c) => c.organization_id === org.id,
              );
              const score = rows.length
                ? Math.round(
                    rows.reduce((sum, c) => sum + c.progress, 0) / rows.length,
                  )
                : 0;
              return (
                <div key={org.id}>
                  <span className="org-mini">{org.name[0]}</span>
                  <div>
                    <Link href={`/organizations/${org.id}`}><strong>{org.name}</strong></Link>
                    <small>{rows.length} obligations</small>
                  </div>
                  <b>{formatPercentage(score / 100)}</b>
                  <div className="mini-bar">
                    <i style={{ width: `${score}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </section>
        <section className="card full-report">
          <CardTitle
            title="Recommended actions"
            sub="Prioritized from your current workspace"
          />
          <div className="recommendation-grid">
            <div>
              <span>01</span>
              <strong>Close evidence gaps</strong>
              <p>
                Collect the missing audit schedules for Udaan before the
                internal target.
              </p>
            </div>
            <div>
              <span>02</span>
              <strong>Approve GST filing</strong>
              <p>
                GSTR-3B is prepared and needs final sign-off before submission.
              </p>
            </div>
            <div>
              <span>03</span>
              <strong>Start tax return</strong>
              <p>Assign a preparer and request tax audit inputs for ITR-7.</p>
            </div>
          </div>
        </section>
      </div>
    </div>
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
  const activeMembers = memberships.filter(
    (member) => member.status !== "INACTIVE",
  ).length;
  return (
    <div className="page">
      <PageHeading
        eyebrow="Tenant controls"
        title="Administration"
        text="Onboard NGOs, manage workspace accounts, review rules and monitor plan limits."
        action={
          <div className="heading-actions">
            <button
              className="button secondary"
              onClick={() => setShowInvite(true)}
            >
              <Users size={17} />
              Add responsibility
            </button>
            <button
              className="button primary"
              onClick={() => setShowNewOrganization(true)}
            >
              <Plus size={17} />
              Add organization
            </button>
          </div>
        }
      />
      <UserManagement currentUser={useCurrentUser()} />
      <PlatformNavigation />
      <OrganizationComplianceProfile organizations={organizations} />
      <div className="admin-summary">
        <div>
          <span>Current plan</span>
          <strong>{subscription.plan_name}</strong>
          <small>
            {subscription.status.toLowerCase()} through{" "}
            {niceDate(subscription.period_end)}
          </small>
        </div>
        <div>
          <span>Organizations</span>
          <strong>
            {organizations.length} / {subscription.organization_limit}
          </strong>
          <small>Consultant portfolio capacity</small>
        </div>
        <div>
          <span>Members</span>
          <strong>
            {activeMembers} / {subscription.user_limit}
          </strong>
          <small>
            {memberships.filter((member) => member.status === "INVITED").length}{" "}
            invitations pending
          </small>
        </div>
        <div>
          <span>Active rules</span>
          <strong>{definitions.length}</strong>
          <small>Versioned catalogue entries</small>
        </div>
      </div>
      <div className="admin-grid">
        <section className="card admin-organizations">
          <CardTitle
            title="Organizations"
            sub="Legal entities inside this tenant"
            action={
              <button
                className="text-button"
                onClick={() => setShowNewOrganization(true)}
              >
                Add organization <Plus size={15} />
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
                      <small>obligations</small>
                    </b>
                    <b className={risk ? "risk" : "safe"}>
                      {risk}
                      <small>high risk</small>
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
            title="Plan & entitlements"
            sub="Limits are enforced server-side"
          />
          <div className="plan-name">
            <ShieldCheck size={22} />
            <div>
              <strong>{subscription.plan_name}</strong>
              <span>Core compliance · portfolio management · reports</span>
            </div>
          </div>
          <UsageBar
            label="Organizations"
            value={organizations.length}
            limit={subscription.organization_limit}
          />
          <UsageBar
            label="Members"
            value={activeMembers}
            limit={subscription.user_limit}
          />
          <UsageBar
            label="Storage allocation"
            value={0}
            limit={subscription.storage_limit_gb}
            suffix=" GB"
          />
          <p className="plan-note">
            Changing plans never deletes organization records or evidence
            history.
          </p>
        </section>
        <section className="card team-card">
          <CardTitle
            title="Responsibility directory"
            sub="Legacy planning records only; login access is managed above"
            action={
              <button
                className="text-button"
                onClick={() => setShowInvite(true)}
              >
                Add responsibility <Plus size={15} />
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
                      : "All organizations"}
                  </strong>
                  <small>{member.status.toLowerCase()}</small>
                </span>
              </div>
            ))}
          </div>
        </section>
        <section className="card rules-card">
          <CardTitle
            title="Compliance catalogue"
            sub="Active, versioned onboarding rules"
          />
          <div className="rule-list">
            {definitions.map((definition) => (
              <div key={definition.id}>
                <i>{definition.code.slice(0, 2)}</i>
                <span>
                  <strong>{definition.title}</strong>
                  <small>
                    {definition.category} · Rule v{definition.rule_version}
                  </small>
                </span>
                <span>
                  <b>
                    {definition.requires_fcra
                      ? "FCRA only"
                      : definition.applicable_legal_types.replaceAll(",", ", ")}
                  </b>
                  <small>
                    Target {definition.internal_lead_days} days early
                  </small>
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
            Catalogue dates are configurable demonstration data and require
            qualified domain validation before production use.
          </p>
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
  limit: number;
  suffix?: string;
}) {
  const percent = Math.min(100, Math.round((value / Math.max(1, limit)) * 100));
  return (
    <div className="usage-row">
      <div>
        <span>{label}</span>
        <strong>
          {value}
          {suffix} of {limit}
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
  return (
    <div className="notification-panel">
      <div className="panel-head">
        <div>
          <strong>Notifications</strong>
          <span>{items.filter((i) => !i.is_read).length} unread</span>
        </div>
        <button
          onClick={onReadAll}
          disabled={items.every((item) => item.is_read)}
        >
          Mark all read
        </button>
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
        View all notifications
      </button>
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
      label: "Start work",
      secondary: {
        status: "NOT_APPLICABLE",
        label: "Mark not applicable",
        needsReason: true,
      },
    },
    NOT_STARTED: {
      status: "IN_PROGRESS",
      label: "Start work",
      secondary: {
        status: "NOT_APPLICABLE",
        label: "Mark not applicable",
        needsReason: true,
      },
    },
    IN_PROGRESS: {
      status: "UNDER_REVIEW",
      label: "Send for review",
      secondary: {
        status: "ON_HOLD",
        label: "Place on hold",
        needsReason: true,
      },
    },
    UNDER_REVIEW: {
      status: "READY_TO_FILE",
      label: "Approve for filing",
      secondary: {
        status: "CHANGES_REQUESTED",
        label: "Request changes",
        needsReason: true,
      },
    },
    CHANGES_REQUESTED: { status: "IN_PROGRESS", label: "Resume work" },
    READY_TO_FILE: {
      status: "FILED",
      label: "Record filing",
      needsReference: true,
      secondary: {
        status: "CHANGES_REQUESTED",
        label: "Request changes",
        needsReason: true,
      },
    },
    FILED: { status: "COMPLETED", label: "Complete compliance" },
    COMPLETED: {
      status: "IN_PROGRESS",
      label: "Reopen compliance",
      needsReason: true,
    },
    ON_HOLD: { status: "IN_PROGRESS", label: "Resume work", secondary: { status: "CANCELLED", label: cancelLabel, needsReason: true } },
    NOT_APPLICABLE: {
      status: "IN_PROGRESS",
      label: "Reopen as applicable",
      needsReason: true,
    },
    OVERDUE: {
      status: "IN_PROGRESS",
      label: "Record recovery work",
      secondary: {
        status: "ON_HOLD",
        label: "Place on hold",
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
        aria-label="Close compliance details"
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
            aria-label="Close compliance details"
            onClick={close}
          >
            <X size={20} />
          </button>
        </div>
        <div className="drawer-body">
          <div className="drawer-status">
            <StatusBadge status={item.status} />
            <span className={`priority-pill ${item.priority.toLowerCase()}`}>
              {item.priority} priority
            </span>
          </div>
          {item.template_version_id && <ComplianceTemplateRuntime item={item} updated={templateUpdated} />}
          <div className="progress-block">
            <div>
              <span>Preparation progress</span>
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
                <strong>Attention needed</strong>
                <p>{item.risk_note}</p>
              </div>
            </div>
          )}
          <section className="detail-section">
            <h3>Key details</h3>
            <div className="detail-grid">
              <div>
                <span>Organization</span>
                <strong>{org?.name}</strong>
              </div>
              <div>
                <span>Category</span>
                <strong>{item.category}</strong>
              </div>
              <div>
                <span>Statutory deadline</span>
                <strong>{niceDate(item.statutory_deadline)}</strong>
              </div>
              <div>
                <span>Internal target</span>
                <strong>{niceDate(item.internal_target)}</strong>
              </div>
              <div>
                <span>Accountable owner</span>
                <strong className="owner-detail">
                  <Avatar name={item.owner_name} label={item.owner_initials} />
                  {item.owner_name}
                </strong>
              </div>
              <div>
                <span>Legal reference</span>
                <strong>{item.legal_reference}</strong>
              </div>
            </div>
          </section>
          <section className="detail-section">
            <div className="section-title">
              <h3>Checklist</h3>
              <span>
                {relatedTasks.filter((task) => task.status === "DONE").length}/
                {relatedTasks.length} complete
              </span>
            </div>
            {relatedTasks.length ? (
              relatedTasks.map((task) => (
                <div className="drawer-list" key={task.id}>
                  <button
                    aria-label={
                      task.status === "DONE"
                        ? `Reopen ${task.title}`
                        : `Complete ${task.title}`
                    }
                    onClick={() => toggleTask(task)}
                    className={task.status === "DONE" ? "complete" : ""}
                  >
                    {task.status === "DONE" && <Check size={13} />}
                  </button>
                  <div>
                    <strong>{task.title}</strong>
                    <small>
                      {task.assignee_name} · Due {niceDate(task.due_at, true)}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <p className="muted">No tasks linked yet.</p>
            )}
          </section>
          <section className="detail-section">
            <div className="section-title">
              <h3>Evidence</h3>
              <span>{relatedDocs.length} files</span>
            </div>
            {relatedDocs.map((doc) => (
              <div className="drawer-list document" key={doc.id}>
                <span>
                  <FileText size={16} />
                </span>
                <div>
                  <strong>{doc.name}</strong>
                  <small>
                    Version {doc.version} · {doc.size_label}
                  </small>
                </div>
                <button
                  aria-label={`Download record for ${doc.name}`}
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
              Attach required evidence
            </button>
          </section>
          <ComplianceDiscussion complianceId={item.id} />
          {transition && selected && (
            <section className="transition-form">
              <strong>{selected.label}</strong>
              {"needsReason" in selected && selected.needsReason && (
                <label>
                  <span>Reason</span>
                  <textarea
                    autoFocus
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="Record the reason for the audit trail"
                  />
                </label>
              )}
              {"needsReference" in selected && selected.needsReference && (
                <label>
                  <span>Submission or acknowledgement reference</span>
                  <input
                    autoFocus
                    value={submissionReference}
                    onChange={(event) =>
                      setSubmissionReference(event.target.value)
                    }
                    placeholder="e.g. portal acknowledgement number"
                  />
                </label>
              )}
              <div>
                <button
                  className="button secondary small"
                  onClick={() => setTransition(null)}
                >
                  Cancel
                </button>
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
                  {saving ? "Saving..." : "Confirm"}
                </button>
              </div>
            </section>
          )}
        </div>
        <div className="drawer-foot">
          <button className="button secondary" onClick={close}>
            Close
          </button>
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
  const currentUser = useCurrentUser();
  const [comments, setComments] = useState<ComplianceComment[]>([]);
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<ComplianceComment["kind"]>("COMMENT");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    loadComplianceComments(complianceId)
      .then(setComments)
      .catch(() => setError("Discussion history is unavailable."));
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
        reason instanceof Error ? reason.message : "Could not save comment",
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="detail-section discussion">
      <div className="section-title">
        <h3>Discussion and exceptions</h3>
        <span>{comments.length} entries</span>
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
              {new Date(comment.created_at).toLocaleString("en-IN")}
            </small>
          </div>
        </div>
      ))}
      {currentUser.role !== "VIEWER" && (
        <form onSubmit={submit}>
          <select
            aria-label="Entry type"
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as ComplianceComment["kind"])
            }
          >
            <option value="COMMENT">Comment</option>
            <option value="CORRECTION">Correction request</option>
            <option value="EXCEPTION">Exception</option>
            <option value="RECOVERY_PLAN">Recovery plan</option>
          </select>
          <textarea
            aria-label="Discussion entry"
            required
            minLength={2}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="Record context, a correction request, exception or recovery plan"
          />
          <button className="button primary small" disabled={saving}>
            {saving ? "Saving..." : "Add entry"}
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
  return (
    <Modal
      title="Compliance workflow guide"
      text="A simple operating rhythm for every obligation."
      close={close}
    >
      <div className="modal-content">
        <div className="guide-steps">
          <div>
            <span>1</span>
            <div>
              <strong>Register the obligation</strong>
              <p>
                Choose the NGO, deadline, accountable owner, category and risk
                priority.
              </p>
            </div>
          </div>
          <div>
            <span>2</span>
            <div>
              <strong>Assign preparation tasks</strong>
              <p>
                Break the obligation into clear evidence, review and filing
                actions.
              </p>
            </div>
          </div>
          <div>
            <span>3</span>
            <div>
              <strong>Attach evidence</strong>
              <p>
                Link each document record to its organization and compliance
                item.
              </p>
            </div>
          </div>
          <div>
            <span>4</span>
            <div>
              <strong>Review and complete</strong>
              <p>
                Send prepared work for review, approve it, and retain the audit
                trail.
              </p>
            </div>
          </div>
        </div>
        <div className="modal-actions">
          <button className="button secondary" onClick={() => go("documents")}>
            Open evidence library
          </button>
          <button className="button primary" onClick={() => go("compliance")}>
            Open compliance register
          </button>
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
  return (
    <Modal
      title="Help centre"
      text="Quick answers for the Setu demonstration workspace."
      close={close}
    >
      <div className="modal-content">
        <div className="help-topics">
          <section>
            <ClipboardCheck size={19} />
            <div>
              <strong>Compliance register</strong>
              <p>
                Search, filter and open an obligation to manage its review
                lifecycle.
              </p>
            </div>
            <button onClick={() => go("compliance")}>
              Open <ArrowRight size={14} />
            </button>
          </section>
          <section>
            <ListChecks size={19} />
            <div>
              <strong>Tasks</strong>
              <p>
                Create assignments, filter by owner and mark checklist work
                complete.
              </p>
            </div>
            <button onClick={() => go("tasks")}>
              Open <ArrowRight size={14} />
            </button>
          </section>
          <section>
            <FolderOpen size={19} />
            <div>
              <strong>Evidence documents</strong>
              <p>
                Register document metadata and link evidence to an obligation.
              </p>
            </div>
            <button onClick={() => go("documents")}>
              Open <ArrowRight size={14} />
            </button>
          </section>
          <section>
            <Gauge size={19} />
            <div>
              <strong>Reports</strong>
              <p>Review portfolio health and export a CSV management report.</p>
            </div>
            <button onClick={() => go("reports")}>
              Open <ArrowRight size={14} />
            </button>
          </section>
        </div>
        <div className="form-info">
          <CircleHelp size={17} />
          This is a local MVP. Actual file storage and production sign-in are
          planned backend integrations.
        </div>
        <div className="modal-actions">
          <button className="button primary" onClick={close}>
            Done
          </button>
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
  const [emailReminders, setEmailReminders] = useState(true);
  const [weeklyDigest, setWeeklyDigest] = useState(true);
  const [leadDays, setLeadDays] = useState(7);
  useEffect(() => {
    const saved = localStorage.getItem("setu-workspace-preferences");
    if (!saved) return;
    try {
      const value = JSON.parse(saved) as {
        emailReminders?: boolean;
        weeklyDigest?: boolean;
        leadDays?: number;
      };
      setEmailReminders(value.emailReminders ?? true);
      setWeeklyDigest(value.weeklyDigest ?? true);
      setLeadDays(value.leadDays ?? 7);
    } catch {
      /* Ignore invalid local demo preferences. */
    }
  }, []);
  function save() {
    localStorage.setItem(
      "setu-workspace-preferences",
      JSON.stringify({ emailReminders, weeklyDigest, leadDays }),
    );
    onSave(leadDays);
  }
  return (
    <Modal
      title="Workspace settings"
      text="Configure local reminder preferences for this browser."
      close={close}
    >
      <div className="modal-content">
        <div className="settings-list">
          <label className="setting-row">
            <span>
              <strong>Deadline reminders</strong>
              <small>Receive alerts for approaching statutory dates.</small>
            </span>
            <input
              type="checkbox"
              checked={emailReminders}
              onChange={(e) => setEmailReminders(e.target.checked)}
            />
          </label>
          <label className="setting-row">
            <span>
              <strong>Weekly portfolio digest</strong>
              <small>Summarize open tasks and high-risk obligations.</small>
            </span>
            <input
              type="checkbox"
              checked={weeklyDigest}
              onChange={(e) => setWeeklyDigest(e.target.checked)}
            />
          </label>
          <label className="setting-row stacked">
            <span>
              <strong>Default internal lead time</strong>
              <small>Days before the statutory deadline.</small>
            </span>
            <input
              type="number"
              min="1"
              max="60"
              value={leadDays}
              onChange={(e) =>
                setLeadDays(Math.min(60, Math.max(1, Number(e.target.value))))
              }
            />
          </label>
        </div>
        <div className="form-info">
          <Settings size={17} />
          Preferences are saved locally in this browser for the MVP.
        </div>
        <div className="modal-actions">
          <button className="button secondary" onClick={close}>
            Cancel
          </button>
          <button className="button primary" onClick={save}>
            Save preferences
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
  return (
    <Modal
      title="Notification centre"
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
            Done
          </button>
        </div>
      </div>
    </Modal>
  );
}

function TaskDetailsModal({
  task,
  compliance,
  close,
  toggleTask,
}: {
  task: ComplianceTask;
  compliance?: Compliance;
  close: () => void;
  toggleTask: () => void;
}) {
  return (
    <Modal
      title={task.title}
      text="Task assignment and linkage details."
      close={close}
    >
      <div className="modal-content">
        <div className="detail-grid modal-detail-grid">
          <div>
            <span>Status</span>
            <strong>
              {task.status === "DONE"
                ? "Completed"
                : task.status === "IN_PROGRESS"
                  ? "In progress"
                  : "To do"}
            </strong>
          </div>
          <div>
            <span>Priority</span>
            <strong>{task.priority}</strong>
          </div>
          <div>
            <span>Due date</span>
            <strong>{niceDate(task.due_at)}</strong>
          </div>
          <div>
            <span>Assignee</span>
            <strong>{task.assignee_name}</strong>
          </div>
          <div className="wide">
            <span>Linked compliance</span>
            <strong>{compliance?.title || "Standalone task"}</strong>
          </div>
        </div>
        <div className="modal-actions">
          <button className="button secondary" onClick={close}>
            Close
          </button>
          <button className="button primary" onClick={toggleTask}>
            {task.status === "DONE" ? "Reopen task" : "Mark complete"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function DocumentDetailsModal({
  doc,
  organization,
  close,
  download,
  onVersion,
}: {
  doc: ComplianceDocument;
  organization?: Organization;
  close: () => void;
  download: () => void;
  onVersion: (document: ComplianceDocument) => void;
}) {
  const currentUser = useCurrentUser();
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void loadDocumentVersions(doc.id).then(setVersions);
  }, [doc.id, doc.version]);

  async function addVersion() {
    if (!file || saving) return;
    if (file.size > 25 * 1024 * 1024) {
      setError("The selected file is larger than 25 MB.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await createDocumentVersion(doc.id, {
        file_type: file.name.split(".").pop()?.toUpperCase() || "FILE",
        size_label:
          file.size >= 1024 * 1024
            ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
            : `${Math.max(1, Math.round(file.size / 1024))} KB`,
        uploaded_by: currentUser.name,
      });
      onVersion(updated);
      setFile(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not add this version.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={doc.name}
      text="Stored document metadata, immutable versions and evidence ownership."
      close={close}
    >
      <div className="modal-content">
        <div className="detail-grid modal-detail-grid">
          <div>
            <span>Organization</span>
            <strong>{organization?.name || doc.organization_id}</strong>
          </div>
          <div>
            <span>Category</span>
            <strong>{doc.category}</strong>
          </div>
          <div>
            <span>File type</span>
            <strong>{doc.file_type}</strong>
          </div>
          <div>
            <span>Active version</span>
            <strong>v{doc.version}</strong>
          </div>
          <div>
            <span>Size</span>
            <strong>{doc.size_label}</strong>
          </div>
          <div>
            <span>Expiry</span>
            <strong>{niceDate(doc.expiry_at)}</strong>
          </div>
        </div>
        <section className="version-section">
          <div className="section-title">
            <h3>Version history</h3>
            <span>{versions.length || doc.version} recorded</span>
          </div>
          <div className="version-list">
            {versions.map((version) => (
              <div key={version.id}>
                <span>v{version.version}</span>
                <div>
                  <strong>
                    {version.file_type} · {version.size_label}
                  </strong>
                  <small>
                    {version.uploaded_by} · {niceDate(version.created_at)}
                  </small>
                </div>
                <ShieldCheck size={16} />
              </div>
            ))}
          </div>
          <div className="version-upload">
            <label>
              <input
                type="file"
                accept=".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png"
                onChange={(event) => {
                  setFile(event.target.files?.[0] || null);
                  setError("");
                }}
              />
              <Upload size={17} />
              {file?.name || "Choose replacement file"}
            </label>
            <button
              className="button secondary small"
              type="button"
              disabled={!file || saving}
              onClick={addVersion}
            >
              {saving ? "Adding..." : "Add version"}
            </button>
          </div>
          {error && (
            <div className="form-error" role="alert">
              <AlertTriangle size={16} />
              {error}
            </div>
          )}
        </section>
        <div className="form-info">
          <ShieldCheck size={17} />
          Each replacement creates a new immutable version record. Binary object
          storage remains the production integration boundary.
        </div>
        <div className="modal-actions">
          <button className="button secondary" onClick={close}>
            Close
          </button>
          <button className="button primary" onClick={download}>
            <Download size={16} />
            Download record
          </button>
        </div>
      </div>
    </Modal>
  );
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
  const currentUser = useCurrentUser();
  const [title, setTitle] = useState("");
  const [org, setOrg] = useState(
    currentOrg === "all" ? organizations[0]?.id : currentOrg,
  );
  const [complianceId, setComplianceId] = useState("");
  const [dueAt, setDueAt] = useState(() => dateInput(7));
  const [priority, setPriority] = useState("MEDIUM");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const availableCompliances = compliances.filter(
    (item) => item.organization_id === org && isOpenCompliance(item.status),
  );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !org || saving) return;
    setSaving(true);
    setError("");
    try {
      const item = await createTask({
        organization_id: org,
        compliance_id: complianceId || null,
        title: title.trim(),
        due_at: dueAt,
        priority,
        assignee_name: currentUser.name,
        assignee_initials: initials(currentUser.name),
      });
      onCreate(item);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not create this task.",
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Create task"
      text="Assign a concrete next step to an owner and obligation."
      close={close}
    >
      <form onSubmit={submit} className="form">
        <label>
          <span>Task title</span>
          <input
            autoFocus
            required
            minLength={3}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Collect signed utilization certificates"
          />
        </label>
        <div className="form-row">
          <label>
            <span>Organization</span>
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
            <span>Due date</span>
            <input
              type="date"
              required
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
            />
          </label>
        </div>
        <label>
          <span>Linked compliance</span>
          <select
            value={complianceId}
            onChange={(e) => setComplianceId(e.target.value)}
          >
            <option value="">Standalone task</option>
            {availableCompliances.map((item) => (
              <option value={item.id} key={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <div className="form-row">
          <label>
            <span>Assignee</span>
            <input value={currentUser.name} readOnly />
          </label>
          <label>
            <span>Priority</span>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
              <option value="LOW">Low</option>
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
          The assignment and any later status changes are written to the audit
          history.
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
            Cancel
          </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? "Creating..." : "Create task"}
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
        requestError instanceof Error
          ? requestError.message
          : "Could not add this compliance.",
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Add compliance"
      text="Create a tracked obligation with a clear owner and deadline."
      close={close}
    >
      <form onSubmit={submit} className="form">
        <label>
          <span>Compliance title</span>
          <input
            autoFocus
            required
            minLength={3}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Annual activity report"
          />
        </label>
        <div className="form-row">
          <label>
            <span>Organization</span>
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
            <span>Statutory deadline</span>
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
            <span>Category</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option>General</option>
              <option>Income Tax</option>
              <option>FCRA</option>
              <option>GST</option>
              <option>Labour</option>
              <option>Governance</option>
            </select>
          </label>
          <label>
            <span>Priority</span>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
              <option value="LOW">Low</option>
            </select>
          </label>
        </div>
        <label>
          <span>Owner</span>
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
          This action will be recorded in the audit history. The internal target
          is set {leadDays} days early.
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
            Cancel
          </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? "Adding..." : "Add to register"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function UploadModal({
  organizations,
  compliances,
  currentOrg,
  initialComplianceId,
  close,
  onUpload,
}: {
  organizations: Organization[];
  compliances: Compliance[];
  currentOrg: string;
  initialComplianceId: string | null;
  close: () => void;
  onUpload: (doc: ComplianceDocument) => void;
}) {
  const currentUser = useCurrentUser();
  const [file, setFile] = useState<File | null>(null);
  const [org, setOrg] = useState(
    currentOrg === "all" ? organizations[0]?.id : currentOrg,
  );
  const [complianceId, setComplianceId] = useState(initialComplianceId || "");
  const [category, setCategory] = useState("Evidence");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !org || saving) return;
    if (file.size > 25 * 1024 * 1024) {
      setError("The selected file is larger than 25 MB.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const doc = await createDocument({
        organization_id: org,
        compliance_id: complianceId || null,
        name: file.name,
        category,
        file_type: file.name.split(".").pop()?.toUpperCase() || "FILE",
        size_label:
          file.size >= 1024 * 1024
            ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
            : `${Math.max(1, Math.round(file.size / 1024))} KB`,
        expiry_at: null,
        uploaded_by: currentUser.name,
      });
      onUpload(doc);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not add this document.",
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Upload evidence"
      text="Add a document to the secure, versioned evidence library."
      close={close}
    >
      <form onSubmit={submit} className="form">
        <label className="dropzone">
          <input
            type="file"
            accept=".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png"
            onChange={(e) => {
              setFile(e.target.files?.[0] || null);
              setError("");
            }}
          />
          <Upload size={24} />
          <strong>{file?.name || "Choose a file or drag it here"}</strong>
          <span>PDF, DOCX, XLSX, JPG or PNG · up to 25 MB</span>
        </label>
        <div className="form-row">
          <label>
            <span>Organization</span>
            <select
              required
              value={org}
              onChange={(e) => {
                setOrg(e.target.value);
                setComplianceId("");
              }}
            >
              {organizations.map((o) => (
                <option value={o.id} key={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Category</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option>Evidence</option>
              <option>Registration</option>
              <option>Financial</option>
              <option>Tax Registration</option>
            </select>
          </label>
        </div>
        <label>
          <span>Linked compliance</span>
          <select
            value={complianceId}
            onChange={(e) => setComplianceId(e.target.value)}
          >
            <option value="">General organization document</option>
            {compliances
              .filter((item) => item.organization_id === org)
              .map((item) => (
                <option value={item.id} key={item.id}>
                  {item.title}
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
          Document metadata is private and access-controlled. New versions never
          overwrite history.
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            className="button primary"
            type="submit"
            disabled={!file || saving}
          >
            {saving ? "Uploading..." : "Upload securely"}
          </button>
        </div>
      </form>
    </Modal>
  );
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
        requestError instanceof Error
          ? requestError.message
          : "Could not onboard this organization.",
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Onboard organization"
      text="Create the legal-entity profile and generate a rule-based compliance plan."
      close={close}
    >
      <form className="form" onSubmit={submit}>
        <label>
          <span>Organization name</span>
          <input
            autoFocus
            required
            minLength={3}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Seva Community Foundation"
          />
        </label>
        <div className="form-row">
          <label>
            <span>Legal structure</span>
            <select
              value={legalType}
              onChange={(event) => setLegalType(event.target.value)}
            >
              <option value="TRUST">Trust</option>
              <option value="SOCIETY">Society</option>
              <option value="SECTION 8">Section 8 company</option>
            </select>
          </label>
          <label>
            <span>City</span>
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
          <span>Registration number</span>
          <input
            required
            minLength={2}
            value={registrationNumber}
            onChange={(event) => setRegistrationNumber(event.target.value)}
            placeholder="Legal registration identifier"
          />
        </label>
        <div className="form-row">
          <label>
            <span>PAN</span>
            <input
              maxLength={20}
              value={pan}
              onChange={(event) => setPan(event.target.value)}
              placeholder="Optional"
            />
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={fcraActive}
              onChange={(event) => setFcraActive(event.target.checked)}
            />
            <span>
              <strong>FCRA active</strong>
              <small>Include FCRA-specific rule candidates</small>
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
            <strong>Generate initial compliance plan</strong>
            <small>
              Evaluate active rule versions against this organization profile.
            </small>
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
          Generated deadlines remain reviewable configuration and must be
          validated before production use.
        </div>
        <div className="modal-actions">
          <button
            className="button secondary"
            type="button"
            onClick={close}
            disabled={saving}
          >
            Cancel
          </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? "Onboarding..." : "Onboard organization"}
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
      setError(emailError);
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
        requestError instanceof Error
          ? requestError.message
          : "Could not create this invitation.",
      );
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Add responsibility"
      text="Grant a role at tenant or organization scope."
      close={close}
    >
      <form className="form" onSubmit={submit} noValidate>
        <div className="form-row">
          <label>
            <span>Full name</span>
            <input
              autoFocus
              required
              minLength={2}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            <span>Email</span>
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
                {emailError}
              </small>
            )}
          </label>
        </div>
        <label>
          <span>Role</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            <option value="TENANT_ADMIN">Tenant admin</option>
            <option value="ORGANIZATION_ADMIN">Organization admin</option>
            <option value="COMPLIANCE_OFFICER">Compliance officer</option>
            <option value="ACCOUNTANT">Accountant</option>
            <option value="AUDITOR">Auditor</option>
            <option value="CONSULTANT">Consultant</option>
            <option value="MANAGEMENT">Management</option>
            <option value="VIEWER">Viewer</option>
          </select>
        </label>
        <label>
          <span>Organization scope</span>
          <select
            value={organizationId}
            onChange={(event) => setOrganizationId(event.target.value)}
          >
            <option value="">All organizations in tenant</option>
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
          The invitation, role and scope are audit logged. Access is denied
          outside the selected scope.
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
            Cancel
          </button>
          <button className="button primary" type="submit" disabled={saving}>
            {saving ? "Creating..." : "Create invitation"}
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
    GRANT: "Grants",
    DONOR: "Donors",
    CSR_PROJECT: "CSR projects",
    VOLUNTEER: "Volunteers",
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
}: {
  items: PortfolioRecord[];
  organizations: Organization[];
  currentOrg: string;
  readOnly: boolean;
  onCreate: (item: PortfolioRecord) => void;
}) {
  const [tab, setTab] = useState<"ALL" | PortfolioRecord["record_type"]>("ALL");
  const [showNewRecord, setShowNewRecord] = useState(false);
  const impactItems = items.filter(isImpactRecord);
  const visible = impactItems.filter(
    (item) => tab === "ALL" || item.record_type === tab,
  );
  return (
    <>
      <div className="page">
        <PageHeading
          eyebrow="Expansion modules"
          title="Impact portfolio"
          text="Manage grants, donor relationships, CSR delivery and volunteer programmes alongside compliance."
          action={
            !readOnly && (
              <button
                className="button primary"
                onClick={() => setShowNewRecord(true)}
              >
                <Plus size={17} />
                Add record
              </button>
            )
          }
        />
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
              <span>{programmeLabels[type]}</span>
            </button>
          ))}
        </div>
        <div className="toolbar">
          <div className="filter-tabs">
            <button
              className={tab === "ALL" ? "active" : ""}
              onClick={() => setTab("ALL")}
            >
              All
            </button>
            {(
              Object.keys(programmeLabels) as PortfolioRecord["record_type"][]
            ).map((type) => (
              <button
                key={type}
                className={tab === type ? "active" : ""}
                onClick={() => setTab(type)}
              >
                {programmeLabels[type]}
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
                  <span>{programmeLabels[item.record_type]}</span>
                  <h3>{item.title}</h3>
                  <p>{item.notes || "No notes recorded."}</p>
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
                      ? `Due ${niceDate(item.due_at)}`
                      : "No due date"}
                  </small>
                </div>
              </article>
            ))}
          </div>
          {!visible.length && (
            <EmptyState
              icon={<HandHeart />}
              title="No records in this module"
              text="Add a record to begin managing this impact portfolio."
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
          status: "ACTIVE",
          owner_name: currentUser.name,
          value_label: valueLabel,
          due_at: dueAt || null,
          notes,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not create record",
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal
      title="Add impact record"
      text="Create a tenant-scoped grant, donor, CSR or volunteer record."
      close={close}
    >
      <form className="form" onSubmit={submit}>
        <div className="form-row">
          <label>
            <span>Module</span>
            <select
              value={recordType}
              onChange={(event) =>
                setRecordType(
                  event.target.value as PortfolioRecord["record_type"],
                )
              }
            >
              {(
                Object.keys(programmeLabels) as PortfolioRecord["record_type"][]
              ).map((type) => (
                <option value={type} key={type}>
                  {programmeLabels[type]}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Organization</span>
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
          <span>Record title</span>
          <input
            autoFocus
            required
            minLength={2}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Programme, relationship or engagement name"
          />
        </label>
        <div className="form-row">
          <label>
            <span>Value or scale</span>
            <input
              value={valueLabel}
              onChange={(event) => setValueLabel(event.target.value)}
              placeholder="e.g. INR 10 lakh or 20 volunteers"
            />
          </label>
          <label>
            <span>Milestone date</span>
            <input
              type="date"
              value={dueAt}
              onChange={(event) => setDueAt(event.target.value)}
            />
          </label>
        </div>
        <label>
          <span>Notes</span>
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Objectives, reporting needs, stewardship or delivery notes"
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={close}>
            Cancel
          </button>
          <button className="button primary" disabled={saving}>
            {saving ? "Saving..." : "Add record"}
          </button>
        </div>
      </form>
    </Modal>
  );
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
    label: "Memberships",
    singular: "membership",
    group: "People",
    description: "Applications, fees, validity and verification",
    defaultStatus: "PENDING",
    statuses: ["PENDING", "VERIFIED", "BLOCKED", "EXPIRED"],
    valueLabel: "Fee / transaction",
    dateLabel: "Valid until",
  },
  VOLUNTEER: {
    label: "Volunteers",
    singular: "volunteer",
    group: "People",
    description: "Applications, approvals and validity",
    defaultStatus: "PENDING",
    statuses: ["PENDING", "ACTIVE", "APPROVED", "REJECTED", "EXPIRED"],
    valueLabel: "Location / ID",
    dateLabel: "Valid until",
  },
  VOLUNTEER_ACTIVITY: {
    label: "Volunteer activities",
    singular: "activity",
    group: "People",
    description: "Hours, activity type, event and notes",
    defaultStatus: "LOGGED",
    statuses: ["LOGGED", "APPROVED", "REJECTED"],
    valueLabel: "Hours / event",
    dateLabel: "Activity date",
  },
  MANAGEMENT_MEMBER: {
    label: "Management body",
    singular: "management member",
    group: "People",
    description: "Board profile, department and display order",
    defaultStatus: "ACTIVE",
    statuses: ["ACTIVE", "INACTIVE"],
    valueLabel: "Role / department",
    dateLabel: "Term end",
  },
  CSR_PROJECT: {
    label: "Projects & funds",
    singular: "project",
    group: "Fundraising",
    description: "Targets, funds raised and delivery status",
    defaultStatus: "ACTIVE",
    statuses: ["DRAFT", "ACTIVE", "ON_TRACK", "COMPLETED", "ON_HOLD"],
    valueLabel: "Target / raised",
    dateLabel: "End date",
  },
  DONATION: {
    label: "Donations",
    singular: "donation",
    group: "Fundraising",
    description: "Donor, amount, transaction and 80G workflow",
    defaultStatus: "PENDING",
    statuses: ["PENDING", "VERIFIED", "APPROVED", "REJECTED"],
    valueLabel: "Amount / transaction",
    dateLabel: "Donation date",
  },
  CAMPAIGN: {
    label: "Crowdfunding",
    singular: "campaign",
    group: "Fundraising",
    description: "Public campaigns, goals and progress",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "ACTIVE", "CLOSED"],
    valueLabel: "Goal / raised",
    dateLabel: "Closing date",
  },
  SPONSOR: {
    label: "Sponsors",
    singular: "sponsor",
    group: "Fundraising",
    description: "Sponsor identity, website and priority",
    defaultStatus: "ACTIVE",
    statuses: ["ACTIVE", "INACTIVE"],
    valueLabel: "Website / priority",
    dateLabel: "Review date",
  },
  EVENT: {
    label: "Events",
    singular: "event",
    group: "Engagement",
    description: "Dates, locations and registration capacity",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "COMPLETED", "CANCELLED"],
    valueLabel: "Location / capacity",
    dateLabel: "Event date",
  },
  MESSAGE: {
    label: "Messages",
    singular: "message",
    group: "Engagement",
    description: "Member email and dashboard delivery",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "SENT", "FAILED"],
    valueLabel: "Audience / channel",
    dateLabel: "Send date",
  },
  INQUIRY: {
    label: "Inquiries",
    singular: "inquiry",
    group: "Engagement",
    description: "Category, urgency, status and admin notes",
    defaultStatus: "OPEN",
    statuses: ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"],
    valueLabel: "Category / urgency",
    dateLabel: "Follow-up date",
  },
  CERTIFICATE: {
    label: "Certificates",
    singular: "certificate",
    group: "Publishing",
    description: "Visitor certificates, issue number and email",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "ISSUED", "EMAILED", "REVOKED"],
    valueLabel: "Recipient / number",
    dateLabel: "Issue date",
  },
  DOCUMENT_TEMPLATE: {
    label: "Document templates",
    singular: "template",
    group: "Publishing",
    description: "Reusable branded certificate and letter layouts",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Brand / document type",
    dateLabel: "Review date",
  },
  NEWS: {
    label: "News & updates",
    singular: "article",
    group: "Publishing",
    description: "Website announcements and publication state",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Slug / category",
    dateLabel: "Publish date",
  },
  GALLERY_ITEM: {
    label: "Gallery",
    singular: "gallery item",
    group: "Publishing",
    description: "Public images and video links",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Image / video",
    dateLabel: "Publish date",
  },
  TESTIMONIAL: {
    label: "Testimonials",
    singular: "testimonial",
    group: "Publishing",
    description: "Review content, stars and display priority",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "INACTIVE"],
    valueLabel: "Role / stars",
    dateLabel: "Publish date",
  },
  TRAINING_VIDEO: {
    label: "Training",
    singular: "training video",
    group: "Publishing",
    description: "Member training videos and resources",
    defaultStatus: "ACTIVE",
    statuses: ["ACTIVE", "INACTIVE"],
    valueLabel: "Video URL / category",
    dateLabel: "Review date",
  },
  CONTENT_PAGE: {
    label: "Website content",
    singular: "content page",
    group: "Publishing",
    description: "About, objectives, legal, contact and slider content",
    defaultStatus: "DRAFT",
    statuses: ["DRAFT", "PUBLISHED", "ARCHIVED"],
    valueLabel: "Page / section",
    dateLabel: "Publish date",
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
}: {
  items: PortfolioRecord[];
  organizations: Organization[];
  currentOrg: string;
  onCreate: (item: PortfolioRecord) => void;
  onUpdate: (item: PortfolioRecord) => void;
  onDelete: (id: string) => void;
}) {
  const [group, setGroup] = useState<OperationGroup>("People");
  const [module, setModule] = useState<OperationalRecordType | "ALL">("ALL");
  const [query, setQuery] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const operationalItems = items.filter(isOperationalRecord);
  const groupModules = operationModules.filter(
    (type) => operationMeta[type].group === group,
  );
  const visible = operationalItems.filter(
    (item) =>
      operationMeta[item.record_type].group === group &&
      (module === "ALL" || item.record_type === module) &&
      `${item.title} ${item.owner_name} ${item.notes} ${item.value_label}`
        .toLowerCase()
        .includes(query.toLowerCase()),
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
        reason instanceof Error ? reason.message : "Could not update record",
      );
    } finally {
      setWorking("");
    }
  }
  async function remove(item: PortfolioRecord) {
    if (!window.confirm(`Delete ${item.title}? This action is audit logged.`))
      return;
    setWorking(item.id);
    setError("");
    try {
      await deletePortfolioRecord(item.id);
      onDelete(item.id);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not delete record",
      );
    } finally {
      setWorking("");
    }
  }
  return (
    <>
      <div className="page operations-page">
        <PageHeading
          eyebrow="Reference portal parity"
          title="NGO operations centre"
          text="Run membership, fundraising, engagement and public website workflows from one tenant-scoped admin workspace."
          action={
            <button className="button primary" onClick={() => setShowNew(true)}>
              <Plus size={17} />
              Add operational record
            </button>
          }
        />
        <div className="operations-hero">
          <div>
            <span>
              <Sparkles size={14} />
              Unified control room
            </span>
            <h2>From first inquiry to verified impact.</h2>
            <p>
              Every operational record belongs to an organization, supports a
              review status and is included in the audit trail.
            </p>
          </div>
          <div>
            <strong>{operationalItems.length}</strong>
            <span>operational records</span>
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
              <span>{item}</span>
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
                <strong>{operationMeta[type].label}</strong>
                <small>{operationMeta[type].description}</small>
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
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Search ${group.toLowerCase()} records...`}
            />
          </label>
          <div className="filter-tabs">
            <button
              className={module === "ALL" ? "active" : ""}
              onClick={() => setModule("ALL")}
            >
              All {group}
            </button>
            {groupModules.map((type) => (
              <button
                key={type}
                className={module === type ? "active" : ""}
                onClick={() => setModule(type)}
              >
                {operationMeta[type].label}
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
        <section className="table-card operations-table">
          <div className="table-head">
            <span>Record</span>
            <span>Organization</span>
            <span>Value / reference</span>
            <span>Date</span>
            <span>Status</span>
            <span>Actions</span>
          </div>
          {visible.map((item) => (
            <div className="table-row" key={item.id}>
              <span>
                <small>{operationMeta[item.record_type].label}</small>
                <strong>{item.title}</strong>
                <em>{item.notes || "No notes recorded"}</em>
              </span>
              <span>
                <strong>
                  {organizations.find(
                    (organization) => organization.id === item.organization_id,
                  )?.name || "Organization"}
                </strong>
                <small>{item.owner_name}</small>
              </span>
              <span>
                <strong>{item.value_label || "—"}</strong>
                <small>{operationMeta[item.record_type].valueLabel}</small>
              </span>
              <span>
                <strong>{item.due_at ? niceDate(item.due_at) : "—"}</strong>
                <small>{operationMeta[item.record_type].dateLabel}</small>
              </span>
              <span>
                <select
                  aria-label={`Status for ${item.title}`}
                  value={item.status}
                  disabled={working === item.id}
                  onChange={(event) =>
                    void changeStatus(item, event.target.value)
                  }
                >
                  {operationMeta[item.record_type].statuses.map((status) => (
                    <option key={status}>{status}</option>
                  ))}
                </select>
              </span>
              <span>
                <button
                  className="icon-button plain danger"
                  aria-label={`Delete ${item.title}`}
                  disabled={working === item.id}
                  onClick={() => void remove(item)}
                >
                  <Trash2 size={16} />
                </button>
              </span>
            </div>
          ))}
          {!visible.length && (
            <EmptyState
              icon={<Megaphone />}
              title={`No ${module === "ALL" ? group.toLowerCase() : operationMeta[module].label.toLowerCase()} records yet`}
              text="Add the first operational record; it will be stored securely under the selected organization."
            />
          )}
        </section>
      </div>
      {showNew && (
        <NewOperationModal
          organizations={organizations}
          currentOrg={currentOrg}
          initialType={module === "ALL" ? groupModules[0] : module}
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
        reason instanceof Error ? reason.message : "Could not create record",
      );
      setSaving(false);
    }
  }
  return (
    <Modal
      title={`Add ${meta.singular}`}
      text="Create a secure, tenant-scoped operational record with a reviewable status."
      close={close}
    >
      <form className="form" onSubmit={submit}>
        <div className="form-row">
          <label>
            <span>Module</span>
            <select
              value={recordType}
              onChange={(event) =>
                setRecordType(event.target.value as OperationalRecordType)
              }
            >
              {operationGroups.map((item) => (
                <optgroup key={item} label={item}>
                  {operationModules
                    .filter((type) => operationMeta[type].group === item)
                    .map((type) => (
                      <option value={type} key={type}>
                        {operationMeta[type].label}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label>
            <span>Organization</span>
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
          <span>Title / person / subject</span>
          <input
            autoFocus
            required
            minLength={2}
            maxLength={220}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={`Name this ${meta.singular}`}
          />
        </label>
        <div className="form-row">
          <label>
            <span>Responsible person / contact</span>
            <input
              required
              minLength={2}
              maxLength={120}
              value={ownerName}
              onChange={(event) => setOwnerName(event.target.value)}
            />
          </label>
          <label>
            <span>{meta.valueLabel}</span>
            <input
              maxLength={80}
              value={valueLabel}
              onChange={(event) => setValueLabel(event.target.value)}
              placeholder={meta.valueLabel}
            />
          </label>
        </div>
        <label>
          <span>{meta.dateLabel}</span>
          <input
            type="date"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
          />
        </label>
        <label>
          <span>Details and internal notes</span>
          <textarea
            maxLength={2000}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder={meta.description}
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
          Initial status: {meta.defaultStatus.replaceAll("_", " ")}. You can
          advance the workflow from the operations table.
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            className="button primary"
            disabled={saving || !organizationId}
          >
            {saving ? "Saving..." : `Add ${meta.singular}`}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AssistantView({ organizationId }: { organizationId?: string }) {
  const [question, setQuestion] = useState("What needs attention right now?");
  const [result, setResult] = useState<AssistantAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function ask(value = question) {
    setQuestion(value);
    setLoading(true);
    setError("");
    try {
      setResult(await askAssistant(value, organizationId));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Assistant unavailable",
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="page">
      <PageHeading
        eyebrow="Grounded intelligence"
        title="Compliance assistant"
        text="Ask operational questions against authorized workspace records. Answers cite the records used."
      />
      <section className="assistant-shell">
        <div className="assistant-prompts">
          <strong>Suggested questions</strong>
          {[
            "What needs attention right now?",
            "Which tasks are still open?",
            "Which documents expire soon?",
          ].map((prompt) => (
            <button key={prompt} onClick={() => void ask(prompt)}>
              {prompt}
              <ArrowRight size={14} />
            </button>
          ))}
        </div>
        <div className="assistant-main">
          <div className="assistant-intro">
            <Bot size={26} />
            <div>
              <strong>Setu operational assistant</strong>
              <p>
                Tenant-grounded summaries with human review for consequential
                decisions.
              </p>
            </div>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void ask();
            }}
          >
            <textarea
              aria-label="Question for the compliance assistant"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
            <button
              className="button primary"
              disabled={loading || question.trim().length < 3}
            >
              {loading ? "Reviewing records..." : "Ask assistant"}
            </button>
          </form>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {result && (
            <div className="assistant-answer" aria-live="polite">
              <h3>Answer</h3>
              <p>{result.answer}</p>
              <strong>Records used</strong>
              {result.sources.length ? (
                <ul>
                  {result.sources.map((source) => (
                    <li key={`${source.type}-${source.id}`}>
                      <span>{source.type}</span>
                      {source.label}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No matching records were required.</p>
              )}
              <small>{result.disclaimer}</small>
            </div>
          )}
        </div>
      </section>
    </div>
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
  onUpdate,
  onAutomation,
}: {
  items: IntegrationConnection[];
  isAdmin: boolean;
  onUpdate: (item: IntegrationConnection) => void;
  onAutomation: (result: AutomationResult) => void;
}) {
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  async function change(item: IntegrationConnection) {
    setWorking(item.id);
    setError("");
    try {
      onUpdate(
        await patchIntegration(
          item.id,
          item.status === "CONNECTED" ? "PAUSED" : "CONNECTED",
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not update integration",
      );
    } finally {
      setWorking("");
    }
  }
  async function automate() {
    setWorking("automation");
    setError("");
    try {
      onAutomation(await runAutomation());
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Automation run failed",
      );
    } finally {
      setWorking("");
    }
  }
  return (
    <div className="page">
      <PageHeading
        eyebrow="Provider abstraction"
        title="Integrations and automation"
        text="Manage external capability readiness without coupling compliance data to a single vendor."
        action={
          isAdmin && (
            <button
              className="button primary"
              disabled={working === "automation"}
              onClick={() => void automate()}
            >
              <RefreshCw size={17} />
              {working === "automation" ? "Running..." : "Run daily automation"}
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
                <button
                  className="button secondary small"
                  disabled={working === item.id}
                  onClick={() => void change(item)}
                >
                  {working === item.id
                    ? "Saving..."
                    : item.status === "CONNECTED"
                      ? "Pause"
                      : "Connect"}
                </button>
              ) : (
                <small>Admin managed</small>
              )}
            </footer>
          </article>
        ))}
      </div>
      <section className="automation-note">
        <ShieldCheck size={21} />
        <div>
          <h2>Idempotent daily operations</h2>
          <p>
            The manual run uses the same safe workflow intended for a scheduler:
            it flags overdue obligations, creates task and expiry alerts once,
            and rolls completed recurring obligations into the next annual cycle
            without changing historical records.
          </p>
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
  return (
    <>
      <button
        className="modal-scrim"
        aria-label={`Close ${title}`}
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
            aria-label={`Close ${title}`}
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
