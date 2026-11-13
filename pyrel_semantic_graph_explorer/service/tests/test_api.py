"""
Tests for main.py FastAPI routes.

Uses httpx AsyncClient with the app in test mode.
Snowflake calls are intercepted by patching _get_executor to return a stub.
"""
import sys
import io
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

# Pre-load the real model into app state before importing the app
from parser.model_parser import ModelParser
from rai.instance_query import QueryPlanner

EXAMPLE_MODEL_PATH = Path("/Users/stevebertolani/Desktop/projects/streamlit_apps/example_semantic_layer.py")

import main as app_module

# Patch state before running tests
_parsed = ModelParser.from_file(EXAMPLE_MODEL_PATH).parse()
app_module._state.parsed_model = _parsed
app_module._state.planner = QueryPlanner(_parsed)

from main import app

client = TestClient(app, raise_server_exceptions=True)


# ── Stub data ─────────────────────────────────────────────────────────────────

STUB_LOCATIONS = [
    {"location_id": 5, "store_name": "Seattle Pike St", "city": "Seattle",
     "state": "WA", "is_active": True, "store_type": "Flagship",
     "monthly_rent": 8500.0, "square_footage": 1200},
    {"location_id": 6, "store_name": "Portland Burnside", "city": "Portland",
     "state": "OR", "is_active": True, "store_type": "Standard"},
]

STUB_ORDERS = [
    {"order_id": 101, "location_id": 5, "subtotal": 12.50, "item_count": 2,
     "order_channel": "mobile"},
]

STUB_BARISTAS = [
    {"barista_id": 3, "full_name": "Alice Johnson", "hourly_wage": 18.5,
     "home_location_id": 5, "is_active": True},
]


def make_stub_executor(data: dict):
    def executor(sql: str) -> list[dict]:
        sql_up = sql.upper()
        for key, rows in data.items():
            if key.upper() in sql_up:
                if "COUNT" in sql_up:
                    return [{"cnt": len(rows)}]
                return rows
        return []
    return executor


# ── /api/health ───────────────────────────────────────────────────────────────

def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_health_shows_model_name():
    r = client.get("/api/health")
    assert r.json()["model"] == "coffee_shop_vp_ops"


# ── /api/concepts ─────────────────────────────────────────────────────────────

def test_list_concepts_returns_11():
    r = client.get("/api/concepts")
    assert r.status_code == 200
    assert len(r.json()) == 11


def test_list_concepts_has_location():
    r = client.get("/api/concepts")
    names = [c["name"] for c in r.json()]
    assert "Location" in names
    assert "Order" in names
    assert "Barista" in names


def test_concept_has_required_fields():
    r = client.get("/api/concepts")
    location = next(c for c in r.json() if c["name"] == "Location")
    assert "source_table" in location
    assert "identify_by" in location
    assert "property_count" in location
    assert "relationship_count" in location
    assert "computed_property_count" in location


def test_location_source_table():
    r = client.get("/api/concepts")
    location = next(c for c in r.json() if c["name"] == "Location")
    assert "LOCATIONS" in location["source_table"]


# ── /api/semantic-graph ───────────────────────────────────────────────────────

def test_semantic_graph_has_nodes():
    r = client.get("/api/semantic-graph")
    assert r.status_code == 200
    data = r.json()
    assert len(data["nodes"]) == 11


def test_semantic_graph_has_edges():
    r = client.get("/api/semantic-graph")
    data = r.json()
    assert len(data["edges"]) > 0


def test_semantic_graph_node_shape():
    r = client.get("/api/semantic-graph")
    node = r.json()["nodes"][0]
    assert "id" in node
    assert "concept" in node
    assert "label" in node
    assert "attributes" in node


def test_semantic_graph_edge_shape():
    r = client.get("/api/semantic-graph")
    edge = r.json()["edges"][0]
    assert "id" in edge
    assert "source" in edge
    assert "target" in edge
    assert "relationship" in edge


# ── /api/parse-model ──────────────────────────────────────────────────────────

