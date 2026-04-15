"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Spinner } from "@/components/ui/spinner";
import { GraphViewer, type GraphData, type GNode } from "./graph-viewer";
import { NodeDetailPanel } from "./node-detail-panel";

// ── Schema types ─────────────────────────────────────────────────────────────

interface NodeTypeDef {
  domain: string;
  color: string;
  embedding?: boolean;
  key_props?: string[];
  description?: string;
}

interface GraphSchema {
  nodes: Record<string, NodeTypeDef>;
  edges: Array<{ from: string; to: string; type: string }>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getDomainsFromSchema(schema: GraphSchema): string[] {
  const domains = new Set(Object.values(schema.nodes).map((n) => n.domain));
  return Array.from(domains).sort();
}

function getTypesForDomain(schema: GraphSchema, domain: string | null): string[] {
  return Object.entries(schema.nodes)
    .filter(([, def]) => !domain || def.domain === domain)
    .map(([label]) => label)
    .sort();
}

function colorForLabels(schema: GraphSchema | null, labels: string[]): string {
  if (!schema) return "#6b7280";
  for (const lbl of labels) {
    const def = schema.nodes[lbl];
    if (def?.color) return def.color;
  }
  return "#6b7280";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4"
      style={{ color: "var(--text-3)" }}>
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="12" cy="12" r="4" />
        <circle cx="36" cy="12" r="4" />
        <circle cx="24" cy="36" r="4" />
        <line x1="16" y1="12" x2="32" y2="12" />
        <line x1="14" y1="15" x2="22" y2="33" />
        <line x1="34" y1="15" x2="26" y2="33" />
      </svg>
      <div className="text-center">
        <p className="text-[14px] font-medium mb-1" style={{ color: "var(--text-2)" }}>
          Kein Graph vorhanden
        </p>
        <p className="text-[12px]">
          Der Wissensgraph wird automatisch befüllt,<br />
          sobald Artikel, Personen und Themen extrahiert werden.
        </p>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  instance: string;
}

export function GraphTab({ instance }: Props) {
  const [schema, setSchema] = useState<GraphSchema | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(true);

  // Filters
  const [domain, setDomain] = useState<string>("");
  const [nodeType, setNodeType] = useState<string>("");
  const [q, setQ] = useState<string>("");

  // Graph data
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] });
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [nodeCount, setNodeCount] = useState<number | null>(null);

  // Detail panel
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load schema ─────────────────────────────────────────────────────────────
  useEffect(() => {
    fetch(`/api/${instance}/graph/schema`)
      .then((r) => r.json())
      .then((d) => setSchema(d ?? null))
      .catch(() => setSchema(null))
      .finally(() => setSchemaLoading(false));
  }, [instance]);

  // ── Load graph data (debounced) ──────────────────────────────────────────────
  const loadGraph = useCallback(() => {
    if (!schema) return;
    setGraphLoading(true);
    setGraphError(null);

    const sp = new URLSearchParams();
    // Domain is a schema-level concept only — Neo4j nodes carry no domain property.
    // Translate the selected domain/type into a label list the backend can filter on.
    if (nodeType) {
      sp.set("types", nodeType);
    } else if (domain && schema) {
      const domainTypes = getTypesForDomain(schema, domain);
      if (domainTypes.length > 0) sp.set("types", domainTypes.join(","));
    }
    if (q.trim()) sp.set("q", q.trim());
    sp.set("limit", "200");

    fetch(`/api/${instance}/graph?${sp}`)
      .then((r) => r.json())
      .then((d: GraphData & { error?: string }) => {
        if (d.error) throw new Error(d.error);
        setGraphData(d);
        setNodeCount(d.nodes.length);
      })
      .catch((e) => setGraphError(String(e.message ?? e)))
      .finally(() => setGraphLoading(false));
  }, [instance, schema, domain, nodeType, q]);

  // Reload when filters change (debounced for search field)
  useEffect(() => {
    if (!schema) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(loadGraph, q ? 400 : 0);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [schema, domain, nodeType, q, loadGraph]);

  // Reset node type when domain changes
  useEffect(() => { setNodeType(""); }, [domain]);

  const colorFn = useCallback(
    (node: GNode) => colorForLabels(schema, node.labels),
    [schema]
  );
  const colorFnByLabels = useCallback(
    (labels: string[]) => colorForLabels(schema, labels),
    [schema]
  );

  const domains = schema ? getDomainsFromSchema(schema) : [];
  const types = schema ? getTypesForDomain(schema, domain || null) : [];
  const hasEmbeddings = nodeType
    ? !!(schema?.nodes[nodeType]?.embedding)
    : false;

  // ── Render ──────────────────────────────────────────────────────────────────
  if (schemaLoading) {
    return <div className="flex-1 flex justify-center items-center"><Spinner /></div>;
  }

  if (!schema) return <EmptyState />;

  const inputStyle: React.CSSProperties = {
    border: "1px solid var(--border)",
    backgroundColor: "var(--bg-elevated)",
    color: "var(--text)",
  };
  const selectClass = "rounded-md px-3 py-1.5 text-[13px] focus:outline-none transition-colors";

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Filter bar ── */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 flex-shrink-0 flex-wrap"
        style={{ borderBottom: "1px solid var(--border)", backgroundColor: "var(--bg-elevated)" }}
      >
        {/* Domain */}
        <select
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          className={selectClass}
          style={inputStyle}
        >
          <option value="">Alle Domains</option>
          {domains.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>

        {/* Node type */}
        <select
          value={nodeType}
          onChange={(e) => setNodeType(e.target.value)}
          className={selectClass}
          style={inputStyle}
        >
          <option value="">Alle Typen</option>
          {types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        {/* Search */}
        <div className="relative flex-1 min-w-[160px]">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            style={{ color: "var(--text-3)" }}
            width="12" height="12" viewBox="0 0 13 13" fill="none"
            stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
            <circle cx="5.5" cy="5.5" r="4" /><line x1="8.75" y1="8.75" x2="12" y2="12" />
          </svg>
          <input
            type="search"
            placeholder={hasEmbeddings ? "Semantische Suche…" : "Knoten suchen…"}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 rounded-md text-[13px] focus:outline-none"
            style={inputStyle}
          />
        </div>

        {/* Stats */}
        <span className="text-[11px] tabular-nums flex-shrink-0" style={{ color: "var(--text-3)" }}>
          {graphLoading ? (
            <Spinner className="h-3 w-3" />
          ) : nodeCount !== null ? (
            `${nodeCount} Knoten · ${graphData.edges.length} Kanten`
          ) : null}
        </span>
      </div>

      {/* ── Graph area + detail panel ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Graph canvas */}
        <div
          className="flex-1 relative overflow-hidden"
          style={{ backgroundColor: "var(--bg)" }}
        >
          {graphError && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <p className="text-[13px]" style={{ color: "var(--danger)" }}>{graphError}</p>
            </div>
          )}
          {!graphError && graphData.nodes.length === 0 && !graphLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <p className="text-[13px]" style={{ color: "var(--text-3)" }}>
                Keine Knoten gefunden. Filter anpassen oder Suche leeren.
              </p>
            </div>
          )}
          {!graphError && graphData.nodes.length > 0 && (
            <GraphViewer
              data={graphData}
              colorFn={colorFn}
              selectedId={selectedNodeId ?? undefined}
              onNodeClick={(node) => setSelectedNodeId(node.id)}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedNodeId && (
          <NodeDetailPanel
            key={selectedNodeId}
            nodeId={selectedNodeId}
            instance={instance}
            colorFn={colorFnByLabels}
            onClose={() => setSelectedNodeId(null)}
            onNavigate={(id) => setSelectedNodeId(id)}
          />
        )}
      </div>
    </div>
  );
}
