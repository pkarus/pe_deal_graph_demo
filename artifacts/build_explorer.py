#!/usr/bin/env python3
"""Build the Deal Graph Explorer (artifacts/deal_graph_explorer.html) from exports/*.json.

Owner: R15 Explorer Builder. Producer of the inputs: R13 Exporter (pe_deal_graph/export.py).

Usage
-----
    .venv/bin/python artifacts/build_explorer.py                      # exports/ -> artifacts/deal_graph_explorer.html
    .venv/bin/python artifacts/build_explorer.py --exports DIR --out FILE
    .venv/bin/python artifacts/build_explorer.py --validate-only      # check the contract, write nothing

The output is one self-contained HTML file: the vendored Cytoscape.js build, all CSS and JS, and
the exports JSON are inlined. No network calls, no localStorage. Positions come from the exports;
the browser never computes a layout. Every number on screen is rendered from the exports through
one formatter (format_value below mirrors the JS fmt()), and every rendered value carries a
data-src attribute "<file stem>:<JSON pointer>|<format>" so tests/test_explorer_numbers.py can
diff the page against exports/.

Safety rules enforced here:
- exports/ missing or any contract violation -> exit 2 with every problem listed.
- meta.source == "FIXTURE" may never be written to the real deliverable path.
- U+2014 (em dash) anywhere in the inputs or output -> exit 2.
- Output larger than 8 MB -> exit 2.
- The vendored Cytoscape file must match its pinned sha256.

=====================================================================================================
EXPORTS CONTRACT (schema_version "1")
=====================================================================================================

General rules
- One JSON object per file, UTF-8, in exports/. Keys are snake_case. No NaN or Infinity (use null).
- IDs are strings and stable across files: the same company, person or organization has the same id
  in graph.json, q_*.json and sql_baseline.json. Use the model's own entity ids.
- Dates are "YYYY-MM-DD" strings. Money is USD millions as a number in fields named *_musd.
  Percentages are numbers in percent units in fields named *_pct (21.8 means 21.8%). Similarities
  and strengths are fractions in [0, 1].
- Export raw values; the explorer rounds half-up for display: int (thousands separators), 1 decimal
  for money, years and percentages, 3 decimals for strength, similarity and recency, 1 decimal for
  betweenness, 4 decimals for pagerank. "facts" entries name their own format (see FMT below).
- Every display string (evidence, why, reason, summary, docstring) is final business-language text,
  US English, no em dash (U+2014), no emoji.
- Every rule_id must exist in rules.json.
- x, y are precomputed layout coordinates in any unit (screen convention: y grows downward). The
  explorer only rescales them uniformly to fit the view; it never computes a layout. Use a deterministic layout (networkx with a fixed seed). Note: networkx
  spring_layout switches to a scipy-only sparse solver above 500 nodes, and scipy is not in the
  venv; use kamada_kawai_layout/circular_layout or install scipy for the global graph.
- FMT, the allowed "fmt" values: raw | int | f1 | f2 | f3 | f4 | musd1 | pct1 | sint (signed int) |
  words (underscores shown as spaces, for codes like control_buyout).

Required files: meta.json, rules.json, graph.json, q_score.json, q_path.json, q_flow.json,
sql_baseline.json. Optional: q_conflict.json (Act 4 in the v2 arc; export it) and q_addon.json
(backup). The act views are modular: each present file adds its view, and the builder fails if a
file named in meta.view_order is missing.

meta.json
  {"schema_version": "1",
   "source": "RAI" | "ORACLE" | "FIXTURE",       # anything but RAI shows a loud banner
   "generated_at": "2026-10-22T10:00:00+02:00",
   "as_of_date": "2026-10-01",
   "customer_display_name": "Northwind Equity Partners",
   "fund_name": "Fund IV",
   "relationalai_version": "1.27.1" | null,
   "engine": "pe_demo_logic" | null,
   "counts": {"pipeline_companies": int,      # optional; the 7.5 cold open ("about 200 in
              "market_companies": int},       # pipeline"); market_companies is validated but never shown (no market-size line)
   "view_order": ["overview","score","path","flow","conflict"]   # optional, this is the default;
  }                                    # ids: overview, score, path, flow, conflict, addon

rules.json
  {"rules": [{"id": "K1_TENURE", "name": "Tenure overlap", "kind": "rule" | "graph",
              "questions": ["Q-PATH"], "docstring": "<business-language docstring from rules.py>",
              "source": "pe_deal_graph/model/rules.py::knows_tenure"}]}

graph.json  (global view; the explorer subgraph)
  {"layout": {"algorithm": "networkx.kamada_kawai_layout", "seed": 42, "scale": 1000},
   "stats": {"num_nodes": int, "num_edges": int, "model_nodes": int | null, "model_edges": int | null},
   "node_types": [{"id": "company", "label": "Company"}, ...],   # ids: company, person, sponsor,
                                                                   # intermediary, fund
   "edge_types": [{"id": "tenure", "label": "Tenure overlap", "rule_id": "K1_TENURE", "count": int}],
                 # must include tenure, board, deal, commercial, crm; may add ownership, employment
   "nodes": [{"id", "label", "type", "x", "y", "tags": [str],
              "facts": [{"label": str, "value": str | number | bool | null, "fmt": FMT?, "rule_id"?}]}],
   "edges": [{"id", "source", "target", "type", "evidence": str, "rule_id": str | null,
              "facts": [...same shape as node facts...]}]}
  Constraints: len(nodes) <= 1500; stats.num_nodes == len(nodes); stats.num_edges == len(edges);
  every edge endpoint exists; every node/edge type is declared; edge_types[].count equals the
  actual count. Tags the explorer styles: northwind, our_person, tier_a, not_in_crm, path_target,
  platform, fund_iii_portfolio, coverage_gap. All hero entities must be in the subgraph.

view_graph  (shape shared by q_path, q_flow, q_addon, q_conflict; a small per-view layout)
  {"nodes": [{"id", "label", "type", "x", "y", "tags": [str], "community": int?}],
   "edges": [{"id", "source", "target", "type", "label": str?}]}

q_score.json  (Act 1, rules)
  {"question_id": "Q-SCORE", "business_question": str,
   "tier_thresholds": {"A": 70, "B": 50}, "readiness_cap": 50, "max_score": 100,
   "components": [{"id": "FIT_THESIS", "label": "Thesis fit", "group": "fit"|"readiness"|"access",
                   "max_points": 15, "rule_id": "FIT_THESIS"}],
   "summary": {"scored": int, "tier_a": int, "tier_b": int, "tier_c": int,
               "tier_a_not_in_crm": int, "ineligible": int},
   "rows": [{"company_id", "name", "rank": int, "score": int, "tier": "A"|"B"|"C",
             "fit": int, "readiness": int, "access": int,          # subtotals, readiness after cap
             "in_crm": bool, "pipeline_stage": str | null, "sector_path": [str],
             "ebitda_musd": number, "revenue_musd": number, "owner": str | null, "why": str,
             "components": [{"id": component id, "points": int,
                             "evidence": str}]}],   # one entry per component, 0 points allowed:
                                                    # evidence then says why it was not awarded
       # ordered by rank; must include every Tier A and Tier B company; Tier C optional
   "ineligible": [{"company_id", "name", "reason": str}],          # near misses worth showing
   "finale": null | {"description": str,
       "rows": [{"company_id", "name", "rank": int | null, "score": int,
                 "tier": "A"|"B"|"C"|"Conflict", "prev_rank": int | null, "prev_score": int,
                 "prev_tier": str, "delta": int,
                 "conflict": null | {"reason", "counterparty_id", "counterparty_name", "rule_id"},
                 "added_components": [{"id", "points", "evidence"}]}]}}

q_path.json  (Act 2, graph + rules)
  {"question_id": "Q-PATH", "business_question": str, "max_hops": 3,
   "seeds": [{"person_id", "name", "title"}],
   "tie_types": [{"id": "K1", "label": "Tenure overlap", "rule_id": "K1_TENURE"}, ...],
   "targets": [{"company_id", "company_name", "score_rank": int, "owner_name": str | null,
       "status": "warm" | "cold",          # warm iff any decision-maker has a path
       "summary": str,
       "decision_makers": [{               # CEO first, then the owner's board designee(s)
           "person_id", "name", "kind": "CEO" | "OWNER_DESIGNEE",
           "role_label": str,               # e.g. "CEO" or "Board designee, Ironbridge Capital"
           "status": "warm" | "cold", "hops": int | null, "best_strength": number | null,
           "summary": str,
           "paths": [{"path_id", "rank": int, "length": int, "strength": number, "node_ids": [str],
                      "hops": [{"edge_id",           # id of the matching view_graph edge
                                "from_id", "from_name", "to_id", "to_name",
                                "tie_type": "K1"|"K2"|"K3", "tie_label": str | null,
                                "org_id": str|null, "org_name": str|null,
                                "start_date": str|null, "end_date": str|null (null = present),
                                "years": number|null, "recency": number|null, "strength": number,
                                "evidence": str, "rule_id"}]}]}],   # best path first
       "rejected_claims": [{"edge_id": str|null, "from_id", "from_name", "to_id", "to_name",
                            "org_name", "claim": str, "reason": str,
                            "intervals": [{"person_id", "name", "start_date", "end_date"}],
                            "gap_days": int|null, "rule_id"}],
       "closest_intermediary": null | {"org_id", "name", "evidence": str, "rule_id"},
       "next_step": null | {"label": str, "view": "flow", "node_id": str}}],
   "view_graph": view_graph}       # seeds, path people, decision-makers (also unreachable ones),
                                   # rejected-claim people; an edge for every hop and every
                                   # rejected claim (edge type "rejected")

q_flow.json  (Act 3, graph + rules)
  {"question_id": "Q-FLOW", "business_question": str,
   "window": {"start", "end"},
   "graph_stats": {"num_nodes", "num_edges", "num_intermediaries"},
   "thresholds": {"top_decile_cutoff_rank": int, "q1_touchpoints": int},
   "intermediaries": [{"org_id", "name", "betweenness": number, "betweenness_rank": int,
       "pagerank": number, "deals_in_window": int, "deals_5y_all_sectors": int,
       "touchpoints_24m": int, "top_decile": bool, "is_gap": bool, "gap_reason": str | null,
       "deal_ids": [txn_id]}],                       # ordered by betweenness_rank
   "deals": [{"txn_id", "close_date", "target_id", "target_name", "buyer_name": str|null,
              "seller_type", "structure", "deal_role", "advisor_ids": [str], "advisor_names": [str],
              "edge_ids": [view_graph edge ids this deal created]}],
   "view_graph": view_graph}       # node types intermediary, sponsor, company; tag coverage_gap

q_conflict.json  (Act 4, graph + rules; optional in the schema, expected for the v2 arc)
  {"question_id": "Q-CONFLICT", "business_question": str,
   "subject": {"company_id", "name", "thesis_area": str},
   "max_distance": 2,
   "rule_ids": [str],                    # rules shown in the side panel, e.g. NorthwindHolding,
                                         # PortfolioExposure, the concentration guideline
   "exposures": [{"company_id", "name", "fund_name", "since": str, "distance": int,
       "kind": "conflict" | "same_fund" | "informational",
       "kind_label": str,                # e.g. "Conflict - cross-fund review"
       "evidence": str,                  # "Tessmark Clinical Supply supplies Pinewick Dermatology Partners"
       "path_node_ids": [str], "edge_ids": [view_graph edge ids], "rule_id"}],
   "context": [{"company_id", "name", "distance": int | null, "reason": str,
                "edge_ids": [str]}],     # shown greyed: former holdings, the 3-hop rim
   "concentration": {"fund_name", "fund_size_musd", "guideline_pct", "check_musd",
       "subject_area": str, "breach": bool, "headroom_musd": number, "over_by_musd": number,
       "rule_id",
       "areas": [{"name", "before_musd", "before_pct", "after_musd", "after_pct",
                  "is_subject_area": bool, "breach": bool}],
       "holdings": [{"company_id", "name", "area", "niche", "since", "equity_musd", "pct"}]},
   "view_graph": view_graph}      # subject tagged "subject"; edges carry "label" with direction,
                                  # e.g. "supplies"; context nodes tagged "context"

q_addon.json  (backup Q-ADDON, optional; its view is a hidden tab reachable at #addon unless
               meta.view_order lists "addon")
  {"question_id": "Q-ADDON", "business_question": str, "similarity_label": str,
   "platform": {"company_id", "name", "niche", "states": [str], "neighbor_count": int},
   "candidates": [{"company_id", "name", "niche", "rank": int, "similarity": number,
       "shared_count": int, "union_count": int, "neighbor_count": int, "community": int,
       "states": [str], "whitespace_states": [str],
       "shared_neighbors": [{"company_id", "name", "relation": "customer" | "supplier"}],
       "ebitda_musd": number | null, "evidence": str}],
   "excluded": [{"company_id", "name", "reason"}],
   "communities": [{"id": int, "label": str, "size": int}],   # display order = color order
   "view_graph": view_graph}      # nodes carry "community"; platform tagged "platform"

sql_baseline.json  (the naive SQL screens, one entry per hero question present)
  {"questions": {"Q-SCORE": {"sql_file": "data/naive_sql/q_score.sql", "description": str,
       "metric_label": str, "row_count": int, "kg_count": int, "kg_label": str,
       "rows": [{"entity_id", "name", "rank": int, "metric": number | str,
                 "verdict": "agrees" | "decoy" | "other", "note": str | null}],   # top 15 or fewer
       "missed": [{"entity_id", "name", "note"}]},
     "Q-PATH": {...}, "Q-FLOW": {...}, "Q-ADDON": {...}?, "Q-CONFLICT": {...}?}}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPORTS = ROOT / "exports"
DEFAULT_OUT = ROOT / "artifacts" / "deal_graph_explorer.html"
VENDOR_JS = ROOT / "artifacts" / "vendor" / "cytoscape-3.34.3.min.js"
VENDOR_SHA256 = "5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91"
MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 1500
EM_DASH = "\u2014"

REQUIRED_FILES = ["meta", "rules", "graph", "q_score", "q_path", "q_flow", "sql_baseline"]
OPTIONAL_FILES = ["q_addon", "q_conflict"]
FMTS = {"raw", "int", "f1", "f2", "f3", "f4", "musd1", "pct1", "sint", "words"}
VIEW_FILE = {"overview": "graph", "score": "q_score", "path": "q_path", "addon": "q_addon",
             "conflict": "q_conflict", "flow": "q_flow"}
QID_FOR_FILE = {"q_score": "Q-SCORE", "q_path": "Q-PATH", "q_flow": "Q-FLOW", "q_addon": "Q-ADDON",
                "q_conflict": "Q-CONFLICT"}


class ContractError(Exception):
    pass


# ----------------------------------------------------------------------------- formatting
def _q(v: float, places: int) -> str:
    d = Decimal(v).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    s = f"{d:f}"
    return "0" if s in ("-0", "-0.0") and places == 0 else s


def _group(s: str) -> str:
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    whole, _, frac = s.partition(".")
    whole = f"{int(whole):,}"
    return ("-" if neg else "") + whole + ("." + frac if frac else "")


def format_value(v, fmt: str = "raw") -> str:
    """Python mirror of the explorer's JS fmt(). Used by the numbers check."""
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if fmt in ("int", "f1", "f2", "f3", "f4", "musd1", "pct1", "sint") and isinstance(v, (int, float)):
        if fmt == "int":
            return _group(_q(v, 0))
        if fmt in ("f1", "f2", "f3", "f4"):
            return _q(v, int(fmt[1]))
        if fmt == "musd1":
            return "$" + _group(_q(v, 1)) + "M"
        if fmt == "pct1":
            return _q(v, 1) + "%"
        if fmt == "sint":
            s = _q(v, 0)
            return "+" + s if v > 0 and s != "0" else s
    if fmt == "words" and isinstance(v, str):
        return v.replace("_", " ")
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    return str(v)


def resolve_pointer(doc, ptr: str):
    if ptr == "":
        return doc
    cur = doc
    for raw in ptr.split("/")[1:]:
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(key)]
        else:
            cur = cur[key]
    return cur


