"""Hero-question tests (owner: R11; G4 and G5 evidence).

Run:
    .venv/bin/python -m pytest tests/test_hero.py -v              # everything (engine + warehouse)
    .venv/bin/python -m pytest tests/test_hero.py -m warehouse    # naive SQL baselines only, no engine
    make test

What is asserted (PROMPT.md 5 R11, 6 G4/G5, 9.1-9.2):
- set equality on entity IDs against data/golden/expected.json, and ranking order where specified;
- must_not_contain decoys absent (by ID in the answer rows, and by name in every cell where the
  golden rehearsal list says the name must not appear);
- evidence (`why`) present and non-trivial in every row;
- identical output across two consecutive runs in the same session (the second round runs after
  finale_rescore(), so it also proves the finale leaves q_score() untouched);
- each naive SQL baseline in data/naive_sql/ returns its decoy(s).

Golden role keys map to IDs only through expected.json (never generate.py). The oracle
(data/oracle_output.json, R06) is used only by the triangulation tests that say so.
Every hero result of the session is written as canonical JSON to tests/out/hero_outputs.json
(previous run kept as hero_outputs.prev.json) so two pytest invocations can be diffed.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = json.loads((ROOT / "data" / "golden" / "expected.json").read_text())["questions"]
ORACLE_PATH = ROOT / "data" / "oracle_output.json"
OUT_DIR = Path(__file__).resolve().parent / "out"
DATE_RE = re.compile(r"\b(19|20)\d{2}(-\d{2})?")
HERO_ORDER = ("q_score", "q_path", "q_flow", "q_conflict", "finale_rescore")


def ids(items) -> list[str]:
    """Golden entries are {"key","id","name"} or {"key": {...}}; return their CSV ids."""
    out = []
    for it in items:
        k = it.get("key", it)
        out.append(k["id"] if isinstance(k, dict) else it["id"])
    return out


def gid(entry) -> str:
    k = entry.get("key", entry)
    return k["id"] if isinstance(k, dict) else entry["id"]


def gname(entry) -> str:
    k = entry.get("key", entry)
    return k["name"] if isinstance(k, dict) else entry["name"]


def frames(res) -> list[pd.DataFrame]:
    return list(res.values()) if isinstance(res, dict) else [res]


def all_text(res) -> str:
    return "\n".join(f.astype(str).to_csv(index=False) for f in frames(res))


def canonical(res):
    def one(df: pd.DataFrame):
        return {"columns": list(df.columns),
                "rows": json.loads(df.astype(object).where(pd.notna(df), None).to_json(orient="values"))}
    return {k: one(v) for k, v in res.items()} if isinstance(res, dict) else one(res)


def assert_why(df: pd.DataFrame, min_len: int = 25):
    assert "why" in df.columns, "every hero frame needs a `why` column"
    bad = [i for i, w in enumerate(df["why"]) if not isinstance(w, str) or len(w.strip()) < min_len]
    assert not bad, f"rows without evidence: {bad}"


# ------------------------------------------------------------------------------------------------
# fixtures
# ------------------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def queries():
    sys.path.insert(0, str(ROOT))
    import pe_deal_graph.queries as q  # noqa: PLC0415
    return q


@pytest.fixture(scope="session")
def hero_runs(queries):
    """Run HERO_QUERIES twice, in demo order; {name: [run1, run2]}."""
    assert tuple(queries.HERO_QUERIES) == HERO_ORDER
    runs: dict[str, list] = {n: [] for n in queries.HERO_QUERIES}
    for _ in range(2):
        for n in queries.HERO_QUERIES:
            runs[n].append(getattr(queries, n)())
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "hero_outputs.json"
    if out.exists():
        shutil.copyfile(out, OUT_DIR / "hero_outputs.prev.json")
    doc = {n: canonical(r[0]) for n, r in runs.items()}
    text = json.dumps(doc, indent=1, sort_keys=True, default=str)
    out.write_text(text)
    print(f"\nhero_outputs.json sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    return runs


@pytest.fixture(scope="session")
def hero(hero_runs):
    return {n: r[0] for n, r in hero_runs.items()}


@pytest.fixture(scope="session")
def oracle():
    if not ORACLE_PATH.exists():
        pytest.skip("data/oracle_output.json not produced yet (R06)")
    return json.loads(ORACLE_PATH.read_text())


@pytest.fixture(scope="session")
def naive():
    sys.path.insert(0, str(ROOT / "data" / "naive_sql"))
    import run_naive  # noqa: PLC0415
    con = run_naive.connect()
    cache: dict[str, pd.DataFrame] = {}

    def get(name: str) -> pd.DataFrame:
        if name not in cache:
            cache[name] = run_naive.run(name, con)
        return cache[name]

    yield get
    con.close()


# ------------------------------------------------------------------------------------------------
# contract and determinism
# ------------------------------------------------------------------------------------------------
@pytest.mark.engine
def test_hero_queries_tuple(queries):
    assert tuple(queries.HERO_QUERIES) == HERO_ORDER
    for n in HERO_ORDER:
        fn = getattr(queries, n)
        assert (fn.__doc__ or "").strip(), f"{n} needs a business-question docstring"


@pytest.mark.engine
@pytest.mark.parametrize("name", HERO_ORDER)
def test_deterministic_two_runs(hero_runs, name):
    a, b = hero_runs[name]
    assert canonical(a) == canonical(b), f"{name}() differs between two consecutive runs"


@pytest.mark.engine
@pytest.mark.parametrize("name", HERO_ORDER)
def test_evidence_every_row(hero, name):
    for f in frames(hero[name]):
        assert len(f) > 0
        assert "name" in f.columns or "target" in f.columns or "area" in f.columns
        assert_why(f)
        assert len(f) <= 10, "answer frames stay at 10 rows or fewer"


# ------------------------------------------------------------------------------------------------
# Q-SCORE (Act 1)
# ------------------------------------------------------------------------------------------------
G_SCORE = GOLDEN["Q-SCORE"]


@pytest.mark.engine
def test_score_tier_a_set_and_order(hero):
    df = hero["q_score"]
    want = [gid(e) for e in G_SCORE["tier_a_ranked"]]
    assert set(df["company_id"]) == set(want)
    assert list(df["company_id"]) == want, "ranking order (score, readiness, fit, name)"
    assert list(df["rank"]) == [e["rank"] for e in G_SCORE["tier_a_ranked"]]
    assert set(df["tier"]) == {"A"}


@pytest.mark.engine
def test_score_points_and_components(hero):
    df = hero["q_score"].set_index("company_id")
    for e in G_SCORE["tier_a_ranked"]:
        r = df.loc[gid(e)]
        assert (int(r.score), int(r.fit), int(r.readiness), int(r.access)) == (
            e["score"], e["fit"], e["readiness"], e["access"]), gname(e)
        got = {c.split()[0]: int(c.split()[1]) for c in r.components.split("; ") if c}
        assert got == e["components"], gname(e)


@pytest.mark.engine
def test_score_not_in_crm(hero):
    df = hero["q_score"]
    assert set(df.loc[~df["in_crm"].astype(bool), "company_id"]) == set(ids(G_SCORE["not_in_crm"]))


@pytest.mark.engine
def test_score_must_not_contain(hero):
    df = hero["q_score"]
    bad = set(ids(G_SCORE["must_not_contain"])) & set(df["company_id"])
    assert not bad, f"decoys in Tier A rows: {bad}"
    text = all_text(df)
    for n in G_SCORE["rehearsal"]["must_not_appear"]:
        assert n not in text, f"decoy name {n!r} appears in q_score() output"
    for n in G_SCORE["rehearsal"]["must_appear"]:
        assert n in set(df["name"])


@pytest.mark.engine
def test_score_why_has_components(hero):
    for r in hero["q_score"].itertuples(index=False):
        assert f"= {r.score}" in r.why and "+" in r.why and DATE_RE.search(r.why), r.name


# ------------------------------------------------------------------------------------------------
# Q-PATH (Act 2)
# ------------------------------------------------------------------------------------------------
G_PATH = GOLDEN["Q-PATH"]


@pytest.mark.engine
def test_path_decision_maker_rows(hero):
    df = hero["q_path"]
    want = {(gid(r["target"]), gid(r["decision_maker"]), r["kind"]) for r in G_PATH["rows"]}
    got = set(zip(df["company_id"], df["person_id"], df["role"]))
    assert got == want
    owner = [r for r in G_PATH["rows"] if r["kind"] == "OWNER_DESIGNEE"]
    assert {gid(r["decision_maker"]) for r in owner} <= set(df["person_id"]), "owner designee rows (Owen Lacey)"
    # target order follows Q-SCORE rank
    order = list(dict.fromkeys(df["company_id"]))
    assert order == list(dict.fromkeys(gid(r["target"]) for r in G_PATH["rows"]))


@pytest.mark.engine
def test_path_best_paths(hero):
    df = hero["q_path"]
    for g in G_PATH["rows"]:
        rows = df[(df["company_id"] == gid(g["target"])) & (df["person_id"] == gid(g["decision_maker"]))]
        if g.get("cold"):
            assert len(rows) == 1 and rows.iloc[0]["status"] == "cold", gname(g["decision_maker"])
            assert rows.iloc[0]["path"] == ""
            assert pd.isna(rows.iloc[0]["hops"]) or int(rows.iloc[0]["hops"]) > 3
            continue
        best = rows[rows["path_rank"] == 1]
        assert len(best) == 1, gname(g["decision_maker"])
        b = best.iloc[0]
        assert b["status"] == "warm" and int(b["hops"]) == g["hops"]
        assert b["path"].split(" > ") == [gname(p) for p in g["best_path"]]
        assert abs(float(b["strength"]) - g["path_strength"]) < 1e-3
        alts = rows[rows["path_rank"] > 1].sort_values("path_rank")
        assert len(alts) == len(g["alternates"]), f"alternates for {gname(g['target'])}"
        for a, ga in zip(alts.itertuples(index=False), g["alternates"]):
            assert int(a.path_rank) == ga["rank"]
            assert a.path.split(" > ") == [gname(p) for p in ga["path"]]
            assert abs(float(a.strength) - ga["path_strength"]) < 1e-3


@pytest.mark.engine
def test_path_hop_evidence_has_dates(hero):
    df = hero["q_path"]
    for r in df[df["status"] == "warm"].itertuples(index=False):
        hops = r.why.split(": ", 1)[1].split("; ")
        assert len(hops) >= int(r.hops), r.why
        assert DATE_RE.search(r.why), f"hop evidence without dates: {r.why}"


@pytest.mark.engine
def test_path_cold_target_closest_intermediary(hero):
    df = hero["q_path"]
    ci = G_PATH["closest_intermediary"]
    cold = df[df["company_id"] == gid(ci["target"])]
    assert set(cold["status"]) == {"cold"}
    assert all(gname(ci["intermediary"]) in w for w in cold["why"])
    # never offered for a target with a warm path
    warm_targets = set(df.loc[df["status"] == "warm", "company_id"])
    assert not any(gname(ci["intermediary"]) in w for w in df[df["company_id"].isin(warm_targets)]["why"])


@pytest.mark.engine
def test_path_must_not_contain(hero):
    df = hero["q_path"]
    text = all_text(df)
    for e in G_PATH["must_not_contain"]:
        assert gid(e) not in set(df["person_id"]) | set(df["company_id"])
        assert gname(e) not in text, f"decoy {gname(e)!r} appears in q_path() output"
    for n in G_PATH["rehearsal"]["must_appear"]:
        assert n in text, n
    # Walter Kim only in the second-ranked Bayside alternate
    wk = df[df["path"].str.contains("Walter Kim") | df["why"].str.contains("Walter Kim")]
    t_warm = next(gid(r["target"]) for r in G_PATH["rows"] if r.get("alternates"))
    assert set(zip(wk["company_id"], wk["path_rank"])) <= {(t_warm, 2)}


# ------------------------------------------------------------------------------------------------
# Q-FLOW (Act 3)
# ------------------------------------------------------------------------------------------------
G_FLOW = GOLDEN["Q-FLOW"]


@pytest.mark.engine
def test_flow_top5_by_betweenness(hero):
    df = hero["q_flow"]
    assert len(df) == 5, "betweenness top 5 only"
    assert list(df["rank"]) == [1, 2, 3, 4, 5]
    assert list(df["betweenness"]) == sorted(df["betweenness"], reverse=True)
    for e in G_FLOW["betweenness_rank_intermediaries"]:
        assert df.iloc[e["rank"] - 1]["intermediary_id"] == gid(e), gname(e)


@pytest.mark.engine
def test_flow_coverage_gap(hero):
    df = hero["q_flow"]
    gaps = set(df.loc[df["coverage_gap"].astype(bool), "intermediary_id"])
    assert gaps == set(ids(G_FLOW["coverage_gaps"]))
    assert not gaps & set(ids(G_FLOW["must_not_contain"]))


@pytest.mark.engine
def test_flow_touchpoints_and_deals(hero):
    df = hero["q_flow"].set_index("intermediary_id")
    keys = {e["key"]["key"]: gid(e) for e in G_FLOW["betweenness_rank_intermediaries"]}
    for k, tp in G_FLOW["touchpoints_24m"].items():
        if k in keys:
            assert int(df.loc[keys[k], "our_touchpoints"]) == tp, k
    assert int(df.loc[keys["HL"], "thesis_deals"]) == G_FLOW["hl_deals_in_window"]


@pytest.mark.engine
def test_flow_must_not_contain(hero):
    df = hero["q_flow"]
    text = all_text(df)
    for e in G_FLOW["tier1_must_not_appear"]:
        assert gid(e) not in set(df["intermediary_id"])
        assert gname(e) not in text, f"decoy {gname(e)!r} appears in q_flow() output"


# ------------------------------------------------------------------------------------------------
# Q-CONFLICT (Act 4)
# ------------------------------------------------------------------------------------------------
G_CONF = GOLDEN["Q-CONFLICT"]


@pytest.mark.engine
def test_conflict_exposures(hero):
    ex = hero["q_conflict"]["exposures"]
    assert set(ex["subject_id"]) == {gid(G_CONF["subject"])}
    want = {(gid(r), r["fund"]["name"], r["distance"], r["kind"]) for r in G_CONF["exposure_rows"]}
    got = set(zip(ex["company_id"], ex["fund"], ex["distance"].astype(int), ex["verdict"]))
    assert got == want
    assert list(ex["company_id"]) == [gid(r) for r in sorted(G_CONF["exposure_rows"], key=lambda r: r["row"])]
    two_hop = next(r for r in G_CONF["exposure_rows"] if r["distance"] == 2)
    row = ex[ex["company_id"] == gid(two_hop)].iloc[0]
    assert two_hop["via"]["name"] in row["why"], "two-link evidence names the middle company"


@pytest.mark.engine
def test_conflict_concentration(hero):
    cc = hero["q_conflict"]["concentration"].set_index("area")
    g = G_CONF["concentration"]
    assert set(cc.index) == set(g["areas"])
    for area, v in g["areas"].items():
        r = cc.loc[area]
        assert abs(float(r.current_pct) - v["before_pct"]) < 0.01, area
        assert abs(float(r.pro_forma_pct) - v["after_pct"]) < 0.01, area
        assert bool(r.breach) == bool(v.get("breach", False)), area
        assert abs(float(r.guideline_pct) - g["guideline_pct"]) < 1e-9
    breach = [a for a, v in g["areas"].items() if v.get("breach")][0]
    r = cc.loc[breach]
    assert abs(float(r.current_musd) - g["areas"][breach]["before_musd"]) < 0.01
    assert abs(float(r.pro_forma_musd) - g["areas"][breach]["after_musd"]) < 0.01
    assert abs(float(r.headroom_musd) - g["headroom_musd"]) < 0.01
    assert abs(float(r.over_by_musd) - g["over_by_musd"]) < 0.01
    holdings = [gname(h) for h in G_CONF["fund_iv_holdings"] if h["area"] == breach]
    assert all(h in r.why for h in holdings), "concentration evidence lists the holdings"


@pytest.mark.engine
def test_conflict_must_not_contain(hero):
    res = hero["q_conflict"]
    text = all_text(res)
    for e in G_CONF["must_not_contain"]:
        assert gid(e) not in set(res["exposures"]["company_id"])
        assert gname(e) not in text, f"decoy {gname(e)!r} appears in q_conflict() output"
    for n in G_CONF["rehearsal"]["must_appear"]:
        assert n in text, n


# ------------------------------------------------------------------------------------------------
# Finale
# ------------------------------------------------------------------------------------------------
G_FIN = GOLDEN["FINALE"]


@pytest.mark.engine
def test_finale_tier_a(hero):
    df = hero["finale_rescore"]
    tier_a = df[df["on_tier_a"].astype(bool)]
    want = [gid(e) for e in G_FIN["tier_a_ranked"]]
    assert list(tier_a["company_id"]) == want
    assert list(tier_a["rank"]) == [e["rank"] for e in G_FIN["tier_a_ranked"]]
    assert list(tier_a["score"]) == [e["score"] for e in G_FIN["tier_a_ranked"]]
    warm = set(ids(G_FIN["warm_path_set"]))
    for r in tier_a.itertuples(index=False):
        assert int(r.change) == (10 if r.company_id in warm else 0), r.name


@pytest.mark.engine
def test_finale_conflict_flag(hero):
    df = hero["finale_rescore"]
    flagged = df[~df["on_tier_a"].astype(bool)]
    want = {gid(c): c for c in G_FIN["conflicts"]}
    assert set(flagged["company_id"]) == set(want)
    for r in flagged.itertuples(index=False):
        assert r.flag == want[r.company_id]["flag"]
        assert int(r.score) == want[r.company_id]["score"], "a conflict keeps its score"
        assert pd.isna(r.rank)
        assert gname(want[r.company_id]["with"]) in r.why
    tier_a = set(df.loc[df["on_tier_a"].astype(bool), "company_id"])
    assert not tier_a & set(ids(G_FIN["must_not_contain"])), "conflicted target must be off the Tier A rows"
    # flagged rows come after the Tier A rows
    assert list(df["on_tier_a"]) == sorted(df["on_tier_a"], reverse=True)


@pytest.mark.engine
def test_finale_leaves_act1_untouched(hero_runs):
    a, b = hero_runs["q_score"]  # b ran after finale_rescore()
    assert canonical(a) == canonical(b)


# ------------------------------------------------------------------------------------------------
# Global decoy scan (R17 checks every Tier-1 transcript for every decoy name, and the presenter
# repeats the `why` column, so no hero output may name a decoy anywhere, in any column)
# ------------------------------------------------------------------------------------------------
DECOY_CAST_KEYS = ("D_VET", "D_SNF", "D_BIG", "D_SHORT", "D_SAME", "BRIGHT", "REDFERN", "MD_MER", "MERIDIAN",
                   "BIGBANK")
QMAP = {"Q-SCORE": "q_score", "Q-PATH": "q_path", "Q-FLOW": "q_flow", "Q-CONFLICT": "q_conflict",
        "FINALE": "finale_rescore"}


def _entities(o):
    """Every {"id", "name"} entity found anywhere in a golden subtree."""
    if isinstance(o, dict):
        if isinstance(o.get("id"), str) and isinstance(o.get("name"), str):
            yield o["id"], o["name"]
        for v in o.values():
            yield from _entities(v)
    elif isinstance(o, list):
        for v in o:
            yield from _entities(v)


def _required_names() -> dict[str, set[str]]:
    """name -> questions that require it (rehearsal must_appear or a golden answer entity)."""
    req: dict[str, set[str]] = {}
    for q, g in GOLDEN.items():
        for n in g.get("rehearsal", {}).get("must_appear", []):
            req.setdefault(re.sub(r"\s*\(.*\)$", "", n), set()).add(q)
        answer = {k: v for k, v in g.items()
                  if k in ("tier_a_ranked", "ranked", "rows", "betweenness_rank_intermediaries", "coverage_gaps",
                           "exposure_rows", "fund_iv_holdings", "conflicts", "warm_path_set", "subject")}
        for _, n in _entities(answer):
            req.setdefault(n, set()).add(q)
    return req


def decoy_set() -> tuple[dict[str, str], dict[str, str]]:
    """(global decoys name -> id, exempt name -> reason).

    Union of every must_not_contain, rehearsal must_not_appear and tier1_must_not_appear name across all
    questions, plus the decoy cast (persons and companies). A name some question requires as an answer
    (Tessmark, Cedar Row, Ashby Vale in the finale, Fernhollow in the Q-ADDON backup) is exempt from the
    global scan; it is still checked per question below."""
    cast = json.loads((ROOT / "data" / "golden" / "expected.json").read_text())["cast"]
    names: dict[str, str] = {}
    for g in GOLDEN.values():
        for k in ("must_not_contain", "tier1_must_not_appear"):
            for e in g.get(k, []):
                names[gname(e)] = gid(e)
        for n in g.get("rehearsal", {}).get("must_not_appear", []):
            names.setdefault(n, "")
    for k in DECOY_CAST_KEYS:
        names[cast[k]["name"]] = cast[k]["id"]
    req = _required_names()
    exempt = {n: "required by " + ", ".join(sorted(req[n])) for n in names if n in req}
    return {n: i for n, i in names.items() if n not in req}, exempt


def _cells(res):
    for label, f in (res.items() if isinstance(res, dict) else [("", res)]):
        for col in f.columns:
            for i, v in enumerate(f[col]):
                yield label, col, i, "" if v is None else str(v)


@pytest.mark.engine
def test_no_decoy_name_in_any_hero_output(hero, queries):
    """No decoy name or decoy id in any cell (why and evidence strings included) of any hero function,
    plus the Q-ADDON backup; per question, its own must_not_contain names are absent unless that same
    question requires the name (Cedar Row is Q-FLOW's top bridge, Tessmark is the flagged finale row)."""
    decoys, exempt = decoy_set()
    assert len(decoys) >= 10 and "Tom Harlowe" in decoys and "Cobbleton Dental Group" in decoys
    assert set(exempt) == {"Tessmark Clinical Supply", "Cedar Row Partners", "Ashby Vale Dental Partners",
                           "Fernhollow Environmental Labs"}, exempt
    results = dict(hero)
    results["q_addon"] = queries.q_addon()
    hits = []
    for fn, res in results.items():
        for label, col, i, text in _cells(res):
            for n, did in decoys.items():
                if n in text or (did and text == did):
                    hits.append(f"{fn}{'.' + label if label else ''}[{i}].{col}: {n}")
    # per question: its own must_not_contain names, unless the same question requires them
    req = _required_names()
    for q, fn in QMAP.items():
        text = all_text(hero[fn])
        for e in GOLDEN[q].get("must_not_contain", []):
            n = gname(e)
            if q in req.get(n, set()):
                continue
            if n in text:
                hits.append(f"{fn}: {q} must_not_contain {n}")
    # Fernhollow belongs to the Q-ADDON backup only
    for fn in HERO_ORDER:
        if "Fernhollow Environmental Labs" in all_text(hero[fn]):
            hits.append(f"{fn}: Fernhollow Environmental Labs (Q-ADDON answer) in a hero output")
    assert not hits, "decoy names in hero output:\n" + "\n".join(hits)


# ------------------------------------------------------------------------------------------------
# Triangulation against the independent oracle (R06), where the golden does not pin a value
# ------------------------------------------------------------------------------------------------
@pytest.mark.engine
def test_oracle_flow_top5(hero, oracle):
    top5 = oracle["Q-FLOW"]["answer"]["top5"]
    want = [x.get("id") or x.get("intermediary_id") or x.get("org_id") for x in top5]
    assert list(hero["q_flow"]["intermediary_id"]) == want


# ------------------------------------------------------------------------------------------------
# Naive SQL baselines (warehouse only; G5: every decoy is returned by its baseline)
# ------------------------------------------------------------------------------------------------
HERO_SQL = ("q_score", "q_path", "q_flow", "q_conflict")


@pytest.mark.warehouse
@pytest.mark.parametrize("name", HERO_SQL)
def test_naive_sql_export_columns(naive, name):
    df = naive(name)
    assert {"entity_id", "name", "metric"} <= set(df.columns), "R13 export convention"
    head = (ROOT / "data" / "naive_sql" / f"{name}.sql").read_text()
    assert "-- description:" in head and "-- metric_label:" in head


@pytest.mark.warehouse
def test_naive_score_returns_decoys(naive):
    """QUESTIONS.md v2 Q-SCORE decoy spec, as golden pins it: the screen's top three are exactly the three
    decoys (D_SHORT 5, D_VET 4, D_SNF 3 signals, distinct counts, so the order is fixed); every other cast
    row in cast_order_top8 is returned, after them and in golden's relative order; the Tier-A names the
    keyword list misses (Saltmarsh, Quarry) and the band near misses are absent. P5 noise rows with 2 or
    fewer signals may interleave among the 2-signal cast rows (ties break by name), so their positions
    are not asserted. The pinned noise rule is checked instead: no non-cast row has 3 or more signals."""
    df = naive("q_score").reset_index(drop=True)
    ns = G_SCORE["naive_screen"]
    got = list(df["entity_id"])
    decoys = [gid(e) for e in ns["cast_order_top8"] if e["key"] in ("D_SHORT", "D_VET", "D_SNF")]
    assert len(decoys) == 3
    assert got[:3] == decoys, "keyword screen top three are exactly the three decoys"
    cast = [gid(e) for e in ns["cast_order_top8"]]
    assert set(cast) <= set(got), f"cast rows missing from the screen: {sorted(set(cast) - set(got))}"
    assert [x for x in got if x in set(cast)] == cast, "cast rows keep golden's relative order"
    others = df[~df["entity_id"].isin(decoys)]
    assert int(others["metric"].max()) < int(df["metric"].iloc[2]), "no other row ties or beats a decoy"
    assert not (set(df.loc[~df["entity_id"].isin(cast), "entity_id"])
                & set(df.loc[df["metric"].astype(int) >= 3, "entity_id"])), "no non-cast row has 3+ signals"
    assert not set(ids(ns["missed_tier_a"])) & set(got), "screen misses Saltmarsh and Quarry"
    assert not set(ids(ns["excluded_by_band"])) & set(got), "band near misses are outside the screen"


@pytest.mark.warehouse
def test_naive_path_returns_false_intro(naive):
    df = naive("q_path")
    mnc = {e["key"]: e for e in G_PATH["must_not_contain"]}
    cold = next(r for r in G_PATH["rows"] if r["kind"] == "CEO" and r.get("cold"))
    assert len(df) == 1
    r = df.iloc[0]
    assert (r.entity_id, r.our_person, r.ceo, r.shared_employer) == (
        gid(cold["target"]), mnc["MD_MER"]["name"], gname(cold["decision_maker"]), mnc["MERIDIAN"]["name"])


@pytest.mark.warehouse
def test_naive_path_sponsor_crm_near_miss(naive):
    df = naive("q_path_sponsor_crm")
    owner = G_FLOW["hl_advised_t_cold_recap"]["owner"]
    assert list(df["name"]) == [gname(owner)]
    assert df.iloc[0]["sentiment"] == "neutral"


@pytest.mark.warehouse
def test_naive_flow_league_table(naive):
    df = naive("q_flow")
    big = G_FLOW["tier1_must_not_appear"][0]
    assert df.iloc[0]["entity_id"] == gid(big), "league table leader is the volume bank"
    assert int(df.iloc[0]["metric"]) == G_FLOW["bigbank_total_deals_5y"]
    hl = next(e for e in G_FLOW["betweenness_rank_intermediaries"] if e["key"]["key"] == "HL")
    assert int(df.set_index("entity_id").loc[gid(hl), "metric"]) == G_FLOW["hl_deals_in_window"]


@pytest.mark.warehouse
def test_naive_conflict_returns_former_holding(naive):
    df = naive("q_conflict")
    assert set(df["entity_id"]) == set(ids(G_CONF["naive_conflict_result"]))
    assert gid(G_CONF["former_holding_decoy"]) in set(df["entity_id"])
    two_hop = next(r for r in G_CONF["exposure_rows"] if r["distance"] == 2)
    assert gid(two_hop) not in set(df["entity_id"]), "the 1-hop join misses the 2-hop exposure"


@pytest.mark.warehouse
def test_naive_concentration_misses_breach(naive):
    df = naive("q_conflict_concentration")
    assert len(df) > 0
    assert set(df["verdict"]) == {"under guideline"}, "niche GROUP BY sees no concentration issue"
    assert float(df["metric"].max()) < G_CONF["concentration"]["guideline_pct"]


# ------------------------------------------------------------------------------------------------
# Backup Q-ADDON (not in HERO_QUERIES; one run)
# ------------------------------------------------------------------------------------------------
@pytest.mark.engine
def test_backup_addon(queries):
    g = GOLDEN["Q-ADDON"]
    df = queries.q_addon()
    assert list(df["company_id"]) == [gid(e) for e in g["ranked"]]
    for r, e in zip(df.itertuples(index=False), g["ranked"]):
        assert abs(float(r.similarity) - e["jaccard"]) < 1e-3
    assert not set(ids(g["must_not_contain"])) & set(df["company_id"])
    assert_why(df)
