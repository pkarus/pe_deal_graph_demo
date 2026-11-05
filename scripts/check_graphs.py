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
import ast
import runpy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pe_deal_graph import settings as _cfg  # noqa: E402  (database/schema/role/engine names)

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


# Focused Knows validation, called under the existing process-local guards.
MIN_TIE_STRENGTH = 0.0
EXPECTED = 2525


def prepare_oracle():
    # Read the graph setting without importing graph algorithms or running RAI.
    tree = ast.parse((ROOT / "pe_deal_graph/model/graphs.py").read_text())
    threshold = next(ast.literal_eval(n.value) for n in tree.body
                     if isinstance(n, ast.Assign) and any(
                         isinstance(t, ast.Name) and t.id == "MIN_TIE_STRENGTH" for t in n.targets))
    if threshold != MIN_TIE_STRENGTH:
        raise RuntimeError("MIN_TIE_STRENGTH must remain 0.0; no threshold change attempted")
    oracle = runpy.run_path(str(ROOT / "data/oracle.py"))
    data = oracle["Data"]()
    connections = oracle["build_knows"](data, set(oracle["our_seeds"](data)))
    pairs = {pair: value for pair, value in connections.items()
             if value["strength"] >= MIN_TIE_STRENGTH}
    if len(pairs) != EXPECTED:
        raise RuntimeError(f"Local oracle changed: {len(pairs)} connections, expected {EXPECTED}")
    print(f"Local oracle: {len(pairs)} unordered connections; MIN_TIE_STRENGTH=0.0")
    return pairs


def compare_pairs(rows, oracle_pairs):
    actual = set()
    noncanonical = []
    for row in rows:
        a, b = row["p1"], row["p2"]
        if not isinstance(a, str) or not isinstance(b, str):
            raise RuntimeError("Pair IDs must be strings")
        if a >= b:
            noncanonical.append([a, b])
        actual.add(tuple(sorted((a, b))))
    expected = set(oracle_pairs)
    missing = sorted(expected - actual)
    return {
        "oracle_count": len(expected), "returned_rows": len(rows),
        "unique_pairs": len(actual), "duplicate_rows": len(rows) - len(actual),
        "noncanonical_pairs": noncanonical,
        "missing_pairs": [list(p) for p in missing],
        "extra_pairs": [list(p) for p in sorted(actual - expected)],
        "missing_pair_oracle_evidence": [
            {"pair": list(p), "oracle": oracle_pairs[p]} for p in missing
        ],
        "rai_rows": rows,
    }


def summarize_people_communities(rows, oracle_data, oracle_graph, top_n=3, *,
                                 method='RAI', parameters=None):
    """Check full membership and every internal score using an independent oracle."""
    import math
    import networkx as nx
    from collections import Counter, defaultdict
    parameters = community_parameters(1, 42) if parameters is None else parameters
    pivots = parameters.get('num_pivots')
    if pivots is not None and pivots < len(oracle_graph):
        raise RuntimeError('Sampled centrality is not supported by this exact validation')
    if set(oracle_graph) != set(oracle_data.person):
        raise RuntimeError('Graph and person universe differ')
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        person = row['person_id']
        if person in seen or person not in oracle_data.person:
            raise RuntimeError('Duplicate or unexpected community member')
        seen.add(person)
        if row['name'] != oracle_data.person[person]['full_name']:
            raise RuntimeError('Person name differs from baseline')
        label = int(row['community'])
        if label != row['community']:
            raise RuntimeError('Community labels must be integers')
        row = dict(row, community=label, betweenness=float(row['betweenness']))
        if not math.isfinite(row['betweenness']):
            raise RuntimeError('Invalid centrality score')
        groups[row['community']].append(row)
    if seen != set(oracle_data.person): raise RuntimeError('Incomplete community membership')
    summaries = []
    rounded_zero_scores = 0
    max_absolute_error = 0.0
    for members in sorted(groups.values(), key=lambda m: (-len(m),min(r['person_id'] for r in m))):
        graph = oracle_graph.subgraph(r['person_id'] for r in members)
        expected = nx.betweenness_centrality(graph, k=None, normalized=False, weight=None, endpoints=False)
        for row in members:
            if not math.isclose(row['betweenness'], expected[row['person_id']], rel_tol=2e-6, abs_tol=1e-5):
                raise RuntimeError('Within-community betweenness differs from oracle: '+row['person_id'])
            max_absolute_error = max(max_absolute_error, abs(row['betweenness'] - expected[row['person_id']]))
            row['raw_betweenness'] = row['betweenness']
            if expected[row['person_id']] == 0.0 and row['betweenness'] != 0.0:
                rounded_zero_scores += 1
                row['betweenness'] = 0.0  # Display only, after independent tolerance check.
        ordered = sorted(members, key=lambda r: (-round(r['betweenness'],3),r['name'],r['person_id']))
        summaries.append(dict(community=len(summaries)+1, size=len(members),
                              person_ids=sorted(r['person_id'] for r in members),
                              internal_edges=graph.number_of_edges(),
                              top_connectors=[{k:r[k] for k in ('person_id','name','betweenness','raw_betweenness')} for r in ordered[:top_n]],
                              all_zero=all(r['betweenness']==0 for r in members)))
    partition = [set(c['person_ids']) for c in summaries]
    return dict(people=len(seen), connections=oracle_graph.number_of_edges(),
                community_count=len(summaries), communities=summaries,
                modularity=nx.community.modularity(oracle_graph, partition, weight=None, resolution=1)
                    if oracle_graph.number_of_edges() else None,
                size_distribution=dict(sorted(Counter(c['size'] for c in summaries).items())),
                largest_community=max((c['size'] for c in summaries), default=0),
                singletons=sum(c['size'] == 1 for c in summaries),
                graph_isolates=nx.number_of_isolates(oracle_graph),
                rounded_zero_scores=rounded_zero_scores,
                score_tolerance=dict(relative=2e-6, absolute=1e-5),
                max_absolute_score_error=max_absolute_error,
                method=method, parameters=parameters,
                centrality=dict(mode='exact', normalized=False, weight=None, endpoints=False,
                                rai_num_pivots=pivots, networkx_k=None),
                validation='All memberships, names and internal scores checked with NetworkX Brandes; '
                           'independent for RAI, consistency check for NetworkX')


def community_parameters(max_levels, randomization_seed):
    """Options supported by the installed RAI 1.27.1 SDK; only level/seed vary."""
    if type(max_levels) is not int or max_levels < 1:
        raise ValueError('max_levels must be a positive integer')
    if type(randomization_seed) is not int or randomization_seed < 0:
        raise ValueError('randomization_seed must be a non-negative integer')
    return dict(max_levels=max_levels, randomization_seed=randomization_seed,
                max_sweeps=20, level_tolerance=0.01, sweep_tolerance=0.0001,
                num_pivots=16000)


def community_graph_fingerprint(data, graph):
    """Bind cached results to the complete named, unweighted people/Knows graph."""
    import hashlib
    payload = dict(people=sorted((p, data.person[p]['full_name']) for p in graph),
                   edges=sorted(tuple(sorted(e)) for e in graph.edges))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def community_focus(oracle, data, summaries):
    """Mirror OurSeed and DecisionMaker for eligible Act 1 Tier A targets."""
    membership = {p: c['community'] for c in summaries for p in c['person_ids']}
    seeds = [dict(person_id=p, name=data.pname(p), community=membership[p])
             for p in oracle['our_seeds'](data)]
    targets = oracle['q_score'](data, oracle['Thesis'](data))['answer']['tier_a']
    decision_makers = []
    for target in targets:
        people = oracle['decision_makers'](data, target['company_id'])
        ceos = {p['person_id'] for p in people if p['kind'] == 'CEO'}
        for person in people:
            # The oracle helper includes all owners; the model uses majority owners
            # and excludes a CEO from OWNER_DESIGNEE. Apply those model constraints.
            if person['kind'] == 'OWNER_DESIGNEE':
                owners = [o for o in data.current_ownerships(target['company_id'])
                          if o['stake_type'] == 'majority' and person['person_id'] in {
                              role['person_id'] for role in data.current_roles_at(
                                  data.fund[o['fund_id']]['sponsor_id'], {'Deal Team'})}]
                if person['person_id'] in ceos or not owners:
                    continue
                person = dict(person, via='; '.join(
                    f"{data.fund[o['fund_id']]['name']} ({data.org_name(data.fund[o['fund_id']]['sponsor_id'])})"
                    for o in owners))
            decision_makers.append(dict(person, target_id=target['company_id'],
                                        target_name=target['name'], target_score=target['score'],
                                        community=membership[person['person_id']]))
    relevant = {p['community'] for p in seeds + decision_makers}
    return dict(as_of=str(oracle['T']), team_seeds=seeds, decision_makers=decision_makers,
                communities=[c for c in summaries if c['community'] in relevant],
                definition='Local oracle of rules.who_we_are, composite_score and decision_makers: '
                           'current Northwind Deal Team/Operating Partners; eligible targets with '
                           'Act 1 score >=70; current CEOs and majority-owning sponsor board designees.',
                relevance='Internal betweenness sums fractions of shortest paths between other community members that pass through a person, using only the induced subgraph. It does not measure introduction success or real-world influence. All-zero groups have no distinction under this metric. Ties use 3 decimals, then name and ID. Scores and display IDs are specific to each partition.')


def adjusted_rand_index(left, right, nodes):
    """Chance-adjusted pair agreement, invariant to arbitrary community labels."""
    from collections import Counter
    from math import comb
    nodes = list(nodes)
    if len(nodes) < 2:
        return 1.0
    cells = Counter((left[p], right[p]) for p in nodes)
    a = sum(comb(n, 2) for n in Counter(left[p] for p in nodes).values())
    b = sum(comb(n, 2) for n in Counter(right[p] for p in nodes).values())
    joint = sum(comb(n, 2) for n in cells.values())
    expected = a * b / comb(len(nodes), 2)
    maximum = (a + b) / 2
    return (joint - expected) / (maximum - expected) if maximum != expected else 1.0


