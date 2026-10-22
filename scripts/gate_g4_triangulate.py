#!/usr/bin/env python
"""R18 Gatekeeper: independent triangulation golden = oracle = RAI (PROMPT.md 9.1), plus evidence and decoy scans.

Reads only files (no engine, no Snowflake):
  data/golden/expected.json     generator intent
  data/oracle_output.json       independent pandas/networkx oracle
  tests/out/hero_outputs.json   RAI outputs written by `make test` (or pass --rai PATH)

Usage: .venv/bin/python scripts/gate_g4_triangulate.py [--rai PATH]
Exit 0 only if every check passes. Written for gates/G4.md; deliberately does not import tests/ or pe_deal_graph/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--rai", default=str(ROOT / "tests/out/hero_outputs.json"))
args = ap.parse_args()

G = json.loads((ROOT / "data/golden/expected.json").read_text())["questions"]
O = json.loads((ROOT / "data/oracle_output.json").read_text())
raw = Path(args.rai).read_bytes()
H = json.loads(raw)
print(f"rai file {args.rai} sha256 {hashlib.sha256(raw).hexdigest()}")

fails: list[str] = []
n_ok = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global n_ok
    if cond:
        n_ok += 1
        print(f"  ok   {label}")
    else:
        fails.append(f"{label} {detail}")
        print(f"  FAIL {label} {detail}")


def rows(fn: str, key: str | None = None):
    f = H[fn] if key is None else H[fn][key]
    return [dict(zip(f["columns"], r)) for r in f["rows"]]


def close(a, b, tol=1e-3):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def comp_dict(s: str) -> dict:
    return {k: int(v) for k, v in (p.rsplit(" ", 1) for p in s.split("; "))} if s else {}


# ---------------------------------------------------------------- Q-SCORE
print("Q-SCORE")
g = G["Q-SCORE"]["tier_a_ranked"]
o = O["Q-SCORE"]["answer"]["tier_a"]
r = rows("q_score")
check("ids+order golden == oracle == RAI",
      [x["key"]["id"] for x in g] == [x["company_id"] for x in o] == [x["company_id"] for x in r] or
      # oracle may use its own tie order; require golden == RAI strictly and oracle as a set + same scores
      ([x["key"]["id"] for x in g] == [x["company_id"] for x in r] and
       {x["company_id"] for x in o} == {x["company_id"] for x in r}),
      f"golden={[x['key']['id'] for x in g]} oracle={[x['company_id'] for x in o]} rai={[x['company_id'] for x in r]}")
check("golden order == RAI order (strict)", [x["key"]["id"] for x in g] == [x["company_id"] for x in r])
print("    oracle order:", [x["company_id"] for x in o], "ranks", [x["rank"] for x in o])
omap = {x["company_id"]: x for x in o}
for gi, ri in zip(g, r):
    cid = gi["key"]["id"]
    oi = omap.get(cid, {})
    oc = {c["component"]: c["points"] for c in oi.get("components", [])}
    check(f"{gi['key']['name']}: score/fit/readiness/access golden=oracle=RAI",
          (gi["score"], gi["fit"], gi["readiness"], gi["access"]) ==
          (oi.get("score"), oi.get("fit"), oi.get("readiness"), oi.get("access")) ==
          (ri["score"], ri["fit"], ri["readiness"], ri["access"]),
          f"g={gi['score'], gi['fit'], gi['readiness'], gi['access']} o={oi.get('score')} r={ri['score']}")
    check(f"{gi['key']['name']}: components golden=oracle=RAI", gi["components"] == oc == comp_dict(ri["components"]),
          f"g={gi['components']} o={oc} r={comp_dict(ri['components'])}")
    check(f"{gi['key']['name']}: rank golden == RAI", gi["rank"] == ri["rank"])
gn = {x["name"] for x in G["Q-SCORE"]["not_in_crm"]}
rn = {x["name"] for x in r if not x["in_crm"]}
on = set(O["Q-SCORE"]["answer"]["not_in_crm_tier_a"])
check("not_in_crm golden == oracle == RAI", gn == rn == on, f"{gn} {on} {rn}")

# ---------------------------------------------------------------- Q-PATH
print("Q-PATH")
gp = G["Q-PATH"]["rows"]
op = O["Q-PATH"]["answer"]["rows"]
rp = rows("q_path")
rwarm = {(x["company_id"], x["person_id"]): x for x in rp if x["path_rank"] == 1 or x["status"] == "cold"}
rpath = {(x["company_id"], x["person_id"], x["path_rank"]): x for x in rp}
check("RAI row set == golden row set (target, decision maker)",
      {(x["target"]["id"], x["decision_maker"]["id"]) for x in gp} == {(a, b) for a, b, _ in rpath},
      f"{sorted({(x['target']['id'], x['decision_maker']['id']) for x in gp})} vs {sorted({(a, b) for a, b, _ in rpath})}")
check("oracle row set == golden row set",
      {(x["target_id"], x["decision_maker_id"]) for x in op} == {(x["target"]["id"], x["decision_maker"]["id"]) for x in gp})
ormap = {(x["target_id"], x["decision_maker_id"]): x for x in op}
for x in gp:
    t, d = x["target"]["id"], x["decision_maker"]["id"]
    nm = f"{x['target']['name']} / {x['decision_maker']['name']}"
    ro = ormap.get((t, d), {})
    if x.get("cold"):
        rr = rpath.get((t, d, None)) or next((v for k, v in rpath.items() if k[:2] == (t, d)), {})
        check(f"{nm}: cold in golden, oracle and RAI",
              rr.get("status") == "cold" and ro.get("within_3_hops") is False and ro.get("best_path") in (None, {}) and rr.get("strength") is None,
              f"rai={rr.get('status')} oracle_hops={ro.get('hops')} within_3={ro.get('within_3_hops')}")
        continue
    rr = rpath.get((t, d, 1), {})
    gnames = " > ".join(p["name"] for p in x["best_path"])
    onames = " > ".join(ro.get("best_path", {}).get("persons", []))
    check(f"{nm}: best path names golden=oracle=RAI", gnames == onames == rr.get("path"), f"{gnames} | {onames} | {rr.get('path')}")
    check(f"{nm}: hops/strength golden=oracle=RAI",
          x["hops"] == ro.get("hops") == rr.get("hops") and close(x["path_strength"], ro["best_path"]["strength"]) and close(x["path_strength"], rr.get("strength")),
          f"g={x['hops'], x['path_strength']} o={ro.get('hops')} r={rr.get('hops'), rr.get('strength')}")
    check(f"{nm}: hop strengths golden == oracle",
          [round(h, 3) for h in x["hop_strengths"]] == [round(h["strength"], 3) for h in ro["best_path"]["hop_detail"]],
          f"{x['hop_strengths']} vs {[h['strength'] for h in ro['best_path']['hop_detail']]}")
    for alt in x.get("alternates", []):
        ra = rpath.get((t, d, alt["rank"]), {})
        check(f"{nm}: alternate {alt['rank']} golden == RAI",
              " > ".join(p["name"] for p in alt["path"]) == ra.get("path") and close(alt["path_strength"], ra.get("strength")),
              f"{ra.get('path')} {ra.get('strength')}")
# no extra RAI alternates beyond golden
galt = {(x["target"]["id"], x["decision_maker"]["id"], a["rank"]) for x in gp for a in x.get("alternates", [])}
extra = {k for k in rpath if k[2] is not None and k[2] > 1} - galt
check("RAI has no alternate path rows beyond golden", not extra, str(extra))

# ---------------------------------------------------------------- Q-FLOW
print("Q-FLOW")
gf = G["Q-FLOW"]
of = O["Q-FLOW"]["answer"]["top5"]
rf = rows("q_flow")
check("RAI top5 ids+order == oracle top5", [x["intermediary_id"] for x in rf] == [x["intermediary_id"] for x in of],
      f"{[x['intermediary_id'] for x in rf]} vs {[x['intermediary_id'] for x in of]}")
check("RAI betweenness == oracle (rel 1e-6)", all(abs(a["betweenness"] - b["betweenness"]) <= 1e-6 * b["betweenness"] + 1e-3 for a, b in zip(rf, of)),
      f"{[(a['betweenness'], b['betweenness']) for a, b in zip(rf, of)]}")
check("RAI touchpoints == oracle", [x["our_touchpoints"] for x in rf] == [x["touchpoints_24m"] for x in of])
check("RAI thesis deals == oracle", [x["thesis_deals"] for x in rf] == [x["deals_in_window_thesis"] for x in of])
check("golden ranks 1,2 (Cedar Row, Harbor Lane) == RAI ranks 1,2 == oracle",
      [(x["rank"], x["key"]["id"]) for x in gf["betweenness_rank_intermediaries"]] == [(x["rank"], x["intermediary_id"]) for x in rf[:2]]
      == [(x["rank"], x["intermediary_id"]) for x in of[:2]])
gtp = gf["touchpoints_24m"]
check("golden touchpoints Cedar 14 / HL 1 == RAI", rf[0]["our_touchpoints"] == gtp["CEDAR"] and rf[1]["our_touchpoints"] == gtp["HL"])
check("golden HL deals in window == RAI", rf[1]["thesis_deals"] == gf["hl_deals_in_window"])
check("coverage gap golden == oracle == RAI",
      [x["id"] for x in gf["coverage_gaps"]] == [x["intermediary_id"] for x in O["Q-FLOW"]["answer"]["coverage_gaps"]]
      == [x["intermediary_id"] for x in rf if x["coverage_gap"]])
check("Brayford (BIGBANK I736) not in RAI top 5, golden min rank 11", "I736" not in {x["intermediary_id"] for x in rf} and gf["bigbank_min_rank"] == 11)

# ---------------------------------------------------------------- Q-CONFLICT
print("Q-CONFLICT")
gc = G["Q-CONFLICT"]
oc = O["Q-CONFLICT"]["answer"]
rce = rows("q_conflict", "exposures")
rcc = rows("q_conflict", "concentration")
gset = [(x["key"]["id"], x["fund"]["id"], x["distance"], x["kind"]) for x in gc["exposure_rows"]]
check("exposures golden == oracle == RAI (id, fund, distance, kind, order)",
      gset == [(x["company_id"], x["fund_id"], x["commercial_distance"], x["kind"]) for x in oc["exposures"]]
      == [(x["company_id"], next(f["fund"]["id"] for f in gc["exposure_rows"] if f["key"]["id"] == x["company_id"]), x["distance"], x["verdict"]) for x in rce],
      f"{gset} | {[(x['company_id'], x['distance'], x['verdict']) for x in rce]}")
check("RAI exposure fund names == golden", [x["fund"] for x in rce] == [
    next(f["fund"]["name"] for f in gc["exposure_rows"] if f["key"]["id"] == x["company_id"]) for x in rce])
gareas = gc["concentration"]["areas"]
rarea = {x["area"]: x for x in rcc}
oarea = {x["thesis_area"]: x for x in oc["concentration"]}
for area, a in gareas.items():
    rr, oo = rarea.get(area, {}), oarea.get(area, {})
    check(f"{area}: before/after pct golden=oracle=RAI",
          close(a["before_pct"], oo.get("before_pct"), 0.01) and close(a["after_pct"], oo.get("with_subject_pct"), 0.01)
          and close(a["before_pct"], rr.get("current_pct"), 0.01) and close(a["after_pct"], rr.get("pro_forma_pct"), 0.01),
          f"g={a['before_pct'], a['after_pct']} o={oo.get('before_pct'), oo.get('with_subject_pct')} r={rr.get('current_pct'), rr.get('pro_forma_pct')}")
    if "breach" in a:
        check(f"{area}: breach flag golden=oracle=RAI, over_by", a["breach"] == oo["breach"] == rr["breach"] and close(gc["concentration"]["over_by_musd"], rr["over_by_musd"]) and close(gc["concentration"]["over_by_musd"], oo["over_by_musd"]))
check("only Specialty Distribution breaches (golden, oracle, RAI)",
      oc["breaches"] == ["Specialty Distribution"] == [x["area"] for x in rcc if x["breach"]])

# ---------------------------------------------------------------- FINALE
print("FINALE")
gfin = G["FINALE"]
ofin = O["FINALE"]["answer"]
rfin = rows("finale_rescore")
rt = [x for x in rfin if x["on_tier_a"]]
rflag = [x for x in rfin if x["flag"]]
gt = [(x["key"]["id"], x["score"]) for x in gfin["tier_a_ranked"]]
check("Tier A ids+order+score golden == oracle == RAI",
      gt == [(x["company_id"], x["score"]) for x in ofin["tier_a"]] == [(x["company_id"], x["score"]) for x in rt],
      f"{gt} | {[(x['company_id'], x['score']) for x in ofin['tier_a']]} | {[(x['company_id'], x['score']) for x in rt]}")
check("ranks 1..6 in RAI", [x["rank"] for x in rt] == [1, 2, 3, 4, 5, 6])
check("warm path set golden == oracle == RAI (access change +10)",
      {x["id"] for x in gfin["warm_path_set"]} == {x["company_id"] for x in ofin["tier_a"] if x.get("A_WARM_PATH")} ==
      {x["company_id"] for x in rt if x["change"] == 10})
check("flagged-off conflict golden == oracle == RAI",
      [x["key"]["id"] for x in gfin["conflicts"]] == [x["company_id"] for x in ofin["flagged_off_tier_a"]] ==
      [x["company_id"] for x in rflag if x["score"] >= 70 and not x["on_tier_a"]])
check("Tessmark not in RAI Tier A rows", "C8200" not in {x["company_id"] for x in rt})

# ---------------------------------------------------------------- explanation evidence
print("EVIDENCE per answer row")
date = re.compile(r"\d{4}-\d{2}")
for x in rows("q_score"):
    c = comp_dict(x["components"])
    check(f"q_score {x['name']}: components sum to score ({sum(c.values())}) and why cites them",
          sum(c.values()) == x["score"] and len(c) >= 6 and "+" in x["why"] and len(x["why"]) > 150)
for x in rows("q_path"):
    if x["status"] == "warm":
        hops = x["path"].count(" > ")
        check(f"q_path {x['target']} / {x['decision_maker']} rank {x['path_rank']}: {hops} hops, tenure dates in why",
              hops == x["hops"] and len(date.findall(x["why"])) >= x["hops"] and "tie" in x["why"])
    else:
        check(f"q_path {x['target']} / {x['decision_maker']}: cold reason stated", x["why"].startswith("Cold:") and "hops" in x["why"])
for x in rf:
    check(f"q_flow {x['name']}: centrality + touchpoints in why",
          "betweenness" in x["why"] and "touchpoint" in x["why"] and x["betweenness"] > 0 and x["our_touchpoints"] is not None)
for x in rce:
    check(f"q_conflict {x['name']}: conflict path in why", " supplies " in x["why"] or " buys from " in x["why"] or "links away" in x["why"]
          or "commercial link" in x["why"])
for x in rcc:
    check(f"q_conflict {x['area']}: concentration figures in why", "%" in x["why"] and "$" in x["why"] and "guideline" in x["why"])
for x in rfin:
    check(f"finale {x['name']}: why present", len(x["why"]) > 150 and ("+" in x["why"]))

# ---------------------------------------------------------------- decoys
print("DECOY names")


def strip_note(n: str) -> str:
    return re.sub(r"\s*\(.*\)$", "", n)


def ents(o):
    if isinstance(o, dict):
        if isinstance(o.get("id"), str) and isinstance(o.get("name"), str):
            yield o["name"]
        for v in o.values():
            yield from ents(v)
    elif isinstance(o, list):
        for v in o:
            yield from ents(v)


required: dict[str, set] = {}
for q, gq in G.items():
    for n in gq.get("rehearsal", {}).get("must_appear", []):
        required.setdefault(strip_note(n), set()).add(q)
    ans = {k: v for k, v in gq.items() if k in ("tier_a_ranked", "ranked", "rows", "betweenness_rank_intermediaries", "coverage_gaps",
                                                 "exposure_rows", "fund_iv_holdings", "conflicts", "warm_path_set", "subject")}
    for n in ents(ans):
        required.setdefault(n, set()).add(q)
decoys: set[str] = set()
for gq in G.values():
    for k in ("must_not_contain", "tier1_must_not_appear"):
        for e in gq.get(k, []):
            decoys.add(e["name"])
    decoys |= set(gq.get("rehearsal", {}).get("must_not_appear", []))
QF = {"Q-SCORE": ["q_score"], "Q-PATH": ["q_path"], "Q-FLOW": ["q_flow"], "Q-CONFLICT": ["q_conflict"], "FINALE": ["finale_rescore"]}


def texts(fn):
    out = []
    v = H[fn]
    frames = [v] if "columns" in v else list(v.values())
    for f in frames:
        for r_ in f["rows"]:
            out += ["" if c is None else str(c) for c in r_]
    return out


alltext = {fn: texts(fn) for fn in H}
print(f"  decoy name set ({len(decoys)}): {sorted(decoys)}")
global_decoys = {n for n in decoys if n not in required}
hits = [f"{fn}: {n}" for fn, ts in alltext.items() for n in global_decoys if any(n in t for t in ts)]
check(f"no globally-forbidden decoy name ({len(global_decoys)} names) in any cell of any hero output", not hits, str(hits))
hits = []
for q, fns in QF.items():
    for e in G[q].get("must_not_contain", []):
        n = e["name"]
        if q in required.get(n, set()):
            continue
        for fn in fns:
            if any(n in t for t in alltext[fn]):
                hits.append(f"{fn}: {n}")
        # by id as an answer-row key
    ids = {e["id"] for e in G[q].get("must_not_contain", []) if q not in required.get(e["name"], set())}
    for fn in fns:
        for t in alltext[fn]:
            if t in ids:
                hits.append(f"{fn}: id {t}")
check("each question's own must_not_contain names and ids absent from its output (unless that question requires the name)", not hits, str(hits))
exempt = sorted(n for n in decoys if n in required)
print(f"  names in must_not lists that some question requires (checked per question, not globally): {exempt}")

print(f"\nSUMMARY {n_ok} ok, {len(fails)} fail")
for f in fails:
    print("FAIL:", f)
print("G4 TRIANGULATION", "PASS" if not fails else "FAIL")
sys.exit(1 if fails else 0)
