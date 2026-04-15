"use client";

import { useEffect, useState } from "react";
import { Spinner } from "@/components/ui/spinner";

export interface Neighbor {
  id: string;
  labels: string[];
  props: Record<string, unknown>;
  rel_type: string;
  direction: "in" | "out";
}

export interface NodeDetail {
  node: { id: string; labels: string[]; props: Record<string, unknown> };
  neighbors: Neighbor[];
}

interface Props {
  nodeId: string;
  instance: string;
  colorFn: (labels: string[]) => string;
  onClose: () => void;
  onNavigate: (nodeId: string) => void;
}

function propDisplayName(props: Record<string, unknown>): string {
  return String(
    props.name ?? props.title ?? props.message ?? props.url ?? "–"
  );
}

function PropRow({ k, v }: { k: string; v: unknown }) {
  if (v === null || v === undefined || v === "") return null;
  const display =
    typeof v === "object" ? JSON.stringify(v) : String(v);
  if (display.length > 300) return null; // skip very long fields
  return (
    <div className="flex gap-2 py-1 text-[12px]"
      style={{ borderBottom: "1px solid var(--border)" }}>
      <span className="w-28 flex-shrink-0 font-medium truncate"
        style={{ color: "var(--text-3)" }}>{k}</span>
      <span className="flex-1 break-words" style={{ color: "var(--text-2)" }}>{display}</span>
    </div>
  );
}

const SKIP_PROPS = new Set(["user_id", "embedding", "created_at", "updated_at", "domain"]);

export function NodeDetailPanel({ nodeId, instance, colorFn, onClose, onNavigate }: Props) {
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setDetail(null);
    fetch(`/api/${instance}/graph/node/${encodeURIComponent(nodeId)}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.error) throw new Error(d.error);
        setDetail(d as NodeDetail);
      })
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false));
  }, [nodeId, instance]);

  // Group neighbors by rel_type
  const grouped = detail?.neighbors.reduce<Record<string, Neighbor[]>>((acc, n) => {
    const key = `${n.direction === "out" ? "→" : "←"} ${n.rel_type}`;
    (acc[key] ??= []).push(n);
    return acc;
  }, {}) ?? {};

  const node = detail?.node;
  const primaryLabel = node?.labels[0] ?? "Node";
  const color = node ? colorFn(node.labels) : "#6b7280";
  const displayName = node ? propDisplayName(node.props) : "…";

  return (
    <div
      className="flex flex-col overflow-hidden h-full"
      style={{
        width: 320,
        minWidth: 280,
        borderLeft: "1px solid var(--border)",
        backgroundColor: "var(--bg-elevated)",
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--border)" }}>
        <span className="w-2 h-2 rounded-full flex-shrink-0"
          style={{ backgroundColor: color }} />
        <div className="flex-1 min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider"
            style={{ color }}>{primaryLabel}</p>
          <p className="text-[13px] font-medium truncate"
            style={{ color: "var(--text)" }}>{displayName}</p>
        </div>
        <button onClick={onClose}
          className="p-1.5 rounded flex-shrink-0"
          style={{ color: "var(--text-3)" }}>✕</button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5">
        {loading && <div className="flex justify-center py-8"><Spinner /></div>}
        {error && <p className="text-[12px] text-center" style={{ color: "var(--danger)" }}>{error}</p>}

        {detail && (
          <>
            {/* Properties */}
            <section>
              <p className="text-[10px] font-semibold uppercase tracking-wider mb-2"
                style={{ color: "var(--text-3)" }}>Eigenschaften</p>
              <div>
                {Object.entries(node!.props)
                  .filter(([k]) => !SKIP_PROPS.has(k))
                  .map(([k, v]) => <PropRow key={k} k={k} v={v} />)}
              </div>
              <p className="text-[10px] mt-1" style={{ color: "var(--text-3)" }}>
                Domain: {String(node!.props.domain ?? "–")}
                {node!.props.created_at
                  ? ` · ${new Date(String(node!.props.created_at)).toLocaleDateString("de-DE")}`
                  : ""}
              </p>
            </section>

            {/* Neighbors */}
            {Object.keys(grouped).length > 0 && (
              <section>
                <p className="text-[10px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "var(--text-3)" }}>
                  Verbindungen ({detail.neighbors.length})
                </p>
                {Object.entries(grouped).map(([rel, nbrs]) => (
                  <div key={rel} className="mb-3">
                    <p className="text-[10px] font-mono mb-1" style={{ color: "var(--text-3)" }}>{rel}</p>
                    {nbrs.map((nb) => {
                      const nbColor = colorFn(nb.labels);
                      return (
                        <button
                          key={nb.id}
                          onClick={() => onNavigate(nb.id)}
                          className="flex items-center gap-2 w-full text-left py-1.5 px-2 rounded transition-colors hover:opacity-80"
                          style={{ backgroundColor: "var(--bg-muted)" }}
                        >
                          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                            style={{ backgroundColor: nbColor }} />
                          <span className="text-[11px] flex-shrink-0 font-medium uppercase"
                            style={{ color: nbColor }}>{nb.labels[0]}</span>
                          <span className="text-[12px] truncate"
                            style={{ color: "var(--text-2)" }}>
                            {propDisplayName(nb.props)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
