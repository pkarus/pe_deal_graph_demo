"""Hero queries for the Northwind deal-graph demo (owner: R11 Query and Test Engineer).

One zero-argument function per question. The first docstring line is the business question in an
MD's words (``demo_workspace/ask.py --list`` shows it). Every function reads the prebuilt model live
through RelationalAI (core.py concepts, R09 rules.py, R10 graphs.py) and returns a pandas DataFrame,
or a dict of label -> DataFrame for a multi-part answer, with:

- answer rows only (no decoys: a name appears only when the answer is about it),
- a deterministic order (QUESTIONS.md v2 tie-breaks, always ending on a name),
- a ``name`` (or ``target``) display column and a ``why`` evidence column in business language.

Nothing here derives a business rule: scores, tiers, paths, ranks, conflicts and exposures are rule
and graph outputs (ONTOLOGY.md section 5). pandas only orders, labels and formats the rows.
All dates are relative to AS_OF = 2026-10-01. All data is synthetic.

HERO_QUERIES is the demo order; ``make warm``, the exporter and rehearsal run exactly this tuple.
"""

from __future__ import annotations

import time

import pandas as pd
from relationalai.semantics import Float, Integer
from relationalai.semantics.std import aggregates as aggs

from pe_deal_graph.model import core as _core
from pe_deal_graph.model.core import (
    AreaExposure,
    Company,
    ConflictSubject,
    CoverageGap,
    DecisionMaker,
    EligibleTarget,
    Fund,
    Intermediary,
    Knows,
    NorthwindHolding,
    OurSeed,
    Ownership,
    Person,
    PipelineEntry,
    PortfolioExposure,
    ProFormaExposure,
    ScoreComponent,
    Sector,
    Sponsor,
    WarmPath,
    WarmPathHop,
    bridge_cutoff,
    coverage_q1,
    model,
)

# Populate the derived layer: R09 rules and R10 graphs add their define() rules to the shared model.
from pe_deal_graph.model import graphs as _graphs  # noqa: F401
from pe_deal_graph.model import rules as _rules

HERO_QUERIES = ("q_score", "q_path", "q_flow", "q_conflict", "finale_rescore")

MAX_PATH_HOPS = _core.MAX_PATH_HOPS
TOP_TARGETS = 3  # Q-PATH: "for our top three"
FLOW_TOP_N = 5  # Q-FLOW: betweenness top 5 only (never a PageRank list)
CONFLICT_FLAG = _rules.CONFLICT_FLAG  # "Conflict - cross-fund review" (one source: rules.py)
ADDON_PLATFORM = "Ironvale Testing Group"  # Q-ADDON backup: the platform the question names
# One label source for score components: rules.SCORE_COMPONENTS (the same labels Company.why uses).
COMPONENT_ORDER = tuple(c for c, m in sorted(_rules.SCORE_COMPONENTS.items(), key=lambda kv: kv[1]["order"])
                        if not m.get("finale_only"))
COMPONENT_LABEL = {c: m["label"] for c, m in _rules.SCORE_COMPONENTS.items()}

# Graph outputs the hero answers read. An empty output is not an empty answer: an empty commercial
# distance would read as "no conflict", empty seed distances as "every CEO is cold". Each graph-backed
# function checks its invariant first, retries once after GRAPH_RETRY_SECONDS, then raises.
GRAPH_RETRY_SECONDS = 20


class GraphOutputMissing(RuntimeError):
    """A graph output a hero answer depends on is empty, so the answer would be wrong, not empty."""

# Decoy names never appear in an answer row (rehearsal fails on any decoy name in a transcript, and the
# presenter repeats the `why` column). The rules already cite former Northwind portfolio companies and our
# own people by role (rules.evidence_names), so this alias map is only a safety net for any other text.
# The descriptors are facts about the entity in the data, so the evidence stays meaningful.
# tests/test_hero.py derives the decoy list independently from golden.
DECOY_ALIASES = {
    "Tom Harlowe": "a Northwind deal-team member",            # Q-PATH false-intro person (current Northwind MD)
    "Varnell Lab Services": "an earlier employer",            # Q-PATH false-intro shared employer
    "Cobbleton Dental Group": "a former Northwind portfolio company",  # Q-CONFLICT former holding (Fund II, sold 2020)
    "Redfern Imaging Centers": "a Fund III portfolio company",  # Q-CONFLICT bound check (3 links away)
    "Brayford Capital Markets": "a generalist investment bank",  # Q-FLOW league-table leader
    "Pembrook Veterinary Pharmaceuticals": "a veterinary pharmaceuticals company",  # Q-SCORE keyword decoy
    "Linden Hollow Senior Care": "a skilled nursing operator",  # Q-SCORE thesis-exclusion decoy
    "Northgate Behavioral Health": "a behavioral health operator",  # Q-SCORE band near miss
    "Cobalt Urgent Care Partners": "an urgent care operator",  # Q-SCORE signal-count decoy
    "Shalecrest Materials Testing": "a materials testing company",  # Q-ADDON same-niche decoy
}


