"""Run the prebuilt hero queries from pe_deal_graph/queries.py and print the result.

Owner: R14 Demo Workspace. Used by the presenter's Claude Code session, `make warm`,
`make keepalive` and rehearsal. Run from demo_workspace/ (or anywhere):

    uv run python ask.py --list                 # hero functions and the business question each answers
    uv run python ask.py q_score                # run one function live, print its rows (incl. the `why` column)
    uv run python ask.py --from-exports q_score # NO ENGINE: print the precomputed rows from exports/q_score.json
    uv run python ask.py --check                # static check of the query interface contract (no engine)
    uv run python ask.py --warm                 # run every hero function, with timings and a golden name check
    uv run python ask.py --keepalive [MIN]      # one cheap query every MIN minutes (default 10) until Ctrl-C

Warm query server (RUNBOOK.md, "Latency"). The first query in a new Python process pays 45-75 s of
model compile and engine setup, even on a warm engine. `make warm` therefore starts one long-lived
local process that keeps the model compiled:

    python ask.py --serve-start    # start it in the background (make warm does this), wait until it listens
    python ask.py --serve-status   # is it running, and for which checkout
    python ask.py --serve-stop     # stop it (after the demo)
    python ask.py serve            # run it in the foreground (debugging)

`ask.py <function>`, `--warm` and `--keepalive` use the server when it is running for this checkout
and its code is current; otherwise they run in-process exactly as before. The server listens on
127.0.0.1 only and accepts a request only with the random token in its state file
(demo_workspace/scratch/.ask_server/, gitignored, mode 0600).

Query interface contract (RUNBOOK.md, "Query interface contract"):
  - pe_deal_graph/queries.py defines zero-argument functions; the docstring's first line is the
    business question.
  - Each returns a pandas DataFrame (or a dict of name -> DataFrame for multi-part answers),
    deterministically ordered, with a `why` column carrying the evidence for every row.
  - HERO_QUERIES (tuple of function names, in demo order) lists what `--warm` runs.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QUERIES = REPO / "pe_deal_graph" / "queries.py"
VENV_PY = REPO / ".venv" / "bin" / "python"
EXPORTS = REPO / "exports"
GOLDEN = REPO / "data" / "golden" / "expected.json"
SERVER_DIR = REPO / "demo_workspace" / "scratch" / ".ask_server"
SERVER_STATE = SERVER_DIR / "state.json"
SERVER_LOG = SERVER_DIR / "server.log"

# Required by the contract (QUESTIONS.md v2: q_conflict is Act 4, q_addon is an optional backup).
REQUIRED = ("q_score", "q_path", "q_flow", "q_conflict", "finale_rescore")
ACT3_CHOICES = ()
OPTIONAL = ("q_addon", "q_compete")
DEFAULT_ORDER = ("q_score", "q_path", "q_flow", "q_conflict", "finale_rescore", "q_addon")
GOLDEN_QID = {"q_score": "Q-SCORE", "q_path": "Q-PATH", "q_flow": "Q-FLOW", "q_conflict": "Q-CONFLICT",
              "finale_rescore": "FINALE", "q_addon": "Q-ADDON"}
MAX_PRINT_ROWS = 40
KEEPALIVE_DEFAULT_MIN = 10
ENGINE_NAME = "pe_demo_logic"


def fail(msg: str, code: int = 2) -> None:
    print(f"ask.py: {msg}", file=sys.stderr)
    sys.exit(code)


def ensure_venv() -> None:
    """Re-exec under the repo venv if started with another interpreter (e.g. system python 3.9)."""
    if Path(sys.prefix).resolve() == (REPO / ".venv").resolve():
        return
    if not VENV_PY.exists():
        fail("repo venv missing. From the repo root run: uv sync  (see RUNBOOK.md step 2)")
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])


def static_functions() -> dict[str, str]:
    """Top-level zero-argument functions in queries.py -> first docstring line, without importing."""
    if not QUERIES.exists():
        fail(
            "pe_deal_graph/queries.py does not exist yet (owner R11). "
            "The hero queries have not landed, so there is nothing to run or warm.",
        )
    tree = ast.parse(QUERIES.read_text(), filename=str(QUERIES))
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            a = node.args
            if a.args or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg:
                continue
            doc = (ast.get_docstring(node) or "").strip().splitlines()
            out[node.name] = doc[0] if doc else ""
    return out


def static_constant(name: str, default):
    """A literal module-level constant from queries.py (e.g. DECOY_ALIASES), without importing it."""
    try:
        tree = ast.parse(QUERIES.read_text(), filename=str(QUERIES))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return ast.literal_eval(node.value)
    except Exception:
        pass
    return default


def check_contract() -> list[str]:
    funcs = static_functions()
    missing = [n for n in REQUIRED if n not in funcs]
    if ACT3_CHOICES and not any(n in funcs for n in ACT3_CHOICES):
        missing.append(" or ".join(ACT3_CHOICES))
    if missing:
        fail(
            "pe_deal_graph/queries.py does not meet the query interface contract yet; "
            f"missing zero-argument function(s): {', '.join(missing)}. "
            "See RUNBOOK.md, section 'Query interface contract'.",
        )
    undocumented = [n for n in funcs if n in REQUIRED + ACT3_CHOICES + OPTIONAL and not funcs[n]]
    if undocumented:
        fail(f"contract functions without a business-question docstring: {', '.join(undocumented)}")
    return [n for n in DEFAULT_ORDER if n in funcs]


def load_queries():
    os.chdir(REPO)  # raiconfig.yaml and relative data paths resolve from the repo root
    sys.path.insert(0, str(REPO))
    try:
        import pe_deal_graph.queries as q  # noqa: PLC0415
    except Exception as exc:  # show one line, not a stack trace, on stage
        fail(f"could not import pe_deal_graph.queries: {type(exc).__name__}: {exc}")
    return q


def show(name: str, result) -> int:
    import pandas as pd  # noqa: PLC0415

    parts = result if isinstance(result, dict) else {name: result}
    rows = 0
    for label, df in parts.items():
        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame(df)
        rows += len(df)
        print(f"## {label}  ({len(df)} rows)")
        with pd.option_context("display.max_colwidth", 200, "display.width", 250):
            print(df.head(MAX_PRINT_ROWS).to_string(index=False))
        if len(df) > MAX_PRINT_ROWS:
            print(f"... {len(df) - MAX_PRINT_ROWS} more rows not shown")
        print()
    return rows


RETRY_WAIT_S = 20.0
FALLBACK_NOTICE = "Live query unavailable, showing precomputed result from exports"


def _transient(exc: Exception) -> bool:
    """Contention failures worth one retry: a missing graph output, an empty frame, an engine lock or a 503."""
    if type(exc).__name__ == "GraphOutputMissing" or isinstance(exc, KeyError):
        return True
    text = str(exc).lower()
    return any(t in text for t in ("503", "lock", "suspending", "service unavailable"))


class LiveUnavailable(Exception):
    pass


def run_one(q, name: str, fallback: bool = False):
    fn = getattr(q, name, None)
    if fn is None or not callable(fn):
        fail(f"pe_deal_graph.queries has no function {name!r}. Try: uv run python ask.py --list")
    import io  # noqa: PLC0415

    t0 = time.perf_counter()
    last = None
    for attempt in (1, 2):
        progress = io.StringIO()  # RAI per-query progress lines are noise on stage; the table is the answer
        try:
            with contextlib.redirect_stdout(progress), contextlib.redirect_stderr(progress):
                result = fn()
            return result, time.perf_counter() - t0
        except Exception as exc:
            last = exc
            if not _transient(exc):
                break
            if attempt == 1:
                print(f"ask.py: {name}() hit {type(exc).__name__}; retrying once in {RETRY_WAIT_S:.0f} s.", file=sys.stderr)
                time.sleep(RETRY_WAIT_S)
    if fallback and _transient(last):
        raise LiveUnavailable(str(last))
    fail(f"{name}() failed after {time.perf_counter() - t0:.1f}s: {type(last).__name__}: {last}. "
         f"Engine or network down? Precomputed fallback: uv run python ask.py --from-exports {name}", 3)


def answer(q, name: str, where: str = "") -> None:
    """Run one hero function and print it (the live path; shared by in-process and server)."""
    try:
        result, secs = run_one(q, name, fallback=True)
    except LiveUnavailable:
        if name not in FROM_EXPORTS:
            fail(f"{name}() live query unavailable and it has no precomputed export.", 3)
        if not (EXPORTS / "meta.json").exists():
            fail(f"Live query unavailable and no precomputed exports found at {EXPORTS}/. Run `make export` with "
                 "the engine up, or use the Deal Graph Explorer (artifacts/deal_graph_explorer.html).", 3)
        print(FALLBACK_NOTICE)
        from_exports(name, EXPORTS)
        return
    doc = ((getattr(q, name).__doc__ or "").strip().splitlines() or [""])[0]
    if doc:
        print(f"# {name}: {doc}\n")
    show(name, result)
    print(f"(ran in {secs:.1f}s{where})")


# ------------------------------------------------------------------------------------------------
# Golden name check for --warm (data/golden/expected.json rehearsal lists; never loaded to Snowflake)
# ------------------------------------------------------------------------------------------------
def golden_lists() -> dict[str, tuple[list[str], list[str]]]:
    try:
        qs = json.loads(GOLDEN.read_text())["questions"]
    except Exception:
        return {}
    out = {}
    for qid, spec in qs.items():
        reh = spec.get("rehearsal") or {}
        # entries may carry a note, e.g. "Tessmark Clinical Supply (as flagged)": check the name only
        clean = [re.sub(r"\s*\([^)]*\)$", "", str(n)).strip() for n in reh.get("must_appear") or []]
        out[qid] = (clean, list(reh.get("must_not_appear") or []))
    return out


def name_check(name: str, text: str, gold: dict) -> str:
    """'' when the printed answer has every golden name and no decoy, else a one-line problem."""
    must, must_not = gold.get(GOLDEN_QID.get(name, ""), ([], []))
    missing = [n for n in must if n not in text]
    decoys = [n for n in must_not if n in text]
    probs = []
    if missing:
        probs.append("missing " + ", ".join(missing))
    if decoys:
        probs.append("decoy shown " + ", ".join(decoys))
    return "; ".join(probs)


def warm_pass(q, names: list[str], label: str, gold: dict) -> list[str]:
    import io  # noqa: PLC0415

    problems = []
    for n in names:
        buf = io.StringIO()
        result, secs = run_one(q, n)
        with contextlib.redirect_stdout(buf):
            nrows = show(n, result)
        bad = name_check(n, buf.getvalue(), gold)
        status = "names OK" if not bad else f"NAME CHECK FAILED: {bad}"
        print(f"{label} {n}: {nrows} rows in {secs:.1f}s, {status}", flush=True)
        if bad:
            problems.append(f"{n}: {bad}")
    return problems


def warm(q, two_pass: bool) -> int:
    names = list(getattr(q, "HERO_QUERIES", check_contract()))
    gold = golden_lists()
    total = time.perf_counter()
    problems = warm_pass(q, names, "warm", gold)
    if two_pass:
        print("second pass, same process (this is the latency each live act will see):", flush=True)
        problems += warm_pass(q, names, "ready", gold)
    print(f"warm done: {len(names)} queries in {time.perf_counter() - total:.1f}s", flush=True)
    if problems:
        problems = list(dict.fromkeys(problems))
        print("ask.py: warm FAILED the golden name check (data/golden/expected.json): " + " | ".join(problems),
              file=sys.stderr)
        return 4
    return 0


def ping(q) -> float:
    """One cheap engine query (entity count), so the engine's idle timer restarts."""
    from relationalai.semantics.std import aggregates as aggs  # noqa: PLC0415
    from pe_deal_graph.model.core import Company, model  # noqa: PLC0415

    import io  # noqa: PLC0415

    t0 = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        model.select(aggs.count(Company).alias("n")).to_df()
    return time.perf_counter() - t0


