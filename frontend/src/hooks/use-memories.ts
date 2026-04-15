"use client";

import { useState, useEffect, useCallback } from "react";
import type { EsMemory, EsMemoryVersion } from "@/lib/es";

export type { EsMemory, EsMemoryVersion };

export function useMemories(instance: string) {
  const [memories, setMemories] = useState<EsMemory[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async (q?: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const url = `/api/${instance}/memories${q ? `?q=${encodeURIComponent(q)}` : ""}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to load.");
      setMemories(await res.json());
    } catch {
      setError("Failed to load memories.");
    } finally {
      setIsLoading(false);
    }
  }, [instance]);

  useEffect(() => { load(); }, [load]);

  const search = useCallback((q: string) => {
    setQuery(q);
    load(q || undefined);
  }, [load]);

  const remove = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/${instance}/memories/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setMemories((prev) => prev.filter((m) => m._id !== id));
    } catch {
      setError("Löschen fehlgeschlagen.");
    }
  }, [instance]);

  const create = useCallback(async (data: {
    type: string; name: string; description: string; content: string; tags: string[];
  }) => {
    const res = await fetch(`/api/${instance}/memories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Erstellen fehlgeschlagen.");
    await load(query || undefined);
  }, [instance, load, query]);

  const update = useCallback(async (id: string, data: {
    type: string; name: string; description: string; content: string; tags: string[];
  }) => {
    const res = await fetch(`/api/${instance}/memories/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Save failed.");
    // Optimistic update in local state
    setMemories((prev) => prev.map((m) => m._id === id
      ? { ...m, ...data, version: (m.version ?? 1) + 1, updated_at: new Date().toISOString() }
      : m
    ));
  }, [instance]);

  const getHistory = useCallback(async (id: string): Promise<EsMemoryVersion[]> => {
    const res = await fetch(`/api/${instance}/memories/${id}/history`);
    if (!res.ok) return [];
    return res.json();
  }, [instance]);

  const restore = useCallback(async (id: string, version: number) => {
    const res = await fetch(`/api/${instance}/memories/${id}/restore`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
    if (!res.ok) throw new Error("Restore failed.");
    // Reload to get the restored content
    await load(query || undefined);
  }, [instance, load, query]);

  return { memories, isLoading, error, query, search, remove, create, update, getHistory, restore };
}
