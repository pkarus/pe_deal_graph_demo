/**
 * Central MobX store for the graph explorer.
 *
 * Two top-level modes:
 *   "semantic" — ontology graph, concepts and relationships
 *   "data"     — actual instance data, neighbourhood traversal
 *
 * Navigation:
 *   setMode("data", { concept: "Location" })   — switch to data view for a concept
 *   setMode("semantic", { highlight: "Order" }) — switch back, highlight concept
 */
import { makeAutoObservable, runInAction } from "mobx";
import {
  api,
  ConceptSummary,
  GraphDTO,
  InstancePage,
  InstanceRow,
} from "../api/client";

export type ViewMode = "semantic" | "data";

export type DataTab = "browse" | "neighbourhood" | "path";

export class ExplorerStore {
  // ── View mode ──────────────────────────────────────────────────────────────
  viewMode: ViewMode = "semantic";
  dataTab: DataTab = "browse";

  // ── Semantic view state ────────────────────────────────────────────────────
  semanticGraph: GraphDTO | null = null;
  concepts: ConceptSummary[] = [];
  conceptCounts: Record<string, number> = {};
  highlightedConcept: string | null = null;
  semanticLoading = false;
  semanticError: string | null = null;

  // ── Data view — browse state ───────────────────────────────────────────────
  activeConcept: string | null = null;
  instancePage: InstancePage | null = null;
  instanceSearch = "";
  instanceLimit = 50;
  instanceOffset = 0;
  browseLoading = false;
  browseError: string | null = null;

  // ── Data view — neighbourhood state ───────────────────────────────────────
  anchorInstance: InstanceRow | null = null;
  neighbourhoodGraph: GraphDTO | null = null;
  neighbourhoodDepth = 1;
  neighbourhoodMaxNodes = 150;
  neighbourhoodLoading = false;
  neighbourhoodError: string | null = null;

  // ── Data view — path state ─────────────────────────────────────────────────
  pathSource: string = "";
  pathTarget: string = "";
  pathResult: GraphDTO | null = null;
  pathLoading = false;
  pathError: string | null = null;

  // ── Model info ─────────────────────────────────────────────────────────────
  modelName: string | null = null;
  showTooltips: boolean = true;
  useRai: boolean = false;
  raiExecutorAvailable: boolean = false;

  constructor() {
    makeAutoObservable(this);
  }

  // ── View mode ──────────────────────────────────────────────────────────────

  setViewMode(mode: ViewMode, opts?: { concept?: string; highlight?: string }) {
    this.viewMode = mode;
    if (mode === "data" && opts?.concept) {
      this.setActiveConcept(opts.concept);
      this.dataTab = "browse";
    }
    if (mode === "semantic" && opts?.highlight) {
      this.highlightedConcept = opts.highlight;
    }
  }

  setDataTab(tab: DataTab) {
    this.dataTab = tab;
  }

  // ── Semantic view ──────────────────────────────────────────────────────────

  async loadSemanticGraph() {
    this.semanticLoading = true;
    this.semanticError = null;
    try {
      const [graph, concepts, health] = await Promise.all([
        api.semanticGraph(),
        api.concepts(),
        api.health(),
      ]);
      runInAction(() => {
        this.raiExecutorAvailable = (health as any).rai_executor_available ?? false;
      });
      runInAction(() => {
        this.semanticGraph = graph;
        this.concepts = concepts;
        this.semanticLoading = false;
      });
      // Load counts lazily after initial render
      this.loadConceptCounts(concepts.map((c) => c.name));
    } catch (e) {
      runInAction(() => {
        this.semanticError = String(e);
        this.semanticLoading = false;
      });
    }
  }

  private async loadConceptCounts(names: string[]) {
    await Promise.allSettled(
      names.map(async (name) => {
        try {
          const { count } = await api.conceptCount(name);
          runInAction(() => {
            this.conceptCounts[name] = count;
          });
        } catch {
          // counts are best-effort; ignore failures
        }
      })
    );
  }

