"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";

export default function ThemeToggle({ variant = "compact", className = "" }: { variant?: "compact" | "icon"; className?: string }) {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    setTheme(current);
    const syncTheme = () => setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    window.addEventListener("storage", syncTheme);
    window.addEventListener("setu-theme-change", syncTheme);
    return () => {
      window.removeEventListener("storage", syncTheme);
      window.removeEventListener("setu-theme-change", syncTheme);
    };
  }, []);

  function toggleTheme() {
    const current = theme ?? (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    const next: Theme = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("setu-theme", next);
    setTheme(next);
    window.dispatchEvent(new Event("setu-theme-change"));
  }

  const dark = theme === "dark";
  return (
    <button
      type="button"
      className={`theme-toggle theme-toggle-${variant} ${className}`.trim()}
      aria-label={`Switch to ${dark ? "light" : "dark"} mode`}
      aria-pressed={dark}
      title={`Switch to ${dark ? "light" : "dark"} mode`}
      onClick={toggleTheme}
    >
      <span className="theme-toggle-track" aria-hidden="true">
        <Sun size={14} />
        <Moon size={13} />
        <i />
      </span>
      {variant === "compact" && <span className="theme-toggle-copy"><small>DAY / NIGHT</small><strong>{theme ? (dark ? "Dark" : "Light") : "Theme"}</strong></span>}
    </button>
  );
}
