/**
 * Generic Cytoscape.js wrapper.
 *
 * Accepts a GraphDTO (nodes + edges) and renders it using the specified layout.
 * Node click fires onNodeClick; edge click fires onEdgeClick.
 */
"use client";
import { useState, useEffect, useRef } from "react";
import type cytoscape from "cytoscape";
import type { GraphDTO, GraphNode } from "../../api/client";

// Concept → colour mapping
const CONCEPT_COLORS: Record<string, string> = {
  Person: "#157b87",
  Center: "#ac7d30",
  Location: "#06b6d4",
  Order: "#3b82f6",
  Barista: "#f97316",
  MenuItem: "#22c55e",
  InventoryItem: "#eab308",
  InventoryTransaction: "#a855f7",
  LoyaltyMember: "#ec4899",
  Shift: "#6b7280",
  LocationDailyMetrics: "#64748b",
  SupplyTransfer: "#14b8a6",
  OrderItem: "#8b5cf6",
};

const DEFAULT_COLOR = "#94a3b8";

function conceptColor(concept: string): string {
  return CONCEPT_COLORS[concept] ?? DEFAULT_COLOR;
}

export type LayoutName = "dagre" | "fcose" | "grid" | "breadthfirst" | "concentric";

interface Props {
  graph: GraphDTO;
  layout?: LayoutName;
  height?: string;
  onNodeClick?: (node: GraphNode) => void;
  onEdgeClick?: (edgeId: string, relationship: string) => void;
  highlightIds?: Set<string>;
  showTooltips?: boolean;
  undirected?: boolean;
}

export default function CytoscapeGraph({
  graph,
  layout = "fcose",
  height = "600px",
  onNodeClick,
  onEdgeClick,
  highlightIds,
  showTooltips = true,
  undirected = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number; y: number; label: string; concept: string;
    attributes: Record<string, unknown>;
  } | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    let owned: cytoscape.Core | null = null;

    const init = async () => {
      const cytoscapeLib = (await import("cytoscape")).default;

      // Register layout extensions
      try {
        const fcose = (await import("cytoscape-fcose")).default;
        cytoscapeLib.use(fcose);
      } catch { /* already registered */ }

      try {
        const dagre = (await import("cytoscape-dagre")).default;
        cytoscapeLib.use(dagre);
      } catch { /* already registered */ }

      const elements: cytoscape.ElementDefinition[] = [
        ...graph.nodes.map((n) => ({
          data: {
            id: n.id,
            label: n.label,
            concept: n.concept,
            ...n.attributes,
          },
        })),
        ...graph.edges.map((e) => ({
          data: {
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.relationship,
            fullLabel: e.label,
            ...e.attributes,
          },
        })),
      ];

      if (cancelled || !containerRef.current) return;
      const cy = cytoscapeLib({
        container: containerRef.current!,
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": (ele: cytoscape.NodeSingular) =>
                ele.data('community_id') != null ? ['#157b87','#8860b0','#b27228','#416ac2','#a45078','#56833c'][String(ele.data('community_id')).split('').reduce((a,c)=>a+c.charCodeAt(0),0)%6] : conceptColor(ele.data("concept") as string),
              label: "data(label)",
              color: "#fff",
              "text-valign": "center",
              "text-halign": "center",
              "font-size": "11px",
              "text-wrap": "wrap",
              "text-max-width": "80px",
              width: (ele:cytoscape.NodeSingular)=>60+Math.min(30,Math.log1p(Number(ele.data('betweenness')??0))*3),
              height: (ele:cytoscape.NodeSingular)=>60+Math.min(30,Math.log1p(Number(ele.data('betweenness')??0))*3),
              shape: "round-rectangle",
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 3,
              "border-color": "#fff",
              "border-opacity": 0.9,
            },
          },
          {
            selector: "edge",
            style: {
              width: (ele:cytoscape.EdgeSingular)=>1.5+7*Math.sqrt(Number(ele.data('strength')??0)),
              "line-color": "#475569",
              "target-arrow-color": "#475569",
              "target-arrow-shape": undirected ? "none" : "triangle",
              "curve-style": "bezier",
              label: "data(label)",
              "font-size": "9px",
              color: "#94a3b8",
              "text-rotation": "autorotate",
              "text-margin-y": -8,
            },
          },
          {
            selector: ".highlighted",
            style: {
              "border-width": 4,
              "border-color": "#fbbf24",
              "border-opacity": 1,
            },
          },
        ] as unknown as cytoscape.StylesheetCSS[],
        layout: { name: layout, spacingFactor: 1.2, animate: false,
          nodeDimensionsIncludeLabels: true, nodeRepulsion: 12000,
          idealEdgeLength: 140, padding: 36,
          ...(layout==='concentric'?{concentric:(node:cytoscape.NodeSingular)=>Math.log1p(Number(node.data('betweenness')??0)),levelWidth:()=>0.7,minNodeSpacing:35}: {}) } as cytoscape.LayoutOptions,
      });

      // Apply highlights
      if (highlightIds?.size) {
        cy.nodes().forEach((n) => {
          if (highlightIds.has(n.id())) n.addClass("highlighted");
        });
      }

      if (onNodeClick) {
        cy.on("tap", "node", (evt) => {
          const node = graph.nodes.find((n) => n.id === evt.target.id());
          if (node) onNodeClick(node);
        });
      }

      if (onEdgeClick) {
        cy.on("tap", "edge", (evt) => {
          onEdgeClick(
            evt.target.id() as string,
            evt.target.data("label") as string
          );
        });
      }

      if (showTooltips) {
        cy.on("mouseover", "node", (evt) => {
          const containerRect = containerRef.current?.getBoundingClientRect();
          if (!containerRect) return;
          const me = evt.originalEvent as MouseEvent;
          const data = evt.target.data() as Record<string, unknown>;
          setTooltip({
            x: me.clientX - containerRect.left,
            y: me.clientY - containerRect.top,
            label: String(data.label ?? evt.target.id()),
            concept: String(data.concept ?? ""),
            attributes: Object.fromEntries(
              Object.entries(data).filter(([k]) => !["id","label","concept"].includes(k))
            ),
          });
        });
        cy.on("mouseout", "node", () => setTooltip(null));
        cy.on("drag", () => setTooltip(null));
      } else {
        setTooltip(null);
      }

      cyRef.current = cy;
      owned = cy;
    };

    init();

    return () => {
      cancelled = true;
      owned?.destroy();
      if (cyRef.current === owned) cyRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, layout, showTooltips, undirected]);

  return (
    <div style={{ position: "relative", width: "100%", height }}>
      <div
        ref={containerRef}
        style={{ width: "100%", height, background: "#0f172a", borderRadius: 8 }}
      />
      {tooltip && (
        <div
          style={{
            position: "absolute",
            left: Math.min(tooltip.x + 12, parseInt(String(height)) - 200 || tooltip.x + 12),
            top: tooltip.y - 10,
            pointerEvents: "none",
            zIndex: 10,
          }}
          className="bg-slate-800 border border-slate-600 rounded-lg shadow-xl px-3 py-2 text-xs max-w-xs"
        >
          <div className="font-semibold text-cyan-300 mb-1">{tooltip.concept}</div>
          <div className="text-slate-200 mb-1">{tooltip.label}</div>
          {Object.entries(tooltip.attributes).slice(0, 8).map(([k, v]) => (
            <div key={k} className="flex gap-1 text-slate-400">
              <span className="text-slate-500">{k}:</span>
              <span className="text-slate-300 truncate max-w-32">{String(v ?? "")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
