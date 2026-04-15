"use client";

import { useState, useEffect, useCallback } from "react";
import type { CommandDef, CommandResponse } from "@/types";

/**
 * Hook for fetching the command registry and executing slash commands.
 * Used by the chat input for autocomplete and command execution.
 */
export function useCommands(instance: string) {
  const [commands, setCommands] = useState<CommandDef[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch command registry on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchCommands() {
      try {
        const res = await fetch(`/api/${instance}/commands`);
        if (res.ok) {
          const data: CommandDef[] = await res.json();
          if (!cancelled) setCommands(data);
        }
      } catch (err) {
        console.error("Failed to fetch commands:", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchCommands();
    return () => { cancelled = true; };
  }, [instance]);

  // Execute a slash command
  const executeCommand = useCallback(
    async (command: string, args: string[]): Promise<CommandResponse> => {
      const res = await fetch(`/api/${instance}/commands`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, args }),
      });
      return res.json();
    },
    [instance]
  );

  return { commands, loading, executeCommand };
}
