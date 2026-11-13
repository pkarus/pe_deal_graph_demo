/**
 * Data View — three tabs: Browse, Neighbourhood, Path.
 */
"use client";
import { observer } from "mobx-react-lite";
import { explorerStore, DataTab } from "../../store/ExplorerStore";
import BrowseTab from "./BrowseTab";
import NeighbourhoodTab from "./NeighbourhoodTab";
import PathTab from "./PathTab";

const TABS: { id: DataTab; label: string }[] = [
  { id: "browse", label: "Browse Instances" },
  { id: "neighbourhood", label: "Neighbourhood" },
  { id: "path", label: "Path Finder" },
];

const DataView = observer(function DataView() {
  const store = explorerStore;

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Back to semantic */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => store.setViewMode("semantic")}
          className="text-sm text-slate-400 hover:text-slate-200 transition-colors"
        >
          ← Semantic view
        </button>
        {store.activeConcept && (
          <span className="text-sm text-slate-300">
            Exploring{" "}
            <span className="text-cyan-400 font-semibold">
              {store.activeConcept}
            </span>
          </span>
        )}
      </div>

      {/* Concept selector */}
      <div className="flex flex-wrap gap-2">
        {store.concepts.map((c) => (
          <button
            key={c.name}
            onClick={() => store.setActiveConcept(c.name)}
            className={`px-3 py-1 rounded text-sm transition-colors ${
              store.activeConcept === c.name
                ? "bg-cyan-700 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
            }`}
          >
            {c.name}
            {store.conceptCounts[c.name] !== undefined && (
              <span className="ml-1 text-xs opacity-70">
                ({store.conceptCounts[c.name].toLocaleString()})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-slate-700">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => store.setDataTab(t.id)}
            className={`px-4 py-2 text-sm transition-colors ${
              store.dataTab === t.id
                ? "border-b-2 border-cyan-500 text-cyan-300"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {store.dataTab === "browse" && <BrowseTab />}
        {store.dataTab === "neighbourhood" && <NeighbourhoodTab />}
        {store.dataTab === "path" && <PathTab />}
      </div>
    </div>
  );
});

export default DataView;
