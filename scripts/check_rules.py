"""Per-rule check of pe_deal_graph/model/rules.py against data/golden/expected.json (owner: R09).

Runs live RAI queries on the loaded data and prints one line per check: PASS/FAIL, the rule, the
golden value and the RAI value. Golden ids are read here only to compare; rules.py never sees them.

Usage:
    .venv/bin/python scripts/check_rules.py                  # rules only (Act 1, Knows, flow counts, concentration)
    .venv/bin/python scripts/check_rules.py --graphs         # also import graphs.py: coverage gap, exposure, path dms
    .venv/bin/python scripts/check_rules.py --graphs --finale
    .venv/bin/python scripts/check_rules.py --only score,knows
Exit code 0 when every executed check passes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GOLDEN = json.loads((ROOT / "data" / "golden" / "expected.json").read_text())
Q = GOLDEN["questions"]
CAST = GOLDEN["cast"]
RESULTS: list[tuple[bool, str, str, str]] = []


def cid(key: str) -> str:
    return CAST[key]["id"]


def check(ok: bool, rule: str, golden, rai) -> None:
    RESULTS.append((bool(ok), rule, str(golden), str(rai)))
    print(f"{'PASS' if ok else 'FAIL'}  {rule:<44} golden={golden}  rai={rai}", flush=True)


def df_sorted(df, cols):
    return df.sort_values(cols).reset_index(drop=True)


def run_score(m, R):
    from relationalai.semantics.std import aggregates as aggs  # noqa: F401
    C = m.Company
    t0 = time.time()
    df = m.model.where(m.EligibleTarget(C)).select(
        C.id.alias("id"), C.name.alias("name"), C.score.alias("score"), C.fit_points.alias("fit"),
        C.readiness_points.alias("readiness"), C.access_points.alias("access"), C.tier.alias("tier"),
        C.score_rank.alias("rank"), C.why.alias("why"), C.why_not.alias("why_not")).to_df()
    df = df_sorted(df, ["rank"])
    print(f"  (score query {time.time() - t0:.1f}s, {len(df)} eligible targets)")
    tier_a = df[df.tier == "A"]
    want = [(r["key"]["id"], r["score"]) for r in Q["Q-SCORE"]["tier_a_ranked"]]
    got = [(r.id, int(r.score)) for r in tier_a.itertuples()]
    check(got == want, "Q-SCORE Tier A ranked (id, score)", want, got)
    for r in Q["Q-SCORE"]["tier_a_ranked"] + Q["Q-SCORE"]["tier_b_reference"]:
        row = df[df.id == r["key"]["id"]]
        g = (r["fit"], r["readiness"], r["access"])
        v = tuple(int(x) for x in row[["fit", "readiness", "access"]].iloc[0]) if len(row) else None
        check(g == v, f"pillars {r['key']['key']}", g, v)
    sc = m.ScoreComponent
    comp = m.model.select(sc.company.id.alias("id"), sc.code.alias("code"), sc.points.alias("points"),
                          sc.evidence.alias("evidence")).to_df()
    for r in Q["Q-SCORE"]["tier_a_ranked"] + Q["Q-SCORE"]["tier_b_reference"]:
        sub = comp[comp.id == r["key"]["id"]]
        got_c = {x.code: int(x.points) for x in sub.itertuples()}
        check(got_c == r["components"], f"components {r['key']['key']}", r["components"], got_c)
    nmb = df[df.id == cid("NM_B")]
    check(len(nmb) and nmb.tier.iloc[0] == "B", "tier NM_B", "B", nmb.tier.tolist())
    for r in Q["Q-SCORE"]["must_not_contain"]:
        check(r["id"] not in set(tier_a.id), f"must_not_contain {r['key']}", "absent", r["id"] in set(tier_a.id))
    ds = Q["Q-SCORE"]["d_short_reference"]
    row = df[df.id == ds["key"]["id"]]
    got_ds = (int(row.score.iloc[0]), row.tier.iloc[0], row.why_not.iloc[0]) if len(row) else None
    check(got_ds == (ds["score"], ds["tier"], ds["why_not"]), "D_SHORT score/tier/why_not",
          (ds["score"], ds["tier"], ds["why_not"]), got_ds)
    # in CRM
    crm = m.model.where(C.in_crm()).select(C.id.alias("id")).to_df()
    not_in = sorted(set(tier_a.id) - set(crm.id))
    want_ni = sorted(x["id"] for x in Q["Q-SCORE"]["not_in_crm"])
    check(not_in == want_ni, "in_crm: Tier A not in CRM", want_ni, not_in)
    # ineligible reasons
    inel = m.model.where(C.ineligible_reason).select(C.id.alias("id"), C.ineligible_reason.alias("reason")).to_df()
    for r in Q["Q-SCORE"]["ineligible_reference"]:
        got_r = inel[inel.id == r["key"]["id"]].reason.tolist()
        check(len(got_r) == 1, f"ineligible_reason {r['key']['key']}", r["reason"], got_r)
    print("  sample why (rank 1):", df.why.iloc[0])


def run_knows(m, R):
    P = m.Person
    k = m.Knows
    kn = m.model.select(k.p1.id.alias("a"), k.p2.id.alias("b"), k.strength.alias("s"),
                        k.evidence.alias("ev"), k.evidence_count.alias("n")).to_df()
    print(f"  ({len(kn)} Knows pairs)")
    lookup = {tuple(sorted((r.a, r.b))): r for r in kn.itertuples()}
    rows = Q["Q-PATH"]["rows"]
    pairs = []
    for r in rows:
        if r.get("best_path"):
            path = r["best_path"]
            pairs += [(path[i]["id"], path[i + 1]["id"], r["hop_strengths"][i], f"{path[i]['key']}-{path[i+1]['key']}")
                      for i in range(len(path) - 1)]
            for alt in r.get("alternates", []):
                ap = alt["path"]
                pairs += [(ap[i]["id"], ap[i + 1]["id"], alt["hop_strengths"][i], f"{ap[i]['key']}-{ap[i+1]['key']}")
                          for i in range(len(ap) - 1)]
    nb = Q["FINALE"]["nm_b_path"]
    pairs += [(nb["path"][i]["id"], nb["path"][i + 1]["id"], nb["hop_strengths"][i],
               f"{nb['path'][i]['key']}-{nb['path'][i+1]['key']}") for i in range(2)]
    for a, b, s, lab in pairs:
        row = lookup.get(tuple(sorted((a, b))))
        got = round(float(row.s), 3) if row is not None else None
        check(got is not None and abs(got - s) < 1e-3, f"Knows strength {lab}", s, got)
        if row is not None:
            print(f"      evidence: {row.ev}")
    dec = (cid("MD_MER"), cid("CEO_C"))
    check(tuple(sorted(dec)) not in lookup, "K1 rejects shared employer (MD_MER-CEO_C)", "no edge",
          tuple(sorted(dec)) in lookup)
    ke = m.KnowsEvidence
    ev = m.model.select(ke.p1.id.alias("a"), ke.p2.id.alias("b"), ke.kind.alias("kind"), ke.strength.alias("s"),
                        ke.label.alias("label")).to_df()
    vp_y = ev[((ev.a == cid("VP")) & (ev.b == cid("Y_BANK"))) | ((ev.b == cid("VP")) & (ev.a == cid("Y_BANK")))]
    got = sorted((x.kind, round(float(x.s), 2)) for x in vp_y.itertuples())
    check(got == [("K1", 0.7), ("K3", 1.0)], "evidence VP-Y_BANK (K1 0.70, K3 1.00)", [("K1", 0.7), ("K3", 1.0)], got)
    for x in vp_y.itertuples():
        print(f"      {x.kind}: {x.label}")
    # decision makers of the golden top three
    dm = m.DecisionMaker
    d = m.model.select(dm.target.id.alias("t"), dm.person.id.alias("p"), dm.kind.alias("kind")).to_df()
    for r in rows:
        hit = d[(d.t == r["target"]["id"]) & (d.p == r["decision_maker"]["id"])].kind.tolist()
        check(hit == [r["kind"]], f"DecisionMaker {r['target']['key']} {r['decision_maker']['key']}", r["kind"], hit)
    n_top3 = {r["target"]["id"] for r in rows}
    extra = d[d.t.isin(n_top3)]
    check(len(extra) == len(rows), "DecisionMaker count for top 3", len(rows), len(extra))
    C = m.Company
    ci = m.model.where(C.closest_intermediary).select(C.id.alias("c"), C.closest_intermediary.id.alias("i"),
                                                      C.closest_intermediary_evidence.alias("ev")).to_df()
    g = Q["Q-PATH"]["closest_intermediary"]
    row = ci[ci.c == g["target"]["id"]]
    got = (row.i.iloc[0], row.ev.iloc[0]) if len(row) else None
    check(got is not None and got[0] == g["intermediary"]["id"], "closest_intermediary T_COLD",
          (g["intermediary"]["name"], g["ties"]), got)
    seeds = m.model.where(m.OurSeed(P)).select(P.name.alias("n")).to_df()
    print("  seeds:", sorted(seeds.n))


def run_flow(m, R, graphs: bool):
    I = m.Intermediary
    df = m.model.select(I.id.alias("id"), I.name.alias("name"), I.touchpoints_24m.alias("tp"),
                        I.thesis_deals_5y.alias("thesis"), I.all_deals_5y.alias("all")).to_df()
    tp = Q["Q-FLOW"]["touchpoints_24m"]
    for key, v in tp.items():
        got = df[df.id == cid(key)].tp.tolist()
        check(got == [v], f"touchpoints_24m {key}", v, got)
    check(df[df.id == cid("HL")].thesis.tolist() == [Q["Q-FLOW"]["hl_deals_in_window"]], "thesis_deals_5y HL",
          Q["Q-FLOW"]["hl_deals_in_window"], df[df.id == cid("HL")].thesis.tolist())
    bb = df[df.id == cid("BIGBANK")]
    check((bb["all"].tolist(), bb.thesis.tolist()) == ([Q["Q-FLOW"]["bigbank_total_deals_5y"]],
                                                       [Q["Q-FLOW"]["bigbank_thesis_deals_5y"]]),
          "all_deals_5y / thesis_deals_5y BIGBANK", (40, 8), (bb["all"].tolist(), bb.thesis.tolist()))
    from relationalai.semantics import Integer
    q = Integer.ref()
    q1 = m.model.where(m.coverage_q1(q)).select(q.alias("q1")).to_df()
    check(q1.q1.tolist() == [Q["Q-FLOW"]["q1_touchpoints"]], "coverage_q1", Q["Q-FLOW"]["q1_touchpoints"],
          q1.q1.tolist())
    if graphs:
        c = Integer.ref()
        bc = m.model.where(m.bridge_cutoff(c)).select(c.alias("c")).to_df()
        check(bc.c.tolist() == [4], "bridge_cutoff (top decile 4)", 4, bc.c.tolist())
        gap = m.model.where(m.CoverageGap(I)).select(I.id.alias("id")).to_df()
        want = sorted(x["id"] for x in Q["Q-FLOW"]["coverage_gaps"])
        check(sorted(gap.id) == want, "CoverageGap", want, sorted(gap.id))


def run_conflict(m, R, graphs: bool):
    C = m.Company
    subj = m.model.where(m.ConflictSubject(C)).select(C.id.alias("id")).to_df()
    check(subj.id.tolist() == [Q["Q-CONFLICT"]["subject"]["id"]], "ConflictSubject", Q["Q-CONFLICT"]["subject"]["id"],
          subj.id.tolist())
    ae = m.AreaExposure
    a = m.model.select(ae.area.name.alias("area"), ae.current_musd.alias("musd"), ae.current_pct.alias("pct"),
                       ae.guideline_pct.alias("g")).to_df()
    pf = m.ProFormaExposure
    p = m.model.select(pf.area.name.alias("area"), pf.musd.alias("musd"), pf.pct.alias("pct"),
                       pf.headroom_musd.alias("headroom"), pf.over_by_musd.alias("over")).to_df()
    br = m.model.where(pf.is_breach()).select(pf.area.name.alias("area")).to_df()
    conc = Q["Q-CONFLICT"]["concentration"]
    for area, v in conc["areas"].items():
        ga = a[a.area == area]
        gp = p[p.area == area]
        got = (round(float(ga.pct.iloc[0]), 2) if len(ga) else None, round(float(gp.pct.iloc[0]), 2) if len(gp) else None)
        check(got == (v["before_pct"], v["after_pct"]), f"concentration {area}", (v["before_pct"], v["after_pct"]), got)
    sd = p[p.area == "Specialty Distribution"]
    got = (float(sd.headroom.iloc[0]), float(sd.over.iloc[0])) if len(sd) else None
    check(got == (conc["headroom_musd"], conc["over_by_musd"]), "headroom / over_by Specialty Distribution",
          (conc["headroom_musd"], conc["over_by_musd"]), got)
    check(sorted(br.area) == ["Specialty Distribution"], "is_breach", ["Specialty Distribution"], sorted(br.area))
    if graphs:
        pe = m.PortfolioExposure
        e = m.model.select(pe.company.id.alias("id"), pe.hops.alias("hops"), pe.kind.alias("kind"),
                           pe.fund.id.alias("fund"), pe.evidence.alias("ev")).to_df()
        want = sorted((r["key"]["id"], r["distance"], r["kind"], r["fund"]["id"]) for r in Q["Q-CONFLICT"]["exposure_rows"])
        got = sorted((r.id, int(r.hops), r.kind, r.fund) for r in e.itertuples())
        check(got == want, "PortfolioExposure rows", want, got)
        for r in e.itertuples():
            print(f"      {r.id}: {r.ev}")


def run_finale(m, R):
    R.enable_finale()
    C = m.Company
    df = m.model.where(m.EligibleTarget(C)).select(
        C.id.alias("id"), C.name.alias("name"), C.finale_score.alias("fs"), C.finale_tier.alias("ft"),
        C.finale_rank.alias("fr"), C.warm_path_points.alias("w"), C.finale_why.alias("why")).to_df()
    conf = m.model.where(C.has_conflict()).select(C.id.alias("id"), C.conflict_evidence.alias("ev")).to_df()
    ta = df_sorted(df[(df.ft == "A") & (~df.id.isin(conf.id))], ["fr"])
    want = [(r["key"]["id"], r["score"]) for r in Q["FINALE"]["tier_a_ranked"]]
    got = [(r.id, int(r.fs)) for r in ta.itertuples()]
    check(got == want, "FINALE Tier A ranked (id, score)", want, got)
    warm = sorted(df[df.w.fillna(0).astype(int) == 10].id)
    want_w = sorted(x["id"] for x in Q["FINALE"]["warm_path_set"])
    check(warm == want_w, "warm_path_points = 10 set", want_w, warm)
    tier_a_ids = {cid(k) for k in ("T_BANKER", "T_WARM", "T_COLD", "T_5", "CONF", "T_6", "NM_B")}
    got_c = sorted(set(conf.id) & tier_a_ids)
    want_c = sorted(x["key"]["id"] for x in Q["FINALE"]["conflicts"])
    check(got_c == want_c, "has_conflict among cast targets", want_c, got_c)
    print("  conflict evidence:", conf.ev.tolist()[:3])
    print("  finale why #1:", ta.why.iloc[0] if len(ta) else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphs", action="store_true", help="import graphs.py (R10) for graph-dependent rules")
    ap.add_argument("--finale", action="store_true", help="enable the Finale rules and check the re-score")
    ap.add_argument("--only", default="score,knows,flow,conflict", help="comma list of sections")
    args = ap.parse_args(argv)
    import pe_deal_graph.model.core as core
    import pe_deal_graph.model.rules as R
    if args.graphs:
        import pe_deal_graph.model.graphs  # noqa: F401
    from relationalai.semantics.std import aggregates as aggs

    class M:  # namespace of core names
        pass
    m = M()
    for n in core.__all__:
        setattr(m, n, getattr(core, n))
    m.aggs = aggs
    only = set(args.only.split(","))
    t0 = time.time()
    if "score" in only:
        print("== Q-SCORE rules"); run_score(m, R)
    if "knows" in only:
        print("== Knows / Q-PATH rules"); run_knows(m, R)
    if "flow" in only:
        print("== Q-FLOW rules"); run_flow(m, R, args.graphs)
    if "conflict" in only:
        print("== Q-CONFLICT rules"); run_conflict(m, R, args.graphs)
    if args.finale:
        print("== FINALE rules"); run_finale(m, R)
    n_fail = sum(1 for r in RESULTS if not r[0])
    print(f"\nSUMMARY: {len(RESULTS) - n_fail} pass, {n_fail} fail ({time.time() - t0:.0f}s)")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