def test_parse_model_upload():
    source = EXAMPLE_MODEL_PATH.read_bytes()
    r = client.post(
        "/api/parse-model",
        files={"file": ("example_semantic_layer.py", source, "text/plain")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["model_name"] == "coffee_shop_vp_ops"
    assert data["concept_count"] == 11


def test_parse_model_rejects_non_py():
    r = client.post(
        "/api/parse-model",
        files={"file": ("model.json", b"{}", "application/json")},
    )
    assert r.status_code == 400


def test_parse_model_invalid_python():
    r = client.post(
        "/api/parse-model",
        files={"file": ("bad.py", b"this is not python !!!", "text/plain")},
    )
    # Should parse (no syntax error) but return empty model — or 422
    # An unparseable file should still return 422 or a valid empty result
    assert r.status_code in (200, 422)


# ── /api/instances/{concept} ──────────────────────────────────────────────────

def test_get_instances_uses_stub():
    stub = make_stub_executor({"LOCATIONS": STUB_LOCATIONS})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/instances/Location")
    assert r.status_code == 200
    data = r.json()
    assert data["concept"] == "Location"
    assert len(data["rows"]) == 2


def test_get_instances_row_shape():
    stub = make_stub_executor({"LOCATIONS": STUB_LOCATIONS})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/instances/Location")
    row = r.json()["rows"][0]
    assert "id_fields" in row
    assert "label" in row
    assert "attributes" in row


def test_get_instances_label_from_store_name():
    stub = make_stub_executor({"LOCATIONS": STUB_LOCATIONS})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/instances/Location")
    labels = [row["label"] for row in r.json()["rows"]]
    assert "Seattle Pike St" in labels


def test_get_instances_unknown_concept_404():
    stub = make_stub_executor({})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/instances/Unicorn")
    assert r.status_code == 404


def test_get_instances_limit_param():
    stub = make_stub_executor({"LOCATIONS": STUB_LOCATIONS})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/instances/Location?limit=1")
    # Stub returns all, but limit is passed through in SQL
    assert r.status_code == 200
    assert r.json()["limit"] == 1


# ── /api/concepts/{concept}/count ─────────────────────────────────────────────

def test_concept_count():
    stub = make_stub_executor({"LOCATIONS": STUB_LOCATIONS})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/concepts/Location/count")
    assert r.status_code == 200
    assert r.json()["concept"] == "Location"
    assert "count" in r.json()


def test_concept_count_unknown_404():
    stub = make_stub_executor({})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/concepts/Ghost/count")
    assert r.status_code == 404


# ── /api/instance/{concept}/{id}/neighbourhood ───────────────────────────────

def test_neighbourhood_returns_anchor():
    stub = make_stub_executor({"LOCATIONS": STUB_LOCATIONS, "ORDERS": STUB_ORDERS})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/instance/Location/5/neighbourhood?depth=1")
    assert r.status_code == 200
    node_ids = [n["id"] for n in r.json()["nodes"]]
    assert "Location:5" in node_ids


def test_neighbourhood_depth_zero():
    stub = make_stub_executor({"LOCATIONS": STUB_LOCATIONS})
    with patch.object(app_module, "_get_executor", return_value=stub):
        r = client.get("/api/instance/Location/5/neighbourhood?depth=0")
    assert r.status_code == 200
    assert len(r.json()["nodes"]) == 1


# ── /api/path ─────────────────────────────────────────────────────────────────

def test_path_between_connected_concepts():
    r = client.get("/api/path?source=Order&target=Location")
    assert r.status_code == 200
    data = r.json()
    assert data is not None
    node_ids = [n["id"] for n in data["nodes"]]
    assert "Order" in node_ids
    assert "Location" in node_ids


def test_path_same_source_and_target():
    r = client.get("/api/path?source=Location&target=Location")
    assert r.status_code == 200
    assert r.json() is not None


def test_path_no_connection_returns_null():
    # In the schema graph, all concepts are connected via Location
    # but we can test with a concept that truly has no path — use non-existent
    r = client.get("/api/path?source=GHOST_A&target=GHOST_B")
    assert r.status_code == 200
    assert r.json() is None
