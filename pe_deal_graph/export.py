#!/usr/bin/env python3
"""Export the demo's numbers: live RAI queries -> exports/*.json (owner: R13 Exporter).

Usage (repo root, via the venv):
    make export                                   # writes exports/ (atomically: temp dir, then rename)
    .venv/bin/python -m pe_deal_graph.export [--out DIR] [--naive-sql-dir DIR] [--subgraph-target N]
    .venv/bin/python -m pe_deal_graph.export --check-contract [DIR]    # validate a dir; default exports/
    .venv/bin/python -m pe_deal_graph.export --compare DIR_A DIR_B     # byte diff ignoring meta.generated_at

What it does
- Calls every function named in pe_deal_graph.queries.HERO_QUERIES, in order, live through RAI. Their
  answer sets (who is Tier A, which targets, which intermediaries, which exposures) define the rows;
  the detail (components, hops, betweenness, exposures) is read live from the model's derived layer
  declared in pe_deal_graph/model/core.py section 3. Each exported row is cross-checked against the
  hero DataFrame it came from, so a drift between queries.py and the export fails the run.
- Nothing numeric is typed here. The only constants are the contract's own (schema_version, layout
  parameters, the 5-year deal-flow window length) and the score-scale constants, which are read from
  rules.py (TIER_A_MIN, TIER_B_MIN, READINESS_CAP, MAX_SCORE) and fall back, with a warning, to the
  values in QUESTIONS.md.
- Writes the files in the R15 contract (docstring of artifacts/build_explorer.py): meta, rules, graph,
  q_score, q_path, q_flow, q_conflict, sql_baseline. Q-ADDON is a backup and is not exported.

Determinism
- Every list is sorted by an explicit key, floats are rounded (raw values 6 dp, layout 2 dp), the layout
  is a numpy force layout seeded with a fixed RandomState, JSON keys keep insertion order and files are
  written with fixed formatting. The ONLY field that differs between two runs is meta.generated_at.
  To diff two runs: `python -m pe_deal_graph.export --compare exports_a exports_b`, or by hand
  `diff <(jq -S 'del(.generated_at)' a/meta.json) <(jq -S 'del(.generated_at)' b/meta.json)` for
  meta.json and plain `diff -r` for every other file.
- No timestamp is placed inside any value that R15/R16's numbers diff reads.

Layout note: networkx kamada_kawai_layout and spring_layout (above 500 nodes) both need scipy, which is
not in the venv. layout() below is a deterministic numpy Fruchterman-Reingold, declared in
graph.json as algorithm "numpy.fruchterman_reingold" with its seed.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import importlib.util
import inspect
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 42
LAYOUT_SCALE = 1000
SUBGRAPH_TARGET = 600  # R15 recommends 400-800 nodes; hard cap is 1,500
SUBGRAPH_MIN, SUBGRAPH_MAX, HARD_CAP = 400, 800, 1500
WINDOW_YEARS = 5  # deal-flow window length, rules.py's "last 5 years" (Intermediary.thesis_deals_5y)
MAX_PATHS_PER_DM = 3
QIDS = {"q_score": "Q-SCORE", "q_path": "Q-PATH", "q_flow": "Q-FLOW", "q_conflict": "Q-CONFLICT",
        "q_addon": "Q-ADDON"}
EM_DASH = "—"
# Shared engine: on a lock, a 503, a suspending engine or an empty hero frame, wait and retry.
RETRY_WAIT_S = 60
RETRY_MAX = 3
TRANSIENT = ("currently locked", "503", "upstream connect", "SUSPENDING", "CREATE_TRANSACTION",
             "engine is not ready", "timed out", "Too Many Requests", "429")


def _transient(exc: BaseException) -> bool:
    if type(exc).__name__ == "GraphOutputMissing":
        return True
    msg = f"{type(exc).__name__}: {exc}"
    return any(t.lower() in msg.lower() for t in TRANSIENT)


def with_retry(what: str, fn, empty=None, retry_on: tuple = ()):
    """Run fn(); on a transient engine error (or empty(result) true) wait RETRY_WAIT_S and retry."""
    for attempt in range(RETRY_MAX + 1):
        try:
            res = fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            if attempt < RETRY_MAX and (_transient(exc) or isinstance(exc, retry_on)):
                print(f"export: {what}: transient engine error ({str(exc).splitlines()[0][:160]}); "
                      f"retry {attempt + 1}/{RETRY_MAX} in {RETRY_WAIT_S}s", file=sys.stderr)
                time.sleep(RETRY_WAIT_S)
                continue
            raise
        if empty is not None and empty(res):
            if attempt < RETRY_MAX:
                print(f"export: {what}: empty result (engine contention?); retry {attempt + 1}/{RETRY_MAX} "
                      f"in {RETRY_WAIT_S}s", file=sys.stderr)
                time.sleep(RETRY_WAIT_S)
                continue
            raise ExportError(f"{what}: still empty after {RETRY_MAX} retries; the engine returned no rows")
        return res


class ExportError(Exception):
    pass


WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"export: WARNING: {msg}", file=sys.stderr)


# ======================================================================================================
# Rule ids this exporter references. Each must exist in rules.json (collected from rules.py/graphs.py).
# ======================================================================================================
RID = {
    "tenure": "K1_TENURE", "board": "K1_BOARD", "deal": "K2_DEAL", "crm": "K3_CRM",
    "commercial": "COMMERCIAL", "ownership": "OWNERSHIP", "employment": "EMPLOYMENT",
    "rejected": "SHARED_EMPLOYER_REJECT", "warm_path": "WARM_PATH", "closest": "CLOSEST_INTERMEDIARY",
    "flow": "DEAL_FLOW", "gap": "COVERAGE_GAP", "holding": "NORTHWIND_HOLDING",
    "exposure": "PORTFOLIO_EXPOSURE", "concentration": "CONCENTRATION", "conflict": "CONFLICT",
    "score": "SCORE", "fit": "FIT_THESIS",
}
KIND_TO_EDGE = {"K1": "tenure", "K2": "deal", "K3": "crm"}
EDGE_LABELS = {"tenure": "Tenure overlap", "board": "Board", "deal": "Deal", "commercial": "Commercial",
               "crm": "CRM", "ownership": "Ownership", "employment": "Current role"}
EDGE_RULE = {"tenure": "tenure", "board": "board", "deal": "deal", "commercial": "commercial", "crm": "crm",
             "ownership": "ownership", "employment": "employment"}
NODE_TYPES = [("company", "Company"), ("person", "Person"), ("sponsor", "Sponsor"),
              ("intermediary", "Intermediary"), ("fund", "Fund")]


# ======================================================================================================
# Small utilities
# ======================================================================================================
def clean(o):
    """JSON-safe, deterministic: numpy -> python, round floats, strip em dashes, no NaN."""
    try:
        import numpy as np
        import pandas as pd
    except Exception:  # pragma: no cover
        np = pd = None
    if o is None:
        return None
    if pd is not None and o is pd.NaT:
        return None
    if np is not None:
        if isinstance(o, np.generic):
            o = o.item()
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        return round(o, 6)
    if isinstance(o, str):
        return o.replace(EM_DASH, " - ").replace("  - ", " - ")
    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if pd is not None and hasattr(o, "isoformat"):
        return o.isoformat()[:10]
    return o


def dumps(o) -> str:
    return json.dumps(clean(o), indent=1, ensure_ascii=False, allow_nan=False) + "\n"


def iso(d) -> str | None:
    if d is None:
        return None
    try:
        import pandas as pd
        if pd.isna(d):
            return None
    except Exception:
        pass
    if isinstance(d, str):
        return d[:10]
    return d.strftime("%Y-%m-%d")


def to_date(s):
    return _dt.date.fromisoformat(s[:10]) if s else None


def years_between(a: str | None, b: str | None, as_of: str) -> float | None:
    if not a:
        return None
    return round(((to_date(b or as_of) - to_date(a)).days) / 365.25, 3)


def minus_years(d: _dt.date, n: int) -> _dt.date:
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - n, day=28)


def nn(v):
    """pandas missing -> None."""
    try:
        import pandas as pd
        return None if pd.isna(v) else v
    except Exception:
        return v


def i_or_none(v):
    v = nn(v)
    return None if v is None else int(v)


def f_or_none(v):
    v = nn(v)
    return None if v is None else float(v)


# ======================================================================================================
# Live access: model selects, one property at a time (a missing optional property never drops a row)
# ======================================================================================================
class Live:
    """Thin wrapper over the PyRel model. All data in the exports passes through here."""

    def __init__(self, core, rules_mod, graphs_mod):
        self.core = core
        self.model = core.model
        self.rules = rules_mod
        self.graphs = graphs_mod
        self._cache: dict = {}

    def C(self, name):
        try:
            return getattr(self.core, name)
        except AttributeError as exc:
            raise ExportError(f"model concept {name!r} is not declared in pe_deal_graph.model.core") from exc

    def df(self, *cols, where=None):
        q = self.model.where(*where) if where else self.model
        return with_retry("model read", lambda: q.select(*cols).to_df())

    def prop(self, concept, attr: str, via: str | None = None) -> dict:
        """id -> value for one property of an entity set. `via` follows an entity-valued property to its id/name."""
        key = (concept.__class__.__name__, getattr(concept, "_name", None) or str(concept), attr, via)
        if key in self._cache:
            return self._cache[key]
        expr = getattr(concept, attr)
        if via:
            expr = getattr(expr, via)
        d = self.df(concept.id.alias("id"), expr.alias("v"))
        out = {str(r.id): nn(r.v) for r in d.itertuples(index=False)}
        self._cache[key] = out
        return out

    def flag(self, concept, attr: str) -> set:
        d = self.df(concept.id.alias("id"), where=[getattr(concept, attr)()])
        if "id" not in d.columns:  # an empty result comes back without columns
            return set()
        return {str(x) for x in d["id"]}

    def ids(self, concept) -> list[str]:
        return sorted(str(x) for x in self.df(concept.id.alias("id"))["id"])

    def scalar(self, expr):
        d = self.df(expr.alias("v"))
        return nn(d["v"].iloc[0]) if len(d) else None


def count_of(live: Live, concept) -> int:
    from relationalai.semantics.std import aggregates as aggs
    d = live.df(aggs.count(concept).alias("n"))
    return int(d["n"].iloc[0]) if len(d) else 0


# ======================================================================================================
# Rule catalog (introspection of rules.py and graphs.py)
# ======================================================================================================
def collect_rules(rules_mod, graphs_mod) -> list[dict]:
    out: dict[str, dict] = {}
    for mod, kind in ((rules_mod, "rule"), (graphs_mod, "graph")):
        if mod is None:
            continue
        rel = f"pe_deal_graph/model/{mod.__name__.rsplit('.', 1)[-1]}.py"
        reg = getattr(mod, "RULES", None) or getattr(mod, "RULE_CATALOG", None)
        if reg:
            items = reg.items() if isinstance(reg, dict) else ((r.get("id"), r) for r in reg)
            for rid, meta in items:
                doc = meta.get("docstring") or meta.get("doc") or ""
                fn = meta.get("function") or meta.get("source") or rid
                out[rid] = {"id": rid, "name": meta.get("name") or rid.replace("_", " ").title(),
                            "kind": meta.get("kind") or kind, "docstring": doc,
                            "questions": list(meta.get("questions") or []),
                            "source": f"{rel}::{fn}" if "::" not in str(fn) else fn}
            continue
        for fname, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ != mod.__name__ or fname.startswith("_") or not fn.__doc__:
                continue
            rid = getattr(fn, "rule_id", fname.upper())
            out[rid] = {"id": rid, "name": getattr(fn, "rule_name", fname.replace("_", " ").capitalize()),
                        "kind": kind, "docstring": fn.__doc__, "questions": list(getattr(fn, "questions", [])),
                        "source": f"{rel}::{fname}"}
    rules = []
    for rid in sorted(out):
        r = out[rid]
        doc = " ".join(inspect.cleandoc(r["docstring"]).split())
        qs = r["questions"] or sorted(set(re.findall(r"Q-[A-Z]+", doc)))
        rules.append({"id": rid, "name": r["name"], "kind": r["kind"], "questions": qs,
                      "docstring": doc, "source": r["source"]})
    if not rules:
        raise ExportError("no rules found: rules.py/graphs.py expose neither RULES nor documented functions")
    return rules


def rule_id(rules_by_id: dict, key: str) -> str:
    rid = RID[key]
    if rid not in rules_by_id:
        raise ExportError(
            f"rule id {rid!r} (used for {key}) not found in rules.py/graphs.py; expose it in a RULES "
            f"registry (id, name, kind, questions, docstring) or adjust RID in pe_deal_graph/export.py")
    return rid


# ======================================================================================================
# Layout: deterministic numpy Fruchterman-Reingold (scipy-free)
# ======================================================================================================
def layout(node_ids: list[str], edges: list[tuple[str, str]], seed: int = SEED, scale: int = LAYOUT_SCALE,
           iterations: int = 120) -> dict[str, tuple[float, float]]:
    import numpy as np
    n = len(node_ids)
    if n == 0:
        return {}
    if n == 1:
        return {node_ids[0]: (0.0, 0.0)}
    idx = {k: i for i, k in enumerate(node_ids)}
    rng = np.random.RandomState(seed)
    pos = rng.uniform(-1, 1, size=(n, 2))
    A = np.zeros((n, n))
    for a, b in edges:
        if a in idx and b in idx and a != b:
            A[idx[a], idx[b]] = A[idx[b], idx[a]] = 1.0
    k = math.sqrt(1.0 / n)
    t = 0.1
    dt = t / (iterations + 1)
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.sqrt((delta ** 2).sum(-1))
        np.fill_diagonal(dist, 1.0)
        dist = np.maximum(dist, 0.01)
        disp = ((delta * (k * k / dist ** 2 - A * dist / k)[:, :, None]).sum(1))
        length = np.maximum(np.sqrt((disp ** 2).sum(-1)), 0.01)
        pos += disp * (t / length)[:, None]
        t -= dt
    pos -= pos.mean(0)
    m = np.abs(pos).max()
    pos = pos / (m if m > 0 else 1.0) * scale / 2
    return {k_: (round(float(pos[i, 0]), 2), round(float(pos[i, 1]), 2)) for k_, i in idx.items()}


def place(nodes: list[dict], edges: list[dict]) -> None:
    xy = layout([n["id"] for n in nodes], [(e["source"], e["target"]) for e in edges])
    for n in nodes:
        n["x"], n["y"] = xy[n["id"]]


# ======================================================================================================
# Contract validator (--check-contract). Independent of R15's builder; also run through it when present.
# ======================================================================================================
S_STR, S_INT, S_NUM, S_BOOL, S_ANY = "str", "int", "num", "bool", "any"


def nul(t):
    return ("null", t)


def enum(*vals):
    return ("enum", vals)


FACT = {"label": S_STR, "value": S_ANY, "fmt?": enum("raw", "int", "f1", "f2", "f3", "f4", "musd1", "pct1", "sint", "words"),
        "rule_id?": S_STR}
VG_NODE = {"id": S_STR, "label": S_STR, "type": S_STR, "x": S_NUM, "y": S_NUM, "tags": [S_STR], "community?": S_INT}
VG_EDGE = {"id": S_STR, "source": S_STR, "target": S_STR, "type": S_STR, "label?": S_STR}
VIEW_GRAPH = {"nodes": [VG_NODE], "edges": [VG_EDGE]}
COMP = {"id": S_STR, "points": S_INT, "evidence": S_STR}
HOP = {"edge_id": S_STR, "from_id": S_STR, "from_name": S_STR, "to_id": S_STR, "to_name": S_STR,
       "tie_type": enum("K1", "K2", "K3"), "tie_label?": nul(S_STR), "org_id": nul(S_STR), "org_name": nul(S_STR),
       "start_date": nul(S_STR), "end_date": nul(S_STR), "years": nul(S_NUM), "recency": nul(S_NUM),
       "strength": S_NUM, "evidence": S_STR, "rule_id": S_STR}
PATH = {"path_id": S_STR, "rank": S_INT, "length": S_INT, "strength": S_NUM, "node_ids": [S_STR], "hops": [HOP]}
DM = {"person_id": S_STR, "name": S_STR, "kind": enum("CEO", "OWNER_DESIGNEE"), "role_label": S_STR,
      "status": enum("warm", "cold"), "hops": nul(S_INT), "best_strength": nul(S_NUM), "summary": S_STR,
      "paths": [PATH]}
REJ = {"edge_id": nul(S_STR), "from_id": S_STR, "from_name": S_STR, "to_id": S_STR, "to_name": S_STR,
       "org_name": S_STR, "claim": S_STR, "reason": S_STR,
       "intervals": [{"person_id": S_STR, "name": S_STR, "start_date": S_STR, "end_date": nul(S_STR)}],
       "gap_days": nul(S_INT), "rule_id": S_STR}
TARGET = {"company_id": S_STR, "company_name": S_STR, "score_rank": S_INT, "owner_name": nul(S_STR),
          "status": enum("warm", "cold"), "summary": S_STR, "decision_makers": [DM], "rejected_claims": [REJ],
          "closest_intermediary": nul({"org_id": S_STR, "name": S_STR, "evidence": S_STR, "rule_id": S_STR}),
          "next_step": nul({"label": S_STR, "view": enum("flow"), "node_id": S_STR})}
SCHEMAS = {
    "meta": {"schema_version": enum("1"), "source": enum("RAI", "ORACLE", "FIXTURE"), "generated_at": S_STR,
             "as_of_date": S_STR, "customer_display_name": S_STR, "fund_name": S_STR,
             "relationalai_version": nul(S_STR), "engine": nul(S_STR),
             "counts?": {"pipeline_companies": S_INT, "market_companies": S_INT},
             "view_order?": [S_STR], "act_order?": [S_STR]},
    "rules": {"rules": [{"id": S_STR, "name": S_STR, "kind": enum("rule", "graph"), "questions": [S_STR],
                         "docstring": S_STR, "source": S_STR}]},
    "graph": {"layout": {"algorithm": S_STR, "seed": S_INT, "scale": S_NUM},
              "stats": {"num_nodes": S_INT, "num_edges": S_INT, "model_nodes": nul(S_INT), "model_edges": nul(S_INT)},
              "node_types": [{"id": S_STR, "label": S_STR}],
              "edge_types": [{"id": S_STR, "label": S_STR, "rule_id": S_STR, "count": S_INT}],
              "nodes": [{"id": S_STR, "label": S_STR, "type": S_STR, "x": S_NUM, "y": S_NUM, "tags": [S_STR],
                         "facts": [FACT]}],
              "edges": [{"id": S_STR, "source": S_STR, "target": S_STR, "type": S_STR, "evidence": S_STR,
                         "rule_id": nul(S_STR), "facts": [FACT]}]},
    "q_score": {"question_id": enum("Q-SCORE"), "business_question": S_STR,
                "tier_thresholds": {"A": S_INT, "B": S_INT}, "readiness_cap": S_INT, "max_score": S_INT,
                "components": [{"id": S_STR, "label": S_STR, "group": enum("fit", "readiness", "access"),
                                "max_points": S_INT, "rule_id": S_STR}],
                "summary": {"scored": S_INT, "tier_a": S_INT, "tier_b": S_INT, "tier_c": S_INT,
                            "tier_a_not_in_crm": S_INT, "ineligible": S_INT},
                "rows": [{"company_id": S_STR, "name": S_STR, "rank": S_INT, "score": S_INT,
                          "tier": enum("A", "B", "C"), "fit": S_INT, "readiness": S_INT, "access": S_INT,
                          "in_crm": S_BOOL, "pipeline_stage": nul(S_STR), "sector_path": [S_STR],
                          "ebitda_musd": S_NUM, "revenue_musd": S_NUM, "owner": nul(S_STR), "why": S_STR,
                          "components": [COMP]}],
                "ineligible": [{"company_id": S_STR, "name": S_STR, "reason": S_STR}],
                "finale": nul({"description": S_STR, "rows": [{
                    "company_id": S_STR, "name": S_STR, "rank": nul(S_INT), "score": S_INT,
                    "tier": enum("A", "B", "C", "Conflict"), "prev_rank": nul(S_INT), "prev_score": S_INT,
                    "prev_tier": S_STR, "delta": S_INT,
                    "conflict": nul({"reason": S_STR, "counterparty_id": S_STR, "counterparty_name": S_STR,
                                     "rule_id": S_STR}),
                    "added_components": [COMP]}]})},
    "q_path": {"question_id": enum("Q-PATH"), "business_question": S_STR, "max_hops": S_INT,
               "seeds": [{"person_id": S_STR, "name": S_STR, "title": S_STR}],
               "tie_types": [{"id": enum("K1", "K2", "K3"), "label": S_STR, "rule_id": S_STR}],
               "targets": [TARGET], "view_graph": VIEW_GRAPH},
    "q_flow": {"question_id": enum("Q-FLOW"), "business_question": S_STR, "window": {"start": S_STR, "end": S_STR},
               "graph_stats": {"num_nodes": S_INT, "num_edges": S_INT, "num_intermediaries": S_INT},
               "thresholds": {"top_decile_cutoff_rank": S_INT, "q1_touchpoints": S_INT},
               "intermediaries": [{"org_id": S_STR, "name": S_STR, "betweenness": S_NUM, "betweenness_rank": S_INT,
                                   "pagerank": S_NUM, "deals_in_window": S_INT, "deals_5y_all_sectors": S_INT,
                                   "touchpoints_24m": S_INT, "top_decile": S_BOOL, "is_gap": S_BOOL,
                                   "gap_reason": nul(S_STR), "deal_ids": [S_STR]}],
               "deals": [{"txn_id": S_STR, "close_date": S_STR, "target_id": S_STR, "target_name": S_STR,
                          "buyer_name": nul(S_STR), "seller_type": S_STR, "structure": S_STR, "deal_role": S_STR,
                          "advisor_ids": [S_STR], "advisor_names": [S_STR], "edge_ids": [S_STR]}],
               "view_graph": VIEW_GRAPH},
    "q_conflict": {"question_id": enum("Q-CONFLICT"), "business_question": S_STR,
                   "subject": {"company_id": S_STR, "name": S_STR, "thesis_area": S_STR}, "max_distance": S_INT,
                   "rule_ids": [S_STR],
                   "exposures": [{"company_id": S_STR, "name": S_STR, "fund_name": S_STR, "since": S_STR,
                                  "distance": S_INT, "kind": enum("conflict", "same_fund", "informational"),
                                  "kind_label": S_STR, "evidence": S_STR, "path_node_ids": [S_STR],
                                  "edge_ids": [S_STR], "rule_id": S_STR}],
                   "context": [{"company_id": S_STR, "name": S_STR, "distance": nul(S_INT), "reason": S_STR,
                                "edge_ids": [S_STR]}],
                   "concentration": {"fund_name": S_STR, "fund_size_musd": S_NUM, "guideline_pct": S_NUM,
                                     "check_musd": S_NUM, "subject_area": S_STR, "breach": S_BOOL,
                                     "headroom_musd": S_NUM, "over_by_musd": S_NUM, "rule_id": S_STR,
                                     "areas": [{"name": S_STR, "before_musd": S_NUM, "before_pct": S_NUM,
                                                "after_musd": S_NUM, "after_pct": S_NUM,
                                                "is_subject_area": S_BOOL, "breach": S_BOOL}],
                                     "holdings": [{"company_id": S_STR, "name": S_STR, "area": S_STR,
                                                   "niche": S_STR, "since": S_STR, "equity_musd": S_NUM,
                                                   "pct": S_NUM}]},
                   "view_graph": VIEW_GRAPH},
    "sql_baseline": {"questions": {"*": {
        "sql_file": S_STR, "description": S_STR, "metric_label": S_STR, "row_count": S_INT, "kg_count": S_INT,
        "kg_label": S_STR,
        "rows": [{"entity_id": S_STR, "name": S_STR, "rank": S_INT, "metric": S_ANY,
                  "verdict": enum("agrees", "decoy", "other"), "note": nul(S_STR)}],
        "missed": [{"entity_id": S_STR, "name": S_STR, "note": S_STR}]}}},
}
REQUIRED_FILES = ("meta", "rules", "graph", "q_score", "q_path", "q_flow", "sql_baseline")
OPTIONAL_FILES = ("q_conflict",)


def _tname(v):
    return type(v).__name__


def _check(v, spec, where, errs):
    if spec == S_ANY:
        if isinstance(v, (dict, list)):
            errs.append(f"{where}: expected a scalar, got {_tname(v)}")
        return
    if isinstance(spec, str):
        ok = {"str": isinstance(v, str), "int": isinstance(v, int) and not isinstance(v, bool),
              "num": isinstance(v, (int, float)) and not isinstance(v, bool),
              "bool": isinstance(v, bool)}[spec]
        if not ok:
            errs.append(f"{where}: expected {spec}, got {_tname(v)} {str(v)[:30]!r}")
        return
    if isinstance(spec, tuple):
        if spec[0] == "null":
            if v is not None:
                _check(v, spec[1], where, errs)
        elif spec[0] == "enum":
            if v not in spec[1]:
                errs.append(f"{where}: expected one of {list(spec[1])}, got {v!r}")
        return
    if isinstance(spec, list):
        if not isinstance(v, list):
            errs.append(f"{where}: expected list, got {_tname(v)}")
            return
        for i, x in enumerate(v):
            _check(x, spec[0], f"{where}[{i}]", errs)
        return
    if isinstance(spec, dict):
        if not isinstance(v, dict):
            errs.append(f"{where}: expected object, got {_tname(v)}")
            return
        if list(spec) == ["*"]:
            for k, x in v.items():
                _check(x, spec["*"], f"{where}.{k}", errs)
            return
        for k, sub in spec.items():
            opt = k.endswith("?")
            key = k.rstrip("?")
            if key not in v:
                if not opt:
                    errs.append(f"{where}: missing key {key!r}")
                continue
            _check(v[key], sub, f"{where}.{key}", errs)
        for k in v:
            if k not in {s.rstrip("?") for s in spec}:
                errs.append(f"{where}: unexpected key {k!r}")


def _strings(o, path, out):
    if isinstance(o, str):
        out.append((path, o))
    elif isinstance(o, dict):
        for k, v in o.items():
            _strings(v, f"{path}.{k}", out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _strings(v, f"{path}[{i}]", out)


def _view_graph_ids(vg, where, errs):
    nids = [n["id"] for n in vg.get("nodes", [])]
    eids = [e["id"] for e in vg.get("edges", [])]
    if len(set(nids)) != len(nids):
        errs.append(f"{where}: duplicate node ids")
    if len(set(eids)) != len(eids):
        errs.append(f"{where}: duplicate edge ids")
    for e in vg.get("edges", []):
        for end in ("source", "target"):
            if e[end] not in set(nids):
                errs.append(f"{where}: edge {e['id']} {end} {e[end]!r} is not a node")
    return set(nids), set(eids)


def check_contract(d: Path) -> list[str]:
    """Return a list of violations of the R15 exports contract for the JSON files in directory d."""
    errs: list[str] = []
    if not d.is_dir():
        return [f"{d}: not a directory"]
    docs: dict = {}
    for name in REQUIRED_FILES + OPTIONAL_FILES:
        p = d / f"{name}.json"
        if not p.exists():
            if name in REQUIRED_FILES:
                errs.append(f"{name}.json: missing")
            continue
        try:
            docs[name] = json.loads(p.read_text(encoding="utf-8"),
                                    parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        except ValueError as exc:
            errs.append(f"{name}.json: invalid JSON or NaN/Infinity ({exc})")
            continue
        _check(docs[name], SCHEMAS[name], name, errs)
    if errs:
        return errs
    strs: list = []
    for name, doc in docs.items():
        _strings(doc, name, strs)
    for path, s in strs:
        if EM_DASH in s:
            errs.append(f"{path}: contains an em dash")
    rule_ids = {r["id"] for r in docs["rules"]["rules"]}

    def rid(r, where, nullable=False):
        if r is None and nullable:
            return
        if r not in rule_ids:
            errs.append(f"{where}: rule_id {r!r} not in rules.json")

    # meta
    meta = docs["meta"]
    for vo in meta.get("view_order", []):
        if vo not in ("overview", "score", "path", "flow", "conflict", "addon"):
            errs.append(f"meta.view_order: unknown id {vo!r}")
    if "q_conflict" in meta.get("view_order", []) and "q_conflict" not in docs:
        errs.append("meta.view_order lists conflict but q_conflict.json is missing")
    # graph
    g = docs["graph"]
    ntypes = {t["id"] for t in g["node_types"]}
    etypes = {t["id"]: t for t in g["edge_types"]}
    for need in ("tenure", "board", "deal", "commercial", "crm"):
        if need not in etypes:
            errs.append(f"graph.edge_types: missing {need!r}")
    for t in g["edge_types"]:
        rid(t["rule_id"], f"graph.edge_types[{t['id']}]")
    nids = [n["id"] for n in g["nodes"]]
    if len(nids) != len(set(nids)):
        errs.append("graph.nodes: duplicate ids")
    if len(nids) > HARD_CAP:
        errs.append(f"graph.nodes: {len(nids)} exceeds {HARD_CAP}")
    if g["stats"]["num_nodes"] != len(nids):
        errs.append("graph.stats.num_nodes != len(nodes)")
    if g["stats"]["num_edges"] != len(g["edges"]):
        errs.append("graph.stats.num_edges != len(edges)")
    nset = set(nids)
    for n in g["nodes"]:
        if n["type"] not in ntypes:
            errs.append(f"graph.nodes[{n['id']}]: undeclared type {n['type']!r}")
        for f in n["facts"]:
            rid(f.get("rule_id"), f"graph.nodes[{n['id']}].facts", True)
    counts: dict = {}
    eset = set()
    for e in g["edges"]:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        eset.add(e["id"])
        if e["type"] not in etypes:
            errs.append(f"graph.edges[{e['id']}]: undeclared type {e['type']!r}")
        for end in ("source", "target"):
            if e[end] not in nset:
                errs.append(f"graph.edges[{e['id']}]: {end} {e[end]!r} is not a node")
        rid(e["rule_id"], f"graph.edges[{e['id']}]", True)
    if len(eset) != len(g["edges"]):
        errs.append("graph.edges: duplicate ids")
    for t in g["edge_types"]:
        if counts.get(t["id"], 0) != t["count"]:
            errs.append(f"graph.edge_types[{t['id']}].count {t['count']} != actual {counts.get(t['id'], 0)}")
    # q_score
    qs = docs["q_score"]
    comp_ids = {c["id"] for c in qs["components"]}
    for c in qs["components"]:
        rid(c["rule_id"], f"q_score.components[{c['id']}]")
    ranks = [r["rank"] for r in qs["rows"]]
    if ranks != sorted(ranks):
        errs.append("q_score.rows: not ordered by rank")
    for r in qs["rows"]:
        if {c["id"] for c in r["components"]} != comp_ids:
            errs.append(f"q_score.rows[{r['company_id']}].components: must have one entry per component")
        if r["fit"] + r["readiness"] + r["access"] != r["score"]:
            errs.append(f"q_score.rows[{r['company_id']}]: fit+readiness+access != score")
        if r["company_id"] not in nset:
            errs.append(f"q_score.rows[{r['company_id']}]: company not in graph.json (hero entity)")
    for t, key in (("A", "tier_a"), ("B", "tier_b")):
        have = sum(1 for r in qs["rows"] if r["tier"] == t)
        if have != qs["summary"][key]:
            errs.append(f"q_score: rows with tier {t} ({have}) != summary.{key} ({qs['summary'][key]})")
    if qs["finale"]:
        for r in qs["finale"]["rows"]:
            if r["conflict"]:
                rid(r["conflict"]["rule_id"], "q_score.finale.conflict")
            for c in r["added_components"]:
                if c["id"] not in comp_ids and not c["id"].startswith(("A_", "R_", "F_")):
                    errs.append(f"q_score.finale.rows[{r['company_id']}].added_components: unknown id {c['id']!r}")
    # q_path
    qp = docs["q_path"]
    vn, ve = _view_graph_ids(qp["view_graph"], "q_path.view_graph", errs)
    for t in qp["tie_types"]:
        rid(t["rule_id"], "q_path.tie_types")
    for tg in qp["targets"]:
        w = f"q_path.targets[{tg['company_id']}]"
        warm = any(dm["status"] == "warm" for dm in tg["decision_makers"])
        if (tg["status"] == "warm") != warm:
            errs.append(f"{w}: status must be warm iff any decision-maker has a path")
        if tg["decision_makers"] and tg["decision_makers"][0]["kind"] != "CEO":
            errs.append(f"{w}: CEO must be the first decision-maker")
        for dm in tg["decision_makers"]:
            if (dm["status"] == "warm") != bool(dm["paths"]):
                errs.append(f"{w}.{dm['person_id']}: status disagrees with paths")
            for p in dm["paths"]:
                for h in p["hops"]:
                    rid(h["rule_id"], f"{w}.hop")
                    if h["edge_id"] not in ve:
                        errs.append(f"{w}: hop edge_id {h['edge_id']!r} not in q_path.view_graph.edges")
        for rc in tg["rejected_claims"]:
            rid(rc["rule_id"], f"{w}.rejected")
            if rc["edge_id"] is not None and rc["edge_id"] not in ve:
                errs.append(f"{w}: rejected edge_id {rc['edge_id']!r} not in view_graph")
        if tg["closest_intermediary"]:
            rid(tg["closest_intermediary"]["rule_id"], f"{w}.closest_intermediary")
    # q_flow
    qf = docs["q_flow"]
    fvn, fve = _view_graph_ids(qf["view_graph"], "q_flow.view_graph", errs)
    ranks = [i["betweenness_rank"] for i in qf["intermediaries"]]
    if ranks != sorted(ranks):
        errs.append("q_flow.intermediaries: not ordered by betweenness_rank")
    txns = {d_["txn_id"] for d_ in qf["deals"]}
    for i in qf["intermediaries"]:
        for t in i["deal_ids"]:
            if t not in txns:
                errs.append(f"q_flow.intermediaries[{i['org_id']}].deal_ids: unknown txn {t!r}")
    for d_ in qf["deals"]:
        for e in d_["edge_ids"]:
            if e not in fve:
                errs.append(f"q_flow.deals[{d_['txn_id']}]: edge_id {e!r} not in view_graph")
    # q_conflict
    if "q_conflict" in docs:
        qc = docs["q_conflict"]
        cvn, cve = _view_graph_ids(qc["view_graph"], "q_conflict.view_graph", errs)
        for r in qc["rule_ids"]:
            rid(r, "q_conflict.rule_ids")
        rid(qc["concentration"]["rule_id"], "q_conflict.concentration")
        for x in qc["exposures"]:
            rid(x["rule_id"], f"q_conflict.exposures[{x['company_id']}]")
            for e in x["edge_ids"]:
                if e not in cve:
                    errs.append(f"q_conflict.exposures[{x['company_id']}]: edge_id {e!r} not in view_graph")
        for x in qc["context"]:
            for e in x["edge_ids"]:
                if e not in cve:
                    errs.append(f"q_conflict.context[{x['company_id']}]: edge_id {e!r} not in view_graph")
    # sql_baseline
    for qid, q in docs["sql_baseline"]["questions"].items():
        if qid not in ("Q-SCORE", "Q-PATH", "Q-FLOW", "Q-ADDON", "Q-CONFLICT"):
            errs.append(f"sql_baseline.questions: unknown question {qid!r}")
        if len(q["rows"]) > 15:
            errs.append(f"sql_baseline.{qid}.rows: more than 15 rows")
    for qid in meta.get("act_order", []):
        if qid not in docs["sql_baseline"]["questions"] and qid != "Q-ADDON":
            errs.append(f"meta.act_order: {qid} has no sql_baseline entry")
    return errs


def run_check_contract(d: Path) -> int:
    errs = check_contract(d)
    # also run R15's builder validation when available (the authoritative copy of the contract)
    be = ROOT / "artifacts" / "build_explorer.py"
    if be.exists() and not errs:
        try:
            spec = importlib.util.spec_from_file_location("_r15_build_explorer", be)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["_r15_build_explorer"] = mod
            spec.loader.exec_module(mod)
            data = mod.load_exports(d)
            errs += [f"R15 builder: {e}" for e in mod.validate(data)]
        except Exception as exc:  # builder may raise ContractError with the full list
            errs.append(f"R15 builder: {exc}")
    if errs:
        print(f"export --check-contract: {len(errs)} violation(s) in {d}", file=sys.stderr)
        for e in errs[:200]:
            print(f"  - {e}", file=sys.stderr)
        return 2
    print(f"export --check-contract: OK ({d} satisfies the R15 contract)")
    return 0


def run_compare(a: Path, b: Path) -> int:
    """Byte-compare two export dirs, ignoring only meta.generated_at."""
    names = sorted({p.name for p in a.glob("*.json")} | {p.name for p in b.glob("*.json")})
    bad = []
    for n in names:
        pa, pb = a / n, b / n
        if not pa.exists() or not pb.exists():
            bad.append(f"{n}: present in only one directory")
            continue
        ta, tb = pa.read_text(encoding="utf-8"), pb.read_text(encoding="utf-8")
        if n == "meta.json":
            ta = re.sub(r'"generated_at": "[^"]*"', '"generated_at": "-"', ta)
            tb = re.sub(r'"generated_at": "[^"]*"', '"generated_at": "-"', tb)
        if ta != tb:
            bad.append(f"{n}: differs")
    if bad:
        print("export --compare: DIFFERENT\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    print(f"export --compare: IDENTICAL ({len(names)} files, meta.generated_at ignored)")
    return 0


# ======================================================================================================
# Hero queries
# ======================================================================================================
def hero_frames(queries_mod) -> dict:
    """Call every function in HERO_QUERIES, in order, live. name -> DataFrame or dict of DataFrames."""
    order = tuple(getattr(queries_mod, "HERO_QUERIES", ()))
    if not order:
        raise ExportError("pe_deal_graph.queries.HERO_QUERIES is missing or empty")
    out = {}
    for name in order:
        fn = getattr(queries_mod, name, None)
        if not callable(fn):
            raise ExportError(f"HERO_QUERIES names {name!r} but queries.{name}() does not exist")
        t0 = time.time()
        # a KeyError on a missing column is how an empty engine frame surfaces inside q_score/finale_rescore
        out[name] = with_retry(f"queries.{name}()", fn, empty=_hero_empty, retry_on=(KeyError,))
        print(f"export: ran queries.{name}() in {time.time() - t0:.1f}s", file=sys.stderr)
    return out


def _hero_empty(res) -> bool:
    """Every hero answer has rows; an empty frame (or a dict of only empty frames) means contention."""
    fs = _frames(res)
    return not fs or all(getattr(f, "empty", True) for f in fs)


def _frames(res) -> list:
    return list(res.values()) if isinstance(res, dict) else [res]


def hero_names(res) -> set[str]:
    names: set[str] = set()
    for f in _frames(res):
        for col in ("name", "target", "company", "intermediary", "candidate"):
            if col in getattr(f, "columns", ()):
                names |= {str(x) for x in f[col].dropna()}
    return names


def crosscheck(label: str, res, exported_names: set[str]) -> None:
    """Every entity the hero query returned must be in the export (the export may add context rows)."""
    missing = sorted(hero_names(res) - exported_names)
    if missing:
        raise ExportError(f"{label}: hero query returned {missing[:5]} which the export does not contain; "
                          f"export and queries.py disagree")


def hero_score_check(res, rows: list[dict]) -> None:
    by = {r["name"]: r for r in rows}
    for f in _frames(res):
        if "name" in f.columns and "score" in f.columns:
            for r in f.itertuples(index=False):
                ex = by.get(str(r.name))
                if ex is not None and nn(r.score) is not None and int(r.score) != ex["score"]:
                    raise ExportError(f"Q-SCORE: {r.name} scores {int(r.score)} in q_score() but {ex['score']} "
                                      f"in the export")


# ======================================================================================================
# Data access shared by the builders
# ======================================================================================================
class Ctx:
    """Everything the builders share: live handle, id->name maps, as-of date, rule lookup."""

    def __init__(self, live: Live, rules: list[dict]):
        L = live
        self.live = live
        self.rules = rules
        self.rules_by_id = {r["id"]: r for r in rules}
        self.as_of = getattr(L.core, "AS_OF_ISO", "2026-10-01")
        self.org_name = L.prop(L.C("Organization"), "name")
        self.person_name = L.prop(L.C("Person"), "name")
        self.company_name = L.prop(L.C("Company"), "name")
        self.sponsor_ids = set(L.ids(L.C("Sponsor")))
        self.interm_ids = set(L.ids(L.C("Intermediary")))
        self.company_ids = set(self.company_name)
        self.fund_name = L.prop(L.C("Fund"), "name")
        self.seed_ids = set(L.ids(L.C("OurSeed")))
        self.sector_name = L.prop(L.C("Sector"), "name")
        self.sector_parent = L.prop(L.C("Sector"), "parent", via="id")

    def rid(self, key: str) -> str:
        return rule_id(self.rules_by_id, key)

    def name_of(self, i: str) -> str:
        return self.person_name.get(i) or self.org_name.get(i) or self.fund_name.get(i) or i

    def sector_path(self, sector_id: str | None) -> list[str]:
        out, cur, guard = [], sector_id, 0
        while cur and guard < 6:
            out.append(self.sector_name.get(cur, cur))
            cur = nn(self.sector_parent.get(cur))
            guard += 1
        return list(reversed(out))

    def node_type(self, i: str) -> str:
        if i in self.person_name:
            return "person"
        if i in self.company_ids:
            return "company"
        if i in self.sponsor_ids:
            return "sponsor"
        if i in self.interm_ids:
            return "intermediary"
        if i in self.fund_name:
            return "fund"
        return "company"


def _by_id(live: Live, concept, attrs: dict) -> dict:
    """id -> {key: value} for several properties. attrs: key -> (attr, via)."""
    out: dict = {}
    for key, (attr, via) in attrs.items():
        for i, v in live.prop(concept, attr, via).items():
            out.setdefault(i, {})[key] = v
    return out


# ======================================================================================================
# Builders
# ======================================================================================================
def score_constants(live: Live) -> dict:
    r = live.rules
    def pick(names, default, label):
        for n in names:
            v = getattr(r, n, None)
            if isinstance(v, (int, float)):
                return int(v)
        raise ExportError(f"rules.py must expose one of {names} ({label})")
    return {"A": pick(("TIER_A_MIN", "TIER_A"), 70, "tier A threshold"),
            "B": pick(("TIER_B_MIN", "TIER_B"), 50, "tier B threshold"),
            "cap": pick(("READINESS_CAP",), 50, "readiness cap"),
            "max": pick(("MAX_SCORE",), 100, "max score")}


def build_q_score(cx: Ctx, hero) -> tuple[dict, dict]:
    L = cx.live
    ET, SC, Co = L.C("EligibleTarget"), L.C("ScoreComponent"), L.C("Company")
    info = _by_id(L, ET, {"name": ("name", None), "score": ("score", None), "tier": ("tier", None),
                          "fit": ("fit_points", None), "readiness": ("readiness_points", None),
                          "access": ("access_points", None), "rank": ("score_rank", None),
                          "why": ("why", None), "ebitda": ("ebitda_musd", None), "revenue": ("revenue_musd", None),
                          "sector": ("sector", "id"), "fscore": ("finale_score", None),
                          "ftier": ("finale_tier", None), "frank": ("finale_rank", None),
                          "fwhy": ("finale_why", None), "wpp": ("warm_path_points", None)})
    in_crm = L.flag(Co, "in_crm")
    conflict = L.flag(Co, "has_conflict")
    conflict_ev = L.prop(Co, "conflict_evidence")
    inelig = L.prop(Co, "ineligible_reason")
    # pipeline stage and owner
    PE = L.C("PipelineEntry")
    d = L.df(PE.company.id.alias("c"), PE.stage.alias("stage"))
    stage = {str(r.c): nn(r.stage) for r in d.itertuples(index=False)}
    d = L.df(PE.company.id.alias("c"), PE.owner.name.alias("owner"))
    owner = {str(r.c): nn(r.owner) for r in d.itertuples(index=False)}
    # components
    d = L.df(SC.company.id.alias("c"), SC.code.alias("code"), SC.points.alias("points"),
             SC.pillar.alias("pillar"), SC.evidence.alias("ev"))
    comps: dict = {}
    catalog: dict = {}
    for r in d.itertuples(index=False):
        comps.setdefault(str(r.c), {})[str(r.code)] = (int(r.points), str(r.ev))
        catalog.setdefault(str(r.code), {"pillar": str(r.pillar).lower(), "max": 0})
        catalog[str(r.code)]["max"] = max(catalog[str(r.code)]["max"], int(r.points))
    declared = getattr(L.rules, "SCORE_COMPONENTS", None)
    if not declared:
        raise ExportError("rules.py must expose SCORE_COMPONENTS")
    components = []
    for code, m in declared.items():
        components.append({"id": code, "label": m.get("label", code), "group": str(m.get("group")).lower(),
                           "max_points": int(m["max_points"]), "rule_id": m.get("rule_id", code)})
    comp_ids = [c["id"] for c in components]
    for c in components:
        if c["rule_id"] not in cx.rules_by_id:
            c["rule_id"] = cx.rid("score")
    sc = score_constants(L)
    ids = sorted(info, key=lambda i: (info[i].get("rank") is None, info[i].get("rank") or 0, i))
    tiers = {i: info[i].get("tier") for i in ids}
    rows = []
    for i in ids:
        x = info[i]
        if x.get("tier") not in ("A", "B"):
            continue
        rows.append({
            "company_id": i, "name": x["name"], "rank": int(x["rank"]), "score": int(x["score"]),
            "tier": x["tier"], "fit": int(x.get("fit") or 0), "readiness": int(x.get("readiness") or 0),
            "access": int(x.get("access") or 0), "in_crm": i in in_crm, "pipeline_stage": stage.get(i),
            "sector_path": cx.sector_path(x.get("sector")), "ebitda_musd": float(x.get("ebitda") or 0),
            "revenue_musd": float(x.get("revenue") or 0), "owner": owner.get(i), "why": x.get("why") or "",
            "components": [{"id": c, "points": comps.get(i, {}).get(c, (0, ""))[0],
                            "evidence": comps.get(i, {}).get(c, (0, "Not awarded: no qualifying evidence on record."))[1]
                            or "Not awarded: no qualifying evidence on record."} for c in comp_ids]})
    hero_score_check(hero.get("q_score"), rows)
    crosscheck("Q-SCORE", hero.get("q_score"), {r["name"] for r in rows})
    summary = {"scored": len(info), "tier_a": sum(1 for t in tiers.values() if t == "A"),
               "tier_b": sum(1 for t in tiers.values() if t == "B"),
               "tier_c": sum(1 for t in tiers.values() if t == "C"),
               "tier_a_not_in_crm": sum(1 for i in ids if tiers[i] == "A" and i not in in_crm),
               "ineligible": len(inelig)}
    ineligible = [{"company_id": i, "name": cx.company_name.get(i, i), "reason": str(r)}
                  for i, r in sorted(inelig.items(), key=lambda kv: (cx.company_name.get(kv[0], ""), kv[0]))
                  if isinstance(r, str) and r][:12]
    # finale: companies Tier A before or after, plus conflicted ones
    finale = None
    if "finale_rescore" in hero:
        frows = []
        for i in ids:
            x = info[i]
            if x.get("tier") != "A" and x.get("ftier") != "A" and i not in conflict:
                continue
            is_conf = i in conflict
            if x.get("fscore") is None:
                continue
            added = []
            if int(x.get("wpp") or 0) > 0:
                added.append({"id": "A_WARM_PATH", "points": int(x["wpp"]), "evidence": x.get("fwhy") or ""})
            cf = None
            if is_conf:
                cp = _conflict_counterparty(cx, i)
                cf = {"reason": conflict_ev.get(i) or "Cross-fund conflict", "counterparty_id": cp[0],
                      "counterparty_name": cp[1], "rule_id": cx.rid("conflict")}
            frows.append({"company_id": i, "name": x["name"],
                          "rank": None if is_conf else i_or_none(x.get("frank")), "score": int(x["fscore"]),
                          "tier": "Conflict" if is_conf else x.get("ftier"), "prev_rank": i_or_none(x.get("rank")),
                          "prev_score": int(x["score"]), "prev_tier": x["tier"],
                          "delta": int(x["fscore"]) - int(x["score"]), "conflict": cf, "added_components": added})
        frows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"]))
        finale = {"description": "Warm-path access points added and cross-fund conflicts flagged: "
                                 "hold until cross-fund clearance.", "rows": frows}
        crosscheck("Finale", hero["finale_rescore"], {r["name"] for r in frows})
    doc = {"question_id": "Q-SCORE", "business_question": _doc(hero_fn=None, default=(
        "Which companies fit the Fund IV thesis and look ready to transact in the next 12 months?")),
        "tier_thresholds": {"A": sc["A"], "B": sc["B"]}, "readiness_cap": sc["cap"], "max_score": sc["max"],
        "components": components, "summary": summary, "rows": rows, "ineligible": ineligible, "finale": finale}
    return doc, {"tier_a_ids": [r["company_id"] for r in rows if r["tier"] == "A"], "info": info,
                 "not_in_crm": {r["company_id"] for r in rows if r["tier"] == "A" and not r["in_crm"]},
                 "rows": rows, "stage": stage}


def _doc(hero_fn, default: str) -> str:
    if hero_fn is not None and getattr(hero_fn, "__doc__", None):
        return inspect.cleandoc(hero_fn.__doc__).splitlines()[0]
    return default


def _conflict_counterparty(cx: Ctx, company_id: str) -> tuple[str | None, str | None]:
    L = cx.live
    CL = cx.live.rules.ConflictLink  # (company, held): the held company comes first by name, then id
    if not hasattr(cx, "_cl"):
        d = L.df(CL.company.id.alias("c"), CL.held.id.alias("h"), CL.held.name.alias("n"))
        cx._cl = {}
        for r in sorted(d.itertuples(index=False), key=lambda r: (str(r.n), str(r.h))):
            cx._cl.setdefault(str(r.c), (str(r.h), str(r.n)))
    return cx._cl.get(company_id, (None, None))


# ---------------------------------------------------------------------------------------------- Q-PATH
def person_roles(cx: Ctx) -> list[dict]:
    L = cx.live
    R = L.C("Role")
    cols = {"role": R.id, "p": R.person.id, "o": R.organization.id, "t": R.role_type, "title": R.title,
            "s": R.start_date}
    d = L.df(*[v.alias(k) for k, v in cols.items()])
    ends = {str(r.i): iso(nn(r.e)) for r in L.df(R.id.alias("i"), R.effective_end_date.alias("e")).itertuples(index=False)}
    raw_ends = {str(r.i): iso(nn(r.e)) for r in L.df(R.id.alias("i"), R.end_date.alias("e")).itertuples(index=False)}
    out = []
    for r in d.itertuples(index=False):
        out.append({"role": str(r.role), "person": str(r.p), "org": str(r.o), "type": str(r.t),
                    "title": nn(r.title), "start": iso(nn(r.s)), "end": raw_ends.get(str(r.role))})
    out.sort(key=lambda x: (x["person"], x["org"], x["start"] or "", x["role"]))
    return out


def knows_pairs(cx: Ctx) -> dict:
    """(p1, p2) -> best evidence dict (strongest), p1 < p2."""
    L = cx.live
    KE = L.C("KnowsEvidence")
    d = L.df(KE.p1.id.alias("p1"), KE.p2.id.alias("p2"), KE.kind.alias("kind"), KE.key.alias("key"),
             KE.strength.alias("st"), KE.label.alias("label"))
    opt = {}
    for attr, via, name in (("organization", "id", "org"), ("from_date", None, "from"), ("to_date", None, "to")):
        e = getattr(KE, attr)
        if via:
            e = getattr(e, via)
        try:
            dd = L.df(KE.p1.id.alias("p1"), KE.p2.id.alias("p2"), KE.kind.alias("kind"), KE.key.alias("key"),
                      e.alias("v"))
            for r in dd.itertuples(index=False):
                opt[(str(r.p1), str(r.p2), str(r.kind), str(r.key), name)] = nn(r.v)
        except Exception as exc:
            warn(f"KnowsEvidence.{attr} not readable ({type(exc).__name__}); hop dates/orgs will be null")
    pairs: dict = {}
    for r in d.itertuples(index=False):
        k = (str(r.p1), str(r.p2))
        ev = {"kind": str(r.kind), "key": str(r.key), "strength": float(r.st), "label": str(r.label),
              "org": opt.get(k + (str(r.kind), str(r.key), "org")),
              "from": iso(opt.get(k + (str(r.kind), str(r.key), "from"))),
              "to": iso(opt.get(k + (str(r.kind), str(r.key), "to")))}
        cur = pairs.get(k)
        if cur is None or (-ev["strength"], ev["kind"], ev["key"]) < (-cur["strength"], cur["kind"], cur["key"]):
            pairs[k] = ev
    return pairs


def tie_type(kind: str) -> str:
    k = kind.upper()
    for p in ("K1", "K2", "K3"):
        if k.startswith(p):
            return p
    raise ExportError(f"KnowsEvidence.kind {kind!r} is not K1, K2 or K3")


def build_q_path(cx: Ctx, hero, score_info: dict) -> tuple[dict, dict]:
    L = cx.live
    DM, WP, WH, Co = L.C("DecisionMaker"), L.C("WarmPath"), L.C("WarmPathHop"), L.C("Company")
    pairs = knows_pairs(cx)
    roles = person_roles(cx)
    d = L.df(DM.target.id.alias("t"), DM.person.id.alias("p"), DM.kind.alias("kind"))
    dms = sorted({(str(r.t), str(r.p), str(r.kind)) for r in d.itertuples(index=False)})
    dm_hops = {(str(r.t), str(r.p)): i_or_none(r.h)
               for r in L.df(DM.target.id.alias("t"), DM.person.id.alias("p"), DM.hops.alias("h")).itertuples(index=False)}
    d = L.df(WP.target.id.alias("t"), WP.decision_maker.id.alias("p"), WP.route.alias("route"),
             WP.seed.id.alias("seed"), WP.hops.alias("hops"), WP.strength.alias("st"), WP.path_rank.alias("rk"))
    paths: dict = {}
    for r in d.itertuples(index=False):
        paths.setdefault((str(r.t), str(r.p)), []).append(
            {"route": str(r.route), "seed": str(r.seed), "hops": int(r.hops), "strength": float(r.st), "rank": int(r.rk)})
    d = L.df(WH.path.target.id.alias("t"), WH.path.decision_maker.id.alias("p"), WH.path.route.alias("route"),
             WH.step.alias("step"), WH.from_person.id.alias("a"), WH.to_person.id.alias("b"),
             WH.strength.alias("st"), WH.evidence.alias("ev"))
    hops: dict = {}
    for r in d.itertuples(index=False):
        hops.setdefault((str(r.t), str(r.p), str(r.route)), {})[int(r.step)] = {
            "a": str(r.a), "b": str(r.b), "st": float(r.st), "ev": str(r.ev)}
    # targets: those the hero q_path returns, by name, in score-rank order
    qp = hero.get("q_path")
    if qp is None or getattr(qp, "empty", True):
        raise ExportError("Q-PATH: queries.q_path() returned no rows (empty frame; engine contention?)")
    # the hero rows carry the model's company_id: use it, so a renamed or scrubbed label cannot break the join
    if "company_id" in qp.columns:
        want = {str(x) for x in qp["company_id"].dropna()}
    else:
        names = hero_names(qp)
        want = {i for i, n in cx.company_name.items() if n in names}
    dm_targets = {t for t, _, _ in dms}
    tgt_ids = sorted(want & dm_targets,
                     key=lambda t: (score_info["info"].get(t, {}).get("rank") or 10**6, t))
    if not tgt_ids or set(tgt_ids) != want:
        raise ExportError(f"Q-PATH: q_path() targets {sorted(want)} vs DecisionMaker targets in the model "
                          f"{sorted(want & dm_targets)} ({len(dms)} DecisionMaker rows read)")
    owner = L.prop(Co, "current_owner_fund", via="id")
    fund_sponsor = {}
    F = L.C("Fund")
    for r in L.df(F.id.alias("f"), F.sponsor.id.alias("s")).itertuples(index=False):
        fund_sponsor[str(r.f)] = str(r.s)
    closest = L.prop(Co, "closest_intermediary", via="id")
    closest_ev = L.prop(Co, "closest_intermediary_evidence")
    edges: dict = {}      # edge_id -> view edge
    vnodes: dict = {}

    def vnode(pid, tags=()):
        n = vnodes.setdefault(pid, {"id": pid, "label": cx.name_of(pid), "type": cx.node_type(pid), "tags": []})
        for t in tags:
            if t not in n["tags"]:
                n["tags"].append(t)

    def eid(a, b, tt):
        a, b = sorted((a, b))
        return f"PE:{a}:{b}:{tt}"

    seeds = sorted(cx.seed_ids)
    seed_title = {}
    for r in roles:
        if r["person"] in cx.seed_ids and r["end"] is None:
            seed_title.setdefault(r["person"], r["title"] or r["type"])
    for s in seeds:
        vnode(s, ["our_person"])
    targets = []
    for t in tgt_ids:
        owner_fund = nn(owner.get(t))
        owner_org = fund_sponsor.get(owner_fund) if owner_fund else None
        dm_docs = []
        for _, p, kind in sorted((x for x in dms if x[0] == t), key=lambda x: (x[2] != "CEO", x[1])):
            vnode(p, ["decision_maker"])
            plist = sorted(paths.get((t, p), []), key=lambda x: (x["rank"], x["route"]))[:MAX_PATHS_PER_DM]
            pdocs = []
            for pr in plist:
                hs = hops.get((t, p, pr["route"]), {})
                hdocs, nodes_ = [], []
                for step in sorted(hs):
                    h = hs[step]
                    a, b = h["a"], h["b"]
                    k = (min(a, b), max(a, b))
                    ev = pairs.get(k)
                    if ev is None:
                        raise ExportError(f"Q-PATH: no KnowsEvidence for hop {a}-{b} on path {pr['route']}")
                    tt = tie_type(ev["kind"])
                    e_id = eid(a, b, tt)
                    for x in (a, b):
                        vnode(x)
                    edges.setdefault(e_id, {"id": e_id, "source": a, "target": b, "type": KIND_TO_EDGE[tt],
                                            "label": ev["label"]})
                    org_id = nn(ev["org"])
                    hdocs.append({"edge_id": e_id, "from_id": a, "from_name": cx.name_of(a), "to_id": b,
                                  "to_name": cx.name_of(b), "tie_type": tt,
                                  "tie_label": EDGE_LABELS[KIND_TO_EDGE[tt]],
                                  "org_id": org_id, "org_name": cx.org_name.get(org_id) if org_id else None,
                                  "start_date": ev["from"], "end_date": ev["to"],
                                  "years": years_between(ev["from"], ev["to"], cx.as_of) if ev["from"] else None,
                                  "recency": None, "strength": h["st"], "evidence": h["ev"] or ev["label"],
                                  "rule_id": cx.rid(KIND_TO_EDGE[tt] if tt != "K1" else "tenure")})
                    if not nodes_:
                        nodes_.append(a)
                    nodes_.append(b)
                pdocs.append({"path_id": f"{t}:{p}:{pr['rank']}", "rank": pr["rank"], "length": pr["hops"],
                              "strength": pr["strength"], "node_ids": nodes_, "hops": hdocs})
            hops_n = dm_hops.get((t, p))
            warm = bool(pdocs)
            label = "CEO" if kind == "CEO" else f"Board designee, {cx.org_name.get(owner_org, 'owner')}"
            dm_docs.append({"person_id": p, "name": cx.name_of(p), "kind": kind, "role_label": label,
                            "status": "warm" if warm else "cold", "hops": hops_n if warm else None,
                            "best_strength": pdocs[0]["strength"] if warm else None,
                            "summary": (f"{cx.name_of(p)} is reachable in {hops_n} hop(s) at strength "
                                        f"{pdocs[0]['strength']:.3f}." if warm else
                                        f"No path from our team to {cx.name_of(p)} within {getattr(L.core, 'MAX_PATH_HOPS', 3)} hops."),
                            "paths": pdocs})
        rej = rejected_claims(cx, t, [x["person_id"] for x in dm_docs], roles, pairs, edges, vnode, eid)
        ci = nn(closest.get(t))
        status = "warm" if any(x["status"] == "warm" for x in dm_docs) else "cold"
        ci_doc = None
        if ci and status == "cold":
            ci_doc = {"org_id": ci, "name": cx.org_name.get(ci, ci), "evidence": closest_ev.get(t) or "",
                      "rule_id": cx.rid("closest")}
            vnode(ci)
        targets.append({"company_id": t, "company_name": cx.company_name[t],
                        "score_rank": int(score_info["info"][t]["rank"]),
                        "owner_name": cx.org_name.get(owner_org) if owner_org else None, "status": status,
                        "summary": (f"Warmest route to the CEO has {min([x['hops'] for x in dm_docs if x['hops'] is not None] or [0])} hop(s)."
                                    if status == "warm" else "No warm path to any decision-maker; closest door is the intermediary below."),
                        "decision_makers": dm_docs, "rejected_claims": rej, "closest_intermediary": ci_doc,
                        "next_step": ({"label": "See who covers this sponsor in deal flow", "view": "flow", "node_id": ci}
                                      if ci_doc else None)})
    crosscheck("Q-PATH", hero.get("q_path"), {x["company_name"] for x in targets} | {
        n for tg in targets for dm in tg["decision_makers"] for n in (dm["name"],)} | set(hero_names(hero.get("q_path")) & set(cx.person_name.values())))
    nodes = sorted(vnodes.values(), key=lambda n: n["id"])
    eds = sorted(edges.values(), key=lambda e: e["id"])
    place(nodes, eds)
    doc = {"question_id": "Q-PATH", "business_question": "For our top three, what is our warmest path to each CEO, and through whom?",
           "max_hops": int(getattr(L.core, "MAX_PATH_HOPS", 3)),
           "seeds": [{"person_id": s, "name": cx.name_of(s), "title": seed_title.get(s) or ""} for s in seeds],
           "tie_types": [{"id": k, "label": EDGE_LABELS[v], "rule_id": cx.rid(v)} for k, v in KIND_TO_EDGE.items()],
           "targets": targets, "view_graph": {"nodes": nodes, "edges": eds}}
    return doc, {"target_ids": tgt_ids, "path_people": {p for tg in targets for dm in tg["decision_makers"]
                                                       for pa in dm["paths"] for p in pa["node_ids"]},
                 "dm_people": {dm["person_id"] for tg in targets for dm in tg["decision_makers"]},
                 "closest": {tg["closest_intermediary"]["org_id"] for tg in targets if tg["closest_intermediary"]}}


def rejected_claims(cx, target, dm_ids, roles, pairs, edges, vnode, eid) -> list[dict]:
    """A shared employer with no overlapping tenure between a person we reach and a decision-maker."""
    L = cx.live
    by_org: dict = {}
    for r in roles:
        by_org.setdefault(r["org"], []).append(r)
    reach = {r["person"] for r in roles} & set(
        L.prop(L.C("Person"), "nearest_seed_hops").keys() if "nearest_seed_hops" in dir(L.C("Person")) else [])
    out = []
    for dm in dm_ids:
        for org, rs in sorted(by_org.items()):
            mine = [r for r in rs if r["person"] == dm]
            if not mine:
                continue
            for q in sorted({r["person"] for r in rs} - {dm}):
                if q not in reach and q not in cx.seed_ids:
                    continue
                theirs = [r for r in rs if r["person"] == q]
                k = (min(dm, q), max(dm, q))
                if k in pairs and pairs[k]["org"] == org:
                    continue
                gaps = []
                overlap = False
                for a in mine:
                    for b in theirs:
                        a0, a1 = to_date(a["start"]), to_date(a["end"] or cx.as_of)
                        b0, b1 = to_date(b["start"]), to_date(b["end"] or cx.as_of)
                        if a0 <= b1 and b0 <= a1:
                            overlap = True
                        else:
                            gaps.append((b0 - a1).days if b0 > a1 else (a0 - b1).days)
                if overlap or not gaps:
                    continue
                gap = min(gaps)
                e_id = eid(dm, q, "rejected") + f":{org}"
                for x in (dm, q):
                    vnode(x)
                edges.setdefault(e_id, {"id": e_id, "source": q, "target": dm, "type": "rejected",
                                        "label": "shared employer, no overlap"})
                out.append({"edge_id": e_id, "from_id": q, "from_name": cx.name_of(q), "to_id": dm,
                            "to_name": cx.name_of(dm), "org_name": cx.org_name.get(org, org),
                            "claim": f"Both worked at {cx.org_name.get(org, org)}.",
                            "reason": f"Their tenures at {cx.org_name.get(org, org)} never overlapped; the gap was {gap} days.",
                            "intervals": [{"person_id": r["person"], "name": cx.name_of(r["person"]),
                                           "start_date": r["start"], "end_date": r["end"]}
                                          for r in sorted(mine + theirs, key=lambda r: (r["start"] or "", r["person"]))],
                            "gap_days": gap, "rule_id": cx.rid("rejected")})
    out.sort(key=lambda x: (x["gap_days"], x["edge_id"]))
    return out[:2]


# ---------------------------------------------------------------------------------------------- Q-FLOW
def build_q_flow(cx: Ctx, hero) -> tuple[dict, dict]:
    L = cx.live
    I, O, Tx, TP = L.C("Intermediary"), L.C("Organization"), L.C("DealFlowTransaction"), L.C("TransactionParty")
    info = _by_id(L, I, {"name": ("name", None), "betw": ("betweenness", None), "pr": ("pagerank", None),
                         "rank": ("bridge_rank", None), "win": ("thesis_deals_5y", None),
                         "all": ("all_deals_5y", None), "tp": ("touchpoints_24m", None)})
    gap_ids = L.ids(L.C("CoverageGap")) if "CoverageGap" in dir(L.core) else []
    gap = set(gap_ids)
    cutoff = i_or_none(L.scalar(L.core.bridge_cutoff))
    q1 = i_or_none(L.scalar(L.core.coverage_q1))
    tinfo = _by_id(L, Tx, {"date": ("close_date", None), "target": ("target", "id"), "seller": ("seller_type", None),
                           "structure": ("structure", None), "role": ("deal_role", None)})
    d = L.df(TP.transaction.id.alias("t"), TP.organization.id.alias("o"), TP.party_role.alias("r"))
    parties: dict = {}
    txn_set = set(tinfo)
    for r in d.itertuples(index=False):
        if str(r.t) in txn_set:
            parties.setdefault(str(r.t), []).append((str(r.o), str(r.r)))
    rows = []
    deals = []
    vn: dict = {}
    ve: dict = {}

    def vnode(i, tags=()):
        n = vn.setdefault(i, {"id": i, "label": cx.name_of(i), "type": cx.node_type(i), "tags": []})
        for t in tags:
            if t not in n["tags"]:
                n["tags"].append(t)
    deal_ids_by_adv: dict = {}
    for t in sorted(tinfo, key=lambda t: (tinfo[t]["date"], t)):
        x = tinfo[t]
        adv = sorted({o for o, r in parties.get(t, []) if r.endswith("advisor") and o in info})
        buyers = sorted({o for o, r in parties.get(t, []) if r == "buyer"})
        tgt = str(x["target"])
        vnode(tgt)
        eids = []
        for a in adv:
            vnode(a)
            e = f"DF:{t}:{a}"
            ve[e] = {"id": e, "source": a, "target": tgt, "type": "advised", "label": "advised"}
            eids.append(e)
            deal_ids_by_adv.setdefault(a, []).append(t)
        for b in buyers:
            vnode(b)
            e = f"DF:{t}:{b}"
            ve[e] = {"id": e, "source": b, "target": tgt, "type": "bought", "label": "bought"}
            eids.append(e)
        deals.append({"txn_id": t, "close_date": iso(x["date"]), "target_id": tgt,
                      "target_name": cx.company_name.get(tgt, tgt),
                      "buyer_name": cx.org_name.get(buyers[0]) if buyers else None,
                      "seller_type": str(x["seller"]), "structure": str(x["structure"]), "deal_role": str(x["role"]),
                      "advisor_ids": adv, "advisor_names": [cx.org_name[a] for a in adv], "edge_ids": eids})
    for i in sorted(info, key=lambda i: (info[i].get("rank") is None, info[i].get("rank") or 0, i)):
        x = info[i]
        if x.get("rank") is None:
            continue
        is_gap = i in gap
        top = cutoff is not None and int(x["rank"]) <= cutoff
        tp = int(x.get("tp") or 0)
        vnode(i, (["coverage_gap"] if is_gap else []) + (["top_decile"] if top else []))
        rows.append({"org_id": i, "name": x["name"], "betweenness": float(x["betw"]), "betweenness_rank": int(x["rank"]),
                     "pagerank": float(x.get("pr") or 0), "deals_in_window": int(x.get("win") or 0),
                     "deals_5y_all_sectors": int(x.get("all") or 0), "touchpoints_24m": tp, "top_decile": top,
                     "is_gap": is_gap,
                     "gap_reason": (f"Top-decile bridge with {tp} touchpoint(s) in 24 months, at or below the "
                                    f"bottom-quartile level of {q1}." if is_gap else None),
                     "deal_ids": sorted(set(deal_ids_by_adv.get(i, [])))})
    if cutoff is None or q1 is None:
        raise ExportError("Q-FLOW: bridge_cutoff / coverage_q1 are not populated by rules.py")
    # organizations in the deal-flow graph and its edge count
    d = L.df(O.id.alias("a"), O.deal_flow_partner.id.alias("b"))
    pairs_ = {tuple(sorted((str(r.a), str(r.b)))) for r in d.itertuples(index=False)}
    gnodes = {x for p in pairs_ for x in p}
    nodes = sorted(vn.values(), key=lambda n: n["id"])
    eds = sorted(ve.values(), key=lambda e: e["id"])
    place(nodes, eds)
    end = _dt.date.fromisoformat(cx.as_of)
    doc = {"question_id": "Q-FLOW",
           "business_question": "Which intermediaries actually bridge deal flow between founders and sponsors, and where do we have no coverage?",
           "window": {"start": minus_years(end, WINDOW_YEARS).isoformat(), "end": end.isoformat()},
           "graph_stats": {"num_nodes": len(gnodes), "num_edges": len(pairs_),
                           "num_intermediaries": len(gnodes & cx.interm_ids)},
           "thresholds": {"top_decile_cutoff_rank": cutoff, "q1_touchpoints": q1},
           "intermediaries": rows, "deals": deals, "view_graph": {"nodes": nodes, "edges": eds}}
    crosscheck("Q-FLOW", hero.get("q_flow"), {r["name"] for r in rows})
    return doc, {"rows": rows, "gap": gap, "top": [r["org_id"] for r in rows if r["top_decile"]],
                 "graph_orgs": gnodes}


# ------------------------------------------------------------------------------------------- Q-CONFLICT
def build_q_conflict(cx: Ctx, hero) -> tuple[dict | None, dict]:
    L = cx.live
    CS, PX, AE, PF, Co = (L.C("ConflictSubject"), L.C("PortfolioExposure"), L.C("AreaExposure"),
                          L.C("ProFormaExposure"), L.C("Company"))
    subs = L.ids(CS)
    if not subs:
        warn("no ConflictSubject rows: q_conflict.json not written")
        return None, {}
    d = L.df(PX.subject.id.alias("s"), PX.company.id.alias("c"), PX.fund.name.alias("f"), PX.hops.alias("h"),
             PX.kind.alias("k"), PX.evidence.alias("ev"))
    kmap = {getattr(L.rules, "EXPOSURE_CONFLICT_KIND", "CONFLICT - cross-fund review"): "conflict",
            "SAME-FUND LINK": "same_fund", "SHARED COUNTERPARTY (informational)": "informational"}
    exp_rows = [(str(r.s), str(r.c), str(r.f), int(r.h), kmap.get(str(r.k), str(r.k)), str(r.ev)) for r in d.itertuples(index=False)]
    hero_n = hero_names(hero.get("q_conflict")) if "q_conflict" in hero else set()
    subs_with = [s for s in subs if any(e[0] == s and e[4] == "conflict" for e in exp_rows)]
    pick = [s for s in (subs_with or subs) if cx.company_name.get(s) in hero_n] or (subs_with or subs)
    subject = sorted(pick)[0]
    if len(subs) > 1:
        warn(f"{len(subs)} ConflictSubjects; exported {cx.company_name[subject]} (named by q_conflict(), else first with a conflict)")
    area = nn(L.prop(Co, "thesis_area", via="id").get(subject))
    area_name = cx.sector_name.get(area, area)
    # commercial links
    CL = L.C("CommercialLink")
    d = L.df(CL.id.alias("i"), CL.supplier.id.alias("a"), CL.customer.id.alias("b"))
    links = sorted((str(r.i), str(r.a), str(r.b)) for r in d.itertuples(index=False))
    adj: dict = {}
    for i, a, b in links:
        adj.setdefault(a, []).append((b, i, a, b))
        adj.setdefault(b, []).append((a, i, a, b))
    # holdings
    Ow = L.C("Ownership")
    d = L.df(Ow.id.alias("o"), Ow.company.id.alias("c"), Ow.fund.id.alias("f"), Ow.start_date.alias("s"))
    own = {str(r.o): {"c": str(r.c), "f": str(r.f), "s": iso(nn(r.s))} for r in d.itertuples(index=False)}
    for r in L.df(Ow.id.alias("o"), Ow.equity_invested_musd.alias("e")).itertuples(index=False):
        own[str(r.o)]["eq"] = f_or_none(r.e)
    for r in L.df(Ow.id.alias("o"), Ow.end_date.alias("e")).itertuples(index=False):
        own[str(r.o)]["end"] = iso(nn(r.e))
    since = {}
    for o in sorted(own):
        if own[o].get("end") is None:
            since.setdefault(own[o]["c"], own[o]["s"])
    vn: dict = {}
    ve: dict = {}

    def vnode(i, tags=()):
        n = vn.setdefault(i, {"id": i, "label": cx.name_of(i), "type": "company", "tags": []})
        for t in tags:
            if t not in n["tags"]:
                n["tags"].append(t)

    def link_edge(l):
        i, a, b = l
        e = f"CL:{i}"
        ve.setdefault(e, {"id": e, "source": a, "target": b, "type": "commercial", "label": "supplies"})
        vnode(a), vnode(b)
        return e

    def route(src, dst, max_d):
        """Shortest commercial route (list of link tuples) from src to dst, deterministic."""
        frontier, seen = [(src, [])], {src}
        for _ in range(max_d):
            nxt = []
            for node, p in frontier:
                for (o, i, a, b) in sorted(adj.get(node, [])):
                    if o in seen:
                        continue
                    seen.add(o)
                    np_ = p + [(i, a, b)]
                    if o == dst:
                        return np_
                    nxt.append((o, np_))
            frontier = nxt
        return None
    vnode(subject, ["subject"])
    exposures = []
    kind_label = {"conflict": "Conflict - cross-fund review", "same_fund": "Same fund - no conflict",
                  "informational": "Informational"}
    for s, c, fund, h, kind, ev in sorted(exp_rows, key=lambda e: (e[3], e[4] != "conflict", e[1])):
        if s != subject:
            continue
        rt = route(subject, c, h) or []
        nodes_ = [subject] + [x for l in rt for x in (l[1], l[2]) if x != subject][:0]
        pn, cur = [subject], subject
        for (i, a, b) in rt:
            cur = b if a == cur else a
            pn.append(cur)
        eids = [link_edge(l) for l in rt]
        vnode(c, ["conflict"] if kind == "conflict" else [])
        exposures.append({"company_id": c, "name": cx.company_name[c], "fund_name": fund, "since": since.get(c) or "",
                          "distance": h, "kind": kind, "kind_label": kind_label.get(kind, kind.replace("_", " ").capitalize()),
                          "evidence": ev, "path_node_ids": pn, "edge_ids": eids, "rule_id": cx.rid("exposure")})
    # context: former holdings of our funds within 2 links, and 3-hop rim
    our_funds = L.ids(L.C("OurFund"))
    now_held = {e["company_id"] for e in exposures}
    context = []
    for o in sorted(own):
        x = own[o]
        if x["f"] in our_funds and x.get("end") is not None and x["c"] not in now_held and x["c"] != subject:
            rt = route(subject, x["c"], 2)
            if rt is not None:
                vnode(x["c"], ["context"])
                context.append({"company_id": x["c"], "name": cx.company_name[x["c"]], "distance": len(rt),
                                "reason": f"Former holding of {cx.fund_name.get(x['f'], x['f'])}, sold on {x['end']}; no longer a current exposure.",
                                "edge_ids": [link_edge(l) for l in rt]})
    held_now = {x["c"] for x in own.values() if x["f"] in our_funds and x.get("end") is None}
    for c in sorted(held_now - now_held - {subject}):
        rt = route(subject, c, 3)
        if rt is not None and len(rt) == 3:
            vnode(c, ["context"])
            context.append({"company_id": c, "name": cx.company_name[c], "distance": 3,
                            "reason": "Held today but three commercial links away, outside the two-link review distance.",
                            "edge_ids": [link_edge(l) for l in rt]})
    # concentration
    BF = L.C("BuyingFund")
    fid = L.ids(BF)[0]
    F = L.C("Fund")
    fsize = L.prop(F, "size_musd")[fid]
    guide = L.prop(F, "area_guideline_pct")[fid]
    PE = L.C("PipelineEntry")
    d = L.df(PE.company.id.alias("c"), PE.est_equity_check_musd.alias("e"))
    check = {str(r.c): f_or_none(r.e) for r in d.itertuples(index=False)}.get(subject)
    if check is None:
        raise ExportError(f"Q-CONFLICT: no pipeline equity check for {cx.company_name[subject]}")
    d = L.df(AE.area.id.alias("a"), AE.current_musd.alias("m"), AE.current_pct.alias("p"))
    before = {str(r.a): (float(r.m), float(r.p)) for r in d.itertuples(index=False)}
    d = L.df(PF.subject.id.alias("s"), PF.area.id.alias("a"), PF.musd.alias("m"), PF.pct.alias("p"),
             PF.headroom_musd.alias("hr"), PF.over_by_musd.alias("ov"))
    after = {str(r.a): r for r in d.itertuples(index=False) if str(r.s) == subject}
    breach = L.flag(PF, "is_breach") if False else set()
    try:
        dd = L.df(PF.subject.id.alias("s"), PF.area.id.alias("a"), where=[PF.is_breach()])
        breach = {str(r.a) for r in dd.itertuples(index=False) if str(r.s) == subject}
    except Exception as exc:
        warn(f"ProFormaExposure.is_breach not readable ({type(exc).__name__}); breach derived from over_by_musd > 0")
        breach = {a for a, r in after.items() if float(r.ov) > 0}
    areas = []
    for a in sorted(before, key=lambda a: (cx.sector_name.get(a, a), a)):
        r = after.get(a)
        areas.append({"name": cx.sector_name.get(a, a), "before_musd": before[a][0], "before_pct": before[a][1],
                      "after_musd": float(r.m) if r is not None else before[a][0],
                      "after_pct": float(r.p) if r is not None else before[a][1],
                      "is_subject_area": a == area, "breach": a in breach})
    sa = after.get(area)
    if sa is None:
        raise ExportError("Q-CONFLICT: no ProFormaExposure for the subject's thesis area")
    Co_area = L.prop(Co, "thesis_area", via="id")
    Co_sector = L.prop(Co, "sector", via="id")
    holdings = []
    for o in sorted(own):
        x = own[o]
        if x["f"] == fid and x.get("end") is None:
            ar, ni = nn(Co_area.get(x["c"])), nn(Co_sector.get(x["c"]))
            holdings.append({"company_id": x["c"], "name": cx.company_name[x["c"]],
                             "area": cx.sector_name.get(ar, ar or ""), "niche": cx.sector_name.get(ni, ni or ""),
                             "since": x["s"] or "", "equity_musd": x.get("eq") or 0.0,
                             "pct": round(100.0 * (x.get("eq") or 0.0) / fsize, 6)})
    holdings.sort(key=lambda h: (-h["equity_musd"], h["name"]))
    nodes = sorted(vn.values(), key=lambda n: n["id"])
    eds = sorted(ve.values(), key=lambda e: e["id"])
    place(nodes, eds)
    doc = {"question_id": "Q-CONFLICT",
           "business_question": f"Before we bid on {cx.company_name[subject]}, does it conflict with anything we own, and does it breach our concentration guideline?",
           "subject": {"company_id": subject, "name": cx.company_name[subject], "thesis_area": area_name or ""},
           "max_distance": max((e["distance"] for e in exposures), default=2),
           "rule_ids": [cx.rid("holding"), cx.rid("exposure"), cx.rid("concentration")],
           "exposures": exposures, "context": context,
           "concentration": {"fund_name": cx.fund_name[fid], "fund_size_musd": fsize, "guideline_pct": guide,
                             "check_musd": check, "subject_area": area_name or "", "breach": area in breach,
                             "headroom_musd": float(sa.hr), "over_by_musd": float(sa.ov),
                             "rule_id": cx.rid("concentration"), "areas": areas, "holdings": holdings},
           "view_graph": {"nodes": nodes, "edges": eds}}
    crosscheck("Q-CONFLICT", hero.get("q_conflict"), {e["name"] for e in exposures} | {doc["subject"]["name"]}
               | {h["name"] for h in holdings} | {c["name"] for c in context} | {a["name"] for a in areas})
    return doc, {"subject": subject, "exposure_ids": {e["company_id"] for e in exposures}}


# ------------------------------------------------------------------------------------------ explorer graph
def build_graph(cx: Ctx, rules_by_id, hero_ids: set, score_ctx: dict, path_ctx: dict, flow_ctx: dict,
                conflict_ctx: dict, target: int) -> dict:
    L = cx.live
    pairs = knows_pairs(cx)
    roles = person_roles(cx)
    adj: dict = {}
    allowed: dict = {}  # edge id -> edge dict
    ev = {}

    def add(a, b, typ, evidence, facts=None, eid=None):
        if a == b:
            return
        a2, b2 = sorted((a, b))
        e = eid or f"G:{typ}:{a2}:{b2}"
        if e in allowed:
            return
        allowed[e] = {"id": e, "source": a, "target": b, "type": typ, "evidence": evidence,
                      "rule_id": cx.rid(EDGE_RULE[typ]), "facts": facts or []}
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    for (p1, p2), e in sorted(pairs.items()):
        tt = tie_type(e["kind"])
        add(p1, p2, KIND_TO_EDGE[tt], e["label"],
            [{"label": "Strength", "value": e["strength"], "fmt": "f3", "rule_id": cx.rid(KIND_TO_EDGE[tt])}])
    for r in roles:
        if r["type"].lower().startswith("board"):
            add(r["person"], r["org"], "board", f"{cx.name_of(r['person'])} sits on the board of {cx.name_of(r['org'])}"
                f" since {r['start']}" if r["start"] else f"{cx.name_of(r['person'])} board member",
                [{"label": "Since", "value": r["start"], "fmt": "raw"}], eid=f"G:board:{r['role']}")
        elif r["end"] is None and r["org"] in cx.company_ids | cx.sponsor_ids | cx.interm_ids:
            add(r["person"], r["org"], "employment", f"{cx.name_of(r['person'])}, {r['title'] or r['type']}, {cx.name_of(r['org'])}",
                [], eid=f"G:employment:{r['role']}")
    CL = L.C("CommercialLink")
    d = L.df(CL.id.alias("i"), CL.supplier.id.alias("a"), CL.customer.id.alias("b"))
    for r in sorted(d.itertuples(index=False), key=lambda r: str(r.i)):
        add(str(r.a), str(r.b), "commercial", f"{cx.name_of(str(r.a))} supplies {cx.name_of(str(r.b))}", [],
            eid=f"G:commercial:{r.i}")
    Ow = L.C("Ownership")
    d = L.df(Ow.id.alias("o"), Ow.company.id.alias("c"), Ow.fund.id.alias("f"))
    ends = {str(r.o): nn(r.e) for r in L.df(Ow.id.alias("o"), Ow.end_date.alias("e")).itertuples(index=False)}
    for r in sorted(d.itertuples(index=False), key=lambda r: str(r.o)):
        cur = ends.get(str(r.o)) is None
        add(str(r.f), str(r.c), "ownership", f"{cx.name_of(str(r.f))} {'holds' if cur else 'held'} {cx.name_of(str(r.c))}",
            [], eid=f"G:ownership:{r.o}")
    # CRM: interactions between our people and counterparties
    I = L.C("Interaction")
    d = L.df(I.id.alias("i"), I.our_person.id.alias("a"), I.counterparty_person.id.alias("b"),
             I.interaction_date.alias("d"), I.channel.alias("ch"))
    seen = set()
    for r in sorted(d.itertuples(index=False), key=lambda r: str(r.i)):
        k = tuple(sorted((str(r.a), str(r.b))))
        if k in seen:
            continue
        seen.add(k)
        add(str(r.a), str(r.b), "crm", f"CRM contact: {r.ch} on {iso(nn(r.d))}",
            [{"label": "Last logged", "value": iso(nn(r.d)), "fmt": "raw"}], eid=f"G:crm:{r.i}")
    # sponsor / fund / transaction edges (deal): buyer-target via party role
    TP = L.C("TransactionParty")
    d = L.df(TP.transaction.id.alias("t"), TP.organization.id.alias("o"), TP.party_role.alias("r"),
             TP.transaction.target.id.alias("c"))
    for r in sorted(d.itertuples(index=False), key=lambda r: (str(r.t), str(r.o), str(r.r))):
        add(str(r.o), str(r.c), "deal", f"{cx.name_of(str(r.o))} was {str(r.r).replace('_', ' ')} on the deal for {cx.name_of(str(r.c))}",
            [], eid=f"G:deal:{r.t}:{r.o}:{r.r}")
    model_nodes = len(set(adj))
    model_edges = len(allowed)
    # --- choose the subgraph: hero entities, then breadth-first by link count, capped
    chosen = {h for h in hero_ids if h in adj or h in cx.person_name or h in cx.org_name}
    target = max(SUBGRAPH_MIN, min(target, SUBGRAPH_MAX))
    frontier = set(chosen)
    while len(chosen) < target:
        cand: dict = {}
        for n in frontier:
            for m in adj.get(n, ()):
                if m not in chosen:
                    cand[m] = cand.get(m, 0) + 1
        if not cand:
            break
        order = sorted(cand, key=lambda m: (-cand[m], -len(adj.get(m, ())), m))
        room = target - len(chosen)
        take = order[:room]
        chosen |= set(take)
        frontier = set(take)
    if len(chosen) > HARD_CAP:
        raise ExportError(f"subgraph has {len(chosen)} nodes, above the hard cap {HARD_CAP}")
    if len(chosen) < SUBGRAPH_MIN:
        warn(f"subgraph has only {len(chosen)} nodes (the model's connected data is smaller than {SUBGRAPH_MIN})")
    edges = [e for k, e in sorted(allowed.items()) if e["source"] in chosen and e["target"] in chosen]
    # --- node documents
    info = score_ctx["info"]
    Co = L.C("Company")
    owner_f = L.prop(Co, "current_owner_fund", via="id")
    our_funds = set(L.ids(L.C("OurFund")))
    buying = set(L.ids(L.C("BuyingFund")))
    our_sponsor = set(L.ids(L.C("OurSponsor")))
    seeds = cx.seed_ids
    nodes = []
    for i in sorted(chosen):
        typ = cx.node_type(i)
        tags, facts = [], []
        if i in our_sponsor:
            tags.append("northwind")
        if i in seeds:
            tags += ["our_person", "northwind"]
        if i in score_ctx["tier_a_ids"]:
            tags.append("tier_a")
        if i in score_ctx["not_in_crm"]:
            tags.append("not_in_crm")
        if i in path_ctx.get("target_ids", []):
            tags.append("path_target")
        if i in flow_ctx.get("gap", set()):
            tags.append("coverage_gap")
        of = nn(owner_f.get(i)) if typ == "company" else None
        if of in buying:
            tags.append("platform")
        elif of in our_funds:
            tags.append("fund_iii_portfolio")
        if typ == "company" and i in info:
            x = info[i]
            facts = [{"label": "Score", "value": int(x["score"]), "fmt": "int", "rule_id": cx.rid("score")},
                     {"label": "Tier", "value": x["tier"]},
                     {"label": "EBITDA", "value": float(x["ebitda"]), "fmt": "musd1"}]
        elif typ == "intermediary":
            fl = {r["org_id"]: r for r in flow_ctx.get("rows", [])}.get(i)
            if fl:
                facts = [{"label": "Bridge rank", "value": fl["betweenness_rank"], "fmt": "int", "rule_id": cx.rid("flow")},
                         {"label": "Touchpoints (24 months)", "value": fl["touchpoints_24m"], "fmt": "int"}]
        nodes.append({"id": i, "label": cx.name_of(i), "type": typ, "tags": sorted(set(tags)), "facts": facts})
    place(nodes, edges)
    counts: dict = {}
    for e in edges:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    etypes = [{"id": t, "label": EDGE_LABELS[t], "rule_id": cx.rid(EDGE_RULE[t]), "count": counts.get(t, 0)}
              for t in ("tenure", "board", "deal", "commercial", "crm", "ownership", "employment")]
    return {"layout": {"algorithm": "numpy.fruchterman_reingold", "seed": SEED, "scale": LAYOUT_SCALE},
            "stats": {"num_nodes": len(nodes), "num_edges": len(edges), "model_nodes": model_nodes,
                      "model_edges": model_edges},
            "node_types": [{"id": a, "label": b} for a, b in NODE_TYPES], "edge_types": etypes,
            "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------------------------- SQL baseline
NAIVE_DIR = ROOT / "data" / "naive_sql"
SQL_FILES = {"Q-SCORE": "q_score.sql", "Q-PATH": "q_path.sql", "Q-FLOW": "q_flow.sql", "Q-CONFLICT": "q_conflict.sql",
             "Q-ADDON": "q_addon.sql"}
KG_LABEL = {"Q-SCORE": "Tier A", "Q-PATH": "Warm targets", "Q-FLOW": "Top bridges", "Q-CONFLICT": "Conflicts",
            "Q-ADDON": "Add-ons"}


def snowflake_rows(sql: str):
    import yaml
    import snowflake.connector
    cfg = yaml.safe_load((ROOT / "raiconfig.yaml").read_text())
    c = cfg["connections"][cfg.get("default_connection", "pe_demo")]
    token = Path(c["token_file_path"]).expanduser().read_text().strip()
    con = snowflake.connector.connect(account=c["account"], user=c["user"], authenticator="programmatic_access_token",
                                      token=token, role=c["role"], warehouse=c["warehouse"],
                                      database="RAI_DEMO_PE_DEALS", schema="DEAL_GRAPH")
    try:
        cur = con.cursor()
        cur.execute(sql)
        cols = [x[0].lower() for x in cur.description]
        return cols, cur.fetchall()
    finally:
        con.close()


def build_sql_baseline(cx: Ctx, answers: dict, naive_dir: Path) -> dict:
    """answers: QID -> list of entity ids the knowledge graph returns (ordered).

    SQL file convention (R11): header comments `-- description: ...`, `-- metric_label: ...`; the query
    returns entity_id, name, metric (ordered best first) and optionally verdict, note.
    """
    if not naive_dir.is_dir():
        warn(f"{naive_dir.relative_to(ROOT) if naive_dir.is_relative_to(ROOT) else naive_dir} does not exist yet "
             f"(owner R11); sql_baseline.json is written with no questions and the explorer's SQL panels will be empty")
        return {"questions": {}}
    out = {}
    for qid, fname in SQL_FILES.items():
        p = naive_dir / fname
        if not p.exists() or qid not in answers:
            if qid in answers:
                warn(f"{p.name} missing: no SQL baseline for {qid}")
            continue
        text = p.read_text(encoding="utf-8")
        head = {m.group(1): m.group(2).strip() for m in re.finditer(r"^--\s*(description|metric_label|kg_label):\s*(.+)$", text, re.M)}
        sql = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--")).strip().rstrip(";")
        cols, data = snowflake_rows(sql)
        for need in ("entity_id", "name"):
            if need not in cols:
                raise ExportError(f"{fname}: result must have columns entity_id, name, metric (got {cols})")
        recs = [dict(zip(cols, r)) for r in data]
        kg = answers[qid]
        kgset = set(kg)
        rows = []
        for n, r in enumerate(recs[:15], 1):
            m = r.get("metric")
            m = float(m) if isinstance(m, (int, float)) and not isinstance(m, bool) else (None if m is None else str(m))
            ver = str(r.get("verdict") or ("agrees" if str(r["entity_id"]) in kgset else "other"))
            rows.append({"entity_id": str(r["entity_id"]), "name": str(r["name"]), "rank": n,
                         "metric": m if m is not None else "", "verdict": ver, "note": r.get("note")})
        returned = {str(r["entity_id"]) for r in recs}
        missed = [{"entity_id": e, "name": cx.name_of(e), "note": "Not returned by the SQL screen."}
                  for e in kg if e not in returned]
        out[qid] = {"sql_file": f"data/naive_sql/{fname}", "description": head.get("description", fname),
                    "metric_label": head.get("metric_label", "Metric"), "row_count": len(recs),
                    "kg_count": len(kg), "kg_label": head.get("kg_label", KG_LABEL[qid]), "rows": rows, "missed": missed}
    return {"questions": out}


# ---------------------------------------------------------------------------------------------- main run
def require_modules():
    if not (ROOT / "pe_deal_graph" / "queries.py").exists():
        print("export: pe_deal_graph/queries.py missing (owner R11)", file=sys.stderr)
        sys.exit(2)
    sys.path.insert(0, str(ROOT))
    try:
        queries = importlib.import_module("pe_deal_graph.queries")
        core = importlib.import_module("pe_deal_graph.model.core")
        rules = importlib.import_module("pe_deal_graph.model.rules")
        graphs = importlib.import_module("pe_deal_graph.model.graphs")
    except ModuleNotFoundError as exc:
        print(f"export: cannot import {exc.name} ({exc}); owners: rules.py R09, graphs.py R10, queries.py R11",
              file=sys.stderr)
        sys.exit(2)
    return queries, core, rules, graphs


def engine_and_version(core):
    try:
        import importlib.metadata as md
        ver = md.version("relationalai")
    except Exception:
        ver = None
    engine = None
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "raiconfig.yaml").read_text())
        engine = (cfg.get("reasoners", {}).get("logic", {}) or {}).get("name") or cfg.get("engine")
    except Exception:
        pass
    return ver, engine or "pe_demo_logic"


ENTITY_KEYS = {"name", "target", "company_name", "counterparty_name", "org_name", "person_name", "label"}


def scrub_decoys(o, aliases: dict, key=None):
    """Rewrite decoy names inside evidence/free text (not entity-name fields) with queries.DECOY_ALIASES."""
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str):
                if k not in ENTITY_KEYS:
                    for n, a in aliases.items():
                        v = v.replace(n, a)
                    o[k] = v
            else:
                scrub_decoys(v, aliases, k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str):
                for n, a in aliases.items():
                    v = v.replace(n, a)
                o[i] = v
            else:
                scrub_decoys(v, aliases, key)


def assert_no_decoys(docs: dict) -> None:
    """Golden decoys must not be part of any hero answer (same semantics as tests/test_hero.py).

    golden must_not_contain is per question: Q-FLOW's list (Cedar Row, Brayford) is about the coverage
    gaps, Tessmark is Q-CONFLICT's subject but must not be a Tier A finale row, and the Q-PATH false
    intro is meant to show up as a rejected claim. So per question, the decoy ids must be absent from the
    answer set, and the golden rehearsal must_not_appear names must be absent from the answer's text.
    Context lists (all intermediaries, rejected claims, context companies, view graphs) are exempt."""
    gq = json.loads((ROOT / "data" / "golden" / "expected.json").read_text())["questions"]

    def ids(q, key="must_not_contain"):
        return {e["id"]: e.get("name") for e in gq.get(q, {}).get(key, []) if isinstance(e, dict)}

    def names(q):
        return list((gq.get(q, {}).get("rehearsal") or {}).get("must_not_appear", [])) + \
            [e["name"] for e in gq.get(q, {}).get("tier1_must_not_appear", []) if isinstance(e, dict)]

    bad: list[str] = []

    def check(q, label, answer_ids: set, answer_docs, key="must_not_contain", text_names=None):
        for i, n in ids(q, key).items():
            if i in answer_ids:
                bad.append(f"{q}: decoy {n} ({i}) is in the {label}")
        txt = json.dumps(answer_docs, ensure_ascii=False)
        for n in (names(q) if text_names is None else text_names):
            if n in txt:
                bad.append(f"{q}: decoy name {n!r} appears in the {label}")

    sc = docs.get("q_score")
    if sc:
        tier_a = [r for r in sc["rows"] if r["tier"] == "A"]
        check("Q-SCORE", "Tier A rows", {r["company_id"] for r in tier_a}, tier_a)
        check("Q-SCORE", "Tier A/B rows (text)", set(), sc["rows"])
        fin = [r for r in ((sc.get("finale") or {}).get("rows") or []) if r["tier"] == "A"]
        check("FINALE", "finale Tier A rows", {r["company_id"] for r in fin}, [r["name"] for r in fin],
              text_names=[n for n in ids("FINALE").values() if n])
    pa = docs.get("q_path")
    if pa:
        ans = [{k: v for k, v in t.items() if k in ("company_id", "company_name", "decision_makers", "summary")}
               for t in pa["targets"]]
        ans_ids = {t["company_id"] for t in pa["targets"]} | {
            x for t in pa["targets"] for dm in t["decision_makers"]
            for x in [dm["person_id"]] + [n for pth in dm["paths"] for n in pth["node_ids"]]} | {
            h.get("org_id") for t in pa["targets"] for dm in t["decision_makers"] for pth in dm["paths"]
            for h in pth["hops"]}
        check("Q-PATH", "targets, decision-makers and warm paths", ans_ids, ans)
    fl = docs.get("q_flow")
    if fl:
        top = [r for r in fl["intermediaries"] if r["betweenness_rank"] <= 5]
        gaps = [r for r in fl["intermediaries"] if r.get("is_gap")]
        check("Q-FLOW", "betweenness top 5", {r["org_id"] for r in top}, top, key="tier1_must_not_appear")
        check("Q-FLOW", "coverage gaps", {r["org_id"] for r in gaps}, gaps)
    co = docs.get("q_conflict")
    if co:
        check("Q-CONFLICT", "exposures", {e["company_id"] for e in co["exposures"]}, co["exposures"])
    if bad:
        raise ExportError("decoys found in hero answers: " + "; ".join(bad))


def run_export(out: Path, naive_dir: Path, target: int) -> int:
    queries, core, rules_mod, graphs_mod = require_modules()
    rules_mod.enable_finale()  # finale_* and has_conflict exist only after the opt-in (idempotent)
    live = Live(core, rules_mod, graphs_mod)
    t0 = time.time()
    hero = hero_frames(queries)
    rules = collect_rules(rules_mod, graphs_mod)
    cx = Ctx(live, rules)
    need = {"q_score", "q_path", "q_flow"}
    if not need <= set(hero):
        raise ExportError(f"HERO_QUERIES must include {sorted(need)}; has {sorted(hero)}")
    score_doc, score_ctx = build_q_score(cx, hero)
    path_doc, path_ctx = build_q_path(cx, hero, score_ctx)
    flow_doc, flow_ctx = build_q_flow(cx, hero)
    conflict_doc, conflict_ctx = (build_q_conflict(cx, hero) if "q_conflict" in hero else (None, {}))
    # hero entities for the explorer subgraph
    hero_ids = set(score_ctx["tier_a_ids"]) | path_ctx["path_people"] | path_ctx["dm_people"] | path_ctx["closest"] \
        | set(path_ctx["target_ids"]) | cx.seed_ids | set(flow_ctx["top"]) | set(flow_ctx["gap"])
    if conflict_doc:
        hero_ids |= {conflict_ctx["subject"]} | conflict_ctx["exposure_ids"]
        hero_ids |= {c["company_id"] for c in conflict_doc["context"]}
    for r in (score_doc["finale"] or {"rows": []})["rows"]:
        hero_ids.add(r["company_id"])
    graph_doc = build_graph(cx, cx.rules_by_id, hero_ids, score_ctx, path_ctx, flow_ctx, conflict_ctx, target)
    missing = sorted(h for h in hero_ids if h not in {n["id"] for n in graph_doc["nodes"]})
    if missing:
        raise ExportError(f"hero entities missing from the explorer subgraph (no edges in the model?): {missing[:8]}")
    for doc in (score_doc, path_doc, flow_doc, conflict_doc):
        if doc:
            scrub_decoys(doc, queries.DECOY_ALIASES)
    assert_no_decoys({"q_score": score_doc, "q_path": path_doc, "q_flow": flow_doc, "q_conflict": conflict_doc})
    # SQL baseline
    answers = {"Q-SCORE": score_ctx["tier_a_ids"], "Q-PATH": path_ctx["target_ids"],
               "Q-FLOW": [r["org_id"] for r in flow_doc["intermediaries"] if r["betweenness_rank"] <= 5]}
    if conflict_doc:
        answers["Q-CONFLICT"] = sorted(e["company_id"] for e in conflict_doc["exposures"] if e["kind"] == "conflict")
    sql_doc = build_sql_baseline(cx, answers, naive_dir)
    # meta
    ver, engine = engine_and_version(core)
    PE, Co = core.PipelineEntry, core.Company
    ET = live.C("EligibleTarget")
    act_order = [QIDS[n] for n in hero if n in QIDS and n != "q_addon"]
    sponsor = live.scalar(live.C("OurSponsor").name)
    meta = {"schema_version": "1", "source": "RAI",
            "generated_at": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
            "as_of_date": cx.as_of, "customer_display_name": sponsor or core.OUR_SPONSOR_NAME,
            "fund_name": cx.fund_name[live.ids(live.C("BuyingFund"))[0]],
            "relationalai_version": ver, "engine": engine,
            "counts": {"pipeline_companies": count_of(live, PE), "market_companies": count_of(live, ET)},
            "act_order": act_order}
    files = {"meta": meta, "rules": {"rules": rules}, "graph": graph_doc, "q_score": score_doc, "q_path": path_doc,
             "q_flow": flow_doc, "sql_baseline": sql_doc}
    if conflict_doc:
        files["q_conflict"] = conflict_doc
    # atomic write: temp dir, validate, rename
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for name, doc in files.items():
        (tmp / f"{name}.json").write_text(dumps(doc), encoding="utf-8")
    errs = check_contract(tmp)
    if errs:
        print(f"export: the generated files violate the contract ({len(errs)}); left in {tmp}", file=sys.stderr)
        for e in errs[:50]:
            print(f"  - {e}", file=sys.stderr)
        return 2
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    print(f"export: wrote {len(files)} files to {out} in {time.time() - t0:.0f}s "
          f"({graph_doc['stats']['num_nodes']} graph nodes, {graph_doc['stats']['num_edges']} edges, "
          f"{len(WARNINGS)} warning(s))")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write exports/*.json from live RAI queries (R13).")
    ap.add_argument("--out", type=Path, default=ROOT / "exports")
    ap.add_argument("--naive-sql-dir", type=Path, default=NAIVE_DIR)
    ap.add_argument("--subgraph-target", type=int, default=SUBGRAPH_TARGET)
    ap.add_argument("--check-contract", nargs="?", const=ROOT / "exports", type=Path, metavar="DIR",
                    help="validate an exports directory against the R15 contract and exit")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"),
                    help="byte-compare two export directories, ignoring meta.generated_at")
    a = ap.parse_args(argv)
    if a.check_contract is not None:
        return run_check_contract(a.check_contract)
    if a.compare:
        return run_compare(*a.compare)
    try:
        return run_export(a.out, a.naive_sql_dir, a.subgraph_target)
    except ExportError as exc:
        print(f"export: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