# ------------------------------------------------------------------------------------------------
# helpers (formatting and ordering only)
# ------------------------------------------------------------------------------------------------
def _run(q) -> pd.DataFrame:
    return q.to_df().reset_index(drop=True)


def _isna(v) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _int_col(df: pd.DataFrame, *cols: str) -> None:
    """Int128 / float columns from to_df() -> nullable Int64 (plain ints compare and print cleanly)."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.array([None if _isna(v) else int(v) for v in df[c]], dtype="Int64")


def _float_col(df: pd.DataFrame, digits: int, *cols: str) -> None:
    for c in cols:
        if c in df.columns:
            df[c] = [None if _isna(v) else round(float(v), digits) for v in df[c]]


def _str_col(df: pd.DataFrame, *cols: str) -> None:
    for c in cols:
        if c in df.columns:
            df[c] = ["" if _isna(v) else str(v) for v in df[c]]


def _money(x: float) -> str:
    return f"${x:,.1f}M" if not float(x).is_integer() else f"${x:,.0f}M"


def _pct(x: float) -> str:
    return f"{x:.1f}%"


def _scrub(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    """Safety net: replace decoy names in free-text evidence columns with their role descriptor.

    The rules already avoid decoy names at the root (rules.evidence_names); this catches anything else.
    Only evidence text is rewritten. Entity columns (name, target, path) are left alone, so a decoy
    that leaks into the answer itself still fails the tests instead of being hidden."""
    for c in cols or ("why",):
        if c in df.columns:
            out = []
            for v in df[c]:
                if isinstance(v, str):
                    for name, alias in DECOY_ALIASES.items():
                        v = v.replace(name, alias)
                out.append(v)
            df[c] = out
    return df


def _ids(q) -> set[str]:
    df = _run(q)
    return set() if df.empty else {str(v) for v in df.iloc[:, 0]}


def _count(expr) -> int:
    """One aggregate count from the engine (an empty aggregate reads as 0)."""
    df = _run(model.select((expr | 0).alias("n")))
    return 0 if df.empty or _isna(df["n"].iloc[0]) else int(df["n"].iloc[0])


def _check_warm_path_graph() -> str | None:
    """Q-PATH and Finale invariant: Knows has pairs and at least one seed has its 0-hop distance row."""
    if _count(aggs.count(Knows)) == 0:
        return "the Knows relationship is empty, so the warm-path graph has no edges"
    sd, p, h = Person.ref(), Person.ref(), Integer.ref()
    if _count(aggs.count(sd).where(OurSeed(sd), Person.seed_hops(sd, p, h), sd == p, h == 0)) == 0:
        return "seed distances are empty (no 0-hop row for any Northwind seed)"
    return None


def _check_deal_flow_graph() -> str | None:
    """Q-FLOW invariant: betweenness produced at least one intermediary bridge rank."""
    i = Intermediary.ref()
    if _count(aggs.count(i).where(i.bridge_rank)) == 0:
        return "deal-flow betweenness returned no intermediary bridge ranks"
    return None


def _check_commercial_graph() -> str | None:
    """Q-CONFLICT invariant: every bid subject has its own 0-hop row in the commercial distance."""
    s = Company.ref()
    subjects = _ids(model.where(ConflictSubject(s)).select(s.id.alias("subject_id")))
    if not subjects:
        return "no bid subject (pipeline company at stage IOI prep) was found"
    s2, c2, h2 = Company.ref(), Company.ref(), Integer.ref()
    reached = _ids(model.where(ConflictSubject(s2), Company.commercial_hops(s2, c2, h2), s2 == c2, h2 == 0)
                   .select(s2.id.alias("subject_id")))
    missing = sorted(subjects - reached)
    if missing:
        return f"the commercial graph returned no rows for bid subject(s) {', '.join(missing)}"
    return None


def _require_graph(check, what: str) -> None:
    """Run a graph invariant; on failure wait GRAPH_RETRY_SECONDS and retry once, then raise."""
    problem = check()
    if problem is None:
        return
    time.sleep(GRAPH_RETRY_SECONDS)
    problem = check()
    if problem is None:
        return
    raise GraphOutputMissing(
        f"GraphOutputMissing: {what}: {problem} (checked twice, {GRAPH_RETRY_SECONDS} s apart). This is not an "
        f"empty answer; do not read it out. Use the fallback from exports/ and re-run once the engine settles.")


# ------------------------------------------------------------------------------------------------
# Act 1: Q-SCORE
# ------------------------------------------------------------------------------------------------
def _scored(tier: str | None = "A") -> pd.DataFrame:
    """EligibleTargets (optionally one Act-1 tier) with score, pillars, rank and why."""
    c = Company.ref()
    conds = [EligibleTarget(c)]
    if tier is not None:
        conds.append(c.tier == tier)
    df = _run(model.where(*conds).select(
        c.id.alias("company_id"), c.name.alias("name"), c.score_rank.alias("rank"), c.score.alias("score"),
        c.fit_points.alias("fit"), c.readiness_points.alias("readiness"), c.access_points.alias("access"),
        c.tier.alias("tier"), c.why.alias("rule_why")))
    _int_col(df, "rank", "score", "fit", "readiness", "access")
    _str_col(df, "company_id", "name", "tier", "rule_why")
    return df


def _components(company_ids: set[str]) -> dict[str, list[tuple[str, int, str]]]:
    """company id -> [(code, points, evidence)] in QUESTIONS.md component order."""
    k, c = ScoreComponent.ref(), Company.ref()
    df = _run(model.where(k.company(c), EligibleTarget(c)).select(
        c.id.alias("company_id"), k.code.alias("code"), k.points.alias("points"), k.evidence.alias("evidence")))
    _int_col(df, "points")
    _str_col(df, "company_id", "code", "evidence")
    out: dict[str, list[tuple[str, int, str]]] = {}
    order = {code: i for i, code in enumerate(COMPONENT_ORDER)}
    for r in df.itertuples(index=False):
        if r.company_id in company_ids:
            out.setdefault(r.company_id, []).append((r.code, int(r.points), r.evidence))
    for v in out.values():
        v.sort(key=lambda x: (order.get(x[0], 99), x[0]))
    return out


def _in_crm_ids() -> set[str]:
    c = Company.ref()
    return _ids(model.where(EligibleTarget(c), c.in_crm()).select(c.id.alias("company_id")))


def _order_scorecard(df: pd.DataFrame, score: str = "score") -> pd.DataFrame:
    """QUESTIONS.md tie-break: score desc, readiness desc, fit desc, name asc."""
    return df.sort_values([score, "readiness", "fit", "name"], ascending=[False, False, False, True],
                          kind="mergesort").reset_index(drop=True)


def q_score() -> pd.DataFrame:
    """Which companies fit the Fund IV thesis and look ready to transact in the next 12-18 months, and why each one?

    Returns the Act-1 Tier A list (score >= 70) of eligible targets, ranked by score, then readiness,
    then fit, then name. Score = Fit (thesis node, EBITDA band, margin vs benchmark) + Readiness
    (PE-backed CFO hire, exit window, banker engaged, debt maturing, founder succession, new
    independent director; capped at 50) + Access (positive CRM touch in 24 months). `in_crm` is False
    for targets with no pipeline row and no CRM touch on the company or its people. `why` lists every
    awarded component with its evidence.
    """
    df = _scored("A")
    comps = _components(set(df["company_id"]))
    crm = _in_crm_ids()
    df["in_crm"] = [cid in crm for cid in df["company_id"]]
    df["components"] = ["; ".join(f"{code} {pts}" for code, pts, _ in comps.get(cid, []))
                        for cid in df["company_id"]]
    whys = []
    for r in df.itertuples(index=False):
        # The governed rule explanation (Company.why) verbatim; pandas adds only the header and the coverage note.
        body = r.rule_why or "; ".join(
            f"{COMPONENT_LABEL.get(code, code)} +{pts} ({ev})" if ev else f"{COMPONENT_LABEL.get(code, code)} +{pts}"
            for code, pts, ev in comps.get(r.company_id, []))
        head = f"Fit {r.fit} + Readiness {r.readiness} + Access {r.access} = {r.score}"
        tail = "" if r.in_crm else "; no coverage: no pipeline row and no CRM touch on the company or its people"
        whys.append(f"{head}: {body}{tail}")
    df["why"] = whys
    df = _scrub(_order_scorecard(df))
    return df[["rank", "name", "score", "fit", "readiness", "access", "tier", "in_crm", "components", "why",
               "company_id"]]


# ------------------------------------------------------------------------------------------------
# Act 2: Q-PATH
# ------------------------------------------------------------------------------------------------
def _top_targets(n: int = TOP_TARGETS) -> pd.DataFrame:
    c = Company.ref()
    df = _run(model.where(EligibleTarget(c), c.score_rank <= n).select(
        c.id.alias("company_id"), c.name.alias("target"), c.score_rank.alias("target_rank")))
    _int_col(df, "target_rank")
    _str_col(df, "company_id", "target")
    return df.sort_values(["target_rank", "target"], kind="mergesort").reset_index(drop=True)


def _owner_sponsor_names(n: int = TOP_TARGETS) -> dict[str, str]:
    c, f, s = Company.ref(), Fund.ref(), Sponsor.ref()
    df = _run(model.where(EligibleTarget(c), c.score_rank <= n, c.current_owner_fund(f), f.sponsor(s)).select(
        c.id.alias("company_id"), s.name.alias("sponsor")))
    _str_col(df, "company_id", "sponsor")
    return dict(zip(df["company_id"], df["sponsor"]))


def q_path() -> pd.DataFrame:
    """For our top three, what is our warmest path to each CEO, and through whom? And if the company is sponsor-owned, do we know the owner's deal partner?

    Returns one row per (target, decision-maker, path) for the top three Act-1 targets. Decision-makers
    are the current CEO and, for sponsor-owned targets, the owner's board designee (a current board
    member who is on the owning sponsor's deal team). A warm row is a shortest Knows path (3 hops or
    fewer) from a current Northwind deal-team member or operating partner, ranked by path strength (the
    product of the hop tie strengths); `path_rank` 1 is the best path and 2-3 are same-length alternates.
    A decision-maker with no path within 3 hops gets one explicit cold row; a target that is cold to
    every decision-maker also names its closest intermediary. `why` gives every hop with its dated evidence.
    """
    _require_graph(_check_warm_path_graph, "Q-PATH warm-path graph")
    tops = _top_targets()
    top_ids = set(tops["company_id"])
    rank_of = dict(zip(tops["company_id"], tops["target_rank"]))
    name_of = dict(zip(tops["company_id"], tops["target"]))

    # decision-makers of the top three (hops is absent when no seed reaches the person)
    c, p, dm = Company.ref(), Person.ref(), DecisionMaker.ref()
    dms = _run(model.where(EligibleTarget(c), c.score_rank <= TOP_TARGETS, dm.target(c), dm.person(p)).select(
        c.id.alias("company_id"), p.id.alias("person_id"), p.name.alias("decision_maker"),
        dm.kind.alias("role"), dm.hops.alias("dm_hops")))
    _int_col(dms, "dm_hops")
    _str_col(dms, "company_id", "person_id", "decision_maker", "role")

    # warm paths (best plus up to 2 same-length alternates) and their hops
    wp, c2, d2, s2 = WarmPath.ref(), Company.ref(), Person.ref(), Person.ref()
    paths = _run(model.where(wp.target(c2), wp.decision_maker(d2), wp.seed(s2), EligibleTarget(c2),
                             c2.score_rank <= TOP_TARGETS, wp.path_rank <= 3, wp.hops <= MAX_PATH_HOPS).select(
        c2.id.alias("company_id"), d2.id.alias("person_id"), wp.route.alias("route"), s2.name.alias("seed"),
        wp.hops.alias("hops"), wp.strength.alias("strength"), wp.path_rank.alias("path_rank"),
        wp.evidence.alias("path_evidence")))
    _int_col(paths, "hops", "path_rank")
    _str_col(paths, "company_id", "person_id", "route", "seed", "path_evidence")

    h, wp3, c3, pf, pt = WarmPathHop.ref(), WarmPath.ref(), Company.ref(), Person.ref(), Person.ref()
    hops = _run(model.where(h.path(wp3), wp3.target(c3), EligibleTarget(c3), c3.score_rank <= TOP_TARGETS,
                            wp3.path_rank <= 3, h.from_person(pf), h.to_person(pt)).select(
        c3.id.alias("company_id"), wp3.route.alias("route"), h.step.alias("step"), pf.name.alias("from_name"),
        pt.name.alias("to_name"), h.strength.alias("strength"), h.evidence.alias("evidence")))
    _int_col(hops, "step")
    _str_col(hops, "company_id", "route", "from_name", "to_name", "evidence")
    hop_map: dict[tuple[str, str], list] = {}
    for r in hops.sort_values(["company_id", "route", "step"], kind="mergesort").itertuples(index=False):
        hop_map.setdefault((r.company_id, r.route), []).append(r)

    owner_sponsor = _owner_sponsor_names()

    # closest intermediary, shown only for targets that are cold to every decision-maker
    c4, i4 = Company.ref(), Intermediary.ref()
    ci = _run(model.where(EligibleTarget(c4), c4.score_rank <= TOP_TARGETS, c4.closest_intermediary(i4)).select(
        c4.id.alias("company_id"), i4.name.alias("intermediary"),
        c4.closest_intermediary_evidence.alias("evidence")))
    _str_col(ci, "company_id", "intermediary", "evidence")
    closest = {r.company_id: (r.intermediary, r.evidence) for r in ci.itertuples(index=False)}

    warm_targets = set(paths["company_id"])
    rows = []
    for d in dms.itertuples(index=False):
        if d.company_id not in top_ids:
            continue
        mine = paths[(paths["company_id"] == d.company_id) & (paths["person_id"] == d.person_id)]
        if len(mine):
            for pr in mine.sort_values(["path_rank", "route"], kind="mergesort").itertuples(index=False):
                steps = hop_map.get((d.company_id, pr.route), [])
                if steps:
                    names = [steps[0].from_name] + [s.to_name for s in steps]
                    hop_txt = "; ".join(
                        f"{s.from_name} - {s.to_name}: {s.evidence} (tie {float(s.strength):.2f})" for s in steps)
                else:
                    names, hop_txt = [], pr.path_evidence
                label = "best path" if pr.path_rank == 1 else f"alternate {pr.path_rank}"
                rows.append({
                    "target_rank": rank_of[d.company_id], "target": name_of[d.company_id],
                    "decision_maker": d.decision_maker, "role": d.role, "status": "warm",
                    "path_rank": pr.path_rank, "hops": pr.hops, "strength": round(float(pr.strength), 3),
                    "path": " > ".join(names) if names else pr.route,
                    "why": f"{label}, {pr.hops} hops, strength {float(pr.strength):.3f} (product of hop ties): {hop_txt}",
                    "company_id": d.company_id, "person_id": d.person_id,
                })
        else:
            sponsor = owner_sponsor.get(d.company_id, "the owner")
            who = (f"{sponsor}{chr(39) if sponsor.endswith('s') else chr(39) + 's'} board designee {d.decision_maker}"
                   if d.role == "OWNER_DESIGNEE" else f"CEO {d.decision_maker}")
            why = (f"Cold: no path within {MAX_PATH_HOPS} hops from any Northwind deal-team member or "
                   f"operating partner to {who}")
            if not _isna(d.dm_hops):
                why += f" (nearest is {int(d.dm_hops)} hops away)"
            if d.company_id not in warm_targets and d.company_id in closest:
                inter, ev = closest[d.company_id]
                why += f". Closest intermediary: {inter} ({ev})" if ev else f". Closest intermediary: {inter}"
            rows.append({
                "target_rank": rank_of[d.company_id], "target": name_of[d.company_id],
                "decision_maker": d.decision_maker, "role": d.role, "status": "cold",
                "path_rank": None, "hops": d.dm_hops if not _isna(d.dm_hops) else None, "strength": None,
                "path": "", "why": why, "company_id": d.company_id, "person_id": d.person_id,
            })
    cols = ["target_rank", "target", "decision_maker", "role", "status", "path_rank", "hops", "strength", "path",
            "why", "company_id", "person_id"]
    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        return out
    out["_role"] = out["role"].map({"CEO": 0, "OWNER_DESIGNEE": 1}).fillna(2)
    out["_pr"] = out["path_rank"].fillna(99)
    out = out.sort_values(["target_rank", "_role", "decision_maker", "_pr"], kind="mergesort")
    out = _scrub(out.drop(columns=["_role", "_pr"]).reset_index(drop=True))
    _int_col(out, "target_rank", "path_rank", "hops")
    return out


# ------------------------------------------------------------------------------------------------
# Act 3: Q-FLOW
# ------------------------------------------------------------------------------------------------
def _standalone_int(rel) -> int | None:
    v = Integer.ref()
    df = _run(model.where(rel(v)).select(v.alias("v")))
    return None if df.empty else int(df["v"].iloc[0])


def q_flow() -> pd.DataFrame:
    """Which intermediaries actually bridge deal flow between founders and sponsors in our sectors, and where is our coverage weakest?

    Returns the top 5 intermediaries by exact betweenness centrality on the deal-flow network of the
    last 5 years in Fund IV thesis sectors (organizations linked by advisor, buyer, seller, owner and
    target roles on each deal), with their thesis deal count, our CRM touchpoints in the last 24 months
    and the coverage-gap flag: a top-decile bridge whose touchpoints sit in the bottom quartile of all
    intermediaries. PageRank is a display column only. `why` gives centrality plus touchpoints.
    """
    _require_graph(_check_deal_flow_graph, "Q-FLOW deal-flow graph")
    i = Intermediary.ref()
    df = _run(model.where(i.bridge_rank <= FLOW_TOP_N).select(
        i.id.alias("intermediary_id"), i.name.alias("name"), i.bridge_rank.alias("rank"),
        i.betweenness.alias("betweenness"), i.pagerank.alias("pagerank"),
        i.thesis_deals_5y.alias("thesis_deals"), i.touchpoints_24m.alias("our_touchpoints")))
    _int_col(df, "rank", "thesis_deals", "our_touchpoints")
    _float_col(df, 4, "betweenness")
    _float_col(df, 6, "pagerank")
    _str_col(df, "intermediary_id", "name")
    g = Intermediary.ref()
    gaps = _ids(model.where(CoverageGap(g)).select(g.id.alias("intermediary_id")))
    j = Intermediary.ref()
    n_int = _run(model.where(j.bridge_rank).select(j.id.alias("intermediary_id")))
    q1, cutoff = _standalone_int(coverage_q1), _standalone_int(bridge_cutoff)

    df["coverage_gap"] = [x in gaps for x in df["intermediary_id"]]
    whys = []
    for r in df.itertuples(index=False):
        t = r.our_touchpoints if not _isna(r.our_touchpoints) else 0
        deals = r.thesis_deals if not _isna(r.thesis_deals) else 0
        s = (f"bridge rank {r.rank} of {len(n_int)} intermediaries; betweenness {float(r.betweenness):,.1f} "
             f"(summed over firm pairs, the share of shortest deal-flow connections that pass through it); "
             f"advised {deals} thesis-sector deals in 5 years; "
             f"{t} CRM touchpoint{'s' if t != 1 else ''} with us in 24 months")
        if r.coverage_gap:
            s += (f"; COVERAGE GAP: top-decile bridge (rank <= {cutoff}) with touchpoints at or below the "
                  f"bottom quartile ({q1})")
        whys.append(s)
    df["why"] = whys
    df = _scrub(df.sort_values(["rank", "name"], kind="mergesort").reset_index(drop=True))
    return df[["rank", "name", "betweenness", "thesis_deals", "our_touchpoints", "coverage_gap", "pagerank", "why",
               "intermediary_id"]]


# ------------------------------------------------------------------------------------------------
# Act 4: Q-CONFLICT
# ------------------------------------------------------------------------------------------------
def q_conflict() -> dict[str, pd.DataFrame]:
    """Before we bid on Tessmark Clinical Supply, does it conflict with anything we own, and would the deal push Fund IV over its sector concentration guideline?

    Two parts. `exposures`: every company Northwind owns today within two commercial (supplier or
    customer) links of the bid subject (the pipeline company at stage "IOI prep"), classified as a
    cross-fund conflict (one link, held by a fund other than Fund IV) or a shared counterparty
    (two links, informational), with the link directions as evidence. `concentration`: Fund IV's
    current equity per thesis area and the pro forma share with the subject's estimated check,
    against the 35% IC guideline, with headroom and breach.
    """
    _require_graph(_check_commercial_graph, "Q-CONFLICT commercial graph")
    # exposures
    px, s, c, f = PortfolioExposure.ref(), Company.ref(), Company.ref(), Fund.ref()
    ex = _run(model.where(px.subject(s), px.company(c), px.fund(f), ConflictSubject(s)).select(
        s.id.alias("subject_id"), s.name.alias("target"), c.id.alias("company_id"), c.name.alias("name"),
        f.name.alias("fund"), px.hops.alias("distance"), px.kind.alias("verdict"),
        px.evidence.alias("evidence")))
    _int_col(ex, "distance")
    _str_col(ex, "subject_id", "target", "company_id", "name", "fund", "verdict", "evidence")
    o, oc, of = Ownership.ref(), Company.ref(), Fund.ref()
    since = _run(model.where(NorthwindHolding(o), o.company(oc), o.fund(of)).select(
        oc.id.alias("company_id"), of.name.alias("fund"), o.start_date.alias("since")))
    _str_col(since, "company_id", "fund")
    since_map = {(r.company_id, r.fund): pd.Timestamp(r.since).date().isoformat()
                 for r in since.itertuples(index=False) if not _isna(r.since)}
    ex["since"] = [since_map.get((r.company_id, r.fund), "") for r in ex.itertuples(index=False)]
    ex["why"] = [f"{r.evidence}; {r.name} is held by {r.fund}" + (f" since {r.since}" if r.since else "")
                 + f"; {r.distance} commercial link{'s' if r.distance != 1 else ''} away"
                 for r in ex.itertuples(index=False)]
    ex = _scrub(ex.sort_values(["target", "distance", "name"], kind="mergesort").reset_index(drop=True))
    exposures = ex[["target", "name", "fund", "since", "distance", "verdict", "why", "subject_id", "company_id"]]

    # concentration: one row per Fund IV thesis area for each bid subject
    pf, s2, a = ProFormaExposure.ref(), Company.ref(), Sector.ref()
    ae = AreaExposure.ref()
    conc = _run(model.where(pf.subject(s2), pf.area(a), ConflictSubject(s2), ae.area(a)).select(
        s2.name.alias("target"), a.id.alias("area_id"), a.name.alias("area"),
        ae.current_musd.alias("current_musd"), ae.current_pct.alias("current_pct"),
        pf.musd.alias("pro_forma_musd"), pf.pct.alias("pro_forma_pct"), ae.guideline_pct.alias("guideline_pct"),
        pf.headroom_musd.alias("headroom_musd"), pf.over_by_musd.alias("over_by_musd")))
    _float_col(conc, 2, "current_musd", "current_pct", "pro_forma_musd", "pro_forma_pct", "guideline_pct",
               "headroom_musd", "over_by_musd")
    _str_col(conc, "target", "area_id", "area")
    pf2, s3, a3 = ProFormaExposure.ref(), Company.ref(), Sector.ref()
    breach = _run(model.where(pf2.subject(s3), pf2.area(a3), ConflictSubject(s3), pf2.is_breach()).select(
        s3.name.alias("target"), a3.id.alias("area_id")))
    _str_col(breach, "target", "area_id")
    breach_set = set(zip(breach["target"], breach["area_id"]))
    conc["breach"] = [(r.target, r.area_id) in breach_set for r in conc.itertuples(index=False)]

    # Fund IV holdings per area (names for the evidence line)
    o2, c5, f5, a5 = Ownership.ref(), Company.ref(), Fund.ref(), Sector.ref()
    hold = _run(model.where(NorthwindHolding(o2), o2.company(c5), o2.fund(f5), _core.BuyingFund(f5),
                            c5.thesis_area(a5)).select(
        a5.id.alias("area_id"), c5.name.alias("holding"), o2.equity_invested_musd.alias("equity")))
    _str_col(hold, "area_id", "holding")
    _float_col(hold, 2, "equity")
    by_area: dict[str, list[tuple[str, float]]] = {}
    for r in hold.sort_values(["area_id", "equity", "holding"], ascending=[True, False, True],
                              kind="mergesort").itertuples(index=False):
        by_area.setdefault(r.area_id, []).append((r.holding, r.equity or 0.0))
    p6, c6 = PipelineEntry.ref(), Company.ref()
    chk = _run(model.where(p6.company(c6), ConflictSubject(c6)).select(
        c6.name.alias("target"), p6.est_equity_check_musd.alias("check")))
    _str_col(chk, "target")
    check_of = {r.target: float(r.check) for r in chk.itertuples(index=False) if not _isna(r.check)}

    whys = []
    for r in conc.itertuples(index=False):
        held = by_area.get(r.area_id, [])
        if held:
            s = (f"Fund IV holds " + ", ".join(f"{n} ({_money(e)})" for n, e in held)
                 + f": {_money(r.current_musd)} = {_pct(r.current_pct)} of the fund")
        else:
            s = f"Fund IV has no current holding in this area: {_money(r.current_musd)} = {_pct(r.current_pct)} of the fund"
        if r.pro_forma_musd is not None and r.current_musd is not None and r.pro_forma_musd > r.current_musd + 1e-9:
            s += (f"; with the {_money(check_of.get(r.target, r.pro_forma_musd - r.current_musd))} {r.target} check: "
                  f"{_money(r.pro_forma_musd)} = {_pct(r.pro_forma_pct)}")
        if r.breach:
            s += (f"; over the {r.guideline_pct:.0f}% guideline by {_money(r.over_by_musd)} "
                  f"(headroom {_money(r.headroom_musd)})")
        else:
            s += f"; within the {r.guideline_pct:.0f}% guideline"
        whys.append(s)
    conc["why"] = whys
    conc = conc.sort_values(["target", "pro_forma_pct", "area"], ascending=[True, False, True],
                            kind="mergesort").reset_index(drop=True)
    conc = _scrub(conc)
    concentration = conc[["target", "area", "current_musd", "current_pct", "pro_forma_musd", "pro_forma_pct",
                          "guideline_pct", "headroom_musd", "over_by_musd", "breach", "why", "area_id"]]
    return {"exposures": exposures, "concentration": concentration}


# ------------------------------------------------------------------------------------------------
# Finale
# ------------------------------------------------------------------------------------------------
def _finale_on() -> None:
    """Switch on R09's FINALE rules if rules.py gates them behind a call (idempotent, no Act-1 effect)."""
    for name in ("enable_finale", "apply_finale", "finale"):
        fn = getattr(_rules, name, None)
        if callable(fn):
            fn()
            return


