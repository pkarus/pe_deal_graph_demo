# PyREL Semantic Layer Graph Explorer

An interactive graph exploration tool for PyREL semantic layer models. Upload any PyREL `.py` model file and explore your ontology visually — then drill down from schema-level concepts to actual Snowflake data instances, traversing relationships at the data layer.

## Overview

Two linked views:

- **Semantic View** — the ontology graph. Concepts as nodes, relationships as edges, live instance counts as badges. Click a concept to highlight it; double-click or press "Explore instances →" to pivot to the Data View.
- **Data View** — actual data from Snowflake. Three tabs:
  - **Browse** — paginated, searchable list of instances for any concept
  - **Neighbourhood** — ego graph around a selected instance, configurable depth (0–3)
  - **Semantic Exploration** — two modes: free-form graph expansion (click a concept to seed, click any node to expand its neighbours) and shortest-path finding between any two nodes

The two views are linked: navigating from the semantic graph into data and back preserves context throughout. The header provides **Tooltips**, **SQL/PyREL query mode**, and **Upload model** controls.

## Architecture

```
ui-next/          Next.js 15 frontend (React, Cytoscape.js, MobX)
service/          Python FastAPI backend
  parser/         AST-based PyREL model file parser
  rai/            RAI SDK client + Snowflake query builder
  graph/          NetworkX neighbourhood graph builder
```

The service parses the model file statically (no execution) and uses the extracted schema — including physical column names from `model.define()` calls — to generate Snowflake SQL queries at runtime.

## Quick Start

You need two terminals — one for the backend service, one for the frontend.

### Terminal 1 — Backend service

```bash
cd service
uv venv
uv pip install fastapi "uvicorn[standard]" networkx "relationalai>=0.12" toml pydantic "python-multipart>=0.0.9" pytest "pytest-asyncio>=0.23" httpx snowflake-connector-python
.venv/bin/uvicorn main:app --reload
# → http://localhost:8000
```

> **Note:** Use `uv pip install` (not `uv pip install -e ".[dev]"`) — the `setuptools.backends` editable install has a compatibility issue with newer Python versions.
>
> **Snowflake column casing:** If your Snowflake tables use lowercase quoted identifiers (common with PyREL models), column names in WHERE clauses must be double-quoted. The service handles this automatically — all filter and JOIN columns are quoted in generated SQL.

The service auto-loads `~/.rai/raiconfig.toml` on startup for Snowflake credentials, and looks for the default model file at `~/Desktop/projects/streamlit_apps/example_semantic_layer.py`. Both can be overridden:

```bash
RAI_CONFIG_PATH=/path/to/raiconfig.toml \
RAI_MODEL_PATH=/path/to/your_model.py \
.venv/bin/uvicorn main:app --reload
```

### Terminal 2 — Frontend

```bash
cd ui-next
npm install
npm run dev
# → http://localhost:3000
```

Open **http://localhost:3000** in your browser.

Set `NEXT_PUBLIC_API_URL` if the service is not on `http://localhost:8000`:

```bash
NEXT_PUBLIC_API_URL=https://your-service.example.com npm run dev
```

### What you'll see

- **Semantic View** (default) — the ontology as an interactive Cytoscape graph. All concepts appear as coloured nodes, relationships as directed edges. Click a concept to highlight it, then press **"Explore instances →"** to switch to the Data View for that concept.
- **Data View** — three tabs:
  - **Browse** — live paginated rows from Snowflake. Click any row to anchor it as the neighbourhood graph centre.
  - **Neighbourhood** — ego graph around the selected instance. Use the depth selector (0–3) to expand outward. Click any node to re-anchor.
  - **Semantic Exploration** — Explore mode: click a concept pill to seed the graph, then click any node to expand its neighbours from the ontology. Find Path mode: type or click two concept names to find the shortest relationship path.
- **Tooltips On/Off** button in the header — toggles hover tooltips showing node attributes in-context.
- **SQL / PyREL** toggle in the header — switches the Neighbourhood tab between raw Snowflake SQL queries (default) and PyREL DSL queries via the RAI reasoner (requires a live engine; button only appears if the executor loaded at startup).
- **Upload model** button in the header — swap in any PyREL `.py` model file to explore a different semantic layer.

> The Semantic View works immediately from the model file with no Snowflake connection. Browse and Neighbourhood tabs require the backend service to be running with valid Snowflake credentials.

### Upload a model

The app loads the default model on startup. To switch models, click **Upload model** in the header and select any PyREL `.py` file.

## Connection Config (`raiconfig.toml`)

The service reads standard PyREL `raiconfig.toml` format:

```toml
active_profile = "default"

[profile.default]
platform = "snowflake"
user = "you@example.com"
account = "myorg-myaccount"
role = "MY_ROLE"
warehouse = "MY_WH"
rai_app_name = "RELATIONALAI"
authenticator = "snowflake"
```

