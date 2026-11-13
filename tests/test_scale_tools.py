"""Offline tests for the scale tools: path procedure, community hybrid, tenure pre-flight.

No connection is made. The live behaviour of the procedure is checked by
``scripts/person_path_proc.py --stress`` (and ``--stress-persisted`` at 10M), which compare every
answer with an independent local calculation.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paths = load("person_path_proc")
preflight = load("knows_preflight")


# ---------------------------------------------------------------------------------------------
# Path procedure
# ---------------------------------------------------------------------------------------------
def test_procedure_sql_is_complete_and_scoped():
    deploy, schema = paths.schemas("connected1m")
    assert schema == deploy + "_PATHS"
    sql = paths.procedure_sql(deploy, schema)
    body = sql.split("$$")[1]
    assert "__" not in body                       # every placeholder was filled in
    assert f"{schema}.KNOWS_EDGES" in body and f"{deploy}.PERSON" in body
    assert "LANGUAGE JAVASCRIPT" in sql and "EXECUTE AS CALLER" in sql
    # The procedure only reads: no DML or DDL in its body.
    for word in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "DROP ", "MERGE "):
        assert word not in body.upper().replace("CREATE OR REPLACE PROCEDURE", "")
    with pytest.raises(ValueError):
        paths.schemas("no_such_fixture")


def test_edge_table_holds_both_directions_sorted_by_source():
    sql = paths.edge_table_sql("DB.DEPLOY", "DB.DEPLOY_PATHS")
    assert "P1 AS SRC, P2 AS DST" in sql and "P2 AS SRC, P1 AS DST" in sql
    assert sql.rstrip().endswith("ORDER BY SRC")


def tiny_graph():
    """A-B-D and A-C-D (two 2-hop routes, the C route stronger), D-E, plus isolated Z."""
    g = paths.LocalGraph.__new__(paths.LocalGraph)
    ids = ["A", "B", "C", "D", "E"]
    edges = [("A", "B", 0.5), ("B", "D", 0.5), ("A", "C", 0.9), ("C", "D", 0.8), ("D", "E", 1.0)]
    index = {p: n for n, p in enumerate(ids)}
    src = np.array([index[a] for a, b, w in edges] + [index[b] for a, b, w in edges])
    dst = np.array([index[b] for a, b, w in edges] + [index[a] for a, b, w in edges])
    wt = np.array([w for *_, w in edges] * 2)
    order = np.argsort(src, kind="stable")
    g.ids, g.index, g.people = ids, index, ids + ["Z"]
    g.dst, g.wt = dst[order], wt[order]
    g.start = np.searchsorted(src[order], np.arange(len(ids) + 1))
    return g


def test_local_oracle_distance_strength_and_route_count():
    g = tiny_graph()
    assert g.expected("A", "A") == (0, 1.0, 1)
    distance, strength, routes = g.expected("A", "D")
    assert (distance, routes) == (2, 2) and strength == pytest.approx(0.72)
    distance, strength, routes = g.expected("A", "E")
    assert (distance, routes) == (3, 2) and strength == pytest.approx(0.72)
    assert g.expected("A", "Z") == (None, None, 0)
    # A threshold removes the weak B route: one route left, same length.
    assert g.expected("A", "D", min_strength=0.6)[2] == 1
    # ... and a higher one disconnects the pair.
    assert g.expected("A", "D", min_strength=0.95)[0] is None


def reachable(route, strength, routes):
    return {"status": "reachable", "distance": len(route) - 1, "route": route, "route_strength": strength,
            "shortest_route_count": routes}


def test_check_accepts_the_right_answer_and_rejects_wrong_ones():
    g = tiny_graph()
    assert paths.check(reachable(["A", "C", "D"], 0.72, 2), g, "A", "D", 12, 0.0) == 2
    with pytest.raises(AssertionError):   # a valid shortest route, but not the strongest one
        paths.check(reachable(["A", "B", "D"], 0.25, 2), g, "A", "D", 12, 0.0)
    with pytest.raises(AssertionError):   # a hop that is not a Knows edge
        paths.check(reachable(["A", "E", "D"], 0.72, 2), g, "A", "D", 12, 0.0)
    with pytest.raises(AssertionError):   # wrong route count
        paths.check(reachable(["A", "C", "D"], 0.72, 1), g, "A", "D", 12, 0.0)
    with pytest.raises(AssertionError):   # longer than the shortest
        paths.check(reachable(["A", "C", "D", "E", "D"], 0.72, 2), g, "A", "D", 12, 0.0)
    assert paths.check({"status": "self"}, g, "A", "A", 12, 0.0) == 0
    assert paths.check({"status": "unreachable"}, g, "A", "Z", 12, 0.0) is None
    assert paths.check({"status": "beyond_max_hops"}, g, "A", "E", 2, 0.0) == 3
    with pytest.raises(AssertionError):
        paths.check({"status": "unreachable"}, g, "A", "D", 12, 0.0)


# ---------------------------------------------------------------------------------------------
# Community hybrid: definitions build on the real SDK without executing anything
# ---------------------------------------------------------------------------------------------
def offline_graph(name):
    from relationalai.config import Config
    from relationalai.semantics import Model, String
    from relationalai.semantics.reasoners.graph import Graph
    cfg = Config(connections={"offline": {"type": "duckdb", "path": ":memory:"}}, default_connection="offline")
    model = Model(name, config=cfg)
    person = model.Concept("Person", identify_by={"id": String})
    return model, person, Graph(model, directed=False, weighted=False, node_concept=person)


def test_community_connectors_exact_and_hybrid_definitions():
    from pe_deal_graph.communities import community_connectors
    model, person, graph = offline_graph("community_hybrid_test")
    labels, scores, sampled = community_connectors(model, person, graph, exact_pivots=1000)
    assert labels is graph.louvain(max_levels=1, randomization_seed=42)
    assert scores is not None and sampled is not None
    labels5, scores5, sampled5 = community_connectors(
        model, person, graph, max_levels=5, randomization_seed=7, exact_pivots=1000, num_pivots=50, exact_up_to=20)
    assert labels5 is graph.louvain(max_levels=5, randomization_seed=7)
    assert scores5 is not scores and sampled5 is not sampled      # each call owns its relations
    for bad in ({"max_levels": 0}, {"randomization_seed": -1}, {"num_pivots": 0}, {"num_pivots": 1.5},
                {"exact_up_to": 0}, {"exact_pivots": 0}):
        options = {"exact_pivots": 1000, **bad}
        with pytest.raises(ValueError):
            community_connectors(model, person, graph, **options)


# ---------------------------------------------------------------------------------------------
# Tenure pre-flight
# ---------------------------------------------------------------------------------------------
def test_preflight_flags_a_giant_employer_and_reports_the_cap_effect():
    small = {"ORGANIZATIONS": 100, "ROLES": 600, "LARGEST_ORG_ROLES": 16, "MEDIAN_ORG_ROLES": 6, "P99_ORG_ROLES": 16,
             "CANDIDATE_PAIRS": 1500, "PAIRS_IN_ORGS_OVER_CAP": 0, "ORGS_OVER_CAP": 0, "ROLES_IN_ORGS_OVER_CAP": 0}
    assert preflight.summarize(small, 500)["verdict"].startswith("OK")
    n = 100_000   # one employer with 100,000 roles
    giant = dict(small, LARGEST_ORG_ROLES=n, CANDIDATE_PAIRS=n * (n - 1) // 2 + 1500,
                 PAIRS_IN_ORGS_OVER_CAP=n * (n - 1) // 2, ORGS_OVER_CAP=1, ROLES_IN_ORGS_OVER_CAP=n)
    out = preflight.summarize(giant, 500)
    assert out["verdict"].startswith("RISK") and out["candidate_pairs_with_cap"] == 1500
    assert out["share_of_pairs_in_orgs_over_cap"] > 0.99
    sql = preflight.preflight_sql("DB.S.ROLE_HISTORY", 500)
    assert "GROUP BY ORG_ID" in sql and "N > 500" in sql


def test_settings_default_to_the_demo_behaviour(monkeypatch):
    """The new switches are opt-in: without the environment variables nothing changes."""
    source = (ROOT / "pe_deal_graph/model/graphs.py").read_text()
    assert "MIN_TIE_STRENGTH = 0.0" in source          # literal default that check_graphs.py reads
    rules = (ROOT / "pe_deal_graph/model/rules.py").read_text()
    assert 'os.environ.get("PE_K1_MAX_ORG_ROLES", "0")' in rules
    assert "if K1_MAX_ORG_ROLES:" in rules
