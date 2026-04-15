"use client";
import { createContext, useContext, useEffect, useState, useCallback } from "react";

type ThemePreference = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";

interface ThemeCtx {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setTheme: (t: ThemePreference) => void;
}

const Ctx = createContext<ThemeCtx>({
  preference: "system",
  resolved: "light",
  setTheme: () => {},
});

const STORAGE_KEY = "claude-code-theme";

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(resolved: ResolvedTheme) {
  const html = document.documentElement;
  if (resolved === "dark") html.classList.add("dark");
  else html.classList.remove("dark");
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreference] = useState<ThemePreference>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  // Init from localStorage
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as ThemePreference | null;
    const pref = stored ?? "system";
    setPreference(pref);
    const res = pref === "system" ? getSystemTheme() : pref;
    setResolved(res);
    applyTheme(res);
  }, []);

  // Watch system preference changes
  useEffect(() => {
    if (preference !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      const res: ResolvedTheme = e.matches ? "dark" : "light";
      setResolved(res);
      applyTheme(res);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [preference]);

  const setTheme = useCallback((t: ThemePreference) => {
    setPreference(t);
    localStorage.setItem(STORAGE_KEY, t);
    const res = t === "system" ? getSystemTheme() : t;
    setResolved(res);
    applyTheme(res);
  }, []);

  return <Ctx.Provider value={{ preference, resolved, setTheme }}>{children}</Ctx.Provider>;
}

export function useTheme() { return useContext(Ctx); }
