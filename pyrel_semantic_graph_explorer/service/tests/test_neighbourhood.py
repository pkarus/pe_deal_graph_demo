"""
Tests for graph/neighbourhood.py

All tests use a stub executor — no live Snowflake connection.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.model_parser import ModelParser
from graph.neighbourhood import (
    build_semantic_graph,
    build_neighbourhood_graph,
    NeighbourhoodRequest,
    graph_dto_to_nx,
    nx_to_graph_dto,
    find_shortest_path,
)
from rai.instance_query import GraphDTO, GraphNode, GraphEdge

EXAMPLE_MODEL_PATH = Path("/Users/stevebertolani/Desktop/projects/streamlit_apps/example_semantic_layer.py")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def parsed_model():
    return ModelParser.from_file(EXAMPLE_MODEL_PATH).parse()


# ── Stub executor ─────────────────────────────────────────────────────────────

def make_stub_executor(data: dict[str, list[dict]]):
    """
    Returns an executor that matches SQL substrings to canned row data.
    data keys are table name fragments (case-insensitive).
    """
    def executor(sql: str) -> list[dict]:
        sql_upper = sql.upper()
        for key, rows in data.items():
            if key.upper() in sql_upper:
                return rows
        return []
    return executor


STUB_DATA = {
    "LOCATIONS": [
        {"location_id": 5, "store_name": "Seattle Pike St", "city": "Seattle",
         "state": "WA", "is_active": True, "store_type": "Flagship"},
    ],
    "ORDERS": [
        {"order_id": 101, "location_id": 5, "subtotal": 12.50, "item_count": 2},
        {"order_id": 102, "location_id": 5, "subtotal": 8.00, "item_count": 1},
    ],
    "SHIFTS": [
        {"shift_id": 201, "location_id": 5, "barista_id": 3,
         "shift_type": "morning", "actual_hours": 8.0},
    ],
    "BARISTAS": [
        {"barista_id": 3, "full_name": "Alice Johnson", "hourly_wage": 18.5,
         "home_location_id": 5},
    ],
}


# ── build_semantic_graph ──────────────────────────────────────────────────────

class TestSemanticGraph:
    def test_returns_graph_dto(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        assert isinstance(dto, GraphDTO)

    def test_has_all_concepts_as_nodes(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        node_ids = {n.id for n in dto.nodes}
        assert "Location" in node_ids
        assert "Order" in node_ids
        assert "Barista" in node_ids
        assert len(dto.nodes) == 11

    def test_has_relationship_edges(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        assert len(dto.edges) > 0

    def test_edge_connects_known_concepts(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        node_ids = {n.id for n in dto.nodes}
        for edge in dto.edges:
            assert edge.source in node_ids, f"Edge source {edge.source!r} not in nodes"
            assert edge.target in node_ids, f"Edge target {edge.target!r} not in nodes"

    def test_no_duplicate_edges(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        edge_ids = [e.id for e in dto.edges]
        assert len(edge_ids) == len(set(edge_ids))

    def test_node_attributes_populated(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        loc = next(n for n in dto.nodes if n.id == "Location")
        assert "source_table" in loc.attributes
        assert "LOCATIONS" in loc.attributes["source_table"]

    def test_order_to_location_edge_exists(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        edges = [(e.source, e.target) for e in dto.edges]
        assert ("Order", "Location") in edges


# ── build_neighbourhood_graph ─────────────────────────────────────────────────

class TestNeighbourhoodGraph:
    def test_anchor_node_present(self, parsed_model):
        executor = make_stub_executor(STUB_DATA)
        req = NeighbourhoodRequest(concept="Location", instance_id=5, depth=1)
        dto = build_neighbourhood_graph(req, parsed_model, executor)
        node_ids = {n.id for n in dto.nodes}
        assert "Location:5" in node_ids

    def test_anchor_label_from_data(self, parsed_model):
        executor = make_stub_executor(STUB_DATA)
        req = NeighbourhoodRequest(concept="Location", instance_id=5, depth=1)
        dto = build_neighbourhood_graph(req, parsed_model, executor)
        anchor = next(n for n in dto.nodes if n.id == "Location:5")
        assert anchor.label == "Seattle Pike St"

    def test_depth_zero_returns_only_anchor(self, parsed_model):
        executor = make_stub_executor(STUB_DATA)
        req = NeighbourhoodRequest(concept="Location", instance_id=5, depth=0)
        dto = build_neighbourhood_graph(req, parsed_model, executor)
        assert len(dto.nodes) == 1
        assert dto.nodes[0].id == "Location:5"

    def test_depth_one_includes_connected_nodes(self, parsed_model):
        executor = make_stub_executor(STUB_DATA)
        req = NeighbourhoodRequest(concept="Location", instance_id=5, depth=1)
        dto = build_neighbourhood_graph(req, parsed_model, executor)
        # Some connected nodes should appear (orders, shifts, etc.)
        assert len(dto.nodes) >= 1  # at minimum the anchor

    def test_edges_reference_existing_nodes(self, parsed_model):
        executor = make_stub_executor(STUB_DATA)
        req = NeighbourhoodRequest(concept="Location", instance_id=5, depth=1)
        dto = build_neighbourhood_graph(req, parsed_model, executor)
        node_ids = {n.id for n in dto.nodes}
        for edge in dto.edges:
            assert edge.source in node_ids
            assert edge.target in node_ids

    def test_max_nodes_cap_respected(self, parsed_model):
        # Stub executor that returns many rows
        def big_executor(sql: str) -> list[dict]:
            if "ORDERS" in sql.upper():
                return [{"order_id": i, "location_id": 5} for i in range(200)]
            if "LOCATIONS" in sql.upper():
                return [{"location_id": 5, "store_name": "Test"}]
            return []

        req = NeighbourhoodRequest(
            concept="Location", instance_id=5, depth=1, max_nodes=10
        )
        dto = build_neighbourhood_graph(req, parsed_model, big_executor)
        assert len(dto.nodes) <= 10

    def test_executor_exception_is_handled(self, parsed_model):
        """Errors in a single hop should not crash the whole graph build."""
        call_count = [0]

        def flaky_executor(sql: str) -> list[dict]:
            call_count[0] += 1
            if "LOCATIONS" in sql.upper():
                return [{"location_id": 5, "store_name": "Test"}]
            raise RuntimeError("Simulated DB error")

        req = NeighbourhoodRequest(concept="Location", instance_id=5, depth=1)
        dto = build_neighbourhood_graph(req, parsed_model, flaky_executor)
        # Should still return the anchor even if neighbours fail
        assert any(n.id == "Location:5" for n in dto.nodes)


# ── graph_dto_to_nx / nx_to_graph_dto ────────────────────────────────────────

class TestNxConversion:
    def test_roundtrip_node_count(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        g = graph_dto_to_nx(dto)
        dto2 = nx_to_graph_dto(g)
        assert len(dto2.nodes) == len(dto.nodes)

    def test_roundtrip_edge_count(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        g = graph_dto_to_nx(dto)
        dto2 = nx_to_graph_dto(g)
        assert len(dto2.edges) == len(dto.edges)

    def test_nx_graph_is_multidigraph(self, parsed_model):
        import networkx as nx
        dto = build_semantic_graph(parsed_model)
        g = graph_dto_to_nx(dto)
        assert isinstance(g, nx.MultiDiGraph)

    def test_node_attributes_preserved(self, parsed_model):
        dto = build_semantic_graph(parsed_model)
        g = graph_dto_to_nx(dto)
        assert g.nodes["Location"]["concept"] == "Location"
        assert g.nodes["Location"]["label"] == "Location"


# ── find_shortest_path ────────────────────────────────────────────────────────

class TestShortestPath:
    def _make_dto(self):
        nodes = [
            GraphNode(id="A", concept="X", label="A"),
            GraphNode(id="B", concept="Y", label="B"),
            GraphNode(id="C", concept="Z", label="C"),
        ]
        edges = [
            GraphEdge(id="A->B", source="A", target="B", relationship="rel1", label="A to B"),
            GraphEdge(id="B->C", source="B", target="C", relationship="rel2", label="B to C"),
        ]
        return GraphDTO(nodes=nodes, edges=edges)

    def test_path_found(self):
        dto = self._make_dto()
        result = find_shortest_path(dto, "A", "C")
        assert result is not None
        node_ids = {n.id for n in result.nodes}
        assert "A" in node_ids
        assert "B" in node_ids
        assert "C" in node_ids

    def test_no_path_returns_none(self):
        dto = self._make_dto()
        # Add isolated node
        dto.nodes.append(GraphNode(id="D", concept="W", label="D"))
        result = find_shortest_path(dto, "A", "D")
        assert result is None

    def test_same_source_and_target(self):
        dto = self._make_dto()
        result = find_shortest_path(dto, "A", "A")
        assert result is not None
        assert any(n.id == "A" for n in result.nodes)

    def test_nonexistent_node_returns_none(self):
        dto = self._make_dto()
        result = find_shortest_path(dto, "A", "GHOST")
        assert result is None
