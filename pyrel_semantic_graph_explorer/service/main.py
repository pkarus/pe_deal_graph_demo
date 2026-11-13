"""
PyREL Semantic Layer Graph Explorer — FastAPI service.

Endpoints
---------
POST /api/parse-model          Upload a .py model file; returns parsed schema
GET  /api/semantic-graph       Full ontology graph (nodes = concepts, edges = relationships)
GET  /api/concepts             List of all concept names with instance counts
GET  /api/instances/{concept}  Paginated data rows for a concept
GET  /api/instance/{concept}/{id}/neighbourhood  Ego graph around one instance
GET  /api/path                 Shortest path between two instance node IDs in the semantic graph
GET  /api/health               Liveness check
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from parser.model_parser import ModelParser, ParsedModel
from rai.client import load_rai_config, RaiConfig, ConfigError
from rai.instance_query import (
    GraphDTO, GraphEdge, GraphNode, InstancePage, QueryPlanner,
    instance_to_node, row_to_instance,
)
from graph.neighbourhood import (
    NeighbourhoodRequest,
    build_neighbourhood_graph,
    build_semantic_graph,
    find_shortest_path,
)


# ── App state ─────────────────────────────────────────────────────────────────

class AppState:
    parsed_model: Optional[ParsedModel] = None
    planner: Optional[QueryPlanner] = None
    rai_config: Optional[RaiConfig] = None
    rai_executor: Optional[Any] = None   # RaiQueryExecutor if available


_state = AppState()


# ── Snowflake executor factory ────────────────────────────────────────────────

def _make_executor(config: RaiConfig):
    """
    Return a callable that runs a SQL string against Snowflake and returns
    list[dict].  Uses snowflake-connector-python directly (no RAI SDK
    needed for raw SQL queries against the source tables).

    If snowflake-connector-python is not installed or credentials are missing,
    returns a stub executor that raises a clear error.
    """
    try:
        import snowflake.connector  # type: ignore[import]
    except ImportError:
        def missing_executor(sql: str):  # type: ignore[return]
            raise HTTPException(
                status_code=503,
                detail="snowflake-connector-python is not installed. "
                       "Run: pip install snowflake-connector-python",
            )
        return missing_executor

    password = config._raw.get("password", os.environ.get("SNOWFLAKE_PASSWORD", ""))
    passcode = config._raw.get("passcode", os.environ.get("SNOWFLAKE_PASSCODE", ""))

    connect_kwargs: dict[str, Any] = dict(
        user=config.user,
        account=config.account,
        role=config.role,
        warehouse=config.warehouse,
        authenticator=config.authenticator,
    )
    if password:
        connect_kwargs["password"] = password
    if passcode and config.authenticator in ("username_password_mfa",):
        connect_kwargs["passcode"] = passcode

    def executor(sql: str) -> list[dict]:
        conn = snowflake.connector.connect(**connect_kwargs)
        try:
            cur = conn.cursor(snowflake.connector.DictCursor)
            cur.execute(sql)
            return cur.fetchall()
        finally:
            conn.close()

    return executor


# ── Lifespan: load config and default model on startup ────────────────────────

DEFAULT_MODEL_PATH = os.environ.get(
    "RAI_MODEL_PATH",
    str(Path.home() / "Desktop/projects/streamlit_apps/example_semantic_layer.py"),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load RAI config
    try:
        _state.rai_config = load_rai_config()
    except ConfigError as e:
        print(f"[startup] Warning: could not load raiconfig.toml — {e}")

    # Load default model if it exists
    model_path = Path(DEFAULT_MODEL_PATH)
    if model_path.exists():
        try:
            _state.parsed_model = ModelParser.from_file(model_path).parse()
            _state.planner = QueryPlanner(_state.parsed_model)
            print(f"[startup] Loaded model '{_state.parsed_model.model_name}' "
                  f"({len(_state.parsed_model.concepts)} concepts)")
        except Exception as e:
            print(f"[startup] Warning: could not parse default model — {e}")

    # Try to load the RAI query executor (requires relationalai SDK + live engine)
    if model_path.exists() and _state.parsed_model:
        try:
            from rai.rai_query_executor import RaiQueryExecutor
            from parser.model_parser import _sanitize_source
            # Patch load_model_namespace to sanitize PyREL DSL before exec()
            import rai.rai_query_executor as _rqe
            _original_load = _rqe.load_model_namespace
            def _sanitized_load(model_path_arg, **kw):
                from pathlib import Path as _Path
                source = _Path(model_path_arg).read_text()
                sanitized = _sanitize_source(source)
                ns: dict = {"__file__": str(model_path_arg)}
                exec(compile(sanitized, str(model_path_arg), "exec"), ns)
                return ns
            _rqe.load_model_namespace = _sanitized_load
            _state.rai_executor = RaiQueryExecutor.from_model_file(
                model_path, _state.parsed_model
            )
            print(f"[startup] RAI query executor loaded")
        except Exception as e:
            print(f"[startup] RAI executor not available: {e}")

    yield  # app runs here


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="PyREL Semantic Layer Graph Explorer",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_model() -> ParsedModel:
    if _state.parsed_model is None:
        raise HTTPException(
            status_code=400,
            detail="No model loaded. POST to /api/parse-model first.",
        )
    return _state.parsed_model


def _require_planner() -> QueryPlanner:
    if _state.planner is None:
        raise HTTPException(status_code=400, detail="No model loaded.")
    return _state.planner


def _get_executor():
    if _state.rai_config is None:
        raise HTTPException(
            status_code=503,
            detail="RAI/Snowflake config not loaded.",
        )
    return _make_executor(_state.rai_config)


# ── Pydantic response models ──────────────────────────────────────────────────

class NodeOut(BaseModel):
    id: str
    concept: str
    label: str
    attributes: dict[str, Any]


class EdgeOut(BaseModel):
    id: str
    source: str
    target: str
    relationship: str
    label: str


class GraphOut(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class ConceptSummary(BaseModel):
    name: str
    source_table: Optional[str]
    identify_by: list[dict]
    property_count: int
    relationship_count: int
    computed_property_count: int


class InstanceOut(BaseModel):
    concept: str
    id_fields: dict[str, Any]
    label: str
    attributes: dict[str, Any]


class InstancePageOut(BaseModel):
    concept: str
    rows: list[InstanceOut]
    limit: int
    offset: int
    total_count: Optional[int]


# ── Converters ────────────────────────────────────────────────────────────────

def _dto_to_out(dto: GraphDTO) -> GraphOut:
    return GraphOut(
        nodes=[NodeOut(id=n.id, concept=n.concept, label=n.label, attributes=n.attributes)
               for n in dto.nodes],
        edges=[EdgeOut(id=e.id, source=e.source, target=e.target,
                       relationship=e.relationship, label=e.label)
               for e in dto.edges],
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": _state.parsed_model.model_name if _state.parsed_model else None,
        "rai_config_loaded": _state.rai_config is not None,
        "rai_executor_available": _state.rai_executor is not None,
    }


@app.post("/api/parse-model")
async def parse_model(file: UploadFile = File(...)):
    """Upload a PyREL .py model file and parse it."""
    if not file.filename or not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="File must be a .py model file.")
    content = await file.read()
    try:
        source = content.decode("utf-8")
        parsed = ModelParser(source).parse()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse model: {e}")

    _state.parsed_model = parsed
    _state.planner = QueryPlanner(parsed)

    return {
        "model_name": parsed.model_name,
        "concept_count": len(parsed.concepts),
        "relationship_count": len(parsed.relationships),
        "source_table_count": len(parsed.source_tables),
    }


@app.get("/api/semantic-graph", response_model=GraphOut)
def semantic_graph():
    """Full ontology graph — one node per concept, edges for relationships."""
    model = _require_model()
    dto = build_semantic_graph(model)
    return _dto_to_out(dto)


@app.get("/api/concepts", response_model=list[ConceptSummary])
def list_concepts():
    """List all concepts with their metadata."""
    model = _require_model()
    return [
        ConceptSummary(
            name=c.name,
            source_table=c.source_table,
            identify_by=c.identify_by,
            property_count=len(c.properties),
            relationship_count=len(c.relationships),
            computed_property_count=len(c.computed_properties),
        )
        for c in model.concepts
    ]


@app.get("/api/instances/{concept}", response_model=InstancePageOut)
def get_instances(
    concept: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
):
    """Fetch paginated data rows for a concept from Snowflake."""
    model = _require_model()
    planner = _require_planner()
    executor = _get_executor()

    try:
        planner.get_concept(concept)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    concept_def = next(c for c in model.concepts if c.name == concept)
    sql = planner.fetch_sql(concept, limit=limit, offset=offset, search=search)

    try:
        rows = executor(sql)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Database query failed: {e}")

    instances = [row_to_instance(concept_def, row) for row in rows]
    return InstancePageOut(
        concept=concept,
        rows=[InstanceOut(concept=i.concept, id_fields=i.id_fields,
                          label=i.label, attributes=i.attributes)
              for i in instances],
        limit=limit,
        offset=offset,
        total_count=None,  # count query is separate for performance
    )


@app.get("/api/concepts/{concept}/count")
def concept_count(concept: str):
    """Return the number of instances for a concept."""
    planner = _require_planner()
    executor = _get_executor()

    try:
        sql = planner.count_sql(concept)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        rows = executor(sql)
        count = rows[0].get("CNT", rows[0].get("cnt", 0)) if rows else 0
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Database query failed: {e}")

    return {"concept": concept, "count": count}


@app.get("/api/instance/{concept}/{instance_id}/neighbourhood", response_model=GraphOut)
def instance_neighbourhood(
    concept: str,
    instance_id: str,
    depth: int = Query(default=1, ge=0, le=3),
    max_nodes: int = Query(default=150, ge=10, le=500),
    use_rai: bool = Query(default=False),
):
    """Ego graph around a single data instance."""
    model = _require_model()
    executor = _get_executor()

    # Try to coerce instance_id to int for numeric PKs
    parsed_id: Any = instance_id
    try:
        parsed_id = int(instance_id)
    except ValueError:
        pass

    # Use RAI executor if requested and available
    if use_rai and _state.rai_executor is not None:
        try:
            dto = _state.rai_executor.fetch_neighbourhood(
                concept, pk_value=parsed_id, depth=depth, max_nodes=max_nodes
            )
            return _dto_to_out(dto)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"RAI executor error: {e}")

    req = NeighbourhoodRequest(
        concept=concept,
        instance_id=parsed_id,
        depth=depth,
        max_nodes=max_nodes,
    )
    try:
        dto = build_neighbourhood_graph(req, model, executor)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _dto_to_out(dto)


@app.get("/api/path", response_model=Optional[GraphOut])
def shortest_path(
    source: str = Query(..., description="Source node ID, e.g. 'Location:5'"),
    target: str = Query(..., description="Target node ID, e.g. 'Barista:3'"),
):
    """
    Find the shortest path between two node IDs within the semantic graph.
    Returns null if no path exists.
    """
    model = _require_model()
    dto = build_semantic_graph(model)
    result = find_shortest_path(dto, source, target)
    if result is None:
        return None
    return _dto_to_out(result)