# ----------------------------------------------------------------------------- loading + validation
def load_exports(exports_dir: Path) -> dict:
    if not exports_dir.is_dir():
        raise ContractError(f"exports directory not found: {exports_dir}. Run 'make export' (R13) first.")
    data = {}
    problems = []
    for stem in REQUIRED_FILES + OPTIONAL_FILES:
        p = exports_dir / f"{stem}.json"
        if not p.exists():
            if stem in REQUIRED_FILES:
                problems.append(f"missing required file {p}")
            continue
        try:
            data[stem] = json.loads(p.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        except (ValueError, json.JSONDecodeError) as exc:
            problems.append(f"{p}: invalid JSON ({exc})")
    if problems:
        raise ContractError("\n".join(problems))
    return data


def _reject_constant(name):
    raise ValueError(f"non-finite number {name} is not allowed")


class _V:
    def __init__(self):
        self.errors: list[str] = []

    def need(self, obj, key, types, where):
        if not isinstance(obj, dict):
            self.errors.append(f"{where}: expected an object")
            return None
        if key not in obj:
            self.errors.append(f"{where}: missing key '{key}'")
            return None
        val = obj[key]
        if types is not None and not isinstance(val, types):
            self.errors.append(f"{where}.{key}: expected {_tn(types)}, got {type(val).__name__}")
            return None
        if isinstance(val, bool) and types in (int, float, (int, float)):
            self.errors.append(f"{where}.{key}: expected a number, got bool")
        return val

    def keys(self, obj, spec, where):
        for key, types in spec.items():
            self.need(obj, key, types, where)


def _tn(t):
    if isinstance(t, tuple):
        return " or ".join(x.__name__ for x in t)
    return t.__name__


NUM = (int, float)
OSTR = (str, type(None))
ONUM = (int, float, type(None))
OINT = (int, type(None))


def _walk_strings(obj, path, out):
    if isinstance(obj, str):
        if EM_DASH in obj:
            out.append(f"{path}: contains an em dash (U+2014); use a hyphen")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_strings(v, f"{path}.{k}", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_strings(v, f"{path}[{i}]", out)


def _check_view_graph(v: _V, vg, where) -> tuple[set, set]:
    if not isinstance(vg, dict):
        v.errors.append(f"{where}: missing view_graph object")
        return set(), set()
    nodes = v.need(vg, "nodes", list, where) or []
    edges = v.need(vg, "edges", list, where) or []
    ids = set()
    for i, n in enumerate(nodes):
        w = f"{where}.nodes[{i}]"
        v.keys(n, {"id": str, "label": str, "type": str, "x": NUM, "y": NUM, "tags": list}, w)
        if isinstance(n, dict) and n.get("id") in ids:
            v.errors.append(f"{w}: duplicate node id {n.get('id')}")
        if isinstance(n, dict):
            ids.add(n.get("id"))
    eids = set()
    for i, e in enumerate(edges):
        w = f"{where}.edges[{i}]"
        v.keys(e, {"id": str, "source": str, "target": str, "type": str}, w)
        if isinstance(e, dict):
            if e.get("id") in eids:
                v.errors.append(f"{w}: duplicate edge id {e.get('id')}")
            eids.add(e.get("id"))
            for end in ("source", "target"):
                if e.get(end) not in ids:
                    v.errors.append(f"{w}: {end} {e.get(end)!r} is not a node of this view_graph")
    return ids, eids


def validate(data: dict) -> list[str]:
    v = _V()
    rules = data.get("rules", {})
    rule_ids = {r.get("id") for r in (rules.get("rules") or []) if isinstance(r, dict)}

    def rule_ref(rid, where, nullable=False):
        if rid is None and nullable:
            return
        if rid not in rule_ids:
            v.errors.append(f"{where}: rule_id {rid!r} not found in rules.json")

    # meta
    meta = data.get("meta", {})
    v.keys(meta, {"schema_version": str, "source": str, "generated_at": str, "as_of_date": str,
                  "customer_display_name": str, "fund_name": str}, "meta")
    if meta.get("schema_version") not in (None, "1"):
        v.errors.append(f"meta.schema_version: expected '1', got {meta.get('schema_version')!r}")
    if meta.get("source") not in (None, "RAI", "ORACLE", "FIXTURE"):
        v.errors.append(f"meta.source: expected RAI, ORACLE or FIXTURE, got {meta.get('source')!r}")
    if "counts" in meta:
        v.keys(meta["counts"], {"pipeline_companies": int, "market_companies": int}, "meta.counts")
    if "view_order" in meta:
        vo = meta["view_order"]
        if not isinstance(vo, list) or any(x not in VIEW_FILE for x in vo):
            v.errors.append(f"meta.view_order: expected a list of {sorted(VIEW_FILE)}")
        else:
            for x in vo:
                if VIEW_FILE[x] not in data:
                    v.errors.append(f"meta.view_order lists '{x}' but {VIEW_FILE[x]}.json is missing")

    # rules
    for i, r in enumerate(v.need(rules, "rules", list, "rules") or []):
        v.keys(r, {"id": str, "name": str, "kind": str, "questions": list, "docstring": str, "source": str}, f"rules.rules[{i}]")
        if isinstance(r, dict) and r.get("kind") not in ("rule", "graph"):
            v.errors.append(f"rules.rules[{i}].kind: expected 'rule' or 'graph'")

    # graph
    g = data.get("graph", {})
    v.need(g, "layout", dict, "graph")
    stats = v.need(g, "stats", dict, "graph") or {}
    v.keys(stats, {"num_nodes": int, "num_edges": int}, "graph.stats")
    ntypes = {t.get("id") for t in (v.need(g, "node_types", list, "graph") or []) if isinstance(t, dict)}
    etypes_list = v.need(g, "edge_types", list, "graph") or []
    etypes = {}
    for i, t in enumerate(etypes_list):
        v.keys(t, {"id": str, "label": str, "count": int}, f"graph.edge_types[{i}]")
        if isinstance(t, dict):
            etypes[t.get("id")] = t
            rule_ref(t.get("rule_id"), f"graph.edge_types[{i}]", nullable=True)
    for req in ("tenure", "board", "deal", "commercial", "crm"):
        if req not in etypes:
            v.errors.append(f"graph.edge_types: missing required edge type '{req}' (section 7.4 toggles)")
    nodes = v.need(g, "nodes", list, "graph") or []
    edges = v.need(g, "edges", list, "graph") or []
    if len(nodes) > MAX_NODES:
        v.errors.append(f"graph.nodes: {len(nodes)} nodes exceeds the {MAX_NODES}-node explorer cap")
    if stats.get("num_nodes") != len(nodes):
        v.errors.append(f"graph.stats.num_nodes={stats.get('num_nodes')} but graph.nodes has {len(nodes)}")
    if stats.get("num_edges") != len(edges):
        v.errors.append(f"graph.stats.num_edges={stats.get('num_edges')} but graph.edges has {len(edges)}")
    gids = set()
    for i, n in enumerate(nodes):
        w = f"graph.nodes[{i}]"
        v.keys(n, {"id": str, "label": str, "type": str, "x": NUM, "y": NUM, "tags": list, "facts": list}, w)
        if not isinstance(n, dict):
            continue
        if n.get("id") in gids:
            v.errors.append(f"{w}: duplicate id {n.get('id')}")
        gids.add(n.get("id"))
        if n.get("type") not in ntypes:
            v.errors.append(f"{w}: type {n.get('type')!r} not declared in graph.node_types")
        _check_facts(v, n.get("facts") or [], w, rule_ref)
    counts = {}
    for i, e in enumerate(edges):
        w = f"graph.edges[{i}]"
        v.keys(e, {"id": str, "source": str, "target": str, "type": str, "evidence": str, "facts": list}, w)
        if not isinstance(e, dict):
            continue
        for end in ("source", "target"):
            if e.get(end) not in gids:
                v.errors.append(f"{w}: {end} {e.get(end)!r} is not a node in graph.nodes")
        if e.get("type") not in etypes:
            v.errors.append(f"{w}: type {e.get('type')!r} not declared in graph.edge_types")
        counts[e.get("type")] = counts.get(e.get("type"), 0) + 1
        rule_ref(e.get("rule_id"), w, nullable=True)
        _check_facts(v, e.get("facts") or [], w, rule_ref)
    for tid, t in etypes.items():
        if t.get("count") != counts.get(tid, 0):
            v.errors.append(f"graph.edge_types[{tid}].count={t.get('count')} but {counts.get(tid, 0)} edges have that type")

    # q_score
    s = data.get("q_score", {})
    v.keys(s, {"question_id": str, "business_question": str, "tier_thresholds": dict, "readiness_cap": NUM,
               "max_score": NUM, "components": list, "summary": dict, "rows": list, "ineligible": list}, "q_score")
    comp_ids = set()
    for i, c in enumerate(s.get("components") or []):
        v.keys(c, {"id": str, "label": str, "group": str, "max_points": NUM, "rule_id": str}, f"q_score.components[{i}]")
        if isinstance(c, dict):
            comp_ids.add(c.get("id"))
            rule_ref(c.get("rule_id"), f"q_score.components[{i}]")
            if c.get("group") not in ("fit", "readiness", "access"):
                v.errors.append(f"q_score.components[{i}].group: expected fit, readiness or access")
    v.keys(s.get("summary") or {}, {k: int for k in ("scored", "tier_a", "tier_b", "tier_c", "tier_a_not_in_crm", "ineligible")}, "q_score.summary")
    for i, r in enumerate(s.get("rows") or []):
        w = f"q_score.rows[{i}]"
        v.keys(r, {"company_id": str, "name": str, "rank": int, "score": NUM, "tier": str, "fit": NUM, "readiness": NUM,
                   "access": NUM, "in_crm": bool, "pipeline_stage": OSTR, "sector_path": list, "ebitda_musd": NUM,
                   "revenue_musd": NUM, "owner": OSTR, "why": str, "components": list}, w)
        if isinstance(r, dict):
            if r.get("tier") not in ("A", "B", "C"):
                v.errors.append(f"{w}.tier: expected A, B or C")
            for j, c in enumerate(r.get("components") or []):
                v.keys(c, {"id": str, "points": NUM, "evidence": str}, f"{w}.components[{j}]")
                if isinstance(c, dict) and c.get("id") not in comp_ids:
                    v.errors.append(f"{w}.components[{j}].id {c.get('id')!r} not in q_score.components")
    for i, r in enumerate(s.get("ineligible") or []):
        v.keys(r, {"company_id": str, "name": str, "reason": str}, f"q_score.ineligible[{i}]")
    fin = s.get("finale")
    if fin is not None:
        v.keys(fin, {"description": str, "rows": list}, "q_score.finale")
        for i, r in enumerate(fin.get("rows") or [] if isinstance(fin, dict) else []):
            w = f"q_score.finale.rows[{i}]"
            v.keys(r, {"company_id": str, "name": str, "rank": OINT, "score": NUM, "tier": str, "prev_rank": OINT,
                       "prev_score": NUM, "prev_tier": str, "delta": NUM, "added_components": list}, w)
            if isinstance(r, dict) and r.get("conflict") is not None:
                v.keys(r["conflict"], {"reason": str, "counterparty_id": str, "counterparty_name": str, "rule_id": str}, f"{w}.conflict")
                rule_ref(r["conflict"].get("rule_id") if isinstance(r["conflict"], dict) else None, f"{w}.conflict")

    # q_path
    p = data.get("q_path", {})
    v.keys(p, {"question_id": str, "business_question": str, "max_hops": int, "seeds": list, "tie_types": list,
               "targets": list}, "q_path")
    pnids, peids = _check_view_graph(v, p.get("view_graph"), "q_path.view_graph")
    ties = set()
    for i, t in enumerate(p.get("tie_types") or []):
        v.keys(t, {"id": str, "label": str, "rule_id": str}, f"q_path.tie_types[{i}]")
        if isinstance(t, dict):
            ties.add(t.get("id"))
            rule_ref(t.get("rule_id"), f"q_path.tie_types[{i}]")
    for i, sd in enumerate(p.get("seeds") or []):
        v.keys(sd, {"person_id": str, "name": str, "title": str}, f"q_path.seeds[{i}]")
    for i, t in enumerate(p.get("targets") or []):
        w = f"q_path.targets[{i}]"
        v.keys(t, {"company_id": str, "company_name": str, "score_rank": OINT, "owner_name": OSTR, "status": str,
                   "summary": str, "decision_makers": list, "rejected_claims": list}, w)
        if not isinstance(t, dict):
            continue
        if t.get("status") not in ("warm", "cold"):
            v.errors.append(f"{w}.status: expected warm or cold")
        dms = t.get("decision_makers") or []
        if not dms:
            v.errors.append(f"{w}.decision_makers: at least the CEO is required")
        for d, dm in enumerate(dms):
            dw = f"{w}.decision_makers[{d}]"
            v.keys(dm, {"person_id": str, "name": str, "kind": str, "role_label": str, "status": str, "hops": OINT,
                        "best_strength": ONUM, "summary": str, "paths": list}, dw)
            if not isinstance(dm, dict):
                continue
            if dm.get("kind") not in ("CEO", "OWNER_DESIGNEE"):
                v.errors.append(f"{dw}.kind: expected CEO or OWNER_DESIGNEE")
            if dm.get("status") == "warm" and not dm.get("paths"):
                v.errors.append(f"{dw}: status warm but no paths")
            if dm.get("person_id") not in pnids:
                v.errors.append(f"{dw}.person_id {dm.get('person_id')!r} not a node of q_path.view_graph")
            for j, pa in enumerate(dm.get("paths") or []):
                pw = f"{dw}.paths[{j}]"
                v.keys(pa, {"path_id": str, "rank": int, "length": int, "strength": NUM, "node_ids": list, "hops": list}, pw)
                for k, hp in enumerate(pa.get("hops") or [] if isinstance(pa, dict) else []):
                    hw = f"{pw}.hops[{k}]"
                    v.keys(hp, {"edge_id": str, "from_id": str, "from_name": str, "to_id": str, "to_name": str, "tie_type": str,
                                "org_name": OSTR, "start_date": OSTR, "end_date": OSTR, "years": ONUM, "recency": ONUM,
                                "strength": NUM, "evidence": str, "rule_id": str}, hw)
                    if isinstance(hp, dict):
                        if hp.get("edge_id") not in peids:
                            v.errors.append(f"{hw}.edge_id {hp.get('edge_id')!r} not in q_path.view_graph.edges")
                        if hp.get("tie_type") not in ties:
                            v.errors.append(f"{hw}.tie_type {hp.get('tie_type')!r} not in q_path.tie_types")
                        rule_ref(hp.get("rule_id"), hw)
        for j, rc in enumerate(t.get("rejected_claims") or []):
            rw = f"{w}.rejected_claims[{j}]"
            v.keys(rc, {"from_id": str, "from_name": str, "to_id": str, "to_name": str, "org_name": str, "claim": str,
                        "reason": str, "intervals": list, "gap_days": OINT, "rule_id": str}, rw)
            if isinstance(rc, dict):
                if rc.get("edge_id") is not None and rc.get("edge_id") not in peids:
                    v.errors.append(f"{rw}.edge_id {rc.get('edge_id')!r} not in q_path.view_graph.edges")
                rule_ref(rc.get("rule_id"), rw)
        ci = t.get("closest_intermediary")
        if ci is not None:
            v.keys(ci, {"org_id": str, "name": str, "evidence": str, "rule_id": str}, f"{w}.closest_intermediary")
            if isinstance(ci, dict):
                rule_ref(ci.get("rule_id"), f"{w}.closest_intermediary")
        ns = t.get("next_step")
        if ns is not None:
            v.keys(ns, {"label": str, "view": str, "node_id": str}, f"{w}.next_step")

    # q_flow
    f = data.get("q_flow", {})
    v.keys(f, {"question_id": str, "business_question": str, "window": dict, "graph_stats": dict, "thresholds": dict,
               "intermediaries": list, "deals": list}, "q_flow")
    fids, feids = _check_view_graph(v, f.get("view_graph"), "q_flow.view_graph")
    v.keys(f.get("thresholds") or {}, {"top_decile_cutoff_rank": int, "q1_touchpoints": NUM}, "q_flow.thresholds")
    v.keys(f.get("graph_stats") or {}, {"num_nodes": int, "num_edges": int, "num_intermediaries": int}, "q_flow.graph_stats")
    txns = set()
    for i, d in enumerate(f.get("deals") or []):
        w = f"q_flow.deals[{i}]"
        v.keys(d, {"txn_id": str, "close_date": str, "target_id": str, "target_name": str, "buyer_name": OSTR,
                   "seller_type": str, "structure": str, "deal_role": str, "advisor_names": list, "edge_ids": list}, w)
        if isinstance(d, dict):
            txns.add(d.get("txn_id"))
            for eid in d.get("edge_ids") or []:
                if eid not in feids:
                    v.errors.append(f"{w}.edge_ids: {eid!r} not in q_flow.view_graph.edges")
    for i, it in enumerate(f.get("intermediaries") or []):
        w = f"q_flow.intermediaries[{i}]"
        v.keys(it, {"org_id": str, "name": str, "betweenness": NUM, "betweenness_rank": int, "pagerank": NUM,
                    "deals_in_window": int, "deals_5y_all_sectors": int, "touchpoints_24m": int, "top_decile": bool,
                    "is_gap": bool, "gap_reason": OSTR, "deal_ids": list}, w)
        if isinstance(it, dict):
            if it.get("org_id") not in fids:
                v.errors.append(f"{w}.org_id {it.get('org_id')!r} not a node of q_flow.view_graph")
            for tx in it.get("deal_ids") or []:
                if tx not in txns:
                    v.errors.append(f"{w}.deal_ids: {tx!r} not in q_flow.deals")

    # q_addon (optional)
    if "q_addon" in data:
        a = data["q_addon"]
        v.keys(a, {"question_id": str, "business_question": str, "similarity_label": str, "platform": dict,
                   "candidates": list, "excluded": list, "communities": list}, "q_addon")
        aids, _ = _check_view_graph(v, a.get("view_graph"), "q_addon.view_graph")
        v.keys(a.get("platform") or {}, {"company_id": str, "name": str, "niche": str, "states": list, "neighbor_count": int}, "q_addon.platform")
        for i, c in enumerate(a.get("candidates") or []):
            w = f"q_addon.candidates[{i}]"
            v.keys(c, {"company_id": str, "name": str, "niche": str, "rank": int, "similarity": NUM, "shared_count": int,
                       "union_count": int, "neighbor_count": int, "community": int, "states": list,
                       "whitespace_states": list, "shared_neighbors": list, "ebitda_musd": ONUM, "evidence": str}, w)
            if isinstance(c, dict) and c.get("company_id") not in aids:
                v.errors.append(f"{w}.company_id {c.get('company_id')!r} not a node of q_addon.view_graph")
        for i, c in enumerate(a.get("communities") or []):
            v.keys(c, {"id": int, "label": str, "size": int}, f"q_addon.communities[{i}]")

    # q_conflict (optional)
    if "q_conflict" in data:
        c = data["q_conflict"]
        v.keys(c, {"question_id": str, "business_question": str, "subject": dict, "max_distance": int, "rule_ids": list,
                   "exposures": list, "context": list, "concentration": dict}, "q_conflict")
        cids, ceids = _check_view_graph(v, c.get("view_graph"), "q_conflict.view_graph")
        v.keys(c.get("subject") or {}, {"company_id": str, "name": str, "thesis_area": str}, "q_conflict.subject")
        for rid in c.get("rule_ids") or []:
            rule_ref(rid, "q_conflict.rule_ids")
        for i, x in enumerate(c.get("exposures") or []):
            w = f"q_conflict.exposures[{i}]"
            v.keys(x, {"company_id": str, "name": str, "fund_name": str, "since": str, "distance": int, "kind": str,
                       "kind_label": str, "evidence": str, "path_node_ids": list, "edge_ids": list, "rule_id": str}, w)
            if isinstance(x, dict):
                if x.get("kind") not in ("conflict", "same_fund", "informational"):
                    v.errors.append(f"{w}.kind: expected conflict, same_fund or informational")
                rule_ref(x.get("rule_id"), w)
                for eid in x.get("edge_ids") or []:
                    if eid not in ceids:
                        v.errors.append(f"{w}.edge_ids: {eid!r} not in q_conflict.view_graph.edges")
                for nid in x.get("path_node_ids") or []:
                    if nid not in cids:
                        v.errors.append(f"{w}.path_node_ids: {nid!r} not in q_conflict.view_graph.nodes")
        for i, x in enumerate(c.get("context") or []):
            w = f"q_conflict.context[{i}]"
            v.keys(x, {"company_id": str, "name": str, "distance": OINT, "reason": str, "edge_ids": list}, w)
            for eid in (x.get("edge_ids") or []) if isinstance(x, dict) else []:
                if eid not in ceids:
                    v.errors.append(f"{w}.edge_ids: {eid!r} not in q_conflict.view_graph.edges")
        cc = c.get("concentration") or {}
        v.keys(cc, {"fund_name": str, "fund_size_musd": NUM, "guideline_pct": NUM, "check_musd": NUM, "subject_area": str,
                    "breach": bool, "headroom_musd": NUM, "over_by_musd": NUM, "rule_id": str, "areas": list,
                    "holdings": list}, "q_conflict.concentration")
        rule_ref(cc.get("rule_id"), "q_conflict.concentration")
        for i, a in enumerate(cc.get("areas") or []):
            v.keys(a, {"name": str, "before_musd": NUM, "before_pct": NUM, "after_musd": NUM, "after_pct": NUM,
                       "is_subject_area": bool, "breach": bool}, f"q_conflict.concentration.areas[{i}]")
        for i, hd in enumerate(cc.get("holdings") or []):
            v.keys(hd, {"company_id": str, "name": str, "area": str, "niche": str, "since": str, "equity_musd": NUM,
                        "pct": NUM}, f"q_conflict.concentration.holdings[{i}]")

    # sql_baseline
    sb = (data.get("sql_baseline") or {}).get("questions")
    if not isinstance(sb, dict):
        v.errors.append("sql_baseline: missing 'questions' object")
        sb = {}
    for stem, qid in QID_FOR_FILE.items():
        if stem in data and qid not in sb:
            v.errors.append(f"sql_baseline.questions: missing entry for {qid} ({stem}.json is present)")
    for qid, q in sb.items():
        w = f"sql_baseline.questions[{qid}]"
        v.keys(q, {"sql_file": str, "description": str, "metric_label": str, "row_count": int, "kg_count": int,
                   "kg_label": str, "rows": list, "missed": list}, w)
        for i, r in enumerate(q.get("rows") or [] if isinstance(q, dict) else []):
            v.keys(r, {"entity_id": str, "name": str, "rank": int, "verdict": str}, f"{w}.rows[{i}]")
            if isinstance(r, dict) and r.get("verdict") not in ("agrees", "decoy", "other"):
                v.errors.append(f"{w}.rows[{i}].verdict: expected agrees, decoy or other")

    # every string, every file: no em dash
    for stem, obj in data.items():
        _walk_strings(obj, stem, v.errors)
    return v.errors


def _check_facts(v: _V, facts, where, rule_ref):
    for j, fa in enumerate(facts):
        w = f"{where}.facts[{j}]"
        v.need(fa, "label", str, w)
        if isinstance(fa, dict):
            if "value" not in fa:
                v.errors.append(f"{w}: missing key 'value'")
            if fa.get("fmt", "raw") not in FMTS:
                v.errors.append(f"{w}.fmt: {fa.get('fmt')!r} not one of {sorted(FMTS)}")
            if "rule_id" in fa:
                rule_ref(fa.get("rule_id"), w, nullable=True)


# ----------------------------------------------------------------------------- HTML assembly
def _vendor_js() -> str:
    raw = VENDOR_JS.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != VENDOR_SHA256:
        raise ContractError(f"{VENDOR_JS}: sha256 {digest} does not match the pinned {VENDOR_SHA256}")
    return raw.decode("utf-8")


def _safe_json(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False, allow_nan=False)
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("<!--", "<\\!--")


def build_html(data: dict) -> str:
    title = "Deal Graph Explorer"
    payload = _safe_json(data)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        f"<title>{title}</title>\n<style>\n{CSS}\n</style>\n</head>\n<body>\n{BODY}\n"
        f"<script>\n{_vendor_js()}\n</script>\n"
        f"<script type=\"application/json\" id=\"exports-data\">{payload}</script>\n"
        f"<script>\n{APP_JS}\n</script>\n</body>\n</html>\n"
    )


def build(exports_dir: Path, out: Path, *, validate_only: bool = False) -> Path | None:
    data = load_exports(exports_dir)
    errors = validate(data)
    if errors:
        raise ContractError(f"{len(errors)} exports contract violation(s) in {exports_dir}:\n  - " + "\n  - ".join(errors))
    if validate_only:
        return None
    if data["meta"].get("source") == "FIXTURE" and out.resolve() == DEFAULT_OUT.resolve():
        raise ContractError("refusing to write FIXTURE data to the real deliverable "
                            f"{DEFAULT_OUT}; pass --out to a scratch path for fixture builds")
    html = build_html(data)
    if EM_DASH in html:
        raise ContractError("output contains an em dash (U+2014)")
    size = len(html.encode("utf-8"))
    if size > MAX_BYTES:
        raise ContractError(f"output is {size} bytes, over the 8 MB limit")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--exports", type=Path, default=DEFAULT_EXPORTS, help="directory holding the *.json exports (default: exports/)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output HTML path (default: artifacts/deal_graph_explorer.html)")
    ap.add_argument("--validate-only", action="store_true", help="check the exports contract and exit")
    args = ap.parse_args(argv)
    try:
        out = build(args.exports, args.out, validate_only=args.validate_only)
    except ContractError as exc:
        print(f"build_explorer: ERROR: {exc}", file=sys.stderr)
        return 2
    if out is None:
        print(f"build_explorer: exports in {args.exports} satisfy the contract")
    else:
        print(f"build_explorer: wrote {out} ({out.stat().st_size} bytes) from {args.exports}")
    return 0


# ----------------------------------------------------------------------------- page shell
BODY = r"""
<div id="app">
  <header class="top">
    <div class="brand">
      <div class="brand-title">Deal Graph Explorer</div>
      <div class="brand-sub" id="brand-sub"></div>
    </div>
    <nav class="tabs" id="tabs" role="tablist" aria-label="Views"></nav>
    <div class="source" id="source"></div>
  </header>
  <div class="banner" id="banner" hidden></div>
  <main id="views"></main>
</div>
"""

# ----------------------------------------------------------------------------- styles
CSS = r"""
:root {
  color-scheme: light;
  --bg: #f4f5f7; --surface: #ffffff; --surface-2: #f8f9fb; --line: #e1e4ea; --line-strong: #c9ced8;
  --ink: #14171c; --ink-2: #4c5361; --ink-3: #7a8191;
  --accent: #1f5fae; --accent-soft: #e6eef9; --navy: #1b2a41;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s5: #e87ba4; --s7: #6250d6; --s4: #eda100; --s6: #008300; --s8: #e34948;
  --good: #1d7a46; --warn: #a36100; --warn-soft: #fff4e0; --crit: #c62f2f; --crit-soft: #fdeaea;
  --node: #8c94a3; --node-person: #aab1bd; --edge: #c3c8d1;
  --shadow: 0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.08);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #121418; --surface: #1a1d23; --surface-2: #20242b; --line: #2d323b; --line-strong: #3b414c;
    --ink: #eef0f3; --ink-2: #b9bfca; --ink-3: #8b92a0; --accent: #5b9be6; --accent-soft: #1d2b40; --navy: #c9d6ea;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s5: #d55181; --s7: #9085e9; --s4: #c98500; --s6: #008300; --s8: #e66767;
    --good: #4fb07a; --warn: #e0a040; --warn-soft: #3a2c12; --crit: #ec6a6a; --crit-soft: #3a1c1c;
    --node: #7d8595; --node-person: #646c7a; --edge: #3f4552;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #121418; --surface: #1a1d23; --surface-2: #20242b; --line: #2d323b; --line-strong: #3b414c;
  --ink: #eef0f3; --ink-2: #b9bfca; --ink-3: #8b92a0; --accent: #5b9be6; --accent-soft: #1d2b40; --navy: #c9d6ea;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s5: #d55181; --s7: #9085e9; --s4: #c98500; --s6: #008300; --s8: #e66767;
  --good: #4fb07a; --warn: #e0a040; --warn-soft: #3a2c12; --crit: #ec6a6a; --crit-soft: #3a1c1c;
  --node: #7d8595; --node-person: #646c7a; --edge: #3f4552;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif;
  font-variant-numeric: tabular-nums; }
#app { display: flex; flex-direction: column; height: 100vh; }
button { font: inherit; color: inherit; }
[hidden] { display: none !important; }
.top { display: flex; align-items: center; gap: 20px; padding: 10px 20px; background: var(--surface);
  border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.brand-title { font-weight: 650; font-size: 16px; letter-spacing: .1px; }
.brand-sub { color: var(--ink-2); font-size: 12px; }
.tabs { display: flex; gap: 2px; flex: 1; flex-wrap: wrap; }
.tab { border: 0; background: transparent; padding: 8px 14px; border-radius: 6px; cursor: pointer; color: var(--ink-2); font-weight: 520; }
.tab:hover { background: var(--surface-2); color: var(--ink); }
.tab[aria-selected="true"] { background: var(--accent-soft); color: var(--accent); }
.source { font-size: 12px; color: var(--ink-2); text-align: right; }
.source .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line-strong); font-weight: 600; }
.source .pill.live { color: var(--good); border-color: var(--good); }
.source .pill.fake { color: #fff; background: var(--crit); border-color: var(--crit); }
.banner { background: var(--crit); color: #fff; padding: 8px 20px; font-weight: 600; letter-spacing: .2px; }
main { flex: 1; min-height: 0; position: relative; }
.view { position: absolute; inset: 0; display: grid; grid-template-columns: minmax(0, 1fr) 380px; }
.view-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; border-right: 1px solid var(--line); }
.view-head { padding: 14px 20px 10px; background: var(--surface); border-bottom: 1px solid var(--line); }
.q-label { font-size: 11px; font-weight: 650; letter-spacing: .6px; text-transform: uppercase; color: var(--accent); }
.q-text { font-size: 17px; font-weight: 560; margin-top: 2px; }
.toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 20px; background: var(--surface); border-bottom: 1px solid var(--line); }
.cy { flex: 1; min-height: 240px; background: var(--surface-2); position: relative; }
.scroll { flex: 1; overflow: auto; min-height: 0; }
.panel { overflow: auto; background: var(--surface); padding: 16px 18px 28px; }
.panel h3 { margin: 18px 0 8px; font-size: 11px; letter-spacing: .6px; text-transform: uppercase; color: var(--ink-3); font-weight: 650; }
.panel h3:first-child { margin-top: 0; }
.panel .title { font-size: 17px; font-weight: 620; margin-bottom: 4px; }
.muted { color: var(--ink-3); }
.small { font-size: 12px; }
.btn { border: 1px solid var(--line-strong); background: var(--surface); padding: 5px 11px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn:hover { border-color: var(--accent); color: var(--accent); }
.btn.on, .btn[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.link { border: 0; padding: 0; background: none; color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
.seg { display: inline-flex; border: 1px solid var(--line-strong); border-radius: 7px; overflow: hidden; }
.seg .btn { border: 0; border-radius: 0; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 10px; font-size: 11.5px; font-weight: 600;
  border: 1px solid var(--line-strong); color: var(--ink-2); background: var(--surface); white-space: nowrap; max-width: 100%; }
.claim .chip { white-space: normal; flex-shrink: 0; max-width: 55%; text-align: right; }
.chip.tier-A { background: var(--navy); color: var(--surface); border-color: var(--navy); }
.chip.tier-B { background: var(--accent-soft); color: var(--accent); border-color: var(--accent-soft); }
.chip.tier-C { color: var(--ink-3); }
.chip.tier-Conflict, .chip.crit { background: var(--crit-soft); color: var(--crit); border-color: var(--crit); }
.chip.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
.chip.good { color: var(--good); border-color: var(--good); }
.chip.decoy { color: var(--crit); border-color: var(--crit); }
.chip.kind-graph { color: var(--s7); border-color: var(--s7); }
.chip.kind-rule { color: var(--accent); border-color: var(--accent); }
.tiles { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.tile { background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; min-width: 150px; }
.tile .k { font-size: 11px; color: var(--ink-3); text-transform: uppercase; letter-spacing: .5px; font-weight: 600; }
.tile .v { font-size: 22px; font-weight: 650; }
.tile .d { font-size: 12px; color: var(--ink-2); }
.tile.contrast .v { color: var(--ink-3); }
table.t { border-collapse: collapse; width: 100%; font-size: 13px; }
table.t th { text-align: left; font-size: 11px; color: var(--ink-3); font-weight: 650; text-transform: uppercase; letter-spacing: .4px;
  border-bottom: 1px solid var(--line); padding: 6px 8px; position: sticky; top: 0; background: var(--surface); }
table.t td { border-bottom: 1px solid var(--line); padding: 7px 8px; vertical-align: top; }
table.t td.num, table.t th.num { text-align: right; }
table.t tr.clickable { cursor: pointer; }
table.t tr.clickable:hover td { background: var(--surface-2); }
table.t tr.sel td { background: var(--accent-soft); }
table.t tr.dim td { color: var(--ink-3); }
.struck { text-decoration: line-through; text-decoration-color: var(--crit); }
.rule-card { border: 1px solid var(--line); border-left: 3px solid var(--accent); border-radius: 6px; padding: 10px 12px; background: var(--surface-2); }
.rule-card.graph { border-left-color: var(--s7); }
.rule-card .rn { font-weight: 620; margin-right: 6px; }
.rule-card .doc { margin: 6px 0; white-space: pre-wrap; }
.rule-card .src { font: 11.5px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--ink-3); word-break: break-all; }
.rulelink { cursor: pointer; color: var(--accent); border-bottom: 1px dotted var(--accent); }
.facts { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; font-size: 13px; }
.facts .fk { color: var(--ink-3); }
.facts .fv.has-rule { cursor: pointer; border-bottom: 1px dotted var(--accent); justify-self: start; }
.legend { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; color: var(--ink-2); align-items: center; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
.sw.line { height: 3px; width: 16px; border-radius: 2px; vertical-align: 2px; }
.toggle { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border: 1px solid var(--line-strong); border-radius: 999px;
  font-size: 12px; cursor: pointer; user-select: none; background: var(--surface); }
.toggle input { margin: 0 2px 0 0; }
.toggle.off { opacity: .5; }
.search { position: relative; }
.search input { width: 260px; padding: 6px 10px; border: 1px solid var(--line-strong); border-radius: 6px; font: inherit; background: var(--surface); color: var(--ink); }
.results { position: absolute; z-index: 20; top: 34px; left: 0; width: 320px; background: var(--surface); border: 1px solid var(--line-strong);
  border-radius: 8px; box-shadow: var(--shadow); max-height: 320px; overflow: auto; }
.results button { display: flex; justify-content: space-between; gap: 8px; width: 100%; text-align: left; border: 0; background: none; padding: 7px 10px; cursor: pointer; }
.results button:hover { background: var(--accent-soft); }
.neighbors { list-style: none; margin: 0; padding: 0; font-size: 13px; }
.neighbors li { padding: 4px 0; border-bottom: 1px solid var(--line); display: flex; gap: 8px; justify-content: space-between; cursor: pointer; }
.neighbors li:hover { color: var(--accent); }
/* scorecard */
.sc-wrap { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0; }
.sc-wrap.with-naive { grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); }
.sc-list { padding: 8px 20px 24px; }
.sc-naive { padding: 12px 20px 24px; border-left: 1px solid var(--line); background: var(--surface); }
.sc-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) 64px minmax(120px, 220px) 48px; align-items: center; gap: 12px;
  padding: 10px 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; margin-top: 8px; cursor: pointer; }
.sc-row:hover { border-color: var(--line-strong); }
.sc-row.open { border-color: var(--accent); }
.sc-rank { font-weight: 650; color: var(--ink-3); text-align: right; }
.sc-name { font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sc-score { font-weight: 700; font-size: 18px; text-align: right; }
.bar { display: flex; height: 12px; border-radius: 4px; overflow: hidden; background: var(--line); gap: 2px; }
.bar span { display: block; height: 100%; }
.bar .fit { background: var(--s1); } .bar .readiness { background: var(--s2); } .bar .access { background: var(--s3); }
.sc-detail { margin: 0 0 4px 46px; padding: 10px 14px 12px; border: 1px solid var(--line); border-top: 0; border-radius: 0 0 8px 8px; background: var(--surface-2); }
.sc-why { margin-bottom: 8px; color: var(--ink-2); }
.comp { display: grid; grid-template-columns: 12px 170px 64px minmax(0, 1fr); gap: 8px; padding: 4px 0; border-top: 1px solid var(--line); font-size: 13px; align-items: baseline; }
.comp.zero { color: var(--ink-3); }
.comp .pts { text-align: right; font-weight: 600; }
.comp .lbl { cursor: pointer; }
.comp .lbl:hover { color: var(--accent); }
.meta-line { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--ink-2); margin-bottom: 8px; }
.move { font-size: 12px; color: var(--ink-2); }
.move .up { color: var(--good); font-weight: 650; }
/* warm path */
.picker { display: flex; gap: 8px; flex-wrap: wrap; }
.pick { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 7px 12px; border: 1px solid var(--line-strong); border-radius: 8px;
  background: var(--surface); cursor: pointer; min-width: 170px; text-align: left; }
.pick:hover { border-color: var(--accent); }
.pick.on { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
.pick .pn { font-weight: 600; }
.path-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; background: var(--surface); }
.path-card.best { border-color: var(--accent); border-width: 2px; }
.path-card .ph { display: flex; justify-content: space-between; gap: 8px; font-weight: 620; margin-bottom: 6px; }
.hops { list-style: none; margin: 0; padding: 0; }
.hop { padding: 7px 0 7px 14px; border-left: 2px solid var(--line-strong); margin-left: 4px; position: relative; }
.path-card.best .hop { border-left-color: var(--accent); }
.hop::before { content: ""; position: absolute; left: -6px; top: 11px; width: 10px; height: 10px; border-radius: 50%; background: var(--surface); border: 2px solid var(--line-strong); }
.path-card.best .hop::before { border-color: var(--accent); }
.hop-who { font-weight: 600; }
.hop-ev { margin: 2px 0; }
.hop-meta { font-size: 12px; color: var(--ink-2); display: flex; gap: 10px; flex-wrap: wrap; }
.cold { border: 1px solid var(--crit); background: var(--crit-soft); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
.cold .ct { font-weight: 650; color: var(--crit); }
.claim { border: 1px dashed var(--line-strong); border-radius: 8px; padding: 8px 10px; margin: 8px 0; background: var(--surface); }
/* add-on map */
.usmap { display: grid; grid-template-columns: repeat(11, 1fr); gap: 3px; max-width: 330px; margin-top: 6px; }
.usmap .st { aspect-ratio: 1 / 1; display: flex; align-items: center; justify-content: center; font-size: 9.5px; border-radius: 3px;
  background: var(--surface-2); color: var(--ink-3); border: 1px solid var(--line); }
.usmap .st.plat { background: var(--line-strong); color: var(--ink); }
.usmap .st.cand { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
.usmap .st.ws { background: var(--s3); color: #fff; border-color: var(--s3); font-weight: 700; }
.empty { color: var(--ink-3); font-size: 13px; padding: 6px 0; }
.area-row { display: grid; grid-template-columns: 220px minmax(0, 1fr) 190px; gap: 12px; align-items: center; padding: 5px 0; font-size: 13px; }
.area-track { position: relative; height: 14px; background: var(--line); border-radius: 4px; }
.area-track .g-before { position: absolute; left: 0; top: 0; bottom: 0; background: var(--s1); border-radius: 4px 0 0 4px; }
.area-track .g-add { position: absolute; top: 0; bottom: 0; background: var(--s2); }
.area-track .g-cap { position: absolute; top: -4px; bottom: -4px; width: 0; border-left: 2px dashed var(--crit); }
.area-val { text-align: right; white-space: nowrap; }
.err { color: var(--crit); padding: 20px; }
@media (max-width: 900px) {
  .view { position: static; display: block; }
  .view-main { border-right: 0; }
  .cy { min-height: 420px; }
  .sc-wrap.with-naive { grid-template-columns: minmax(0, 1fr); }
  .sc-row { grid-template-columns: 26px minmax(0, 1fr) 56px 44px; }
  .sc-row .bar { display: none; }
  #app { height: auto; }
}
"""

# ----------------------------------------------------------------------------- application
APP_JS = r"""
(function () {
'use strict';
var X = JSON.parse(document.getElementById('exports-data').textContent);
var E = window.__explorer = { registry: [], ready: false, readyMs: null, cys: {}, state: {}, views: [], api: {} };

/* ---------------- formatting: mirrored by build_explorer.format_value ---------------- */
function group(s) {
  var neg = s.charAt(0) === '-'; if (neg) s = s.slice(1);
  var p = s.split('.'); p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (neg ? '-' : '') + p.join('.');
}
function fixed(v, d) { var s = Number(v).toFixed(d); return (d === 0 && (s === '-0')) ? '0' : s; }
function fmt(v, f) {
  if (v === null || v === undefined) return 'n/a';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'number') {
    switch (f) {
      case 'int': return group(fixed(v, 0));
      case 'f1': return fixed(v, 1);
      case 'f2': return fixed(v, 2);
      case 'f3': return fixed(v, 3);
      case 'f4': return fixed(v, 4);
      case 'musd1': return '$' + group(fixed(v, 1)) + 'M';
      case 'pct1': return fixed(v, 1) + '%';
      case 'sint': var s = fixed(v, 0); return (v > 0 && s !== '0') ? '+' + s : s;
    }
  }
  if (f === 'words' && typeof v === 'string') return v.replace(/_/g, ' ');
  return String(v);
}
function get(file, ptr) {
  var o = X[file];
  if (!ptr) return o;
  var parts = ptr.split('/').slice(1);
  for (var i = 0; i < parts.length; i++) {
    if (o === null || o === undefined) return undefined;
    var k = parts[i].replace(/~1/g, '/').replace(/~0/g, '~');
    o = Array.isArray(o) ? o[Number(k)] : o[k];
  }
  return o;
}
/* V: a rendered export value, tagged for the numbers check */
function V(file, ptr, f, tag) {
  var el = document.createElement(tag || 'span');
  el.textContent = fmt(get(file, ptr), f || 'raw');
  el.setAttribute('data-src', file + ':' + ptr + '|' + (f || 'raw'));
  return el;
}
/* S: static UI text that contains digits (not data) */
function S(text) { var el = document.createElement('span'); el.textContent = text; el.setAttribute('data-static', ''); return el; }
/* lab: canvas label text, registered for the numbers check */
function lab(parts) {
  var text = '', items = [];
  parts.forEach(function (p) {
    if (typeof p === 'string') { text += p; return; }
    var t = fmt(get(p[0], p[1]), p[2] || 'raw');
    items.push({ src: p[0] + ':' + p[1] + '|' + (p[2] || 'raw'), text: t });
    text += t;
  });
  E.registry.push({ text: text, parts: items });
  return text;
}
function h(tag, attrs) {
  var el = document.createElement(tag);
  if (attrs) Object.keys(attrs).forEach(function (k) {
    var v = attrs[k];
    if (v === null || v === undefined || v === false) return;
    if (k === 'class') el.className = v;
    else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  });
  for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
  return el;
}
function add(el, c) {
  if (c === null || c === undefined || c === false) return;
  if (Array.isArray(c)) { c.forEach(function (x) { add(el, x); }); return; }
  el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
}
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function idx(list, key) { var m = {}; (list || []).forEach(function (x, i) { m[x[key]] = i; }); return m; }

/* ---------------- rules ---------------- */
var RULES = X.rules.rules, RULE_IDX = idx(RULES, 'id');
function ruleCard(target, ruleId, context) {
  clear(target);
  var i = RULE_IDX[ruleId];
  if (ruleId === undefined || ruleId === null || i === undefined) {
    add(target, h('div', { class: 'empty' }, 'Select a highlighted fact, hop or score component to see the business rule behind it.'));
    return;
  }
  var r = RULES[i], base = '/rules/' + i;
  add(target, h('div', { class: 'rule-card' + (r.kind === 'graph' ? ' graph' : ''), 'data-rule': r.id },
    h('div', null, V('rules', base + '/name', 'raw', 'span'), ' ',
      h('span', { class: 'chip kind-' + r.kind }, r.kind === 'graph' ? 'Graph algorithm' : 'Rule')),
    context ? h('div', { class: 'small muted', style: 'margin-top:4px' }, context) : null,
    h('div', { class: 'doc' }, V('rules', base + '/docstring')),
    h('div', { class: 'src' }, V('rules', base + '/source'))));
}
function ruleLink(text, ruleId, target) {
  return h('span', { class: 'rulelink', 'data-rule-link': ruleId || '', onclick: function (ev) { ev.stopPropagation(); if (target) ruleCard(target, ruleId); } }, text);
}

/* ---------------- cytoscape helpers ---------------- */
function baseStyle(curve) {
  var ink = css('--ink'), ink2 = css('--ink-2'), surf = css('--surface-2');
  return [
    { selector: 'node', style: { 'background-color': css('--node'), 'width': 'data(size)', 'height': 'data(size)', 'label': '',
      'font-size': 10, 'color': ink, 'text-valign': 'bottom', 'text-margin-y': 3, 'text-outline-color': surf, 'text-outline-width': 2,
      'min-zoomed-font-size': 7, 'border-width': 0, 'text-wrap': 'wrap', 'text-max-width': 140 } },
    { selector: 'node.lbl, node:selected, node.hl, node.on-path', style: { 'label': 'data(label)' } },
    { selector: 'node.t-person', style: { 'background-color': css('--node-person') } },
    { selector: 'node.t-sponsor', style: { 'shape': 'diamond' } },
    { selector: 'node.t-intermediary', style: { 'shape': 'hexagon', 'background-color': css('--s7') } },
    { selector: 'node.t-fund', style: { 'shape': 'round-rectangle' } },
    { selector: 'node.northwind, node.our_person', style: { 'background-color': css('--s3') } },
    { selector: 'node.tier_a, node.path_target, node.subject', style: { 'background-color': css('--s1') } },
    { selector: 'node.platform', style: { 'background-color': css('--s2') } },
    { selector: 'node.fund_iii_portfolio', style: { 'background-color': css('--s5') } },
    { selector: 'node.coverage_gap', style: { 'border-width': 4, 'border-color': css('--crit') } },
    { selector: 'node:selected', style: { 'border-width': 3, 'border-color': css('--accent'), 'font-weight': 700 } },
    { selector: 'edge', style: { 'width': 1, 'line-color': css('--edge'), 'curve-style': curve, 'opacity': 0.8, 'font-size': 9,
      'color': ink2, 'text-outline-color': surf, 'text-outline-width': 2, 'min-zoomed-font-size': 7 } },
    { selector: 'edge.e-tenure', style: { 'line-color': css('--s1') } },
    { selector: 'edge.e-board', style: { 'line-color': css('--s7') } },
    { selector: 'edge.e-deal', style: { 'line-color': css('--s2') } },
    { selector: 'edge.e-commercial', style: { 'line-color': css('--s3') } },
    { selector: 'edge.e-crm', style: { 'line-color': css('--s5') } },
    { selector: 'edge.e-ownership', style: { 'line-color': css('--ink-3') } },
    { selector: 'edge.e-employment', style: { 'line-color': css('--edge') } },
    { selector: 'edge.e-rejected', style: { 'line-color': css('--crit'), 'line-style': 'dashed', 'opacity': 0.25 } },
    { selector: 'edge:selected', style: { 'width': 3, 'line-color': css('--accent'), 'opacity': 1 } },
    { selector: '.off', style: { 'display': 'none' } },
    { selector: '.faded', style: { 'opacity': 0.1, 'text-opacity': 0 } },
    { selector: 'edge.hl', style: { 'width': 2.5, 'opacity': 1 } },
    { selector: 'edge.path-best', style: { 'width': 5, 'line-color': css('--accent'), 'opacity': 1, 'label': 'data(label)' } },
    { selector: 'edge.path-alt', style: { 'width': 3, 'line-style': 'dashed', 'line-color': css('--ink-3'), 'opacity': 0.9, 'label': 'data(label)' } },
    { selector: 'edge.rejected-on', style: { 'width': 3, 'line-style': 'dashed', 'line-color': css('--crit'), 'opacity': 1, 'label': 'data(label)' } },
    { selector: 'node.on-path', style: { 'border-width': 3, 'border-color': css('--accent') } },
    { selector: 'edge.conflict', style: { 'width': 4, 'line-color': css('--crit'), 'opacity': 1, 'label': 'data(label)' } },
    { selector: 'edge.info', style: { 'width': 3, 'line-style': 'dashed', 'line-color': css('--s4'), 'opacity': 1, 'label': 'data(label)' } },
    { selector: 'edge.ctx', style: { 'width': 1.5, 'line-style': 'dashed', 'line-color': css('--edge'), 'opacity': 0.9, 'label': 'data(label)' } },
    { selector: 'node.ctx', style: { 'background-color': css('--surface-2'), 'border-width': 1.5, 'border-color': css('--ink-3'), 'color': css('--ink-3') } },
    { selector: 'node.unreached', style: { 'border-width': 3, 'border-style': 'dashed', 'border-color': css('--crit') } }
  ];
}
function makeCy(viewId, container, file, vgPtr, nodeExtra, opts) {
  opts = opts || {};
  var vg = get(file, vgPtr), els = [];
  /* positions come from the exports; only a uniform rescale to the container size happens here */
  var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  vg.nodes.forEach(function (n) { minx = Math.min(minx, n.x); maxx = Math.max(maxx, n.x); miny = Math.min(miny, n.y); maxy = Math.max(maxy, n.y); });
  var cw = container.clientWidth || 900, ch = container.clientHeight || 520;
  var box = vg.nodes.length > 300 ? Math.max(cw, ch, 800) : Math.max(320, Math.min(cw, ch) - 80);
  var k = box / Math.max(maxx - minx, maxy - miny, 1);
  vg.nodes.forEach(function (n, i) {
    var d = { id: n.id, type: n.type, idx: i, size: 16, label: lab([[file, vgPtr + '/nodes/' + i + '/label']]) };
    var cls = ['t-' + n.type].concat(n.tags || []);
    if (nodeExtra) nodeExtra(n, i, d, cls);
    els.push({ group: 'nodes', data: d, position: { x: (n.x - minx) * k, y: (n.y - miny) * k }, classes: cls.join(' ') });
  });
  vg.edges.forEach(function (e, i) {
    var d = { id: e.id, source: e.source, target: e.target, type: e.type, idx: i, label: '' };
    if (e.label) d.label = lab([[file, vgPtr + '/edges/' + i + '/label']]);
    els.push({ group: 'edges', data: d, classes: 'e-' + e.type });
  });
  var big = els.length > 1500;
  var cy = cytoscape({ container: container, elements: els, style: baseStyle(big ? 'haystack' : 'straight'), layout: { name: 'preset', fit: true, padding: 40 },
    minZoom: 0.05, maxZoom: 4, boxSelectionEnabled: false, textureOnViewport: big, hideEdgesOnViewport: big,
    pixelRatio: big ? 1 : 'auto', selectionType: 'single' });
  E.cys[viewId] = cy;
  return cy;
}
function fitTo(cy, eles, maxZ) {
  var bb = eles.boundingBox(), w = cy.width(), ht = cy.height(), pad = 60;
  if (!w || !ht || !isFinite(bb.w)) return;
  var z = Math.min((w - 2 * pad) / Math.max(bb.w, 1), (ht - 2 * pad) / Math.max(bb.h, 1));
  z = Math.max(cy.minZoom(), Math.min(z, maxZ || 1.6));
  var cx = (bb.x1 + bb.x2) / 2, cyy = (bb.y1 + bb.y2) / 2;
  cy.stop();
  cy.animate({ zoom: z, pan: { x: w / 2 - z * cx, y: ht / 2 - z * cyy } }, { duration: 300 });
}

/* ---------------- shell ---------------- */
var VIEW_DEFS = {
  overview: { label: 'Overview', file: 'graph', init: initOverview },
  score: { label: 'Scorecard', file: 'q_score', init: initScore },
  path: { label: 'Warm path', file: 'q_path', init: initPath },
  flow: { label: 'Deal flow', file: 'q_flow', init: initFlow },
  conflict: { label: 'Conflict check', file: 'q_conflict', init: initConflict },
  addon: { label: 'Add-on map (backup)', file: 'q_addon', init: initAddon }
};
/* nav tabs follow meta.view_order (default: the v2 arc); any other exported view stays reachable by #id */
var ORDER = (X.meta.view_order || ['overview', 'score', 'path', 'flow', 'conflict']).filter(function (v) {
  return VIEW_DEFS[v] && X[VIEW_DEFS[v].file];
});
if (ORDER.indexOf('overview') < 0) ORDER.unshift('overview');
var HIDDEN = Object.keys(VIEW_DEFS).filter(function (v) { return ORDER.indexOf(v) < 0 && X[VIEW_DEFS[v].file]; });
E.views = ORDER.slice();
E.hiddenViews = HIDDEN.slice();
var SECTIONS = {}, TABS = {}, INITED = {}, CURRENT = null;

function header() {
  var sub = document.getElementById('brand-sub');
  add(sub, [V('meta', '/customer_display_name'), ' | ', V('meta', '/fund_name'), ' | As of ', V('meta', '/as_of_date')]);
  var src = X.meta.source, el = document.getElementById('source');
  if (src === 'RAI') {
    add(el, [h('span', { class: 'pill live' }, 'Live RAI export'), h('div', { class: 'small' }, 'Generated ', V('meta', '/generated_at'))]);
  } else {
    add(el, h('span', { class: 'pill fake' }, V('meta', '/source'), ' DATA'));
    var b = document.getElementById('banner');
    b.hidden = false;
    add(b, [V('meta', '/source'), ' DATA. These are not results from the RelationalAI model. Do not present.']);
  }
  var tabs = document.getElementById('tabs');
  ORDER.concat(HIDDEN).forEach(function (id) {
    var t = h('button', { class: 'tab', role: 'tab', id: 'tab-' + id, 'data-view': id, 'aria-selected': 'false', hidden: HIDDEN.indexOf(id) >= 0,
      onclick: function () { show(id); } }, VIEW_DEFS[id].label);
    TABS[id] = t; add(tabs, t);
    var s = h('section', { class: 'view', id: 'view-' + id, role: 'tabpanel', hidden: true });
    SECTIONS[id] = s; add(document.getElementById('views'), s);
  });
}
function show(id, arg) {
  if (!SECTIONS[id]) id = ORDER[0];
  if (CURRENT && CURRENT !== id) { SECTIONS[CURRENT].hidden = true; TABS[CURRENT].setAttribute('aria-selected', 'false'); if (HIDDEN.indexOf(CURRENT) >= 0) TABS[CURRENT].hidden = true; }
  SECTIONS[id].hidden = false; TABS[id].setAttribute('aria-selected', 'true'); TABS[id].hidden = false;
  CURRENT = id;
  if (!INITED[id]) {
    INITED[id] = true;
    try { VIEW_DEFS[id].init(SECTIONS[id]); }
    catch (e) { console.error('view ' + id + ' failed', e); add(SECTIONS[id], h('div', { class: 'err' }, 'This view failed to render.')); }
  } else if (E.cys[id]) { E.cys[id].resize(); }
  if (location.hash.slice(1).split('/')[0] !== id) { try { history.replaceState(null, '', '#' + id); } catch (e) { /* file URL */ } }
  if (arg && E.api[id]) E.api[id](arg);
}
E.show = show;
function viewFrame(sec, file, qid) {
  var main = h('div', { class: 'view-main' }), panel = h('aside', { class: 'panel' });
  add(sec, [main, panel]);
  if (qid) {
    add(main, h('div', { class: 'view-head' }, h('div', { class: 'q-label' }, V(file, '/question_id')), h('div', { class: 'q-text' }, V(file, '/business_question'))));
  }
  return { main: main, panel: panel };
}
function panelSections(panel, names) {
  var out = {};
  names.forEach(function (n) { var hd = h('h3', null, n[1]); var body = h('div', { id: n[0] }); add(panel, [hd, body]); out[n[0]] = body; });
  return out;
}
function sqlTable(qid, title, onRow) {
  var base = '/questions/' + qid, q = get('sql_baseline', base);
  if (!q) return h('div', { class: 'empty' }, 'No SQL baseline exported for this question.');
  var tbody = h('tbody');
  q.rows.forEach(function (r, i) {
    var rb = base + '/rows/' + i;
    add(tbody, h('tr', { class: onRow ? 'clickable' : null, onclick: onRow ? function () { onRow(r.entity_id); } : null },
      h('td', { class: 'num' }, V('sql_baseline', rb + '/rank', 'int')),
      h('td', { class: r.verdict === 'decoy' ? 'struck' : null }, V('sql_baseline', rb + '/name'),
        r.note ? h('div', { class: 'small muted' }, V('sql_baseline', rb + '/note')) : null),
      h('td', { class: 'num' }, V('sql_baseline', rb + '/metric', typeof r.metric === 'number' ? (Number.isInteger(r.metric) ? 'int' : 'f1') : 'raw')),
      h('td', null, r.verdict === 'decoy' ? h('span', { class: 'chip decoy' }, 'Wrong') : (r.verdict === 'agrees' ? h('span', { class: 'chip good' }, 'Agrees') : null))));
  });
  var missed = q.missed.length ? h('div', { style: 'margin-top:10px' }, h('div', { class: 'small muted' }, 'Missed by the screen'),
    q.missed.map(function (m, i) { return h('div', { class: 'small' }, V('sql_baseline', base + '/missed/' + i + '/name'), ': ', V('sql_baseline', base + '/missed/' + i + '/note')); })) : null;
  return h('div', null,
    title ? h('div', { style: 'font-weight:620' }, title) : null,
    h('div', { class: 'small muted' }, V('sql_baseline', base + '/description'), ' (', V('sql_baseline', base + '/sql_file'), ')'),
    h('table', { class: 't', style: 'margin-top:6px' }, h('thead', null, h('tr', null, h('th', { class: 'num' }, 'Rank'), h('th', null, 'Name'),
      h('th', { class: 'num' }, V('sql_baseline', base + '/metric_label')), h('th', null, ''))), tbody), missed);
}
function contrastTiles(qid, file, kgPtr, kgLabelNode, extra) {
  var base = '/questions/' + qid;
  if (!get('sql_baseline', base)) return null;
  return h('div', { class: 'tiles' },
    h('div', { class: 'tile contrast' }, h('div', { class: 'k' }, 'SQL screen'), h('div', { class: 'v' }, V('sql_baseline', base + '/row_count', 'int')),
      h('div', { class: 'd' }, V('sql_baseline', base + '/description'))),
    h('div', { class: 'tile' }, h('div', { class: 'k' }, 'Knowledge graph'), h('div', { class: 'v' }, V(file, kgPtr, 'int')), h('div', { class: 'd' }, kgLabelNode)),
    extra || null);
}

/* ---------------- overview (global graph) ---------------- */
var TAG_TEXT = { northwind: 'Our firm', our_person: 'Our team', tier_a: 'Tier A target', not_in_crm: 'No coverage', path_target: 'Warm-path target',
  platform: 'Platform', fund_iii_portfolio: 'Fund III portfolio', coverage_gap: 'Coverage gap', subject: 'Subject' };
function tagChips(tags) {
  return (tags || []).filter(function (t) { return TAG_TEXT[t]; }).map(function (t) {
    return h('span', { class: 'chip' + (t === 'coverage_gap' || t === 'not_in_crm' ? ' warn' : '') }, TAG_TEXT[t]);
  });
}
function factsGrid(file, base, facts, ruleTarget) {
  return h('div', { class: 'facts' }, facts.map(function (fa, j) {
    var fb = base + '/facts/' + j;
    var val = V(file, fb + '/value', fa.fmt || 'raw');
    var cell = h('div', { class: 'fv' + (fa.rule_id ? ' has-rule' : '') }, val);
    if (fa.rule_id) cell.addEventListener('click', function () { ruleCard(ruleTarget, fa.rule_id); });
    return [h('div', { class: 'fk' }, V(file, fb + '/label')), cell];
  }));
}
function initOverview(sec) {
  var G = X.graph, NI = idx(G.nodes, 'id'), EI = idx(G.edges, 'id'), TI = idx(G.node_types, 'id'), ETI = idx(G.edge_types, 'id');
  var fr = viewFrame(sec, 'graph', false);
  var head = h('div', { class: 'view-head' },
    h('div', { class: 'q-label' }, 'The model'),
    h('div', { class: 'q-text' }, 'One semantic layer over CRM, deal history, people and commercial data'),
    h('div', { class: 'small muted', style: 'margin-top:2px' }, 'Showing ', V('graph', '/stats/num_nodes', 'int'), ' entities and ',
      V('graph', '/stats/num_edges', 'int'), ' relationships',
      G.stats.model_nodes != null ? [' of ', V('graph', '/stats/model_nodes', 'int'), ' entities in the model'] : null, '.'),
    X.meta.counts ? h('div', { class: 'small', style: 'margin-top:2px' }, 'Your pipeline has ', V('meta', '/counts/pipeline_companies', 'int'),
      ' names. Which do you call on Monday, why now, and who gets us in?') : null);
  var input = h('input', { type: 'search', placeholder: 'Search a company or person', 'aria-label': 'Search', id: 'search' });
  var results = h('div', { class: 'results', hidden: true, id: 'search-results' });
  var toggles = h('div', { class: 'legend' });
  var tb = h('div', { class: 'toolbar' },
    h('div', { class: 'search' }, input, results),
    h('button', { class: 'btn', id: 'hop1', onclick: function () { expand(1); } }, S('1 hop')),
    h('button', { class: 'btn', id: 'hop2', onclick: function () { expand(2); } }, S('2 hops')),
    h('button', { class: 'btn', id: 'reset', onclick: reset }, 'Reset'));
  var tb2 = h('div', { class: 'toolbar' }, h('span', { class: 'small muted' }, 'Relationships'), toggles);
  var cont = h('div', { class: 'cy', id: 'cy-overview' });
  add(fr.main, [head, tb, tb2, cont]);
  var P = panelSections(fr.panel, [['ov-sel', 'Selection'], ['ov-rule', 'Rule behind this fact'], ['ov-legend', 'Legend']]);
  add(P['ov-sel'], h('div', { class: 'empty' }, S('Search or click a node to inspect it. Use 1 hop or 2 hops to expand its neighborhood.')));
  ruleCard(P['ov-rule'], null);
  add(P['ov-legend'], h('div', { class: 'legend' },
    h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s3') }), 'Our firm and team'),
    h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s1') }), 'Tier A target'),
    h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s2') }), 'Platform'),
    h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s7') }), 'Intermediary'),
    h('span', null, h('span', { class: 'sw', style: 'background:' + css('--node') }), 'Other organization or person')));

  G.edge_types.forEach(function (t, i) {
    var cb = h('input', { type: 'checkbox', checked: true, 'data-type': t.id });
    var lbl = h('label', { class: 'toggle', 'data-edge-type': t.id }, cb,
      h('span', { class: 'sw line', style: 'background:' + css(EDGE_COLOR[t.id] || '--edge') }), V('graph', '/edge_types/' + i + '/label'),
      ' ', h('span', { class: 'muted' }, V('graph', '/edge_types/' + i + '/count', 'int')));
    cb.addEventListener('change', function () {
      lbl.classList.toggle('off', !cb.checked);
      var es = cy.edges('[type = "' + t.id + '"]');
      if (cb.checked) es.removeClass('off'); else es.addClass('off');
      if (E.state.ovHops && E.state.ovSel) expand(E.state.ovHops);
    });
    add(toggles, lbl);
  });

  var cy = makeCy('overview', cont, 'graph', '', function (n, i, d, cls) {
    d.size = n.type === 'person' ? 9 : 13;
    var t = n.tags || [];
    if (t.indexOf('tier_a') >= 0 || t.indexOf('platform') >= 0 || t.indexOf('coverage_gap') >= 0 || t.indexOf('path_target') >= 0) { d.size = 20; cls.push('lbl'); }
    if (t.indexOf('northwind') >= 0 || t.indexOf('our_person') >= 0) { d.size = Math.max(d.size, 15); cls.push('lbl'); }
  });
  /* the global graph has edge facts and evidence; edge labels stay off on the canvas */
  function selectNode(id) {
    var n = cy.getElementById(id); if (n.empty()) return;
    cy.elements().unselect(); n.select(); E.state.ovSel = id;
    var i = NI[id], node = G.nodes[i], base = '/nodes/' + i, sel = clear(P['ov-sel']);
    add(sel, [h('div', { class: 'title' }, V('graph', base + '/label')),
      h('div', { class: 'small muted', style: 'margin-bottom:8px' }, V('graph', '/node_types/' + TI[node.type] + '/label'), ' ', tagChips(node.tags)),
      node.facts.length ? factsGrid('graph', base, node.facts, P['ov-rule']) : null]);
    var conn = h('ul', { class: 'neighbors', id: 'ov-neighbors' }), shown = 0;
    n.connectedEdges().forEach(function (e) {
      if (shown >= 25) return; shown++;
      var other = e.source().id() === id ? e.target().id() : e.source().id(), ei = EI[e.id()];
      add(conn, h('li', { onclick: function () { selectEdge(e.id()); } },
        h('span', null, V('graph', '/nodes/' + NI[other] + '/label')), h('span', { class: 'muted small' }, V('graph', '/edge_types/' + ETI[G.edges[ei].type] + '/label'))));
    });
    add(sel, [h('h3', null, 'Connections'), conn, n.connectedEdges().length > 25 ? h('div', { class: 'small muted' }, S('More connections not listed. Use 1 hop to see them.')) : null]);
    if (E.state.ovHops) expand(E.state.ovHops); else cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.1) }, { duration: 250 });
  }
  function selectEdge(id) {
    var i = EI[id]; if (i === undefined) return;
    var e = G.edges[i], base = '/edges/' + i, sel = clear(P['ov-sel']);
    cy.elements().unselect(); cy.getElementById(id).select();
    add(sel, [h('div', { class: 'title' }, V('graph', '/nodes/' + NI[e.source] + '/label'), ' and ', V('graph', '/nodes/' + NI[e.target] + '/label')),
      h('div', { class: 'small muted', style: 'margin-bottom:6px' }, V('graph', '/edge_types/' + ETI[e.type] + '/label')),
      h('div', { style: 'margin-bottom:8px' }, V('graph', base + '/evidence')),
      e.facts.length ? factsGrid('graph', base, e.facts, P['ov-rule']) : null,
      h('div', { style: 'margin-top:8px' }, h('button', { class: 'btn link', onclick: function () { selectNode(e.source); } }, 'Open ', V('graph', '/nodes/' + NI[e.source] + '/label')))]);
    ruleCard(P['ov-rule'], e.rule_id || G.edge_types[ETI[e.type]].rule_id);
  }
  function expand(k) {
    if (!E.state.ovSel) { clear(P['ov-sel']); add(P['ov-sel'], h('div', { class: 'empty' }, 'Select a node first, then expand.')); return; }
    E.state.ovHops = k;
    var nb = cy.getElementById(E.state.ovSel);
    for (var s = 0; s < k; s++) nb = nb.union(nb.connectedEdges(':visible').connectedNodes());
    var es = nb.connectedEdges(':visible').filter(function (e) { return nb.contains(e.source()) && nb.contains(e.target()); });
    cy.batch(function () { cy.elements().addClass('faded').removeClass('hl'); nb.union(es).removeClass('faded').addClass('hl'); });
    document.getElementById('hop1').setAttribute('aria-pressed', String(k === 1));
    document.getElementById('hop2').setAttribute('aria-pressed', String(k === 2));
    fitTo(cy, nb);
  }
  function reset() {
    E.state.ovHops = 0; E.state.ovSel = null;
    cy.batch(function () { cy.elements().removeClass('faded hl').unselect(); });
    document.getElementById('hop1').setAttribute('aria-pressed', 'false'); document.getElementById('hop2').setAttribute('aria-pressed', 'false');
    clear(P['ov-sel']); add(P['ov-sel'], h('div', { class: 'empty' }, 'Search or click a node to inspect it.'));
    cy.animate({ fit: { eles: cy.elements(), padding: 40 } }, { duration: 250 });
  }
  cy.on('tap', 'node', function (ev) { selectNode(ev.target.id()); });
  cy.on('tap', 'edge', function (ev) { selectEdge(ev.target.id()); });
  input.addEventListener('input', function () {
    var q = input.value.trim().toLowerCase(); clear(results);
    if (q.length < 2) { results.hidden = true; return; }
    var hits = 0;
    for (var i = 0; i < G.nodes.length && hits < 10; i++) {
      if (G.nodes[i].label.toLowerCase().indexOf(q) < 0) continue;
      hits++;
      (function (i) {
        add(results, h('button', { 'data-node': G.nodes[i].id, onclick: function () { results.hidden = true; input.value = G.nodes[i].label; selectNode(G.nodes[i].id); } },
          V('graph', '/nodes/' + i + '/label'), h('span', { class: 'muted small' }, V('graph', '/node_types/' + TI[G.nodes[i].type] + '/label'))));
      })(i);
    }
    if (!hits) add(results, h('div', { class: 'empty', style: 'padding:8px 10px' }, 'No match'));
    results.hidden = false;
  });
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { var b = results.querySelector('button'); if (b) b.click(); }
    if (ev.key === 'Escape') results.hidden = true;
  });
  E.api.overview = function (id) { selectNode(id); };
  E.api.overviewEdge = selectEdge;
  E.api.expand = expand;
}
var EDGE_COLOR = { tenure: '--s1', board: '--s7', deal: '--s2', commercial: '--s3', crm: '--s5', ownership: '--ink-3', employment: '--edge' };

/* ---------------- scorecard (Q-SCORE) ---------------- */
function initScore(sec) {
  var Q = X.q_score, fr = viewFrame(sec, 'q_score', true), CI = idx(Q.components, 'id');
  add(fr.main.firstChild, contrastTiles('Q-SCORE', 'q_score', '/summary/tier_a', ['Tier A, score ', V('q_score', '/tier_thresholds/A', 'int'), ' or more']),
    null);
  var tiles = fr.main.firstChild.querySelector('.tiles');
  if (tiles) add(tiles, h('div', { class: 'tile' }, h('div', { class: 'k' }, 'No coverage'), h('div', { class: 'v' }, V('q_score', '/summary/tier_a_not_in_crm', 'int')),
    h('div', { class: 'd' }, 'Tier A names with no pipeline entry and no logged touch')));
  var modeSeg = h('div', { class: 'seg' });
  var bAct = h('button', { class: 'btn on', id: 'score-act1', onclick: function () { setMode('act1'); } }, 'Scored');
  var bFin = Q.finale ? h('button', { class: 'btn', id: 'score-finale', onclick: function () { setMode('finale'); } }, 'Finale re-score') : null;
  add(modeSeg, [bAct, bFin]);
  var allCb = h('input', { type: 'checkbox', id: 'score-all' });
  var naiveBtn = h('button', { class: 'btn', id: 'score-naive', 'aria-pressed': 'false', onclick: function () { toggleNaive(); } }, 'Compare with SQL screen');
  var expBtn = h('button', { class: 'btn', id: 'score-expand', onclick: function () { expandAll(); } }, 'Expand all');
  add(fr.main, h('div', { class: 'toolbar' }, modeSeg, h('label', { class: 'toggle' }, allCb, 'Show all scored companies'), naiveBtn, expBtn,
    h('span', { class: 'legend', style: 'margin-left:auto' },
      h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s1') }), 'Fit'),
      h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s2') }), 'Readiness'),
      h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s3') }), 'Access'))));
  var list = h('div', { class: 'sc-list', id: 'score-list' }), naive = h('div', { class: 'sc-naive', id: 'score-naive-panel', hidden: true });
  var wrap = h('div', { class: 'sc-wrap' }, list, naive);
  add(fr.main, h('div', { class: 'scroll' }, wrap));
  add(naive, sqlTable('Q-SCORE', 'What a SQL screen returns'));
  var P = panelSections(fr.panel, [['sc-rule', 'Rule behind this point'], ['sc-comp', 'Score components'], ['sc-inel', 'Near misses (ineligible)']]);
  ruleCard(P['sc-rule'], null);
  add(P['sc-comp'], h('table', { class: 't' }, h('thead', null, h('tr', null, h('th', null, 'Component'), h('th', null, 'Group'), h('th', { class: 'num' }, 'Max'))),
    h('tbody', null, Q.components.map(function (c, k) {
      return h('tr', { class: 'clickable', onclick: function () { ruleCard(P['sc-rule'], c.rule_id); } },
        h('td', null, V('q_score', '/components/' + k + '/label')), h('td', { class: 'muted' }, V('q_score', '/components/' + k + '/group')),
        h('td', { class: 'num' }, V('q_score', '/components/' + k + '/max_points', 'int')));
    }))));
  add(P['sc-comp'], h('div', { class: 'small muted', style: 'margin-top:6px' }, 'Readiness is capped at ', V('q_score', '/readiness_cap', 'int'),
    ' points. Tier A is ', V('q_score', '/tier_thresholds/A', 'int'), ' or more, Tier B is ', V('q_score', '/tier_thresholds/B', 'int'), ' or more.'));
  if (Q.ineligible.length) add(P['sc-inel'], Q.ineligible.map(function (r, i) {
    return h('div', { class: 'claim' }, h('div', { style: 'font-weight:600' }, V('q_score', '/ineligible/' + i + '/name')), h('div', { class: 'small' }, V('q_score', '/ineligible/' + i + '/reason')));
  })); else add(P['sc-inel'], h('div', { class: 'empty' }, 'None exported.'));

  var mode = 'act1', open = {};
  function bar(r) {
    var m = Q.max_score || 100;
    return h('div', { class: 'bar' }, h('span', { class: 'fit', style: 'width:' + (100 * r.fit / m) + '%' }),
      h('span', { class: 'readiness', style: 'width:' + (100 * r.readiness / m) + '%' }), h('span', { class: 'access', style: 'width:' + (100 * r.access / m) + '%' }));
  }
  function detail(r, i) {
    var base = '/rows/' + i, CJ = idx(r.components, 'id');
    var d = h('div', { class: 'sc-detail', 'data-company': r.company_id });
    add(d, h('div', { class: 'meta-line' },
      h('span', null, r.sector_path.map(function (s, k) { return [k ? ' > ' : '', V('q_score', base + '/sector_path/' + k)]; })),
      h('span', null, 'EBITDA ', V('q_score', base + '/ebitda_musd', 'musd1'), ' on revenue ', V('q_score', base + '/revenue_musd', 'musd1')),
      h('span', null, 'Owner: ', r.owner ? V('q_score', base + '/owner') : 'Founder or family'),
      h('span', null, 'CRM: ', r.in_crm ? V('q_score', base + '/pipeline_stage') : 'No coverage')));
    add(d, h('div', { class: 'sc-why' }, V('q_score', base + '/why')));
    var groups = { fit: '--s1', readiness: '--s2', access: '--s3' };
    Q.components.forEach(function (c, k) {
      var j = CJ[c.id]; if (j === undefined) return;
      var cb = base + '/components/' + j, pts = r.components[j].points;
      add(d, h('div', { class: 'comp' + (pts ? '' : ' zero'), 'data-component': c.id },
        h('span', { class: 'sw', style: 'background:' + (pts ? css(groups[c.group]) : 'transparent') + ';border:1px solid ' + css(groups[c.group]) }),
        h('span', { class: 'lbl', onclick: function () { ruleCard(P['sc-rule'], c.rule_id); } }, V('q_score', '/components/' + k + '/label')),
        h('span', { class: 'pts' }, V('q_score', cb + '/points', 'int'), ' / ', V('q_score', '/components/' + k + '/max_points', 'int')),
        h('span', null, V('q_score', cb + '/evidence'))));
    });
    add(d, h('div', { class: 'small muted', style: 'margin-top:6px' }, 'Fit ', V('q_score', base + '/fit', 'int'), ', readiness ', V('q_score', base + '/readiness', 'int'),
      ', access ', V('q_score', base + '/access', 'int'), '. Click a component for its rule.'));
    return d;
  }
  function renderAct1() {
    var showAll = allCb.checked;
    Q.rows.forEach(function (r, i) {
      if (!showAll && r.tier !== 'A') return;
      var base = '/rows/' + i;
      var row = h('div', { class: 'sc-row' + (open[r.company_id] ? ' open' : ''), 'data-company': r.company_id, onclick: function () { open[r.company_id] = !open[r.company_id]; render(); } },
        h('div', { class: 'sc-rank' }, V('q_score', base + '/rank', 'int')),
        h('div', { class: 'sc-name' }, V('q_score', base + '/name'), r.in_crm ? null : h('span', { class: 'chip warn', 'data-badge': 'not-in-crm' }, 'No coverage')),
        h('div', null, h('span', { class: 'chip tier-' + r.tier }, 'Tier ', V('q_score', base + '/tier'))),
        bar(r), h('div', { class: 'sc-score' }, V('q_score', base + '/score', 'int')));
      add(list, row);
      if (open[r.company_id]) add(list, detail(r, i));
    });
  }
  function renderFinale() {
    var F = Q.finale, RI = idx(Q.rows, 'company_id');
    add(list, h('div', { class: 'small muted', style: 'margin:8px 0 2px' }, V('q_score', '/finale/description')));
    F.rows.forEach(function (r, i) {
      if (!allCb.checked && r.tier !== 'A' && r.tier !== 'Conflict' && r.prev_tier !== 'A') return;
      var base = '/finale/rows/' + i;
      var row = h('div', { class: 'sc-row', 'data-company': r.company_id, onclick: function () { open[r.company_id] = !open[r.company_id]; render(); } },
        h('div', { class: 'sc-rank' }, r.rank === null ? '' : V('q_score', base + '/rank', 'int')),
        h('div', { class: 'sc-name' }, h('span', { class: r.conflict ? 'struck' : null }, V('q_score', base + '/name')),
          h('span', { class: 'move' }, r.prev_rank === null ? 'new' : ['was #', V('q_score', base + '/prev_rank', 'int')]),
          r.delta ? h('span', { class: 'move' }, h('span', { class: 'up' }, V('q_score', base + '/delta', 'sint'))) : null),
        h('div', null, h('span', { class: 'chip tier-' + r.tier }, r.tier === 'Conflict' ? 'Hold until cross-fund clearance' : ['Tier ', V('q_score', base + '/tier')])),
        h('div', { class: 'small muted' }, 'Before: ', V('q_score', base + '/prev_score', 'int'), ', Tier ', V('q_score', base + '/prev_tier')),
        h('div', { class: 'sc-score' }, V('q_score', base + '/score', 'int')));
      add(list, row);
      if (open[r.company_id]) {
        var d = h('div', { class: 'sc-detail' });
        if (r.conflict) add(d, h('div', { class: 'cold' }, h('div', { class: 'ct' }, 'Conflict: ', V('q_score', base + '/conflict/counterparty_name')),
          h('div', null, V('q_score', base + '/conflict/reason')), ruleLink('Show the conflict rule', r.conflict.rule_id, P['sc-rule'])));
        r.added_components.forEach(function (c, j) {
          var cb = base + '/added_components/' + j;
          add(d, h('div', { class: 'comp' }, h('span', { class: 'sw', style: 'background:' + css('--s3') }),
            h('span', { class: 'lbl', onclick: function () { ruleCard(P['sc-rule'], c.id); } }, V('q_score', cb + '/id')),
            h('span', { class: 'pts' }, V('q_score', cb + '/points', 'sint')), h('span', null, V('q_score', cb + '/evidence'))));
        });
        if (!r.conflict && !r.added_components.length) add(d, h('div', { class: 'empty' }, 'No change from the first scoring.'));
        add(list, d);
      }
    });
  }
  function render() { clear(list); if (mode === 'finale') renderFinale(); else renderAct1(); }
  function setMode(m) { mode = m; bAct.classList.toggle('on', m === 'act1'); if (bFin) bFin.classList.toggle('on', m === 'finale'); open = {}; render(); }
  function toggleNaive() { naive.hidden = !naive.hidden; wrap.classList.toggle('with-naive', !naive.hidden); naiveBtn.setAttribute('aria-pressed', String(!naive.hidden)); }
  function expandAll() { (mode === 'finale' ? Q.finale.rows : Q.rows).forEach(function (r) { open[r.company_id] = true; }); render(); }
  allCb.addEventListener('change', render);
  render();
  E.api.score = function (a) {
    if (a.mode) setMode(a.mode);
    if (a.all !== undefined) { allCb.checked = !!a.all; render(); }
    if (a.expandAll) expandAll();
    if (a.naive !== undefined && a.naive === naive.hidden) toggleNaive();
  };
}

/* ---------------- warm path (Q-PATH) ---------------- */
function initPath(sec) {
  var Q = X.q_path, fr = viewFrame(sec, 'q_path', true), TI = idx(Q.tie_types, 'id');
  add(fr.main.firstChild, contrastTiles('Q-PATH', 'sql_baseline', '/questions/Q-PATH/kg_count', V('sql_baseline', '/questions/Q-PATH/kg_label')));
  var picker = h('div', { class: 'picker', id: 'path-picker' });
  add(fr.main, h('div', { class: 'toolbar' }, h('span', { class: 'small muted' }, 'Pick a target'), picker,
    h('span', { class: 'legend', style: 'margin-left:auto' },
      h('span', null, h('span', { class: 'sw line', style: 'background:' + css('--accent') }), 'Warmest path'),
      h('span', null, h('span', { class: 'sw line', style: 'background:' + css('--ink-3') }), 'Alternate'),
      h('span', null, h('span', { class: 'sw line', style: 'background:' + css('--crit') }), 'Rejected claim'))));
  var cont = h('div', { class: 'cy', id: 'cy-path' });
  add(fr.main, cont);
  var P = panelSections(fr.panel, [['path-evidence', 'Path evidence'], ['path-rule', 'Rule behind this hop'], ['path-seeds', 'Our people (path starts)']]);
  ruleCard(P['path-rule'], null);
  add(P['path-evidence'], h('div', { class: 'empty' }, 'Pick a target to light up the warmest paths from our people.'));
  add(P['path-seeds'], h('div', null, Q.seeds.map(function (s, i) {
    return h('div', { class: 'small' }, V('q_path', '/seeds/' + i + '/name'), h('span', { class: 'muted' }, ', ', V('q_path', '/seeds/' + i + '/title')));
  })));
  var cy = makeCy('path', cont, 'q_path', '/view_graph', function (n, i, d, cls) {
    d.size = (n.tags || []).indexOf('path_target') >= 0 ? 26 : ((n.tags || []).indexOf('our_person') >= 0 ? 22 : 16);
    cls.push('lbl');
  });
  function dmChip(base, dm) {
    return h('span', { class: 'chip ' + (dm.status === 'warm' ? 'good' : 'crit'), 'data-dm-chip': dm.kind },
      dm.kind === 'CEO' ? 'CEO' : 'Owner designee', ': ',
      dm.status === 'warm' ? [V('q_path', base + '/hops', 'int'), dm.hops === 1 ? ' hop' : ' hops'] : 'cold');
  }
  Q.targets.forEach(function (t, i) {
    var base = '/targets/' + i;
    add(picker, h('button', { class: 'pick', 'data-target': t.company_id, onclick: function () { pick(t.company_id); } },
      h('span', { class: 'pn' }, V('q_path', base + '/company_name')),
      h('span', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, t.decision_makers.map(function (dm, d) { return dmChip(base + '/decision_makers/' + d, dm); }))));
  });
  function hopEl(base, hp) {
    var ti = TI[hp.tie_type];
    return h('li', { class: 'hop', 'data-edge': hp.edge_id },
      h('div', { class: 'hop-who' }, V('q_path', base + '/from_name'), ' to ', V('q_path', base + '/to_name')),
      h('div', { class: 'small' }, ruleLink(hp.tie_label ? V('q_path', base + '/tie_label') : V('q_path', '/tie_types/' + ti + '/label'), hp.rule_id, P['path-rule']),
        ' (', V('q_path', base + '/tie_type'), ')'),
      h('div', { class: 'hop-ev' }, V('q_path', base + '/evidence')),
      h('div', { class: 'hop-meta' },
        hp.org_name ? h('span', null, V('q_path', base + '/org_name')) : null,
        hp.start_date ? h('span', null, V('q_path', base + '/start_date'), ' to ', hp.end_date ? V('q_path', base + '/end_date') : 'present') : null,
        hp.years !== null && hp.years !== undefined ? h('span', null, V('q_path', base + '/years', 'f1'), ' years') : null,
        h('span', null, 'Strength ', V('q_path', base + '/strength', 'f3'))));
  }
  function pick(cid) {
    var ti = -1; Q.targets.forEach(function (t, i) { if (t.company_id === cid) ti = i; });
    if (ti < 0) return;
    E.state.pathTarget = cid;
    picker.querySelectorAll('.pick').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-target') === cid); });
    var t = Q.targets[ti], base = '/targets/' + ti, ev = clear(P['path-evidence']);
    var on = cy.collection(), firstRule = null;
    cy.batch(function () {
      cy.elements().removeClass('path-best path-alt rejected-on on-path unreached').addClass('faded');
      t.decision_makers.forEach(function (dm) {
        var dn = cy.getElementById(dm.person_id); on = on.union(dn);
        if (dm.status !== 'warm') dn.addClass('unreached');
        dm.paths.forEach(function (pa, j) {
          pa.hops.forEach(function (hp) { var e = cy.getElementById(hp.edge_id); e.addClass(j === 0 ? 'path-best' : 'path-alt'); on = on.union(e).union(e.connectedNodes()); if (!firstRule) firstRule = hp.rule_id; });
          pa.node_ids.forEach(function (nid) { var n = cy.getElementById(nid); if (j === 0) n.addClass('on-path'); on = on.union(n); });
        });
      });
      t.rejected_claims.forEach(function (rc) { if (rc.edge_id) { var e = cy.getElementById(rc.edge_id); e.addClass('rejected-on'); on = on.union(e).union(e.connectedNodes()); } });
      on.removeClass('faded');
    });
    if (on.nonempty()) fitTo(cy, on, 1.3);
    add(ev, [h('div', { class: 'title' }, V('q_path', base + '/company_name')),
      h('div', { class: 'small muted' }, 'Score rank ', V('q_path', base + '/score_rank', 'int'), '. Owner: ', t.owner_name ? V('q_path', base + '/owner_name') : 'founder or family', '.'),
      h('div', { style: 'margin:8px 0' }, V('q_path', base + '/summary'))]);
    t.decision_makers.forEach(function (dm, d) {
      var db = base + '/decision_makers/' + d;
      var box = h('div', { 'data-dm': dm.kind, 'data-person': dm.person_id, style: 'margin-top:12px' },
        h('div', { style: 'display:flex;justify-content:space-between;gap:8px;align-items:baseline;margin-bottom:6px' },
          h('span', { style: 'font-weight:620' }, V('q_path', db + '/name'), h('span', { class: 'muted small' }, ', ', V('q_path', db + '/role_label'))), dmChip(db, dm)));
      if (dm.status !== 'warm') {
        add(box, h('div', { class: 'cold', 'data-cold': dm.kind }, h('div', { class: 'ct' }, 'No path within ', V('q_path', '/max_hops', 'int'), ' hops'), h('div', { class: 'small' }, V('q_path', db + '/summary'))));
      } else {
        add(box, h('div', { class: 'small muted', style: 'margin-bottom:6px' }, V('q_path', db + '/summary')));
      }
      dm.paths.forEach(function (pa, j) {
        var pb = db + '/paths/' + j;
        add(box, h('div', { class: 'path-card' + (j === 0 ? ' best' : ''), 'data-path': pa.path_id },
          h('div', { class: 'ph' }, h('span', null, j === 0 ? 'Warmest path' : ['Alternate, rank ', V('q_path', pb + '/rank', 'int')]),
            h('span', null, V('q_path', pb + '/length', 'int'), ' hops, strength ', V('q_path', pb + '/strength', 'f3'))),
          h('ol', { class: 'hops' }, pa.hops.map(function (hp, k) { return hopEl(pb + '/hops/' + k, hp); }))));
      });
      add(ev, box);
    });
    if (t.closest_intermediary) {
      add(ev, h('div', { class: 'claim', id: 'path-closest', style: 'border-style:solid;border-color:' + css('--accent') },
        h('div', { style: 'font-weight:620' }, 'Closest intermediary: ', V('q_path', base + '/closest_intermediary/name')),
        h('div', { class: 'small' }, V('q_path', base + '/closest_intermediary/evidence')),
        h('div', { class: 'small', style: 'margin:4px 0' }, ruleLink('How this is chosen', t.closest_intermediary.rule_id, P['path-rule'])),
        t.next_step ? h('button', { class: 'btn', id: 'path-next', onclick: function () { show(t.next_step.view, t.next_step.node_id); } }, V('q_path', base + '/next_step/label')) : null));
    } else if (t.next_step) {
      add(ev, h('button', { class: 'btn', id: 'path-next', onclick: function () { show(t.next_step.view, t.next_step.node_id); } }, V('q_path', base + '/next_step/label')));
    }
    t.rejected_claims.forEach(function (rc, j) {
      var rb = base + '/rejected_claims/' + j;
      add(ev, h('div', { class: 'claim', 'data-claim': j },
        h('div', { class: 'struck' }, V('q_path', rb + '/claim')),
        h('div', { class: 'small', style: 'margin:4px 0' }, h('span', { class: 'chip crit' }, 'Rejected'), ' ', V('q_path', rb + '/reason')),
        h('div', { class: 'small muted' }, rc.intervals.map(function (iv, k) {
          var ib = rb + '/intervals/' + k;
          return h('div', null, V('q_path', ib + '/name'), ' at ', V('q_path', rb + '/org_name'), ': ', V('q_path', ib + '/start_date'), ' to ', iv.end_date ? V('q_path', ib + '/end_date') : 'present');
        })),
        rc.gap_days !== null ? h('div', { class: 'small' }, 'Gap between tenures: ', V('q_path', rb + '/gap_days', 'int'), ' days') : null,
        h('div', { class: 'small' }, ruleLink('Why this is not a relationship', rc.rule_id, P['path-rule']))));
    });
    if (firstRule) ruleCard(P['path-rule'], firstRule, 'First hop of the warmest path');
    else if (t.rejected_claims.length) ruleCard(P['path-rule'], t.rejected_claims[0].rule_id);
    else ruleCard(P['path-rule'], null);
  }
  cy.on('tap', 'edge', function (ev) {
    var id = ev.target.id(), t = Q.targets.filter(function (x) { return x.company_id === E.state.pathTarget; })[0];
    if (!t) return;
    t.decision_makers.forEach(function (dm) { dm.paths.forEach(function (pa) { pa.hops.forEach(function (hp) { if (hp.edge_id === id) ruleCard(P['path-rule'], hp.rule_id); }); }); });
    t.rejected_claims.forEach(function (rc) { if (rc.edge_id === id) ruleCard(P['path-rule'], rc.rule_id); });
  });
  E.api.path = pick;
  if (Q.targets.length) pick(Q.targets[0].company_id);
}

/* ---------------- add-on map (Q-ADDON, Act 3 variant A) ---------------- */
var US_TILES = { AK: [0, 0], ME: [10, 0], VT: [9, 1], NH: [10, 1], WA: [0, 2], ID: [1, 2], MT: [2, 2], ND: [3, 2], MN: [4, 2], IL: [5, 2], WI: [6, 2],
  MI: [7, 2], NY: [8, 2], RI: [9, 2], MA: [10, 2], OR: [0, 3], NV: [1, 3], WY: [2, 3], SD: [3, 3], IA: [4, 3], IN: [5, 3], OH: [6, 3], PA: [7, 3],
  NJ: [8, 3], CT: [9, 3], CA: [0, 4], UT: [1, 4], CO: [2, 4], NE: [3, 4], MO: [4, 4], KY: [5, 4], WV: [6, 4], VA: [7, 4], MD: [8, 4], DE: [9, 4],
  AZ: [1, 5], NM: [2, 5], KS: [3, 5], AR: [4, 5], TN: [5, 5], NC: [6, 5], SC: [7, 5], DC: [8, 5], OK: [3, 6], LA: [4, 6], MS: [5, 6], AL: [6, 6],
  GA: [7, 6], HI: [0, 7], TX: [3, 7], FL: [8, 7] };
var CAT = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
function usMap(platStates, candStates, wsStates) {
  var m = h('div', { class: 'usmap', 'aria-label': 'US states' });
  Object.keys(US_TILES).forEach(function (st) {
    var c = US_TILES[st], cls = 'st';
    if (wsStates.indexOf(st) >= 0) cls += ' ws'; else if (candStates.indexOf(st) >= 0) cls += ' cand'; else if (platStates.indexOf(st) >= 0) cls += ' plat';
    add(m, h('div', { class: cls, style: 'grid-column:' + (c[0] + 1) + ';grid-row:' + (c[1] + 1), 'data-state': st }, st));
  });
  return m;
}
function initAddon(sec) {
  var Q = X.q_addon, fr = viewFrame(sec, 'q_addon', true), COM = idx(Q.communities, 'id');
  add(fr.main.firstChild, contrastTiles('Q-ADDON', 'sql_baseline', '/questions/Q-ADDON/kg_count', V('sql_baseline', '/questions/Q-ADDON/kg_label')));
  var cont = h('div', { class: 'cy', id: 'cy-addon' });
  var leg = h('div', { class: 'legend' }, h('span', { class: 'small muted' }, 'Communities'), Q.communities.slice(0, 8).map(function (c, k) {
    return h('span', null, h('span', { class: 'sw', style: 'background:' + css(CAT[k]) }), V('q_addon', '/communities/' + k + '/label'));
  }), h('span', { class: 'small muted' }, 'Size shows similarity to the platform'));
  add(fr.main, [h('div', { class: 'toolbar' }, leg), cont]);
  var tbody = h('tbody');
  var tableWrap = h('div', { style: 'max-height:34%;overflow:auto;border-top:1px solid ' + css('--line') + ';background:' + css('--surface') },
    h('table', { class: 't', id: 'addon-table' }, h('thead', null, h('tr', null, h('th', { class: 'num' }, 'Rank'), h('th', null, 'Candidate'), h('th', null, 'Niche'),
      h('th', { class: 'num' }, 'Similarity'), h('th', { class: 'num' }, 'Shared'), h('th', null, 'New states'))), tbody));
  add(fr.main, tableWrap);
  var P = panelSections(fr.panel, [['addon-detail', 'Candidate'], ['addon-map', 'Footprint'], ['addon-rule', 'Rule'], ['addon-sql', 'SQL screen'], ['addon-excl', 'Excluded']]);
  ruleCard(P['addon-rule'], null);
  add(P['addon-sql'], sqlTable('Q-ADDON'));
  add(P['addon-excl'], Q.excluded.length ? Q.excluded.map(function (x, i) {
    return h('div', { class: 'claim' }, h('div', { class: 'muted', style: 'font-weight:600' }, V('q_addon', '/excluded/' + i + '/name')), h('div', { class: 'small' }, V('q_addon', '/excluded/' + i + '/reason')));
  }) : h('div', { class: 'empty' }, 'None.'));
  var maxSim = Math.max.apply(null, Q.candidates.map(function (c) { return c.similarity; }).concat([1e-9]));
  var CAND = idx(Q.candidates, 'company_id');
  var cy = makeCy('addon', cont, 'q_addon', '/view_graph', function (n, i, d, cls) {
    var ci = CAND[n.id];
    if ((n.tags || []).indexOf('platform') >= 0) { d.size = 40; cls.push('lbl'); }
    else if (ci !== undefined) { d.size = 16 + 34 * Q.candidates[ci].similarity / maxSim; cls.push('lbl'); }
    else d.size = 10;
    var k = COM[n.community];
    d.color = (k !== undefined && k < 8) ? css(CAT[k]) : css('--node');
  });
  cy.style().selector('node[color]').style('background-color', 'data(color)').selector('node.platform').style({ 'border-width': 4, 'border-color': css('--ink') }).update();
  Q.candidates.forEach(function (c, i) {
    var b = '/candidates/' + i;
    add(tbody, h('tr', { class: 'clickable', 'data-candidate': c.company_id, onclick: function () { pickC(c.company_id); } },
      h('td', { class: 'num' }, V('q_addon', b + '/rank', 'int')), h('td', null, V('q_addon', b + '/name')), h('td', { class: 'muted' }, V('q_addon', b + '/niche')),
      h('td', { class: 'num' }, V('q_addon', b + '/similarity', 'f3')),
      h('td', { class: 'num' }, V('q_addon', b + '/shared_count', 'int'), ' of ', V('q_addon', b + '/union_count', 'int')),
      h('td', null, c.whitespace_states.length ? c.whitespace_states.map(function (s, k) { return [k ? ', ' : '', V('q_addon', b + '/whitespace_states/' + k)]; }) : h('span', { class: 'muted' }, 'none'))));
  });
  function pickC(cid) {
    var i = CAND[cid]; if (i === undefined) return;
    E.state.addon = cid;
    tbody.querySelectorAll('tr').forEach(function (tr) { tr.classList.toggle('sel', tr.getAttribute('data-candidate') === cid); });
    var c = Q.candidates[i], b = '/candidates/' + i, plat = cy.getElementById(Q.platform.company_id), cn = cy.getElementById(cid);
    var shared = cy.collection();
    c.shared_neighbors.forEach(function (s) { shared = shared.union(cy.getElementById(s.company_id)); });
    var es = shared.connectedEdges().filter(function (e) { var o = e.connectedNodes(); return o.contains(plat) || o.contains(cn); });
    cy.batch(function () { cy.elements().addClass('faded').removeClass('hl'); plat.union(cn).union(shared).union(es).removeClass('faded').addClass('hl'); });
    fitTo(cy, plat.union(cn).union(shared));
    var d = clear(P['addon-detail']);
    add(d, [h('div', { class: 'title' }, V('q_addon', b + '/name')), h('div', { class: 'small muted' }, V('q_addon', b + '/niche'),
      c.ebitda_musd !== null ? [', EBITDA ', V('q_addon', b + '/ebitda_musd', 'musd1')] : null),
      h('div', { style: 'margin:8px 0' }, V('q_addon', b + '/evidence')),
      h('div', { class: 'facts' }, h('div', { class: 'fk' }, 'Similarity'), h('div', null, V('q_addon', b + '/similarity', 'f3')),
        h('div', { class: 'fk' }, 'Shared neighbors'), h('div', null, V('q_addon', b + '/shared_count', 'int'), ' of ', V('q_addon', b + '/union_count', 'int'), ' combined'),
        h('div', { class: 'fk' }, 'Community'), h('div', null, COM[c.community] !== undefined ? V('q_addon', '/communities/' + COM[c.community] + '/label') : V('q_addon', b + '/community', 'int'))),
      h('h3', null, 'Shared customers and suppliers'),
      h('ul', { class: 'neighbors', id: 'addon-shared' }, c.shared_neighbors.map(function (s, k) {
        return h('li', null, V('q_addon', b + '/shared_neighbors/' + k + '/name'), h('span', { class: 'muted small' }, V('q_addon', b + '/shared_neighbors/' + k + '/relation')));
      }))]);
    var m = clear(P['addon-map']);
    add(m, [h('div', { class: 'legend' }, h('span', null, h('span', { class: 'sw', style: 'background:' + css('--line-strong') }), V('q_addon', '/platform/name')),
      h('span', null, h('span', { class: 'sw', style: 'background:' + css('--accent-soft') + ';border:1px solid ' + css('--accent') }), 'Candidate'),
      h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s3') }), 'Whitespace (new states)')),
      usMap(Q.platform.states, c.states, c.whitespace_states),
      h('div', { class: 'small', style: 'margin-top:6px' }, 'Platform states: ', Q.platform.states.map(function (s, k) { return [k ? ', ' : '', V('q_addon', '/platform/states/' + k)]; })),
      h('div', { class: 'small' }, 'Candidate states: ', c.states.map(function (s, k) { return [k ? ', ' : '', V('q_addon', b + '/states/' + k)]; })),
      h('div', { class: 'small', id: 'addon-whitespace' }, 'Whitespace: ', c.whitespace_states.length ? c.whitespace_states.map(function (s, k) { return [k ? ', ' : '', V('q_addon', b + '/whitespace_states/' + k)]; }) : 'none')]);
    ruleCard(P['addon-rule'], firstRule(['ADDON_SIMILARITY', 'JACCARD', 'ADDON_FIT']));
  }
  cy.on('tap', 'node', function (ev) { if (CAND[ev.target.id()] !== undefined) pickC(ev.target.id()); });
  E.api.addon = pickC;
  if (Q.candidates.length) pickC(Q.candidates[0].company_id);
}
function firstRule(ids) {
  for (var i = 0; i < ids.length; i++) if (RULE_IDX[ids[i]] !== undefined) return ids[i];
  return null;
}

/* ---------------- conflict check (Q-CONFLICT, Act 4) ---------------- */
function initConflict(sec) {
  var Q = X.q_conflict, fr = viewFrame(sec, 'q_conflict', true), C = Q.concentration;
  add(fr.main.firstChild, contrastTiles('Q-CONFLICT', 'sql_baseline', '/questions/Q-CONFLICT/kg_count', V('sql_baseline', '/questions/Q-CONFLICT/kg_label'),
    h('div', { class: 'tile' }, h('div', { class: 'k' }, 'Guideline'), h('div', { class: 'v' }, C.breach ? h('span', { style: 'color:' + css('--crit') }, 'Breach') : 'Within'),
      h('div', { class: 'd' }, V('q_conflict', '/concentration/subject_area'), ', headroom ', V('q_conflict', '/concentration/headroom_musd', 'musd1')))));
  var cont = h('div', { class: 'cy', id: 'cy-conflict' });
  add(fr.main, [h('div', { class: 'toolbar legend' },
    h('span', null, h('span', { class: 'sw line', style: 'background:' + css('--crit') }), 'Conflict'),
    h('span', null, h('span', { class: 'sw line', style: 'background:' + css('--s4') }), 'Informational'),
    h('span', null, h('span', { class: 'sw line', style: 'background:' + css('--edge') }), 'Context, not an exposure'),
    h('span', { class: 'small muted' }, 'Commercial links within ', V('q_conflict', '/max_distance', 'int'), ' hops of ', V('q_conflict', '/subject/name'))), cont]);
  /* concentration gauge: one bar per thesis area against the guideline */
  var scale = Math.max.apply(null, C.areas.map(function (a) { return Math.max(a.after_pct, a.before_pct); }).concat([C.guideline_pct])) * 1.12;
  function pct(v) { return (100 * v / scale) + '%'; }
  var gauge = h('div', { id: 'cf-gauge', style: 'padding:10px 20px 14px;background:' + css('--surface') + ';border-top:1px solid ' + css('--line') },
    h('div', { style: 'display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:4px' },
      h('span', { style: 'font-weight:620' }, V('q_conflict', '/concentration/fund_name'), ' exposure by thesis area, with ', V('q_conflict', '/subject/name'), ' at ', V('q_conflict', '/concentration/check_musd', 'musd1')),
      h('span', { class: 'small' }, 'Guideline ', V('q_conflict', '/concentration/guideline_pct', 'pct1'), ' of ', V('q_conflict', '/concentration/fund_size_musd', 'musd1'),
        C.breach ? [', over by ', V('q_conflict', '/concentration/over_by_musd', 'musd1')] : null, '. ', ruleLink('Rule', C.rule_id, null))),
    C.areas.map(function (a, i) {
      var b = '/concentration/areas/' + i;
      return h('div', { class: 'area-row', 'data-area': a.name },
        h('div', { class: 'area-name' }, V('q_conflict', b + '/name')),
        h('div', { class: 'area-track' },
          h('div', { class: 'g-before', style: 'width:' + pct(a.before_pct) }),
          a.after_pct > a.before_pct ? h('div', { class: 'g-add', style: 'left:' + pct(a.before_pct) + ';width:' + pct(a.after_pct - a.before_pct) }) : null,
          h('div', { class: 'g-cap', style: 'left:' + pct(C.guideline_pct) })),
        h('div', { class: 'area-val' }, V('q_conflict', b + '/before_pct', 'pct1'),
          a.after_pct !== a.before_pct ? [' to ', h('b', null, V('q_conflict', b + '/after_pct', 'pct1'))] : null,
          a.breach ? [' ', h('span', { class: 'chip crit' }, 'Over')] : null));
    }));
  add(fr.main, gauge);
  var P = panelSections(fr.panel, [['cf-hits', 'Exposures (current holdings)'], ['cf-ctx', 'Checked and set aside'], ['cf-rule', 'Rules'], ['cf-hold', 'Fund holdings'], ['cf-sql', 'SQL check']]);
  /* gauge rule link targets the panel rule card */
  gauge.querySelectorAll('.rulelink').forEach(function (el) { el.addEventListener('click', function () { ruleCard(P['cf-rule'], C.rule_id); }); });
  var cy = makeCy('conflict', cont, 'q_conflict', '/view_graph', function (n, i, d, cls) { d.size = (n.tags || []).indexOf('subject') >= 0 ? 34 : 20; cls.push('lbl'); });
  cy.batch(function () {
    Q.exposures.forEach(function (x) { x.edge_ids.forEach(function (eid) { cy.getElementById(eid).addClass(x.kind === 'conflict' ? 'conflict' : 'info'); }); });
    Q.context.forEach(function (x) { cy.getElementById(x.company_id).addClass('ctx'); x.edge_ids.forEach(function (eid) { cy.getElementById(eid).addClass('ctx'); }); });
  });
  var rl = h('div', { style: 'margin-bottom:8px' }, (Q.rule_ids || []).map(function (rid, k) {
    var ri = RULE_IDX[rid];
    return [k ? ' | ' : '', ruleLink(V('rules', '/rules/' + ri + '/name'), rid, null)];
  }));
  var rc = h('div');
  add(P['cf-rule'], [rl, rc]);
  rl.querySelectorAll('.rulelink').forEach(function (el, k) { el.addEventListener('click', function () { ruleCard(rc, Q.rule_ids[k]); }); });
  P['cf-rule'] = rc;
  ruleCard(rc, Q.exposures.length ? Q.exposures[0].rule_id : C.rule_id);
  function focus(ids) { var els = cy.collection(); ids.forEach(function (n) { els = els.union(cy.getElementById(n)); }); if (els.nonempty()) fitTo(cy, els, 1.4); }
  add(P['cf-hits'], Q.exposures.length ? Q.exposures.map(function (x, i) {
    var b = '/exposures/' + i;
    return h('div', { class: 'claim', 'data-exposure': x.company_id, style: 'cursor:pointer', onclick: function () { ruleCard(rc, x.rule_id); focus(x.path_node_ids); } },
      h('div', { style: 'display:flex;justify-content:space-between;gap:8px' }, h('span', { style: 'font-weight:600' }, V('q_conflict', b + '/name')),
        h('span', { class: 'chip ' + (x.kind === 'conflict' ? 'crit' : 'warn') }, V('q_conflict', b + '/kind_label'))),
      h('div', { class: 'small muted' }, V('q_conflict', b + '/fund_name'), ' since ', V('q_conflict', b + '/since'), ', distance ', V('q_conflict', b + '/distance', 'int')),
      h('div', { class: 'small' }, V('q_conflict', b + '/evidence')));
  }) : h('div', { class: 'empty' }, 'No current holding within reach.'));
  add(P['cf-ctx'], Q.context.length ? Q.context.map(function (x, i) {
    var b = '/context/' + i;
    return h('div', { class: 'claim', 'data-context': x.company_id, style: 'cursor:pointer', onclick: function () { focus([Q.subject.company_id, x.company_id]); } },
      h('div', { class: 'struck muted', style: 'font-weight:600' }, V('q_conflict', b + '/name')),
      h('div', { class: 'small' }, x.distance !== null ? ['Distance ', V('q_conflict', b + '/distance', 'int'), '. '] : null, V('q_conflict', b + '/reason')));
  }) : h('div', { class: 'empty' }, 'None.'));
  add(P['cf-hold'], h('table', { class: 't' }, h('thead', null, h('tr', null, h('th', null, 'Holding'), h('th', null, 'Thesis area'), h('th', { class: 'num' }, 'Equity'), h('th', { class: 'num' }, 'Of fund'))),
    h('tbody', null, C.holdings.map(function (x, i) {
      var b = '/concentration/holdings/' + i;
      return h('tr', null, h('td', null, V('q_conflict', b + '/name'), h('div', { class: 'small muted' }, V('q_conflict', b + '/niche'), ', since ', V('q_conflict', b + '/since'))),
        h('td', { class: 'muted' }, V('q_conflict', b + '/area')), h('td', { class: 'num' }, V('q_conflict', b + '/equity_musd', 'musd1')), h('td', { class: 'num' }, V('q_conflict', b + '/pct', 'pct1')));
    }))));
  add(P['cf-sql'], sqlTable('Q-CONFLICT'));
  E.api.conflict = function (id) { var x = Q.exposures.filter(function (e) { return e.company_id === id; })[0]; if (x) focus(x.path_node_ids); };
}

/* ---------------- deal flow (Q-FLOW) ---------------- */
function initFlow(sec) {
  var Q = X.q_flow, fr = viewFrame(sec, 'q_flow', true), II = idx(Q.intermediaries, 'org_id'), DI = idx(Q.deals, 'txn_id');
  var gapIdx = -1; Q.intermediaries.forEach(function (x, i) { if (x.is_gap && gapIdx < 0) gapIdx = i; });
  var P = panelSections(fr.panel, [['flow-detail', 'Intermediary'], ['flow-rule', 'Rule'], ['flow-sql', 'Deal-count league table']]);
  var sqlHead = P['flow-sql'].previousSibling; sqlHead.hidden = true; P['flow-sql'].hidden = true;
  var lgBtn = h('button', { class: 'btn', id: 'flow-league', 'aria-pressed': 'false', onclick: function () {
    var on = P['flow-sql'].hidden; P['flow-sql'].hidden = !on; sqlHead.hidden = !on; lgBtn.setAttribute('aria-pressed', String(on));
    if (on) sqlHead.scrollIntoView({ block: 'start' });
  } }, 'Compare with league table');
  add(fr.main.firstChild, contrastTiles('Q-FLOW', 'sql_baseline', '/questions/Q-FLOW/kg_count', V('sql_baseline', '/questions/Q-FLOW/kg_label'),
    gapIdx >= 0 ? h('div', { class: 'tile' }, h('div', { class: 'k' }, 'Biggest gap'), h('div', { class: 'v', style: 'font-size:16px;margin-top:4px' }, V('q_flow', '/intermediaries/' + gapIdx + '/name')),
      h('div', { class: 'd' }, 'Centrality rank ', V('q_flow', '/intermediaries/' + gapIdx + '/betweenness_rank', 'int'), ', ', V('q_flow', '/intermediaries/' + gapIdx + '/touchpoints_24m', 'int'), S(' touchpoints in 24 months'))) : null));
  var cont = h('div', { class: 'cy', id: 'cy-flow' });
  add(fr.main, [h('div', { class: 'toolbar legend' },
    h('span', null, h('span', { class: 'sw', style: 'background:' + css('--s7') }), 'Intermediary, sized by centrality'),
    h('span', null, h('span', { class: 'sw', style: 'background:' + css('--node') }), 'Sponsor or company'),
    h('span', null, h('span', { class: 'sw', style: 'background:transparent;border:3px solid ' + css('--crit') }), 'Coverage gap'),
    h('span', { class: 'small muted' }, S('Labels show touchpoints in the last 24 months. Deals from '), V('q_flow', '/window/start'), ' to ', V('q_flow', '/window/end'), '.'),
    h('span', { style: 'margin-left:auto' }, lgBtn)), cont]);
  var tbody = h('tbody');
  add(fr.main, h('div', { style: 'max-height:30%;overflow:auto;border-top:1px solid ' + css('--line') + ';background:' + css('--surface') },
    h('table', { class: 't', id: 'flow-table' }, h('thead', null, h('tr', null, h('th', { class: 'num' }, 'Rank'), h('th', null, 'Intermediary'),
      h('th', { class: 'num' }, 'Betweenness'), h('th', { class: 'num' }, 'PageRank'), h('th', { class: 'num' }, 'Deals in sectors'),
      h('th', { class: 'num' }, 'Touchpoints'), h('th', null, ''))), tbody)));
  ruleCard(P['flow-rule'], firstRule(['COVERAGE_GAP', 'DEAL_FLOW']));
  add(P['flow-sql'], [sqlTable('Q-FLOW', null, function (id) { if (II[id] !== undefined) pickI(id); }),
    h('div', { class: 'small muted', style: 'margin-top:6px' }, 'Top decile: centrality rank ', V('q_flow', '/thresholds/top_decile_cutoff_rank', 'int'),
      ' or better. Bottom quartile: ', V('q_flow', '/thresholds/q1_touchpoints', 'int'), ' touchpoints or fewer. Graph: ',
      V('q_flow', '/graph_stats/num_nodes', 'int'), ' organizations, ', V('q_flow', '/graph_stats/num_edges', 'int'), ' links.')]);
  var maxB = Math.max.apply(null, Q.intermediaries.map(function (x) { return x.betweenness; }).concat([1e-9]));
  var cy = makeCy('flow', cont, 'q_flow', '/view_graph', function (n, i, d, cls) {
    var ii = II[n.id];
    if (ii !== undefined) {
      var it = Q.intermediaries[ii];
      d.size = 14 + 46 * Math.sqrt(it.betweenness / maxB);
      d.label = lab([['q_flow', '/view_graph/nodes/' + i + '/label'], ' (', ['q_flow', '/intermediaries/' + ii + '/touchpoints_24m', 'int'], ')']);
      if (it.top_decile || it.is_gap || ii < 5) cls.push('lbl');
      if (it.is_gap) cls.push('coverage_gap');
    } else { d.size = n.type === 'sponsor' ? 12 : 8; if ((n.tags || []).indexOf('path_target') >= 0) { d.size = 16; cls.push('lbl'); } }
  });
  Q.intermediaries.forEach(function (it, i) {
    var b = '/intermediaries/' + i;
    add(tbody, h('tr', { class: 'clickable', 'data-org': it.org_id, onclick: function () { pickI(it.org_id); } },
      h('td', { class: 'num' }, V('q_flow', b + '/betweenness_rank', 'int')), h('td', null, V('q_flow', b + '/name')),
      h('td', { class: 'num' }, V('q_flow', b + '/betweenness', 'f1')), h('td', { class: 'num' }, V('q_flow', b + '/pagerank', 'f4')),
      h('td', { class: 'num' }, V('q_flow', b + '/deals_in_window', 'int')), h('td', { class: 'num' }, V('q_flow', b + '/touchpoints_24m', 'int')),
      h('td', null, it.is_gap ? h('span', { class: 'chip crit', 'data-badge': 'gap' }, 'Coverage gap') : (it.top_decile ? h('span', { class: 'chip' }, 'Top decile') : null))));
  });
  var pathTargets = {}; if (X.q_path) X.q_path.targets.forEach(function (t) { pathTargets[t.company_id] = true; });
  function pickI(oid) {
    var i = II[oid]; if (i === undefined) return;
    E.state.flow = oid;
    tbody.querySelectorAll('tr').forEach(function (tr) { tr.classList.toggle('sel', tr.getAttribute('data-org') === oid); });
    var it = Q.intermediaries[i], b = '/intermediaries/' + i, node = cy.getElementById(oid), on = node;
    it.deal_ids.forEach(function (tx) { var d = Q.deals[DI[tx]]; if (d) d.edge_ids.forEach(function (eid) { var e = cy.getElementById(eid); on = on.union(e).union(e.connectedNodes()); }); });
    var focusEdges = cy.collection();
    it.deal_ids.forEach(function (tx) { var d = Q.deals[DI[tx]]; if (d && pathTargets[d.target_id]) d.edge_ids.forEach(function (eid) { focusEdges = focusEdges.union(cy.getElementById(eid)); }); });
    cy.batch(function () { cy.elements().addClass('faded').removeClass('hl path-best'); on.removeClass('faded').addClass('hl'); focusEdges.addClass('path-best'); cy.elements().unselect(); node.select(); });
    fitTo(cy, on, 1.2);
    var d = clear(P['flow-detail']);
    add(d, [h('div', { class: 'title' }, V('q_flow', b + '/name')),
      it.is_gap ? h('div', { class: 'cold' }, h('div', { class: 'ct' }, 'Coverage gap'), h('div', null, V('q_flow', b + '/gap_reason'))) : null,
      h('div', { class: 'facts' },
        h('div', { class: 'fk' }, 'Centrality rank'), h('div', null, V('q_flow', b + '/betweenness_rank', 'int')),
        h('div', { class: 'fk' }, 'Betweenness'), h('div', null, V('q_flow', b + '/betweenness', 'f1')),
        h('div', { class: 'fk' }, 'PageRank'), h('div', null, V('q_flow', b + '/pagerank', 'f4')),
        h('div', { class: 'fk' }, 'Deals in our sectors'), h('div', null, V('q_flow', b + '/deals_in_window', 'int')),
        h('div', { class: 'fk' }, 'Deals, all sectors'), h('div', null, V('q_flow', b + '/deals_5y_all_sectors', 'int')),
        h('div', { class: 'fk' }, 'Our touchpoints'), h('div', null, V('q_flow', b + '/touchpoints_24m', 'int'))),
      h('h3', null, 'Deals in our sectors'),
      h('ul', { class: 'neighbors', id: 'flow-deals' }, it.deal_ids.map(function (tx) {
        var k = DI[tx], db = '/deals/' + k, dl = Q.deals[k];
        if (!dl) return null;
        return h('li', { 'data-txn': tx, style: 'flex-direction:column;cursor:default' },
          h('div', null, V('q_flow', db + '/target_name'), h('span', { class: 'muted small' }, ', ', V('q_flow', db + '/close_date'))),
          h('div', { class: 'small muted' }, V('q_flow', db + '/structure', 'words'), ', ', V('q_flow', db + '/seller_type', 'words'), dl.buyer_name ? [', buyer ', V('q_flow', db + '/buyer_name')] : null),
          pathTargets[dl.target_id] ? h('div', null, h('button', { class: 'btn link', 'data-goto-path': dl.target_id, onclick: function () { show('path', dl.target_id); } }, 'Open the warm-path view for ', V('q_flow', db + '/target_name'))) : null);
      }))]);
    ruleCard(P['flow-rule'], it.is_gap ? firstRule(['COVERAGE_GAP', 'DEAL_FLOW']) : firstRule(['DEAL_FLOW', 'COVERAGE_GAP']));
  }
  cy.on('tap', 'node', function (ev) { if (II[ev.target.id()] !== undefined) pickI(ev.target.id()); });
  E.api.flow = pickI;
  if (gapIdx >= 0) pickI(Q.intermediaries[gapIdx].org_id);
}

/* ---------------- boot ---------------- */
header();
var hash = location.hash.slice(1).split('/');
show(VIEW_DEFS[hash[0]] && SECTIONS[hash[0]] ? hash[0] : ORDER[0], hash[1] ? decodeURIComponent(hash[1]) : undefined);
var cy0 = E.cys[CURRENT];
function markReady() { requestAnimationFrame(function () { requestAnimationFrame(function () { E.readyMs = performance.now(); E.ready = true; document.documentElement.setAttribute('data-ready', '1'); }); }); }
if (cy0) cy0.ready(markReady); else markReady();
window.addEventListener('hashchange', function () { var p = location.hash.slice(1).split('/'); if (p[0] && p[0] !== CURRENT && SECTIONS[p[0]]) show(p[0], p[1] ? decodeURIComponent(p[1]) : undefined); });
})();
"""


if __name__ == "__main__":
    sys.exit(main())
