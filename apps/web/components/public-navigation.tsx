"use client";

import {
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  ChevronDown,
  Ellipsis,
  Globe2,
  HandHeart,
  Menu,
  ShieldCheck,
  X,
} from "lucide-react";
import ThemeToggle from "@/components/theme-toggle";
import { useLocale } from "next-intl";
import { localeCookieName, type AppLocale } from "@/i18n/config";

type Locale = "en" | "hi" | "mr" | "kn";
type OpenMenu = "about" | "donation" | "more" | "language" | null;

const languages: Array<{
  id: Locale;
  htmlLang: string;
  badge: string;
  label: string;
}> = [
  { id: "en", htmlLang: "en", badge: "EN", label: "English" },
  { id: "hi", htmlLang: "hi", badge: "हि", label: "हिन्दी" },
  { id: "mr", htmlLang: "mr", badge: "म", label: "मराठी" },
  { id: "kn", htmlLang: "kn", badge: "ಕ", label: "ಕನ್ನಡ" },
];

const navigationCopy: Record<
  Locale,
  {
    home: string;
    about: string;
    certificates: string;
    projects: string;
    donation: string;
    contact: string;
    more: string;
    login: string;
    support: string;
  }
> = {
  en: {
    home: "Home",
    about: "About",
    certificates: "Certificates",
    projects: "Projects",
    donation: "Donation",
    contact: "Contact",
    more: "More",
    login: "Log in",
    support: "Support Us",
  },
  hi: {
    home: "होम",
    about: "परिचय",
    certificates: "प्रमाणपत्र",
    projects: "परियोजनाएँ",
    donation: "दान",
    contact: "संपर्क",
    more: "अधिक",
    login: "लॉग इन",
    support: "सहयोग करें",
  },
  mr: {
    home: "मुख्यपृष्ठ",
    about: "आमच्याबद्दल",
    certificates: "प्रमाणपत्रे",
    projects: "प्रकल्प",
    donation: "देणगी",
    contact: "संपर्क",
    more: "अधिक",
    login: "लॉग इन",
    support: "सहयोग करा",
  },
  kn: {
    home: "ಮುಖಪುಟ",
    about: "ಪರಿಚಯ",
    certificates: "ಪ್ರಮಾಣಪತ್ರಗಳು",
    projects: "ಯೋಜನೆಗಳು",
    donation: "ದೇಣಿಗೆ",
    contact: "ಸಂಪರ್ಕ",
    more: "ಇನ್ನಷ್ಟು",
    login: "ಲಾಗ್ ಇನ್",
    support: "ಬೆಂಬಲಿಸಿ",
  },
};