# ------------------------------------------------------------------------------------------------
# --from-exports: the engine-free fallback (same rows, read from exports/*.json written by R13)
# ------------------------------------------------------------------------------------------------
def _scrub(df, aliases: dict):
    """Same rule as queries._scrub: decoy names in `why` text become their role descriptor."""
    if "why" in df.columns and aliases:
        out = []
        for v in df["why"]:
            if isinstance(v, str):
                for name, alias in aliases.items():
                    v = v.replace(name, alias)
            out.append(v)
        df["why"] = out
    return df


def _money(x) -> str:
    return f"${x:,.1f}M" if not float(x).is_integer() else f"${x:,.0f}M"


def _exp_score(d: dict, meta: dict):
    import pandas as pd  # noqa: PLC0415

    rows = [r for r in d["rows"] if r.get("tier") == "A"]
    out = []
    for r in rows:
        comps = "; ".join(f"{c['id']} {c['points']}" for c in r.get("components", []) if c.get("points"))
        why = f"Fit {r['fit']} + Readiness {r['readiness']} + Access {r['access']} = {r['score']}: {r.get('why', '')}"
        if not r.get("in_crm", True):
            why += "; no coverage: no pipeline row and no CRM touch on the company or its people"
        out.append({"rank": r["rank"], "name": r["name"], "score": r["score"], "fit": r["fit"],
                    "readiness": r["readiness"], "access": r["access"], "tier": r["tier"],
                    "in_crm": r.get("in_crm"), "components": comps, "why": why, "company_id": r["company_id"]})
    return pd.DataFrame(out)


