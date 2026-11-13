/**
 * Neighbourhood tab — ego graph around the selected anchor instance.
 */
"use client";
import { observer } from "mobx-react-lite";
import { explorerStore } from "../../store/ExplorerStore";
import dynamic from "next/dynamic";
import type { GraphNode } from "../../api/client";

const CytoscapeGraph = dynamic(
  () => import("../shared/CytoscapeGraph"),
  { ssr: false }
);

const NeighbourhoodTab = observer(function NeighbourhoodTab() {
  const store = explorerStore;

  if (!store.anchorInstance) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Select an instance from Browse tab to explore its neighbourhood.
      </div>
    );
  }

  const handleNodeClick = (node: GraphNode) => {
    // Allow navigating to a clicked instance's neighbourhood
    const [concept, pk] = node.id.split(":");
    if (concept && pk && node.id !== `${store.anchorInstance!.concept}:${Object.values(store.anchorInstance!.id_fields)[0]}`) {
      // Set this node as the new anchor
      store.setAnchorInstance({
        concept,
        id_fields: { id: pk },
        label: node.label,
        attributes: node.attributes,
      });
    }
  };

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Controls */}
      <div className="flex items-center gap-4 bg-slate-800 rounded px-3 py-2">
        <div className="text-sm text-slate-300">
          Anchor:{" "}
          <span className="text-cyan-400 font-semibold">
            {store.anchorInstance.label}
          </span>
          <span className="text-slate-500 ml-1">
            ({store.anchorInstance.concept})
          </span>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <label className="text-xs text-slate-400">Depth</label>
          <select
            value={store.neighbourhoodDepth}
            onChange={(e) =>
              store.setNeighbourhoodDepth(Number(e.target.value))
            }
            className="bg-slate-700 text-slate-200 text-sm rounded px-2 py-1
                       focus:outline-none focus:ring-1 focus:ring-cyan-600"
          >
            {[0, 1, 2, 3].map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>

          <button
            onClick={() => store.loadNeighbourhood()}
            className="text-xs bg-cyan-700 hover:bg-cyan-600 text-white
                       px-3 py-1 rounded transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Error */}
      {store.neighbourhoodError && (
        <div className="text-red-400 text-sm bg-red-950 rounded px-3 py-2">
          {store.neighbourhoodError}
        </div>
      )}

      {/* Loading */}
      {store.neighbourhoodLoading && (
        <div className="text-slate-500 text-sm">Building neighbourhood graph…</div>
      )}

      {/* Graph */}
      {store.neighbourhoodGraph && !store.neighbourhoodLoading && (
        <>
          <div className="text-xs text-slate-500">
            {store.neighbourhoodGraph.nodes.length} nodes ·{" "}
            {store.neighbourhoodGraph.edges.length} edges
            {" · "}
            <span className="text-slate-600">click a node to re-anchor</span>
          </div>
          <CytoscapeGraph
            graph={store.neighbourhoodGraph}
            layout="fcose"
            height="calc(100vh - 310px)"
            onNodeClick={handleNodeClick}
            highlightIds={
              new Set([
                `${store.anchorInstance.concept}:${Object.values(store.anchorInstance.id_fields)[0]}`,
              ])
            }
            showTooltips={store.showTooltips}
          />
        </>
      )}
    </div>
  );
});

export default NeighbourhoodTab;
