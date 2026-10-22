#!/usr/bin/env python
"""R18 Gatekeeper independent G2 check. Reads data/csv, data/golden/expected.json, data/oracle_output.json,
and queries Snowflake (RAI_DEMO_PE_DEALS.DEAL_GRAPH) read-only. Does not import generate.py/oracle.py/load.py.
Exit 0 only if every check passes."""
import json, re, sys
from pathlib import Path
import pandas as pd
import snowflake.connector, yaml

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "csv"
DB, SCH = "RAI_DEMO_PE_DEALS", "DEAL_GRAPH"
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" :: {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


man = json.loads((CSV / "MANIFEST.json").read_text())["tables"]
TABLES = sorted(man)
dfs = {t: pd.read_csv(CSV / man[t]["file"], dtype=str, keep_default_na=False, na_values=[""]) for t in TABLES}

PKS = {t: [f"{t.lower()}_id"] for t in TABLES}
PKS.update({"FUND_FOCUS": ["fund_id", "sector_id"], "COMPANY_SITE": ["company_id", "region_id"],
            "PIPELINE": ["company_id"], "COMPANY": ["company_id"], "TRANSACTION": ["txn_id"],
            "TRANSACTION_PARTY": ["party_id"], "COMMERCIAL_LINK": ["link_id"], "CRM_INTERACTION": ["interaction_id"],
            "ROLE_HISTORY": ["role_id"], "OWNERSHIP": ["ownership_id"], "COMPANY_SIGNAL": ["signal_id"],
            "REGION": ["region_id"], "SECTOR": ["sector_id"], "SPONSOR": ["sponsor_id"], "FUND": ["fund_id"],
            "INTERMEDIARY": ["intermediary_id"], "PERSON": ["person_id"]})
FKS = [  # (child, col, parent, pcol)
    ("SECTOR", "parent_id", "SECTOR", "sector_id"), ("REGION", "parent_id", "REGION", "region_id"),
    ("SPONSOR", "hq_region_id", "REGION", "region_id"), ("FUND", "sponsor_id", "SPONSOR", "sponsor_id"),
    ("FUND_FOCUS", "fund_id", "FUND", "fund_id"), ("FUND_FOCUS", "sector_id", "SECTOR", "sector_id"),
    ("INTERMEDIARY", "hq_region_id", "REGION", "region_id"),
    ("COMPANY", "sector_id", "SECTOR", "sector_id"), ("COMPANY", "hq_region_id", "REGION", "region_id"),
    ("COMPANY_SITE", "company_id", "COMPANY", "company_id"), ("COMPANY_SITE", "region_id", "REGION", "region_id"),
    ("ROLE_HISTORY", "person_id", "PERSON", "person_id"),
    ("OWNERSHIP", "company_id", "COMPANY", "company_id"), ("OWNERSHIP", "fund_id", "FUND", "fund_id"),
    ("TRANSACTION", "target_id", "COMPANY", "company_id"),
    ("TRANSACTION_PARTY", "txn_id", "TRANSACTION", "txn_id"), ("TRANSACTION_PARTY", "fund_id", "FUND", "fund_id"),
    ("TRANSACTION_PARTY", "lead_person_id", "PERSON", "person_id"),
    ("COMMERCIAL_LINK", "supplier_id", "COMPANY", "company_id"), ("COMMERCIAL_LINK", "customer_id", "COMPANY", "company_id"),
    ("CRM_INTERACTION", "our_person_id", "PERSON", "person_id"), ("CRM_INTERACTION", "counterparty_person_id", "PERSON", "person_id"),
    ("PIPELINE", "company_id", "COMPANY", "company_id"), ("PIPELINE", "owner_person_id", "PERSON", "person_id"),
    ("COMPANY_SIGNAL", "company_id", "COMPANY", "company_id"), ("COMPANY_SIGNAL", "intermediary_id", "INTERMEDIARY", "intermediary_id"),
]
POLY = [("ROLE_HISTORY", "org_id", "org_type"), ("TRANSACTION_PARTY", "org_id", "org_type"),
        ("CRM_INTERACTION", "counterparty_org_id", "counterparty_org_type")]
