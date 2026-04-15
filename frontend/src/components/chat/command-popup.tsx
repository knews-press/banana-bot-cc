"use client";

import { useMemo } from "react";
import type { CommandDef, SubcommandDef } from "@/types";

export type PopupLevel = "hidden" | "level1" | "level2";

export interface CommandPopupState {
  level: PopupLevel;
  /** The matched parent command (only set in level2). */
  parentCommand: CommandDef | null;
  /** Filtered items to display. */
  items: PopupItem[];
  /** Index of the highlighted item. */
  selectedIndex: number;
}

export interface PopupItem {
  /** Display label — "new", "session", "list", "load" etc. */
  label: string;
  /** Icon (only level1). */
  icon?: string;
  /** Description text. */
  description: string;
  /** Args placeholder (only subcommands). */
  argsPlaceholder?: string | null;
  /** Full text to insert into the input when selected. */
  insertText: string;
  /** True if this item is a dispatcher (has subcommands) → selecting opens level2. */
  hasSubcommands?: boolean;
}

/**
 * Compute popup state from the current input value and the command registry.
 */
export function computePopupState(
  inputValue: string,
  commands: CommandDef[],
): Omit<CommandPopupState, "selectedIndex"> {
  // Only trigger when input starts with "/"
  if (!inputValue.startsWith("/")) {
    return { level: "hidden", parentCommand: null, items: [] };
  }

  const raw = inputValue.slice(1); // remove leading "/"
  const parts = raw.split(/\s+/);
  const cmdPart = parts[0]?.toLowerCase() ?? "";

  // Check if user typed a known command + space → level 2
  const exactMatch = commands.find((c) => c.name === cmdPart);
  if (exactMatch && exactMatch.subcommands.length > 0 && raw.includes(" ")) {
    const subFilter = parts[1]?.toLowerCase() ?? "";
    const filtered = exactMatch.subcommands.filter((s) =>
      s.name.toLowerCase().startsWith(subFilter)
    );

    // If the subcommand is already fully typed (and there are more args), hide popup
    const exactSub = exactMatch.subcommands.find((s) => s.name === subFilter);
    if (exactSub && parts.length > 2) {
      return { level: "hidden", parentCommand: null, items: [] };
    }

    const items: PopupItem[] = filtered.map((s) => ({
      label: s.name,
      description: s.description,
      argsPlaceholder: s.args_placeholder,
      insertText: `/${exactMatch.name} ${s.name} `,
    }));

    return { level: "level2", parentCommand: exactMatch, items };
  }

  // Level 1: filter commands by what's typed
  const filtered = commands.filter((c) =>
    c.name.startsWith(cmdPart)
  );

  // If user already typed a full command that's standalone (no subcommands), hide popup
  if (exactMatch && exactMatch.subcommands.length === 0 && parts.length >= 1 && raw.includes(" ")) {
    return { level: "hidden", parentCommand: null, items: [] };
  }

  const items: PopupItem[] = filtered.map((c) => ({
    label: c.name,
    icon: c.icon,
    description: c.description,
    insertText: c.subcommands.length > 0 ? `/${c.name} ` : `/${c.name}`,
    hasSubcommands: c.subcommands.length > 0,
  }));

  return { level: "level1", parentCommand: null, items };
}

/**
 * Floating autocomplete popup, positioned above the input.
 */
export function CommandPopup({
  state,
  onSelect,
}: {
  state: CommandPopupState;
  onSelect: (insertText: string) => void;
}) {
  if (state.level === "hidden" || state.items.length === 0) return null;

  return (
    <div
      className="absolute bottom-full left-0 right-0 mb-1 z-50"
      style={{ maxHeight: 280, overflowY: "auto" }}
    >
      <div
        className="rounded-md overflow-hidden text-[13px] shadow-lg"
        style={{
          backgroundColor: "var(--bg-elevated)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Level 2 header */}
        {state.level === "level2" && state.parentCommand && (
          <div
            className="px-3 py-1.5 text-[11px] font-medium"
            style={{
              backgroundColor: "var(--bg-subtle)",
              color: "var(--text-3)",
              borderBottom: "1px solid var(--border)",
            }}
          >
            {state.parentCommand.icon} /{state.parentCommand.name}
          </div>
        )}

        {state.items.map((item, i) => {
          const isSelected = i === state.selectedIndex;
          return (
            <button
              key={item.label}
              className="w-full text-left px-3 py-2 flex items-center gap-2.5 transition-colors"
              style={{
                backgroundColor: isSelected ? "var(--bg-muted)" : "transparent",
                color: "var(--text)",
              }}
              onMouseDown={(e) => {
                // mouseDown instead of click to fire before textarea blur
                e.preventDefault();
                onSelect(item.insertText);
              }}
            >
              {/* Icon (level 1 only) */}
              {item.icon && (
                <span className="w-5 text-center flex-shrink-0">{item.icon}</span>
              )}

              {/* Command/subcommand name */}
              <span className="font-mono font-medium" style={{ color: "var(--success)" }}>
                {state.level === "level1" ? "/" : ""}{item.label}
              </span>

              {/* Args placeholder */}
              {item.argsPlaceholder && (
                <span className="font-mono" style={{ color: "var(--text-3)" }}>
                  {item.argsPlaceholder}
                </span>
              )}

              {/* Description */}
              <span className="flex-1 text-right truncate" style={{ color: "var(--text-3)" }}>
                {item.description}
              </span>

              {/* Chevron for dispatchers */}
              {item.hasSubcommands && (
                <span style={{ color: "var(--text-3)", fontSize: 10 }}>▸</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