def finale_rescore() -> pd.DataFrame:
    """Add two rules and re-score: warm-path access points, and a cross-fund conflict flag. What is the Tier A list now?

    Rule one: a target earns 10 access points if a current Northwind deal-team member or operating
    partner reaches its CEO in two Knows hops or fewer. Rule two: a target that supplies or buys from
    a current Fund III portfolio company is flagged "Conflict - cross-fund review" (hold until
    cross-fund clearance); it keeps its score but stays off the Tier A call list until cleared. Returns the re-scored Tier A list ranked by finale score, then
    readiness, then fit, then name, followed by the flagged target(s) that would otherwise be Tier A.
    `change` is the score change from Act 1; `why` is the full evidence including the new points.
    """
    _finale_on()
    _require_graph(_check_warm_path_graph, "Finale warm-path graph")
    c = Company.ref()
    df = _run(model.where(EligibleTarget(c), c.finale_tier == "A").select(
        c.id.alias("company_id"), c.name.alias("name"), c.finale_rank.alias("rank"),
        c.finale_score.alias("score"), c.score.alias("act1_score"), c.score_rank.alias("act1_rank"),
        c.tier.alias("act1_tier"), c.warm_path_points.alias("warm_path_points"),
        c.readiness_points.alias("readiness"), c.fit_points.alias("fit"), c.finale_why.alias("why")))
    _int_col(df, "rank", "score", "act1_score", "act1_rank", "warm_path_points", "readiness", "fit")
    _str_col(df, "company_id", "name", "act1_tier", "why")
    c2 = Company.ref()
    conflicted = _ids(model.where(EligibleTarget(c2), c2.has_conflict()).select(c2.id.alias("company_id")))
    df["flag"] = [CONFLICT_FLAG if x in conflicted else "" for x in df["company_id"]]
    df["on_tier_a"] = df["flag"] == ""
    df["change"] = df["score"] - df["act1_score"]
    df.loc[~df["on_tier_a"], "rank"] = pd.NA
    df["_off"] = ~df["on_tier_a"]
    df = df.sort_values(["_off", "score", "readiness", "fit", "name"], ascending=[True, False, False, False, True],
                        kind="mergesort").drop(columns="_off").reset_index(drop=True)
    df = _scrub(df)
    return df[["rank", "name", "score", "change", "act1_score", "act1_rank", "act1_tier", "flag", "on_tier_a",
               "why", "company_id"]]


