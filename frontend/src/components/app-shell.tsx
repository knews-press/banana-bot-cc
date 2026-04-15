"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { Sidebar } from "@/components/sidebar/sidebar";
import { useBotStatus } from "@/hooks/use-bot-status";

function HamburgerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <line x1="2" y1="4.5" x2="16" y2="4.5" />
      <line x1="2" y1="9"   x2="16" y2="9"   />
      <line x1="2" y1="13.5" x2="16" y2="13.5" />
    </svg>
  );
}

function ComposeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 2l3 3-7 7H4v-3l7-7z" />
      <line x1="1" y1="14" x2="15" y2="14" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 1L13 13H1L7 1z" />
      <line x1="7" y1="6" x2="7" y2="8.5" />
      <circle cx="7" cy="10.5" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function AuthWarningBanner({ instance }: { instance: string }) {
  const [dismissed, setDismissed] = useState(false);
  const { claudeReady, isLoading } = useBotStatus(instance);

  if (isLoading || claudeReady || dismissed) return null;

  return (
    <div
      className="flex items-center gap-2.5 px-4 py-2.5 text-[12px] flex-shrink-0"
      style={{
        backgroundColor: "var(--warning-bg, #7c4a0020)",
        borderBottom: "1px solid var(--warning-border, #c8830044)",
        color: "var(--warning-text, #c07020)",
      }}
    >
      <span className="flex-shrink-0"><WarningIcon /></span>
      <span className="flex-1">
        <strong>Claude nicht eingeloggt.</strong>{" "}
        Schreib dem Bot auf Telegram — er schickt dir einen Login-Link.
      </span>
      <button
        onClick={() => setDismissed(true)}
        className="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity px-1"
        aria-label="Schließen"
        style={{ color: "inherit" }}
      >
        ✕
      </button>
    </div>
  );
}

export function AppShell({
  instance,
  children,
}: {
  instance: string;
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  // Close drawer on every navigation
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Lock body scroll while drawer is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  return (
    <div className="flex h-dvh overflow-hidden" style={{ backgroundColor: "var(--bg)" }}>

      {/* ── Mobile backdrop ── */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 md:hidden"
          style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      {/* Desktop: always visible in flow | Mobile: fixed drawer, z-50 */}
      <div
        className={[
          "fixed inset-y-0 left-0 z-50",          // mobile: fixed overlay
          "md:relative md:inset-auto md:z-auto",   // desktop: back in flow
          mobileOpen ? "flex" : "hidden md:flex",  // show/hide on mobile
        ].join(" ")}
      >
        <Sidebar instance={instance} onMobileClose={() => setMobileOpen(false)} />
      </div>

      {/* ── Main area ───────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* Mobile top bar – only visible below md breakpoint */}
        <div
          className="md:hidden flex items-center h-12 px-3 flex-shrink-0 safe-top"
          style={{ borderBottom: "1px solid var(--border)", backgroundColor: "var(--bg)" }}
        >
          {/* Left: hamburger + instance name */}
          <button
            onClick={() => setMobileOpen(true)}
            className="p-2 -ml-1 rounded-md touch-compact"
            style={{ color: "var(--text-2)" }}
            aria-label="Open menu"
          >
            <HamburgerIcon />
          </button>
          <span
            className="ml-1.5 text-[13px] font-semibold tracking-tight flex-1"
            style={{ color: "var(--text)" }}
          >
            {instance}
          </span>
          {/* Right: new chat button */}
          <Link
            href={`/${instance}/chat?new=1`}
            className="p-2 -mr-1 rounded-md touch-compact"
            style={{ color: "var(--text-2)" }}
            aria-label="Neuer Chat"
          >
            <ComposeIcon />
          </Link>
        </div>

        {/* Auth warning banner */}
        <AuthWarningBanner instance={instance} />

        {/* Page content */}
        <main className="flex-1 flex flex-col overflow-hidden min-w-0">
          {children}
        </main>
      </div>
    </div>
  );
}
