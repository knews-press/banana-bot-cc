"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";

interface AuthUser {
  user_id: number;
  email: string;
  display_name: string | null;
  instance: string;
}

export function useAuth() {
  const params = useParams<{ instance: string }>();
  const instance = params?.instance;
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const url = instance ? `/api/auth/me?instance=${instance}` : "/api/auth/me";
    fetch(url)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, [instance]);

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instance }),
    });
    setUser(null);
    window.location.href = instance ? `/${instance}/login` : "/";
  }, [instance]);

  return { user, isLoading, logout };
}
