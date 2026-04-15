"use client";

import { useState, useEffect } from "react";
import type { DailyStatRow, ToolStat } from "@/types";

interface DailyStatsData {
  daily: DailyStatRow[];
  tools: ToolStat[];
}

export function useDailyStats(instance: string) {
  const [data, setData] = useState<DailyStatsData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    fetch(`/api/${instance}/user/stats/daily`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load.");
        return res.json();
      })
      .then(setData)
      .catch(() => setError("Failed to load statistics."))
      .finally(() => setIsLoading(false));
  }, [instance]);

  return { data, isLoading, error };
}