def _exp_path(d: dict, meta: dict):
    import pandas as pd  # noqa: PLC0415

    max_hops = d.get("max_hops", 3)
    out = []
    for t in sorted(d["targets"], key=lambda t: (t["score_rank"], t["company_name"])):
        dms = sorted(t["decision_makers"], key=lambda m: ({"CEO": 0, "OWNER_DESIGNEE": 1}.get(m["kind"], 2), m["name"]))
        for m in dms:
            if m.get("paths"):
                for p in sorted(m["paths"], key=lambda p: p["rank"]):
                    hops = p.get("hops", [])
                    names = [hops[0]["from_name"]] + [h["to_name"] for h in hops] if hops else []
                    hop_txt = "; ".join(f"{h['from_name']} - {h['to_name']}: {h['evidence']} (tie {h['strength']:.2f})"
                                        for h in hops)
                    label = "best path" if p["rank"] == 1 else f"alternate {p['rank']}"
                    out.append({"target_rank": t["score_rank"], "target": t["company_name"],
                                "decision_maker": m["name"], "role": m["kind"], "status": "warm",
                                "path_rank": p["rank"], "hops": p["length"], "strength": round(p["strength"], 3),
                                "path": " > ".join(names),
                                "why": f"{label}, {p['length']} hops, strength {p['strength']:.3f} (product of hop "
                                       f"ties): {hop_txt}",
                                "company_id": t["company_id"], "person_id": m["person_id"]})
            else:
                who = (f"{t.get('owner_name') or 'the owner'}'s board designee {m['name']}"
                       if m["kind"] == "OWNER_DESIGNEE" else f"CEO {m['name']}")
                why = (f"Cold: no path within {max_hops} hops from any Northwind deal-team member or "
                       f"operating partner to {who}")
                if m.get("hops") is not None:
                    why += f" (nearest is {m['hops']} hops away)"
                ci = t.get("closest_intermediary")
                if t.get("status") == "cold" and ci:
                    why += f". Closest intermediary: {ci['name']}" + (f" ({ci['evidence']})" if ci.get("evidence") else "")
                out.append({"target_rank": t["score_rank"], "target": t["company_name"], "decision_maker": m["name"],
                            "role": m["kind"], "status": "cold", "path_rank": None, "hops": m.get("hops"),
                            "strength": None, "path": "", "why": why, "company_id": t["company_id"],
                            "person_id": m["person_id"]})
    df = pd.DataFrame(out)
    for c in ("path_rank", "hops"):
        if c in df.columns:
            df[c] = df[c].astype("Int64")
    return df


