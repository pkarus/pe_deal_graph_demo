/**
 * Main explorer page.
 *
 * Header: model name + view toggle [Semantic | Data] + model upload button
 * Body:   SemanticView or DataView depending on viewMode
 */
import { useEffect, useRef } from "react";
import { observer } from "mobx-react-lite";
import { explorerStore } from "@/lib/store/ExplorerStore";
import SemanticView from "@/lib/components/semantic/SemanticView";
import DataView from "@/lib/components/data/DataView";

const Home = observer(function Home() {
  const store = explorerStore;
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    store.loadSemanticGraph();
  }, [store]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) await store.uploadModel(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col">
      {/* Header */}
      <header className="flex items-center gap-4 px-6 py-3 border-b border-slate-800">
        <h1 className="text-lg font-bold text-white tracking-tight">
          PyREL Graph Explorer
        </h1>

        {store.modelName && (
          <span className="text-sm text-slate-400 font-mono">
            {store.modelName}
          </span>
        )}

        <div className="ml-auto flex items-center gap-3">
          {/* View toggle */}
          <div className="flex rounded overflow-hidden border border-slate-700">
            <button
              onClick={() => store.setViewMode("semantic")}
              className={`px-4 py-1.5 text-sm transition-colors ${
                store.viewMode === "semantic"
                  ? "bg-cyan-700 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Semantic
            </button>
            <button
              onClick={() => store.setViewMode("data")}
              className={`px-4 py-1.5 text-sm transition-colors ${
                store.viewMode === "data"
                  ? "bg-cyan-700 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Data
            </button>
          </div>

          {/* PyREL query toggle */}
          {store.raiExecutorAvailable && (
            <button
              onClick={() => store.toggleUseRai()}
              className={`text-sm px-3 py-1.5 rounded border transition-colors ${
                store.useRai
                  ? "bg-cyan-800 border-cyan-600 text-cyan-200"
                  : "border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {store.useRai ? "PyREL" : "SQL"}
            </button>
          )}

          {/* Tooltip toggle */}
          <button
            onClick={() => store.toggleTooltips()}
            className={`text-sm px-3 py-1.5 rounded border transition-colors ${
              store.showTooltips
                ? "bg-slate-700 border-slate-500 text-slate-200"
                : "border-slate-700 text-slate-400 hover:text-slate-200"
            }`}
          >
            Tooltips {store.showTooltips ? "On" : "Off"}
          </button>

          {/* Model upload */}
          <button
            onClick={() => fileInputRef.current?.click()}
            className="text-sm text-slate-400 hover:text-slate-200 px-3 py-1.5
                       rounded border border-slate-700 hover:border-slate-500 transition-colors"
          >
            Upload model
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".py"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>
      </header>

      {/* Body */}
      <main className="flex-1 px-6 py-4 overflow-hidden">
        {store.viewMode === "semantic" ? <SemanticView /> : <DataView />}
      </main>
    </div>
  );
});

export default Home;
