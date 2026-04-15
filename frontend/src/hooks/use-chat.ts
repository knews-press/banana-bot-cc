"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import type { ChatMessage, ToolEvent } from "@/types";

/** Fallback polling interval when SSE is unavailable or idle */
const FALLBACK_POLL_MS = 10_000;

/** How often to check whether Telegram holds the execution lock */
const LOCK_POLL_MS = 3_000;

type HistoryMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  tools?: ToolEvent[];
};

function mapHistory(history: HistoryMessage[]): ChatMessage[] {
  return history.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    tools: m.tools ?? [],
    timestamp: new Date(m.timestamp),
  }));
}

export function useChat(instance: string, initialSessionId?: string, forceNew = false) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [thinkingElapsed, setThinkingElapsed] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, _setSessionId] = useState<string | null>(
    forceNew ? null : (initialSessionId ?? null)
  );
  // True when Telegram holds the execution lock for the current session
  const [telegramRunning, setTelegramRunning] = useState(false);
  const telegramSessionIdRef = useRef<string | null>(null);
  // Context window usage reported by the SDK
  const [contextTokens, setContextTokens] = useState(0);
  const [contextMaxTokens, setContextMaxTokens] = useState(200_000);

  // Refs so async callbacks always see latest values without re-triggering effects
  const sessionIdRef = useRef<string | null>(forceNew ? null : (initialSessionId ?? null));
  const isStreamingRef = useRef(false);
  const lastMessageCountRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const sseAbortRef = useRef<AbortController | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lockPollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Ref so sendMessage always reads the current forceNew value even though it
  // is not listed in the useCallback dependency array.
  const forceNewRef = useRef(forceNew);
  forceNewRef.current = forceNew;

  const setSessionId = useCallback((id: string | null) => {
    sessionIdRef.current = id;
    _setSessionId(id);
  }, []);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  // ── History fetch ──────────────────────────────────────────────────────

  const fetchHistory = useCallback(
    async (sid: string): Promise<ChatMessage[] | null> => {
      try {
        const res = await fetch(`/api/${instance}/sessions/${sid}/messages`);
        if (!res.ok) return null;
        const data: HistoryMessage[] = await res.json();
        return mapHistory(data);
      } catch {
        return null;
      }
    },
    [instance]
  );

  const loadHistory = useCallback(
    async (sid: string) => {
      setIsLoadingHistory(true);
      setMessages([]);
      setError(null);
      lastMessageCountRef.current = 0;
      const msgs = await fetchHistory(sid);
      if (msgs) {
        setMessages(msgs);
        lastMessageCountRef.current = msgs.length;
      } else {
        setError("Failed to load message history.");
      }
      setIsLoadingHistory(false);
    },
    [fetchHistory]
  );

  // ── SSE live stream for an active session ─────────────────────────────

  const startSessionSSE = useCallback(
    (sid: string) => {
      // Close any existing SSE connection
      sseAbortRef.current?.abort();
      const ctrl = new AbortController();
      sseAbortRef.current = ctrl;

      (async () => {
        try {
          const res = await fetch(`/api/${instance}/sessions/${sid}/stream`, {
            signal: ctrl.signal,
          });
          if (!res.ok || !res.body) return;

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          // Optimistic live-assistant message while Telegram executes
          const liveId = `live-${sid}`;
          let hasLiveMsg = false;

          const ensureLiveMsg = () => {
            if (hasLiveMsg) return;
            hasLiveMsg = true;
            setMessages((prev) => {
              // Don't add if there's already a streaming assistant message at the end
              const last = prev[prev.length - 1];
              if (last?.id === liveId) return prev;
              return [
                ...prev,
                {
                  id: liveId,
                  role: "assistant" as const,
                  content: "",
                  tools: [],
                  timestamp: new Date(),
                },
              ];
            });
          };

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              if (line.startsWith("event: ")) continue; // handled via data field
              if (!line.startsWith("data: ")) continue;
              const raw = line.slice(6).trim();
              if (!raw || raw === "{}") continue;

              // When sendMessage() is actively streaming the same session via the
              // direct /chat endpoint, it already handles all events and updates
              // state. The SSE bus receives duplicates — skip them to avoid a
              // second live-message and premature fetchHistory replacement.
              if (isStreamingRef.current) continue;

              let ev: Record<string, unknown>;
              try { ev = JSON.parse(raw); } catch { continue; }

              const evType = ev.event as string | undefined;

              if (evType === "ping") continue;

              if (evType === "context_usage") {
                const t = ev.input_tokens as number | undefined;
                const m = ev.max_tokens as number | undefined;
                if (t !== undefined) setContextTokens(t);
                if (m !== undefined) setContextMaxTokens(m);
                continue;
              }

              if (evType === "thinking_text") {
                ensureLiveMsg();
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === liveId
                      ? { ...m, thinking: ev.content as string }
                      : m
                  )
                );
              } else if (evType === "text") {
                ensureLiveMsg();
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === liveId
                      ? { ...m, content: m.content + (ev.content as string), thinking: "" }
                      : m
                  )
                );
              } else if (evType === "tool_start") {
                ensureLiveMsg();
                const toolName = ev.tool as string;
                const tool: ToolEvent = {
                  tool: toolName,
                  input: (ev.input as Record<string, unknown>) ?? {},
                  status: "running",
                  isBackgroundTask: toolName.includes("spawn_background_task") || toolName.includes("tasks__spawn"),
                };
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === liveId
                      ? { ...m, tools: [...(m.tools ?? []), tool] }
                      : m
                  )
                );
              } else if (evType === "tool_result") {
                setMessages((prev) =>
                  prev.map((m) => {
                    if (m.id !== liveId) return m;
                    const tools = (m.tools ?? []).map((t) =>
                      t.tool === (ev.tool as string) && t.status === "running"
                        ? {
                            ...t,
                            success: ev.success as boolean,
                            duration: ev.duration as number,
                            preview: ev.preview as string,
                            status: (ev.success ? "done" : "error") as "done" | "error",
                          }
                        : t
                    );
                    return { ...m, tools };
                  })
                );
              } else if (evType === "done") {
                // Replace optimistic live-message with persisted DB version,
                // but preserve tool statuses that were built up via SSE events.
                const finalSid = (ev.session_id as string) ?? sid;
                setTimeout(async () => {
                  const msgs = await fetchHistory(finalSid);
                  if (!msgs) return;
                  lastMessageCountRef.current = msgs.length;
                  setMessages((prev) => {
                    const liveTools = prev.find((m) => m.id === liveId)?.tools ?? [];
                    if (liveTools.length === 0) return msgs;
                    return msgs.map((m, i) =>
                      i === msgs.length - 1 && m.role === "assistant"
                        ? { ...m, tools: liveTools }
                        : m
                    );
                  });
                  setIsSyncing(false);
                }, 600);
                // Reconnect after a short delay so we're ready for the next
                // Telegram message — without this, context_usage and live
                // events from subsequent executions are never received.
                setTimeout(() => {
                  if (!ctrl.signal.aborted) startSessionSSE(sid);
                }, 2000);
                return; // Close current stream
              }
            }
          }
        } catch (err) {
          if ((err as Error).name === "AbortError") return;
          // SSE failed — fallback polling will take over
        }
      })();
    },
    [instance, fetchHistory]
  );

  // ── Fallback polling (when SSE unavailable or no active execution) ─────

  const startFallbackPoll = useCallback(
    (sid: string) => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      pollTimerRef.current = setInterval(async () => {
        if (isStreamingRef.current) return;
        const msgs = await fetchHistory(sid);
        if (!msgs) return;
        if (msgs.length !== lastMessageCountRef.current) {
          lastMessageCountRef.current = msgs.length;
          if (!isStreamingRef.current) {
            setIsSyncing(true);
            setMessages(msgs);
            setTimeout(() => setIsSyncing(false), 600);
          }
        }
      }, FALLBACK_POLL_MS);
    },
    [fetchHistory]
  );

  // ── Lock polling: detect when Telegram holds the execution lock ──────

  const checkLock = useCallback(async () => {
    if (isStreamingRef.current) return;
    try {
      // Use the user-wide active-lock endpoint so we detect Telegram
      // activity regardless of which session is open in the browser.
      const res = await fetch(`/api/${instance}/sessions/active-lock`);
      if (!res.ok) return;
      const data: { is_running: boolean; channel: string | null; session_id: string | null } = await res.json();
      const tgRunning = data.is_running && data.channel === "telegram";
      telegramSessionIdRef.current = tgRunning ? data.session_id : null;
      setTelegramRunning(tgRunning);
    } catch {
      // Ignore — network hiccup
    }
  }, [instance]);

  const startLockPoll = useCallback(
    (_sid?: string) => {
      if (lockPollTimerRef.current) clearInterval(lockPollTimerRef.current);
      // Immediate check so the input is disabled right away
      checkLock();
      lockPollTimerRef.current = setInterval(checkLock, LOCK_POLL_MS);
    },
    [checkLock]
  );

  // ── Stop a remote (Telegram) execution ───────────────────────────────

  const stopRemote = useCallback(async () => {
    // Use the session Telegram is actually running in, not the one open in the browser
    const sid = telegramSessionIdRef.current ?? sessionIdRef.current;
    if (!sid) return;
    try {
      await fetch(`/api/${instance}/sessions/${sid}/stop`, { method: "POST" });
      setTelegramRunning(false);
      telegramSessionIdRef.current = null;
    } catch {
      // Ignore
    }
  }, [instance]);

  // ── Initial load + wire up SSE / polling when session changes ─────────

  useEffect(() => {
    // Tear down previous connections
    sseAbortRef.current?.abort();
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    if (lockPollTimerRef.current) clearInterval(lockPollTimerRef.current);

    if (!initialSessionId) {
      setMessages([]);
      setSessionId(null);
      lastMessageCountRef.current = 0;
      // Still poll for cross-channel lock even without a specific session
      startLockPoll();
      return;
    }

    setSessionId(initialSessionId);
    loadHistory(initialSessionId).then(() => {
      // Start SSE for live updates, fallback poll and lock poll as safety net
      startSessionSSE(initialSessionId);
      startFallbackPoll(initialSessionId);
      startLockPoll(initialSessionId);
    });

    return () => {
      sseAbortRef.current?.abort();
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (lockPollTimerRef.current) clearInterval(lockPollTimerRef.current);
    };
  }, [instance, initialSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Also start SSE + polling when sessionId first becomes known after a new web chat
  useEffect(() => {
    if (!sessionId || sessionId === initialSessionId) return;
    startSessionSSE(sessionId);
    startFallbackPoll(sessionId);
    startLockPoll(sessionId);
    return () => {
      sseAbortRef.current?.abort();
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (lockPollTimerRef.current) clearInterval(lockPollTimerRef.current);
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Send message (web-initiated streaming) ────────────────────────────

  const sendMessage = useCallback(
    async (content: string) => {
      setError(null);
      // Sync the ref immediately (don't wait for the React effect) so the SSE
      // guard is active before any events arrive on the bus.
      isStreamingRef.current = true;
      setIsStreaming(true);

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        timestamp: new Date(),
      };
      const assistantId = crypto.randomUUID();

      // Only add the user message upfront — the assistant message is added lazily
      // on the first incoming event so we never show an empty duplicate bubble.
      setMessages((prev) => [...prev, userMsg]);

      const controller = new AbortController();
      abortRef.current = controller;

      let streamedContent = "";
      let newSessionId: string | null = null;
      let assistantMsgAdded = false;

      // Mirror tool state in a plain variable so the finally-merge doesn't need
      // to find assistantId in React state (which may have been replaced by then).
      let capturedTools: ToolEvent[] = [];

      // Lazily add (or update) the assistant message in state.
      // On first call it inserts a new row; subsequent calls update in-place.
      const upsertAssistant = (updater: (prev: ChatMessage) => ChatMessage) => {
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === assistantId);
          if (idx !== -1) {
            // Already exists — update in place
            return prev.map((m) => (m.id === assistantId ? updater(m) : m));
          }
          // First event — insert assistant message
          const base: ChatMessage = {
            id: assistantId,
            role: "assistant",
            content: "",
            tools: [],
            timestamp: new Date(),
          };
          return [...prev, updater(base)];
        });
        assistantMsgAdded = true;
      };

      try {
        const res = await fetch(`/api/${instance}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: content,
            session_id: sessionIdRef.current,
            force_new: forceNewRef.current && !sessionIdRef.current,
            stream: true,
          }),
          signal: controller.signal,
        });

        if (!res.ok) {
          let errMsg = "Failed to send.";
          try {
            const d = await res.json();
            let raw = d.error ?? errMsg;
            // The proxy wraps FastAPI's JSON response as a string — unwrap the detail field
            try { const inner = JSON.parse(raw); if (inner.detail) raw = inner.detail; } catch { /* not JSON, use as-is */ }
            errMsg = raw;
          } catch {
            errMsg = (await res.text().catch(() => "")) || errMsg;
          }
          setError(errMsg);
          setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
          return;
        }

        const reader = res.body?.getReader();
        if (!reader) {
          setError("Keine Streaming-Verbindung.");
          setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw || raw === "[DONE]") continue;

            let event: Record<string, unknown>;
            try { event = JSON.parse(raw); } catch { continue; }

            if (event.event === "done") {
              if (event.session_id) {
                newSessionId = event.session_id as string;
                setSessionId(newSessionId);
              }
              // If no streamed text arrived, use the content from the done event
              if (streamedContent === "" && event.content) {
                upsertAssistant((m) => ({ ...m, content: event.content as string }));
              }
              continue;
            }

            if (event.event === "context_usage") {
              const t = event.input_tokens as number | undefined;
              const m = event.max_tokens as number | undefined;
              if (t !== undefined) setContextTokens(t);
              if (m !== undefined) setContextMaxTokens(m);
              continue;
            }

            if (event.event === "thinking") {
              setThinkingElapsed(event.elapsed_s as number ?? 0);
              continue;
            }

            if (event.event === "thinking_text") {
              upsertAssistant((m) => ({ ...m, thinking: event.content as string }));
              continue;
            }

            if (event.event === "error") {
              setError(
                (event.content as string) ??
                (event.message as string) ??
                "Unbekannter Fehler."
              );
              continue;
            }

            // First real content — reset thinking counter
            setThinkingElapsed(0);

            switch (event.event as string) {
              case "text": {
                const chunk = event.content as string;
                streamedContent += chunk;
                upsertAssistant((m) => ({ ...m, content: m.content + chunk, thinking: "" }));
                break;
              }
              case "tool_start": {
                const toolName = event.tool as string;
                const tool: ToolEvent = {
                  tool: toolName,
                  input: (event.input as Record<string, unknown>) ?? {},
                  status: "running",
                  isBackgroundTask:
                    toolName.includes("spawn_background_task") ||
                    toolName.includes("tasks__spawn"),
                };
                capturedTools = [...capturedTools, tool];
                upsertAssistant((m) => ({ ...m, tools: [...(m.tools ?? []), tool] }));
                break;
              }
              case "tool_result": {
                capturedTools = capturedTools.map((t) =>
                  t.tool === (event.tool as string) && t.status === "running"
                    ? {
                        ...t,
                        success: event.success as boolean,
                        duration: event.duration as number,
                        preview: event.preview as string,
                        status: (event.success ? "done" : "error") as "done" | "error",
                      }
                    : t
                );
                upsertAssistant((m) => {
                  const tools = capturedTools;
                  return { ...m, tools };
                });
                break;
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError("Verbindung unterbrochen.");
          setMessages((prev) =>
            prev.filter((m) => m.id !== assistantId && m.id !== userMsg.id)
          );
        }
      } finally {
        setIsStreaming(false);
        setThinkingElapsed(0);
        abortRef.current = null;
        // Sync with DB for correct message IDs and metadata, but preserve
        // streamed tool events (the DB only stores text, not per-message tools).
        // Keep isStreamingRef.current = true until the merge is done so the SSE
        // bus guard stays active and can't race with a plain setMessages(msgs).
        const sid = newSessionId ?? sessionIdRef.current;
        if (sid) {
          setTimeout(async () => {
            const msgs = await fetchHistory(sid);
            // Release SSE guard now that we hold the final msgs snapshot
            isStreamingRef.current = false;
            if (!msgs) return;
            lastMessageCountRef.current = msgs.length;
            if (!assistantMsgAdded || capturedTools.length === 0) {
              setMessages(msgs);
              return;
            }
            // Merge: inject streamed tool statuses into the last DB assistant msg.
            // Use capturedTools directly — don't look up assistantId in state,
            // because a parallel SSE event may have already replaced it.
            setMessages(
              msgs.map((m, i) =>
                i === msgs.length - 1 && m.role === "assistant"
                  ? { ...m, tools: capturedTools }
                  : m
              )
            );
          }, 1200);
        } else {
          isStreamingRef.current = false;
        }
      }
    },
    [instance, setSessionId, fetchHistory]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return {
    messages,
    setMessages,
    sendMessage,
    isStreaming,
    isLoadingHistory,
    isSyncing,
    thinkingElapsed,
    error,
    sessionId,
    stop,
    telegramRunning,
    stopRemote,
    contextTokens,
    contextMaxTokens,
  };
}
