"use client";

import { useState, useEffect } from "react";

interface TerminalErrorProps {
  command: string;
  errorText: string;
  /** Show a "retry" button that reloads the page */
  showRetry?: boolean;
}

interface Line {
  text: string;
  color: "prompt" | "muted" | "danger";
}

export function TerminalError({ command, errorText, showRetry }: TerminalErrorProps) {
  const [lines, setLines] = useState<Line[]>([]);
  const [phase, setPhase] = useState<"typing" | "searching" | "done">("typing");
  const [typed, setTyped] = useState("");
  const [dots, setDots] = useState("");

  // Phase 1: Typewriter for the command
  useEffect(() => {
    const full = `$ ${command}`;
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setTyped(full.slice(0, i));
      if (i >= full.length) {
        clearInterval(interval);
        setTimeout(() => setPhase("searching"), 150);
      }
    }, 25);
    return () => clearInterval(interval);
  }, [command]);

  // Phase 2: Animated dots
  useEffect(() => {
    if (phase !== "searching") return;
    setLines([{ text: `$ ${command}`, color: "prompt" }]);
    setTyped("");

    let count = 0;
    const interval = setInterval(() => {
      count++;
      setDots(".".repeat(count));
      if (count >= 10) {
        clearInterval(interval);
        setTimeout(() => setPhase("done"), 300);
      }
    }, 80);
    return () => clearInterval(interval);
  }, [phase, command]);

  // Phase 3: Show error
  useEffect(() => {
    if (phase !== "done") return;
    setDots("");
    setLines([
      { text: `$ ${command}`, color: "prompt" },
      { text: `searching .......... `, color: "muted" },
      { text: "", color: "muted" },
      { text: errorText, color: "danger" },
    ]);
  }, [phase, command, errorText]);

  const colorMap = {
    prompt: "var(--success)",
    muted: "var(--text-3)",
    danger: "var(--danger)",
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ backgroundColor: "var(--bg)" }}
    >
      <div
        className="w-full max-w-xl font-mono text-sm leading-relaxed"
        style={{ color: "var(--success)", padding: "2rem 0" }}
      >
        {/* Committed lines */}
        {lines.map((line, i) => (
          <div
            key={i}
            style={{ color: colorMap[line.color], whiteSpace: "pre-wrap" }}
          >
            {line.text || "\u00A0"}
          </div>
        ))}

        {/* Typewriter phase */}
        {phase === "typing" && (
          <div style={{ color: "var(--success)", whiteSpace: "pre" }}>
            {typed}
            <span className="terminal-error-cursor" />
          </div>
        )}

        {/* Searching phase */}
        {phase === "searching" && (
          <div style={{ color: "var(--text-3)", whiteSpace: "pre" }}>
            searching {dots}
          </div>
        )}

        {/* Final cursor */}
        {phase === "done" && (
          <>
            <div style={{ whiteSpace: "pre", marginTop: "0.25rem" }}>
              <span style={{ color: "var(--success)" }}>$ </span>
              <span className="terminal-error-cursor" />
            </div>
            {showRetry && (
              <div style={{ marginTop: "1.5rem" }}>
                <button
                  onClick={() => window.location.reload()}
                  className="text-xs underline"
                  style={{ color: "var(--text-3)", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit" }}
                >
                  retry
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <style jsx global>{`
        .terminal-error-cursor {
          display: inline-block;
          width: 0.6em;
          height: 1.15em;
          background-color: var(--success);
          animation: terminal-error-blink 1s step-end infinite;
          vertical-align: text-bottom;
        }
        @keyframes terminal-error-blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    </div>
  );
}
