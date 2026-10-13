import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router";
import { Icon, type IconName } from "./Icon";

type Theme = "system" | "light" | "dark";
const THEME_KEY = "lessongen.theme";

function readTheme(): Theme {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage may be unavailable (private mode) - the toggle still works for this visit */
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const icon: Record<Theme, IconName> = { system: "monitor", light: "sun", dark: "moon" };
  return (
    <button
      type="button"
      className="btn btn-ghost btn-sm"
      onClick={() => setTheme(next[theme])}
      aria-label={`Theme: ${theme}. Switch to ${next[theme]}`}
      title={`Theme: ${theme}`}
    >
      <Icon name={icon[theme]} />
      <span className="hint">{theme === "system" ? "Auto theme" : theme === "light" ? "Light" : "Dark"}</span>
    </button>
  );
}

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Studio", icon: "spark", end: true },
  { to: "/runs", label: "Runs", icon: "runs" },
  { to: "/lab", label: "Evaluator Lab", icon: "lab" },
  { to: "/memory", label: "Memory & Learning", icon: "brain" },
  { to: "/rubric", label: "Rubric", icon: "rubric" },
  { to: "/knowledge", label: "Knowledge", icon: "book" },
  { to: "/system", label: "System", icon: "server" },
];

export function Layout() {
  return (
    <div className="app">
      <aside className="sidebar">
        <NavLink to="/" className="brand" aria-label="Lesson Studio home">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="var(--accent)" />
            <path d="M9 9.5h9.5a4.5 4.5 0 0 1 4.5 4.5v8.5H13.5A4.5 4.5 0 0 1 9 18z" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinejoin="round" />
            <path d="m13 15.5 2.4 2.4 4.6-4.6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>
            <span className="brand-name">Lesson Studio</span>
            <br />
            <span className="brand-sub">Self-evaluating generator</span>
          </span>
        </NavLink>
        <nav className="nav" aria-label="Main">
          <div className="nav-section">Create</div>
          {NAV.slice(0, 3).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
          <div className="nav-section">Learn &amp; inspect</div>
          {NAV.slice(3).map((item) => (
            <NavLink key={item.to} to={item.to}>
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <ThemeToggle />
          <span className="hint muted" style={{ fontSize: "0.74rem" }}>
            Generate → evaluate → regenerate, until it ships.
          </span>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
