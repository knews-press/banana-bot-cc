"use client";

import { useParams } from "next/navigation";
import { useState, useRef, useEffect, useCallback } from "react";

interface TermLine {
  type: "prompt" | "input" | "output" | "processing" | "boot";
  text: string;
}

/* ── Boot sequence ──────────────────────────────────────────────────────── */

function bootLines(instance: string): { text: string; delay: number }[] {
  return [
    { text: "BIOS v2.4.1 ... ok", delay: 200 },
    { text: "Loading banana-os kernel .......... done", delay: 400 },
    { text: "Mounting /dev/sda1 ... ok", delay: 250 },
    { text: "Starting network services ... ok", delay: 300 },
    { text: `Initializing ${instance} runtime ... ok`, delay: 350 },
    { text: "", delay: 150 },
    { text: `banana-os v1.0 (${instance})`, delay: 100 },
    { text: `Last login: ${new Date().toLocaleDateString("de-DE")} on tty1`, delay: 100 },
    { text: "", delay: 200 },
  ];
}

/* ── Easter egg system ──────────────────────────────────────────────────── */

// Exact-match commands
const EXACT_COMMANDS: Record<string, string | null> = {
  whoami: "Das wüsstest du wohl gerne.",
  pwd: "/dev/null",
  exit: "Es gibt kein Entkommen.",
  quit: "Es gibt kein Entkommen.",
  logout: "Es gibt kein Entkommen.",
  q: "Es gibt kein Entkommen.",
  hello: "Hey.",
  hi: "Hey.",
  hey: "Hey.",
  hallo: "Hey.",
  ping: "Pong.",
  cat: "Miau.",
  login: "Du bist bereits hier.",
  id: "uid=0(nobody) gid=0(nobody)",
  history: "Keine History verfügbar.",
  clear: null, // handled specially
};

// Prefix-match commands (first word)
const PREFIX_COMMANDS: Record<string, string> = {
  help: "Keine Hilfe verfügbar.",
  man: "Keine Hilfe verfügbar.",
  "--help": "Keine Hilfe verfügbar.",
  "-h": "Keine Hilfe verfügbar.",
  ls: "Permission denied.",
  dir: "Permission denied.",
  ll: "Permission denied.",
  cd: "Wohin willst du?",
  sudo: "Nice try.",
  su: "Nice try.",
  doas: "Nice try.",
  rm: "Netter Versuch.",
  ssh: "Connection refused.",
  curl: "Kein Internetzugang.",
  wget: "Kein Internetzugang.",
  passwd: "Zugriff verweigert.",
  password: "Zugriff verweigert.",
  vim: "Kein Editor verfügbar.",
  nano: "Kein Editor verfügbar.",
  vi: "Kein Editor verfügbar.",
  emacs: "Kein Editor verfügbar.",
  reboot: "Nein.",
  shutdown: "Nein.",
  poweroff: "Nein.",
  ping: "Pong.",
  cat: "Permission denied.",
};

function getPageLoadTime() {
  return Date.now();
}

/* ── Typewriter hook ────────────────────────────────────────────────────── */

function useTypewriter(text: string, speed = 30, enabled = false) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setDisplayed("");
      setDone(false);
      return;
    }
    setDisplayed("");
    setDone(false);
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(interval);
        setDone(true);
      }
    }, speed);
    return () => clearInterval(interval);
  }, [text, speed, enabled]);

  return { displayed, done };
}

/* ── Component ──────────────────────────────────────────────────────────── */

