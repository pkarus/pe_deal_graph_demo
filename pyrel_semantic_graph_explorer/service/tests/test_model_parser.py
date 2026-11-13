"""
Tests for service/parser/model_parser.py

Uses a minimal inline model and also validates against the real
example_semantic_layer.py coffee-shop model.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.model_parser import ModelParser, ParsedModel, ConceptDef, RelationshipDef

# ── Minimal inline fixture ────────────────────────────────────────────────────

MINIMAL_MODEL = '''
from relationalai.semantics import Model, Bool, Float, Integer, String

model = Model("test_model")

class Sources:
    class db:
        class schema:
            orders = model.Table("MY_DB.MY_SCHEMA.ORDERS")
            customers = model.Table("MY_DB.MY_SCHEMA.CUSTOMERS")

Order = model.Concept("Order", identify_by={"Order ID": Integer})
model.define(Order.new(order_id=Sources.db.schema.orders.order_id))

Customer = model.Concept("Customer", identify_by={"Customer ID": Integer})
model.define(Customer.new(customer_id=Sources.db.schema.customers.customer_id))

Order.placed_by = model.Relationship(f"{Order} placed by {Customer}", short_name="order_placed_by")
Order.details = model.Relationship(
    f"{Order} has {Float:Total Amount} has {Integer:Item Count} has {Bool:Is Rush}",
    short_name="order_details"
)
'''

MINIMAL_COMPUTED = '''
from relationalai.semantics import Model, Float, Integer, define, Concept
from typing import Optional

model = Model("test_computed")

Order = model.Concept("Order", identify_by={"Order ID": Integer})

def extend(model, concepts, source_tables):
    @define(concepts.Order)
    class OrderExtension:
        @property
        def total_with_tax(self) -> float:
            """Total including tax."""
            return self.subtotal * 1.08

        @property
        def is_large_order(self) -> bool:
            return self.item_count > 10
'''


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse(src: str) -> ParsedModel:
    return ModelParser(src).parse()


# ── Model name ────────────────────────────────────────────────────────────────

def test_model_name_extracted():
    m = parse(MINIMAL_MODEL)
    assert m.model_name == "test_model"


# ── Source tables ─────────────────────────────────────────────────────────────

def test_source_tables_extracted():
    m = parse(MINIMAL_MODEL)
    assert "orders" in m.source_tables
    assert m.source_tables["orders"] == "MY_DB.MY_SCHEMA.ORDERS"
    assert m.source_tables["customers"] == "MY_DB.MY_SCHEMA.CUSTOMERS"


# ── Concepts ──────────────────────────────────────────────────────────────────

def test_concepts_extracted():
    m = parse(MINIMAL_MODEL)
    names = [c.name for c in m.concepts]
    assert "Order" in names
    assert "Customer" in names


def test_concept_identify_by():
    m = parse(MINIMAL_MODEL)
    order = next(c for c in m.concepts if c.name == "Order")
    assert len(order.identify_by) == 1
    assert order.identify_by[0]["name"] == "Order ID"
    assert order.identify_by[0]["type"] == "Integer"


def test_concept_source_table_resolved():
    m = parse(MINIMAL_MODEL)
    order = next(c for c in m.concepts if c.name == "Order")
    assert order.source_table == "MY_DB.MY_SCHEMA.ORDERS"


# ── Relationships ─────────────────────────────────────────────────────────────

def test_relationships_extracted():
    m = parse(MINIMAL_MODEL)
    rel_names = [r.name for r in m.relationships]
    assert "placed_by" in rel_names
    assert "details" in rel_names


def test_relationship_source_concept():
    m = parse(MINIMAL_MODEL)
    placed_by = next(r for r in m.relationships if r.name == "placed_by")
    assert placed_by.source_concept == "Order"


def test_relationship_target_concept():
    m = parse(MINIMAL_MODEL)
    placed_by = next(r for r in m.relationships if r.name == "placed_by")
    assert "Customer" in placed_by.target_concepts


def test_relationship_short_name():
    m = parse(MINIMAL_MODEL)
    placed_by = next(r for r in m.relationships if r.name == "placed_by")
    assert placed_by.short_name == "order_placed_by"


def test_relationship_label():
    m = parse(MINIMAL_MODEL)
    placed_by = next(r for r in m.relationships if r.name == "placed_by")
    assert "Order" in placed_by.label
    assert "Customer" in placed_by.label


def test_scalar_properties_extracted():
    m = parse(MINIMAL_MODEL)
    details = next(r for r in m.relationships if r.name == "details")
    prop_names = [p.name for p in details.scalar_properties]
    assert "total_amount" in prop_names
    assert "item_count" in prop_names
    assert "is_rush" in prop_names


def test_scalar_property_types():
    m = parse(MINIMAL_MODEL)
    details = next(r for r in m.relationships if r.name == "details")
    by_name = {p.name: p for p in details.scalar_properties}
    assert by_name["total_amount"].type == "Float"
    assert by_name["item_count"].type == "Integer"
    assert by_name["is_rush"].type == "Bool"


def test_relationship_with_no_target_concept():
    """Scalar-only relationships have no target concepts."""
    m = parse(MINIMAL_MODEL)
    details = next(r for r in m.relationships if r.name == "details")
    assert details.target_concepts == []


# ── Computed properties ───────────────────────────────────────────────────────

def test_computed_properties_extracted():
    m = parse(MINIMAL_COMPUTED)
    order = next(c for c in m.concepts if c.name == "Order")
    names = [p.name for p in order.computed_properties]
    assert "total_with_tax" in names
    assert "is_large_order" in names


def test_computed_property_return_type():
    m = parse(MINIMAL_COMPUTED)
    order = next(c for c in m.concepts if c.name == "Order")
    by_name = {p.name: p for p in order.computed_properties}
    assert by_name["total_with_tax"].return_type == "float"
    assert by_name["is_large_order"].return_type == "bool"


def test_computed_property_docstring():
    m = parse(MINIMAL_COMPUTED)
    order = next(c for c in m.concepts if c.name == "Order")
    ttax = next(p for p in order.computed_properties if p.name == "total_with_tax")
    assert ttax.docstring and "tax" in ttax.docstring.lower()


# ── Properties attached to concept ───────────────────────────────────────────

def test_scalar_properties_on_concept():
    """Scalars from relationships are also surfaced on the concept's properties list."""
    m = parse(MINIMAL_MODEL)
    order = next(c for c in m.concepts if c.name == "Order")
    prop_names = [p.name for p in order.properties]
    assert "total_amount" in prop_names