def _exp_flow(d: dict, meta: dict):
    import pandas as pd  # noqa: PLC0415

    n_int = d.get("graph_stats", {}).get("num_intermediaries", len(d["intermediaries"]))
    th = d.get("thresholds", {})
    out = []
    for i in sorted(d["intermediaries"], key=lambda i: (i["betweenness_rank"], i["name"]))[:5]:
        t = i.get("touchpoints_24m") or 0
        why = (f"bridge rank {i['betweenness_rank']} of {n_int} intermediaries by betweenness "
               f"(betweenness {i['betweenness']:,.1f}: summed share of shortest connections between pairs of firms that pass through it); advised "
               f"{i.get('deals_in_window') or 0} thesis-sector deals in 5 years; {t} CRM touchpoint"
               f"{'s' if t != 1 else ''} with us in 24 months")
        if i.get("is_gap"):
            why += (f"; COVERAGE GAP: top-decile bridge (rank <= {th.get('top_decile_cutoff_rank')}) with touchpoints "
                    f"at or below the bottom quartile ({th.get('q1_touchpoints')})")
        out.append({"rank": i["betweenness_rank"], "name": i["name"], "betweenness": round(i["betweenness"], 4),
                    "thesis_deals": i.get("deals_in_window"), "our_touchpoints": t, "coverage_gap": bool(i.get("is_gap")),
                    "pagerank": i.get("pagerank"), "why": why, "intermediary_id": i["org_id"]})
    return pd.DataFrame(out)


