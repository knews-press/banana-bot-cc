"use client";

import { useState } from "react";
import type { ToolEvent } from "@/types";
import { FileCard, isCreationsPath } from "@/components/ui/file-card";

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="10" height="10" viewBox="0 0 10 10" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
      className={`transition-transform duration-150 ${open ? "rotate-90" : ""}`}
    >
      <polyline points="3 2 7 5 3 8" />
    </svg>
  );
}

function StatusDot({ status }: { status: ToolEvent["status"] }) {
  if (status === "running") {
    return (
      <span
        className="w-1.5 h-1.5 rounded-full animate-pulse flex-shrink-0"
        style={{ backgroundColor: "#d4a017" }}   // yellow
      />
    );
  }
  if (status === "done") {
    return (
      <span
        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
        style={{ backgroundColor: "var(--success, #4caf7d)" }}  // green
      />
    );
  }
  // error
  return (
    <span
      className="w-1.5 h-1.5 rounded-full flex-shrink-0"
      style={{ backgroundColor: "var(--danger, #e05252)" }}  // red
    />
  );
}

export function ToolCall({ tool }: { tool: ToolEvent }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = tool.input || tool.preview;

  return (
    <div className="text-[12px]">
      <button
        onClick={() => hasDetails && setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left py-0.5"
        style={{ cursor: hasDetails ? "pointer" : "default" }}
      >
        <StatusDot status={tool.status} />
        <span className="font-mono" style={{ color: "var(--text-2)" }}>
          {tool.tool}
        </span>
        {tool.duration !== undefined && tool.duration > 0 && (
          <span style={{ color: "var(--text-3)" }}>{tool.duration.toFixed(1)}s</span>
        )}
        {hasDetails && (
          <span className="ml-auto" style={{ color: "var(--text-3)" }}>
            <ChevronIcon open={expanded} />
          </span>
        )}
      </button>

      {expanded && hasDetails && (
        <div className="ml-3.5 mt-1 space-y-1.5 pb-1">
          {tool.input && Object.keys(tool.input).length > 0 && (
            <pre
              className="text-[11px] font-mono rounded-md p-2.5 overflow-x-auto leading-relaxed"
              style={{ backgroundColor: "var(--bg-subtle)", color: "var(--text-2)" }}
            >
              {JSON.stringify(tool.input, null, 2)}
            </pre>
          )}
          {tool.preview && (
            isCreationsPath(tool.preview) ? (
              <div className="mt-1">
                <FileCard path={tool.preview.trim()} />
              </div>
            ) : (
              <pre
                className="text-[11px] font-mono rounded-md p-2.5 overflow-x-auto leading-relaxed"
                style={{ backgroundColor: "var(--bg-subtle)", color: "var(--text-3)" }}
              >
                {tool.preview}
              </pre>
            )
          )}
        </div>
      )}
    </div>
  );
}