Discovery order: `~/.rai/raiconfig.toml` → `$RAI_CONFIG_PATH` → repo root.

## Model File Format

The explorer parses any PyREL model file of this shape:

```python
from relationalai.semantics import Model, Bool, Float, Integer, String

model = Model("my_model")

class Sources:
    class db:
        class schema:
            orders = model.Table("MY_DB.MY_SCHEMA.ORDERS")

Order = model.Concept("Order", identify_by={"Order ID": Integer})
model.define(Order.new(order_id=Sources.db.schema.orders.order_id))

Order.at_location = model.Relationship(
    f"{Order} placed {Location}", short_name="order_at_location"
)
model.define(
    Order.filter_by(Order_ID=Sources.db.schema.orders.Order_ID)
         .at_location(Location.filter_by(Location_ID=Sources.db.schema.orders.Location_ID), ...)
)
```

The parser extracts: concepts, identify-by fields, physical PK column names (from `.new()` calls), relationship FK column mappings (from `filter_by()` chains), scalar properties (typed), source table mappings, and computed properties from `@define` extension blocks — all without executing the file.

## RAI Query Executor (Prototype)

`service/rai/rai_query_executor.py` contains a prototype for querying the semantic layer via the RelationalAI Python library instead of hand-crafted SQL. This enables:

- **Computed/derived properties** — `years_of_service`, `profit_margin`, `violates_overtime_limit`, and other `@define`-block computed properties are evaluated server-side by the RAI reasoner
- **Business rule filtering** — filter instances by predicates like `valid_hourly_wage == True`
- **Multi-hop traversals** — natural dot-notation relationship chaining
- **Aggregations** — `count().per(concept)`, `sum()`, `avg()` via the PyREL DSL

```python
from rai.rai_query_executor import RaiQueryExecutor

executor = RaiQueryExecutor.from_model_file("model.py", parsed_model)

# Fetch with computed properties
page = executor.fetch_instances(
    "Barista",
    include_computed=["years_of_service", "valid_hourly_wage"],
    limit=50,
)

# Filter by computed predicate
df = executor.fetch_instances_with_computed(
    "Barista",
    computed_properties=["years_of_service", "valid_hourly_wage"],
    filter_computed={"valid_hourly_wage": True},
)

# Neighbourhood via relationship traversal
graph = executor.fetch_neighbourhood("Barista", pk_value=5, depth=2)
```

Requires `pip install relationalai` and a live RAI engine. Designed as a drop-in alongside the existing `QueryPlanner`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Service health + loaded model name |
| `POST` | `/api/parse-model` | Upload a `.py` model file |
| `GET` | `/api/semantic-graph` | Full ontology graph DTO |
| `GET` | `/api/concepts` | Concept list with metadata |
| `GET` | `/api/concepts/{concept}/count` | Instance count for a concept |
| `GET` | `/api/instances/{concept}` | Paginated rows (`limit`, `offset`, `search`) |
| `GET` | `/api/instance/{concept}/{id}/neighbourhood` | Ego graph (`depth`, `max_nodes`) |
| `GET` | `/api/path` | Shortest path between two node IDs |

Interactive docs at `http://localhost:8000/docs`.

## Running Tests

```bash
cd service
.venv/bin/python -m pytest tests/ -v
# 116 tests, 0 failures
```

Tests cover: model parser (including the real `example_semantic_layer.py`), RAI client config loading, SQL query builder, neighbourhood graph builder, and all FastAPI endpoints — all offline, no live Snowflake connection required.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend framework | Next.js 15, React 19, TypeScript |
| Graph visualization | Cytoscape.js + cytoscape-fcose + cytoscape-dagre |
| State management | MobX |
| Styling | Tailwind CSS |
| Backend framework | FastAPI + uvicorn |
| Graph algorithms | NetworkX (MultiDiGraph, BFS, shortest path) |
| Model parsing | Python `ast` module (static, no execution) |
| Physical column mapping | Extracted from PyREL `model.define()` AST |
| Data connection | Snowflake via snowflake-connector-python |
| RAI query layer (prototype) | RelationalAI Python SDK (`relationalai`) |
| Config | PyREL `raiconfig.toml` standard format |

## Inspiration

This project draws from two internal tools:

- **[by-plat-jdp-sna-kg-mirror](https://github.com/sjbertolani/by-plat-jdp-sna-kg-mirror)** — knowledge graph and network analysis tooling for large-scale data exploration, including the idea of bridging ontology-level schema navigation with instance-level data traversal
- **[semantic-search](https://github.com/sjbertolani/semantic-search)** — semantic layer exploration with Cytoscape.js, the graph layout and concept colouring approach, and the two-view (schema ↔ data) architecture pattern
