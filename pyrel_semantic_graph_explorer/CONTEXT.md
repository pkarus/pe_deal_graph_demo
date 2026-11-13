# Project Context

## What it is

A full-stack interactive graph exploration tool for PyREL semantic layer models. Upload any PyREL `.py` model file and explore the ontology visually, then drill from schema-level concepts into actual Snowflake data instances, traversing relationships at the data layer.

**GitHub:** `github.com:sjbertolani/pyrel_graph_explorer.git`
**Local path:** `/Users/stevebertolani/software/PYREL_SEMANTIC_LAYER_GRAPH_EXPLORER/`

---

## Two Views

- **Semantic View** — ontology graph (concepts as nodes, relationships as edges). Built from static AST parse of the model file. Shows live instance counts as badges (fetched lazily from Snowflake). Double-click concept → pivot to Data View.
- **Data View** — actual Snowflake data. Three tabs:
  - **Browse** — paginated searchable list of instances for any concept
  - **Neighbourhood** — ego graph (BFS) around a selected instance, depth 0–3
  - **Path Finder** — shortest path between two concept/instance node IDs

---

## Architecture

```
PYREL_SEMANTIC_LAYER_GRAPH_EXPLORER/
├── service/          Python FastAPI backend
│   ├── parser/       AST parser for PyREL model files
│   ├── rai/          RAI client (raiconfig.toml) + SQL query builder
│   ├── graph/        NetworkX neighbourhood graph builder
│   ├── tests/        116 tests, all passing
│   └── main.py       FastAPI app (9 endpoints)
├── ui-next/          Next.js 15 frontend
│   └── src/
│       ├── lib/api/client.ts         typed API client
│       ├── lib/store/ExplorerStore.ts MobX store
│       └── lib/components/
│           ├── shared/CytoscapeGraph.tsx
│           ├── semantic/SemanticView.tsx
│           └── data/{DataView,BrowseTab,NeighbourhoodTab,PathTab}.tsx
└── README.md
```

---

## Key Technical Decisions

**Model parser is purely static (AST, no execution).** The PyREL model file often contains invalid Python syntax — multi-word identifiers with spaces in keyword arg positions (e.g. `filter_by(Menu Item ID=...)`). Fixed by `_sanitize_source()` regex preprocessor before `ast.parse()`. F-string `{Float:Label}` tokens parse as `FormattedValue` with `format_spec`, not as subscripts.

**No by-plat-jdp dependency for core graph queries.** The by-plat-jdp supply chain repo was the inspiration for graph algorithms (compression, aggregation, critical paths) but the actual data queries are done via direct Snowflake SQL built from the parsed model. NetworkX is used for BFS and shortest path only.

**Executor is injected (not global).** The Snowflake query function is a callable passed into graph builders, making all graph logic fully testable offline with stub executors.

**MultiDiGraph not DiGraph.** Concept pairs can share multiple relationship types (e.g. Barista→Location via both `barista_shift` and `barista_home_location`). DiGraph would silently drop duplicate edges.

**Cytoscape.js for visualization.** Kept consistent with the `semantic-search` repo. Uses fcose (force-directed) for neighbourhood graphs, dagre (hierarchical) for path views. Per-concept colour coding matches by-plat-jdp visual style conventions.

---

## Connection Config

Connection is via `~/.rai/raiconfig.toml`:
- Account: `ndsoebe-rai_sales_engineering_aws_us_west_2`
- RAI app: `RELATIONALAI`
- Warehouse: `RAI_XS`
- Auth: `username_password_mfa`

Discovery order: `~/.rai/raiconfig.toml` → `$RAI_CONFIG_PATH` → repo root.

---

## Example Model

Primary test model: `/Users/stevebertolani/Desktop/projects/streamlit_apps/example_semantic_layer.py`
- Model name: `coffee_shop_vp_ops`
- 11 concepts: MenuItem, InventoryItem, InventoryTransaction, Shift, OrderItem, LoyaltyMember, LocationDailyMetrics, Location, SupplyTransfer, Order, Barista
- 11 Snowflake source tables: `BESPOKE.COFFEE_SHOP_VP_OPS.*`
- 15+ relationships
- Business rules extension with computed properties (profit_margin, years_of_service, churn_risk_score, etc.)

---

## Running

```bash
# Service
cd service && .venv/bin/uvicorn main:app --reload

# UI
cd ui-next && npm run dev

# Tests
cd service && .venv/bin/python -m pytest tests/ -v
```

Note: the service needs `snowflake-connector-python` installed separately (not in pyproject.toml yet) for live Snowflake queries. The parser and graph builder work fully offline.

---

## Related Repos (used as references)

- `/Users/stevebertolani/software/semantic-search` — existing production ontology explorer (Go backend, Next.js/Cytoscape frontend). This project was inspired by and borrows patterns from it.
- `/Users/stevebertolani/software/by-plat-jdp-sna-kg-mirror` — supply chain knowledge graph (Python/NetworkX/PyREL). Compression, aggregation, and critical path algorithms came from here conceptually.
