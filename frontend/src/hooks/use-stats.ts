"use client";

import { useState, useEffect } from "react";
import type { UserStats } from "@/types";

export function useStats(instance: string) {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    fetch(`/api/${instance}/user/stats`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load.");
        return res.json();
      })
      .then(setStats)
      .catch(() => setError("Failed to load statistics."))
      .finally(() => setIsLoading(false));
  }, [instance]);

  return { stats, isLoading, error };
}
