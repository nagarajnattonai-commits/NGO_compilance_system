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
import { useLocale, useTranslations } from "next-intl";
import { availableLocales, localeMetadata, isAppLocale, type AppLocale } from "@/i18n/config";
import { switchPublicLocale } from "@/i18n/public-preference";
import type { LocalizationSettings } from "@/lib/types";
import { BrandIdentity, useTenantBrand } from "@/branding/client";

type OpenMenu = "about" | "donation" | "more" | "language" | null;

export default function PublicNavigation({ localization }: { localization?: LocalizationSettings | null }) {
  const t = useTranslations("Marketing");
  const [changingLanguage, setChangingLanguage] = useState(false);
  const languages = availableLocales(localization?.locales);
  const brand = useTenantBrand();
  const requestLocale = useLocale();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<OpenMenu>(null);
  const [activeSection, setActiveSection] = useState("home");
  const locale = isAppLocale(requestLocale) ? requestLocale : "en-IN";
  const [languageNotice, setLanguageNotice] = useState("");
  const headerRef = useRef<HTMLElement>(null);
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectedLanguage =
    languages.find((language) => language.code === locale) ?? localeMetadata(locale);


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

  const chooseLanguage = async (nextLocale: AppLocale) => {
    if (changingLanguage) return;
    setChangingLanguage(true);
    try {
      await switchPublicLocale(nextLocale, localization);
      setOpenMenu(null);
      setLanguageNotice(t("navigation.selectionNotice", {language: localeMetadata(nextLocale).nativeLabel}));
      noticeTimerRef.current = setTimeout(() => window.location.reload(), 150);
    } catch {
      setChangingLanguage(false);
      setLanguageNotice(t("navigation.selectionFailed"));
    }
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
        aria-label={brand.product_name}
        onClick={closeNavigation}
      >
        {brand.enabled ? <BrandIdentity /> : <><span className="brand-mark">
          <ShieldCheck size={23} />
          <i />
        </span>
        <strong>
          Setu NGO<small>{t("complianceAndImpactManagement")}</small>
        </strong></>}
      </Link>

      {mobileOpen && (
        <button
          className="public-nav-backdrop"
          type="button"
          aria-label={t("navigation.closeNavigation")}
          onClick={closeNavigation}
        />
      )}

      <nav id="public-navigation" aria-label={t("navigation.publicNavigation")} data-open={mobileOpen}>
        <a
          className={activeSection === "home" ? "active" : ""}
          href="#home"
          onClick={(event) => navigateToSection(event, "home")}
        >
          {t("navigation.home")}
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
            {t("navigation.about")} <ChevronDown size={13} />
          </button>
          <div className="nav-menu-panel" id="about-navigation">
            <a
              href="#platform"
              onClick={(event) => navigateToSection(event, "platform")}
            >
              <strong>{t("navigation.aboutBrand", {brand: brand.brand_name})}</strong>
              <small>{t("navigation.provides")}</small>
            </a>
            <a
              href="#workflow"
              onClick={(event) => navigateToSection(event, "workflow")}
            >
              <strong>{t("navigation.howItWorks")}</strong>
              <small>{t("navigation.lifecycle")}</small>
            </a>
            <a
              href="#security"
              onClick={(event) => navigateToSection(event, "security")}
            >
              <strong>{t("navigation.security")}</strong>
              <small>{t("navigation.isolation")}</small>
            </a>
          </div>
        </div>
        <a
          className={activeSection === "certificates" ? "active" : ""}
          href="#certificates"
          onClick={(event) => navigateToSection(event, "certificates")}
        >
          {t("navigation.certificates")}
        </a>
        <a
          className={activeSection === "projects" ? "active" : ""}
          href="#projects"
          onClick={(event) => navigateToSection(event, "projects")}
        >
          {t("navigation.projects")}
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
            {t("navigation.donation")} <ChevronDown size={13} />
          </button>
          <div className="nav-menu-panel" id="donation-navigation">
            <a href="#dnd" onClick={(event) => navigateToSection(event, "dnd")}>
              <strong>{t("navigation.donors")}</strong>
              <small>{t("navigation.relationships")}</small>
            </a>
            <a href="#dnd" onClick={(event) => navigateToSection(event, "dnd")}>
              <strong>{t("navigation.grants")}</strong>
              <small>{t("navigation.commitments")}</small>
            </a>
            <a
              href="#projects"
              onClick={(event) => navigateToSection(event, "projects")}
            >
              <strong>{t("navigation.impact")}</strong>
              <small>{t("navigation.milestones")}</small>
            </a>
          </div>
        </div>
        <a
          className={activeSection === "contact" ? "active" : ""}
          href="#contact"
          onClick={(event) => navigateToSection(event, "contact")}
        >
          {t("navigation.contact")}
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
            aria-label={`${t("navigation.more")} navigation`}
            aria-expanded={openMenu === "more"}
            aria-controls="more-navigation"
            onClick={() => toggleMenu("more")}
          >
            <Ellipsis size={18} />
            <span className="more-label">{t("navigation.more")}</span>
          </button>
          <div className="nav-menu-panel" id="more-navigation">
            <a
              href="#plans"
              onClick={(event) => navigateToSection(event, "plans")}
            >
              <strong>{t("navigation.plans")}</strong>
              <small>{t("navigation.capacity")}</small>
            </a>
            <a
              href="#admin"
              onClick={(event) => navigateToSection(event, "admin")}
            >
              <strong>{t("navigation.administration")}</strong>
              <small>{t("navigation.governance")}</small>
            </a>
            <a href="#faq" onClick={(event) => navigateToSection(event, "faq")}>
              <strong>{t("navigation.questions")}</strong>
              <small>{t("navigation.answers")}</small>
            </a>
            <Link href="/admin/login" onClick={closeNavigation}>
              <strong>{t("navigation.adminPortal")}</strong>
              <small>{t("navigation.adminSignIn")}</small>
            </Link>
          </div>
        </div>
        <div className="mobile-nav-access">
          <button type="button" className="mobile-language-trigger" aria-label={t("navigation.chooseLanguage", {language: selectedLanguage.nativeLabel})} onClick={() => {setMobileOpen(false); setOpenMenu("language");}}>
            <Globe2 size={15} />
            <span>
              <strong>{selectedLanguage.nativeLabel}</strong>
              <small>{t("navigation.availableLanguages")}</small>
            </span>
          </button>
          <Link href="/login" onClick={closeNavigation}>
            {t("navigation.login")} <ArrowUpRight size={14} />
          </Link>
          <a
            href="#support"
            onClick={(event) => navigateToSection(event, "support")}
          >
            {t("navigation.support")} <HandHeart size={14} />
          </a>
        </div>
      </nav>

      <div className="marketing-actions">
        <ThemeToggle variant="icon" />
        <div className="public-language" data-open={openMenu === "language"}>
          <button
            className="language-trigger"
            type="button"
            aria-label={t("navigation.chooseLanguage", {language: selectedLanguage.nativeLabel})}
            title={t("navigation.chooseLanguage", {language: selectedLanguage.nativeLabel})}
            aria-expanded={openMenu === "language"}
            aria-controls="language-options"
            onClick={() => {
              setMobileOpen(false);
              toggleMenu("language");
            }}
          >
            <Globe2 size={17} />
            <span className="language-current">{selectedLanguage.language.toUpperCase()}</span>
          </button>
          <div className="language-panel" id="language-options">
            {languages.map((language) => (
              <button
                type="button"
                className={locale === language.code ? "active" : ""}
                aria-pressed={locale === language.code}
                disabled={changingLanguage}
                onClick={() => chooseLanguage(language.code)}
                key={language.code}
              >
                <span>{language.language.toUpperCase()}</span>
                {language.nativeLabel}
                <small>{locale === language.code ? t("navigation.selected") : t("navigation.choose")}</small>
              </button>
            ))}
          </div>
        </div>
        <Link className="header-login-link" href="/login">
          {t("navigation.login")}
        </Link>
        <a
          className="marketing-support-button"
          href="#support"
          onClick={(event) => navigateToSection(event, "support")}
        >
          <HandHeart size={15} />
          {t("navigation.support")}
        </a>
        <button
          className="public-nav-toggle"
          type="button"
          aria-label={mobileOpen ? t("navigation.closeNavigation") : t("navigation.openNavigation")}
          aria-controls="public-navigation"
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
