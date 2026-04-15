"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import type { ChatMessage, ToolEvent } from "@/types";
import { ToolCall } from "./tool-call";
import { MarkdownContent } from "./markdown-content";

const MAX_VISIBLE_TOOLS = 5;

// Background task tool name patterns
function isBackgroundTask(tool: ToolEvent) {
  return tool.isBackgroundTask ||
    tool.tool.includes("spawn_background_task") ||
    tool.tool.includes("tasks__spawn");
}

function ThinkingBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const preview = text.length > 120 ? text.slice(0, 120) + "…" : text;

  return (
    <div
      className="mb-3 rounded-md px-3 py-2 text-[12px]"
      style={{
        backgroundColor: "var(--bg-subtle)",
        borderLeft: "2px solid var(--border)",
        color: "var(--text-3)",
      }}
    >
      <button
        className="flex items-center gap-1.5 w-full text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="italic flex-1" style={{ color: "var(--text-3)" }}>
          {expanded ? text : preview}
        </span>
        {text.length > 120 && (
          <span style={{ opacity: 0.5, fontSize: 10, flexShrink: 0 }}>
            {expanded ? "▲" : "▼"}
          </span>
        )}
      </button>
    </div>
  );
}

function BackgroundTasksSection({ tasks }: { tasks: ToolEvent[] }) {
  return (
    <div
      className="mt-3 rounded-md px-3 py-2 space-y-1"
      style={{
        backgroundColor: "var(--bg-subtle)",
        border: "1px solid var(--border)",
      }}
    >
      <p className="text-[11px] font-medium mb-1.5" style={{ color: "var(--text-3)" }}>
        🚀 Hintergrund-Tasks
      </p>
      {tasks.map((tool, i) => (
        <ToolCall key={i} tool={tool} />
      ))}
    </div>
  );
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const { instance } = useParams<{ instance: string }>();
  const avatarLetter = (instance ?? "B").charAt(0).toUpperCase();
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isUser) {
    return (
      <div className="flex justify-end mb-4">
        <div
          className="max-w-[88%] md:max-w-[75%] px-3.5 py-2.5 rounded-md text-[14px] leading-relaxed"
          style={{ backgroundColor: "var(--bg-muted)", color: "var(--text)" }}
        >
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        </div>
      </div>
    );
  }

  // System messages — slash command responses
  if (isSystem) {
    return (
      <div className="flex gap-3 mb-6">
        {/* Terminal icon — desktop only */}
        <div
          className="hidden md:flex w-5 h-5 rounded flex-shrink-0 mt-0.5 items-center justify-center text-[9px] font-bold"
          style={{ backgroundColor: "var(--bg-subtle)", color: "var(--success)" }}
        >
          ›
        </div>
        <div className="flex-1 min-w-0">
          {message.commandTitle && (
            <p
              className="text-[11px] font-medium mb-1.5 uppercase tracking-wide"
              style={{ color: "var(--text-3)" }}
            >
              {message.commandTitle}
            </p>
          )}
          <div
            className="rounded-md px-3.5 py-2.5"
            style={{
              backgroundColor: "var(--bg-subtle)",
              border: "1px solid var(--border)",
            }}
          >
            <MarkdownContent content={message.content} />
          </div>
        </div>
      </div>
    );
  }

  // Split tools into regular and background tasks
  const allTools = message.tools ?? [];
  const regularTools = allTools.filter((t) => !isBackgroundTask(t));
  const bgTasks = allTools.filter((t) => isBackgroundTask(t));

  // Apply max-5 limit: show last 5 (most recent), count the hidden ones
  const hiddenCount = Math.max(0, regularTools.length - MAX_VISIBLE_TOOLS);
  const visibleTools = regularTools.slice(-MAX_VISIBLE_TOOLS);

  return (
    <div className="flex gap-3 mb-6">
      {/* Avatar — desktop only */}
      <div
        className="hidden md:flex w-5 h-5 rounded flex-shrink-0 mt-0.5 items-center justify-center text-[9px] font-bold uppercase"
        style={{ backgroundColor: "var(--bg-muted)", color: "var(--text-2)" }}
      >
        {avatarLetter}
      </div>

      <div className="flex-1 min-w-0">

        {/* 1. Reasoning block — above tools */}
        {message.thinking && (
          <ThinkingBlock text={message.thinking} />
        )}

        {/* 2. Tool calls — max 5, newest last */}
        {visibleTools.length > 0 && (
          <div className="mb-3 space-y-2">
            {hiddenCount > 0 && (
              <p className="text-[11px] mb-1" style={{ color: "var(--text-3)" }}>
                + {hiddenCount} weitere Tool{hiddenCount !== 1 ? "s" : ""}
              </p>
            )}
            {visibleTools.map((tool, i) => (
              <ToolCall key={hiddenCount + i} tool={tool} />
            ))}
          </div>
        )}

        {/* 3. Response content */}
        {message.content ? (
          <MarkdownContent content={message.content} />
        ) : null}

        {/* 4. Background tasks section — below content */}
        {bgTasks.length > 0 && (
          <BackgroundTasksSection tasks={bgTasks} />
        )}

      </div>
    </div>
  );
}