def compare_community_partitions(partitions, graph):
    from itertools import combinations
    comparisons = []
    nonisolated = [p for p in graph if graph.degree(p)]
    for left, right in combinations(partitions, 2):
        same_method = left['method'] == right['method']
        same_level = left['max_levels'] == right['max_levels']
        same_seed = left['seed'] == right['seed']
        if same_method and same_level:
            kind = 'seed stability'
        elif same_method and same_seed:
            kind = 'level limit comparison'
        elif not same_method and same_seed and same_level:
            kind = 'RAI / NetworkX reference agreement (not an equality requirement)'
        else:
            continue
        comparisons.append(dict(left=left['id'], right=right['id'], kind=kind,
            adjusted_rand_all=adjusted_rand_index(left['membership'], right['membership'], graph),
            adjusted_rand_nonisolated=adjusted_rand_index(left['membership'], right['membership'], nonisolated)))
    return comparisons


def analyze_people_communities(oracle_pairs, levels, seeds, saved_path, *, execute=False, output_path=None):
    """Offline by default; only the guarded caller may enable missing RAI runs."""
    import networkx as nx
    levels, seeds = list(dict.fromkeys(levels)), list(dict.fromkeys(seeds))
    settings = [community_parameters(level, seed) for level in levels for seed in seeds]
    oracle = runpy.run_path(str(ROOT/'data/oracle.py'))
    data = oracle['Data']()
    graph = oracle['knows_graph'](data, oracle_pairs)
    fingerprint = community_graph_fingerprint(data, graph)
    saved = json.loads(Path(saved_path).read_text())
    if saved['graph_sha256'] != fingerprint:
        raise RuntimeError('Saved RAI graph fingerprint differs from local baseline')
    raw_runs = saved['saved_rai_runs'][:]
    saved_by_setting = {}
    for run in raw_runs:
        p = run['parameters']
        key = (p['max_levels'], p['randomization_seed'])
        if p != community_parameters(*key) or key in saved_by_setting:
            raise RuntimeError('Saved RAI parameters differ or duplicate a run')
        saved_by_setting[key] = run
    artifact = dict(graph_sha256=fingerprint, saved_rai_runs=raw_runs)
    if execute and output_path is None:
        raise ValueError('Live comparisons require a new --community-output file for saved rows')
    if output_path:
        # Never overwrite the baseline or another result. Checkpoint completed queries below.
        with Path(output_path).open('x') as stream:
            json.dump(artifact, stream, indent=2)
    reports, partitions, pending = [], [], []
    for parameters in settings:
        level, seed = parameters['max_levels'], parameters['randomization_seed']
        run = saved_by_setting.get((level, seed))
        if run is None and execute:
            run = run_people_communities(oracle_pairs, max_levels=level, randomization_seed=seed)
            raw_runs.append(run)
            # Save raw scores before numerical validation, including on validation failure.
            Path(output_path).write_text(json.dumps(artifact, indent=2)+'\n')
        variants = []
        if run is None:
            pending.append(dict(method='RAI', status='requires live execution', parameters=parameters))
        else:
            variants.append(('RAI', 'live RAI' if execute and (level, seed) not in saved_by_setting
                             else 'saved RAI; analyzed locally', parameters, run['rows']))
        # Explicitly ignore Knows strength attributes: this reference is unweighted.
        communities = nx.community.louvain_communities(graph, weight=None, resolution=1,
                                                       threshold=1e-7, max_level=level, seed=seed)
        nx_rows = []
        for label, members in enumerate(communities):
            scores = nx.betweenness_centrality(graph.subgraph(members), k=None,
                                               normalized=False, weight=None, endpoints=False)
            nx_rows.extend(dict(person_id=p, name=data.pname(p), community=label, betweenness=scores[p])
                           for p in sorted(members))
        nx_parameters = dict(max_level=level, seed=seed, weight=None, resolution=1, threshold=1e-7, k=None)
        variants.append(('NetworkX', 'local NetworkX reference', nx_parameters, nx_rows))
        for method, origin, options, rows in variants:
            result = summarize_people_communities(rows, data, graph, method=method, parameters=options)
            identifier = f'{method}:levels={level}:seed={seed}'
            summaries = result['communities']
            result.update(id=identifier, origin=origin, focus=community_focus(oracle, data, summaries))
            reports.append(result)
            partitions.append(dict(id=identifier, method=method, max_levels=level, seed=seed,
                membership={p: c['community'] for c in summaries for p in c['person_ids']}))
    artifact['analysis'] = dict(runs=reports, pending_rai_runs=pending,
        stability=compare_community_partitions(partitions, graph), networkx_version=nx.__version__,
        metric='Unweighted modularity at resolution 1; adjusted Rand index (1 = identical '
               'co-membership, 0 = chance agreement). Also reported without graph isolates.',
        caveat='RAI and NetworkX have different tolerances and implementations; equal seeds or '
               'level caps do not imply identical partitions. Level caps do not prove convergence. '
               'RAI seed stability requires multiple available RAI seeds at the same level cap.')
    if output_path:
        Path(output_path).write_text(json.dumps(artifact, indent=2)+'\n')
    print(json.dumps(artifact['analysis'], indent=2), flush=True)
    return artifact


def run_people_communities(oracle_pairs, *, max_levels=1, randomization_seed=42):
    """Only called inside the existing source, engine, and no-mutation guards."""
    from pe_deal_graph.model.core import model, Person, Knows, SOURCE_TABLES, BETWEENNESS_PIVOTS
    import pe_deal_graph.model.rules
    from pe_deal_graph.model.graphs import knows_graph, people_community_relations
    from guarded_people_count import require_table_sources
    from relationalai.semantics import Integer, Float
    require_table_sources(SOURCE_TABLES.values())
    oracle = runpy.run_path(str(ROOT/'data/oracle.py'))
    data = oracle['Data']()
    if len(data.person) > BETWEENNESS_PIVOTS: raise RuntimeError('Exact centrality pivot cap exceeded')
    # Compare actual graph inputs before algorithms; no count-only shortcut.
    edges = model.where(Knows.strength >= MIN_TIE_STRENGTH).select(
        Knows.p1.id.alias('p1'), Knows.p2.id.alias('p2'), Knows.strength.alias('strength')).to_df().to_dict('records')
    if len(edges) != len(oracle_pairs) or {(r['p1'],r['p2']) for r in edges} != set(oracle_pairs):
        raise RuntimeError('Live Knows pairs differ from baseline oracle')
    parameters = community_parameters(max_levels, randomization_seed)
    if BETWEENNESS_PIVOTS != parameters['num_pivots']:
        raise RuntimeError('Centrality pivot settings changed')
    labels, centrality = people_community_relations(knows_graph, max_levels=max_levels,
                                                   randomization_seed=randomization_seed)
    p, label, score = Person.ref(), Integer.ref(), Float.ref()
    rows = model.where(labels(p,label),centrality(p,score)).select(
        p.id.alias('person_id'),p.name.alias('name'),label.alias('community'),score.alias('betweenness')).to_df().to_dict('records')
    rows = [dict(row, community=int(row['community']), betweenness=float(row['betweenness'])) for row in rows]
    return dict(origin='live RAI', sdk_version='1.27.1', parameters=parameters, rows=rows)


def run_knows_count(oracle_pairs):
    # Called only inside guarded_people_count's process-local guard context.
    from pe_deal_graph.model.core import model, Knows, SOURCE_TABLES
    from guarded_people_count import require_table_sources
    import pe_deal_graph.model.rules  # Existing definitions; no graph algorithms.
    require_table_sources(SOURCE_TABLES.values())
    from relationalai.semantics.std import aggregates as aggs

    result = model.select(
        aggs.count(Knows).where(Knows.strength >= MIN_TIE_STRENGTH).alias("connections")
    ).to_df()
    if len(result) != 1:
        raise RuntimeError("Expected exactly one count row")
    count = int(result["connections"].iloc[0])
    print(f"RAI Knows: {count}; local oracle: {len(oracle_pairs)}; delta: {count - len(oracle_pairs):+d}")
    if count == len(oracle_pairs):
        print("COUNT MATCH (pair identity equality has not been checked)")
        return

    # One diagnostic read on mismatch; no retries or repairs.
    pairs = model.where(Knows.strength >= MIN_TIE_STRENGTH).select(
        Knows.p1.id.alias("p1"), Knows.p2.id.alias("p2"),
        Knows.strength.alias("strength"),
    ).to_df().to_dict(orient="records")
    report = compare_pairs(pairs, oracle_pairs)
    report["aggregate_count"] = count
    path = ROOT / "artifacts/knows_oracle_difference.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"Missing pairs: {len(report['missing_pairs'])}; extra pairs: {len(report['extra_pairs'])}; details: {path}")
    raise RuntimeError("Knows count differs from oracle; evidence saved, no rules changed")


def prepare_route_examples():
    """Deterministically select shortest routes from one existing introduction seed."""
    import networkx as nx
    pairs = prepare_oracle()  # Includes the unchanged 0.0 threshold check.
    oracle = runpy.run_path(str(ROOT / "data/oracle.py"))
    data = oracle["Data"]()
    graph = nx.Graph()
    graph.add_nodes_from(sorted(data.person))  # Include isolated people.
    graph.add_edges_from(sorted(pairs))
    for source in oracle["our_seeds"](data):
        distances = nx.single_source_shortest_path_length(graph, source)
        unreachable = sorted(set(graph) - set(distances))
        if not unreachable or not all(h in distances.values() for h in (1, 2, 3)):
            continue
        examples = []
        for hops in (1, 2, 3, None):
            target = unreachable[0] if hops is None else min(
                person for person, distance in distances.items() if distance == hops)
            path = [] if hops is None else nx.shortest_path(graph, source, target)
            example = {"source": source, "source_name": data.pname(source),
                       "target": target, "target_name": data.pname(target),
                       "hops": hops, "path": path,
                       "path_names": [data.pname(person) for person in path]}
            examples.append(example)
            print(json.dumps(example))
        return examples
    raise RuntimeError("Oracle cannot supply all four route cases from one seed")


def validate_route_distances(examples, endpoint_ids, rows):
    """An absent distance means unreachable only after positive controls pass."""
    source = examples[0]["source"]
    required = {source} | {e["target"] for e in examples}
    if set(endpoint_ids) != required:
        raise RuntimeError("Route endpoints missing or unexpected in RAI")
    observed = {}
    for row in rows:
        target, hops = row["target"], row["hops"]
        if row["source"] != source or target not in required or target in observed:
            raise RuntimeError("Unexpected or duplicate distance row")
        if isinstance(hops, bool) or int(hops) != hops or hops < 0:
            raise RuntimeError("Invalid graph distance")
        observed[target] = int(hops)
    if observed.get(source) != 0:
        raise RuntimeError("Missing seed self-distance; cannot trust unreachable result")
    for example in examples:
        if observed.get(example["target"]) != example["hops"]:
            raise RuntimeError(f"Shortest-distance mismatch: {example['source']} -> {example['target']}")


