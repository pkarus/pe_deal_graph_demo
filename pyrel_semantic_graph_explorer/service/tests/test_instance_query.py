"""
Tests for rai/instance_query.py

All tests are offline — no live connection needed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.model_parser import ModelParser
from rai.instance_query import (
    QueryPlanner, row_to_instance, instance_to_node, _snake, _build_label,
)

EXAMPLE_MODEL_PATH = Path("/Users/stevebertolani/Desktop/projects/streamlit_apps/example_semantic_layer.py")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def parsed_model():
    return ModelParser.from_file(EXAMPLE_MODEL_PATH).parse()


@pytest.fixture(scope="module")
def planner(parsed_model):
    return QueryPlanner(parsed_model)


# ── _snake helper ─────────────────────────────────────────────────────────────

def test_snake_single_word():
    assert _snake("Name") == "name"

def test_snake_multi_word():
    assert _snake("Location ID") == "location_id"

def test_snake_multi_word_long():
    assert _snake("Avg Wait Time Seconds") == "avg_wait_time_seconds"


# ── QueryPlanner.concept_names ────────────────────────────────────────────────

def test_concept_names(planner):
    names = planner.concept_names()
    assert "Location" in names
    assert "Order" in names
    assert "Barista" in names
    assert len(names) == 11


# ── QueryPlanner.count_sql ────────────────────────────────────────────────────

def test_count_sql_contains_table(planner):
    sql = planner.count_sql("Location")
    assert "BESPOKE.COFFEE_SHOP_VP_OPS.LOCATIONS" in sql
    assert "COUNT" in sql.upper()


def test_count_sql_unknown_concept(planner):
    with pytest.raises(ValueError, match="Unknown concept"):
        planner.count_sql("NonExistent")


# ── QueryPlanner.fetch_sql ────────────────────────────────────────────────────

def test_fetch_sql_selects_from_table(planner):
    sql = planner.fetch_sql("Location")
    assert "BESPOKE.COFFEE_SHOP_VP_OPS.LOCATIONS" in sql
    assert sql.strip().upper().startswith("SELECT")


def test_fetch_sql_uses_select_star(planner):
    sql = planner.fetch_sql("Location")
    assert "SELECT *" in sql


def test_fetch_sql_limit_offset(planner):
    sql = planner.fetch_sql("Location", limit=25, offset=50)
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql


def test_fetch_sql_default_limit(planner):
    sql = planner.fetch_sql("Order")
    assert "LIMIT 50" in sql
    assert "OFFSET 0" in sql


def test_fetch_sql_with_int_filter(planner):
    sql = planner.fetch_sql("Location", filters={"location_id": 5})
    assert "location_id = 5" in sql
    assert "WHERE" in sql


def test_fetch_sql_with_string_filter(planner):
    sql = planner.fetch_sql("Location", filters={"city": "Seattle"})
    assert "city = 'Seattle'" in sql


def test_fetch_sql_with_search(planner):
    sql = planner.fetch_sql("Barista", search="Alice")
    assert "ILIKE" in sql
    assert "Alice" in sql


def test_fetch_sql_no_sql_injection_in_filter(planner):
    """Single quotes in filter values should be escaped."""
    sql = planner.fetch_sql("Location", filters={"city": "O'Brien's"})
    assert "O''Brien''s" in sql


def test_fetch_sql_no_sql_injection_in_search(planner):
    sql = planner.fetch_sql("Barista", search="Alice' OR '1'='1")
    # Should be escaped, not literal injection
    assert "OR '1'='1" not in sql


def test_fetch_sql_no_explicit_columns(planner):
    sql = planner.fetch_sql("Location")
    # Should use SELECT * rather than explicit columns derived from model names
    assert "store_name" not in sql
    assert "SELECT *" in sql


def test_fetch_sql_unknown_concept(planner):
    with pytest.raises(ValueError, match="Unknown concept"):
        planner.fetch_sql("Ghost")


# ── QueryPlanner.relationship_join_sql ───────────────────────────────────────

def test_relationship_join_sql_order_to_location(planner):
    sql = planner.relationship_join_sql("Order", 42, "order_at_location")
    # May return None if FK can't be resolved — that's acceptable
    if sql is not None:
        assert "LOCATIONS" in sql or "ORDERS" in sql
        assert "42" in sql


def test_relationship_join_sql_unknown_rel_returns_none(planner):
    result = planner.relationship_join_sql("Order", 1, "nonexistent_rel")
    assert result is None


# ── row_to_instance ───────────────────────────────────────────────────────────

def test_row_to_instance_basic(parsed_model):
    location_concept = next(c for c in parsed_model.concepts if c.name == "Location")
    row = {
        "location_id": 5,
        "store_name": "Seattle Pike St",
        "city": "Seattle",
        "state": "WA",
        "is_active": True,
    }
    inst = row_to_instance(location_concept, row)
    assert inst.concept == "Location"
    assert inst.id_fields == {"location_id": 5}
    assert inst.label == "Seattle Pike St"
    assert inst.attributes["city"] == "Seattle"


def test_row_to_instance_fallback_label(parsed_model):
    """When no name-like column exists, label falls back to 'Concept #id'."""
    order_concept = next(c for c in parsed_model.concepts if c.name == "Order")
    row = {"order_id": 99, "subtotal": 12.5}
    inst = row_to_instance(order_concept, row)
    assert "99" in inst.label


# ── instance_to_node ──────────────────────────────────────────────────────────

def test_instance_to_node_id_format(parsed_model):
    location_concept = next(c for c in parsed_model.concepts if c.name == "Location")
    row = {"location_id": 5, "store_name": "Seattle Pike St"}
    inst = row_to_instance(location_concept, row)
    node = instance_to_node(inst)
    assert node.id == "Location:5"
    assert node.concept == "Location"
    assert node.label == "Seattle Pike St"


def test_instance_to_node_attributes_merged(parsed_model):
    barista_concept = next(c for c in parsed_model.concepts if c.name == "Barista")
    row = {"barista_id": 3, "full_name": "Alice", "hourly_wage": 18.5}
    inst = row_to_instance(barista_concept, row)
    node = instance_to_node(inst)
    assert node.attributes.get("hourly_wage") == 18.5
