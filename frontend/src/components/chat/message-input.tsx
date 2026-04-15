"use client";

import { useState, useRef, useCallback, useEffect, KeyboardEvent } from "react";
import { CommandPopup, computePopupState } from "./command-popup";
import type { CommandDef } from "@/types";
import type { CommandPopupState } from "./command-popup";

interface MessageInputProps {
  onSend: (message: string) => void;
  /** Called when user sends a /command. Returns false if not handled. */
  onCommand?: (command: string, args: string[]) => void;
  /** Available slash commands for autocomplete. */
  commands?: CommandDef[];
  disabled?: boolean;
  onStop?: () => void;
  isStreaming?: boolean;
  /** True when Telegram holds the execution lock (shows different stop label) */
  telegramRunning?: boolean;
}

function SendIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="2" x2="6" y2="8" />
      <polygon points="12 2 8 12 6 8 2 6 12 2" fill="currentColor" stroke="none" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
      <rect x="2" y="2" width="8" height="8" rx="1" />
    </svg>
  );
}

/**
 * Parse a raw input string like "/session load abc123" into command + args.
 */
function parseCommand(input: string): { command: string; args: string[] } | null {
  if (!input.startsWith("/")) return null;
  const parts = input.slice(1).trim().split(/\s+/);
  if (parts.length === 0 || !parts[0]) return null;
  return { command: parts[0].toLowerCase(), args: parts.slice(1) };
}

export function MessageInput({
  onSend,
  onCommand,
  commands = [],
  disabled,
  onStop,
  isStreaming,
  telegramRunning,
}: MessageInputProps) {
  const [value, setValue] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Compute popup state from input
  const popupBase = computePopupState(value, commands);
  const popupState: CommandPopupState = {
    ...popupBase,
    selectedIndex: Math.min(selectedIndex, Math.max(0, popupBase.items.length - 1)),
  };

  const popupVisible = popupState.level !== "hidden" && popupState.items.length > 0;

  // Reset selection when items change
  useEffect(() => {
    setSelectedIndex(0);
  }, [popupBase.level, popupBase.items.length]);

  const handleSelect = useCallback((insertText: string) => {
    setValue(insertText);
    setSelectedIndex(0);
    // Focus textarea and place cursor at end
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) {
        el.focus();
        el.selectionStart = el.selectionEnd = insertText.length;
      }
    });
  }, []);

  const handleSend = useCallback(() => {
    const msg = value.trim();
    if (!msg || disabled) return;

    // Check if it's a slash command
    const parsed = parseCommand(msg);
    if (parsed && onCommand) {
      onCommand(parsed.command, parsed.args);
      setValue("");
      if (textareaRef.current) textareaRef.current.style.height = "auto";
      return;
    }

    onSend(msg);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [value, disabled, onSend, onCommand]);

  const handleKeyDown = (e: KeyboardEvent) => {
    // When popup is visible, handle navigation keys
    if (popupVisible) {
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(0, prev - 1));
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(popupState.items.length - 1, prev + 1));
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        const item = popupState.items[popupState.selectedIndex];
        if (item) handleSelect(item.insertText);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        // Clear the slash to dismiss popup
        setValue("");
        return;
      }
      // Enter on popup: if a command is fully formed, send it. Otherwise select.
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const item = popupState.items[popupState.selectedIndex];
        if (item) {
          // If this is a dispatcher, select it (insert into input to show subcommands)
          if (item.hasSubcommands) {
            handleSelect(item.insertText);
            return;
          }
          // If it's a subcommand or standalone, check if there are required args
          if (item.argsPlaceholder) {
            // Insert the command so user can type args
            handleSelect(item.insertText);
            return;
          }
          // No args needed — execute directly
          handleSelect(item.insertText);
          // Send after a tick so value is updated
          requestAnimationFrame(() => {
            const parsed = parseCommand(item.insertText.trim());
            if (parsed && onCommand) {
              onCommand(parsed.command, parsed.args);
              setValue("");
            }
          });
        }
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    const maxH = window.innerWidth < 768 ? 120 : 180;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, maxH) + "px";
  };

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div className="relative safe-bottom" style={{ backgroundColor: "var(--bg)" }}>
      {/* Gradient fade — replaces the hard border-top line */}
      <div
        className="absolute inset-x-0 top-0 h-8 pointer-events-none -translate-y-full"
        style={{ background: "linear-gradient(to bottom, transparent, var(--bg))" }}
      />

      <div className="max-w-2xl mx-auto px-3 pb-3 pt-1 md:px-5 md:pb-4 md:pt-1.5">
        {/* Popup + Input wrapper — popup anchored to this container */}
        <div ref={containerRef} className="relative">
          <CommandPopup state={popupState} onSelect={handleSelect} />

          <div className="flex items-end gap-1.5">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onInput={handleInput}
              placeholder={telegramRunning ? "Telegram running…" : "Type a message…"}
              disabled={disabled}
              rows={1}
              className="flex-1 resize-none bg-transparent text-[14px] leading-relaxed focus:outline-none disabled:opacity-40 placeholder:italic"
              style={{ color: "var(--text)", caretColor: "var(--accent)" }}
            />
            {(isStreaming || telegramRunning) ? (
              <button
                onClick={onStop}
                className="flex-shrink-0 p-2 rounded-full transition-colors mb-0.5"
                style={{ color: "var(--danger)" }}
                title={telegramRunning ? "Telegram-Ausführung stoppen" : "Stop"}
                aria-label={telegramRunning ? "Telegram-Ausführung stoppen" : "Antwort stoppen"}
              >
                <StopIcon />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!canSend}
                className="flex-shrink-0 p-2 rounded-full transition-all duration-200 mb-0.5"
                style={{
                  color: canSend ? "var(--bg)" : "var(--text-3)",
                  backgroundColor: canSend ? "var(--text)" : "transparent",
                  opacity: canSend ? 1 : 0.3,
                  transform: canSend ? "scale(1)" : "scale(0.85)",
                }}
                title="Senden (Enter)"
                aria-label="Senden"
              >
                <SendIcon />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