def _exp_conflict(d: dict, meta: dict):
    import pandas as pd  # noqa: PLC0415

    subj = d["subject"]["name"]
    ex = []
    for e in sorted(d.get("exposures", []), key=lambda e: (e["distance"], e["name"])):
        dist = e["distance"]
        why = (f"{e['evidence']}; {e['name']} is held by {e['fund_name']}"
               + (f" since {e['since']}" if e.get("since") else "")
               + f"; {dist} commercial link{'s' if dist != 1 else ''} away")
        ex.append({"target": subj, "name": e["name"], "fund": e["fund_name"], "since": e.get("since", ""),
                   "distance": dist, "verdict": e.get("kind_label") or e.get("kind"), "why": why,
                   "company_id": e["company_id"]})
    k = d["concentration"]
    held: dict[str, list] = {}
    for h in sorted(k.get("holdings", []), key=lambda h: (h["area"], -h["equity_musd"], h["name"])):
        held.setdefault(h["area"], []).append(h)
    conc = []
    for a in sorted(k["areas"], key=lambda a: (-a["after_pct"], a["name"])):
        hs = held.get(a["name"], [])
        if hs:
            why = ("Fund IV holds " + ", ".join(f"{h['name']} ({_money(h['equity_musd'])})" for h in hs)
                   + f": {_money(a['before_musd'])} = {a['before_pct']:.1f}% of the fund")
        else:
            why = f"Fund IV has no current holding in this area: {_money(a['before_musd'])} = {a['before_pct']:.1f}% of the fund"
        if a["after_musd"] > a["before_musd"] + 1e-9:
            why += (f"; with the {_money(k['check_musd'])} {subj} check: {_money(a['after_musd'])} = "
                    f"{a['after_pct']:.1f}%")
        if a.get("breach"):
            why += (f"; over the {k['guideline_pct']:.0f}% guideline by {_money(k['over_by_musd'])} "
                    f"(headroom {_money(k['headroom_musd'])})")
        else:
            why += f"; within the {k['guideline_pct']:.0f}% guideline"
        subject_area = a.get("is_subject_area")
        conc.append({"target": subj, "area": a["name"], "current_musd": round(a["before_musd"], 2),
                     "current_pct": round(a["before_pct"], 2), "pro_forma_musd": round(a["after_musd"], 2),
                     "pro_forma_pct": round(a["after_pct"], 2), "guideline_pct": k["guideline_pct"],
                     "headroom_musd": k["headroom_musd"] if subject_area else None,
                     "over_by_musd": k["over_by_musd"] if subject_area else None,
                     "breach": bool(a.get("breach")), "why": why})
    return {"exposures": pd.DataFrame(ex), "concentration": pd.DataFrame(conc)}


def _exp_finale(d: dict, meta: dict):
    import pandas as pd  # noqa: PLC0415

    a_min = d.get("tier_thresholds", {}).get("A", 70)
    on = [r for r in d["finale"]["rows"] if not r.get("conflict") and r.get("tier") == "A"]
    off = [r for r in d["finale"]["rows"] if r.get("conflict") and (r.get("score") or 0) >= a_min]
    act1_why = {r["company_id"]: r.get("why", "") for r in d.get("rows", [])}
    out = []
    for r in sorted(on, key=lambda r: r["rank"]) + sorted(off, key=lambda r: (-r["score"], r["name"])):
        added = [c for c in r.get("added_components", []) if c.get("evidence")]
        flagged = bool(r.get("conflict"))
        # the exporter stores the full finale evidence (Act-1 why plus the new points) on the added component
        evidence = added[0]["evidence"] if added else act1_why.get(r["company_id"], "")
        why = f"Act 1 score {r['prev_score']} + finale points {r['delta']} = {r['score']}: {evidence}"
        if flagged:
            why += f"; Conflict - cross-fund review: {r['conflict'].get('reason', '')}"
        out.append({"rank": None if flagged else r["rank"], "name": r["name"], "score": r["score"],
                    "change": r["delta"], "act1_score": r["prev_score"], "act1_rank": r["prev_rank"],
                    "act1_tier": r["prev_tier"], "flag": "Conflict - cross-fund review" if flagged else "",
                    "on_tier_a": not flagged, "why": why, "company_id": r["company_id"]})
    df = pd.DataFrame(out)
    if "rank" in df.columns:
        df["rank"] = df["rank"].astype("Int64")
    return df


def _exp_addon(d: dict, meta: dict):
    import pandas as pd  # noqa: PLC0415

    plat = (d.get("platform") or {}).get("name", "")
    out = [{"rank": c["rank"], "name": c["name"], "similarity": c["similarity"], "platform": plat,
            "why": c.get("evidence") or f"Jaccard {c['similarity']:.4f} with {plat} over shared customers and suppliers",
            "company_id": c["company_id"]}
           for c in sorted(d.get("candidates", []), key=lambda c: c["rank"])[:3]]
    return pd.DataFrame(out)


FROM_EXPORTS = {  # function -> (export file, builder)
    "q_score": ("q_score.json", _exp_score),
    "q_path": ("q_path.json", _exp_path),
    "q_flow": ("q_flow.json", _exp_flow),
    "q_conflict": ("q_conflict.json", _exp_conflict),
    "finale_rescore": ("q_score.json", _exp_finale),
    "q_addon": ("q_addon.json", _exp_addon),
}