def validate_route_edges(examples, rows):
    edges = {tuple(sorted((r["p1"], r["p2"]))) for r in rows}
    for example in examples:
        path = example["path"]
        for a, b in zip(path, path[1:]):
            if tuple(sorted((a, b))) not in edges:
                raise RuntimeError(f"Oracle route edge missing in RAI: {a} -> {b}")


def run_person_routes(examples):
    """Three guarded reads: endpoints, shortest distances, and route edge witnesses."""
    from pe_deal_graph.model.core import model, Person, Knows, SOURCE_TABLES
    from guarded_people_count import require_table_sources
    from relationalai.semantics import Integer
    import pe_deal_graph.model.rules
    import pe_deal_graph.model.graphs as graphs
    if graphs.MIN_TIE_STRENGTH != 0.0:
        raise RuntimeError("Graph threshold changed")
    require_table_sources(SOURCE_TABLES.values())
    source = examples[0]["source"]
    endpoints = sorted({source} | {e["target"] for e in examples})
    people = model.where(Person.id.in_(endpoints)).select(Person.id.alias("id")).to_df()
    if set(people["id"]) != set(endpoints):
        raise RuntimeError("An example endpoint is missing; stopping before graph checks")

    seed, target, hops = Person.ref(), Person.ref(), Integer.ref()
    distances = model.where(
        Person.seed_hops(seed, target, hops), seed.id == source, target.id.in_(endpoints),
    ).select(seed.id.alias("source"), target.id.alias("target"), hops.alias("hops")).to_df()
    validate_route_distances(examples, people["id"], distances.to_dict(orient="records"))

    route_nodes = sorted({p for e in examples for p in e["path"]})
    edges = model.where(
        Knows.strength >= MIN_TIE_STRENGTH,
        Knows.p1.id.in_(route_nodes), Knows.p2.id.in_(route_nodes),
    ).select(Knows.p1.id.alias("p1"), Knows.p2.id.alias("p2")).to_df()
    validate_route_edges(examples, edges.to_dict(orient="records"))
    for e in examples:
        print(f"PASS {e['source_name']} -> {e['target_name']}: "
              + ("unreachable" if e["hops"] is None else f"{e['hops']} hops; route edges verified"))


def prepare_person_path_examples(source_id=None, target_id=None, *, remaining=False, long_paths=False):
    """Oracle expectations for explicit IDs or a non-seed regression suite."""
    import networkx as nx
    pairs = prepare_oracle()
    oracle = runpy.run_path(str(ROOT / "data/oracle.py"))
    data = oracle["Data"]()
    seeds = set(oracle["our_seeds"](data))
    graph = nx.Graph()
    graph.add_nodes_from(sorted(data.person))
    graph.add_edges_from(sorted(pairs))
    if (source_id is None) != (target_id is None):
        raise ValueError("Both person IDs are required")
    remaining_expected = {"P31852": 1, "P37083": 2, "P10034": 0, "P10001": None}
    long_expected = {"P19694": 4, "P11562": 5}
    if long_paths:
        if remaining or source_id is not None or target_id is not None:
            raise ValueError("Long-path batch cannot be combined with other selections")
        requests = [("P10034", target) for target in long_expected]
        if any(p not in graph or p in seeds for pair in requests for p in pair):
            raise RuntimeError("Reviewed long-path non-seed endpoints changed")
    elif remaining:
        if source_id is not None or target_id is not None:
            raise ValueError("Remaining batch uses the previously reviewed person IDs")
        requests = [("P10034", target) for target in remaining_expected]
        if "P10034" in seeds or any(p not in graph for pair in requests for p in pair):
            raise RuntimeError("Reviewed non-seed batch endpoints changed")
    elif source_id is not None:
        missing = {source_id, target_id} - set(graph)
        if missing:
            raise ValueError(f"Unknown oracle person IDs: {sorted(missing)}")
        requests = [(source_id, target_id)]
    else:
        requests = []
        for source in sorted(set(graph) - seeds):
            distances = nx.single_source_shortest_path_length(graph, source)
            unreachable = sorted(set(graph) - set(distances))
            if unreachable and all(h in distances.values() for h in (1, 2, 3)):
                requests = [(source, min(p for p, h in distances.items() if h == hops))
                            for hops in (1, 2, 3)]
                requests += [(source, source), (source, unreachable[0]),
                             (requests[-1][1], source)]
                break
        if not requests:
            raise RuntimeError("No non-seed oracle source covers all required cases")
    examples = []
    for source, target in requests:
        paths = nx.single_source_shortest_path(graph, source)
        path = paths.get(target, [])
        example = {"source": source, "target": target,
                   "source_name": data.pname(source), "target_name": data.pname(target),
                   "source_is_seed": source in seeds,
                   "hops": len(path) - 1 if path else None, "path": path,
                   "path_names": [data.pname(p) for p in path]}
        if remaining and example["hops"] != remaining_expected[target]:
            raise RuntimeError(f"Oracle distance changed for reviewed pair {source} -> {target}")
        if long_paths and example["hops"] != long_expected[target]:
            raise RuntimeError(f"Oracle distance changed for reviewed pair {source} -> {target}")
        # Strongest shortest route under the same product-of-strengths rule.
        if len(path) > 1:
            knows = oracle["build_knows"](data, seeds)
            example["best_strength"] = round(max(
                oracle["path_strength"](knows, p) for p in nx.all_shortest_paths(graph, source, target)), 6)
        examples.append(example)
        print(json.dumps(example))
    return examples


def run_arbitrary_person_paths(examples):
    """Run under existing guards; validate distance and each returned route edge."""
    from pe_deal_graph.queries import q_person_path
    oracle_pairs = prepare_oracle()
    for example in examples:
        result = q_person_path(example["source"], example["target"])
        expected_status = ("self" if example["source"] == example["target"] else
                           "unreachable" if example["hops"] is None else "reachable")
        if result["distance"] != example["hops"] or result["status"] != expected_status:
            raise RuntimeError(f"Path differs from oracle: {result}")
        route = result["route"]
        if example["hops"] is None:
            if route:
                raise RuntimeError("Unreachable result contains a route")
        elif (not route or route[0] != example["source"] or route[-1] != example["target"]
              or len(route) - 1 != example["hops"] or len(set(route)) != len(route)
              or any(tuple(sorted(edge)) not in oracle_pairs for edge in zip(route, route[1:]))):
            raise RuntimeError(f"Route witness differs from oracle: {result}")
        if "best_strength" in example and "route_strength" in result \
                and abs(result["route_strength"] - example["best_strength"]) > 1e-6:
            raise RuntimeError(f"Route is not the strongest shortest route "
                               f"(expected {example['best_strength']}): {result}")
        print("PASS " + json.dumps(result))


def fixed_probe_oracle_rows():
    """All expected rows for the two fixed sources, including self distances."""
    import networkx as nx
    oracle = runpy.run_path(str(ROOT / "data/oracle.py"))
    data = oracle["Data"]()
    pairs = oracle["build_knows"](data, set(oracle["our_seeds"](data)))
    graph = oracle["knows_graph"](data, pairs)
    return [{"source": source, "target": target, "hops": hops}
            for source in ("P10034", "P10451")
            for target, hops in sorted(nx.single_source_shortest_path_length(graph, source).items())]


def validate_fixed_probe_rows(rows):
    """Fail on duplicates, omissions, extra sources/targets, or wrong distances."""
    expected = {(r["source"], r["target"]): r["hops"] for r in fixed_probe_oracle_rows()}
    actual = {}
    for row in rows:
        key = (row["source"], row["target"])
        if key in actual or row["hops"] != expected.get(key):
            raise RuntimeError("Fixed probe has a duplicate, unexpected pair, or wrong distance")
        actual[key] = row["hops"]
    if actual != expected:
        raise RuntimeError("Fixed probe is incomplete; cannot infer unreachable")


def seed_probe_oracle_rows():
    """Independent per-seed BFS, never all-pairs; include each source's self row."""
    import networkx as nx
    oracle = runpy.run_path(str(ROOT / 'data/oracle.py'))
    if PROBE_FIXTURE != 'baseline':
        oracle['load_csv'].__globals__['CSV_DIR'] = fixture_directory(PROBE_FIXTURE)
    data = oracle['Data']()
    if data.manifest_mismatches: raise RuntimeError('Fixture manifest mismatch')
    seeds = oracle['our_seeds'](data)
    graph = oracle['knows_graph'](data, oracle['build_knows'](data, set(seeds), include_evidence=PROBE_FIXTURE!='connected1m'))
    return seeds, [dict(source=source, target=target, hops=hops)
                   for source in seeds
                   for target, hops in sorted(nx.single_source_shortest_path_length(graph, source).items())]


def validate_seed_probe_rows(rows, live_seeds):
    seeds, expected_rows = seed_probe_oracle_rows()
    if len(live_seeds) != len(set(live_seeds)) or set(live_seeds) != set(seeds):
        raise RuntimeError('Deployed OurSeed membership differs from the independent oracle')
    expected = {(r['source'], r['target']): r['hops'] for r in expected_rows}
    actual = {}
    for row in rows:
        key = row['source'], row['target']
        if key in actual or key not in expected or row['hops'] != expected[key]:
            raise RuntimeError('Seed distances contain duplicates, unexpected pairs, or wrong distances')
        actual[key] = row['hops']
    if actual != expected: raise RuntimeError('Seed distances are incomplete')
    return dict(seed_count=len(seeds), reachable_distance_rows=len(actual),
                self_rows=len(seeds), nonself_rows=len(actual)-len(seeds), correctness='PASS')


PROBE_SOURCE = f"{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_DEPLOY_SRC"
PROBE_OUTPUT = f"{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_DEPLOY"
PROBE_META = PROBE_OUTPUT + "_META"


PROBE_FIXTURE = 'baseline'

def fixture_directory(fixture):
    return ROOT / 'data' / {'sparse': 'scale_sparse_seed_10k', 'connected': 'scale_connected_10k', 'connected100k': 'scale_connected_100k', 'connected1m': 'scale_connected_1m'}[fixture]


