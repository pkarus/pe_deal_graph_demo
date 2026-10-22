#!/usr/bin/env python
"""R19c data realism and integrity audit (pandas only, no Snowflake, no engine).

Usage:
    .venv/bin/python scripts/audit_realism.py                    # audits data/csv_noise
    .venv/bin/python scripts/audit_realism.py --dir data/csv     # signal layer spot-check

Read-only: never writes data. Prints a sectioned report; lines tagged [FLAG] are candidate findings.
Reference ranges come from research/domain_brief.md (section 2) and PROMPT.md section 8.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AS_OF = pd.Timestamp("2026-10-01")
TARGETS = {"SECTOR": 70, "REGION": 60, "SPONSOR": 40, "FUND": 80, "INTERMEDIARY": 50, "COMPANY": 1200,
           "PERSON": 2500, "ROLE_HISTORY": 3500, "OWNERSHIP": 600, "TRANSACTION": 500,
           "TRANSACTION_PARTY": 1200, "COMMERCIAL_LINK": 2500, "CRM_INTERACTION": 1500, "PIPELINE": 200,
           "COMPANY_SIGNAL": 1200}
# Brief section 2: margin range (lo, hi, median) per thesis level-2 sector.
MARGIN_BRIEF = {"Healthcare Services": (10, 20, 14), "Tech-Enabled Business Services": (15, 25, 18),
                "Testing, Inspection & Certification": (14, 22, 17), "Specialty Distribution": (6, 13, 9)}
# GF Data 2025 medians by TEV band (brief section 2).
EV_BANDS = [(10, 25, 5.9), (25, 50, 6.6), (50, 100, 8.7), (100, 250, 10.0), (250, 500, 9.8)]
PROTECTED = re.compile(r"(^|_)(age|gender|sex|ethnic\w*|race|dob|birth\w*|nationality|religion|marital|"
                       r"pronoun\w*|salutation|honorific|disab\w*|veteran)($|_)", re.I)

FLAGS: list[str] = []


def flag(msg: str):
    FLAGS.append(msg)
    print(f"  [FLAG] {msg}")


def head(t: str):
    print(f"\n=== {t} ===")


def q(s: pd.Series, ps=(0.05, 0.25, 0.5, 0.75, 0.95)) -> str:
    s = s.dropna()
    if s.empty:
        return "n=0"
    return f"n={len(s)} " + " ".join(f"p{int(p*100)}={s.quantile(p):.2f}" for p in ps) + \
        f" min={s.min():.2f} max={s.max():.2f}"


def load(d: Path) -> dict[str, pd.DataFrame]:
    t = {}
    for f in sorted(d.glob("*.csv")):
        t[f.stem] = pd.read_csv(f, dtype=str, keep_default_na=False, na_values=[""])
    num = {"COMPANY": ["revenue_musd", "ebitda_musd", "employees", "founded_year"],
           "FUND": ["vintage_year", "size_musd", "ebitda_min_musd", "ebitda_max_musd", "area_guideline_pct"],
           "SPONSOR": ["aum_musd"], "OWNERSHIP": ["equity_invested_musd"],
           "TRANSACTION": ["ev_musd", "ev_ebitda"], "COMMERCIAL_LINK": ["since_year"],
           "PIPELINE": ["est_equity_check_musd"], "COMPANY_SIGNAL": ["magnitude_musd"],
           "SECTOR": ["level"], "REGION": ["level"], "FUND_FOCUS": ["margin_benchmark_pct"]}
    for tb, cols in num.items():
        for c in cols:
            t[tb][c] = pd.to_numeric(t[tb][c])
    dates = {"ROLE_HISTORY": ["start_date", "end_date"], "OWNERSHIP": ["start_date", "end_date"],
             "TRANSACTION": ["close_date"], "CRM_INTERACTION": ["interaction_date"],
             "PIPELINE": ["added_date"], "COMPANY_SIGNAL": ["signal_date", "event_date"]}
    for tb, cols in dates.items():
        for c in cols:
            t[tb][c] = pd.to_datetime(t[tb][c])
    return t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/csv_noise")
    ap.add_argument("--signal-dir", default="data/csv",
                    help="signal-layer CSVs; rows whose PK appears there are tagged 'signal', others 'noise'")
    a = ap.parse_args(argv)
    d = (ROOT / a.dir).resolve()
    T = load(d)
    co, sec, reg, sp, fu, ff = (T[k] for k in ["COMPANY", "SECTOR", "REGION", "SPONSOR", "FUND", "FUND_FOCUS"])
    im, pe, rh, ow, tx, tp = (T[k] for k in ["INTERMEDIARY", "PERSON", "ROLE_HISTORY", "OWNERSHIP",
                                             "TRANSACTION", "TRANSACTION_PARTY"])
    cl, crm, pl, sg, site = (T[k] for k in ["COMMERCIAL_LINK", "CRM_INTERACTION", "PIPELINE",
                                            "COMPANY_SIGNAL", "COMPANY_SITE"])
    print(f"R19c realism audit of {d.relative_to(ROOT)}  (AS_OF {AS_OF.date()})")

    # ------------------------------------------------------------------ 1. sizes
    head("1. Row counts vs PROMPT 8.1 targets and caps")
    total = 0
    for k, df in T.items():
        total += len(df)
        tg = TARGETS.get(k)
        pct = f"{100*len(df)/tg:.0f}% of {tg}" if tg else ""
        print(f"  {k:18s} {len(df):5d}  {pct}")
        if len(df) > 4000:
            flag(f"{k} over the 4,000 per-table cap")
        if tg and len(df) < 0.6 * tg:
            flag(f"{k} has {len(df)} rows, under 60% of the {tg} target")
    print(f"  TOTAL {total}")
    if total > 16000:
        flag("total over 16,000 cap")
    man = json.loads((d / "MANIFEST.json").read_text())
    mrows = sum(v["rows"] for v in man["tables"].values())
    print(f"  MANIFEST rows {mrows} (match={mrows == total})")

    # ------------------------------------------------------------------ 2. keys
    head("2. Primary keys, duplicates, referential integrity")
    pks = {"SECTOR": ["sector_id"], "REGION": ["region_id"], "SPONSOR": ["sponsor_id"], "FUND": ["fund_id"],
           "FUND_FOCUS": ["fund_id", "sector_id"], "INTERMEDIARY": ["intermediary_id"],
           "COMPANY": ["company_id"], "COMPANY_SITE": ["company_id", "region_id"], "PERSON": ["person_id"],
           "ROLE_HISTORY": ["role_id"], "OWNERSHIP": ["ownership_id"], "TRANSACTION": ["txn_id"],
           "TRANSACTION_PARTY": ["party_id"], "COMMERCIAL_LINK": ["link_id"],
           "CRM_INTERACTION": ["interaction_id"], "PIPELINE": ["company_id"], "COMPANY_SIGNAL": ["signal_id"]}
    for k, cols in pks.items():
        n = T[k].duplicated(cols).sum()
        nulls = T[k][cols].isna().any(axis=1).sum()
        if n or nulls:
            flag(f"{k} PK {cols}: {n} duplicates, {nulls} nulls")
    print("  PK uniqueness checked on 17 tables")
    # natural-key duplicates
    for k, col in [("COMPANY", "name"), ("SPONSOR", "name"), ("FUND", "name"), ("INTERMEDIARY", "name"),
                   ("SECTOR", "name")]:
        dup = T[k][T[k].duplicated(col, keep=False)]
        print(f"  duplicate {k}.{col}: {dup[col].nunique()} values")
        if len(dup):
            flag(f"duplicate {k}.{col}: {sorted(dup[col].unique())[:8]}")
    dn = pe[pe.duplicated("full_name", keep=False)]
    print(f"  duplicate PERSON.full_name: {dn.full_name.nunique()} names over {len(dn)} rows "
          f"({100*len(dn)/len(pe):.1f}% of people)")
    bad_full = (pe.first_name + " " + pe.last_name != pe.full_name).sum()
    print(f"  full_name != first + ' ' + last: {bad_full}")
    # name collisions across entity types (company vs intermediary vs sponsor)
    allnames = pd.concat([co.name.rename("n").to_frame().assign(t="company"),
                          sp.name.rename("n").to_frame().assign(t="sponsor"),
                          im.name.rename("n").to_frame().assign(t="intermediary")])
    x = allnames.groupby("n").t.nunique()
    print(f"  names reused across org types: {list(x[x > 1].index)[:10]}")
    tri = allnames[allnames.n.str.contains(r"(?:(\w)\1\1)", regex=True)]
    print(f"  malformed names (same letter 3x): {tri.n.tolist()}")
    if len(tri):
        flag(f"{len(tri)} malformed org names with a tripled letter: {tri.n.tolist()}")
    # stems shared between hero-visible names and other orgs (confusability in live name lookups)
    gold = ROOT / "data/golden/expected.json"
    if gold.exists():
        cast = json.loads(gold.read_text())["cast"]
        cast_names = {v["name"] for v in cast.values() if v["id"][0] in "CSI"}
        allnames["stem"] = allnames.n.str.split().str[0]
        cstem = {n.split()[0]: n for n in cast_names}
        reuse = allnames[allnames.stem.isin(cstem) & ~allnames.n.isin(cast_names)]
        print(f"  non-cast orgs sharing the first word of a cast name: {len(reuse)} "
              f"e.g. {[(cstem[s_], n_) for s_, n_ in zip(reuse.stem, reuse.n)][:12]}")
        sp2 = sp.assign(stem=sp.name.str.split().str[0])
        twin = sp2[sp2.duplicated("stem", keep=False)]
        print(f"  sponsors sharing a first word: {twin.name.tolist()}")
        if len(twin):
            flag(f"near-duplicate sponsor names {twin.name.tolist()}")
    dupl = cl.duplicated(["supplier_id", "customer_id"]).sum()
    selfl = (cl.supplier_id == cl.customer_id).sum()
    recip = cl.merge(cl, left_on=["supplier_id", "customer_id"], right_on=["customer_id", "supplier_id"])
    print(f"  COMMERCIAL_LINK dup pairs={dupl} self-links={selfl} reciprocal pairs={len(recip)//2}")
    if dupl or selfl:
        flag(f"COMMERCIAL_LINK dup pairs={dupl} self-links={selfl}")
    rd = rh.duplicated(["person_id", "org_id", "role_type", "start_date"]).sum()
    print(f"  ROLE_HISTORY duplicate (person, org, role_type, start): {rd}")
    od = ow.duplicated(["company_id", "fund_id", "start_date"]).sum()
    print(f"  OWNERSHIP duplicate (company, fund, start): {od}")
    xd = crm.duplicated(["our_person_id", "counterparty_person_id", "counterparty_org_id",
                         "interaction_date", "channel"]).sum()
    print(f"  CRM duplicate (our, cp person, cp org, date, channel): {xd}")
    td = tx.duplicated(["target_id", "close_date"]).sum()
    print(f"  TRANSACTION duplicate (target, close_date): {td}")
    tpd = tp.duplicated(["txn_id", "org_id", "party_role"]).sum()
    print(f"  TRANSACTION_PARTY duplicate (txn, org, role): {tpd}")
    for n, v in [("ROLE_HISTORY", rd), ("OWNERSHIP", od), ("CRM_INTERACTION", xd), ("TRANSACTION", td),
                 ("TRANSACTION_PARTY", tpd)]:
        if v:
            flag(f"{n} has {v} duplicate natural-key rows")

    ids = {"company": set(co.company_id), "sponsor": set(sp.sponsor_id), "intermediary": set(im.intermediary_id)}
    fk = [("SECTOR.parent_id", sec.parent_id.dropna(), set(sec.sector_id)),
          ("REGION.parent_id", reg.parent_id.dropna(), set(reg.region_id)),
          ("SPONSOR.hq_region_id", sp.hq_region_id, set(reg.region_id)),
          ("FUND.sponsor_id", fu.sponsor_id, ids["sponsor"]),
          ("FUND_FOCUS.fund_id", ff.fund_id, set(fu.fund_id)),
          ("FUND_FOCUS.sector_id", ff.sector_id, set(sec.sector_id)),
          ("INTERMEDIARY.hq_region_id", im.hq_region_id, set(reg.region_id)),
          ("COMPANY.sector_id", co.sector_id, set(sec.sector_id)),
          ("COMPANY.hq_region_id", co.hq_region_id, set(reg.region_id)),
          ("COMPANY_SITE.company_id", site.company_id, ids["company"]),
          ("COMPANY_SITE.region_id", site.region_id, set(reg.region_id)),
          ("ROLE_HISTORY.person_id", rh.person_id, set(pe.person_id)),
          ("OWNERSHIP.company_id", ow.company_id, ids["company"]),
          ("OWNERSHIP.fund_id", ow.fund_id, set(fu.fund_id)),
          ("TRANSACTION.target_id", tx.target_id, ids["company"]),
          ("TRANSACTION_PARTY.txn_id", tp.txn_id, set(tx.txn_id)),
          ("TRANSACTION_PARTY.fund_id", tp.fund_id.dropna(), set(fu.fund_id)),
          ("TRANSACTION_PARTY.lead_person_id", tp.lead_person_id.dropna(), set(pe.person_id)),
          ("COMMERCIAL_LINK.supplier_id", cl.supplier_id, ids["company"]),
          ("COMMERCIAL_LINK.customer_id", cl.customer_id, ids["company"]),
          ("CRM.our_person_id", crm.our_person_id, set(pe.person_id)),
          ("CRM.counterparty_person_id", crm.counterparty_person_id.dropna(), set(pe.person_id)),
          ("PIPELINE.company_id", pl.company_id, ids["company"]),
          ("PIPELINE.owner_person_id", pl.owner_person_id, set(pe.person_id)),
          ("SIGNAL.company_id", sg.company_id, ids["company"]),
          ("SIGNAL.intermediary_id", sg.intermediary_id.dropna(), ids["intermediary"])]
    for df, idc, tc in [(rh, "org_id", "org_type"), (tp, "org_id", "org_type"),
                        (crm.dropna(subset=["counterparty_org_id"]), "counterparty_org_id", "counterparty_org_type")]:
        bad = sum(1 for i, t_ in zip(df[idc], df[tc]) if i not in ids.get(t_, set()))
        fk.append((f"poly {tc}->{idc}", pd.Series([0] * bad), set()))
    nbad = 0
    for name, s, tgt in fk:
        b = (~s.isin(tgt)).sum() if len(tgt) else len(s)
        nbad += b
        if b:
            flag(f"FK {name}: {b} orphans")
    print(f"  {len(fk)} FK checks, {nbad} orphans total")
    # company sector level 3, hq is state/province
    lv = co.sector_id.map(sec.set_index("sector_id").level)
    print(f"  companies not on a level-3 sector: {(lv != 3).sum()}")
    rt = co.hq_region_id.map(reg.set_index("region_id").region_type)
    print(f"  company HQ not a state/province: {(~rt.isin(['state', 'province'])).sum()}")
    hq_in_site = co.merge(site, left_on=["company_id", "hq_region_id"], right_on=["company_id", "region_id"])
    print(f"  companies whose HQ is missing from COMPANY_SITE: {len(co) - len(hq_in_site)}")
    # TP integrity: each txn has exactly one buyer; add-on buyer is a company
    nb = tp[tp.party_role == "buyer"].groupby("txn_id").size().reindex(tx.txn_id, fill_value=0)
    print(f"  txns by buyer count: {nb.value_counts().sort_index().to_dict()}")
    txr = tx.set_index("txn_id")
    b = tp[tp.party_role == "buyer"].copy()
    b["deal_role"] = b.txn_id.map(txr.deal_role)
    print("  buyer org_type by deal_role:", b.groupby(["deal_role", "org_type"]).size().to_dict())
    noaddbuyer = b[(b.deal_role == "add_on") & (b.org_type != "company")]
    if len(noaddbuyer):
        flag(f"{len(noaddbuyer)} add-ons whose buyer is not a platform company")
    spb = tp[tp.org_type == "sponsor"]
    print(f"  sponsor party rows missing fund_id: {spb.fund_id.isna().sum()}")
    mism = spb.dropna(subset=["fund_id"])
    mism = mism[mism.fund_id.map(fu.set_index("fund_id").sponsor_id) != mism.org_id]
    print(f"  sponsor party whose fund belongs to a different sponsor: {len(mism)}")
    if len(mism):
        flag(f"{len(mism)} TRANSACTION_PARTY sponsor rows with fund of another sponsor")

    # ------------------------------------------------------------------ 3. distributions
    head("3a. EBITDA margin by thesis sector vs brief")
    sp_ = sec.set_index("sector_id")
    l2 = co.sector_id.map(sp_.parent_id)
    co["l2"] = l2.map(sp_.name)
    co["l1"] = l2.map(sp_.parent_id).map(sp_.name)
    co["l3"] = co.sector_id.map(sp_.name)
    co["margin"] = 100 * co.ebitda_musd / co.revenue_musd
    # thesis area: Healthcare Services is a level-1 node; the other three are level-2 nodes
    co["area"] = np.where(co.l1 == "Healthcare Services", "Healthcare Services", co.l2)
    co["l2"] = co["area"]
    for s_, (lo, hi, med) in MARGIN_BRIEF.items():
        m = co[co.area == s_].margin
        inr = ((m >= lo) & (m <= hi)).mean() * 100
        print(f"  {s_:38s} n={len(m):4d} median={m.median():5.1f} (brief {med}) in [{lo},{hi}]={inr:5.1f}% "
              f"p5={m.quantile(.05):.1f} p95={m.quantile(.95):.1f}")
        if abs(m.median() - med) > 3 or inr < 60:
            flag(f"margin {s_} median {m.median():.1f} vs brief {med}, {inr:.0f}% in range")
    oth = co[~co.l2.isin(MARGIN_BRIEF)]
    print("  non-thesis level-2 medians:",
          {k: round(v, 1) for k, v in oth.groupby("l2").margin.median().sort_values().items()})
    print(f"  all companies margin: {q(co.margin)}")
    neg = co[co.margin <= 0]
    print(f"  margin <= 0: {len(neg)}; > 40%: {(co.margin > 40).sum()}")
    if (co.margin > 40).sum() > 0:
        print("   >40%:", co[co.margin > 40][["name", "l3", "revenue_musd", "ebitda_musd"]].head(8).to_dict("records"))
    co["rev_per_emp_k"] = 1000 * co.revenue_musd / co.employees
    print(f"  revenue per employee ($k): {q(co.rev_per_emp_k)}")
    hi_rpe = co[(co.rev_per_emp_k > 1500) | (co.rev_per_emp_k < 40)]
    print(f"  rev/employee outside $40k-$1.5M: {len(hi_rpe)}")
    if len(hi_rpe):
        print("   e.g.", hi_rpe[["name", "l2", "revenue_musd", "employees"]].head(6).to_dict("records"))
    print("  rev/employee median by l2:",
          {k: round(v) for k, v in co.groupby("l2").rev_per_emp_k.median().sort_values().items()})
    print(f"  revenue: {q(co.revenue_musd)}")
    print(f"  EBITDA: {q(co.ebitda_musd)}")
    print(f"  founded_year: {q(co.founded_year)}")
    thesis_band = co[co.l2.isin(MARGIN_BRIEF) & co.ebitda_musd.between(5, 40)]
    print(f"  thesis sectors AND EBITDA 5-40: {len(thesis_band)} = {100*len(thesis_band)/len(co):.1f}% "
          f"(spec about 15%)")
    print(f"  is_public: {co.is_public.value_counts().to_dict()}")

    head("3b. EV/EBITDA by TEV band vs GF Data 2025")
    tx["band"] = pd.cut(tx.ev_musd, [0, 10, 25, 50, 100, 250, 500, 1e9],
                        labels=["<10", "10-25", "25-50", "50-100", "100-250", "250-500", "500+"])
    g = tx.groupby("band", observed=False).ev_ebitda.agg(["size", "median", "min", "max"])
    print(g.round(2).to_string())
    for lo, hi, gf in EV_BANDS:
        m = tx[(tx.ev_musd >= lo) & (tx.ev_musd < hi)].ev_ebitda.median()
        if pd.notna(m) and abs(m - gf) > 1.5:
            flag(f"EV band {lo}-{hi} median {m:.2f}x vs GF Data {gf}x")
    print(f"  ev_ebitda overall: {q(tx.ev_ebitda)}")
    out = tx[(tx.ev_ebitda < 4) | (tx.ev_ebitda > 14)]
    print(f"  ev_ebitda outside 4-14x: {len(out)}")
    tx["tl2"] = tx.target_id.map(co.set_index("company_id").l2)
    tx["timplied_ebitda"] = tx.ev_musd / tx.ev_ebitda
    tx["tgt_ebitda_now"] = tx.target_id.map(co.set_index("company_id").ebitda_musd)
    for s_ in MARGIN_BRIEF:
        z = tx[(tx.tl2 == s_)]
        print(f"  {s_:38s} EV50-100 med={z[z.ev_musd.between(50, 100)].ev_ebitda.median():.2f} "
              f"EV100-400 med={z[z.ev_musd.between(100, 400)].ev_ebitda.median():.2f} n={len(z)}")
    print(f"  ev_musd: {q(tx.ev_musd)}")
    print(f"  deal_role: {tx.deal_role.value_counts().to_dict()}  addon share="
          f"{100*(tx.deal_role=='add_on').mean():.1f}% (brief EST 65-75)")
    print(f"  seller_type: {tx.seller_type.value_counts().to_dict()}")
    print(f"  structure: {tx.structure.value_counts().to_dict()}")
    print("  platform deals by seller_type:", tx[tx.deal_role == "platform"].seller_type.value_counts().to_dict())
    print(f"  close year: {tx.close_date.dt.year.value_counts().sort_index().to_dict()}")
    plat = tx[tx.deal_role == "platform"]
    adds = tx[tx.deal_role == "add_on"]
    print(f"  platform EV: {q(plat.ev_musd)}")
    print(f"  add-on EV: {q(adds.ev_musd)}")
    print(f"  add-on EV/EBITDA median {adds.ev_ebitda.median():.2f} vs platform {plat.ev_ebitda.median():.2f}")
    # implied EBITDA at deal vs EBITDA now: growth consistent?
    tx["ratio_now_vs_deal"] = tx.tgt_ebitda_now / tx.timplied_ebitda
    print(f"  target EBITDA now / implied EBITDA at close: {q(tx.ratio_now_vs_deal)}")
    wild = tx[(tx.ratio_now_vs_deal > 5) | (tx.ratio_now_vs_deal < 0.3)]
    print(f"  ratio outside 0.3-5x: {len(wild)}")

    head("3c. Hold periods (OWNERSHIP)")
    ow["years"] = ((ow.end_date.fillna(AS_OF) - ow.start_date).dt.days / 365.25)
    ex = ow[ow.end_date.notna()]
    cur = ow[ow.end_date.isna()]
    print(f"  exited holds: {q(ex.years)}  (brief median about 6, p5-p95 3-10)")
    print(f"  current holds (age so far): {q(cur.years)}")
    if len(ex) and abs(ex.years.median() - 6) > 1.5:
        flag(f"exited hold median {ex.years.median():.2f} vs brief about 6")
    print(f"  exited holds < 2 yrs: {(ex.years < 2).sum()}, > 10 yrs: {(ex.years > 10).sum()}")
    print(f"  current holds > 10 yrs: {(cur.years > 10).sum()}")
    print(f"  stake_type: {ow.stake_type.value_counts().to_dict()}")
    print(f"  current vs exited: {len(cur)} / {len(ex)}")
    ow["l2"] = ow.company_id.map(co.set_index("company_id").l2)
    print("  exited hold median by thesis l2:",
          {k: round(v, 2) for k, v in ex.assign(l2=ow.l2).groupby("l2").years.median().items()
           if k in MARGIN_BRIEF})

    head("3d. Funds: size, vintage, life, deployment, concentration")
    print(f"  size_musd: {q(fu.size_musd)}  (brief LMM EST $250M-1.5B)")
    print(f"  funds < $150M: {(fu.size_musd < 150).sum()}, > $2B: {(fu.size_musd > 2000).sum()}")
    print(f"  vintage: {fu.vintage_year.value_counts().sort_index().to_dict()}")
    if fu.vintage_year.min() < 2010 or fu.vintage_year.max() > 2025:
        flag(f"vintages outside 2010-2025: {fu.vintage_year.min()}-{fu.vintage_year.max()}")
    fsz = fu.set_index("fund_id")
    ow["vintage"] = ow.fund_id.map(fsz.vintage_year)
    ow["size"] = ow.fund_id.map(fsz.size_musd)
    ow["start_yr"] = ow.start_date.dt.year
    pre = ow[ow.start_yr < ow.vintage - 1]
    print(f"  ownership starts more than 1 year before fund vintage: {len(pre)}")
    if len(pre):
        flag(f"{len(pre)} OWNERSHIP rows start before vintage-1 (fund did not exist)")
        print(pre[["ownership_id", "company_id", "fund_id", "start_date", "vintage"]].head(8).to_string())
    late = ow[ow.start_yr > ow.vintage + 6]
    print(f"  new holdings more than 6 years after vintage (past investment period): {len(late)}")
    if len(late):
        print(late[["ownership_id", "fund_id", "start_date", "vintage", "stake_type"]].head(8).to_string())
    old = cur[cur.fund_id.map(fsz.vintage_year) <= AS_OF.year - 13]
    print(f"  current holdings in funds aged 13+ years (past 10+2 extensions): {len(old)}")
    if len(old):
        flag(f"{len(old)} current holdings in funds older than 12 years "
             f"(e.g. {old[['company_id','fund_id']].head(3).values.tolist()})")
    ow["pct_of_fund"] = 100 * ow.equity_invested_musd / ow["size"]
    print(f"  equity check % of fund: {q(ow.pct_of_fund)}")
    big = ow[ow.pct_of_fund > 20].copy()
    big["fund"] = big.fund_id.map(fsz.name)
    big["company"] = big.company_id.map(co.set_index("company_id").name)
    print(f"  checks > 20% of fund: {len(big)} (> 25%: {(ow.pct_of_fund > 25).sum()})")
    if len(big):
        print(big.sort_values("pct_of_fund", ascending=False)[
            ["company", "fund", "size", "equity_invested_musd", "pct_of_fund"]].head(15).round(1).to_string())
    dep = ow.groupby("fund_id").equity_invested_musd.sum().reindex(fu.fund_id, fill_value=0)
    fu["deployed_pct"] = 100 * fu.fund_id.map(dep) / fu.size_musd
    fu["n_hold"] = fu.fund_id.map(ow.groupby("fund_id").size()).fillna(0)
    mature = fu[fu.vintage_year <= 2021]
    print(f"  deployed % (all funds): {q(fu.deployed_pct)}")
    print(f"  deployed % (vintage <= 2021, investment period over): {q(mature.deployed_pct)}")
    print(f"  holdings per fund: {q(fu.n_hold)}")
    zero = mature[mature.n_hold == 0]
    print(f"  mature funds with zero holdings: {len(zero)}; under 40% deployed: "
          f"{(mature.deployed_pct < 40).sum()} of {len(mature)}")
    if (fu.deployed_pct > 100).any():
        flag(f"{(fu.deployed_pct > 100).sum()} funds over 100% deployed")
    if (mature.deployed_pct < 40).sum() > 0.25 * len(mature):
        flag(f"{(mature.deployed_pct < 40).sum()} of {len(mature)} mature funds under 40% deployed")
    spf = fu.groupby("sponsor_id").size()
    print(f"  funds per sponsor: {spf.value_counts().sort_index().to_dict()}")
    fu["fund_no"] = fu.name.str.extract(r"Fund (?:Legacy )?([IVX]+)(?: Legacy)?$")[0]
    leg = fu[fu.name.str.contains("Legacy")]
    print(f"  fund names containing 'Legacy': {len(leg)} e.g. {leg.name.head(4).tolist()}")
    if len(leg):
        flag(f"{len(leg)} fund names use an unrealistic 'Legacy' label")
    # sponsor fund sequence monotone with vintage
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
    fu["fn"] = fu.fund_no.map(roman)
    bad_seq = 0
    for s_, g_ in fu.dropna(subset=["fn"]).groupby("sponsor_id"):
        g_ = g_.sort_values("fn")
        if not g_.vintage_year.is_monotonic_increasing:
            bad_seq += 1
            print(f"   out of order: {g_[['name', 'vintage_year']].values.tolist()}")
        gap = g_.fn.diff().max()
        if pd.notna(gap) and gap > 1:
            print(f"   numbering gap: {g_[['name', 'vintage_year']].values.tolist()}")
    print(f"  sponsors whose fund numbers are not in vintage order: {bad_seq}")
    if bad_seq:
        flag(f"{bad_seq} sponsors with fund numbering out of vintage order")
    aum = fu.groupby("sponsor_id").size_musd.sum()
    sp["fund_sum"] = sp.sponsor_id.map(aum).fillna(0)
    lowaum = sp[sp.aum_musd < sp.fund_sum * 0.6]
    print(f"  sponsor AUM vs sum of fund sizes: AUM/sum {q(sp.aum_musd / sp.fund_sum.replace(0, np.nan))}")
    print(f"  sponsors with AUM < 60% of fund sum: {len(lowaum)}")
    print(f"  sponsor AUM: {q(sp.aum_musd)}")
    lmm = sp[sp.strategy == "lower_mid_market_buyout"]
    big_lmm = fu[fu.sponsor_id.isin(lmm.sponsor_id) & (fu.size_musd > 1500)]
    print(f"  LMM-strategy funds > $1.5B: {len(big_lmm)}")
    # concurrent majority owners
    maj = ow[ow.stake_type == "majority"].copy()
    maj["end"] = maj.end_date.fillna(AS_OF + pd.Timedelta(days=1))
    ov = maj.merge(maj, on="company_id")
    ov = ov[(ov.ownership_id_x < ov.ownership_id_y) & (ov.start_date_x < ov.end_y) & (ov.start_date_y < ov.end_x)]
    print(f"  overlapping majority stakes on the same company: {len(ov)}")
    if len(ov):
        flag(f"{len(ov)} overlapping majority ownership pairs")
        print(ov[["company_id", "fund_id_x", "start_date_x", "end_x", "fund_id_y", "start_date_y", "end_y"]]
              .head(8).to_string())
    curmaj = maj[maj.end_date.isna()].groupby("company_id").size()
    print(f"  companies with >1 current majority owner: {(curmaj > 1).sum()}")
    # minority + majority from same fund concurrently
    mm = ow.merge(ow, on=["company_id", "fund_id"])
    mm = mm[(mm.ownership_id_x < mm.ownership_id_y)]
    print(f"  same company held twice by the same fund: {len(mm)}")
    endb = ow[ow.end_date.notna() & (ow.end_date <= ow.start_date)]
    print(f"  ownership end <= start: {len(endb)}")
    # owned public companies
    pubown = cur[cur.company_id.map(co.set_index("company_id").is_public) == "TRUE"]
    print(f"  current sponsor holdings that are public companies: {len(pubown)}")
    if len(pubown):
        flag(f"{len(pubown)} public companies currently majority/minority owned by a PE fund")

    head("3e. Ownership vs transactions consistency")
    buyers = tp[(tp.party_role == "buyer") & tp.fund_id.notna()][["txn_id", "fund_id"]]
    buyers = buyers.merge(tx[["txn_id", "target_id", "close_date", "deal_role", "structure"]], on="txn_id")
    m = ow.merge(buyers, left_on=["company_id", "fund_id"], right_on=["target_id", "fund_id"], how="left")
    m["gap"] = (m.close_date - m.start_date).dt.days.abs()
    best = m.groupby("ownership_id").gap.min()
    print(f"  ownership rows with a buyer txn by same fund within 31 days: {(best <= 31).sum()} of {len(ow)}")
    print(f"  ownership rows with no matching buy txn at all: {best.isna().sum()}")
    nobuy = ow[ow.ownership_id.isin(best[best.isna()].index)]
    print(f"   of which start in last 10 yrs (txn table covers about 10 yrs): "
          f"{(nobuy.start_date >= AS_OF - pd.DateOffset(years=10)).sum()}")
    # sponsor buyer txns with no ownership row
    m2 = buyers.merge(ow, left_on=["target_id", "fund_id"], right_on=["company_id", "fund_id"], how="left")
    print(f"  sponsor-buyer txns with no OWNERSHIP row for that fund: {m2.ownership_id.isna().sum()} of {len(buyers)}")
    # exits: exited holdings with a sale txn (seller = that fund) near end_date
    sellers = tp[(tp.party_role == "seller") & tp.fund_id.notna()][["txn_id", "fund_id"]].merge(
        tx[["txn_id", "target_id", "close_date"]], on="txn_id")
    e = ex.merge(sellers, left_on=["company_id", "fund_id"], right_on=["target_id", "fund_id"], how="left")
    e["gap"] = (e.close_date - e.end_date).dt.days.abs()
    eb = e.groupby("ownership_id").gap.min()
    exr = ex[ex.end_date >= AS_OF - pd.DateOffset(years=10)]
    print(f"  exits in last 10 yrs: {len(exr)}; with a seller txn by that fund within 31 days: "
          f"{(eb.reindex(exr.ownership_id) <= 31).sum()}")
    # who owns the company after a sponsor exit?
    nxt = []
    for _, r in exr.iterrows():
        later = ow[(ow.company_id == r.company_id) & (ow.start_date >= r.end_date - pd.Timedelta(days=31))]
        nxt.append(len(later) > 0)
    print(f"  exits followed by another fund's ownership (SBO): {sum(nxt)} of {len(exr)}")
    # add-on: platform sponsor-owned at close
    ab = tp[(tp.party_role == "buyer") & (tp.org_type == "company")][["txn_id", "org_id"]].merge(
        tx[["txn_id", "target_id", "close_date"]], on="txn_id")
    def owned_at(cid, dt):
        z = ow[(ow.company_id == cid) & (ow.start_date <= dt) & (ow.end_date.isna() | (ow.end_date >= dt))]
        return len(z) > 0
    ab["plat_owned"] = [owned_at(c, dt) for c, dt in zip(ab.org_id, ab.close_date)]
    print(f"  add-ons whose platform is fund-owned at close: {ab.plat_owned.sum()} of {len(ab)}")
    # target of add-on still independent afterwards?
    ab["tgt_rev"] = ab.target_id.map(co.set_index("company_id").revenue_musd)
    ab["plat_rev"] = ab.org_id.map(co.set_index("company_id").revenue_musd)
    print(f"  add-on target revenue > platform revenue: {(ab.tgt_rev > ab.plat_rev).sum()}")
    tgt_after = ab.merge(rh[(rh.org_type == "company") & (rh.role_type == "CEO") & rh.end_date.isna()],
                         left_on="target_id", right_on="org_id")
    print(f"  acquired add-on targets that still have a current CEO row: {tgt_after.target_id.nunique()} "
          f"of {ab.target_id.nunique()}")
    tgt_sig = sg.merge(ab, left_on="company_id", right_on="target_id")
    tgt_sig = tgt_sig[tgt_sig.signal_date > tgt_sig.close_date]
    print(f"  signals on add-on targets dated after they were acquired: {len(tgt_sig)} "
          f"({tgt_sig.signal_type.value_counts().to_dict()})")
    tgt_pl = pl[pl.company_id.isin(ab.target_id)]
    print(f"  add-on targets (already acquired) sitting in our PIPELINE: {len(tgt_pl)}")
    tgt_own = ow[ow.company_id.isin(ab.target_id)].merge(ab, left_on="company_id", right_on="target_id")
    tgt_own = tgt_own[tgt_own.start_date > tgt_own.close_date]
    print(f"  add-on targets later bought outright by a fund: {len(tgt_own)}")
    per_plat = ab.groupby("org_id").size()
    print(f"  add-ons per platform: {q(per_plat)}")

    head("3f. Executive tenure lengths")
    rh["end"] = rh.end_date.fillna(AS_OF)
    rh["yrs"] = (rh.end - rh.start_date).dt.days / 365.25
    rh["closed"] = rh.end_date.notna()
    for (rt_, fd), g_ in rh.groupby(["role_type", "is_founder"]):
        c = g_[g_.closed].yrs
        o = g_[~g_.closed].yrs
        print(f"  {rt_:18s} founder={fd:5s} closed n={len(c):4d} med={c.median():5.1f} p90={c.quantile(.9):5.1f} | "
              f"current n={len(o):4d} med-so-far={o.median():5.1f} max={o.max():5.1f}")
    fceo = rh[(rh.role_type == "CEO") & (rh.is_founder == "TRUE")]
    peceo = rh[(rh.role_type == "CEO") & (rh.is_founder == "FALSE") & rh.closed]
    cfo = rh[(rh.role_type == "CFO") & rh.closed]
    brd = rh[(rh.role_type == "Board") & rh.closed]
    print(f"  founder CEO total tenure (closed+current): {q(fceo.yrs)}  (brief 12-30)")
    print(f"  non-founder CEO closed tenure: {q(peceo.yrs)}  (brief PE-appointed 3-6)")
    print(f"  CFO closed tenure: {q(cfo.yrs)}  (brief 2-5)")
    print(f"  Board closed tenure: {q(brd.yrs)}  (brief 3-7)")
    print(f"  negative or zero-length tenures: {(rh.yrs <= 0).sum()}")
    if (rh.yrs <= 0).any():
        flag(f"{(rh.yrs <= 0).sum()} tenures with end <= start")
    print(f"  tenures > 40 years: {(rh.yrs > 40).sum()}")
    # current CEO count per company
    cc = rh[(rh.org_type == "company") & (rh.role_type == "CEO") & rh.end_date.isna()].groupby("org_id").size()
    print(f"  companies by current CEO count: {cc.reindex(co.company_id, fill_value=0).value_counts().to_dict()}")
    ccfo = rh[(rh.org_type == "company") & (rh.role_type == "CFO") & rh.end_date.isna()].groupby("org_id").size()
    print(f"  companies with >1 current CFO: {(ccfo > 1).sum()}")
    # overlapping CEO tenures at same company
    ceos = rh[(rh.org_type == "company") & (rh.role_type == "CEO")]
    o2 = ceos.merge(ceos, on="org_id")
    o2 = o2[(o2.role_id_x < o2.role_id_y) & (o2.start_date_x < o2.end_y) & (o2.start_date_y < o2.end_x)]
    o2["days"] = (np.minimum(o2.end_x, o2.end_y) - np.maximum(o2.start_date_x, o2.start_date_y)).dt.days
    print(f"  overlapping CEO tenures at the same company: {len(o2)} (over 90 days: {(o2.days > 90).sum()})")
    if (o2.days > 90).sum():
        flag(f"{(o2.days > 90).sum()} pairs of CEOs overlapping >90 days at one company")
        print(o2[o2.days > 90][["org_id", "person_id_x", "start_date_x", "end_x", "person_id_y",
                                "start_date_y", "end_y", "days"]].head(6).to_string())
    # same person holds 2 concurrent C-suite roles at different companies
    cs = rh[(rh.org_type == "company") & rh.role_type.isin(["CEO", "CFO", "COO", "President"])]
    o3 = cs.merge(cs, on="person_id")
    o3 = o3[(o3.role_id_x < o3.role_id_y) & (o3.org_id_x != o3.org_id_y) &
            (o3.start_date_x < o3.end_y) & (o3.start_date_y < o3.end_x)]
    o3["days"] = (np.minimum(o3.end_x, o3.end_y) - np.maximum(o3.start_date_x, o3.start_date_y)).dt.days
    print(f"  people with concurrent C-suite roles at two companies (>90 days): {(o3.days > 90).sum()}")
    if (o3.days > 90).sum():
        flag(f"{(o3.days > 90).sum()} concurrent full-time C-suite roles at different companies")
        print(o3[o3.days > 90][["person_id", "org_id_x", "role_type_x", "start_date_x", "end_x", "org_id_y",
                                "role_type_y", "start_date_y", "end_y"]].head(6).to_string())
    roles_per_person = rh.groupby("person_id").size().reindex(pe.person_id, fill_value=0)
    print(f"  roles per person: {roles_per_person.value_counts().sort_index().to_dict()}")
    print(f"  persons with no role and no CRM/TP reference: "
          f"{(~pe.person_id.isin(set(rh.person_id) | set(crm.our_person_id) | set(crm.counterparty_person_id.dropna()) | set(tp.lead_person_id.dropna()) | set(pl.owner_person_id))).sum()}")
    print(f"  Board seats: {len(rh[rh.role_type=='Board'])} for {len(co)} companies; companies with a board row: "
          f"{rh[rh.role_type=='Board'].org_id.nunique()}")

    head("4. Temporal sanity")
    fy = co.set_index("company_id").founded_year
    rc = rh[rh.org_type == "company"].copy()
    rc["fy"] = rc.org_id.map(fy)
    early = rc[rc.start_date.dt.year < rc.fy]
    print(f"  company roles starting before founded_year: {len(early)}")
    if len(early):
        flag(f"{len(early)} company roles start before founding")
        print(early[["role_id", "org_id", "role_type", "start_date", "fy"]].head(8).to_string())
    fnot = rc[(rc.is_founder == "TRUE")]
    fgap = (fnot.start_date.dt.year - fnot.fy)
    print(f"  founder roles: start year - founded_year: {fgap.value_counts().sort_index().to_dict()}")
    if (fgap.abs() > 1).any():
        flag(f"{(fgap.abs() > 1).sum()} founder roles starting more than 1 year after/before founding")
        print(fnot[fgap.abs() > 1][["role_id", "org_id", "role_type", "start_date", "fy"]].head(8).to_string())
    # birth proxy: career span
    span = rh.groupby("person_id").agg(first=("start_date", "min"), last=("end", "max"))
    span["yrs"] = (span["last"] - span["first"]).dt.days / 365.25
    print(f"  career span (first senior role to last end/AS_OF): {q(span.yrs)}")
    print(f"  spans > 45 yrs: {(span.yrs > 45).sum()}; > 40: {(span.yrs > 40).sum()}; earliest senior start: "
          f"{rh.start_date.min().date()}")
    if (span.yrs > 45).sum():
        flag(f"{(span.yrs > 45).sum()} people with senior careers over 45 years (implies age 70+ at AS_OF)")
        print(span[span.yrs > 45].head(6).to_string())
    # founders: founded long ago and still current
    longf = fceo[(fceo.end_date.isna()) & (fceo.yrs > 35)]
    print(f"  current founder CEOs with 35+ years in seat: {len(longf)}")
    if len(longf):
        print("   ", longf[["org_id", "person_id", "start_date"]].head(5).values.tolist())
    # deals before company exists
    tx["fy"] = tx.target_id.map(fy)
    bad = tx[tx.close_date.dt.year < tx.fy]
    print(f"  deals closing before target founded: {len(bad)}")
    young = tx[tx.close_date.dt.year - tx.fy < 3]
    print(f"  deals on targets under 3 years old: {len(young)}")
    if len(bad):
        flag(f"{len(bad)} deals before target founded")
    ob = ow[ow.start_date.dt.year < ow.company_id.map(fy)]
    print(f"  ownership starting before founding: {len(ob)}")
    if len(ob):
        flag(f"{len(ob)} ownership starts before founding")
    sgb = sg[sg.signal_date.dt.year < sg.company_id.map(fy)]
    print(f"  signals before founding: {len(sgb)}")
    clb = cl[(cl.since_year < cl.supplier_id.map(fy)) | (cl.since_year < cl.customer_id.map(fy))]
    print(f"  commercial links since before either party founded: {len(clb)}")
    if len(clb):
        flag(f"{len(clb)} COMMERCIAL_LINK since_year before a party was founded")
    print(f"  commercial link since_year: {q(cl.since_year)}")
    plb = pl[pl.added_date.dt.year < pl.company_id.map(fy)]
    print(f"  pipeline added before founding: {len(plb)}")
    # future dates
    fut = {
        "ROLE start": (rh.start_date > AS_OF).sum(), "ROLE end": (rh.end_date > AS_OF).sum(),
        "OWNERSHIP start": (ow.start_date > AS_OF).sum(), "OWNERSHIP end": (ow.end_date > AS_OF).sum(),
        "TXN close": (tx.close_date > AS_OF).sum(), "CRM date": (crm.interaction_date > AS_OF).sum(),
        "PIPELINE added": (pl.added_date > AS_OF).sum(), "SIGNAL signal_date": (sg.signal_date > AS_OF).sum(),
        "LINK since_year": (cl.since_year > AS_OF.year).sum(), "COMPANY founded": (co.founded_year > AS_OF.year).sum(),
        "FUND vintage": (fu.vintage_year > AS_OF.year).sum(),
    }
    print(f"  dates after AS_OF (should all be 0): {fut}")
    for k_, v in fut.items():
        if v:
            flag(f"{v} {k_} after AS_OF")
    evf = sg[sg.event_date > AS_OF]
    print(f"  event_date after AS_OF by type (only DEBT_MATURITY allowed): {evf.signal_type.value_counts().to_dict()}")
    if (evf.signal_type != "DEBT_MATURITY").any():
        flag("future event_date on a non-maturity signal")
    dm = sg[sg.signal_type == "DEBT_MATURITY"]
    dm_m = (dm.event_date - AS_OF).dt.days / 30.44
    print(f"  DEBT_MATURITY months from AS_OF: {q(dm_m)}")
    print(f"  DEBT_MATURITY event_date missing: {dm.event_date.isna().sum()}, maturity before signal_date: "
          f"{(dm.event_date < dm.signal_date).sum()}")
    past_dm = dm[dm.event_date < AS_OF]
    print(f"  DEBT_MATURITY already matured (event before AS_OF): {len(past_dm)}")
    print(f"  signal_date range: {sg.signal_date.min().date()} .. {sg.signal_date.max().date()}")
    print(f"  signals per company: {sg.groupby('company_id').size().value_counts().sort_index().to_dict()}")
    print(f"  CRM date range: {crm.interaction_date.min().date()} .. {crm.interaction_date.max().date()}")
    # roles at intermediary/sponsor ending after AS_OF etc covered. PIPELINE stage vs owned.
    nwf = set(fu[fu.sponsor_id.isin(sp[sp.name.str.startswith("Northwind")].sponsor_id)].fund_id)
    owned_now = set(cur[cur.fund_id.isin(nwf)].company_id)
    print(f"  PIPELINE companies currently owned by Northwind: {len(set(pl.company_id) & owned_now)}")
    if set(pl.company_id) & owned_now:
        flag("pipeline contains a current Northwind holding")
    # interactions with persons before their first role / after their last role
    cp = crm.dropna(subset=["counterparty_person_id"]).merge(span, left_on="counterparty_person_id",
                                                            right_index=True, how="left")
    print(f"  CRM touches with a person before their first senior role: {(cp.interaction_date < cp['first']).sum()}")
    # weekend meetings/calls
    wk = crm.interaction_date.dt.dayofweek >= 5
    print(f"  CRM on weekends: {wk.sum()} ({100*wk.mean():.1f}%; uniform random would be 28.6%)")
    print("  weekend share by channel:", (crm.assign(w=wk).groupby("channel").w.mean() * 100).round(1).to_dict())
    tw = tx.close_date.dt.dayofweek >= 5
    print(f"  deals closing on weekends: {tw.sum()} ({100*tw.mean():.1f}%)")

    head("3g. Deal counts per intermediary")
    adv = tp[tp.org_type == "intermediary"]
    cnt = adv.groupby("org_id").size().reindex(im.intermediary_id, fill_value=0)
    imx = im.set_index("intermediary_id").assign(deals=cnt)
    print(imx.groupby("intermediary_type").deals.describe()[["count", "mean", "50%", "max"]].round(1).to_string())
    print(f"  top 8: {imx.sort_values('deals', ascending=False).head(8)[['name','intermediary_type','deals']].values.tolist()}")
    print(f"  intermediaries with 0 deals: {(cnt == 0).sum()}")
    advised = adv.txn_id.nunique()
    print(f"  txns with any advisor: {advised} of {len(tx)} ({100*advised/len(tx):.0f}%)")
    sell = adv[adv.party_role == "sell_side_advisor"].merge(tx, on="txn_id")
    print(f"  sell-side advised share by deal_role: "
          f"{(sell.groupby('deal_role').txn_id.nunique() / tx.groupby('deal_role').size() * 100).round(0).to_dict()}")
    print(f"  sell-side advised share platforms over $50M EV: "
          f"{100*sell[sell.ev_musd>50].txn_id.nunique()/max(1,(tx.ev_musd>50).sum()):.0f}%")
    bro = adv[adv.org_id.isin(im[im.intermediary_type == "business_broker"].intermediary_id)].merge(tx, on="txn_id")
    print(f"  business-broker deal EV: {q(bro.ev_musd)}")
    lb = adv[adv.org_id.isin(im[im.intermediary_type == "large_bank"].intermediary_id)].merge(tx, on="txn_id")
    print(f"  large-bank deal EV: {q(lb.ev_musd)}")
    bout = adv[adv.org_id.isin(im[im.intermediary_type == "boutique"].intermediary_id)].merge(tx, on="txn_id")
    print(f"  boutique deal EV: {q(bout.ev_musd)}")
    # banker headcount per intermediary
    bk = rh[rh.org_type == "intermediary"].groupby("org_id").person_id.nunique().reindex(im.intermediary_id,
                                                                                         fill_value=0)
    print(f"  bankers per intermediary: {q(bk)}; with 0 bankers: {(bk == 0).sum()}")
    nolead = adv.lead_person_id.isna().mean() * 100
    print(f"  advisor rows with no lead banker: {nolead:.0f}%")

    head("3h. CRM touchpoint cadence")
    crm["ym"] = crm.interaction_date.dt.to_period("M")
    rng_m = (crm.interaction_date.max() - crm.interaction_date.min()).days / 30.44
    print(f"  span {rng_m:.1f} months; per our_person per month: "
          f"{(crm.groupby('our_person_id').size() / rng_m).round(1).to_dict()}")
    last24 = crm[crm.interaction_date >= AS_OF - pd.DateOffset(months=24)]
    print(f"  touches in last 24 months: {len(last24)} ({100*len(last24)/len(crm):.0f}%)")
    print(f"  touches by year: {crm.interaction_date.dt.year.value_counts().sort_index().to_dict()}")
    keyc = crm.counterparty_person_id.fillna(crm.counterparty_org_id)
    per = crm.assign(k=keyc).groupby("k").size()
    print(f"  touches per counterparty: {q(per)}")
    gaps = (crm.assign(k=keyc).sort_values("interaction_date").groupby("k").interaction_date.diff().dt.days)
    print(f"  days between successive touches to the same counterparty: {q(gaps)}")
    print(f"  sentiment: {crm.sentiment.value_counts(normalize=True).round(2).to_dict()}")
    print(f"  org-level vs person-level: person={crm.counterparty_person_id.notna().sum()} "
          f"org-only={crm.counterparty_person_id.isna().sum()}")
    both_null = crm[crm.counterparty_person_id.isna() & crm.counterparty_org_id.isna()]
    print(f"  CRM rows with neither counterparty person nor org: {len(both_null)}")
    if len(both_null):
        flag(f"{len(both_null)} CRM rows with no counterparty at all")
    # person-level touch whose org does not match any role of that person
    pr = crm.dropna(subset=["counterparty_person_id", "counterparty_org_id"])
    rk = set(zip(rh.person_id, rh.org_id))
    mis = sum((p, o) not in rk for p, o in zip(pr.counterparty_person_id, pr.counterparty_org_id))
    print(f"  person-level touches whose org is not one of the person's employers: {mis} of {len(pr)}")
    # pipeline
    print(f"  PIPELINE stages: {pl.stage.value_counts().to_dict()}")
    plc = pl.merge(co, on="company_id")
    print(f"  pipeline companies in thesis l2: {plc.l2.isin(MARGIN_BRIEF).mean()*100:.0f}%; EBITDA in 5-40: "
          f"{plc.ebitda_musd.between(5,40).mean()*100:.0f}%")
    print(f"  pipeline est_equity_check: {q(pl.est_equity_check_musd)}")
    plc["chk_vs_ebitda"] = plc.est_equity_check_musd / plc.ebitda_musd
    print(f"  pipeline check / EBITDA (turns of equity): {q(plc.chk_vs_ebitda)}")
    pl_crm = pl.company_id.isin(set(crm.counterparty_org_id.dropna()) |
                                set(rh[rh.person_id.isin(crm.counterparty_person_id.dropna())].org_id))
    print(f"  pipeline companies with any CRM touch (org or a person employed there): {pl_crm.sum()} of {len(pl)}")
    stalled = pl[(pl.stage.isin(["Engaged", "IOI prep", "IOI Submitted"])) & ~pl_crm]
    print(f"  advanced-stage pipeline rows with no CRM touch: {len(stalled)}")
    if len(stalled):
        flag(f"{len(stalled)} Engaged/IOI pipeline rows with zero CRM touch")

    head("5. Protected attributes and proxies")
    hits = [(k, c) for k, df in T.items() for c in df.columns if PROTECTED.search(c)]
    print(f"  protected-attribute column names: {hits}")
    if hits:
        flag(f"protected columns {hits}")
    vals = re.compile(r"\b(male|female|man|woman|mr|mrs|ms|miss|he|she|asian|black|white|hispanic|latino|"
                      r"caucasian|african|jewish|muslim|christian|born|age \d+|aged)\b", re.I)
    vh = []
    for k, df in T.items():
        for c in df.columns:
            if df[c].dtype == object:
                s = df[c].dropna().astype(str)
                m_ = s[s.str.contains(vals)]
                if len(m_) and c not in ("first_name", "last_name", "full_name", "name"):
                    vh.append((k, c, m_.head(3).tolist()))
    print(f"  protected-looking values outside name columns: {vh}")
    titles = rh.title.value_counts().index.tolist()
    print(f"  ROLE_HISTORY titles (proxy check): {titles}")
    print("  PERSON columns:", list(pe.columns), "(names only; name-based gender/ethnicity inference is the only proxy)")
    # model code check: do rules reference first_name / names?
    rules = (ROOT / "pe_deal_graph/model/rules.py")
    if rules.exists():
        src = rules.read_text()
        print(f"  rules.py mentions first_name/last_name/full_name: "
              f"{len(re.findall(r'first_name|last_name|full_name', src))}; age|gender|birth: "
              f"{len(re.findall(r'(?i)\\b(age|gender|birth|ethnic)', src))}")

    head("6. Decoys and near-misses (plausibility)")
    nm = co.set_index("name")
    def show(n):
        if n not in nm.index:
            print(f"  {n}: not present"); return None
        r = nm.loc[n]
        cid = r.company_id
        s = sg[sg.company_id == cid].signal_type.value_counts().to_dict()
        o = ow[ow.company_id == cid][["fund_id", "start_date", "end_date", "stake_type"]].values.tolist()
        print(f"  {n}: {r.l2}/{r.l3} rev={r.revenue_musd} ebitda={r.ebitda_musd} margin={r.margin:.1f}% "
              f"founded={r.founded_year} signals={s} own={[(f, str(a.date()), str(b.date()) if pd.notna(b) else None, st) for f, a, b, st in o]}")
        return cid
    for n in ["Cobalt Urgent Care Partners", "Pembrook Veterinary Pharmaceuticals", "Linden Hollow Senior Care",
              "Northgate Behavioral Health", "Ashby Vale Dental Partners", "Shalecrest Materials Testing",
              "Larkspur Revenue Partners",
              "Saltmarsh Home Infusion", "Tessmark Clinical Supply", "Ironvale Testing Group",
              "Fernhollow Environmental Labs", "Bayside Pediatric Therapy Group", "Quarry Records Retrieval",
              "Fenwick Food Safety Labs"]:
        show(n)
    # R12 crafted near-misses by ID (handoff 18 names are stale after the R20 regeneration)
    nmid = {"C2405": "EBITDA just over band", "C7851": "US gate", "C6151": "public", "C5026": "exit window",
            "C6041": "CFO from PE", "C7185": "11-month overlap", "C6342": "Q-ADDON Jaccard", "C9099": "conflict"}
    cidx = co.set_index("company_id")
    for k_, v in nmid.items():
        if k_ in cidx.index:
            print(f"  near-miss {v}: {k_} now named '{cidx.loc[k_, 'name']}'")
    cob = co[co.name == "Cobalt Urgent Care Partners"].company_id
    if len(cob):
        na = (sg.company_id.isin(cob) & (sg.signal_type == "ADDON_ANNOUNCED")).sum()
        nt = tp[(tp.party_role == "buyer") & tp.org_id.isin(cob)].txn_id.nunique()
        print(f"  Cobalt ADDON_ANNOUNCED signals {na} vs add-on txns bought by Cobalt {nt}")
    sigc = sg.groupby("company_id").size()
    print(f"  signals per company among companies with signals: {q(sigc)}; companies with >=5: {(sigc>=5).sum()}")
    # Brayford league table vs others
    print(f"  Brayford rank in deal count: "
          f"{list(imx.sort_values('deals', ascending=False).name).index('Brayford Capital Markets')+1 if 'Brayford Capital Markets' in set(imx.name) else 'n/a'}")
    bray = im[im.name == "Brayford Capital Markets"].intermediary_id
    if len(bray):
        bd = adv[adv.org_id.isin(bray)].merge(tx, on="txn_id")
        bd["buyer"] = bd.txn_id.map(tp[tp.party_role == "buyer"].set_index("txn_id").org_id)
        print(f"  Brayford deals: {len(bd)}; distinct buyers {bd.buyer.nunique()}; thesis-l2 share "
              f"{bd.tl2.isin(MARGIN_BRIEF).mean()*100:.0f}%; EV {q(bd.ev_musd)}; roles {bd.party_role.value_counts().to_dict()}")
        print(f"  Brayford deal_role: {bd.deal_role.value_counts().to_dict()}")
    hl = im[im.name == "Harbor Lane Advisors"].intermediary_id
    if len(hl):
        hd = adv[adv.org_id.isin(hl)].merge(tx, on="txn_id")
        print(f"  Harbor Lane deals: {len(hd)}; EV {q(hd.ev_musd)}; years {hd.close_date.dt.year.value_counts().sort_index().to_dict()}")
    # Northgate EBITDA vs fund band
    print(f"  Fund IV band: {fu[fu.name.str.contains('Northwind Equity Partners Fund IV')][['ebitda_min_musd','ebitda_max_musd','size_musd','area_guideline_pct']].values.tolist()}")


    head("7. Layer attribution (signal = PK present in --signal-dir) and hero-visible detail")
    sd = (ROOT / a.signal_dir).resolve()
    if sd != d and (sd / "COMPANY.csv").exists():
        S = {k: pd.read_csv(sd / f"{k}.csv", dtype=str) for k in ["COMPANY", "ROLE_HISTORY", "OWNERSHIP",
                                                                  "TRANSACTION", "COMMERCIAL_LINK", "PERSON"]}
        sig_co, sig_role = set(S["COMPANY"].company_id), set(S["ROLE_HISTORY"].role_id)
        sig_own, sig_tx = set(S["OWNERSHIP"].ownership_id), set(S["TRANSACTION"].txn_id)
        sig_link, sig_pe = set(S["COMMERCIAL_LINK"].link_id), set(S["PERSON"].person_id)
        lay = lambda s_, ss: np.where(s_.isin(ss), "signal", "noise")
        rh["layer"] = lay(rh.role_id, sig_role)
        for (rt_, fd), g_ in rh[rh.role_type.isin(["CEO"])].groupby(["is_founder", "layer"]):
            print(f"  CEO founder={rt_} {fd}: {q(g_.yrs, (0.5, 0.75, 0.95))}")
        span2 = span.assign(layer=lay(pd.Series(span.index, index=span.index), sig_pe))
        print(f"  careers > 45 yrs by layer: {span2[span2.yrs > 45].layer.value_counts().to_dict()}")
        lf = fceo[(fceo.end_date.isna()) & (fceo.yrs > 35)]
        print(f"  current founder CEOs 35+ yrs by layer: "
              f"{pd.Series(lay(lf.role_id, sig_role)).value_counts().to_dict()}")
        nf = rh[(rh.role_type == "CEO") & (rh.is_founder == "FALSE")]
        print(f"  non-founder CEO closed tenure by layer: "
              f"{nf[nf.closed].groupby('layer').yrs.median().round(1).to_dict()}; current-so-far "
              f"{nf[~nf.closed].groupby('layer').yrs.median().round(1).to_dict()}")
        # first CEO of a company that started at founding but is not marked founder
        fstart = nf.assign(fy=nf.org_id.map(fy))
        atfound = fstart[fstart.start_date.dt.year <= fstart.fy + 1]
        print(f"  non-founder CEOs who start within a year of founding: {len(atfound)} "
              f"(closed median {atfound[atfound.closed].yrs.median():.1f} yrs)")
        tx["layer"] = lay(tx.txn_id, sig_tx)
        print("  EV/EBITDA median by band and layer:")
        print(tx.groupby(["band", "layer"], observed=True).ev_ebitda.agg(["size", "median"]).round(2).to_string())
        print("  add-on vs platform EV/EBITDA by layer:",
              tx.groupby(["layer", "deal_role"]).ev_ebitda.median().round(2).to_dict())
        ow["layer"] = lay(ow.ownership_id, sig_own)
        big2 = ow[ow.pct_of_fund > 20]
        print(f"  checks > 20% of fund by layer: {big2.layer.value_counts().to_dict()}; > 25%: "
              f"{big2[big2.pct_of_fund > 25].layer.value_counts().to_dict()}")
        print(f"  ownership rows by layer: {ow.layer.value_counts().to_dict()}")
        print(f"  late (vintage+6) holdings by layer: {ow[ow.start_yr > ow.vintage + 6].layer.value_counts().to_dict()}")
        clb2 = clb.assign(layer=lay(clb.link_id, sig_link))
        print(f"  links since before founding by layer: {clb2.layer.value_counts().to_dict()}")
        ab["tlayer"] = lay(ab.target_id, sig_co)
        print(f"  add-on targets by layer: {ab.tlayer.value_counts().to_dict()}")
        tpl = tgt_pl.merge(ab, left_on="company_id", right_on="target_id")
        tpl["plat_name"] = tpl.org_id.map(co.set_index("company_id").name)
        tpl["tgt_name"] = tpl.target_id.map(co.set_index("company_id").name)
        print(f"  acquired add-on targets in PIPELINE: {len(tpl)}; stages {tpl.stage.value_counts().to_dict()}; "
              f"pipeline added after acquisition: {(tpl.added_date > tpl.close_date).sum()}")
        print(tpl[["tgt_name", "stage", "added_date", "close_date", "plat_name"]].head(8).to_string())
        sigp = tgt_sig[tgt_sig.signal_type.isin(["BANKER_ENGAGED", "DEBT_MATURITY"])]
        print(f"  scored-type signals (BANKER_ENGAGED/DEBT_MATURITY) on already-acquired add-ons: {len(sigp)} "
              f"on {sigp.company_id.nunique()} companies")
        # founder-title rows whose start is far from founding (layer)
        far = fnot[fgap.abs() > 1]
        print(f"  founder roles far from founding: {far.assign(n=far.org_id.map(co.set_index('company_id').name))[['org_id','n','title','start_date','fy']].values.tolist()}")
        # CRM/deal weekend by layer
        # hero-visible size detail
        hero = ["Larkspur Revenue Partners", "Bayside Pediatric Therapy Group", "Saltmarsh Home Infusion",
                "Quarry Records Retrieval", "Tessmark Clinical Supply", "Fenwick Food Safety Labs",
                "Ashby Vale Dental Partners", "Tullmere Chemical Distribution", "Flintmoor Industrial Supply",
                "Primdale Ingredients Co", "Ironvale Testing Group", "Pinewick Dental Partners"]
        hv = co[co.name.isin(hero)][["name", "area", "revenue_musd", "ebitda_musd", "employees", "rev_per_emp_k",
                                     "founded_year"]]
        print(hv.round(1).to_string(index=False))
        # growth since deal vs years since close
        tx["yrs_since"] = (AS_OF - tx.close_date).dt.days / 365.25
        print(f"  corr(EBITDA now / at-close, years since close) = "
              f"{tx[['ratio_now_vs_deal','yrs_since']].corr().iloc[0,1]:.2f}; "
              f"median ratio deals <1y old {tx[tx.yrs_since<1].ratio_now_vs_deal.median():.2f} vs >7y "
              f"{tx[tx.yrs_since>7].ratio_now_vs_deal.median():.2f}")
        tx["wk"] = tx.close_date.dt.dayofweek >= 5
        print(f"  weekend closings by layer: {(tx.groupby('layer').wk.mean()*100).round(1).to_dict()}")
        brk = adv[adv.org_id.isin(im[im.intermediary_type == "business_broker"].intermediary_id)].merge(
            tx[["txn_id", "ev_musd", "layer"]], on="txn_id")
        print(f"  business-broker deals > $25M EV: {(brk.ev_musd > 25).sum()} of {len(brk)}; by layer "
              f"{brk[brk.ev_musd > 25].layer.value_counts().to_dict()}")
        ex2 = exr.assign(layer=lay(exr.ownership_id, sig_own))
        ex2["has_sale"] = (eb.reindex(ex2.ownership_id) <= 31).values
        print(f"  exits (last 10 yrs) without a sale txn by layer: {ex2[~ex2.has_sale].layer.value_counts().to_dict()}")
        aa = sg[sg.signal_type == "ADDON_ANNOUNCED"]
        abuy = set(tp[(tp.party_role == "buyer") & (tp.org_type == "company")].org_id)
        print(f"  ADDON_ANNOUNCED signals on companies that never bought an add-on: "
              f"{(~aa.company_id.isin(abuy)).sum()} of {len(aa)}")
        print(f"  platform seller_type by layer: "
              f"{tx[tx.deal_role=='platform'].groupby(['layer','seller_type']).size().to_dict()}")
    else:
        print("  skipped (no separate signal dir)")

    head("SUMMARY")
    print(f"  {len(FLAGS)} flags")
    for f_ in FLAGS:
        print(f"   - {f_}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