export default function LoginPage() {
  const { instance } = useParams<{ instance: string }>();
  const [input, setInput] = useState("");
  const [lines, setLines] = useState<TermLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [responseText, setResponseText] = useState("");
  const [showResponse, setShowResponse] = useState(false);
  const [booting, setBooting] = useState(true);
  const [pageLoadedAt] = useState(getPageLoadTime);
  const inputRef = useRef<HTMLInputElement>(null);
  const termRef = useRef<HTMLDivElement>(null);

  const prompt = `${instance}:~ $ `;

  // ── Boot sequence ──
  useEffect(() => {
    const steps = bootLines(instance ?? "system");
    let timeout: ReturnType<typeof setTimeout>;
    let totalDelay = 0;

    steps.forEach((step, i) => {
      totalDelay += step.delay;
      timeout = setTimeout(() => {
        setLines((prev) => [...prev, { type: "boot", text: step.text }]);
        if (i === steps.length - 1) {
          setTimeout(() => setBooting(false), 300);
        }
      }, totalDelay);
    });

    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    if (termRef.current) {
      termRef.current.scrollTop = termRef.current.scrollHeight;
    }
  }, [lines, responseText, showResponse]);

  // Auto-focus input
  useEffect(() => {
    if (!booting) inputRef.current?.focus();
  }, [loading, booting]);

  const { displayed: typedResponse, done: typingDone } = useTypewriter(
    responseText,
    25,
    showResponse,
  );

  // When typing is done, commit the line and reset for next input
  useEffect(() => {
    if (typingDone && responseText) {
      setLines((prev) => [...prev, { type: "output", text: responseText }]);
      setResponseText("");
      setShowResponse(false);
      setLoading(false);
    }
  }, [typingDone, responseText]);

  const addResponse = useCallback((text: string) => {
    setResponseText(text);
    setShowResponse(true);
  }, []);

  // ── Process input ──
  const processCommand = useCallback(
    (trimmed: string): { response?: string; action?: string } => {
      const lower = trimmed.toLowerCase();
      const firstWord = lower.split(/\s+/)[0];
      const hasArgs = trimmed.includes(" ");
      const restArgs = trimmed.slice(trimmed.indexOf(" ") + 1);

      // 1. Email detection (contains @)
      if (trimmed.includes("@")) {
        return { action: "login-email" };
      }

      // 2. Telegram ID (only digits, 5+)
      if (/^\d{5,}$/.test(trimmed)) {
        return { action: "login-telegram" };
      }

      // 3. Special: clear
      if (lower === "clear") {
        return { action: "clear" };
      }

      // 4. Special: echo
      if (firstWord === "echo") {
        return { response: hasArgs ? restArgs : "" };
      }

      // 5. Special: date
      if (lower === "date") {
        return {
          response: new Date().toLocaleString("de-DE", {
            weekday: "short",
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
        };
      }

      // 6. Special: uptime
      if (lower === "uptime") {
        const mins = Math.floor((Date.now() - pageLoadedAt) / 60000);
        return { response: `up ${mins} min` };
      }

      // 7. Special: uname
      if (firstWord === "uname") {
        return { response: `banana-os 1.0 ${instance} aarch64` };
      }

      // 8. Exact matches (only if no args, except for known exact-only cmds)
      if (!hasArgs && lower in EXACT_COMMANDS) {
        const result = EXACT_COMMANDS[lower];
        if (result === null) return { action: lower };
        return { response: `> ${result}` };
      }

      // 9. cat special case: exact "cat" → Miau, "cat <file>" → Permission denied
      if (firstWord === "cat" && hasArgs) {
        return { response: "> Permission denied." };
      }

      // 10. Prefix matches
      if (firstWord in PREFIX_COMMANDS) {
        return { response: `> ${PREFIX_COMMANDS[firstWord]}` };
      }

      // 11. Fallback
      return { response: `> ${firstWord}: command not found` };
    },
    [instance, pageLoadedAt],
  );

  const handleSubmit = useCallback(async () => {
    const trimmed = input.trim();
    setLines((prev) => [...prev, { type: "input", text: `${prompt}${trimmed}` }]);
    setInput("");

    if (!trimmed) return;

    const result = processCommand(trimmed);

    // Handle actions
    if (result.action === "clear") {
      setLines([]);
      return;
    }

    if (result.action === "login-email" || result.action === "login-telegram") {
      setLoading(true);
      setLines((prev) => [...prev, { type: "processing", text: "Verarbeite Anfrage..." }]);

      try {
        const body =
          result.action === "login-email"
            ? { email: trimmed, instance }
            : { telegram_id: trimmed, instance };

        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (res.ok) {
          addResponse("> Mal schauen, was passiert.");
        } else {
          addResponse("> Unknown command.");
        }
      } catch {
        addResponse("> Verbindungsfehler. Versuch es nochmal.");
      }
      return;
    }

    // Regular response (easter egg / fallback)
    if (result.response !== undefined) {
      addResponse(result.response);
    }
  }, [input, instance, prompt, addResponse, processCommand]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !loading) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      onClick={() => inputRef.current?.focus()}
      style={{ backgroundColor: "var(--bg)", cursor: "text" }}
    >
      <div
        ref={termRef}
        className="w-full max-w-xl font-mono text-sm leading-relaxed overflow-auto"
        style={{
          color: "var(--success)",
          maxHeight: "80vh",
          padding: "2rem 0",
        }}
      >
        {/* History lines */}
        {lines.map((line, i) => (
          <div
            key={i}
            style={{
              color:
                line.type === "boot"
                  ? "var(--text-3)"
                  : line.type === "output"
                    ? "var(--text-2)"
                    : line.type === "processing"
                      ? "var(--text-3)"
                      : "var(--success)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {line.text || "\u00A0"}
          </div>
        ))}

        {/* Typewriter response */}
        {showResponse && (
          <div style={{ color: "var(--text-2)", whiteSpace: "pre-wrap" }}>
            {typedResponse}
            <span className="terminal-cursor" />
          </div>
        )}

        {/* Active input line */}
        {!loading && !showResponse && !booting && (
          <div style={{ display: "flex", whiteSpace: "pre" }}>
            <span>{prompt}</span>
            <div style={{ position: "relative", flex: 1 }}>
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                autoFocus
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                className="terminal-input"
                style={{
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: "var(--success)",
                  font: "inherit",
                  width: "100%",
                  padding: 0,
                  margin: 0,
                  caretColor: "transparent",
                }}
              />
              {/* Custom block cursor */}
              <span
                className="terminal-cursor"
                style={{
                  position: "absolute",
                  left: `${input.length}ch`,
                  top: 0,
                }}
              />
            </div>
          </div>
        )}
      </div>

      <style jsx global>{`
        .terminal-cursor {
          display: inline-block;
          width: 0.6em;
          height: 1.15em;
          background-color: var(--success);
          animation: blink 1s step-end infinite;
          vertical-align: text-bottom;
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        .terminal-input::selection {
          background: color-mix(in srgb, var(--success) 30%, transparent);
        }
      `}</style>
    </div>
  );
}