def select_probe_fixture(fixture):
    global PROBE_SOURCE, PROBE_OUTPUT, PROBE_META, PROBE_FIXTURE
    import os
    suffix = {'baseline': 'DEPLOY', 'sparse': 'SPARSE_10K', 'connected': 'CONNECTED_10K', 'connected100k': 'CONNECTED_100K', 'connected1m': 'CONNECTED_1M'}[fixture]
    PROBE_FIXTURE = fixture
    PROBE_OUTPUT = f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_' + suffix
    PROBE_SOURCE, PROBE_META = PROBE_OUTPUT + '_SRC', PROBE_OUTPUT + '_META'
    os.environ['PE_DEAL_GRAPH_PROBE_FIXTURE'] = fixture


def prepare_copied_distance_probe():
    """Describe targets without connecting or compiling a deployment."""
    return {
        "source": PROBE_SOURCE, "output": PROBE_OUTPUT, "metadata": PROBE_META,
        "role": f"{_cfg.DEPLOY_ROLE}", "warehouse": f"{_cfg.WAREHOUSE}",
        "deployment": {
            "schema": PROBE_OUTPUT, "meta_schema": PROBE_META,
            "role": f"{_cfg.DEPLOY_ROLE}", "auto_deploy": False,
            "schedules": {"path_probe": {"interval_s": 0, "run_on_deploy": False}},
            "outputs": {"type": "table", "schedule": "path_probe"}},
    }


def probe_date_views_sql():
    """Two views over experiment copies; original source tables stay untouched."""
    as_of = "CAST('2026-10-01' AS DATE)"
    return [
        f"CREATE OR REPLACE VIEW {PROBE_OUTPUT}.{name}_NORMALIZED AS "
        f"SELECT *, COALESCE(END_DATE, {as_of}) AS EFFECTIVE_END_DATE, "
        f"(START_DATE <= {as_of} AND (END_DATE IS NULL OR END_DATE > {as_of})) AS IS_CURRENT "
        f"FROM {PROBE_SOURCE}.{name}"
        for name in ("ROLE_HISTORY", "OWNERSHIP")
    ]


def build_deployment_probe():
    """Load the existing probe with a dedicated SDK configuration/session."""
    import os
    from relationalai.config import create_config, DeploymentConfig
    from relationalai.config.config import ambient_model_config

    if any(k.startswith("pe_deal_graph.model") for k in sys.modules):
        raise RuntimeError("Run deployment in a fresh Python process")
    os.environ.pop("DEBUG", None)
    os.environ["RAI_CONFIG_FILE_PATH"] = str(ROOT / "raiconfig.yaml")
    os.environ["PE_DEAL_GRAPH_BUILD_PROFILE"] = "copied-distance-probe"
    os.environ["PE_DEAL_GRAPH_FINALE"] = "0"
    cfg = create_config()
    conn = cfg.get_default_connection()
    conn.role, conn.warehouse = f"{_cfg.DEPLOY_ROLE}", f"{_cfg.WAREHOUSE}"
    conn.database, conn.schema_ = PROBE_SOURCE.split(".")
    cfg.oplog.enabled = False
    cfg.execution.retries.enabled = False
    cfg.deployment = DeploymentConfig(**prepare_copied_distance_probe()["deployment"])
    # SDK 1.27.1 otherwise may adopt an unrelated active Snowpark session.
    session = conn._create_new_session()
    try:
        cfg = create_config(snowflake_session=session, **cfg.model_dump())
        context = session.sql('SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE()').collect()[0]
        if tuple(context) != (f'{_cfg.DEPLOY_ROLE}', f'{_cfg.WAREHOUSE}', f'{_cfg.DATABASE}'):
            raise RuntimeError('Deployment session context changed')
        tasks = session.sql(f"SELECT STATE FROM TABLE({_cfg.DATABASE}.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME=>'REFRESH_PATH_PROBE',RESULT_LIMIT=>100)) WHERE DATABASE_NAME='{_cfg.DATABASE}' AND SCHEMA_NAME='{PROBE_META.split('.')[1]}' AND STATE IN ('EXECUTING','SCHEDULED')").collect()
        if tasks: raise RuntimeError('An experiment refresh is already active; stop without changes')
        seeds, _ = seed_probe_oracle_rows()
        if PROBE_FIXTURE != 'baseline':
            import importlib.util
            spec = importlib.util.spec_from_file_location('fixture_loader', ROOT / 'data/load.py')
            loader = importlib.util.module_from_spec(spec); spec.loader.exec_module(loader)
            for schema in (PROBE_OUTPUT, PROBE_META):
                if session.sql(f'SHOW OBJECTS IN SCHEMA {schema}').collect():
                    raise RuntimeError('Fixture deployment target is not empty; stop')
            loader.verify_fixture_session(session, PROBE_FIXTURE)
            live_seeds = seeds  # Full source contents authenticated above; derived seeds checked after refresh.
        else:
            live_seeds = [r[0] for r in session.sql(f'SELECT ID FROM {PROBE_OUTPUT}.OURSEED ORDER BY ID').collect()]
        if live_seeds != seeds: raise RuntimeError('Existing seed membership differs from oracle')
        print(json.dumps({'verified_seed_count': len(seeds), 'seed_ids': seeds}), flush=True)
        for sql in probe_date_views_sql():
            session.sql(sql).collect()
        with ambient_model_config(cfg):
            from pe_deal_graph.model import core, graphs
        return core.model, session
    except Exception:
        session.close()
        raise


def minimum_distance_merge(query):
    """Keep the best known distance across old state AND new candidates."""
    from relationalai.semantics.backends.sql.sql_ir import (
        SQLSelectQuery, SQLSelectItem, SQLColumnRef, SQLFunctionCall,
        SQLFromItem, SQLSubquerySource,
    )
    return SQLSelectQuery(
        select=(SQLSelectItem(SQLColumnRef("NODE_U"), alias="NODE_U"),
                SQLSelectItem(SQLColumnRef("NODE_V"), alias="NODE_V"),
                SQLSelectItem(SQLFunctionCall("MIN", (SQLColumnRef("D"),)), alias="D")),
        from_item=SQLFromItem(source=SQLSubquerySource(query), alias="distance_candidates"),
        group_by=(SQLColumnRef("NODE_U"), SQLColumnRef("NODE_V")),
    )


def deploy_distance_probe(model):
    """SDK 1.27.1 workaround, limited to this probe's distance relation.

    Its SQL lowerer unions recursive aggregate state without re-aggregating.
    On cycles that retains increasing walk lengths indefinitely. Re-minimize
    accumulated + candidate distances before computing the next delta. The
    installed SDK and the normal interactive graph path remain unchanged.
    Remove this compatibility shim when the upstream compiler is fixed.
    """
    from unittest.mock import patch
    from relationalai.semantics.backends.sql.lowerer import Lowerer
    from relationalai.semantics.backends.sql.orchestrator import PlanTable
    from relationalai.semantics.backends.sql.snowflake_backend import SnowflakeBackend
    from v0.relationalai.clients.resources.snowflake.snowflake import Resources
    original_entries = PlanTable.write_entries
    def sql_only_plan(manager, meta, entries):
        if meta != PROBE_META or not entries or any(e.reasoner != 'sql' or e.schedule_name != 'path_probe' for e in entries):
            raise RuntimeError('Unexpected deployment plan; source/stream changes forbidden')
        return original_entries(manager, meta, entries)
    def existing_schema(backend, schema_name, **kw):
        if schema_name not in (PROBE_OUTPUT, PROBE_META): raise RuntimeError('Unreviewed schema')
        rows = backend._session.sql(f'SHOW SCHEMAS IN DATABASE {_cfg.DATABASE}').collect()
        if not any(r['name'] == schema_name.split('.')[1] and r['owner'] == f'{_cfg.ADMIN_ROLE}' for r in rows):
            raise RuntimeError('Reviewed schema identity/owner changed')
        return False
    def no_stream_changes(*a, **kw):
        raise RuntimeError('Native-app stream/engine mutation is forbidden')
    original = Lowerer._coalesce_target_query
    target_name = (PROBE_OUTPUT +
        ".PERSON_PERSON_NODE_U_AND_PERSON_NODE_V_HAVE_A_DISTANCE_OF_NUMBER_38_0_D")

    def coalesce(lowerer, target, selects, **kwargs):
        query = original(lowerer, target, selects, **kwargs)
        if target.object_name.replace('"', '').upper() == target_name:
            if tuple(c.upper() for c in target.column_names) != ("NODE_U", "NODE_V", "D"):
                raise RuntimeError("Distance relation layout changed; update compatibility fix")
            return minimum_distance_merge(query)
        return query

    with patch.object(Lowerer, "_coalesce_target_query", coalesce), \
         patch.object(PlanTable, 'write_entries', sql_only_plan), \
         patch.object(SnowflakeBackend, 'create_schema_if_not_exists', existing_schema), \
         patch.object(Resources, '_exec', no_stream_changes):
        model.deploy(wait=False, force=False)