ORGMAP = {"company": ("COMPANY", "company_id", "C"), "sponsor": ("SPONSOR", "sponsor_id", "S"),
          "intermediary": ("INTERMEDIARY", "intermediary_id", "I")}


def pk_fk(get, label):
    """get(table) -> DataFrame."""
    for t in TABLES:
        d = get(t)
        n = int(d.duplicated(subset=PKS[t]).sum()) + int(d[PKS[t]].isna().any(axis=1).sum())
        check(f"[{label}] PK unique+non-null {t}{PKS[t]}", n == 0, f"{len(d)} rows, {n} violations")
    tot = bad = 0
    for c, col, p, pcol in FKS:
        d, pd_ = get(c), get(p)
        s = d[col].dropna()
        miss = int((~s.isin(set(pd_[pcol]))).sum())
        tot += len(s); bad += miss
        check(f"[{label}] FK {c}.{col} -> {p}.{pcol}", miss == 0, f"{len(s)} refs, {miss} dangling")
    for t, col, tcol in POLY:
        d = get(t)
        d = d[d[col].notna()]
        types = set(d[tcol].dropna())
        check(f"[{label}] polymorphic {t}.{tcol} values known", types <= set(ORGMAP), str(sorted(types)))
        for ty, (pt, pcol, pref) in ORGMAP.items():
            sub = d[d[tcol] == ty]
            miss = int((~sub[col].isin(set(get(pt)[pcol]))).sum())
            badpref = int((~sub[col].str.startswith(pref)).sum())
            tot += len(sub); bad += miss
            check(f"[{label}] polymorphic {t}.{col}[{ty}] -> {pt}", miss == 0 and badpref == 0,
                  f"{len(sub)} refs, {miss} dangling, {badpref} wrong prefix")
        check(f"[{label}] polymorphic {t}.{col} has no null org_type", int(d[tcol].isna().sum()) == 0)
    print(f"[{label}] FK TOTAL refs={tot} dangling={bad} integrity={100*(tot-bad)/tot:.2f}%")


def sf_connect():
    cfg = yaml.safe_load((ROOT / "raiconfig.yaml").read_text())
    c = cfg["connections"][cfg.get("default_connection", "pe_demo")]
    tok = Path(c["token_file_path"]).expanduser().read_text().strip()
    return snowflake.connector.connect(account=c["account"], user=c["user"], authenticator="programmatic_access_token",
                                       token=tok, role=c["role"], warehouse=c["warehouse"], database=DB, schema=SCH)


def gid(r):
    return r["key"]["id"] if isinstance(r.get("key"), dict) else r["id"]


