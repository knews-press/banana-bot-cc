"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSessions } from "@/hooks/use-sessions";
import { ContextRing } from "@/components/ui/context-ring";
import { useAuth } from "@/hooks/use-auth";
import { useTheme } from "@/lib/theme";
import { Spinner } from "@/components/ui/spinner";
import { useBotStatus } from "@/hooks/use-bot-status";

/** Return display_name if available, otherwise first 12 chars of session ID. */
function shortName(displayName?: string, sessionId?: string): string {
  if (displayName) return displayName;
  return (sessionId ?? "").slice(0, 12);
}

interface SidebarProps {
  instance: string;
  /** Called when the user taps a nav link on mobile (closes the drawer). */
  onMobileClose?: () => void;
}

// ── Icons ────────────────────────────────────────────────────────────────────

function PlusIcon() {
  return <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><line x1="6.5" y1="1" x2="6.5" y2="12" /><line x1="1" y1="6.5" x2="12" y2="6.5" /></svg>;
}
function CollapseIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><rect x="1" y="1" width="13" height="13" rx="2" /><line x1="5" y1="1" x2="5" y2="14" /></svg>;
}
function CloseIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><line x1="2" y1="2" x2="13" y2="13" /><line x1="13" y1="2" x2="2" y2="13" /></svg>;
}
function TrashIcon() {
  return <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M1 2.5h9M3.5 2.5V1.5a1 1 0 011-1h1a1 1 0 011 1v1M4.5 5v3M6.5 5v3M2 2.5l.6 6a1 1 0 001 .9h3.8a1 1 0 001-.9l.6-6" /></svg>;
}
function ChatIcon() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 2h10a1 1 0 011 1v6a1 1 0 01-1 1H4.5L2 13V3a1 1 0 011-1z" /></svg>;
}
function MemoryIcon() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4.5 2.5H3a1 1 0 00-1 1v7a1 1 0 001 1h8a1 1 0 001-1v-7a1 1 0 00-1-1h-1.5" /><rect x="4.5" y="1" width="5" height="3" rx="0.75" /><line x1="3.5" y1="7" x2="10.5" y2="7" /><line x1="3.5" y1="9.5" x2="7.5" y2="9.5" /></svg>;
}
function FolderIcon() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M1 4a1 1 0 011-1h3l1.5 2H12a1 1 0 011 1v5a1 1 0 01-1 1H2a1 1 0 01-1-1V4z" /></svg>;
}
function GearIcon() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="7" cy="7" r="2" /><path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.5 2.5l1.06 1.06M10.44 10.44l1.06 1.06M2.5 11.5l1.06-1.06M10.44 3.56l1.06-1.06" /></svg>;
}
function SunIcon() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="7" cy="7" r="2.5" /><line x1="7" y1="1" x2="7" y2="2.5" /><line x1="7" y1="11.5" x2="7" y2="13" /><line x1="1" y1="7" x2="2.5" y2="7" /><line x1="11.5" y1="7" x2="13" y2="7" /><line x1="2.93" y1="2.93" x2="3.99" y2="3.99" /><line x1="10.01" y1="10.01" x2="11.07" y2="11.07" /><line x1="11.07" y1="2.93" x2="10.01" y2="3.99" /><line x1="3.99" y1="10.01" x2="2.93" y2="11.07" /></svg>;
}
function MoonIcon() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M11.5 9A5.5 5.5 0 015 2.5a5.5 5.5 0 100 9 5.5 5.5 0 006.5-2.5z" /></svg>;
}
function AutoIcon() {
  return <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="7" cy="7" r="5.5" /><path d="M7 1.5v11M4 4l3 3-3 3" /></svg>;
}

// ── NavItem ──────────────────────────────────────────────────────────────────

function NavItem({ href, icon, label, active, onClick }: {
  href: string; icon: React.ReactNode; label: string; active: boolean;
  onClick?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-[13px] transition-colors"
      style={{
        color: active ? "var(--text)" : "var(--text-2)",
        backgroundColor: active ? "var(--bg-subtle)" : "transparent",
        fontWeight: active ? 500 : 400,
        // Ensure touch-friendly height without visual bloat
        minHeight: "40px",
      }}
      onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text)"; }}
      onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text-2)"; }}
    >
      <span className="flex-shrink-0 opacity-70">{icon}</span>
      {label}
    </Link>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────────────────

