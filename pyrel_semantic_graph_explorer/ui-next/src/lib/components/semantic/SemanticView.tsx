/**
 * Semantic View — shows the ontology graph (concepts + relationships).
 * Right-click a concept node to explore its instances in Data View.
 */
"use client";
import { useEffect } from "react";
import { observer } from "mobx-react-lite";
import { explorerStore } from "../../store/ExplorerStore";
import dynamic from "next/dynamic";
import type { GraphNode } from "../../api/client";

const CytoscapeGraph = dynamic(
  () => import("../shared/CytoscapeGraph"),
  { ssr: false }
);

const SemanticView = observer(function SemanticView() {
  const store = explorerStore;

  useEffect(() => {
    if (!store.semanticGraph) store.loadSemanticGraph();
  }, [store]);

  const handleNodeClick = (node: GraphNode) => {
    store.setHighlightedConcept(node.concept);
  };

  if (store.semanticLoading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        Loading semantic graph…
      </div>
    );
  }

  if (store.semanticError) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Error: {store.semanticError}
      </div>
    );
  }

  return (
    <div className="flex h-full gap-4">
      {/* Concept list sidebar */}
      <div className="w-56 shrink-0 flex flex-col gap-1 overflow-y-auto">
        <p className="text-xs text-slate-500 uppercase tracking-wide mb-2">
          Concepts
        </p>
        {store.concepts.map((c) => (
          <button
            key={c.name}
            onClick={() => store.setHighlightedConcept(c.name)}
            onDoubleClick={() =>
              store.setViewMode("data", { concept: c.name })
            }
            className={`text-left px-3 py-2 rounded text-sm transition-colors ${
              store.highlightedConcept === c.name
                ? "bg-cyan-900 text-cyan-200"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            <span className="font-medium">{c.name}</span>
            {store.conceptCounts[c.name] !== undefined && (
              <span className="ml-2 text-xs text-slate-500">
                {store.conceptCounts[c.name].toLocaleString()}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Graph canvas */}
      <div className="flex-1 flex flex-col gap-2">
        {store.highlightedConcept && (
          <div className="flex items-center justify-between bg-slate-800 rounded px-3 py-2 text-sm">
            <span className="text-slate-300">
              Selected:{" "}
              <span className="text-cyan-400 font-semibold">
                {store.highlightedConcept}
              </span>
            </span>
            <button
              onClick={() =>
                store.setViewMode("data", {
                  concept: store.highlightedConcept!,
                })
              }
              className="text-xs bg-cyan-700 hover:bg-cyan-600 text-white px-3 py-1 rounded transition-colors"
            >
              Explore instances →
            </button>
          </div>
        )}

        {store.semanticGraph && (
          <CytoscapeGraph
            graph={store.semanticGraph}
            layout="fcose"
            height="calc(100vh - 220px)"
            onNodeClick={handleNodeClick}
            highlightIds={
              store.highlightedConcept
                ? new Set([store.highlightedConcept])
                : undefined
            }
            showTooltips={store.showTooltips}
          />
        )}
      </div>
    </div>
  );
});

export default SemanticView;