export default function PublicNavigation() {
  const requestLocale = useLocale();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<OpenMenu>(null);
  const [activeSection, setActiveSection] = useState("home");
  const locale = (requestLocale.split("-")[0] as Locale) || "en";
  const [languageNotice, setLanguageNotice] = useState("");
  const headerRef = useRef<HTMLElement>(null);
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectedLanguage =
    languages.find((language) => language.id === locale) ?? languages[0];
  const copy = navigationCopy[locale];

  const closeNavigation = () => {
    setMobileOpen(false);
    setOpenMenu(null);
  };

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeNavigation();
    };
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (
        headerRef.current &&
        !headerRef.current.contains(event.target as Node)
      )
        closeNavigation();
    };
    window.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("pointerdown", closeOnOutsideClick);
    };
  }, []);

  useEffect(
    () => () => {
      if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    if (!mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileOpen]);

  useEffect(() => {
    const sectionIds = [
      "home",
      "platform",
      "workflow",
      "security",
      "certificates",
      "projects",
      "dnd",
      "contact",
      "plans",
      "admin",
      "faq",
      "support",
    ];
    const sections = sectionIds
      .map((id) => document.getElementById(id))
      .filter((section): section is HTMLElement => Boolean(section));
    if (window.location.hash) setActiveSection(window.location.hash.slice(1));
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (first, second) =>
              second.intersectionRatio - first.intersectionRatio,
          )[0];
        if (visible?.target.id) setActiveSection(visible.target.id);
      },
      { rootMargin: "-28% 0px -58%", threshold: [0, 0.15, 0.4] },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const chooseLanguage = (nextLocale: Locale) => {
    const language =
      languages.find((item) => item.id === nextLocale) ?? languages[0];
    const localeCode = (
      { en: "en-IN", hi: "hi-IN", mr: "mr-IN", kn: "kn-IN" } as Record<
        Locale,
        AppLocale
      >
    )[nextLocale];
    localStorage.setItem("setu-locale-explicit", "1");
    document.cookie = `${localeCookieName}=${localeCode};path=/;max-age=31536000;samesite=lax`;
    setOpenMenu(null);
    setLanguageNotice(
      `${language.label} selected. Navigation language updated.`,
    );
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = setTimeout(() => window.location.reload(), 250);
  };

  const navigateToSection = (
    event: ReactMouseEvent<HTMLAnchorElement>,
    sectionId: string,
  ) => {
    event.preventDefault();
    setActiveSection(sectionId);
    closeNavigation();
    window.requestAnimationFrame(() => {
      const section = document.getElementById(sectionId);
      if (!section) return;
      section.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
        block: "start",
      });
      window.history.replaceState(null, "", `#${sectionId}`);
    });
  };

  const toggleMenu = (menu: Exclude<OpenMenu, null>) => {
    setOpenMenu((current) => (current === menu ? null : menu));
  };

  const aboutActive = ["platform", "workflow", "security"].includes(
    activeSection,
  );
  const moreActive = ["plans", "admin", "faq"].includes(activeSection);

  return (
    <header
      className="marketing-header"
      ref={headerRef}
      data-menu-open={mobileOpen}
    >
      <Link
        className="marketing-brand"
        href="/"
        aria-label="Setu NGO home"
        onClick={closeNavigation}
      >
        <span className="brand-mark">
          <ShieldCheck size={23} />
          <i />
        </span>
        <strong>
          Setu NGO<small>Compliance and impact management</small>
        </strong>
      </Link>

      {mobileOpen && (
        <button
          className="public-nav-backdrop"
          type="button"
          aria-label="Close navigation"
          onClick={closeNavigation}
        />
      )}

      <nav aria-label="Public website navigation" data-open={mobileOpen}>
        <a
          className={activeSection === "home" ? "active" : ""}
          href="#home"
          onClick={(event) => navigateToSection(event, "home")}
        >
          {copy.home}
        </a>
        <div className="public-nav-menu" data-open={openMenu === "about"}>
          <button
            className={
              aboutActive ? "nav-menu-trigger active" : "nav-menu-trigger"
            }
            type="button"
            aria-expanded={openMenu === "about"}
            aria-controls="about-navigation"
            onClick={() => toggleMenu("about")}
          >
            {copy.about} <ChevronDown size={13} />
          </button>
          <div className="nav-menu-panel" id="about-navigation">
            <a
              href="#platform"
              onClick={(event) => navigateToSection(event, "platform")}
            >
              <strong>About Setu</strong>
              <small>What the platform provides</small>
            </a>
            <a
              href="#workflow"
              onClick={(event) => navigateToSection(event, "workflow")}
            >
              <strong>How it works</strong>
              <small>The compliance lifecycle</small>
            </a>
            <a
              href="#security"
              onClick={(event) => navigateToSection(event, "security")}
            >
              <strong>Security</strong>
              <small>Tenant isolation and audit</small>
            </a>
          </div>
        </div>
        <a
          className={activeSection === "certificates" ? "active" : ""}
          href="#certificates"
          onClick={(event) => navigateToSection(event, "certificates")}
        >
          {copy.certificates}
        </a>
        <a
          className={activeSection === "projects" ? "active" : ""}
          href="#projects"
          onClick={(event) => navigateToSection(event, "projects")}
        >
          {copy.projects}
        </a>
        <div className="public-nav-menu" data-open={openMenu === "donation"}>
          <button
            className={
              activeSection === "dnd"
                ? "nav-menu-trigger active"
                : "nav-menu-trigger"
            }
            type="button"
            aria-expanded={openMenu === "donation"}
            aria-controls="donation-navigation"
            onClick={() => toggleMenu("donation")}
          >
            {copy.donation} <ChevronDown size={13} />
          </button>
          <div className="nav-menu-panel" id="donation-navigation">
            <a href="#dnd" onClick={(event) => navigateToSection(event, "dnd")}>
              <strong>Donor records</strong>
              <small>Relationships and stewardship</small>
            </a>
            <a href="#dnd" onClick={(event) => navigateToSection(event, "dnd")}>
              <strong>Donations and grants</strong>
              <small>Commitments and evidence</small>
            </a>
            <a
              href="#projects"
              onClick={(event) => navigateToSection(event, "projects")}
            >
              <strong>Impact reporting</strong>
              <small>Milestones and utilization</small>
            </a>
          </div>
        </div>
        <a
          className={activeSection === "contact" ? "active" : ""}
          href="#contact"
          onClick={(event) => navigateToSection(event, "contact")}
        >
          {copy.contact}
        </a>
        <div
          className="public-nav-menu more-menu"
          data-open={openMenu === "more"}
        >
          <button
            className={
              moreActive ? "nav-menu-trigger active" : "nav-menu-trigger"
            }
            type="button"
            aria-label={`${copy.more} navigation`}
            aria-expanded={openMenu === "more"}
            aria-controls="more-navigation"
            onClick={() => toggleMenu("more")}
          >
            <Ellipsis size={18} />
            <span className="more-label">{copy.more}</span>
          </button>
          <div className="nav-menu-panel" id="more-navigation">
            <a
              href="#plans"
              onClick={(event) => navigateToSection(event, "plans")}
            >
              <strong>Plans</strong>
              <small>Capacity for every team</small>
            </a>
            <a
              href="#admin"
              onClick={(event) => navigateToSection(event, "admin")}
            >
              <strong>Administration</strong>
              <small>Workspace governance</small>
            </a>
            <a href="#faq" onClick={(event) => navigateToSection(event, "faq")}>
              <strong>Common questions</strong>
              <small>Product scope and answers</small>
            </a>
            <Link href="/admin/login" onClick={closeNavigation}>
              <strong>Admin portal</strong>
              <small>Administrator sign in</small>
            </Link>
          </div>
        </div>
        <div className="mobile-nav-access">
          <div>
            <Globe2 size={15} />
            <span>
              <strong>{selectedLanguage.label}</strong>
              <small>English, हिन्दी, मराठी and ಕನ್ನಡ available</small>
            </span>
          </div>
          <Link href="/login" onClick={closeNavigation}>
            {copy.login} <ArrowUpRight size={14} />
          </Link>
          <a
            href="#support"
            onClick={(event) => navigateToSection(event, "support")}
          >
            {copy.support} <HandHeart size={14} />
          </a>
        </div>
      </nav>

      <div className="marketing-actions">
        <ThemeToggle variant="icon" />
        <div className="public-language" data-open={openMenu === "language"}>
          <button
            className="language-trigger"
            type="button"
            aria-label={`Choose language. Current language: ${selectedLanguage.label}`}
            title={`Language: ${selectedLanguage.label}`}
            aria-expanded={openMenu === "language"}
            aria-controls="language-options"
            onClick={() => toggleMenu("language")}
          >
            <Globe2 size={17} />
            <span className="language-current">{selectedLanguage.badge}</span>
          </button>
          <div className="language-panel" id="language-options">
            {languages.map((language) => (
              <button
                type="button"
                className={locale === language.id ? "active" : ""}
                aria-pressed={locale === language.id}
                onClick={() => chooseLanguage(language.id)}
                key={language.id}
              >
                <span>{language.badge}</span>
                {language.label}
                <small>{locale === language.id ? "Selected" : "Choose"}</small>
              </button>
            ))}
          </div>
        </div>
        <Link className="header-login-link" href="/login">
          {copy.login}
        </Link>
        <a
          className="marketing-support-button"
          href="#support"
          onClick={(event) => navigateToSection(event, "support")}
        >
          <HandHeart size={15} />
          {copy.support}
        </a>
        <button
          className="public-nav-toggle"
          type="button"
          aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={mobileOpen}
          onClick={() => {
            setMobileOpen((open) => !open);
            setOpenMenu(null);
          }}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>
      <div
        className={`language-notice${languageNotice ? " visible" : ""}`}
        role="status"
        aria-live="polite"
      >
        <Globe2 size={16} />
        {languageNotice}
      </div>
    </header>
  );
}