export function Sidebar({ instance, onMobileClose }: SidebarProps) {
  const { sessions, isLoading, deleteSession } = useSessions(instance);
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const { preference, setTheme } = useTheme();
  const { claudeReady } = useBotStatus(instance);

  const isActive = (path: string) => pathname === `/${instance}${path}`;

  const cycleTheme = () => {
    const next = preference === "light" ? "dark" : preference === "dark" ? "system" : "light";
    setTheme(next);
  };
  const ThemeIcon = preference === "dark" ? MoonIcon : preference === "light" ? SunIcon : AutoIcon;
  const themeLabel = preference === "dark" ? "Dark" : preference === "light" ? "Light" : "Auto";

  // ── Collapsed (desktop only, on mobile onMobileClose is used instead) ─────
  if (collapsed) {
    return (
      <div
        className="w-10 flex flex-col items-center pt-3 gap-3 flex-shrink-0 h-full"
        style={{ borderRight: "1px solid var(--border)", backgroundColor: "var(--bg)" }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="p-1.5 rounded-md transition-colors"
          style={{ color: "var(--text-3)" }}
          title="Open sidebar"
        >
          <CollapseIcon />
        </button>
      </div>
    );
  }

  return (
    <div
      className="w-64 md:w-56 flex flex-col flex-shrink-0 h-full"
      style={{ borderRight: "1px solid var(--border)", backgroundColor: "var(--bg)" }}
    >
      {/* Header */}
      <div
        className="h-12 px-3.5 flex items-center justify-between flex-shrink-0"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <Link
          href={`/${instance}`}
          onClick={onMobileClose}
          className="flex items-center gap-2"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/icon.png" alt="logo" width={22} height={22} style={{ imageRendering: "pixelated", flexShrink: 0 }} />
          <span className="text-[13px] font-semibold tracking-tight flex items-center gap-1.5" style={{ color: "var(--text)" }}>
            {instance}
            {!claudeReady && (
              <span
                title="Claude not logged in"
                style={{
                  display: "inline-block",
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  backgroundColor: "var(--danger, #e05252)",
                  flexShrink: 0,
                }}
              />
            )}
          </span>
        </Link>

        <div className="flex items-center gap-1">
          {/* Desktop: collapse to icon strip */}
          <button
            onClick={() => setCollapsed(true)}
            className="hidden md:flex p-1 rounded-md transition-colors"
            style={{ color: "var(--text-3)" }}
            title="Close sidebar"
          >
            <CollapseIcon />
          </button>
          {/* Mobile: close drawer */}
          <button
            onClick={onMobileClose}
            className="flex md:hidden p-1 rounded-md transition-colors"
            style={{ color: "var(--text-3)" }}
            aria-label="Close menu"
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      {/* Navigation */}
      <nav className="px-3 pt-2 pb-1 space-y-0.5 flex-shrink-0">
        <NavItem
          href={`/${instance}/chat`}
          icon={<ChatIcon />}
          label="Chat"
          active={pathname.startsWith(`/${instance}/chat`)}
          onClick={onMobileClose}
        />
        <NavItem
          href={`/${instance}/memories`}
          icon={<MemoryIcon />}
          label="Memories"
          active={isActive("/memories")}
          onClick={onMobileClose}
        />
        <NavItem
          href={`/${instance}/files`}
          icon={<FolderIcon />}
          label="Dateien"
          active={pathname.startsWith(`/${instance}/files`)}
          onClick={onMobileClose}
        />
        <NavItem
          href={`/${instance}/settings`}
          icon={<GearIcon />}
          label="Settings"
          active={pathname.startsWith(`/${instance}/settings`)}
          onClick={onMobileClose}
        />
      </nav>

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto px-3 pb-2 min-h-0">
        <p
          className="text-[10px] font-medium px-2 pt-1 pb-1.5 uppercase tracking-widest"
          style={{ color: "var(--text-3)" }}
        >
          Letzte Sessions
        </p>
        {isLoading ? (
          <div className="flex justify-center py-4">
            <Spinner className="h-3.5 w-3.5" />
          </div>
        ) : sessions.length === 0 ? (
          <p className="text-[12px] px-2 py-1" style={{ color: "var(--text-3)" }}>Keine Sessions.</p>
        ) : (
          <div className="space-y-px">
            {sessions.map((s) => {
              const active = pathname.includes(s.session_id);
              return (
                <div
                  key={s.session_id}
                  className="group relative flex items-center rounded-md"
                  style={{
                    backgroundColor: active ? "var(--bg-subtle)" : "transparent",
                    borderLeft: active ? "2px solid var(--accent)" : "2px solid transparent",
                  }}
                >
                  <Link
                    href={`/${instance}/chat/${s.session_id}`}
                    onClick={onMobileClose}
                    className="flex-1 px-2 py-2 min-w-0"
                  >
                    <p
                      className="text-[12px] font-mono truncate"
                      style={{ color: active ? "var(--text)" : "var(--text-2)", fontWeight: active ? 500 : 400 }}
                    >
                      {shortName(s.display_name, s.session_id)}
                    </p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <p className="text-[11px]" style={{ color: "var(--text-3)" }}>
                        {s.total_turns}t · ${s.total_cost.toFixed(2)}
                      </p>
                      {(s.context_tokens ?? 0) > 0 && (
                        <ContextRing tokens={s.context_tokens!} maxTokens={s.context_max_tokens || 200_000} size={12} />
                      )}
                      {(s.compact_count ?? 0) > 0 && (
                        <span className="text-[10px]" style={{ color: "var(--text-3)" }} title={`${s.compact_count}× kompaktiert`}>
                          {s.compact_count}×
                        </span>
                      )}
                      {s.running_channel === "telegram" && (
                        <span
                          className="telegram-marker-active"
                          style={{
                            color: "#2AABEE",
                            fontSize: "10px",
                            fontWeight: 700,
                            lineHeight: 1,
                            flexShrink: 0,
                          }}
                          title="Läuft gerade auf Telegram"
                        >
                          T
                        </span>
                      )}
                    </div>
                  </Link>
                  <button
                    onClick={() => deleteSession(s.session_id)}
                    className="opacity-0 group-hover:opacity-100 p-2 mr-1 rounded transition-all"
                    style={{ color: "var(--text-3)" }}
                    title="Delete"
                    onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--danger)"}
                    onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-3)"}
                  >
                    <TrashIcon />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* New Chat button */}
      <div className="px-3 pt-2 pb-2 flex-shrink-0">
        <Link
          href={`/${instance}/chat?new=1`}
          onClick={onMobileClose}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[13px] transition-colors w-full"
          style={{ color: "var(--text-2)", minHeight: "40px" }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.color = "var(--text)";
            (e.currentTarget as HTMLElement).style.backgroundColor = "var(--bg-subtle)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.color = "var(--text-2)";
            (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
          }}
        >
          <PlusIcon />
          Neuer Chat
        </Link>
      </div>

      {/* Footer */}
      <div
        className="px-3.5 py-2.5 flex-shrink-0 safe-bottom"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        {user && (
          <div className="flex items-center gap-2 min-w-0 mb-1.5">
            <div
              className="w-5 h-5 rounded flex-shrink-0 flex items-center justify-center text-[9px] font-bold uppercase"
              style={{ backgroundColor: "var(--bg-muted)", color: "var(--text-2)" }}
            >
              {(user.display_name || user.email || "?")[0]}
            </div>
            <span className="text-[12px] truncate" style={{ color: "var(--text-2)" }}>
              {user.display_name || user.email}
            </span>
          </div>
        )}

        <div className="flex items-center justify-between">
          <button
            onClick={cycleTheme}
            className="flex items-center gap-1.5 text-[11px] transition-colors py-1"
            style={{ color: "var(--text-3)" }}
            title={`Theme: ${themeLabel} — klicken zum Wechseln`}
            onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-2)"}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-3)"}
          >
            <ThemeIcon />
            <span>{themeLabel}</span>
          </button>

          {user && (
            <button
              onClick={logout}
              className="text-[11px] transition-colors py-1 px-1"
              style={{ color: "var(--text-3)" }}
              onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = "var(--danger)"}
              onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = "var(--text-3)"}
            >
              Abmelden
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