def refresh_distance_probe(session, timeout=1800):
    """Run the manual SDK task once and compare the resulting distances."""
    tasks = session.sql(f'SHOW TASKS IN SCHEMA {PROBE_META}').collect()
    if (len(tasks) != 1 or tasks[0]['name'] != 'REFRESH_PATH_PROBE' or
            tasks[0]['owner'] != f'{_cfg.DEPLOY_ROLE}' or tasks[0]['warehouse'] != f'{_cfg.WAREHOUSE}' or
            tasks[0]['state'].lower() != 'suspended' or tasks[0]['schedule']):
        raise RuntimeError('Manual task scope/schedule changed')
    params = session.sql(f"SHOW PARAMETERS LIKE 'TASK_AUTO_RETRY_ATTEMPTS' IN TASK {PROBE_META}.REFRESH_PATH_PROBE").collect()
    if len(params) != 1 or str(params[0]['value']) != '0': raise RuntimeError('Task retries must already be disabled')
    wall_start = time.perf_counter()
    started = session.sql("SELECT CURRENT_TIMESTAMP() AS T").collect()[0][0]
    session.sql(f"EXECUTE TASK {PROBE_META}.REFRESH_PATH_PROBE").collect()
    deadline = time.monotonic() + timeout
    while True:
        rows = session.sql(
            "SELECT STATE, ERROR_MESSAGE, QUERY_ID, SCHEDULED_TIME, QUERY_START_TIME, COMPLETED_TIME FROM TABLE("
            f"{_cfg.DATABASE}.INFORMATION_SCHEMA.TASK_HISTORY("
            "TASK_NAME=>'REFRESH_PATH_PROBE', SCHEDULED_TIME_RANGE_START=>TO_TIMESTAMP_LTZ(?), RESULT_LIMIT=>100)) "
            f"WHERE DATABASE_NAME='{_cfg.DATABASE}' "
            f"AND SCHEMA_NAME='{PROBE_META.split('.')[1]}' "
            "ORDER BY SCHEDULED_TIME DESC", params=[started.isoformat()]).collect()
        if len(rows) > 1: raise RuntimeError("More than one manual refresh run")
        if rows and rows[0]["STATE"] == "SUCCEEDED":
            break
        if rows and rows[0]["STATE"] in {"FAILED", "CANCELLED", "SKIPPED"}:
            raise RuntimeError(f"Refresh stopped: {rows[0]}")
        if time.monotonic() >= deadline:
            raise TimeoutError("Refresh still pending; task left running. Check Snowflake task history.")
        print("Waiting for the manual refresh...", flush=True)
        time.sleep(10)
    task_run = rows[0]
    refresh_wall_seconds = time.perf_counter() - wall_start
    rows = session.sql(
        f'SELECT SOURCE_ID AS "source", TARGET_ID AS "target", HOPS AS "hops" '
        f'FROM {PROBE_OUTPUT}.PERSONDISTANCEPROBE').collect()
    live_seeds = [r[0] for r in session.sql(f'SELECT ID FROM {PROBE_OUTPUT}.OURSEED ORDER BY ID').collect()]
    result = validate_seed_probe_rows([r.as_dict() for r in rows], live_seeds)
    result.update(refresh_query_id=task_run['QUERY_ID'],
                  refresh_execution_seconds=(task_run['COMPLETED_TIME']-task_run['QUERY_START_TIME']).total_seconds(),
                  refresh_scheduled_to_complete_seconds=(task_run['COMPLETED_TIME']-task_run['SCHEDULED_TIME']).total_seconds(),
                  refresh_observed_seconds=refresh_wall_seconds)
    print(json.dumps(result), flush=True)
    return result


def run_copied_distance_probe(*, execute=False, refresh=False):
    if not execute:
        print(json.dumps(prepare_copied_distance_probe(), indent=2))
        return
    model, session = build_deployment_probe()
    try:
        print(f"Deploying to {PROBE_OUTPUT} as {_cfg.DEPLOY_ROLE} on {_cfg.WAREHOUSE}", flush=True)
        deploy_distance_probe(model)
        print("SDK deployment returned successfully", flush=True)
        if refresh:
            refresh_distance_probe(session)
    finally:
        session.close()


def distance_lookup_cases():
    """Local oracle only; both materialized sources, deterministic 1–5/self/unreachable."""
    oracle = runpy.run_path(str(ROOT / 'data/oracle.py'))
    data = oracle['Data']()
    expected = fixed_probe_oracle_rows()
    cases = []
    for source in ('P10034', 'P10451'):
        distances = {r['target']: r['hops'] for r in expected if r['source'] == source}
        for hops in range(1, 6):
            targets = sorted(t for t, d in distances.items() if d == hops)
            if not targets: raise RuntimeError(f'No oracle example at {hops} hops from {source}')
            cases.append(dict(source=source, target=targets[0], expected=hops, case=f'{hops} hops'))
        cases.append(dict(source=source, target=source, expected=0, case='self'))
        unreachable = sorted(set(data.person) - set(distances))
        if not unreachable: raise RuntimeError('No oracle unreachable example')
        cases.append(dict(source=source, target=unreachable[0], expected=None, case='unreachable'))
    return cases


def seed_lookup_cases(seeds, expected_rows, people):
    """Select 1–5-hop, self and unreachable examples for every stored seed."""
    by_source = {seed:{} for seed in seeds}
    for row in expected_rows:
        by_source[row['source']][row['target']] = row['hops']
    cases=[]
    for source in seeds:
        distances=by_source[source]
        for hops in range(1,6):
            targets=sorted(t for t,d in distances.items() if d==hops)
            if not targets: raise RuntimeError(f'No {hops}-hop example from {source}')
            cases.append(dict(source=source,target=targets[0],expected=hops,case=f'{hops} hops'))
        cases.append(dict(source=source,target=source,expected=0,case='self'))
        unreachable=sorted(set(people)-set(distances))
        if not unreachable: raise RuntimeError('No unreachable control')
        cases.append(dict(source=source,target=unreachable[0],expected=None,case='unreachable'))
    return cases


def benchmark_distance_lookups():
    """Direct connector SELECTs only. Never imports model/SDK or computes graph SQL."""
    from statistics import median
    from datetime import datetime
    from zoneinfo import ZoneInfo
    prep_start = time.perf_counter()
    import yaml
    import snowflake.connector
    import csv
    seeds, expected_rows = seed_probe_oracle_rows()
    directory = ROOT/'data/csv' if PROBE_FIXTURE=='baseline' else fixture_directory(PROBE_FIXTURE)
    with (directory/'PERSON.csv').open() as fh:
        people = [r['person_id'] for r in csv.DictReader(fh)]
    cases = seed_lookup_cases(seeds, expected_rows, people)
    expected_pairs = {(r['source'],r['target']):r['hops'] for r in expected_rows}
    cfg = yaml.safe_load((ROOT / 'raiconfig.yaml').read_text())
    saved = cfg['connections'][cfg['default_connection']]
    if saved['authenticator'] != 'programmatic_access_token':
        raise RuntimeError('Unexpected authentication configuration')
    parameters = {k: saved[k] for k in ('account', 'user', 'authenticator', 'token')}
    parameters.update(role=f'{_cfg.DEPLOY_ROLE}', warehouse=f'{_cfg.WAREHOUSE}', database=f'{_cfg.DATABASE}',
                      schema=PROBE_OUTPUT.split('.')[1])
    report = {'label': f'lookup over {len(seeds)} precomputed team sources', 'fixture': PROBE_FIXTURE,
              'measured_at': datetime.now(ZoneInfo('America/New_York')).isoformat(),
              'table': PROBE_OUTPUT + '.PERSONDISTANCEPROBE',
              'local_preparation_ms': (time.perf_counter()-prep_start)*1000}
    start = time.perf_counter()
    connection = snowflake.connector.connect(**parameters)
    report['connection_ms'] = (time.perf_counter()-start)*1000
    try:
        cursor = connection.cursor()
        def read(sql, params=None):
            if not sql.lstrip().upper().startswith(('SELECT ', 'SHOW ')):
                raise RuntimeError('Benchmark permits SELECT/SHOW only')
            cursor.execute(sql, params)
            return cursor.fetchall()
        start = time.perf_counter()
        context = read('SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_SESSION()')[0]
        if context[:4] != (f'{_cfg.DEPLOY_ROLE}', f'{_cfg.WAREHOUSE}', f'{_cfg.DATABASE}', PROBE_OUTPUT.split('.')[1]):
            raise RuntimeError('Unexpected benchmark session context')
        report['session_id'] = context[4]
        cache = read("SHOW PARAMETERS LIKE 'USE_CACHED_RESULT' IN SESSION")
        names = [c[0].lower() for c in cursor.description]
        report['cache_settings'] = [dict(zip(names, row)) for row in cache]
        wh = read(f"SHOW WAREHOUSES LIKE '{_cfg.WAREHOUSE}'")
        names = [c[0].lower() for c in cursor.description]
        report['warehouse'] = [{k:v for k,v in dict(zip(names,row)).items()
                                if k in ('name','state','size','auto_suspend','auto_resume')} for row in wh]
        tables = read(f"SHOW TABLES LIKE 'PERSONDISTANCEPROBE' IN SCHEMA {PROBE_OUTPUT}")
        names = [c[0].lower() for c in cursor.description]
        tables = [dict(zip(names,row)) for row in tables]
        if len(tables) != 1 or tables[0]['name'] != 'PERSONDISTANCEPROBE' or tables[0]['owner'] != f'{_cfg.DEPLOY_ROLE}':
            raise RuntimeError('Materialized distance table identity changed')
        report['table_created_on'] = str(tables[0]['created_on'])
        if read(f"SELECT STATE FROM {PROBE_META}._INTERNAL_DEPLOY_STATE") != [('SUCCESS',)]:
            raise RuntimeError('Deployment is not successful')
        full_sql = f'SELECT SOURCE_ID, TARGET_ID, HOPS FROM {report["table"]}'
        before = read(full_sql)
        if len(before)!=len(expected_pairs) or {(a,b):c for a,b,c in before}!=expected_pairs:
            raise RuntimeError('Persisted distances differ from complete seed oracle')
        report['validated_distance_rows']=len(before)
        refresh_log_sql=f'SELECT COUNT(*),HASH_AGG(*) FROM {PROBE_META}._INTERNAL_REFRESH_LOG'
        refresh_before=read(refresh_log_sql)
        active=read(f"SELECT STATE FROM TABLE({_cfg.DATABASE}.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME=>'REFRESH_PATH_PROBE',RESULT_LIMIT=>100)) WHERE SCHEMA_NAME='{PROBE_META.split('.')[1]}' AND STATE IN ('EXECUTING','SCHEDULED')")
        if active: raise RuntimeError('Refresh is active; do not benchmark changing outputs')
        report['preflight_ms'] = (time.perf_counter()-start)*1000
        report['preflight_note'] = f'Read all {len(before)} materialized rows before timing to verify completeness; first measured runs are not assumed cold. Warehouse state is recorded after connection/setup.'
        query = f'SELECT HOPS FROM {report["table"]} WHERE SOURCE_ID = %s AND TARGET_ID = %s'
        report['sql'] = query
        for case in cases:
            case['runs'] = []
            for number in range(1, 6):
                start = time.perf_counter()
                rows = read(query, (case['source'], case['target']))
                elapsed = (time.perf_counter()-start)*1000
                expected = [] if case['expected'] is None else [(case['expected'],)]
                if rows != expected: raise RuntimeError(f'Lookup disagrees with oracle: {case}')
                case['runs'].append(dict(run=number, query_id=cursor.sfqid, python_ms=elapsed))
        start = time.perf_counter()
        history = read(f"SELECT QUERY_ID,TOTAL_ELAPSED_TIME,EXECUTION_TIME,COMPILATION_TIME,QUEUED_PROVISIONING_TIME,QUEUED_OVERLOAD_TIME,EXECUTION_STATUS FROM TABLE({_cfg.DATABASE}.INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION(RESULT_LIMIT=>10000))")
        by_id = {row[0]: row for row in history}
        for case in cases:
            for run in case['runs']:
                h = by_id.get(run['query_id'])
                if h is None or h[6] != 'SUCCESS': raise RuntimeError('Missing successful server timing evidence')
                run.update(snowflake_ms=h[1], execution_ms=h[2], compilation_ms=h[3],
                           queued_provisioning_ms=h[4], queued_overload_ms=h[5])
            case['first'] = {k: case['runs'][0][k] for k in ('snowflake_ms','python_ms')}
            case['median_runs_2_to_5'] = {k: median(r[k] for r in case['runs'][1:]) for k in ('snowflake_ms','python_ms')}
        after = read(full_sql)
        if sorted(before) != sorted(after): raise RuntimeError('Materialized distances changed during measurement')
        report['history_and_postcheck_ms'] = (time.perf_counter()-start)*1000
        if read(refresh_log_sql)!=refresh_before: raise RuntimeError('Refresh log changed during benchmark')
        report['refresh_log_unchanged']=True
        report['cases'] = cases
        report['result'] = 'PASS'
        if any(n == 'pe_deal_graph.model' or n.startswith('pe_deal_graph.model.') for n in sys.modules):
            raise RuntimeError('Benchmark unexpectedly imported the model')
        print(json.dumps(report, indent=2, default=str), flush=True)
        return report
    finally:
        connection.close()


