"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";

export default function AuthCallbackPage() {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const instance = params.instance as string;
  const token = searchParams.get("token");

  const [lines, setLines] = useState<string[]>([
    `banana-os v1.0 (${instance})`,
    "",
    `${instance}:~ $ verify --token ••••••••`,
    "Authentifiziere...",
  ]);

  useEffect(() => {
    if (!token) {
      setLines((prev) => [...prev, "> No token. Access denied."]);
      return;
    }

    fetch("/api/auth/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      credentials: "same-origin",
    })
      .then(async (res) => {
        if (res.ok) {
          setLines((prev) => [...prev, "> Authentifizierung erfolgreich.", "", "Weiterleitung..."]);
          setTimeout(() => router.replace(`/${instance}/chat`), 800);
        } else {
          const data = await res.json().catch(() => ({}));
          setLines((prev) => [
            ...prev,
            `> Error: ${data.error || "Token invalid or expired."}`,
            "",
            `Neuer Versuch: ${instance}:~ $ _`,
          ]);
        }
      })
      .catch(() => {
        setLines((prev) => [...prev, "> Netzwerkfehler. Verbindung fehlgeschlagen."]);
      });
  }, [token, instance, router]);

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ backgroundColor: "var(--bg)" }}
    >
      <div
        className="w-full max-w-xl font-mono text-sm leading-relaxed"
        style={{ color: "var(--success)", padding: "2rem 0" }}
      >
        {lines.map((line, i) => (
          <div
            key={i}
            style={{
              color: line.startsWith(">") ? "var(--text-2)"
                : line.startsWith("Weiterleitung") ? "var(--success)"
                : line.includes("Error") ? "var(--danger)"
                : line.startsWith(instance) ? "var(--success)"
                : "var(--text-3)",
              whiteSpace: "pre-wrap",
            }}
          >
            {line || "\u00A0"}
          </div>
        ))}
        <span
          style={{
            display: "inline-block",
            width: "0.6em",
            height: "1.15em",
            backgroundColor: "var(--success)",
            animation: "blink 1s step-end infinite",
            verticalAlign: "text-bottom",
          }}
        />
        <style jsx global>{`
          @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
          }
        `}</style>
      </div>
    </div>
  );
}
