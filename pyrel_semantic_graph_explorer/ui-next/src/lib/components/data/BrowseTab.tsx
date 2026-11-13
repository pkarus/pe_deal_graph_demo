/**
 * Browse tab — paginated list of instances for the selected concept.
 * Click a row to anchor it as the neighbourhood graph centre.
 */
"use client";
import { observer } from "mobx-react-lite";
import { explorerStore } from "../../store/ExplorerStore";

const BrowseTab = observer(function BrowseTab() {
  const store = explorerStore;

  if (!store.activeConcept) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        Select a concept above to browse its instances.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Search bar */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder={`Search ${store.activeConcept}…`}
          value={store.instanceSearch}
          onChange={(e) => store.setInstanceSearch(e.target.value)}
          className="flex-1 bg-slate-800 text-slate-200 placeholder-slate-500
                     rounded px-3 py-2 text-sm focus:outline-none focus:ring-1
                     focus:ring-cyan-600"
        />
        {store.browseLoading && (
          <span className="text-slate-500 text-sm self-center">Loading…</span>
        )}
      </div>

      {/* Error */}
      {store.browseError && (
        <div className="text-red-400 text-sm bg-red-950 rounded px-3 py-2">
          {store.browseError}
        </div>
      )}

      {/* Rows */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-1">
        {store.instancePage?.rows.map((row) => {
          const pkVal = Object.values(row.id_fields)[0];
          return (
            <button
              key={String(pkVal)}
              onClick={() => store.setAnchorInstance(row)}
              className="text-left bg-slate-800 hover:bg-slate-700 rounded px-3 py-2
                         transition-colors group"
            >
              <div className="flex items-center justify-between">
                <span className="text-slate-200 text-sm font-medium">
                  {row.label}
                </span>
                <span className="text-xs text-slate-600 group-hover:text-cyan-500 transition-colors">
                  Explore →
                </span>
              </div>
              <div className="flex flex-wrap gap-x-3 mt-1">
                {Object.entries(row.id_fields).map(([k, v]) => (
                  <span key={k} className="text-xs text-slate-500">
                    {k}: <span className="text-slate-400">{String(v)}</span>
                  </span>
                ))}
              </div>
            </button>
          );
        })}
      </div>

      {/* Pagination */}
      {store.instancePage && (
        <div className="flex items-center gap-3 text-sm text-slate-400">
          <button
            disabled={store.instanceOffset === 0}
            onClick={() =>
              store.setInstanceOffset(
                Math.max(0, store.instanceOffset - store.instanceLimit)
              )
            }
            className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ← Prev
          </button>
          <span>
            {store.instanceOffset + 1}–
            {store.instanceOffset + (store.instancePage.rows.length)}
          </span>
          <button
            disabled={store.instancePage.rows.length < store.instanceLimit}
            onClick={() =>
              store.setInstanceOffset(store.instanceOffset + store.instanceLimit)
            }
            className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
});

export default BrowseTab;
