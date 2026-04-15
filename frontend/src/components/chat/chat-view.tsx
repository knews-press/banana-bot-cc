"use client";

import { useEffect, useRef, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useChat } from "@/hooks/use-chat";
import { useCommands } from "@/hooks/use-commands";
import { MessageBubble } from "./message-bubble";
import { MessageInput } from "./message-input";
import { Spinner } from "@/components/ui/spinner";
import type { ChatMessage } from "@/types";

interface ChatViewProps { instance: string; sessionId?: string; }

export function ChatView({ instance, sessionId: initialSessionId }: ChatViewProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const forceNew = searchParams.get("new") === "1";
  const { messages, setMessages, sendMessage, isStreaming, isLoadingHistory, isSyncing, thinkingElapsed, error, sessionId, stop, telegramRunning, stopRemote, contextTokens, contextMaxTokens } = useChat(instance, initialSessionId, forceNew);
  const { commands, executeCommand } = useCommands(instance);
  const anyRunning = isStreaming || telegramRunning;

  const bottomRef = useRef<HTMLDivElement>(null);
  const prevSessionIdRef = useRef<string | null>(initialSessionId ?? null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Reset ref when initialSessionId changes (e.g. navigating from a session to new chat)
  useEffect(() => {
    prevSessionIdRef.current = initialSessionId ?? null;
  }, [initialSessionId]);

  useEffect(() => {
    if (sessionId && sessionId !== prevSessionIdRef.current && !initialSessionId) {
      prevSessionIdRef.current = sessionId;
      router.replace(`/${instance}/chat/${sessionId}`);
    }
  }, [sessionId, initialSessionId, instance, router]);

  // Handle slash commands
  const handleCommand = useCallback(async (command: string, args: string[]) => {
    const commandText = `/${command}${args.length ? " " + args.join(" ") : ""}`;

    // Add user message showing the command
    const userMsg: ChatMessage = {
      id: `cmd-${Date.now()}-user`,
      role: "user",
      content: commandText,
      timestamp: new Date(),
    };

    // Add placeholder system message
    const sysId = `cmd-${Date.now()}-sys`;
    const loadingMsg: ChatMessage = {
      id: sysId,
      role: "system",
      content: "…",
      commandTitle: command,
      timestamp: new Date(),
    };

    setMessages((prev: ChatMessage[]) => [...prev, userMsg, loadingMsg]);

    try {
      const result = await executeCommand(command, args);

      // Replace loading message with result
      const resultMsg: ChatMessage = {
        id: sysId,
        role: "system",
        content: result.error || result.content,
        commandTitle: result.title,
        timestamp: new Date(),
      };

      setMessages((prev: ChatMessage[]) =>
        prev.map((m) => (m.id === sysId ? resultMsg : m))
      );
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: sysId,
        role: "system",
        content: `Fehler: ${err instanceof Error ? err.message : "Unbekannter Fehler"}`,
        commandTitle: "Error",
        timestamp: new Date(),
      };
      setMessages((prev: ChatMessage[]) =>
        prev.map((m) => (m.id === sysId ? errorMsg : m))
      );
    }
  }, [executeCommand, setMessages]);

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: "var(--bg)" }}>
      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-3 py-4 md:px-5 md:py-8">
          {isLoadingHistory ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3" style={{ color: "var(--text-3)" }}>
              <Spinner className="h-4 w-4" />
              <span className="text-[13px]">Loading history…</span>
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 select-none">
              <p className="text-[22px] font-semibold mb-2" style={{ color: "var(--text)" }}>{instance}</p>
              <p className="text-[14px]" style={{ color: "var(--text-3)" }}>Send a message to get started.</p>
            </div>
          ) : (
            messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)
          )}

          {/* Inline status — replaces the old top bar, shown in the message flow */}
          {anyRunning && (
            <div className="flex gap-3 mb-6">
              <div
                className="hidden md:flex w-5 h-5 rounded flex-shrink-0 mt-0.5 items-center justify-center text-[9px] font-bold"
                style={{ backgroundColor: "var(--bg-muted)", color: "var(--text-2)" }}
              >
                {telegramRunning ? "TG" : instance.charAt(0).toUpperCase()}
              </div>
              <div className="flex items-center gap-1.5 py-1 text-[12px]" style={{ color: "var(--text-3)" }}>
                <span className="flex gap-0.5">
                  <span className="w-1 h-1 rounded-full animate-bounce" style={{ backgroundColor: "var(--text-3)", animationDelay: "0ms" }} />
                  <span className="w-1 h-1 rounded-full animate-bounce" style={{ backgroundColor: "var(--text-3)", animationDelay: "150ms" }} />
                  <span className="w-1 h-1 rounded-full animate-bounce" style={{ backgroundColor: "var(--text-3)", animationDelay: "300ms" }} />
                </span>
                {telegramRunning && <span>Telegram</span>}
                {isStreaming && thinkingElapsed > 0 && <span>{thinkingElapsed}s</span>}
              </div>
            </div>
          )}

          {isSyncing && !isStreaming && (
            <div className="flex justify-center py-2 text-[11px]" style={{ color: "var(--text-3)" }}>
              <span className="w-1 h-1 rounded-full animate-pulse mr-1.5 self-center" style={{ backgroundColor: "var(--text-3)" }} />
              synchronisiert…
            </div>
          )}

          {error && (
            <div
              className="text-[13px] rounded-md px-3.5 py-2.5 mb-4"
              style={{ backgroundColor: "var(--bg-subtle)", color: "var(--danger)", border: "1px solid var(--border)" }}
            >
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <MessageInput
        onSend={sendMessage}
        onCommand={handleCommand}
        commands={commands}
        disabled={anyRunning}
        onStop={telegramRunning ? stopRemote : stop}
        isStreaming={anyRunning}
        telegramRunning={telegramRunning}
      />
    </div>
  );
}