def from_exports(name: str, exports: Path) -> None:
    if name not in FROM_EXPORTS:
        fail(f"--from-exports supports {', '.join(FROM_EXPORTS)}; got {name!r}")
    fname, build = FROM_EXPORTS[name]
    path, meta_path = exports / fname, exports / "meta.json"
    if not meta_path.exists():
        fail(f"no precomputed exports at {exports}/ (meta.json missing). Run `make export` with the engine up, "
             "or switch to the Deal Graph Explorer (artifacts/deal_graph_explorer.html).")
    if not path.exists():
        hint = " (Q-ADDON is a backup and may not be exported; use the explorer #addon tab)" if name == "q_addon" else ""
        fail(f"{path} is missing{hint}.")
    try:
        meta = json.loads(meta_path.read_text())
        data = json.loads(path.read_text())
        result = build(data, meta)
    except (KeyError, TypeError, ValueError) as exc:
        fail(f"could not read {path}: {type(exc).__name__}: {exc}. Switch to the explorer view for this act.")
    aliases = static_constant("DECOY_ALIASES", {})
    parts = result if isinstance(result, dict) else {name: result}
    for df in parts.values():
        _scrub(df, aliases)
    source = str(meta.get("source", "")).upper()
    print(f"# PRECOMPUTED, not a live query: {name} from the governed export generated at "
          f"{meta.get('generated_at', '?')} (engine {meta.get('engine', '?')}, data as of {meta.get('as_of_date', '?')}).")
    if source not in ("RAI", "LIVE"):
        print(f"# WARNING: export source is {source or 'UNLABELLED'}, not RAI. Do not present these rows.")
    q = static_functions().get(name, "") if QUERIES.exists() else ""
    if q:
        print(f"# {name}: {q}")
    print()
    show(name, result)
    print("(precomputed: same rules and rows as the live query when the export was generated; no engine was used)")


# ------------------------------------------------------------------------------------------------
# Warm query server: one long-lived process keeps the model compiled (localhost TCP, token, JSON lines)
# ------------------------------------------------------------------------------------------------
def fingerprint() -> str:
    """Changes when any model/query source or this file changes, so a stale server is never used."""
    h = hashlib.sha256()
    files = sorted((REPO / "pe_deal_graph").rglob("*.py")) + [Path(__file__).resolve()]
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f.relative_to(REPO)}:{st.st_mtime_ns}:{st.st_size};".encode())
    return h.hexdigest()[:16]


class _SockWriter:
    """File-like object that forwards print() output to the client as JSON lines."""

    def __init__(self, conn: socket.socket, stream: str):
        self.conn, self.stream = conn, stream

    def write(self, s: str) -> int:
        if s:
            try:
                self.conn.sendall((json.dumps({self.stream: s}) + "\n").encode())
            except OSError:
                pass
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:  # progress spinners check this; answer "not a terminal"
        return False

    def fileno(self) -> int:
        raise OSError("socket-backed stream has no file descriptor")

    encoding = "utf-8"
    errors = "replace"


def _send(conn: socket.socket, obj: dict) -> None:
    with contextlib.suppress(OSError):
        conn.sendall((json.dumps(obj) + "\n").encode())


def _read_state() -> dict | None:
    try:
        return json.loads(SERVER_STATE.read_text())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def serve() -> None:
    """Foreground server. Import the model once, then answer requests one at a time until stopped."""
    ensure_venv()
    check_contract()
    t0 = time.perf_counter()
    q = load_queries()
    print(f"[{datetime.now():%H:%M:%S}] ask server: model imported in {time.perf_counter() - t0:.1f}s", flush=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    token = secrets.token_hex(16)
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SERVER_DIR, 0o700)
    state = {"pid": os.getpid(), "port": srv.getsockname()[1], "token": token, "repo": str(REPO),
             "fingerprint": fingerprint(), "started_at": datetime.now().isoformat(timespec="seconds")}
    tmp = SERVER_STATE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, SERVER_STATE)
    print(f"[{datetime.now():%H:%M:%S}] ask server: listening on 127.0.0.1:{state['port']} (pid {state['pid']})",
          flush=True)

    def _cleanup(*_):
        st = _read_state()
        if st and st.get("pid") == os.getpid():
            with contextlib.suppress(OSError):
                SERVER_STATE.unlink()
        print(f"[{datetime.now():%H:%M:%S}] ask server: stopped", flush=True)
        os._exit(0)  # not sys.exit: a SystemExit raised inside a request would be caught and ignored

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    allowed = set(static_functions())
    while True:
        conn, _ = srv.accept()
        with conn:
            try:
                conn.settimeout(10)
                req = json.loads(conn.makefile("r").readline() or "{}")
                conn.settimeout(None)
            except (OSError, ValueError):
                continue
            if not secrets.compare_digest(str(req.get("token", "")), token):
                _send(conn, {"done": True, "code": 2, "err": "bad token"})
                continue
            op, fn = req.get("op"), req.get("fn", "")
            started = time.perf_counter()
            print(f"[{datetime.now():%H:%M:%S}] request {op} {fn}".rstrip(), flush=True)
            code = 0
            out, err = _SockWriter(conn, "out"), _SockWriter(conn, "err")
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    if op == "status":
                        print(json.dumps(state | {"token": "***"}))
                    elif op == "run" and fn in allowed:
                        answer(q, fn, " on the warm query server")
                    elif op == "warm":
                        code = warm(q, two_pass=True)
                    elif op == "ping":
                        print(f"ping_ok {ping(q):.1f}")
                    elif op == "stop":
                        print("stopping")
                    else:
                        print(f"ask.py: unknown request {op} {fn}", file=sys.stderr)
                        code = 2
            except SystemExit as exc:  # fail() inside a request: report it, keep serving
                code = exc.code if isinstance(exc.code, int) else 1
            except Exception as exc:  # never die on a bad request
                print(f"ask.py: server error: {type(exc).__name__}: {exc}", file=err)
                code = 3
            _send(conn, {"done": True, "code": code})
            print(f"[{datetime.now():%H:%M:%S}] done {op} {fn} code {code} in {time.perf_counter() - started:.1f}s",
                  flush=True)
            if op == "stop":
                _cleanup()