def main():
    # ---- CSV level
    print("== CSV: manifest rows, PK, FK")
    for t in TABLES:
        check(f"[csv] rows {t} == manifest", len(dfs[t]) == man[t]["rows"], f"{len(dfs[t])} vs {man[t]['rows']}")
    pk_fk(lambda t: dfs[t], "csv")

    # ---- caps
    print("== Caps")
    mx = max(len(d) for d in dfs.values()); total = sum(len(d) for d in dfs.values())
    check("caps: max rows per table <= 4000", mx <= 4000, str(mx))
    check("caps: total rows <= 16000", total <= 16000, str(total))
    check("17 tables in manifest", len(TABLES) == 17, str(len(TABLES)))

    # ---- Snowflake
    print("== Snowflake")
    con = sf_connect(); cur = con.cursor()
    ident = cur.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_SCHEMA()").fetchone()
    print("connected as", ident)
    check("role RAI_DEMO_PE", ident[0] == "RAI_DEMO_PE", str(ident))
    cur.execute(f"SHOW TABLES IN SCHEMA {DB}.{SCH}")
    cols = [d[0] for d in cur.description]
    shown = {r[cols.index("name")]: r[cols.index("change_tracking")] for r in cur.fetchall()}
    print("tables in schema:", sorted(shown))
    for t in TABLES:
        check(f"[sf] table exists {t}", t in shown)
        n = cur.execute(f"SELECT COUNT(*) FROM {DB}.{SCH}.{t}").fetchone()[0]
        check(f"[sf] rows {t} == manifest", n == man[t]["rows"], f"{n} vs {man[t]['rows']}")
        check(f"[sf] CHANGE_TRACKING ON {t}", shown.get(t) == "ON", str(shown.get(t)))
    extra = sorted(set(shown) - set(TABLES))
    print("non-manifest tables in schema (informational):", extra)
    check("no golden-like table names", not [x for x in shown if re.search(r"golden|expected|oracle|planted|decoy|(^|_)story", x, re.I)], str(extra))
    sfd = {}
    for t in TABLES:
        cur.execute(f"SELECT * FROM {DB}.{SCH}.{t}")
        names = [d[0].lower() for d in cur.description]
        sfd[t] = pd.DataFrame(cur.fetchall(), columns=names).astype(object).where(lambda x: x.notna(), None)
        sfd[t] = sfd[t].map(lambda v: None if v is None else str(v))
        check(f"[sf] column set == csv header {t}", names == list(dfs[t].columns), str(names))
    # SQL-side PK/FK (independent of pandas on Snowflake data)
    for t in TABLES:
        k = ",".join(PKS[t])
        dup = cur.execute(f"SELECT COUNT(*) FROM (SELECT {k} FROM {t} GROUP BY {k} HAVING COUNT(*)>1)").fetchone()[0]
        nul = cur.execute(f"SELECT COUNT(*) FROM {t} WHERE " + " OR ".join(f"{c} IS NULL" for c in PKS[t])).fetchone()[0]
        check(f"[sql] PK unique {t}", dup == 0 and nul == 0, f"dup groups={dup} null={nul}")
    for c, col, p, pcol in FKS:
        m = cur.execute(f"SELECT COUNT(*) FROM {c} x WHERE x.{col} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {p} y WHERE y.{pcol}=x.{col})").fetchone()[0]
        check(f"[sql] FK {c}.{col} -> {p}.{pcol}", m == 0, f"{m} dangling")
    for t, col, tcol in POLY:
        for ty, (pt, pcol, _) in ORGMAP.items():
            m = cur.execute(f"SELECT COUNT(*) FROM {t} x WHERE x.{tcol}='{ty}' AND NOT EXISTS (SELECT 1 FROM {pt} y WHERE y.{pcol}=x.{col})").fetchone()[0]
            check(f"[sql] polymorphic {t}.{col}[{ty}] -> {pt}", m == 0, f"{m} dangling")
    pk_fk(lambda t: sfd[t], "sf-pandas")
    # snowflake content equals CSV content
    for t in TABLES:
        a = dfs[t].astype(object).where(dfs[t].notna(), None)
        a = a.map(lambda v: None if v is None else str(v))
        key = PKS[t]
        ma = a.sort_values(key).reset_index(drop=True); mb = sfd[t].sort_values(key).reset_index(drop=True)
        # normalise numerics/dates textually
        def norm(v):
            if v is None or v != v: return None
            v = str(v)
            if v.lower() in ("true", "false"): return v.lower()
            try: return repr(round(float(v), 6))
            except ValueError: return v
        same = ma.map(norm).equals(mb.map(norm))
        if not same:
            diff = [(c, int((ma[c].map(norm) != mb[c].map(norm)).sum()), ma[c].map(norm)[ma[c].map(norm) != mb[c].map(norm)].head(2).tolist(), mb[c].map(norm)[ma[c].map(norm) != mb[c].map(norm)].head(2).tolist()) for c in ma.columns if not ma[c].map(norm).equals(mb[c].map(norm))]
            print("  diff detail:", diff)
        check(f"[sf] content == csv {t}", same)
    # ---- leaks
    print("== Leak scan")
    pat = re.compile(r"is_planted|planted|golden|decoy|role_key|story_key|ground_truth|expected|cast_key|\bkey_role\b|T_WARM|T_COLD|T_BANKER|NM_B", re.I)
    cur.execute(f"SELECT table_name, column_name FROM {DB}.INFORMATION_SCHEMA.COLUMNS WHERE table_schema='{SCH}'")
    allcols = cur.fetchall()
    bad = [(a, b) for a, b in allcols if pat.search(b) or pat.search(a)]
    print(f"scanned {len(allcols)} column names across {len({a for a,_ in allcols})} tables in Snowflake")
    check("no leaking column names (Snowflake)", not bad, str(bad))
    badc = [(t, c) for t in TABLES for c in dfs[t].columns if pat.search(c)]
    check("no leaking column names (CSV)", not badc, str(badc))
    exp = json.loads((ROOT / "data/golden/expected.json").read_text())
    rolekeys = set(exp["cast"]); 
    def walk(x):
        if isinstance(x, dict):
            if set(x) >= {"key", "id"} and isinstance(x["key"], str): rolekeys.add(x["key"])
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(exp["questions"])
    print(f"golden role keys collected: {len(rolekeys)} (e.g. {sorted(rolekeys)[:8]})")
    hits = []
    for t in TABLES:
        for c in sfd[t].columns:
            vals = set(v for v in sfd[t][c] if v)
            h = vals & rolekeys
            if h: hits.append((t, c, sorted(h)))
    check("no golden role key appears as a cell value (Snowflake, exact match)", not hits, str(hits))
    hits2 = []
    for t in TABLES:
        for c in dfs[t].columns:
            h = set(v for v in dfs[t][c].dropna()) & rolekeys
            if h: hits2.append((t, c, sorted(h)))
    check("no golden role key appears as a cell value (CSV, exact match)", not hits2, str(hits2))
    sub = []
    longkeys = [k for k in rolekeys if len(k) >= 5 and "_" in k]
    for t in TABLES:
        for c in dfs[t].columns:
            for v in dfs[t][c].dropna():
                if any(k in v for k in longkeys): sub.append((t, c, v))
    check("no underscore-style role key (e.g. T_WARM) as substring in any CSV cell", not sub, str(sub[:5]))
    # golden file ids not loaded as a table: ensure tables have no free text columns beyond names
    con.close()

    # ---- oracle vs golden
    print("== Oracle vs golden")
    o = json.loads((ROOT / "data/oracle_output.json").read_text())
    G = exp["questions"]
    # Q-SCORE
    gs = [(r["key"]["id"], r["score"], r["fit"], r["readiness"], r["access"]) for r in G["Q-SCORE"]["tier_a_ranked"]]
    os_ = [(r["company_id"], r["score"], r["fit"], r["readiness"], r["access"]) for r in o["Q-SCORE"]["answer"]["tier_a"]]
    check("Q-SCORE tier A ids/order/score/fit/readiness/access", gs == os_, f"golden={gs} oracle={os_}")
    allsc = {r["company_id"]: r for r in o["Q-SCORE"]["all_scored"]}
    gb = G["Q-SCORE"]["tier_b_reference"][0]
    check("Q-SCORE NM_B score 65 tier B", allsc[gb["key"]["id"]]["score"] == gb["score"] and allsc[gb["key"]["id"]]["tier"] == "B")
    ds = G["Q-SCORE"]["d_short_reference"]
    check("Q-SCORE D_SHORT score 30 tier C", allsc[ds["key"]["id"]]["score"] == ds["score"] and allsc[ds["key"]["id"]]["tier"] == ds["tier"])
    # components
    gcomp = {r["key"]["id"]: r["components"] for r in G["Q-SCORE"]["tier_a_ranked"]}
    ocomp = {}
    for r in o["Q-SCORE"]["all_scored"]:
        if r["company_id"] in gcomp:
            ocomp[r["company_id"]] = {c["component"]: c["points"] for c in r["components"] if c["points"]}
    check("Q-SCORE component points per Tier A company", all({k: v for k, v in gcomp[i].items() if v} == ocomp[i] for i in gcomp),
          str({i: (gcomp[i], ocomp[i]) for i in gcomp if {k: v for k, v in gcomp[i].items() if v} != ocomp[i]}))
    mn = {(r["key"]["id"] if isinstance(r.get("key"), dict) else r["id"]) for r in G["Q-SCORE"]["must_not_contain"]}
    check("Q-SCORE must_not_contain absent from tier A", not (mn & {r[0] for r in os_}))
    check("Q-SCORE not_in_crm set", {gid(r) for r in G["Q-SCORE"]["not_in_crm"]} == set(o["Q-SCORE"]["answer"]["not_in_crm_tier_a"]) or
          {gid(r) for r in G["Q-SCORE"]["not_in_crm"]} == {i for i in [r["company_id"] for r in o["Q-SCORE"]["answer"]["tier_a"]] if allsc[i]["not_in_crm"]},
          str(o["Q-SCORE"]["answer"]["not_in_crm_tier_a"]))
    # Q-PATH
    orows = {(r["target_id"], r["kind"]): r for r in o["Q-PATH"]["answer"]["rows"]}
    for r in G["Q-PATH"]["rows"]:
        k = (r["target"]["id"], r["kind"]); orow = orows.get(k)
        if orow is None:
            check(f"Q-PATH row {k}", False, "missing in oracle"); continue
        if r.get("cold"):
            ok = orow["decision_maker_id"] == r["decision_maker"]["id"] and orow["best_path"] is None and not orow["within_3_hops"] and (orow["hops"] is None or orow["hops"] >= 4) and not orow["alternates"]
            check(f"Q-PATH {r['target']['name']} {r['kind']} cold (no path within 3 hops, seed distance >=4)", ok, f"oracle hops={orow['hops']} path={orow['best_path'] and orow['best_path']['person_ids']} msg={orow['message']}")
            continue
        gpath = [p["id"] for p in r.get("best_path") or []]
        opath = orow["best_path"]["person_ids"] if orow.get("best_path") else []
        ok = orow["decision_maker_id"] == r["decision_maker"]["id"] and orow["hops"] == r["hops"] and gpath == opath
        ok &= abs(orow["path_strength"] - r["path_strength"]) < 5e-4
        ohs = [h["strength"] for h in orow["best_path"]["hop_detail"]]
        ok &= all(abs(x - y) < 5e-4 for x, y in zip(ohs, r["hop_strengths"])) and len(ohs) == len(r["hop_strengths"])
        check(f"Q-PATH {r['target']['name']} {r['kind']} dm/hops/path/strengths", ok, f"golden hops={r['hops']} path={gpath} hs={r['hop_strengths']} ps={r['path_strength']} | oracle hops={orow['hops']} path={opath} hs={ohs} ps={orow['path_strength']}")
        galt = [([p["id"] for p in a["path"]], a["path_strength"]) for a in r.get("alternates", [])]
        oalt = [(a["person_ids"], a["strength"]) for a in orow["alternates"]]
        check(f"Q-PATH {r['target']['name']} {r['kind']} alternates (path, strength)", len(galt) == len(oalt) and all(g[0] == q[0] and abs(g[1] - q[1]) < 5e-4 for g, q in zip(galt, oalt)), f"golden={galt} oracle={oalt}")
    ci = G["Q-PATH"]["closest_intermediary"]
    ot = {t["target_id"]: t for t in o["Q-PATH"]["answer"]["targets"]}[ci["target"]["id"]]
    check("Q-PATH closest intermediary (cold target) == HL", ot["closest_intermediary"]["intermediary_id"] == ci["intermediary"]["id"])
    check("Q-PATH only cold target has closest_intermediary", [t["target"] for t in o["Q-PATH"]["answer"]["targets"] if t["closest_intermediary"]] == [ci["target"]["name"]])
    # Q-FLOW
    fl = G["Q-FLOW"]; ofl = o["Q-FLOW"]["answer"]
    gr = [(r["rank"], r["key"]["id"]) for r in fl["betweenness_rank_intermediaries"]]
    orr = [(r["rank"], r["intermediary_id"]) for r in ofl["top5"][:len(gr)]]
    check("Q-FLOW betweenness rank 1..2 (CEDAR, HL)", gr == orr, f"{gr} vs {orr}")
    check("Q-FLOW coverage gaps set == {HL}", {gid(g) for g in fl["coverage_gaps"]} == {g["intermediary_id"] for g in ofl["coverage_gaps"]})
    tp = {r["intermediary_id"]: r["touchpoints_24m"] for r in o["Q-FLOW"]["intermediary_ranking"]}
    check("Q-FLOW touchpoints CEDAR=14, HL=1, BIGBANK=9", all(tp.get(fl_id) == v for fl_id, v in [("I210", 14), ("I139", 1), ("I736", 9)]) and tp["I210"] == fl["touchpoints_24m"]["CEDAR"] and tp["I139"] == fl["touchpoints_24m"]["HL"] and tp["I736"] == fl["touchpoints_24m"]["BIGBANK"], str({k: tp.get(k) for k in ["I210", "I139", "I736"]}))
    bb = next(r for r in o["Q-FLOW"]["intermediary_ranking"] if r["intermediary_id"] == "I736")
    check("Q-FLOW BIGBANK rank >= 11", bb["rank"] >= fl["bigbank_min_rank"], f"rank {bb['rank']}")
    check("Q-FLOW BIGBANK deals_5y == 40", bb["deals_5y_all_sectors"] == fl["bigbank_total_deals_5y"], str(bb["deals_5y_all_sectors"]))
    check("Q-FLOW BIGBANK not in top 5", "I736" not in [r["intermediary_id"] for r in ofl["top5"]])
    d = o["Q-FLOW"]["diagnostics"]
    check("Q-FLOW n_intermediaries 31-40, top decile 4, Q1=1", 31 <= d["n_intermediaries_in_graph"] <= 40 and d["top_decile_size"] == 4 and d["q1_touchpoints"] == fl["q1_touchpoints"])
    hl = next(r for r in o["Q-FLOW"]["intermediary_ranking"] if r["intermediary_id"] == "I139")
    check("Q-FLOW HL deals in window == 9", hl["deals_in_window_thesis"] == fl["hl_deals_in_window"], str(hl["deals_in_window_thesis"]))
    # Q-CONFLICT
    gc = G["Q-CONFLICT"]; oc = o["Q-CONFLICT"]["answer"]
    check("Q-CONFLICT subject", oc["subject"]["company_id"] == gc["subject"]["id"])
    ge = [(r["key"]["id"], r["distance"], r["kind"].split(" (")[0]) for r in gc["exposure_rows"]]
    oe = [(r["company_id"], r["commercial_distance"], r["kind"].split(" (")[0]) for r in oc["exposures"]]
    check("Q-CONFLICT exposure rows (id, distance, kind) in order", ge == oe, f"{ge} vs {oe}")
    check("Q-CONFLICT via ids", [r.get("via", {}).get("id") for r in gc["exposure_rows"]] == [None, "C8773"])
    exc = {r["company_id"] for r in oc["exposures"]}
    check("Q-CONFLICT must_not_contain (REDFERN, BRIGHT) absent", not ({gid(r) for r in gc["must_not_contain"]} & exc))
    gcn = gc["concentration"]["areas"]["Specialty Distribution"]
    oca = next(r for r in oc["concentration"] if r["thesis_area"] == "Specialty Distribution")
    check("Q-CONFLICT Specialty Distribution before/after %/breach", abs(oca["before_pct"] - gcn["before_pct"]) < 0.01 and abs(oca["with_subject_pct"] - gcn["after_pct"]) < 0.01 and oca["breach"] == gcn["breach"] and oca["before_musd"] == gcn["before_musd"] and oca["with_subject_musd"] == gcn["after_musd"], f"{oca}")
    check("Q-CONFLICT headroom 35 / over_by 20", oca["headroom_musd"] == gc["concentration"]["headroom_musd"] and oca["over_by_musd"] == gc["concentration"]["over_by_musd"])
    check("Q-CONFLICT only breach = Specialty Distribution", oc["breaches"] == ["Specialty Distribution"] and [a for a, v in gc["concentration"]["areas"].items() if v.get("breach")] == ["Specialty Distribution"])
    gh = {r["key"]["id"] for r in gc["fund_iv_holdings"]}
    oh = {r["company_id"] for r in o["Q-CONFLICT"]["diagnostics"]["fund_iv"]["holdings"]}
    check("Q-CONFLICT Fund IV holdings set", gh == oh)
    # FINALE
    gf = G["FINALE"]; of = o["FINALE"]["answer"]
    g1 = [(r["rank"], gid(r), r["score"]) for r in gf["tier_a_ranked"]]
    o1 = [(r["rank"], r["company_id"], r["score"]) for r in of["tier_a"]]
    check("FINALE Tier A rank/id/score", g1 == o1, f"{g1} vs {o1}")
    check("FINALE warm path set", {gid(r) for r in gf["warm_path_set"]} == {r["company_id"] for r in of["tier_a"] if r["A_WARM_PATH"] > 0})
    gnm = gf["nm_b_path"]; onm = next(r for r in of["tier_a"] if r["company_id"] == "C4685")["warm_path"]
    check("FINALE NM_B path persons + strength", [p["id"] for p in gnm["path"]] == onm["person_ids"] and abs(gnm["path_strength"] - onm["strength"]) < 1e-9, str(onm["person_ids"]))
    gw = next(r for r in G["Q-PATH"]["rows"] if r["target"]["id"] == "C6334")
    check("FINALE T_WARM warm path = Q-PATH path", next(r for r in of["tier_a"] if r["company_id"] == "C6334")["warm_path"]["person_ids"] == [p["id"] for p in gw["best_path"]])
    # conflict semantics
    gconf = {r["key"]["id"] if isinstance(r["key"], dict) and "id" in r["key"] else r["key"]["key"]["id"] for r in gf["conflicts"]}
    oflag = {r["company_id"]: r for r in of["flagged"]}
    ooff = {r["company_id"] for r in of["flagged_off_tier_a"]}
    check("FINALE golden conflicts == oracle flagged_off_tier_a (Tier A semantics)", gconf == ooff, f"{gconf} vs {ooff}")
    check("FINALE golden conflict CONF with PINE direction", all(r["with"]["id"] == "C2514" for r in gf["conflicts"]) and "Pinewick" in oflag["C8200"]["evidence"][0])
    extra_flag = set(oflag) - gconf
    allsc_t = {i: allsc[i]["tier"] for i in extra_flag}
    check("FINALE extra flagged (superset) are all Tier C and outside Tier A/final Tier A", all(t == "C" for t in allsc_t.values()) and not (extra_flag & {r["company_id"] for r in of["tier_a"]}), f"extra={ {i: (oflag[i]['name'], oflag[i]['score'], allsc_t[i]) for i in extra_flag} }")
    check("FINALE CONF absent from Tier A rows", "C8200" not in {r["company_id"] for r in of["tier_a"]})
    check("FINALE guards F1/F2 hold", o["FINALE"]["guards"]["guard_F1"]["holds"] and o["FINALE"]["guards"]["guard_F2"]["holds"])
    print("FAILS:", FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
