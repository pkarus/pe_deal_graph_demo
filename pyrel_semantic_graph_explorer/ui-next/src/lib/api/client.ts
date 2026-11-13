/**
 * Typed API client for the FastAPI service.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  concept: string;
  label: string;
  attributes: Record<string, unknown>;
}

export interface GraphEdge {
  attributes?: Record<string, unknown>;
  id: string;
  source: string;
  target: string;
  relationship: string;
  label: string;
}

export interface GraphDTO {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ConceptSummary {
  name: string;
  source_table: string | null;
  identify_by: Array<{ name: string; type: string }>;
  property_count: number;
  relationship_count: number;
  computed_property_count: number;
}

export interface InstanceRow {
  concept: string;
  id_fields: Record<string, unknown>;
  label: string;
  attributes: Record<string, unknown>;
}

export interface InstancePage {
  concept: string;
  rows: InstanceRow[];
  limit: number;
  offset: number;
  total_count: number | null;
}

export interface ParseModelResult {
  model_name: string;
  concept_count: number;
  relationship_count: number;
  source_table_count: number;
}

export interface HealthResult {
  status: string;
  model: string | null;
  rai_config_loaded: boolean;
}

// ── Fetch helper ──────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ── API methods ───────────────────────────────────────────────────────────────

export const api = {
  health: () => apiFetch<HealthResult>("/api/health"),

  parseModel: async (file: File): Promise<ParseModelResult> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/api/parse-model`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return res.json();
  },

  semanticGraph: () => apiFetch<GraphDTO>("/api/semantic-graph"),

  concepts: () => apiFetch<ConceptSummary[]>("/api/concepts"),

  conceptCount: (concept: string) =>
    apiFetch<{ concept: string; count: number }>(`/api/concepts/${concept}/count`),

  instances: (
    concept: string,
    opts: { limit?: number; offset?: number; search?: string } = {}
  ) => {
    const params = new URLSearchParams();
    if (opts.limit) params.set("limit", String(opts.limit));
    if (opts.offset) params.set("offset", String(opts.offset));
    if (opts.search) params.set("search", opts.search);
    return apiFetch<InstancePage>(`/api/instances/${concept}?${params}`);
  },

  neighbourhood: (
    concept: string,
    id: string | number,
    opts: { depth?: number; max_nodes?: number; use_rai?: boolean } = {}
  ) => {
    const params = new URLSearchParams();
    if (opts.depth !== undefined) params.set("depth", String(opts.depth));
    if (opts.max_nodes) params.set("max_nodes", String(opts.max_nodes));
    if (opts.use_rai) params.set("use_rai", "true");
    return apiFetch<GraphDTO>(
      `/api/instance/${concept}/${id}/neighbourhood?${params}`
    );
  },

  path: (source: string, target: string) =>
    apiFetch<GraphDTO | null>(
      `/api/path?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}`
    ),
};