def server_request(op: str, fn: str = "", quiet_if_absent: bool = True, connect_timeout: float = 3.0) -> int | None:
    """Send one request to this checkout's warm server and stream its output.

    Returns the exit code, or None when no usable server exists (the caller then runs in-process)."""
    st = _read_state()
    if not st:
        return None
    reason = ""
    if st.get("repo") != str(REPO):
        reason = "it belongs to another checkout"
    elif not _pid_alive(st.get("pid")):
        reason = "its process is gone"
    elif st.get("fingerprint") != fingerprint():
        reason = "the model or query code changed after it started (restart it: make warm)"
    if reason:
        if not quiet_if_absent:
            print(f"ask.py: not using the warm query server: {reason}; running in-process.", file=sys.stderr)
        return None
    try:
        conn = socket.create_connection(("127.0.0.1", int(st["port"])), timeout=connect_timeout)
    except (OSError, ValueError, KeyError):
        if not quiet_if_absent:
            print("ask.py: warm query server not reachable; running in-process.", file=sys.stderr)
        return None
    with conn:
        conn.settimeout(None)
        conn.sendall((json.dumps({"token": st.get("token"), "op": op, "fn": fn}) + "\n").encode())
        for line in conn.makefile("r"):
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "out" in msg:
                sys.stdout.write(msg["out"])
                sys.stdout.flush()
            if "err" in msg:
                sys.stderr.write(msg["err"])
                sys.stderr.flush()
            if msg.get("done"):
                return int(msg.get("code", 0))
    print("ask.py: warm query server closed the connection mid-answer; running in-process.", file=sys.stderr)
    return None


def serve_status() -> int:
    code = server_request("status", quiet_if_absent=False)
    if code is None:
        print("query server: not running for this checkout (live acts run in-process; first query 45-75 s)")
        return 1
    return code


def serve_stop() -> int:
    st = _read_state()
    if not st:
        print("query server: not running")
        return 0
    if st.get("repo") == str(REPO) and _pid_alive(st.get("pid")):
        with contextlib.suppress(OSError):
            os.kill(int(st["pid"]), signal.SIGTERM)
        for _ in range(50):
            if not _pid_alive(st.get("pid")):
                break
            time.sleep(0.1)
    with contextlib.suppress(OSError):
        SERVER_STATE.unlink()
    print(f"query server: stopped (pid {st.get('pid')})")
    return 0


