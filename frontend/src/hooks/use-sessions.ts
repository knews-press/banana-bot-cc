"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type { Session } from "@/types";

const SESSION_POLL_INTERVAL_MS = 8000; // refresh session list every 8s

export function useSessions(instance: string) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`/api/${instance}/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
      }
    } catch {
      // ignore network errors silently
    } finally {
      setIsLoading(false);
    }
  }, [instance]);

  // Initial load
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll for new sessions (e.g. created via Telegram)
  useEffect(() => {
    pollTimerRef.current = setInterval(refresh, SESSION_POLL_INTERVAL_MS);
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [refresh]);

  const deleteSession = useCallback(
    async (id: string) => {
      await fetch(`/api/${instance}/sessions/${id}`, { method: "DELETE" });
      await refresh();
    },
    [instance, refresh]
  );

  return { sessions, isLoading, deleteSession, refresh };
}
