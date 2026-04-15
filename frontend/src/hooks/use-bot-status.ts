"use client";

import { useState, useEffect, useCallback } from "react";

export interface BotStatus {
  instance_name: string;
  uptime_seconds: number;
  claude_cli: boolean;
  active_sessions: number;
  total_messages: number;
  total_cost: number;
}

export function useBotStatus(instance: string) {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/${instance}/status`);
      if (!res.ok) return;
      setStatus(await res.json());
    } catch {
      // silently ignore — bot may be temporarily unreachable
    } finally {
      setIsLoading(false);
    }
  }, [instance]);

  useEffect(() => {
    load();
    // Re-check every 60 seconds so the banner disappears once auth is done
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  return { status, isLoading, claudeReady: status?.claude_cli ?? true };
}