# ── Real model: example_semantic_layer.py ─────────────────────────────────────

EXAMPLE_MODEL_PATH = Path("/Users/stevebertolani/Desktop/projects/streamlit_apps/example_semantic_layer.py")


@pytest.mark.skipif(
    not EXAMPLE_MODEL_PATH.exists(),
    reason="example_semantic_layer.py not found"
)
class TestCoffeeShopModel:
    @pytest.fixture(scope="class")
    def model(self):
        return ModelParser.from_file(EXAMPLE_MODEL_PATH).parse()

    def test_model_name(self, model):
        assert model.model_name == "coffee_shop_vp_ops"

    def test_all_concepts_present(self, model):
        names = {c.name for c in model.concepts}
        expected = {
            "MenuItem", "InventoryItem", "InventoryTransaction", "Shift",
            "OrderItem", "LoyaltyMember", "LocationDailyMetrics", "Location",
            "SupplyTransfer", "Order", "Barista",
        }
        assert expected == names

    def test_location_identify_by(self, model):
        loc = next(c for c in model.concepts if c.name == "Location")
        assert loc.identify_by[0]["name"] == "Location ID"
        assert loc.identify_by[0]["type"] == "Integer"

    def test_location_source_table(self, model):
        loc = next(c for c in model.concepts if c.name == "Location")
        assert loc.source_table == "BESPOKE.COFFEE_SHOP_VP_OPS.LOCATIONS"

    def test_source_tables_count(self, model):
        assert len(model.source_tables) == 11  # one per source table in Sources

    def test_relationships_count(self, model):
        assert len(model.relationships) >= 15

    def test_order_at_location_relationship(self, model):
        rel = next(
            (r for r in model.relationships
             if r.source_concept == "Order" and r.name == "at_location"),
            None
        )
        assert rel is not None
        assert "Location" in rel.target_concepts

    def test_supply_transfer_multi_target(self, model):
        rel = next(
            (r for r in model.relationships
             if r.source_concept == "SupplyTransfer"),
            None
        )
        assert rel is not None
        # moves InventoryItem via Location — two concept targets
        assert len(rel.target_concepts) >= 1

    def test_location_profile_scalars(self, model):
        loc = next(c for c in model.concepts if c.name == "Location")
        rel = next(r for r in loc.relationships if r.name == "profile")
        prop_names = [p.name for p in rel.scalar_properties]
        assert "store_name" in prop_names
        assert "city" in prop_names
        assert "is_active" in prop_names

    def test_computed_properties_on_barista(self, model):
        barista = next(c for c in model.concepts if c.name == "Barista")
        names = [p.name for p in barista.computed_properties]
        assert "years_of_service" in names
        assert "valid_hourly_wage" in names
        assert "monthly_orders_handled" in names

    def test_computed_properties_on_menu_item(self, model):
        mi = next(c for c in model.concepts if c.name == "MenuItem")
        names = [p.name for p in mi.computed_properties]
        assert "profit_margin" in names
        assert "positive_pricing" in names

    def test_multi_identify_by(self, model):
        ldm = next(c for c in model.concepts if c.name == "LocationDailyMetrics")
        id_names = {f["name"] for f in ldm.identify_by}
        assert "Metric ID" in id_names
        assert "Location ID" in id_names
        assert "Metric Date" in id_names
