"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";

// Load ForceGraph3D client-side only — it uses WebGL / Three.js
const ForceGraph3D = dynamic(
  () => import("react-force-graph-3d").then((m) => m.default),
  { ssr: false, loading: () => <GraphLoadingOverlay /> }
);

function GraphLoadingOverlay() {
  return (
    <div className="absolute inset-0 flex items-center justify-center"
      style={{ backgroundColor: "var(--bg)" }}>
      <div className="text-[13px]" style={{ color: "var(--text-3)" }}>
        Loading graph…
      </div>
    </div>
  );
}

export interface GNode {
  id: string;
  labels: string[];
  props: Record<string, unknown>;
}

export interface GEdge {
  source: string;
  target: string;
  type: string;
}

export interface GraphData {
  nodes: GNode[];
  edges: GEdge[];
}

interface Props {
  data: GraphData;
  colorFn: (node: GNode) => string;
  selectedId?: string;
  onNodeClick: (node: GNode) => void;
}

/** Derive the best human-readable label for a node. */
function nodeDisplayName(node: GNode): string {
  const p = node.props;
  return String(
    p.name ?? p.title ?? p.message ?? p.url ?? node.labels[0] ?? node.id
  );
}

export function GraphViewer({ data, colorFn, selectedId, onNodeClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 800, height: 600 });

  // Track container size and update on resize
  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        setDims({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight,
        });
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const graphData = {
    nodes: data.nodes.map((n) => ({
      id: n.id,
      name: nodeDisplayName(n),
      color: colorFn(n),
      val: n.id === selectedId ? 4 : 1,
      __gnode: n,
    })),
    links: data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      label: e.type,
    })),
  };

  return (
    <div ref={containerRef} className="relative w-full h-full">
      {dims.width > 0 && (
        <ForceGraph3D
          graphData={graphData}
          width={dims.width}
          height={dims.height}
          backgroundColor="rgba(0,0,0,0)"
          nodeLabel="name"
          linkLabel="label"
          linkColor={() => "rgba(150,150,150,0.4)"}
          linkWidth={1}
          nodeRelSize={4}
          onNodeClick={(node: Record<string, unknown>) =>
            onNodeClick((node as { __gnode: GNode }).__gnode)
          }
        />
      )}
    </div>
  );
}
