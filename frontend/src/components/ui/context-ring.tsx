"use client";

/** Max context window for Claude models (tokens). */
export const CONTEXT_MAX_TOKENS = 200_000;

interface ContextRingProps {
  /** Current context window usage in tokens. */
  tokens: number;
  /** Maximum tokens (default: 200 000). */
  maxTokens?: number;
  /** Diameter in px (default: 16). */
  size?: number;
  /** Show a tooltip with the percentage. */
  title?: string;
}

function ringColor(pct: number): string {
  if (pct >= 0.85) return "var(--danger)";
  if (pct >= 0.7)  return "#f59e0b";   // amber
  return "var(--accent)";
}

/**
 * Circular progress ring showing context window usage.
 *
 * Usage:
 *   <ContextRing tokens={45000} />
 *   <ContextRing tokens={45000} size={20} />
 */
export function ContextRing({ tokens, maxTokens = CONTEXT_MAX_TOKENS, size = 16, title }: ContextRingProps) {
  const strokeWidth = 1.75;
  const r = (size - strokeWidth) / 2;
  const circ = 2 * Math.PI * r;
  const pct = Math.min(1, Math.max(0, tokens / maxTokens));
  const offset = circ * (1 - pct);
  const cx = size / 2;
  const color = ringColor(pct);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ flexShrink: 0, display: "block" }}
      aria-label={title ?? `${Math.round(pct * 100)}% Context used (${(tokens / 1000).toFixed(0)}k / ${(maxTokens / 1000).toFixed(0)}k)`}
      role="img"
    >
      <title>{title ?? `${Math.round(pct * 100)}% Context used (${(tokens / 1000).toFixed(0)}k / ${(maxTokens / 1000).toFixed(0)}k)`}</title>
      {/* Track */}
      <circle cx={cx} cy={cx} r={r} fill="none" strokeWidth={strokeWidth} stroke="var(--border)" />
      {/* Fill */}
      {pct > 0 && (
        <circle
          cx={cx} cy={cx} r={r}
          fill="none"
          strokeWidth={strokeWidth}
          stroke={color}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cx})`}
          style={{ transition: "stroke-dashoffset 0.4s ease, stroke 0.4s ease" }}
        />
      )}
    </svg>
  );
}