# ------------------------------------------------------------------------------------------------
# Backup (not in HERO_QUERIES)
# ------------------------------------------------------------------------------------------------
def q_addon() -> pd.DataFrame:
    """Which add-ons best extend our Ironvale Testing Group platform, beyond the obvious same-niche names?

    Backup only. Ranks eligible targets by Jaccard similarity of their commercial neighborhood
    (customers and suppliers) with the Ironvale Testing Group platform (Fund IV), top 3. Companies that share no customer or
    supplier with the platform have no similarity at all and never appear.
    """
    p, cnd, sc = Company.ref(), Company.ref(), Float.ref()
    df = _run(model.where(Company.addon_similarity(p, cnd, sc), p.name == ADDON_PLATFORM, EligibleTarget(cnd),
                          p != cnd).select(
        p.name.alias("platform"), cnd.id.alias("company_id"), cnd.name.alias("name"), sc.alias("similarity")))
    _float_col(df, 4, "similarity")
    _str_col(df, "platform", "company_id", "name")
    df = df.sort_values(["similarity", "name"], ascending=[False, True], kind="mergesort").head(3)
    df = df.reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    df["why"] = [f"Jaccard {r.similarity:.4f} with {r.platform} over shared customers and suppliers"
                 for r in df.itertuples(index=False)]
    df = _scrub(df)
    return df[["rank", "name", "similarity", "platform", "why", "company_id"]]


__all__ = ["HERO_QUERIES", "q_score", "q_path", "q_flow", "q_conflict", "finale_rescore", "q_addon",
           "GraphOutputMissing"]