def serve_start(wait_s: float = 120.0) -> int:
    """Start the server in the background unless a current one is already running; wait until it listens."""
    st = _read_state()
    if st and st.get("repo") == str(REPO) and _pid_alive(st.get("pid")):
        if st.get("fingerprint") == fingerprint() and server_request("status") == 0:
            print(f"query server: already running (pid {st['pid']}, since {st.get('started_at')})")
            return 0
        print("query server: restarting (code changed or not responding)")
        serve_stop()
    with contextlib.suppress(OSError):
        SERVER_STATE.unlink()
    if not VENV_PY.exists():
        fail("repo venv missing. From the repo root run: uv sync  (see RUNBOOK.md step 2)")
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SERVER_DIR, 0o700)
    log = open(SERVER_LOG, "a")  # noqa: SIM115 - handed to the child
    proc = subprocess.Popen([str(VENV_PY), str(Path(__file__).resolve()), "serve"], cwd=str(REPO),
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < wait_s:
        if proc.poll() is not None:
            print(f"query server: FAILED to start (exit {proc.returncode}); see {SERVER_LOG}", file=sys.stderr)
            return 1
        st = _read_state()
        if st and st.get("pid") == proc.pid:
            print(f"query server: started (pid {proc.pid}, 127.0.0.1:{st['port']}, log {SERVER_LOG.relative_to(REPO)})")
            return 0
        time.sleep(0.5)
    print(f"query server: did not come up within {wait_s:.0f}s; see {SERVER_LOG}", file=sys.stderr)
    return 1


def keepalive(minutes: float) -> None:
    """Ping the engine every `minutes` until Ctrl-C, through the warm server when it is up."""
    print(f"keepalive: one cheap query every {minutes:g} min so engine {ENGINE_NAME} does not auto-suspend "
          "(30 min idle). Ctrl-C to stop.", flush=True)
    import io  # noqa: PLC0415

    q = None
    try:
        while True:
            stamp = f"{datetime.now():%H:%M:%S}"
            secs, via, why = None, "warm query server", ""
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = server_request("ping")
            if code == 0:
                m = re.search(r"ping_ok ([\d.]+)", buf.getvalue())
                secs = float(m.group(1)) if m else None
                why = "" if m else "no ping result from the server"
            elif code is not None:  # the server is up but the query failed: report it, do not load a 2nd model
                lines = [ln for ln in buf.getvalue().strip().splitlines() if ln.strip()]
                why = lines[-1][:200] if lines else f"exit {code}"
            else:  # no server: ping from this process (the first ping pays the 45-75 s first-query cost)
                via = "this process"
                try:
                    if q is None:
                        q = load_queries()
                    secs = ping(q)
                except SystemExit:
                    why = "could not load the model"
                except Exception as exc:
                    why = f"{type(exc).__name__}: {str(exc)[:200]}"
            nxt = datetime.fromtimestamp(time.time() + minutes * 60)
            if secs is not None:
                print(f"[{stamp}] keepalive: engine awake, ping took {secs:.1f}s via {via}; next ping {nxt:%H:%M}",
                      flush=True)
            else:
                print(f"[{stamp}] keepalive: ping FAILED via {via} ({why}). Engine suspended, auth or network? "
                      f"Run make warm in another terminal. Next try {nxt:%H:%M}", flush=True)
            time.sleep(minutes * 60)
    except KeyboardInterrupt:
        print(f"\nkeepalive: stopped at {datetime.now():%H:%M:%S}. After the Q&A, suspend the engine "
              "(RUNBOOK.md, 'After the demo').")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "--check":
        names = check_contract()
        print("query interface contract OK: " + ", ".join(names))
        return
    if cmd == "--list":
        for n, doc in static_functions().items():
            print(f"{n}: {doc}")
        return
    if cmd == "--from-exports":
        args = argv[1:]
        exports = EXPORTS
        if "--exports" in args:
            i = args.index("--exports")
            if i + 1 >= len(args):
                fail("--exports needs a directory")
            exports = Path(args[i + 1]).expanduser().resolve()
            args = args[:i] + args[i + 2:]
        if len(args) != 1:
            fail("usage: uv run python ask.py --from-exports <function>   (e.g. q_score)")
        ensure_venv()  # pandas lives in the repo venv
        from_exports(args[0], exports)
        return
    if cmd == "serve":
        serve()
        return
    if cmd == "--serve-start":
        sys.exit(serve_start())
    if cmd == "--serve-stop":
        sys.exit(serve_stop())
    if cmd == "--serve-status":
        sys.exit(serve_status())
    if cmd == "--keepalive":
        try:
            minutes = float(argv[1]) if len(argv) > 1 else KEEPALIVE_DEFAULT_MIN
        except ValueError:
            fail("usage: ask.py --keepalive [MINUTES]")
        if not 1 <= minutes <= 25:
            fail("keepalive interval must be 1-25 minutes (the engine suspends after 30 idle minutes)")
        ensure_venv()
        keepalive(minutes)
        return
    if cmd == "--warm":
        check_contract()
        code = server_request("warm", quiet_if_absent=False)
        if code in (0, 4):  # 4 = golden name check failed; the answers ran, so do not re-run in-process
            sys.exit(code)
        if code is not None:
            print("ask.py: warm on the query server failed (above); restarting the server and retrying once.",
                  file=sys.stderr)
            serve_stop()
            if serve_start() == 0:
                code = server_request("warm", quiet_if_absent=False)
                if code is not None:
                    sys.exit(code)
        print("ask.py: no warm query server; warming in-process. The engine gets warm, but every live act will "
              "still pay the 45-75 s first-query cost.", file=sys.stderr)
        ensure_venv()
        sys.exit(warm(load_queries(), two_pass=False))
    if cmd not in static_functions():
        fail(f"pe_deal_graph/queries.py has no zero-argument function {cmd!r}. Try: uv run python ask.py --list")
    code = server_request("run", cmd)
    if code is not None:  # the server answered (or reported the failure with the fallback hint); no retry
        sys.exit(code)
    ensure_venv()
    answer(load_queries(), cmd)


if __name__ == "__main__":
    main(sys.argv[1:])
