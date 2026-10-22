"""Generate the FIXTURE exports set for the Deal Graph Explorer (owner: R15).

FIXTURE ONLY. Every name and number here is fake and labelled FIXTURE. This set exists so the
explorer can be developed and tested before R13 writes exports/ from live RAI queries. It must
never be the explorer's default input, and the builder refuses to write the real deliverable
(artifacts/deal_graph_explorer.html) from it.

Regenerate (deterministic):
    .venv/bin/python tests/fixtures/exports/_generate.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import networkx as nx

OUT = Path(__file__).resolve().parent
RNG = random.Random(42)
SCALE = 1000.0


def dump(name: str, obj: dict) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def layout(g: nx.Graph, seed: int = 42) -> dict:
    pos = nx.spring_layout(g, seed=seed, iterations=80)
    return {n: (round(float(x) * SCALE, 2), round(float(y) * SCALE, 2)) for n, (x, y) in pos.items()}


# ---------------------------------------------------------------- rules.json
RULES = [
    ("SECTOR_CLOSURE", "Sector hierarchy closure", "rule", ["Q-SCORE", "Q-FLOW"],
     "FIXTURE. A niche is in the thesis when one of its ancestors is a fund focus area and none is excluded."),
    ("FIT_THESIS", "Thesis fit", "rule", ["Q-SCORE"], "FIXTURE. Eligible companies earn thesis points."),
    ("FIT_EBITDA", "EBITDA band", "rule", ["Q-SCORE"], "FIXTURE. Points when EBITDA sits in the core band."),
    ("FIT_MARGIN", "Margin benchmark", "rule", ["Q-SCORE"], "FIXTURE. Points when margin beats the focus-area benchmark."),
    ("R_CFO_FROM_PE", "CFO from a PE-backed company", "rule", ["Q-SCORE"], "FIXTURE. Recent CFO hire who came from a sponsor-backed employer."),
    ("R_EXIT_WINDOW", "Sponsor exit window", "rule", ["Q-SCORE"], "FIXTURE. Sponsor has held long enough and the fund is old enough to sell."),
    ("R_BANKER", "Banker engaged", "rule", ["Q-SCORE"], "FIXTURE. A banker engagement signal in the recent window."),
    ("R_DEBT", "Debt maturity", "rule", ["Q-SCORE"], "FIXTURE. Debt matures inside the window."),
    ("R_SUCCESSION", "Succession signal", "rule", ["Q-SCORE"], "FIXTURE. Long-tenured founder CEO with no President or COO."),
    ("R_NEW_DIRECTOR", "New independent director", "rule", ["Q-SCORE"], "FIXTURE. A new board seat in the last year."),
    ("A_CRM", "Recent positive CRM touch", "rule", ["Q-SCORE"], "FIXTURE. A positive CRM interaction in the window."),
    ("A_WARM_PATH", "Warm path access", "rule", ["FINALE"], "FIXTURE. Targets within two hops earn access points."),
    ("CONFLICT", "Cross-fund conflict", "rule", ["FINALE", "Q-CONFLICT"], "FIXTURE. A target that trades with a Fund III company is flagged."),
    ("K1_TENURE", "Tenure overlap", "rule", ["Q-PATH"], "FIXTURE. Two people overlapped at the same organization for a year or more."),
    ("K1_BOARD", "Board co-service", "rule", ["Q-PATH"], "FIXTURE. Two people served on the same board for a year or more."),
    ("K2_DEAL", "Deal co-participation", "rule", ["Q-PATH"], "FIXTURE. Two people worked the same transaction."),
    ("K3_CRM", "Positive CRM contact", "rule", ["Q-PATH"], "FIXTURE. Our person had positive meetings with the other person."),
    ("SHARED_EMPLOYER_REJECT", "Shared employer is not a tie", "rule", ["Q-PATH"], "FIXTURE. Same employer at different times is not a relationship."),
    ("WARM_PATH", "Warm path search", "graph", ["Q-PATH"], "FIXTURE. Shortest hop distance from our people over the relationship graph."),
    ("COMMERCIAL", "Commercial link", "rule", ["Q-ADDON", "Q-CONFLICT"], "FIXTURE. A supplier and customer relationship."),
    ("ADDON_SIMILARITY", "Add-on similarity", "graph", ["Q-ADDON"], "FIXTURE. Share of customers and suppliers in common with the platform."),
    ("WHITESPACE", "Whitespace states", "rule", ["Q-ADDON"], "FIXTURE. States the candidate operates in that the platform does not."),
    ("DEAL_FLOW", "Deal-flow centrality", "graph", ["Q-FLOW"], "FIXTURE. How often an intermediary sits on the shortest route between parties."),
    ("COVERAGE_GAP", "Coverage gap", "rule", ["Q-FLOW"], "FIXTURE. A top-decile intermediary we rarely talk to."),
    ("OWNERSHIP", "Fund ownership", "rule", ["Q-CONFLICT"], "FIXTURE. A fund currently owns the company."),
    ("CONCENTRATION", "Sector concentration guideline", "rule", ["Q-CONFLICT"], "FIXTURE. Fund exposure to one sector stays under the guideline."),
    ("EMPLOYMENT", "Current role", "rule", [], "FIXTURE. A person holds a role at an organization."),
    ("CLOSEST_INTERMEDIARY", "Closest intermediary", "rule", ["Q-PATH"], "FIXTURE. The intermediary with the most recent tie to a cold target."),
    ("NORTHWIND_HOLDING", "Current holding", "rule", ["Q-CONFLICT"], "FIXTURE. A company a fund of ours owns today, not one it used to own."),
    ("PORTFOLIO_EXPOSURE", "Portfolio exposure", "rule", ["Q-CONFLICT"], "FIXTURE. A current holding within two commercial hops of the target, classified by fund."),
]
dump("rules.json", {"rules": [
    {"id": i, "name": n, "kind": k, "questions": q, "docstring": d, "source": f"pe_deal_graph/model/rules.py::{i.lower()}"}
    for i, n, k, q, d in RULES]})

# ---------------------------------------------------------------- meta.json
dump("meta.json", {
    "schema_version": "1",
    "source": "FIXTURE",
    "generated_at": "2000-01-01T00:00:00+00:00",
    "as_of_date": "2000-01-01",
    "customer_display_name": "FIXTURE Capital",
    "fund_name": "Fixture Fund IV",
    "relationalai_version": None,
    "engine": None,
    "counts": {"pipeline_companies": 99, "market_companies": 999},
})

GREEK = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet",
         "Kilo", "Lima", "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo", "Sierra", "Tango"]

# ---------------------------------------------------------------- q_score.json
COMPONENTS = [
    ("FIT_THESIS", "Thesis fit", "fit", 15), ("FIT_EBITDA", "EBITDA band", "fit", 10),
    ("FIT_MARGIN", "Margin benchmark", "fit", 5), ("R_CFO_FROM_PE", "CFO from PE-backed company", "readiness", 15),
    ("R_EXIT_WINDOW", "Exit window", "readiness", 15), ("R_BANKER", "Banker engaged", "readiness", 10),
    ("R_DEBT", "Debt maturity", "readiness", 10), ("R_SUCCESSION", "Succession", "readiness", 10),
    ("R_NEW_DIRECTOR", "New director", "readiness", 5), ("A_CRM", "CRM touch", "access", 10),
]
# (id, name, awarded component ids, in_crm)
SCORE_ROWS = [
    ("C_T1", "FIXTURE Target Alpha", ["FIT_THESIS", "FIT_EBITDA", "FIT_MARGIN", "R_CFO_FROM_PE", "R_EXIT_WINDOW", "R_BANKER", "R_DEBT", "A_CRM"], True),
    ("C_T2", "FIXTURE Target Bravo", ["FIT_THESIS", "FIT_EBITDA", "FIT_MARGIN", "R_CFO_FROM_PE", "R_SUCCESSION", "R_DEBT", "R_BANKER", "A_CRM"], True),
    ("C_T3", "FIXTURE Target Charlie", ["FIT_THESIS", "FIT_EBITDA", "FIT_MARGIN", "R_EXIT_WINDOW", "R_BANKER", "R_DEBT", "R_CFO_FROM_PE"], False),
    ("C_T4", "FIXTURE Target Delta", ["FIT_THESIS", "FIT_EBITDA", "FIT_MARGIN", "R_SUCCESSION", "R_BANKER", "R_DEBT", "R_CFO_FROM_PE"], True),
    ("C_T5", "FIXTURE Target Echo", ["FIT_THESIS", "FIT_MARGIN", "R_CFO_FROM_PE", "R_SUCCESSION", "R_DEBT", "R_NEW_DIRECTOR", "A_CRM"], True),
    ("C_T6", "FIXTURE Target Foxtrot", ["FIT_THESIS", "FIT_EBITDA", "FIT_MARGIN", "R_EXIT_WINDOW", "R_BANKER", "R_DEBT", "R_NEW_DIRECTOR"], False),
    ("C_T7", "FIXTURE Target Golf", ["FIT_THESIS", "FIT_EBITDA", "FIT_MARGIN", "R_SUCCESSION", "R_DEBT", "R_CFO_FROM_PE"], True),
    ("C_T8", "FIXTURE Target Hotel", ["FIT_THESIS", "FIT_EBITDA", "R_BANKER", "R_DEBT"], True),
]
cmax = {c[0]: c[3] for c in COMPONENTS}
cgroup = {c[0]: c[2] for c in COMPONENTS}
rows = []
for cid, name, awarded, in_crm in SCORE_ROWS:
    comps = []
    for c in COMPONENTS:
        pts = cmax[c[0]] if c[0] in awarded else 0
        if c[0] == "FIT_EBITDA" and c[0] not in awarded and cid == "C_T5":
            pts = 5
        comps.append({"id": c[0], "points": pts,
                      "evidence": f"FIXTURE evidence for {c[1].lower()}" if pts else f"FIXTURE reason {c[1].lower()} not awarded"})
    fit = sum(x["points"] for x in comps if cgroup[x["id"]] == "fit")
    rd = min(50, sum(x["points"] for x in comps if cgroup[x["id"]] == "readiness"))
    acc = sum(x["points"] for x in comps if cgroup[x["id"]] == "access")
    rows.append({"company_id": cid, "name": name, "score": fit + rd + acc, "fit": fit, "readiness": rd, "access": acc,
                 "in_crm": in_crm, "pipeline_stage": "FIXTURE Stage" if in_crm else None,
                 "sector_path": ["FIXTURE Sector", "FIXTURE Subsector", f"FIXTURE Niche {name.split()[-1]}"],
                 "ebitda_musd": 11.1 * (1 + len(rows)), "revenue_musd": 99.9, "owner": "FIXTURE Owner" if cid in ("C_T1", "C_T3", "C_T6") else None,
                 "why": f"FIXTURE why line for {name}", "components": comps})
rows.sort(key=lambda r: (-r["score"], -r["readiness"], -r["fit"], r["name"]))
for i, r in enumerate(rows):
    r["rank"] = i + 1
    r["tier"] = "A" if r["score"] >= 70 else ("B" if r["score"] >= 50 else "C")
SCORED = {r["company_id"]: r for r in rows}
tier_a = [r for r in rows if r["tier"] == "A"]
q_score = {
    "question_id": "Q-SCORE",
    "business_question": "FIXTURE. Which companies fit the thesis and look ready to transact, and why?",
    "tier_thresholds": {"A": 70, "B": 50}, "readiness_cap": 50, "max_score": 100,
    "components": [{"id": c[0], "label": c[1], "group": c[2], "max_points": c[3], "rule_id": c[0]} for c in COMPONENTS],
    "summary": {"scored": len(rows), "tier_a": len(tier_a), "tier_b": sum(r["tier"] == "B" for r in rows),
                "tier_c": sum(r["tier"] == "C" for r in rows),
                "tier_a_not_in_crm": sum(not r["in_crm"] for r in tier_a), "ineligible": 2},
    "rows": rows,
    "ineligible": [{"company_id": "C_X1", "name": "FIXTURE Too Big Co", "reason": "FIXTURE. EBITDA $99.9M is above the band."},
                   {"company_id": "C_X2", "name": "FIXTURE Off Thesis Co", "reason": "FIXTURE. Niche is outside the thesis tree."}],
}
# finale: T2 gains 10 and moves to #1; T4 conflicted; T7 rises.
fin = []
for r in rows:
    add = 10 if r["company_id"] in ("C_T2", "C_T7") else 0
    conflict = None
    if r["company_id"] == "C_T4":
        conflict = {"reason": "FIXTURE. Supplies a Fund III portfolio company.", "counterparty_id": "C_P3",
                    "counterparty_name": "FIXTURE Portfolio Three", "rule_id": "CONFLICT"}
    fin.append({"company_id": r["company_id"], "name": r["name"], "score": r["score"] + add, "prev_rank": r["rank"],
                "prev_score": r["score"], "prev_tier": r["tier"], "delta": add, "conflict": conflict,
                "added_components": ([{"id": "A_WARM_PATH", "points": 10, "evidence": "FIXTURE. Reachable in two hops."}] if add else [])})
ranked = sorted([f for f in fin if not f["conflict"]], key=lambda f: (-f["score"], f["prev_rank"]))
for i, f in enumerate(ranked):
    f["rank"] = i + 1
    f["tier"] = "A" if f["score"] >= 70 else ("B" if f["score"] >= 50 else "C")
for f in fin:
    if f["conflict"]:
        f["rank"] = None
        f["tier"] = "Conflict"
q_score["finale"] = {"description": "FIXTURE. Warm-path access points added and cross-fund conflicts flagged.",
                     "rows": ranked + [f for f in fin if f["conflict"]]}
dump("q_score.json", q_score)

# ---------------------------------------------------------------- people and q_path.json
P = {  # id: (name, title)
    "P_S1": ("FIXTURE Seed Person One", "Operating Partner"), "P_S2": ("FIXTURE Seed Person Two", "Principal"),
    "P_S3": ("FIXTURE Seed Person Three", "Managing Director"), "P_S4": ("FIXTURE Seed Person Four", "Managing Partner"),
    "P_M1": ("FIXTURE Bridge CFO", "CFO"), "P_M2": ("FIXTURE Bridge Banker", "Banker"),
    "P_M3": ("FIXTURE Bridge Banker MD", "Managing Director"), "P_M4": ("FIXTURE Stale Director", "Board"),
    "P_C1": ("FIXTURE CEO Alpha", "CEO"), "P_C2": ("FIXTURE CEO Bravo", "CEO"), "P_C3": ("FIXTURE CEO Charlie", "CEO"),
    "P_D1": ("FIXTURE Designee Alpha", "Board"), "P_D3": ("FIXTURE Designee Charlie", "Board"),
}
SEEDS = ["P_S1", "P_S2", "P_S3", "P_S4"]


def hop(eid, a, b, tie, org_id, org, s, e, yrs, rec, st, rule):
    return {"edge_id": eid, "from_id": a, "from_name": P[a][0], "to_id": b, "to_name": P[b][0], "tie_type": tie,
            "org_id": org_id, "org_name": org, "start_date": s, "end_date": e, "years": yrs, "recency": rec,
            "strength": st, "evidence": f"FIXTURE. {'Overlapped' if tie == 'K1' else 'Worked together'} at {org}, {s} to {e or 'present'}.",
            "rule_id": rule}


pe = [("PE1", "P_S1", "P_M1", "K1"), ("PE2", "P_M1", "P_C2", "K1"), ("PE3", "P_S2", "P_M2", "K1"),
      ("PE4", "P_M2", "P_M3", "K1"), ("PE5", "P_M3", "P_C1", "K2"), ("PE6", "P_S4", "P_M4", "K1"),
      ("PE7", "P_M4", "P_C2", "K1"), ("PE8", "P_S3", "P_C3", "REJECTED")]
pg = nx.Graph()
pg.add_nodes_from(P)
pos_path = {"P_S1": (0, -300), "P_S2": (0, -100), "P_S3": (0, 100), "P_S4": (0, 300),
            "P_M1": (350, -300), "P_M2": (300, -100), "P_M3": (600, -100), "P_M4": (350, 300),
            "P_C1": (900, -100), "P_C2": (700, -300), "P_C3": (900, 150), "P_D1": (900, -220), "P_D3": (900, 300)}
def dm(pid, kind, role_label, status, hops, best, summary, paths):
    return {"person_id": pid, "name": P[pid][0], "kind": kind, "role_label": role_label, "status": status, "hops": hops,
            "best_strength": best, "summary": summary, "paths": paths}


COLD_DM = "FIXTURE. No path within 3 hops."
targets = [
    {"company_id": "C_T1", "company_name": SCORED["C_T1"]["name"], "score_rank": SCORED["C_T1"]["rank"],
     "owner_name": "FIXTURE Sponsor Alpha", "status": "warm", "summary": "FIXTURE. CEO reachable in three hops through two bankers.",
     "decision_makers": [
         dm("P_C1", "CEO", "CEO", "warm", 3, 0.111, "FIXTURE. Three hops through two bankers.",
            [{"path_id": "T1-1", "rank": 1, "length": 3, "strength": 0.111, "node_ids": ["P_S2", "P_M2", "P_M3", "P_C1"],
              "hops": [hop("PE3", "P_S2", "P_M2", "K1", "O_B1", "FIXTURE Bank One", "2001-01-01", "2004-01-01", 3.0, 0.7, 0.333, "K1_TENURE"),
                       hop("PE4", "P_M2", "P_M3", "K1", "O_I2", "FIXTURE Boutique Two", "2005-01-01", "2010-01-01", 5.0, 1.0, 0.555, "K1_TENURE"),
                       hop("PE5", "P_M3", "P_C1", "K2", "O_I2", "FIXTURE Boutique Two", "2006-06-06", None, None, 1.0, 0.666, "K2_DEAL")]}]),
         dm("P_D1", "OWNER_DESIGNEE", "Board designee, FIXTURE Sponsor Alpha", "cold", None, None, COLD_DM, [])],
     "rejected_claims": [], "closest_intermediary": None, "next_step": None},
    {"company_id": "C_T2", "company_name": SCORED["C_T2"]["name"], "score_rank": SCORED["C_T2"]["rank"],
     "owner_name": None, "status": "warm", "summary": "FIXTURE. CEO reachable in two hops through a former CFO.",
     "decision_makers": [
         dm("P_C2", "CEO", "CEO", "warm", 2, 0.222, "FIXTURE. Two hops through a former CFO.",
            [{"path_id": "T2-1", "rank": 1, "length": 2, "strength": 0.222, "node_ids": ["P_S1", "P_M1", "P_C2"],
              "hops": [hop("PE1", "P_S1", "P_M1", "K1", "C_P1", "FIXTURE Portfolio One", "2002-02-02", "2006-06-06", 4.3, 1.0, 0.444, "K1_TENURE"),
                       hop("PE2", "P_M1", "P_C2", "K1", "C_T2", SCORED["C_T2"]["name"], "2007-07-07", None, 1.3, 1.0, 0.5, "K1_TENURE")]},
             {"path_id": "T2-2", "rank": 2, "length": 2, "strength": 0.099, "node_ids": ["P_S4", "P_M4", "P_C2"],
              "hops": [hop("PE6", "P_S4", "P_M4", "K1", "O_X9", "FIXTURE Old Employer", "1990-01-01", "1992-01-01", 2.0, 0.4, 0.3, "K1_TENURE"),
                       hop("PE7", "P_M4", "P_C2", "K1", "C_T2", SCORED["C_T2"]["name"], "2008-08-08", None, 3.7, 1.0, 0.33, "K1_TENURE")]}])],
     "rejected_claims": [], "closest_intermediary": None, "next_step": None},
    {"company_id": "C_T3", "company_name": SCORED["C_T3"]["name"], "score_rank": SCORED["C_T3"]["rank"],
     "owner_name": "FIXTURE Sponsor Charlie", "status": "cold", "summary": "FIXTURE. Cold to the CEO and to the owner's designee.",
     "decision_makers": [dm("P_C3", "CEO", "CEO", "cold", None, None, COLD_DM, []),
                         dm("P_D3", "OWNER_DESIGNEE", "Board designee, FIXTURE Sponsor Charlie", "cold", None, None, COLD_DM, [])],
     "rejected_claims": [{"edge_id": "PE8", "from_id": "P_S3", "from_name": P["P_S3"][0], "to_id": "P_C3", "to_name": P["P_C3"][0],
                          "org_name": "FIXTURE Shared Employer", "claim": "FIXTURE. A shared-employer join says these two know each other.",
                          "reason": "FIXTURE. Same employer, never at the same time.",
                          "intervals": [{"person_id": "P_S3", "name": P["P_S3"][0], "start_date": "1990-01-01", "end_date": "1991-01-01"},
                                        {"person_id": "P_C3", "name": P["P_C3"][0], "start_date": "1995-01-01", "end_date": "1999-01-01"}],
                          "gap_days": 1461, "rule_id": "SHARED_EMPLOYER_REJECT"}],
     "closest_intermediary": {"org_id": "O_I1", "name": "FIXTURE Boutique Gap", "evidence": "FIXTURE. Engaged on this company and advised its last recap.",
                              "rule_id": "CLOSEST_INTERMEDIARY"},
     "next_step": {"label": "Open deal flow at FIXTURE Boutique Gap", "view": "flow", "node_id": "O_I1"}},
]
vnodes = [{"id": k, "label": v[0], "type": "person", "x": pos_path[k][0], "y": pos_path[k][1],
           "tags": (["our_person"] if k in SEEDS else []) + (["path_target"] if k.startswith(("P_C", "P_D")) else [])} for k, v in P.items()]
vedges = [{"id": e, "source": a, "target": b, "type": "rejected" if t == "REJECTED" else {"K1": "tenure", "K2": "deal"}[t],
           "label": "FIXTURE tie" if t != "REJECTED" else "FIXTURE shared employer"} for e, a, b, t in pe]
dump("q_path.json", {
    "question_id": "Q-PATH",
    "business_question": "FIXTURE. For the top three, what is our warmest path to the CEO, and through whom?",
    "max_hops": 3,
    "seeds": [{"person_id": s, "name": P[s][0], "title": P[s][1]} for s in SEEDS],
    "tie_types": [{"id": "K1", "label": "Tenure overlap", "rule_id": "K1_TENURE"},
                  {"id": "K2", "label": "Deal co-participation", "rule_id": "K2_DEAL"},
                  {"id": "K3", "label": "Positive CRM contact", "rule_id": "K3_CRM"}],
    "targets": targets,
    "view_graph": {"nodes": vnodes, "edges": vedges},
})

# ---------------------------------------------------------------- q_flow.json
INTS = [("O_I1", "FIXTURE Boutique Gap"), ("O_I2", "FIXTURE Boutique Two"), ("O_I3", "FIXTURE Big Bank"),
        ("O_I4", "FIXTURE Regional Bank"), ("O_I5", "FIXTURE Broker Five"), ("O_I6", "FIXTURE Broker Six"),
        ("O_I7", "FIXTURE Advisor Seven"), ("O_I8", "FIXTURE Advisor Eight")]
SPONS = [(f"O_S{i}", f"FIXTURE Sponsor {g}") for i, g in enumerate(GREEK[:6], start=1)]
FCOS = [(f"C_F{i:02d}", f"FIXTURE Deal Co {g}") for i, g in enumerate(GREEK[:16], start=1)] + [("C_T3", SCORED["C_T3"]["name"])]
fg = nx.Graph()
deals = []
for i in range(24):
    tgt = FCOS[i % len(FCOS)]
    adv = INTS[(i * 3) % len(INTS)] if i % 5 else INTS[0]
    buyer = SPONS[i % len(SPONS)]
    if tgt[0] == "C_T3":
        adv, buyer = INTS[0], SPONS[2]
    tid = f"TX{i + 1:02d}"
    e1, e2 = f"FE_{adv[0]}_{tgt[0]}", f"FE_{adv[0]}_{buyer[0]}"
    fg.add_edge(adv[0], tgt[0]); fg.add_edge(adv[0], buyer[0]); fg.add_edge(buyer[0], tgt[0])
    deals.append({"txn_id": tid, "close_date": f"2001-{(i % 12) + 1:02d}-15", "target_id": tgt[0], "target_name": tgt[1],
                  "buyer_name": buyer[1], "seller_type": "founder_family" if i % 2 else "sponsor",
                  "structure": "dividend_recap" if tgt[0] == "C_T3" else "control_buyout", "deal_role": "platform",
                  "advisor_ids": [adv[0]], "advisor_names": [adv[1]], "edge_ids": sorted({e1, e2, f"FE_{buyer[0]}_{tgt[0]}"})})
names = dict(INTS + SPONS + FCOS)
bc = nx.betweenness_centrality(fg, normalized=False)
pr = {n: d / (2.0 * fg.number_of_edges()) for n, d in fg.degree()}  # FIXTURE stand-in; scipy is not installed
ints_sorted = sorted(INTS, key=lambda x: (-bc.get(x[0], 0), x[1]))
touch = {"O_I1": 1, "O_I2": 9, "O_I3": 8, "O_I4": 0, "O_I5": 3, "O_I6": 0, "O_I7": 5, "O_I8": 2}
intermediaries = []
for rank, (oid, nm) in enumerate(ints_sorted, start=1):
    dids = [d["txn_id"] for d in deals if oid in d["advisor_ids"]]
    gap = oid == "O_I1"
    intermediaries.append({"org_id": oid, "name": nm, "betweenness": round(bc.get(oid, 0.0), 3), "betweenness_rank": rank,
                           "pagerank": round(pr.get(oid, 0.0), 5), "deals_in_window": len(dids),
                           "deals_5y_all_sectors": len(dids) + (40 if oid == "O_I3" else 1), "touchpoints_24m": touch[oid],
                           "top_decile": rank == 1 or gap, "is_gap": gap,
                           "gap_reason": "FIXTURE. Top decile by centrality, bottom quartile by touchpoints." if gap else None,
                           "deal_ids": dids})
fpos = layout(fg)
fedges = []
seen = set()
for d in deals:
    for eid in d["edge_ids"]:
        if eid in seen:
            continue
        seen.add(eid)
        _, a, b = eid.split("_", 2)[0], "_".join(eid.split("_")[1:3]), "_".join(eid.split("_")[3:5])
        fedges.append({"id": eid, "source": a, "target": b, "type": "deal"})


def ntype(n):
    return "intermediary" if n.startswith("O_I") else ("sponsor" if n.startswith("O_S") else "company")


fnodes = [{"id": n, "label": names[n], "type": ntype(n), "x": fpos[n][0], "y": fpos[n][1],
           "tags": (["coverage_gap"] if n == "O_I1" else []) + (["path_target"] if n == "C_T3" else [])} for n in sorted(fg.nodes)]
dump("q_flow.json", {
    "question_id": "Q-FLOW",
    "business_question": "FIXTURE. Which intermediaries control deal flow in our sectors, and where is coverage weakest?",
    "window": {"start": "1996-01-01", "end": "2000-01-01"},
    "graph_stats": {"num_nodes": fg.number_of_nodes(), "num_edges": fg.number_of_edges(), "num_intermediaries": len(INTS)},
    "thresholds": {"top_decile_cutoff_rank": 1, "q1_touchpoints": 1},
    "intermediaries": intermediaries,
    "deals": deals,
    "view_graph": {"nodes": fnodes, "edges": fedges},
})

# ---------------------------------------------------------------- q_addon.json
PLAT = ("C_P1", "FIXTURE Platform Co")
CUST = [(f"C_K{i:02d}", f"FIXTURE Customer {g}") for i, g in enumerate(GREEK[:12], start=1)]
CANDS = [("C_A1", "FIXTURE Addon Alpha", "FIXTURE Sibling Niche", ["XA", "XB", "XC", "XD"], [0, 1, 2, 3, 4], 0),
         ("C_A2", "FIXTURE Addon Bravo", "FIXTURE Other Niche", ["XA", "XE"], [5, 6], 1),
         ("C_A3", "FIXTURE Addon Charlie", "FIXTURE Third Niche", ["XB", "XF"], [7], 2)]
ag = nx.Graph()
for k in CUST[:9]:
    ag.add_edge(PLAT[0], k[0])
own = 0
for cid, nm, niche, st, shared, comm in CANDS:
    for j in shared:
        ag.add_edge(cid, CUST[j][0])
    for j in range(2):
        ag.add_edge(cid, f"C_OWN{own}")
        own += 1
apos = layout(ag)
cand_rows = []
for rank, (cid, nm, niche, st, shared, comm) in enumerate(CANDS, start=1):
    nb = set(ag[cid]); pn = set(ag[PLAT[0]])
    cand_rows.append({"company_id": cid, "name": nm, "niche": niche, "rank": rank, "similarity": round(len(nb & pn) / len(nb | pn), 4),
                      "shared_count": len(nb & pn), "union_count": len(nb | pn), "neighbor_count": len(nb), "community": comm,
                      "states": st, "whitespace_states": [s for s in st if s not in ("XA", "XB")],
                      "shared_neighbors": [{"company_id": CUST[j][0], "name": CUST[j][1], "relation": "customer"} for j in shared],
                      "ebitda_musd": 5.5 * rank, "evidence": f"FIXTURE. Shares {len(nb & pn)} customers with the platform."})
anames = dict(CUST + [PLAT] + [(c[0], c[1]) for c in CANDS])
anodes = [{"id": n, "label": anames.get(n, f"FIXTURE Own Customer {n[-1]}"), "type": "company", "x": apos[n][0], "y": apos[n][1],
           "tags": ["platform"] if n == PLAT[0] else [],
           "community": next((c[5] for c in CANDS if c[0] == n), 0 if n == PLAT[0] else 3)} for n in sorted(ag.nodes)]
aedges = [{"id": f"AE_{a}_{b}", "source": a, "target": b, "type": "commercial"} for a, b in sorted(tuple(sorted(e)) for e in ag.edges)]
dump("q_addon.json", {
    "question_id": "Q-ADDON",
    "business_question": "FIXTURE. Which add-ons best extend our platform beyond the obvious ones?",
    "similarity_label": "FIXTURE similarity over customers and suppliers",
    "platform": {"company_id": PLAT[0], "name": PLAT[1], "niche": "FIXTURE Platform Niche", "states": ["XA", "XB"],
                 "neighbor_count": len(ag[PLAT[0]])},
    "candidates": cand_rows,
    "excluded": [{"company_id": "C_D1", "name": "FIXTURE Same Niche Co", "reason": "FIXTURE. Same niche, no customer overlap, no new states."}],
    "communities": [{"id": 0, "label": "FIXTURE Community Zero", "size": 11}, {"id": 1, "label": "FIXTURE Community One", "size": 4},
                    {"id": 2, "label": "FIXTURE Community Two", "size": 3}, {"id": 3, "label": "FIXTURE Community Three", "size": 6}],
    "view_graph": {"nodes": anodes, "edges": aedges},
})

# ---------------------------------------------------------------- q_conflict.json
cg = nx.Graph()
cg.add_edges_from([("C_T4", "C_P3"), ("C_T4", "C_K07"), ("C_K07", "C_P1"), ("C_T4", "C_K08"), ("C_T4", "C_OLD"),
                   ("C_K08", "C_K09"), ("C_K09", "C_RIM")])
cpos = layout(cg)
cnames = {"C_T4": SCORED["C_T4"]["name"], "C_P3": "FIXTURE Portfolio Three", "C_K07": "FIXTURE Customer Golf",
          "C_K08": "FIXTURE Customer Hotel", "C_K09": "FIXTURE Customer India", "C_P1": PLAT[1],
          "C_OLD": "FIXTURE Former Holding", "C_RIM": "FIXTURE Rim Holding"}
ctags = {"C_T4": ["subject"], "C_OLD": ["context"], "C_RIM": ["context"]}
cedges = [("CE1", "C_T4", "C_P3", "FIXTURE supplies"), ("CE2", "C_T4", "C_K07", "FIXTURE supplies"),
          ("CE3", "C_P1", "C_K07", "FIXTURE supplies"), ("CE4", "C_T4", "C_K08", None), ("CE5", "C_T4", "C_OLD", "FIXTURE supplies"),
          ("CE6", "C_K09", "C_K08", None), ("CE7", "C_K09", "C_RIM", None)]
dump("q_conflict.json", {
    "question_id": "Q-CONFLICT",
    "business_question": "FIXTURE. Does this target conflict with anything we own, and would it breach the sector guideline?",
    "subject": {"company_id": "C_T4", "name": SCORED["C_T4"]["name"], "thesis_area": "FIXTURE Area One"},
    "max_distance": 2,
    "rule_ids": ["NORTHWIND_HOLDING", "PORTFOLIO_EXPOSURE", "CONCENTRATION"],
    "exposures": [{"company_id": "C_P3", "name": "FIXTURE Portfolio Three", "fund_name": "FIXTURE Fund III", "since": "2000-01-01",
                   "distance": 1, "kind": "conflict", "kind_label": "FIXTURE Conflict - cross-fund review",
                   "evidence": "FIXTURE. Target supplies this portfolio company.", "path_node_ids": ["C_T4", "C_P3"],
                   "edge_ids": ["CE1"], "rule_id": "PORTFOLIO_EXPOSURE"},
                  {"company_id": "C_P1", "name": PLAT[1], "fund_name": "Fixture Fund IV", "since": "2000-02-02", "distance": 2,
                   "kind": "informational", "kind_label": "FIXTURE Shared customer",
                   "evidence": "FIXTURE. Target supplies FIXTURE Customer Golf, which buys from the platform.",
                   "path_node_ids": ["C_T4", "C_K07", "C_P1"], "edge_ids": ["CE2", "CE3"], "rule_id": "PORTFOLIO_EXPOSURE"}],
    "context": [{"company_id": "C_OLD", "name": "FIXTURE Former Holding", "distance": 1,
                 "reason": "FIXTURE. Sold 2000-03-03, so not a current holding.", "edge_ids": ["CE5"]},
                {"company_id": "C_RIM", "name": "FIXTURE Rim Holding", "distance": 3,
                 "reason": "FIXTURE. Outside the 2-hop check.", "edge_ids": ["CE6", "CE7"]}],
    "concentration": {"fund_name": "Fixture Fund IV", "fund_size_musd": 1000.0, "guideline_pct": 35.0, "check_musd": 55.5,
                      "subject_area": "FIXTURE Area One", "breach": True, "headroom_musd": 22.2, "over_by_musd": 33.3,
                      "rule_id": "CONCENTRATION",
                      "areas": [{"name": "FIXTURE Area One", "before_musd": 327.8, "before_pct": 32.8, "after_musd": 383.3, "after_pct": 38.3,
                                 "is_subject_area": True, "breach": True},
                                {"name": "FIXTURE Area Two", "before_musd": 111.1, "before_pct": 11.1, "after_musd": 111.1, "after_pct": 11.1,
                                 "is_subject_area": False, "breach": False},
                                {"name": "FIXTURE Area Three", "before_musd": 0.0, "before_pct": 0.0, "after_musd": 0.0, "after_pct": 0.0,
                                 "is_subject_area": False, "breach": False}],
                      "holdings": [{"company_id": "C_H1", "name": "FIXTURE Holding One", "area": "FIXTURE Area One", "niche": "FIXTURE Niche One",
                                    "since": "2000-01-01", "equity_musd": 200.0, "pct": 20.0},
                                   {"company_id": "C_H2", "name": "FIXTURE Holding Two", "area": "FIXTURE Area One", "niche": "FIXTURE Niche Two",
                                    "since": "2000-01-01", "equity_musd": 127.8, "pct": 12.8},
                                   {"company_id": "C_P1", "name": PLAT[1], "area": "FIXTURE Area Two", "niche": "FIXTURE Platform Niche",
                                    "since": "2000-02-02", "equity_musd": 111.1, "pct": 11.1}]},
    "view_graph": {"nodes": [{"id": n, "label": cnames[n], "type": "company", "x": cpos[n][0], "y": cpos[n][1], "tags": ctags.get(n, [])}
                             for n in sorted(cg.nodes)],
                   "edges": [dict({"id": e, "source": a, "target": b, "type": "commercial"}, **({"label": l} if l else {}))
                             for e, a, b, l in cedges]},
})

# ---------------------------------------------------------------- graph.json (global)
gg = nx.Graph()
gnodes = {}


def addn(nid, label, typ, tags=(), facts=()):
    gnodes[nid] = {"id": nid, "label": label, "type": typ, "tags": list(tags), "facts": list(facts)}
    gg.add_node(nid)


for r in rows:
    tags = []
    if r["tier"] == "A":
        tags.append("tier_a")
    if not r["in_crm"]:
        tags.append("not_in_crm")
    addn(r["company_id"], r["name"], "company", tags,
         [{"label": "Score", "value": r["score"], "fmt": "int", "rule_id": "FIT_THESIS"},
          {"label": "Tier", "value": r["tier"]}, {"label": "EBITDA", "value": r["ebitda_musd"], "fmt": "musd1"}])
for k, (nm, title) in P.items():
    addn(k, nm, "person", ["our_person", "northwind"] if k in SEEDS else [], [{"label": "Title", "value": title}])
for oid, nm in INTS:
    addn(oid, nm, "intermediary", ["coverage_gap"] if oid == "O_I1" else [], [{"label": "Touchpoints (24 months)", "value": touch[oid], "fmt": "int", "rule_id": "COVERAGE_GAP"}])
for oid, nm in SPONS:
    addn(oid, nm, "sponsor")
addn("O_NW", "FIXTURE Capital", "sponsor", ["northwind"])
addn("F_III", "FIXTURE Fund III", "fund", ["northwind"])
addn("F_IV", "Fixture Fund IV", "fund", ["northwind"])
addn("C_P1", PLAT[1], "company", ["platform"])
addn("C_P3", "FIXTURE Portfolio Three", "company", ["fund_iii_portfolio"])
for cid, nm in CUST:
    addn(cid, nm, "company")
for cid, nm, *_ in CANDS:
    addn(cid, nm, "company")
for i in range(60):
    addn(f"P_N{i:02d}", f"FIXTURE Person {GREEK[i % 20]} {i // 20 + 1}", "person")
for i, (cid, nm) in enumerate(FCOS):
    if cid not in gnodes:
        addn(cid, nm, "company")

gedges = []
EDGE_RULE = {"tenure": "K1_TENURE", "board": "K1_BOARD", "deal": "K2_DEAL", "commercial": "COMMERCIAL", "crm": "K3_CRM",
             "ownership": "OWNERSHIP", "employment": "EMPLOYMENT"}


def adde(a, b, typ, evidence, facts=()):
    eid = f"GE{len(gedges) + 1:04d}"
    gedges.append({"id": eid, "source": a, "target": b, "type": typ, "evidence": evidence, "rule_id": EDGE_RULE[typ], "facts": list(facts)})
    gg.add_edge(a, b)


for e, a, b, t in pe:
    if t != "REJECTED":
        adde(a, b, "tenure" if t == "K1" else "deal", f"FIXTURE {t} evidence",
             [{"label": "Strength", "value": 0.5, "fmt": "f3", "rule_id": EDGE_RULE["tenure" if t == "K1" else "deal"]}])
for s in SEEDS:
    adde(s, "O_NW", "employment", "FIXTURE current role")
adde("O_NW", "F_III", "ownership", "FIXTURE manages fund")
adde("O_NW", "F_IV", "ownership", "FIXTURE manages fund")
adde("F_IV", "C_P1", "ownership", "FIXTURE owns since 2000-01-01")
adde("F_III", "C_P3", "ownership", "FIXTURE owns since 2000-01-01")
adde("C_T4", "C_P3", "commercial", "FIXTURE supplies")
for k in CUST[:9]:
    adde(k[0], "C_P1", "commercial", "FIXTURE buys from platform")
for cid, nm, niche, st, shared, comm in CANDS:
    for j in shared:
        adde(CUST[j][0], cid, "commercial", "FIXTURE buys from candidate")
for d in deals:
    adde(d["advisor_ids"][0], d["target_id"], "deal", f"FIXTURE advised {d['txn_id']}")
people = [k for k in gnodes if k.startswith("P_N")]
orgs = [k for k in gnodes if k.startswith(("C_", "O_I", "O_S"))]
for p in people:
    adde(p, RNG.choice(orgs), "employment", "FIXTURE role")
for _ in range(50):
    a, b = RNG.sample(people, 2)
    adde(a, b, RNG.choice(["tenure", "board"]), "FIXTURE overlap")
for _ in range(12):
    adde(RNG.choice(SEEDS), RNG.choice(people), "crm", "FIXTURE positive meetings",
         [{"label": "Meetings (24 months)", "value": RNG.randint(1, 4), "fmt": "int", "rule_id": "K3_CRM"}])
for nid in sorted(gnodes):
    if gg.degree(nid) == 0:
        adde(nid, "O_NW" if nid.startswith("P_") else "O_S1", "employment", "FIXTURE link so no node is isolated")
gpos = layout(gg, seed=42)
for n in gnodes.values():
    n["x"], n["y"] = gpos[n["id"]]
counts = {}
for e in gedges:
    counts[e["type"]] = counts.get(e["type"], 0) + 1
ET = [("tenure", "Tenure overlap"), ("board", "Board co-service"), ("deal", "Deal"), ("commercial", "Commercial"),
      ("crm", "CRM"), ("ownership", "Ownership"), ("employment", "Current role")]
dump("graph.json", {
    "layout": {"algorithm": "networkx.spring_layout", "seed": 42, "scale": SCALE},
    "stats": {"num_nodes": len(gnodes), "num_edges": len(gedges), "model_nodes": 9999, "model_edges": 99999},
    "node_types": [{"id": "company", "label": "Company"}, {"id": "person", "label": "Person"},
                   {"id": "sponsor", "label": "Sponsor"}, {"id": "intermediary", "label": "Intermediary"}, {"id": "fund", "label": "Fund"}],
    "edge_types": [{"id": t, "label": lab, "rule_id": EDGE_RULE[t], "count": counts.get(t, 0)} for t, lab in ET],
    "nodes": list(gnodes.values()),
    "edges": gedges,
})

# ---------------------------------------------------------------- sql_baseline.json
dump("sql_baseline.json", {"questions": {
    "Q-SCORE": {"sql_file": "data/naive_sql/q_score.sql", "description": "FIXTURE keyword and signal-count screen",
                "metric_label": "Signals (12 months)", "row_count": 41, "kg_count": len(tier_a), "kg_label": "Tier A",
                "rows": [{"entity_id": "C_X3", "name": "FIXTURE Busy Decoy", "rank": 1, "metric": 9, "verdict": "decoy", "note": "FIXTURE. Lots of signals, none that matter."},
                         {"entity_id": "C_X2", "name": "FIXTURE Off Thesis Co", "rank": 2, "metric": 7, "verdict": "decoy", "note": "FIXTURE. Keyword match outside the thesis."},
                         {"entity_id": "C_T1", "name": SCORED["C_T1"]["name"], "rank": 3, "metric": 4, "verdict": "agrees", "note": None}],
                "missed": [{"entity_id": "C_T5", "name": SCORED["C_T5"]["name"], "note": "FIXTURE. No keyword in its name."}]},
    "Q-PATH": {"sql_file": "data/naive_sql/q_path.sql", "description": "FIXTURE shared-employer join",
               "metric_label": "Shared employers", "row_count": 7, "kg_count": 2, "kg_label": "Warm targets",
               "rows": [{"entity_id": "C_T3", "name": "FIXTURE Seed Person Three to FIXTURE CEO Charlie", "rank": 1, "metric": 1, "verdict": "decoy", "note": "FIXTURE. Never overlapped."}],
               "missed": []},
    "Q-FLOW": {"sql_file": "data/naive_sql/q_flow.sql", "description": "FIXTURE deal-count league table",
               "metric_label": "Deals (5 years)", "row_count": len(INTS), "kg_count": 1, "kg_label": "Coverage gaps",
               "rows": [{"entity_id": i["org_id"], "name": i["name"], "rank": n + 1, "metric": i["deals_5y_all_sectors"],
                         "verdict": "decoy" if i["org_id"] == "O_I3" else "other", "note": None}
                        for n, i in enumerate(sorted(intermediaries, key=lambda x: (-x["deals_5y_all_sectors"], x["name"])))],
               "missed": []},
    "Q-ADDON": {"sql_file": "data/naive_sql/q_addon.sql", "description": "FIXTURE same-niche screen",
                "metric_label": "Revenue ($M)", "row_count": 3, "kg_count": 3, "kg_label": "Candidates",
                "rows": [{"entity_id": "C_D1", "name": "FIXTURE Same Niche Co", "rank": 1, "metric": 55.5, "verdict": "decoy", "note": "FIXTURE. No overlap."}],
                "missed": [{"entity_id": "C_A1", "name": "FIXTURE Addon Alpha", "note": "FIXTURE. Sibling niche."}]},
    "Q-CONFLICT": {"sql_file": "data/naive_sql/q_conflict.sql", "description": "FIXTURE direct-ownership check",
                   "metric_label": "Owned by us", "row_count": 0, "kg_count": 1, "kg_label": "Conflicts",
                   "rows": [], "missed": [{"entity_id": "C_P3", "name": "FIXTURE Portfolio Three", "note": "FIXTURE. Two-hop link."}]},
}})
print("FIXTURE exports written to", OUT)