COMMUNITY_OUTPUT = f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_COMMUNITY'
COMMUNITY_META = COMMUNITY_OUTPUT + '_META'
COMMUNITY_ENGINE = f'{_cfg.ENGINE}'
COMMUNITY_LEVELS = 1
COMMUNITY_SEED = 42


def select_community_fixture(fixture):
    global COMMUNITY_OUTPUT, COMMUNITY_META
    if fixture not in ('baseline','connected','connected100k','connected1m'):
        raise ValueError('Community fixtures are baseline or connected 10K, 100K, 1M')
    select_probe_fixture(fixture)
    suffix = {'baseline': 'COMMUNITY', 'connected': 'CONNECTED_10K_COMMUNITY',
              'connected100k': 'CONNECTED_100K_COMMUNITY',
              'connected1m': 'CONNECTED_1M_COMMUNITY'}[fixture]
    if fixture != 'baseline' and (COMMUNITY_LEVELS, COMMUNITY_SEED) != (1, 42):
        suffix += f'_L{COMMUNITY_LEVELS}_S{COMMUNITY_SEED}'
    COMMUNITY_OUTPUT = f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_' + suffix
    COMMUNITY_META = COMMUNITY_OUTPUT + '_META'


def deployed_community_parameters():
    parameters = community_parameters(COMMUNITY_LEVELS, COMMUNITY_SEED)
    parameters['num_pivots'] = {'connected100k': 100000, 'connected1m': 1000000}.get(PROBE_FIXTURE, 16000)
    return parameters


def prepare_community_probe():
    """Separate manual Logic deployment of the unchanged baseline algorithms."""
    return dict(schema=COMMUNITY_OUTPUT, meta_schema=COMMUNITY_META,
                role=f'{_cfg.DEPLOY_ROLE}', auto_deploy=False,
                schedules={'community_baseline': dict(interval_s=0, run_on_deploy=False)},
                outputs=dict(type='table', schedule='community_baseline', reasoner='logic'))


