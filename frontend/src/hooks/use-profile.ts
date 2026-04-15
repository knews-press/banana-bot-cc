"use client";

import { useState, useEffect, useCallback } from "react";
import type { UserProfile } from "@/types";

export function useProfile(instance: string) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/${instance}/user/profile`);
      if (!res.ok) throw new Error("Failed to load.");
      setProfile(await res.json());
    } catch {
      setError("Failed to load profile.");
    } finally {
      setIsLoading(false);
    }
  }, [instance]);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(
    async (updates: Partial<UserProfile["preferences"]> & { display_name?: string }) => {
      setIsSaving(true);
      setError(null);
      setSaveSuccess(false);
      try {
        const res = await fetch(`/api/${instance}/user/profile`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(updates),
        });
        if (!res.ok) {
          const d = await res.json();
          throw new Error(d.error || "Save failed.");
        }
        setProfile(await res.json());
        setSaveSuccess(true);
        setTimeout(() => setSaveSuccess(false), 3000);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Save failed.");
      } finally {
        setIsSaving(false);
      }
    },
    [instance]
  );

  return { profile, isLoading, isSaving, error, saveSuccess, save };
}
