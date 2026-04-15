"use client";

import { useState, useEffect, useCallback } from "react";
import type { ClusterStatus } from "@/types";

export function useCluster(instance: string) {
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/${instance}/cluster`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus(await res.json());
    } catch {
      setError("Cluster status unavailable.");
    } finally {
      setIsLoading(false);
    }
  }, [instance]);

  useEffect(() => { load(); }, [load]);

  return { status, isLoading, error, refresh: load };
}
