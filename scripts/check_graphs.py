"""Check the graph layer (pe_deal_graph/model/graphs.py) against the golden answers and the oracle.

What it does, in order:
1. Validates every network first: node and edge counts from the engine (graphs.validate_graphs),
   logged, and compared with the independent oracle's counts (data/oracle_output.json).
2. Q-PATH: best routes and alternates per decision-maker (hops, route, strength 0.700 / 0.600 /
   0.287, hop strengths), cold decision-makers, and the must-not-contain decoys.
3. Q-FLOW: bridge rank of Cedar Row (1) and Harbor Lane (2), the decoy bank at rank 11 or lower,
   and exact betweenness for every intermediary against the oracle (networkx exact Brandes).
4. Q-CONFLICT: our current holdings within 2 commercial links of the bid subject are exactly the
   golden set, with the right distances; the bound check (3 links) and the former holding (1 link).
5. Q-ADDON backup: Jaccard ranking from the platform; the same-niche decoy is absent.

Golden ids are read from data/golden/expected.json here, in the check only; the model never sees them.

Usage
    .venv/bin/python scripts/check_graphs.py            # exit 0 = every check passed
    .venv/bin/python scripts/check_graphs.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS: list[dict] = []


def record(ok: bool, name: str, detail: str = "") -> bool:
    """Print and keep one PASS/FAIL line."""
    RESULTS.append({"ok": bool(ok), "check": name, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)
    return ok


def _ids(rows):
    return [x["id"] for x in rows]


def run_checks(import_rules: bool = True) -> int:
    """Run every graph check against the live model; returns the number of failures."""
    t0 = time.time()
    if import_rules:
        import pe_deal_graph.model.rules  # noqa: F401  (R09: Knows, OurSeed, DecisionMaker, ...)
    from relationalai.semantics import Float, Integer, String  # noqa: F401
    from relationalai.semantics.std import aggregates as aggs

    import pe_deal_graph.model.graphs as G
    from pe_deal_graph.model import core as C

    golden = json.loads((ROOT / "data/golden/expected.json").read_text())["questions"]
    oracle = json.loads((ROOT / "data/oracle_output.json").read_text())
    model = C.model

    # ---------------------------------------------------------------- 1. sizes first
    sizes = G.validate_graphs()
    print(f"INFO  first graph query done in {time.time() - t0:.1f}s", flush=True)
    o_knows = oracle["Q-PATH"]["diagnostics"]["knows_graph"]
    o_flow = oracle["Q-FLOW"]["diagnostics"]
    o_comm = oracle["Q-CONFLICT"]["diagnostics"]["commercial_graph"]
    for name, o in (("warm_path", o_knows), ("deal_flow", o_flow), ("commercial", o_comm)):
        s = sizes[name]
        record(s["nodes"] == o["num_nodes"] and s["edges"] == o["num_edges"],
               f"{name} graph size equals oracle",
               f"rai {s['nodes']} nodes/{s['edges']} edges, oracle {o['num_nodes']}/{o['num_edges']}")
    record(sizes["deal_flow"]["nodes"] <= C.BETWEENNESS_PIVOTS, "deal-flow |V| <= BETWEENNESS_PIVOTS (exact betweenness)",
           f"{sizes['deal_flow']['nodes']} <= {C.BETWEENNESS_PIVOTS}")

    # ---------------------------------------------------------------- 2. Q-PATH
    WP, WH, DM = C.WarmPath, C.WarmPathHop, C.DecisionMaker
    paths = model.select(
        WP.target.id.alias("target"), WP.decision_maker.id.alias("dm"), WP.route.alias("route"),
        WP.path_rank.alias("rank"), WP.hops.alias("hops"), WP.strength.alias("strength"),
        WP.seed.id.alias("seed"), WP.evidence.alias("evidence"),
    ).to_df()
    for col in ("rank", "hops"):
        paths[col] = paths[col].astype(int)
    paths = paths.sort_values(["target", "dm", "rank"]).reset_index(drop=True)
    hops_df = model.select(
        WH.path.target.id.alias("target"), WH.path.decision_maker.id.alias("dm"), WH.path.route.alias("route"),
        WH.step.alias("step"), WH.from_person.id.alias("from_id"), WH.to_person.id.alias("to_id"),
        WH.strength.alias("strength"), WH.evidence.alias("evidence"),
    ).to_df()
    hops_df["step"] = hops_df["step"].astype(int)
    dms = model.select(DM.target.id.alias("target"), DM.person.id.alias("dm"), DM.kind.alias("kind"),
                       DM.hops.alias("hops")).to_df()
    cold = model.where(DM.is_cold()).select(DM.target.id.alias("target"), DM.person.id.alias("dm")).to_df()
    cold_set = {(r.target, r.dm) for r in cold.itertuples(index=False)}
    print(f"INFO  WarmPath rows {len(paths)}, WarmPathHop rows {len(hops_df)}, DecisionMaker rows {len(dms)}, "
          f"cold {len(cold_set)}", flush=True)
    print(paths[["target", "dm", "rank", "hops", "strength", "route"]].to_string(index=False), flush=True)
    for r in paths.itertuples(index=False):
        print(f"EVIDENCE  {r.target} {r.dm} rank {r.rank}: {r.evidence}", flush=True)

    for row in golden["Q-PATH"]["rows"]:
        t, d = row["target"]["id"], row["decision_maker"]["id"]
        label = f"{row['target']['name']} -> {row['decision_maker']['name']} ({row['kind']})"
        mine = paths[(paths.target == t) & (paths.dm == d)]
        if row.get("cold"):
            record(mine.empty and (t, d) in cold_set, f"Q-PATH {label}: cold, no path within 3 hops",
                   f"paths={len(mine)} cold_flag={(t, d) in cold_set}")
            continue
        best = mine[mine["rank"] == 1]
        want_route = ">".join(_ids(row["best_path"]))
        ok = len(best) == 1 and best.iloc[0].route == want_route and int(best.iloc[0].hops) == row["hops"] \
            and round(float(best.iloc[0].strength), 3) == round(row["path_strength"], 3)
        got = (best.iloc[0].route, int(best.iloc[0].hops), round(float(best.iloc[0].strength), 3)) if len(best) else None
        record(ok, f"Q-PATH {label}: best path, {row['hops']} hops, strength {row['path_strength']:.3f}",
               f"got {got}")
        if len(best):
            h = hops_df[(hops_df.target == t) & (hops_df.dm == d) & (hops_df.route == want_route)].sort_values("step")
            got_hs = [round(float(x), 3) for x in h.strength]
            record(got_hs == [round(x, 3) for x in row["hop_strengths"]] and list(h.step) == list(range(1, row["hops"] + 1)),
                   f"Q-PATH {label}: hop rows and hop strengths", f"got {got_hs} want {row['hop_strengths']}")
        alts = mine[mine["rank"] > 1].sort_values("rank")
        want_alts = row.get("alternates", [])
        got_alts = [(r.route, round(float(r.strength), 3), int(r["rank"])) for _, r in alts.iterrows()]
        exp_alts = [(">".join(_ids(a["path"])), round(a["path_strength"], 3), a["rank"]) for a in want_alts]
        record(got_alts == exp_alts, f"Q-PATH {label}: alternates", f"got {got_alts} want {exp_alts}")
        dm_row = dms[(dms.target == t) & (dms.dm == d)]
        record(len(dm_row) == 1 and int(dm_row.iloc[0].hops) == row["hops"] and (t, d) not in cold_set,
               f"Q-PATH {label}: DecisionMaker.hops = {row['hops']} and not cold")
    bad_people = {x["id"] for x in golden["Q-PATH"]["must_not_contain"] if x["id"].startswith("P")}
    bad_orgs = [x["name"] for x in golden["Q-PATH"]["must_not_contain"] if not x["id"].startswith("P")]
    leaks = [r.route for r in paths.itertuples(index=False)
             if set(r.route.split(">")) & bad_people or any(o in r.evidence for o in bad_orgs)]
    record(not leaks, "Q-PATH must_not_contain: no route through the decoy person or the decoy employer",
           f"leaks={leaks}")
    record(bool((paths["rank"] <= G.MAX_RANKED_PATHS).all()), "WarmPath keeps ranks 1-3 only",
           f"max rank {paths['rank'].max() if len(paths) else None}")

    # ---------------------------------------------------------------- 3. Q-FLOW
    I = C.Intermediary
    flow = model.select(I.id.alias("id"), I.name.alias("name"), I.betweenness.alias("betweenness"),
                        I.pagerank.alias("pagerank"), I.bridge_rank.alias("bridge_rank")).to_df()
    flow = flow.dropna(subset=["bridge_rank"]).copy()
    flow["bridge_rank"] = flow["bridge_rank"].astype(int)
    flow = flow.sort_values("bridge_rank").reset_index(drop=True)
    print(flow.head(12).to_string(index=False), flush=True)
    rank_of = dict(zip(flow.id, flow.bridge_rank))
    for g in golden["Q-FLOW"]["betweenness_rank_intermediaries"]:
        k = g["key"]
        record(rank_of.get(k["id"]) == g["rank"], f"Q-FLOW {k['name']} bridge rank {g['rank']}",
               f"got {rank_of.get(k['id'])}")
    big = next(x for x in golden["Q-FLOW"]["must_not_contain"] if x["key"] == "BIGBANK")
    br = rank_of.get(big["id"])
    record(br is None or br >= golden["Q-FLOW"]["bigbank_min_rank"],
           f"Q-FLOW decoy {big['name']} ranks {golden['Q-FLOW']['bigbank_min_rank']} or lower", f"got {br}")
    o_rank = oracle["Q-FLOW"]["intermediary_ranking"]
    o_bc = {x["intermediary_id"]: x["betweenness"] for x in o_rank}
    o_pr = {x["intermediary_id"]: x["pagerank"] for x in o_rank}
    rai_bc = dict(zip(flow.id, flow.betweenness.astype(float)))
    # abs 1e-4, or 1e-7 relative for large values (engine floats match networkx to ~5e-9 relative; P5 noise
    # pushed the top betweenness past 7,500, where 1e-4 absolute is below float noise plus the oracle's 6 dp rounding)
    bc_diff = [(i, rai_bc.get(i), o_bc[i]) for i in o_bc
               if rai_bc.get(i) is None or abs(rai_bc[i] - o_bc[i]) > max(1e-4, 1e-7 * abs(o_bc[i]))]
    record(not bc_diff and len(rai_bc) == len(o_bc),
           "Q-FLOW exact betweenness equals oracle for every intermediary in the graph",
           f"{len(rai_bc)} rai vs {len(o_bc)} oracle; diffs={bc_diff[:5]}")
    record(list(flow.id) == [x["intermediary_id"] for x in o_rank], "Q-FLOW full bridge ranking equals oracle order")
    rai_pr = dict(zip(flow.id, flow.pagerank.astype(float)))
    pr_diff = max((abs(rai_pr.get(i, 0.0) - o_pr[i]) for i in o_pr), default=0.0)
    record(pr_diff < 1e-4, "Q-FLOW pagerank close to oracle (display only)", f"max abs diff {pr_diff:.2e}")
    n_int = len(flow)
    record(n_int == oracle["Q-FLOW"]["diagnostics"]["n_intermediaries_in_graph"],
           "Q-FLOW intermediaries in graph equal oracle", f"{n_int}")

    # ---------------------------------------------------------------- 4. Q-CONFLICT
    Co, Ow, F = C.Company, C.Ownership, C.Fund
    s, c, h = Co.ref(), Co.ref(), Integer.ref()
    reach = model.where(Co.commercial_hops(s, c, h)).select(  # fields (subject, company, hops)
        s.id.alias("subject"), c.id.alias("company"), c.name.alias("name"), h.alias("hops")).to_df()
    reach["hops"] = reach["hops"].astype(int)
    q = golden["Q-CONFLICT"]
    subj = q["subject"]["id"]
    mine = reach[reach.subject == subj]
    record(set(reach.subject) == {subj}, "Q-CONFLICT reach is computed from the bid subject only",
           f"subjects={sorted(set(reach.subject))}")
    o, c2, f = Ow.ref(), Co.ref(), F.ref()
    hold = model.where(C.NorthwindHolding(o), o.company(c2), o.fund(f)).select(
        c2.id.alias("company"), f.name.alias("fund")).to_df()
    held = set(hold.company)
    dist = dict(zip(mine.company, mine.hops))
    within2 = {k: v for k, v in dist.items() if k in held and 1 <= v <= 2}
    want = {r["key"]["id"]: r["distance"] for r in q["exposure_rows"]}
    record(within2 == want, "Q-CONFLICT holdings within 2 links equal golden",
           f"got {within2} want {want}")
    bc_ = q["bound_check"]
    record(dist.get(bc_["key"]["id"]) == bc_["distance"], f"Q-CONFLICT bound check {bc_['key']['name']} at 3 links",
           f"got {dist.get(bc_['key']['id'])}")
    fh = q["former_holding_decoy"]
    record(dist.get(fh["key"]["id"]) == fh["distance"] and fh["key"]["id"] not in held,
           f"Q-CONFLICT former holding {fh['key']['name']} at 1 link and not a current holding",
           f"dist={dist.get(fh['key']['id'])} held={fh['key']['id'] in held}")

    # ---------------------------------------------------------------- 5. Q-ADDON (backup)
    a = golden.get("Q-ADDON")
    if a:
        u, v, sc = Co.ref(), Co.ref(), Float.ref()
        sim = model.where(Co.addon_similarity(u, v, sc)).select(
            u.id.alias("platform"), v.id.alias("candidate"), v.name.alias("name"), sc.alias("jaccard")).to_df()
        plat = sim[sim.platform == a["platform"]["id"]]
        got = {r.candidate: round(float(r.jaccard), 4) for r in plat.itertuples(index=False)}
        for want_row in a["ranked"]:
            k = want_row["key"]
            record(got.get(k["id"]) == round(want_row["jaccard"], 4),
                   f"Q-ADDON {k['name']} jaccard {want_row['jaccard']}", f"got {got.get(k['id'])}")
        top = [r.candidate for r in plat.sort_values(["jaccard", "candidate"], ascending=[False, True]).itertuples()][:3]
        record(top == [x["key"]["id"] for x in a["ranked"]], "Q-ADDON top 3 order equals golden", f"got {top}")
        for d in a["must_not_contain"]:
            record(d["id"] not in got, f"Q-ADDON decoy {d['name']} absent (zero overlap)")

    # ---------------------------------------------------------------- 6. every R10 contract name has facts
    p1, p2, p3 = C.Person.ref(), C.Person.ref(), Integer.ref()
    o1, o2 = C.Organization.ref(), C.Organization.ref()
    c1, c2_, f1 = Co.ref(), Co.ref(), Float.ref()
    counts = {
        "Person.seed_hops": aggs.count(p1, p2).where(C.Person.seed_hops(p1, p2, p3)),
        "Person.nearest_seed_hops": aggs.count(C.Person).where(C.Person.nearest_seed_hops),
        "Person.dm_hops": aggs.count(p1, p2).where(C.Person.dm_hops(p1, p2, p3)),
        "DecisionMaker.hops": aggs.count(DM).where(DM.hops),
        "DecisionMaker.is_cold": aggs.count(DM).where(DM.is_cold()),
        "WarmPath": aggs.count(WP), "WarmPathHop": aggs.count(WH),
        "Organization.deal_flow_partner": aggs.count(o1, o2).where(o1.deal_flow_partner(o2)),
        "Organization.betweenness": aggs.count(C.Organization).where(C.Organization.betweenness),
        "Organization.pagerank": aggs.count(C.Organization).where(C.Organization.pagerank),
        "Organization.flow_community": aggs.count(C.Organization).where(C.Organization.flow_community),
        "Intermediary.bridge_rank": aggs.count(I).where(I.bridge_rank),
        "Company.commercial_hops": aggs.count(c1, c2_).where(Co.commercial_hops(c1, c2_, p3)),
        "Company.commercial_community": aggs.count(Co).where(Co.commercial_community),
        "Company.addon_similarity": aggs.count(c1, c2_).where(Co.addon_similarity(c1, c2_, f1)),
    }
    names = list(counts)
    cdf = model.select(*[counts[n].alias(f"c{i}") for i, n in enumerate(names)]).to_df()
    for i, n in enumerate(names):
        v = int(cdf[f"c{i}"].iloc[0]) if len(cdf) and f"c{i}" in cdf else 0
        record(v > 0, f"contract {n} has facts", f"{v}")

    n_fail = sum(1 for r in RESULTS if not r["ok"])
    print(f"\nGRAPH CHECK {'PASS' if n_fail == 0 else 'FAIL'}: {len(RESULTS) - n_fail} pass, {n_fail} fail "
          f"({time.time() - t0:.0f}s)", flush=True)
    return n_fail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="also write the results to this JSON file")
    args = ap.parse_args()
    n_fail = run_checks()
    if args.json:
        Path(args.json).write_text(json.dumps(RESULTS, indent=1))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