def community_export_procedure_sql(meta_schema=None):
    """Scope the SDK 1.27.1 identifier fix to this deployment's CSV export helper."""
    import importlib.metadata
    from relationalai.semantics.backends.sql.orchestrator import _load_js_procedure
    if importlib.metadata.version('relationalai') != '1.27.1':
        raise RuntimeError('Review the export compatibility fix after an SDK change')
    meta_schema = meta_schema or COMMUNITY_META
    if meta_schema not in {COMMUNITY_META, f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_TARGETS_META'}:
        raise ValueError('Unreviewed export-helper schema')
    original = _load_js_procedure('run_lqp_block_export', schema=meta_schema, app_name='RELATIONALAI')
    replacements = {
        'JSON.stringify(columnFields)':
            'JSON.stringify(columnFields.map(function (field) { '
            'return [renderColumnIdentifier(field[0])].concat(field.slice(1)); }))',
        'projectionParts.push(physicalCol + " as " + renderColumnIdentifier(declaredCol));':
            'projectionParts.push(renderColumnIdentifier(physicalCol) + " as " + renderColumnIdentifier(declaredCol));',
    }
    fixed = original
    for before, after in replacements.items():
        if fixed.count(before) != 1: raise RuntimeError('SDK export helper changed; review the fix')
        fixed = fixed.replace(before, after)
    return original, fixed


def install_community_export_fix(session, meta_schema=None):
    """Replace only the community export helper; leave the RAI plan and output names intact."""
    import hashlib
    original, fixed = community_export_procedure_sql(meta_schema)
    signature = (meta_schema or COMMUNITY_META) + '._INTERNAL_RUN_LQP_BLOCK_EXPORT(FLOAT,VARCHAR,VARCHAR)'
    def body():
        values = {r['property'].lower(): r['value'] for r in session.sql('DESCRIBE PROCEDURE ' + signature).collect()}
        return values['body'].strip()
    original_body, fixed_body = (sql.split('$$')[1].strip() for sql in (original, fixed))
    before = body()
    if before not in (original_body, fixed_body):
        raise RuntimeError('Deployed export helper differs from the reviewed SDK implementation')
    grants = session.sql('SHOW GRANTS ON PROCEDURE ' + signature).collect()
    if not grants or any(r['privilege'] != 'OWNERSHIP' or r['grantee_name'] != f'{_cfg.DEPLOY_ROLE}' for r in grants):
        raise RuntimeError('Unexpected helper grants; refusing replacement that could lose grants')
    if before != fixed_body:
        for statement in fixed.split('-- @@NEXT_STATEMENT@@'):
            session.sql(statement.strip()).collect()
    after = body()
    if after != fixed_body: raise RuntimeError('Export helper repair did not persist')
    return dict(procedure=signature, changed=before != after,
                body_sha256_before=hashlib.sha256(before.encode()).hexdigest(),
                body_sha256_after=hashlib.sha256(after.encode()).hexdigest(),
                change='Quote CSV temporary-table column identifiers in persist_from_stage and projection only')


def reduced_community_export_body(body, output_schema):
    """Experiment only: persist two results after the unchanged Logic transaction."""
    expected = f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_CONNECTED_100K_COMMUNITY_LEAN'
    if output_schema != expected:
        raise ValueError('Reduced exports are limited to the isolated 100K experiment')
    marker = 'tracer.startActiveSpan("export_results", function (span) {'
    if body.count(marker) != 1 or 'PE_REDUCED_EXPORT_EXPERIMENT' in body:
        raise RuntimeError('Unexpected SDK export body')
    allowed = [output_schema + '.KNOWS', output_schema + '.PERSONCOMMUNITYPROBE']
    addition = ('// PE_REDUCED_EXPORT_EXPERIMENT: do not change the Logic payload.\n'
                'var peAllowedExports = ' + json.dumps(allowed) + ';\n'
                'exportSpecs = exportSpecs.filter(function (spec) {\n'
                '    return peAllowedExports.indexOf(spec.destination_fqn) !== -1;\n'
                '});\n'
                'if (exportSpecs.length !== 2 || exportSpecs[0].destination_fqn === exportSpecs[1].destination_fqn) {\n'
                '    throw new Error("Expected both Knows and community exports");\n'
                '}\n')
    return body.replace(marker, addition + marker)


def install_reduced_community_exports(session):
    """Change only the new experiment's persistence helper, never SDK files."""
    import hashlib
    signature = COMMUNITY_META + '._INTERNAL_RUN_LQP_BLOCK(FLOAT,VARCHAR,VARCHAR,VARCHAR,FLOAT,BOOLEAN,FLOAT,VARCHAR,VARCHAR,VARCHAR,VARCHAR,VARCHAR)'
    ddl = session.sql("SELECT GET_DDL('PROCEDURE', ?, TRUE)", params=[signature]).collect()[0][0]
    if not ddl.split("(", 1)[0].replace('"', "").upper().endswith(COMMUNITY_META + "._INTERNAL_RUN_LQP_BLOCK"):
        raise RuntimeError("GET_DDL did not qualify the experiment procedure")
    values = {r['property'].lower(): r['value'] for r in session.sql('DESCRIBE PROCEDURE ' + signature).collect()}
    body = values['body']
    changed = reduced_community_export_body(body, COMMUNITY_OUTPUT)
    # GET_DDL can quote the JavaScript body with either dollar or SQL quoting.
    if '$$' in ddl:
        old, new = body, changed
    else:
        old, new = (text.replace(chr(92), chr(92) * 2).replace("'", "''") for text in (body, changed))
    if ddl.count(old) != 1:
        raise RuntimeError('Cannot locate the exact helper body in GET_DDL')
    grants = session.sql('SHOW GRANTS ON PROCEDURE ' + signature).collect()
    if not grants or any(r['privilege'] != 'OWNERSHIP' or r['grantee_name'] != f'{_cfg.DEPLOY_ROLE}' for r in grants):
        raise RuntimeError('Unexpected experiment helper grants')
    session.sql(ddl.replace(old, new)).collect()
    after = {r['property'].lower(): r['value'] for r in session.sql('DESCRIBE PROCEDURE ' + signature).collect()}['body']
    if after.strip() != changed.strip(): raise RuntimeError('Export filter did not persist')
    return dict(kept=['KNOWS','PERSONCOMMUNITYPROBE'],
                body_sha256_before=hashlib.sha256(body.encode()).hexdigest(),
                body_sha256_after=hashlib.sha256(after.encode()).hexdigest(),
                scope='Snowflake persistence only; full Logic computation and staged exports unchanged')


def community_preservation_snapshot(session):
    """Fingerprint original/copied inputs and the existing distance deployment."""
    import hashlib
    loader = runpy.run_path(str(ROOT / 'data/load.py'))
    tables = [name for name, _ in loader['parse_schema'](ROOT / 'data/schema.sql')]
    result = {}
    for schema in (f'{_cfg.BASE_SCHEMA}', f'{_cfg.BASE_SCHEMA}_DEPLOY_SRC'):
        sql = ' UNION ALL '.join(
            f"SELECT '{t}' AS NAME, COUNT(*) AS N, HASH_AGG(*) AS H "
            f"FROM {_cfg.DATABASE}.{schema}.{t}" for t in tables)
        result[schema] = [r.as_dict() for r in session.sql(sql).collect()]
    distance = f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_DEPLOY'
    for table in (distance + '.PERSONDISTANCEPROBE', distance + '_META._INTERNAL_PLAN',
                  distance + '_META._INTERNAL_REFRESH_LOG'):
        result[table] = [r.as_dict() for r in session.sql(
            f'SELECT COUNT(*) AS N, HASH_AGG(*) AS H FROM {table}').collect()]
    tasks = [r.as_dict() for r in session.sql(f'SHOW TASKS IN SCHEMA {distance}_META').collect()]
    result['distance_tasks_sha256'] = hashlib.sha256(
        json.dumps(tasks, sort_keys=True, default=str).encode()).hexdigest()
    return result


def validate_community_deployment_rows(rows, edge_rows):
    """Use fresh deployed edges and scores; never use saved scores as refresh evidence."""
    oracle = runpy.run_path(str(ROOT / 'data/oracle.py'))
    data = oracle['Data']()
    if PROBE_FIXTURE != 'baseline':
        oracle['load_csv'].__globals__['CSV_DIR'] = fixture_directory(PROBE_FIXTURE)
        data = oracle['Data']()
        pairs = oracle['build_knows'](data, set(oracle['our_seeds'](data)),
                                      include_evidence=PROBE_FIXTURE != 'connected1m')
    else:
        pairs = prepare_oracle()
    difference = compare_pairs(edge_rows, pairs)
    if any(difference[k] for k in ('missing_pairs', 'extra_pairs', 'duplicate_rows', 'noncanonical_pairs')):
        raise RuntimeError('Deployed Knows graph differs from the baseline oracle')
    graph = oracle['knows_graph'](data, pairs)
    report = summarize_people_communities(rows, data, graph, parameters=deployed_community_parameters())
    if PROBE_FIXTURE != 'baseline':
        report['fixture'] = PROBE_FIXTURE
        return report
    report['focus'] = community_focus(oracle, data, report['communities'])
    saved_path = ROOT / 'artifacts/people_communities.json'
    saved = json.loads(saved_path.read_text()) if saved_path.exists() else None
    if not saved or saved['graph_sha256'] != community_graph_fingerprint(data, graph):
        return report  # no earlier local run to compare against (e.g. a new account)
    baseline = next(r for r in saved['saved_rai_runs'] if r['parameters'] == community_parameters(1, 42))
    left = {r['person_id']: r['community'] for r in baseline['rows']}
    right = {r['person_id']: r['community'] for r in rows}
    report['saved_baseline_agreement'] = dict(
        adjusted_rand_all=adjusted_rand_index(left, right, graph),
        adjusted_rand_nonisolated=adjusted_rand_index(left, right, [p for p in graph if graph.degree(p)]))
    return report


def capture_community_diagnostics(config, output_path):
    """Save the SDK's debugger-readable plan, trace and transaction-progress bundle."""
    from relationalai.tools.cli.doctor_report import run_doctor_report
    from zipfile import ZipFile
    report = run_doctor_report(output_path=Path(output_path), config=config)
    with ZipFile(report) as archive:
        files = archive.namelist()
    return dict(path=str(report), files=files,
                open_command=f'env -u DEBUG .venv/bin/rai debugger --host 127.0.0.1 --report {report}')


def run_community_probe(*, execute=False, refresh=False, output_path=None, redeploy=False, reduced_exports=False):
    """Deploy into fresh experiment schemas; one optional refresh, without retries."""
    if reduced_exports and (PROBE_FIXTURE != 'connected100k' or redeploy):
        raise ValueError('Reduced exports require a fresh isolated 100K deployment')
    if redeploy and PROBE_FIXTURE != 'baseline':
        raise ValueError('In-place community updates are limited to the demo baseline')
    if not execute:
        print(json.dumps(dict(deployment=prepare_community_probe(),
                              compiler={'safe_recursion': False},
                              parameters=deployed_community_parameters()), indent=2))
        return
    import hashlib
    import importlib.metadata
    import os
    from unittest.mock import patch
    from relationalai.config import create_config, DeploymentConfig
    from relationalai.config.config import ambient_model_config
    from relationalai.semantics.backends.sql.orchestrator import PlanTable, SnowflakeOrchestrator
    from relationalai.semantics.backends.sql.snowflake_backend import SnowflakeBackend

    if importlib.metadata.version('relationalai') != '1.27.1':
        raise RuntimeError('Review deployment compatibility after an SDK change')
    if any(k.startswith('pe_deal_graph.model') for k in sys.modules):
        raise RuntimeError('Community deployment requires a fresh Python process')
    path = Path(output_path or ROOT / 'artifacts/people_communities_deployment.json')
    if path.exists(): raise RuntimeError('Preserve the previous deployment evidence; choose a new output file')
    os.environ['RAI_CONFIG_FILE_PATH'] = str(ROOT / 'raiconfig.yaml')
    os.environ['PE_DEAL_GRAPH_BUILD_PROFILE'] = 'copied-community-probe'
    os.environ['PE_COMMUNITY_MAX_LEVELS'] = str(COMMUNITY_LEVELS)
    os.environ['PE_COMMUNITY_SEED'] = str(COMMUNITY_SEED)
    os.environ['PE_DEAL_GRAPH_PROBE_FIXTURE'] = PROBE_FIXTURE
    os.environ['PE_DEAL_GRAPH_FINALE'] = '0'
    cfg = create_config()
    if cfg.reasoners.logic.name != COMMUNITY_ENGINE or cfg.data.ensure_change_tracking:
        raise RuntimeError('Experiment engine or source-preservation configuration changed')
    cfg.compiler.safe_recursion = False
    cfg.oplog.enabled = False
    cfg.execution.retries.enabled = False
    cfg.deployment = DeploymentConfig(**prepare_community_probe())
    cfg.reasoners.logic.query_timeout_mins = 25
    conn = cfg.get_default_connection()
    conn.role, conn.warehouse = f'{_cfg.DEPLOY_ROLE}', f'{_cfg.WAREHOUSE}'
    conn.database, conn.schema_ = PROBE_SOURCE.split('.')
    session = conn._create_new_session()
    evidence = dict(sdk='1.27.1', fixture=PROBE_FIXTURE, source=PROBE_SOURCE, deployment=prepare_community_probe(),
                    parameters=deployed_community_parameters(), compiler={'safe_recursion': False},
                    status='preflight', refresh_requested=refresh)
    def save(): path.write_text(json.dumps(evidence, indent=2, default=str))
    before = None
    try:
        cfg = create_config(snowflake_session=session, **cfg.model_dump())
        engine = session.sql('SELECT NAME, STATUS FROM RELATIONALAI.API.REASONERS WHERE NAME=?',
                             params=[COMMUNITY_ENGINE]).collect()
        if len(engine) != 1 or engine[0]['STATUS'] != 'READY':
            raise RuntimeError('Existing experiment engine must be READY; no create/resize/resume attempted')
        before = community_preservation_snapshot(session)
        evidence['preservation_before'] = before
        save()
        # Full value comparison of the baseline copies before any deployment changes.
        import csv
        loader = runpy.run_path(str(ROOT / 'data/load.py'))
        for name, ddl in loader['parse_schema'](ROOT / 'data/schema.sql'):
            with ((ROOT / 'data/csv' if PROBE_FIXTURE=='baseline' else fixture_directory(PROBE_FIXTURE)) / f'{name}.csv').open() as fh:
                reader = csv.reader(fh); next(reader); expected = list(reader)
            actual = session.sql(f"SELECT {','.join(loader['schema_cols'](ddl))} "
                                 f'FROM {conn.database}.{conn.schema_}.{name}').collect()
            if loader['canonical_rows'](actual, ddl) != loader['canonical_rows'](expected, ddl):
                raise RuntimeError('Copied baseline source differs from CSV: ' + name)
        evidence['source_value_validation'] = f'17 copied tables match {PROBE_FIXTURE} CSV values'
        session.sql(f'USE ROLE {_cfg.ADMIN_ROLE}').collect()
        names = {r['name'] for r in session.sql(f'SHOW SCHEMAS IN DATABASE {_cfg.DATABASE}').collect()}
        if redeploy:
            if not all(s.split('.')[1] in names for s in (COMMUNITY_OUTPUT, COMMUNITY_META)):
                raise RuntimeError('Baseline update requires both existing schemas')
            evidence['previous_plan'] = [r.as_dict() for r in session.sql(f'SELECT * FROM {COMMUNITY_META}._INTERNAL_PLAN').collect()]
        elif any(s.split('.')[1] in names for s in (COMMUNITY_OUTPUT, COMMUNITY_META)):
            raise RuntimeError('Community schemas already exist; refusing overwrite')
        for schema in (() if redeploy else (COMMUNITY_OUTPUT, COMMUNITY_META)):
            session.sql(f'CREATE SCHEMA {schema}').collect()
            session.sql(f'GRANT USAGE, CREATE TABLE, CREATE VIEW, CREATE PROCEDURE, CREATE TASK, CREATE TAG '
                        f'ON SCHEMA {schema} TO ROLE {_cfg.DEPLOY_ROLE}').collect()
        session.sql(f'USE ROLE {_cfg.DEPLOY_ROLE}').collect()
        evidence['status'] = 'schemas provisioned'
        save()
        with ambient_model_config(cfg):
            from pe_deal_graph.model import core, graphs  # noqa: F401
        if core.BETWEENNESS_PIVOTS != evidence['parameters']['num_pivots']:
            raise RuntimeError('Model pivots differ from reported exact configuration')

        original_entries = PlanTable.write_entries
        def scoped_plan(manager, meta, entries):
            if meta != COMMUNITY_META or len(entries) != 1:
                raise RuntimeError('Unexpected community deployment plan')
            entry = entries[0]
            if (entry.reasoner != 'logic' or entry.schedule_name != 'community_baseline' or
                    entry.parameters.get('engine_name') != COMMUNITY_ENGINE):
                raise RuntimeError('Community plan reasoner, engine or schedule changed')
            sources = entry.parameters['source_table_names']
            if any(not (s.startswith(PROBE_SOURCE + '.') or
                        s.startswith(COMMUNITY_META + '.') or s in {
                            PROBE_OUTPUT + '.ROLE_HISTORY_NORMALIZED',
                            PROBE_OUTPUT + '.OWNERSHIP_NORMALIZED'})
                   for s in sources):
                raise RuntimeError('Unexpected Logic input source')
            evidence['plan'] = dict(parameters=entry.parameters, targets=entry.target_table_names,
                                    sql_sha256=hashlib.sha256(entry.sql_statements.encode()).hexdigest())
            save()
            return original_entries(manager, meta, entries)
        def existing_schema(backend, schema_name, **kwargs):
            if schema_name not in (COMMUNITY_OUTPUT, COMMUNITY_META):
                raise RuntimeError('Unreviewed schema')
            rows = session.sql(f'SHOW SCHEMAS IN DATABASE {_cfg.DATABASE}').collect()
            if not any(r['name'] == schema_name.split('.')[1] and r['owner'] == f'{_cfg.ADMIN_ROLE}' for r in rows):
                raise RuntimeError('Provisioned schema owner changed')
            return False
        def preserve_streams(orchestrator, prior_sources, deploy_objects):
            sources = {s for e in orchestrator._pending_entries for s in e.source_tables}
            streams = session.sql('SELECT FQ_OBJECT_NAME FROM RELATIONALAI.API.DATA_STREAMS').collect()
            if (prior_sources and not redeploy) or (sources | set(prior_sources)) & {r[0] for r in streams}:
                raise RuntimeError('Deployment would require deleting an existing data stream')
            return '-- No source streams exist; stream deletion skipped to preserve other deployments.'
        with patch.object(PlanTable, 'write_entries', scoped_plan), \
             patch.object(SnowflakeBackend, 'create_schema_if_not_exists', existing_schema), \
             patch.object(SnowflakeOrchestrator, '_delete_stale_logic_streams', preserve_streams):
            core.model.deploy(wait=False, force=False)
        evidence['export_identifier_fix'] = install_community_export_fix(session)
        if reduced_exports:
            evidence['reduced_exports'] = install_reduced_community_exports(session)
        session.sql(f'ALTER TASK {COMMUNITY_META}.REFRESH_COMMUNITY_BASELINE SET USER_TASK_TIMEOUT_MS=1800000').collect()
        evidence['timeouts'] = {'logic_query_minutes': 25, 'task_minutes': 30, 'monitor_minutes': 35}
        evidence['status'] = 'deployed; not refreshed'
        save()
        if refresh:
            evidence['status'] = 'baseline refresh requested'
            save()
            evidence['refresh'] = refresh_community_probe(session, timeout=2100)
            save()
            if evidence['refresh']['STATE'] != 'SUCCEEDED':
                raise RuntimeError('Baseline refresh did not succeed; no automatic retry')
            rows = [r.as_dict() for r in session.sql(
                f'SELECT C.ID AS "person_id", P.FULL_NAME AS "name", C.COMMUNITY AS "community", '
                f'C.INTERNAL_BETWEENNESS AS "betweenness" FROM {COMMUNITY_OUTPUT}.PERSONCOMMUNITYPROBE C '
                f'JOIN {PROBE_SOURCE}.PERSON P ON P.PERSON_ID=C.ID').collect()]
            edges = [r.as_dict() for r in session.sql(
                f'SELECT P1 AS "p1", P2 AS "p2" FROM {COMMUNITY_OUTPUT}.KNOWS').collect()]
            evidence.update(rows=rows, edge_rows=edges)
            save()
            evidence['analysis'] = validate_community_deployment_rows(rows, edges)
            evidence['status'] = 'baseline refresh validated'
    except Exception as error:
        evidence.update(status='failed', error_type=type(error).__name__, error=str(error))
        if evidence.get('refresh_requested') and 'plan' in evidence:
            try:
                evidence['diagnostics'] = capture_community_diagnostics(cfg, path.with_suffix('.debug.zip'))
            except Exception as diagnostic_error:
                evidence['diagnostic_error'] = str(diagnostic_error)
            save()
        raise
    finally:
        if before is not None:
            session.sql(f'USE ROLE {_cfg.DEPLOY_ROLE}').collect()
            evidence['preservation_after'] = community_preservation_snapshot(session)
            evidence['preservation_passed'] = before == evidence['preservation_after']
        save()
        session.close()
    if not evidence.get('preservation_passed'):
        raise RuntimeError('Protected source or distance state changed during the run')
    print(json.dumps(dict(status=evidence['status'], evidence=str(path)), indent=2))


def refresh_community_probe(session, timeout=1800):
    """Execute the new manual task exactly once; retain failure evidence without retry."""
    return refresh_manual_task(session, COMMUNITY_META, 'REFRESH_COMMUNITY_BASELINE', timeout)


def refresh_manual_task(session, meta_schema, task_name, timeout=1800):
    """Run one allowlisted manual experiment refresh, with automatic retries off."""
    if (meta_schema, task_name) not in {
            (COMMUNITY_META, 'REFRESH_COMMUNITY_BASELINE'),
            (f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_TARGETS_META', 'REFRESH_TARGET_BASELINE')}:
        raise ValueError('Unreviewed refresh task')
    task = meta_schema + '.' + task_name
    tasks = session.sql(f'SHOW TASKS IN SCHEMA {meta_schema}').collect()
    if (len(tasks) != 1 or tasks[0]['name'] != task_name or
            tasks[0]['owner'] != f'{_cfg.DEPLOY_ROLE}' or tasks[0]['warehouse'] != f'{_cfg.WAREHOUSE}' or
            tasks[0]['state'].lower() != 'suspended' or tasks[0]['schedule']):
        raise RuntimeError('Community task scope/schedule changed')
    params = session.sql(f"SHOW PARAMETERS LIKE 'TASK_AUTO_RETRY_ATTEMPTS' IN TASK {task}").collect()
    if len(params) != 1 or str(params[0]['value']) != '0': raise RuntimeError('Task retries must be disabled')
    started = session.sql('SELECT CURRENT_TIMESTAMP()').collect()[0][0]
    session.sql(f'EXECUTE TASK {task}').collect()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = session.sql("SELECT STATE, ERROR_MESSAGE, QUERY_ID, SCHEDULED_TIME, QUERY_START_TIME, COMPLETED_TIME "
            f"FROM TABLE({_cfg.DATABASE}.INFORMATION_SCHEMA.TASK_HISTORY("
            f"TASK_NAME=>'{task_name}', SCHEDULED_TIME_RANGE_START=>TO_TIMESTAMP_LTZ(?), RESULT_LIMIT=>100)) "
            f"WHERE DATABASE_NAME='{_cfg.DATABASE}' AND SCHEMA_NAME='{meta_schema.split('.')[1]}'",
            params=[started.isoformat()]).collect()
        if len(rows) > 1: raise RuntimeError('More than one community refresh run')
        if rows and rows[0]['STATE'] in {'SUCCEEDED', 'FAILED', 'CANCELLED', 'SKIPPED'}:
            return rows[0].as_dict()
        print(f'Waiting for the single {task_name} refresh...', flush=True)
        time.sleep(10)
    raise TimeoutError('Community refresh still pending; check task history before any further action')


def main() -> int:
    global COMMUNITY_LEVELS, COMMUNITY_SEED, COMMUNITY_OUTPUT, COMMUNITY_META
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", help="write graph check results to this JSON file")
    ap.add_argument("--prepare-copied-distance-probe", action="store_true",
                    help="Print deployment targets; no connection")
    ap.add_argument("--run-copied-distance-probe", action="store_true",
                    help="Use existing copied sources and SDK deployment")
    ap.add_argument("--execute", action="store_true", help="Actually deploy")
    ap.add_argument("--refresh", action="store_true",
                    help="After deployment, run one manual refresh and validate distances")
    ap.add_argument("--benchmark-distance-lookups", action="store_true", help="Direct SQL reads of existing RAI materialized distances only")
    ap.add_argument("--run-community-probe", action="store_true", help="Prepare/deploy the isolated baseline community model")
    ap.add_argument("--fixture", choices=("baseline", "sparse", "connected", "connected100k", "connected1m"), default="baseline")
    ap.add_argument("--community-levels", type=int, default=1)
    ap.add_argument("--community-seed", type=int, default=42)
    ap.add_argument("--redeploy-community", action="store_true", help="Update the existing baseline community deployment only")
    ap.add_argument("--reduced-community-exports", action="store_true", help="Isolated 100K persistence experiment; keeps scores and Knows only")
    args = ap.parse_args()
    if args.reduced_community_exports and (not args.run_community_probe or args.fixture != "connected100k" or args.redeploy_community):
        ap.error("Reduced exports require a fresh connected100k community run")
    community_parameters(args.community_levels, args.community_seed)
    COMMUNITY_LEVELS, COMMUNITY_SEED = args.community_levels, args.community_seed
    if args.redeploy_community and not args.run_community_probe: ap.error("--redeploy-community requires --run-community-probe")
    if args.run_community_probe:
        if args.fixture not in ('baseline','connected','connected100k','connected1m') or args.run_copied_distance_probe or args.prepare_copied_distance_probe or args.benchmark_distance_lookups:
            ap.error('Community deployment supports baseline/connected 10K/100K/1M and cannot be combined with distance actions')
        select_community_fixture(args.fixture)
        if args.reduced_community_exports:
            COMMUNITY_OUTPUT += "_LEAN"
            COMMUNITY_META = COMMUNITY_OUTPUT + "_META"
        if args.refresh and not args.execute: ap.error('--refresh requires --execute')
        run_community_probe(execute=args.execute, refresh=args.refresh, output_path=args.json, redeploy=args.redeploy_community, reduced_exports=args.reduced_community_exports)
        return 0
    select_probe_fixture(args.fixture)
    if args.benchmark_distance_lookups:
        if args.execute or args.refresh or args.run_copied_distance_probe or args.prepare_copied_distance_probe or args.json:
            ap.error("Lookup benchmark cannot be combined with deployment/refresh/output flags")
        benchmark_distance_lookups()
        return 0
    if args.execute and not args.run_copied_distance_probe:
        ap.error("--execute requires --run-copied-distance-probe")
    if args.refresh and not args.execute:
        ap.error("--refresh requires --execute")
    if args.prepare_copied_distance_probe or args.run_copied_distance_probe:
        if args.prepare_copied_distance_probe and args.execute:
            ap.error("Preparation does not execute deployment")
        run_copied_distance_probe(execute=args.execute, refresh=args.refresh)
        return 0
    n_fail = run_checks()
    if args.json:
        Path(args.json).write_text(json.dumps(RESULTS, indent=1))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