  setHighlightedConcept(name: string | null) {
    this.highlightedConcept = name;
  }

  // ── Data browse ───────────────────────────────────────────────────────────

  setActiveConcept(name: string) {
    this.activeConcept = name;
    this.instanceOffset = 0;
    this.instanceSearch = "";
    this.instancePage = null;
    this.loadInstances();
  }

  setInstanceSearch(q: string) {
    this.instanceSearch = q;
    this.instanceOffset = 0;
    this.loadInstances();
  }

  setInstanceOffset(offset: number) {
    this.instanceOffset = offset;
    this.loadInstances();
  }

  async loadInstances() {
    if (!this.activeConcept) return;
    this.browseLoading = true;
    this.browseError = null;
    try {
      const page = await api.instances(this.activeConcept, {
        limit: this.instanceLimit,
        offset: this.instanceOffset,
        search: this.instanceSearch || undefined,
      });
      runInAction(() => {
        this.instancePage = page;
        this.browseLoading = false;
      });
    } catch (e) {
      runInAction(() => {
        this.browseError = String(e);
        this.browseLoading = false;
      });
    }
  }

  // ── Neighbourhood ──────────────────────────────────────────────────────────

  setAnchorInstance(row: InstanceRow) {
    this.anchorInstance = row;
    this.neighbourhoodGraph = null;
    this.dataTab = "neighbourhood";
    this.loadNeighbourhood();
  }

  setNeighbourhoodDepth(depth: number) {
    this.neighbourhoodDepth = depth;
    if (this.anchorInstance) this.loadNeighbourhood();
  }

  async loadNeighbourhood() {
    if (!this.anchorInstance) return;
    this.neighbourhoodLoading = true;
    this.neighbourhoodError = null;
    const pkValue = Object.values(this.anchorInstance.id_fields)[0];
    try {
      const graph = await api.neighbourhood(
        this.anchorInstance.concept,
        String(pkValue),
        {
          depth: this.neighbourhoodDepth,
          max_nodes: this.neighbourhoodMaxNodes,
          use_rai: this.useRai,
        }
      );
      runInAction(() => {
        this.neighbourhoodGraph = graph;
        this.neighbourhoodLoading = false;
      });
    } catch (e) {
      runInAction(() => {
        this.neighbourhoodError = String(e);
        this.neighbourhoodLoading = false;
      });
    }
  }

  // ── Path ──────────────────────────────────────────────────────────────────

  setPathSource(id: string) {
    this.pathSource = id;
  }

  setPathTarget(id: string) {
    this.pathTarget = id;
  }

  async findPath() {
    if (!this.pathSource || !this.pathTarget) return;
    this.pathLoading = true;
    this.pathError = null;
    try {
      const result = await api.path(this.pathSource, this.pathTarget);
      runInAction(() => {
        this.pathResult = result;
        this.pathLoading = false;
      });
    } catch (e) {
      runInAction(() => {
        this.pathError = String(e);
        this.pathLoading = false;
      });
    }
  }

  // ── Model upload ──────────────────────────────────────────────────────────

  toggleTooltips() {
    this.showTooltips = !this.showTooltips;
  }

  toggleUseRai() {
    this.useRai = !this.useRai;
    if (this.anchorInstance) this.loadNeighbourhood();
  }

  async uploadModel(file: File) {
    try {
      const result = await api.parseModel(file);
      runInAction(() => {
        this.modelName = result.model_name;
        // Reset everything so the new model loads fresh
        this.semanticGraph = null;
        this.concepts = [];
        this.conceptCounts = {};
        this.instancePage = null;
        this.anchorInstance = null;
        this.neighbourhoodGraph = null;
      });
      await this.loadSemanticGraph();
    } catch (e) {
      console.error("Model upload failed:", e);
    }
  }
}

// Singleton — use via React context in _app.tsx
export const explorerStore = new ExplorerStore();
