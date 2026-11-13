/**
 * Path tab — find shortest path between two node IDs in the semantic graph.
 */
"use client";
import { observer } from "mobx-react-lite";
import { explorerStore } from "../../store/ExplorerStore";
import dynamic from "next/dynamic";

const CytoscapeGraph = dynamic(
  () => import("../shared/CytoscapeGraph"),
  { ssr: false }
);

const PathTab = observer(function PathTab() {
  const store = explorerStore;

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Inputs */}
      <div className="flex gap-3 items-end">
        <div className="flex flex-col gap-1 flex-1">
          <label className="text-xs text-slate-400">Source node ID</label>
          <input
            value={store.pathSource}
            onChange={(e) => store.setPathSource(e.target.value)}
            placeholder="e.g. Order or Order:101"
            className="bg-slate-800 text-slate-200 placeholder-slate-500 rounded
                       px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-600"
          />
        </div>
        <div className="flex flex-col gap-1 flex-1">
          <label className="text-xs text-slate-400">Target node ID</label>
          <input
            value={store.pathTarget}
            onChange={(e) => store.setPathTarget(e.target.value)}
            placeholder="e.g. Location or Location:5"
            className="bg-slate-800 text-slate-200 placeholder-slate-500 rounded
                       px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-600"
          />
        </div>
        <button
          onClick={() => store.findPath()}
          disabled={!store.pathSource || !store.pathTarget || store.pathLoading}
          className="px-4 py-2 text-sm bg-cyan-700 hover:bg-cyan-600 text-white rounded
                     disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {store.pathLoading ? "Finding…" : "Find Path"}
        </button>
      </div>

      {/* Concept quick-fill */}
      <div className="flex flex-wrap gap-2">
        {store.concepts.map((c) => (
          <button
            key={c.name}
            onClick={() => {
              if (!store.pathSource) store.setPathSource(c.name);
              else if (!store.pathTarget) store.setPathTarget(c.name);
            }}
            className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-400
                       hover:text-slate-200 px-2 py-1 rounded transition-colors"
          >
            {c.name}
          </button>
        ))}
      </div>

      {/* Error */}
      {store.pathError && (
        <div className="text-red-400 text-sm bg-red-950 rounded px-3 py-2">
          {store.pathError}
        </div>
      )}

      {/* No path */}
      {store.pathResult === null && !store.pathLoading && store.pathSource && store.pathTarget && (
        <div className="text-slate-500 text-sm">
          No path found between{" "}
          <span className="text-slate-300">{store.pathSource}</span> and{" "}
          <span className="text-slate-300">{store.pathTarget}</span>.
        </div>
      )}

      {/* Result graph */}
      {store.pathResult && (
        <>
          <div className="text-xs text-slate-500">
            Path: {store.pathResult.nodes.length} concepts ·{" "}
            {store.pathResult.edges.length} relationships
          </div>
          <CytoscapeGraph
            graph={store.pathResult}
            layout="dagre"
            height="calc(100vh - 380px)"
            highlightIds={
              new Set([store.pathSource, store.pathTarget])
            }
          />
        </>
      )}
    </div>
  );
});

export default PathTab;
