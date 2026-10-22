#!/usr/bin/env python3
"""Independent oracle for the PE deal-graph hero questions (owner: R06 Oracle Engineer).

Reads ONLY data/csv/*.csv (and implements the specs in QUESTIONS.md v2). It never reads
data/generate.py or data/golden/. Pure pandas + networkx, no RAI, no Snowflake.

Computes:
  Q-SCORE     thesis fit (sector-hierarchy closure), readiness, access, composite score, tiers
  Q-PATH      Knows (K1 tenure overlap, K2 deal co-participation, K3 positive CRM), seed
              distances, shortest-path reconstruction, path strength ranking, decision-makers
  Q-FLOW      sector-scoped deal-flow graph (last 5 years), exact betweenness (unnormalized),
              pagerank, CoverageGap, top 5 bridges
  Q-CONFLICT  2-hop commercial reach to current Northwind holdings, thesis-area concentration
  FINALE      A_WARM_PATH (+10, CEO within 2 Knows hops of a seed) and the Fund III conflict flag

Output: data/oracle_output.json (deterministic; no timestamps).
Usage:  .venv/bin/python data/oracle.py [--out PATH]
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parent
CSV_DIR = ROOT / "csv"
DEFAULT_OUT = ROOT / "oracle_output.json"

# ----------------------------------------------------------------------------------------------
# Clock (QUESTIONS.md 0.1). Every window is relative to AS_OF; never today().
# ----------------------------------------------------------------------------------------------
AS_OF = date(2026, 10, 1)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


T = AS_OF
T_6M = add_months(T, -6)
T_12M = add_months(T, -12)
T_18M = add_months(T, -18)
T_24M = add_months(T, -24)
T_5Y = add_months(T, -60)
T_10Y = add_months(T, -120)
T_15Y = add_months(T, -180)
T_20Y = add_months(T, -240)
T_P18M = add_months(T, 18)
VINTAGE_CUT = T.year - 8

NORTHWIND_SPONSOR_NAME = "Northwind Equity Partners"  # CONFIG CUSTOMER_DISPLAY_NAME
CONFLICT_SUBJECT_NAME = "Keystone Clinical Supply"  # Q-CONFLICT Tier-1 prompt names the subject
ADVISOR_ROLES = {"sell_side_advisor", "buy_side_advisor", "debt_advisor"}
SCORED_SIGNAL_TYPES = {"BANKER_ENGAGED", "DEBT_MATURITY"}
EBITDA_MIN, EBITDA_MAX = 5.0, 40.0
TIER_A, TIER_B = 70, 50
READINESS_CAP = 50
FLOAT_DP = 6


# ----------------------------------------------------------------------------------------------
# Loading helpers
# ----------------------------------------------------------------------------------------------
def _d(v) -> date | None:
    if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
        return None
    return date.fromisoformat(str(v)[:10])


def _f(v) -> float | None:
    if v is None or v == "":
        return None
    return float(v)


def _s(v) -> str | None:
    return None if v is None or v == "" else str(v)


def _b(v) -> bool:
    return str(v).strip().upper() in {"TRUE", "1", "T", "YES", "Y"}


def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(CSV_DIR / f"{name}.csv", dtype=str, keep_default_na=False)


def rows(df: pd.DataFrame) -> list[dict]:
    return df.to_dict(orient="records")


def r(x: float | None, dp: int = FLOAT_DP):
    return None if x is None else round(float(x), dp)


def years(days: int) -> float:
    return days / 365.25


def is_current(start: date | None, end: date | None) -> bool:
    """Current at T: started on or before T and end NULL or after T."""
    return start is not None and start <= T and (end is None or end > T)


def eff_end(end: date | None) -> date:
    """Open end date (NULL) is evaluated as T (QUESTIONS.md 0.1)."""
    return T if end is None else end


def fmt_end(end: date | None) -> str:
    return "present" if end is None else end.isoformat()


def recency(d: date) -> float:
    if d >= T_10Y:
        return 1.0
    if d >= T_20Y:
        return 0.7
    return 0.4


# ----------------------------------------------------------------------------------------------
# Data model (plain dicts built from pandas frames)
# ----------------------------------------------------------------------------------------------
class Data:
    def __init__(self):
        self.manifest_sha256 = None
        mpath = CSV_DIR / "MANIFEST.json"
        if mpath.exists():
            self.manifest_sha256 = hashlib.sha256(mpath.read_bytes()).hexdigest()
        self.csv_sha256 = {}
        for p in sorted(CSV_DIR.glob("*.csv")):
            self.csv_sha256[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest_mismatches = []
        if mpath.exists():
            man = json.loads(mpath.read_text())
            for tbl, meta in sorted(man.get("tables", {}).items()):
                f = CSV_DIR / meta.get("file", f"{tbl}.csv")
                if not f.exists():
                    self.manifest_mismatches.append(f"{tbl}: file missing")
                    continue
                if meta.get("sha256") and meta["sha256"] != self.csv_sha256.get(f.name):
                    self.manifest_mismatches.append(f"{tbl}: sha256 differs from MANIFEST")
                n = len(pd.read_csv(f, dtype=str, keep_default_na=False))
                if meta.get("rows") is not None and int(meta["rows"]) != n:
                    self.manifest_mismatches.append(f"{tbl}: {n} rows, MANIFEST says {meta['rows']}")
        else:
            self.manifest_mismatches.append("MANIFEST.json missing")

        self.sector = {x["sector_id"]: x for x in rows(load_csv("SECTOR"))}
        self.region = {x["region_id"]: x for x in rows(load_csv("REGION"))}
        self.sponsor = {x["sponsor_id"]: x for x in rows(load_csv("SPONSOR"))}
        self.intermediary = {x["intermediary_id"]: x for x in rows(load_csv("INTERMEDIARY"))}
        self.fund = {}
        for x in rows(load_csv("FUND")):
            x["vintage_year"] = int(x["vintage_year"])
            x["size_musd"] = _f(x["size_musd"])
            x["area_guideline_pct"] = _f(x["area_guideline_pct"])
            self.fund[x["fund_id"]] = x
        self.focus = rows(load_csv("FUND_FOCUS"))
        for x in self.focus:
            x["margin_benchmark_pct"] = _f(x["margin_benchmark_pct"])
        self.company = {}
        for x in rows(load_csv("COMPANY")):
            x["revenue_musd"] = _f(x["revenue_musd"])
            x["ebitda_musd"] = _f(x["ebitda_musd"])
            x["is_public"] = _b(x["is_public"])
            self.company[x["company_id"]] = x
        self.person = {x["person_id"]: x for x in rows(load_csv("PERSON"))}
        self.roles = []
        for x in rows(load_csv("ROLE_HISTORY")):
            x["start_date"] = _d(x["start_date"])
            x["end_date"] = _d(x["end_date"])
            x["is_founder"] = _b(x["is_founder"])
            self.roles.append(x)
        self.roles.sort(key=lambda x: x["role_id"])
        self.ownership = []
        for x in rows(load_csv("OWNERSHIP")):
            x["start_date"] = _d(x["start_date"])
            x["end_date"] = _d(x["end_date"])
            x["equity_invested_musd"] = _f(x["equity_invested_musd"])
            self.ownership.append(x)
        self.ownership.sort(key=lambda x: x["ownership_id"])
        self.txn = {}
        for x in rows(load_csv("TRANSACTION")):
            x["close_date"] = _d(x["close_date"])
            self.txn[x["txn_id"]] = x
        self.party = sorted(rows(load_csv("TRANSACTION_PARTY")), key=lambda x: x["party_id"])
        for x in self.party:
            x["fund_id"] = _s(x["fund_id"])
            x["lead_person_id"] = _s(x["lead_person_id"])
        self.links = sorted(rows(load_csv("COMMERCIAL_LINK")), key=lambda x: x["link_id"])
        self.crm = []
        for x in rows(load_csv("CRM_INTERACTION")):
            x["interaction_date"] = _d(x["interaction_date"])
            x["counterparty_person_id"] = _s(x["counterparty_person_id"])
            x["counterparty_org_id"] = _s(x["counterparty_org_id"])
            self.crm.append(x)
        self.crm.sort(key=lambda x: x["interaction_id"])
        self.pipeline = {}
        for x in rows(load_csv("PIPELINE")):
            x["est_equity_check_musd"] = _f(x["est_equity_check_musd"])
            self.pipeline[x["company_id"]] = x
        self.signals = []
        for x in rows(load_csv("COMPANY_SIGNAL")):
            x["signal_date"] = _d(x["signal_date"])
            x["event_date"] = _d(x["event_date"])
            x["intermediary_id"] = _s(x["intermediary_id"])
            self.signals.append(x)
        self.signals.sort(key=lambda x: x["signal_id"])

        # indexes
        self.roles_by_org = defaultdict(list)
        self.roles_by_person = defaultdict(list)
        for x in self.roles:
            self.roles_by_org[x["org_id"]].append(x)
            self.roles_by_person[x["person_id"]].append(x)
        self.own_by_company = defaultdict(list)
        for x in self.ownership:
            self.own_by_company[x["company_id"]].append(x)
        self.signals_by_company = defaultdict(list)
        for x in self.signals:
            self.signals_by_company[x["company_id"]].append(x)
        self.parties_by_txn = defaultdict(list)
        for x in self.party:
            self.parties_by_txn[x["txn_id"]].append(x)
        self.txn_by_target = defaultdict(list)
        for x in sorted(self.txn.values(), key=lambda t: (t["close_date"], t["txn_id"])):
            self.txn_by_target[x["target_id"]].append(x)

        # Northwind and its funds (identified by name; no IDs are hard-coded)
        nw = [s for s in self.sponsor.values() if s["name"] == NORTHWIND_SPONSOR_NAME]
        if len(nw) != 1:
            raise SystemExit(f"oracle: expected exactly one sponsor named {NORTHWIND_SPONSOR_NAME!r}, found {len(nw)}")
        self.nw_id = nw[0]["sponsor_id"]
        self.nw_funds = {f["fund_id"]: f for f in self.fund.values() if f["sponsor_id"] == self.nw_id}
        self.fund_iv = self._nw_fund("IV")
        self.fund_iii = self._nw_fund("III")

    def _nw_fund(self, roman: str) -> str:
        hits = [f["fund_id"] for f in self.nw_funds.values() if re.search(rf"\bFund {roman}$", f["name"])]
        if len(hits) != 1:
            raise SystemExit(f"oracle: expected exactly one Northwind 'Fund {roman}', found {hits}")
        return hits[0]

    # names
    def org_name(self, org_id: str) -> str:
        for tbl in (self.company, self.sponsor, self.intermediary):
            if org_id in tbl:
                return tbl[org_id]["name"]
        if org_id in self.fund:
            return self.fund[org_id]["name"]
        return org_id

    def org_type(self, org_id: str) -> str:
        if org_id in self.company:
            return "company"
        if org_id in self.sponsor:
            return "sponsor"
        if org_id in self.intermediary:
            return "intermediary"
        return "unknown"

    def pname(self, pid: str) -> str:
        return self.person[pid]["full_name"] if pid in self.person else pid

    def current_roles_at(self, org_id: str, role_types: set[str] | None = None) -> list[dict]:
        return [x for x in self.roles_by_org.get(org_id, [])
                if is_current(x["start_date"], x["end_date"])
                and (role_types is None or x["role_type"] in role_types)]

    def current_role_holders(self, org_id: str) -> set[str]:
        return {x["person_id"] for x in self.current_roles_at(org_id)}

    def current_ownerships(self, company_id: str) -> list[dict]:
        return sorted([o for o in self.own_by_company.get(company_id, []) if is_current(o["start_date"], o["end_date"])],
                      key=lambda o: (o["start_date"], o["ownership_id"]))


# ----------------------------------------------------------------------------------------------
# Sector and region closures
# ----------------------------------------------------------------------------------------------
def ancestors_or_self(tree: dict, node_id: str) -> list[str]:
    out, seen, cur = [], set(), node_id
    while cur and cur in tree and cur not in seen:
        out.append(cur)
        seen.add(cur)
        cur = _s(tree[cur].get("parent_id"))
    return out


class Thesis:
    """Fund IV thesis tree with mixed-level include and exclude nodes."""

    def __init__(self, data: Data):
        self.data = data
        self.include = {}
        self.exclude = set()
        for x in data.focus:
            if x["fund_id"] != data.fund_iv:
                continue
            if x["mode"] == "include":
                self.include[x["sector_id"]] = x["margin_benchmark_pct"]
            elif x["mode"] == "exclude":
                self.exclude.add(x["sector_id"])

    def classify(self, niche: str) -> dict:
        anc = ancestors_or_self(self.data.sector, niche)
        incs = [a for a in anc if a in self.include]
        excs = [a for a in anc if a in self.exclude]
        area = incs[0] if incs else None  # nearest include node above (or at) the niche
        return {
            "in_thesis": bool(incs) and not excs,
            "area_id": area,
            "exclude_id": excs[0] if excs else None,
            "under_include": bool(incs),
        }

    def area_name(self, area_id: str | None) -> str | None:
        return None if area_id is None else self.data.sector[area_id]["name"]


def is_us(data: Data, region_id: str) -> bool:
    return "US" in ancestors_or_self(data.region, region_id)


# ----------------------------------------------------------------------------------------------
# Q-SCORE
# ----------------------------------------------------------------------------------------------
def fmt_types(types: list[str]) -> str:
    counts = defaultdict(int)
    for t in types:
        counts[t] += 1
    return ", ".join(f"{t} x{n}" if n > 1 else t for t, n in sorted(counts.items()))


def ineligibility_reasons(data: Data, thesis: Thesis, c: dict) -> list[str]:
    reasons = []
    cls = thesis.classify(c["sector_id"])
    niche = data.sector[c["sector_id"]]["name"]
    if cls["exclude_id"]:
        ex = data.sector[cls["exclude_id"]]["name"]
        if ex == niche:
            reasons.append(f"niche {niche} is excluded from the Fund IV thesis")
        else:
            reasons.append(f"niche {niche} is excluded from the Fund IV thesis (under excluded node {ex})")
    elif not cls["under_include"]:
        reasons.append(f"niche {niche} is outside the Fund IV thesis (no ancestor is a Fund IV focus node)")
    e = c["ebitda_musd"]
    if e is None:
        reasons.append("EBITDA unknown")
    elif e > EBITDA_MAX:
        reasons.append(f"EBITDA ${e:.1f}M is above the ${EBITDA_MAX:.0f}M band")
    elif e < EBITDA_MIN:
        reasons.append(f"EBITDA ${e:.1f}M is below the ${EBITDA_MIN:.0f}M band")
    if not is_us(data, c["hq_region_id"]):
        reasons.append(f"HQ {c['hq_region_id']} is outside the US")
    if c["is_public"]:
        reasons.append("publicly listed")
    for o in data.current_ownerships(c["company_id"]):
        if o["fund_id"] in data.nw_funds:
            reasons.append(f"currently owned by {data.fund[o['fund_id']]['name']} (since {o['start_date']})")
    return reasons


def score_company(data: Data, thesis: Thesis, c: dict) -> dict:
    cid = c["company_id"]
    cls = thesis.classify(c["sector_id"])
    area_id = cls["area_id"]
    bench = thesis.include[area_id]
    comps = []  # awarded components
    notes = []  # near-misses and why-not templates

    # --- Fit
    comps.append({"component": "FIT_THESIS", "points": 15,
                  "evidence": f"niche {data.sector[c['sector_id']]['name']} under Fund IV focus {thesis.area_name(area_id)}"})
    e = c["ebitda_musd"]
    if 10.0 <= e <= 30.0:
        comps.append({"component": "FIT_EBITDA", "points": 10, "evidence": f"EBITDA ${e:.1f}M in $10-30M"})
    else:
        comps.append({"component": "FIT_EBITDA", "points": 5, "evidence": f"EBITDA ${e:.1f}M at the edge of the $5-40M band"})
    rev = c["revenue_musd"]
    margin = (e / rev * 100.0) if rev else None
    if margin is not None and bench is not None and margin >= bench:
        comps.append({"component": "FIT_MARGIN", "points": 5,
                      "evidence": f"margin {margin:.1f}% vs {bench:g}% benchmark ({thesis.area_name(area_id)})"})
    elif margin is not None:
        notes.append(f"FIT_MARGIN not awarded: margin {margin:.1f}% below {bench:g}% benchmark")

    # --- R_CFO_FROM_PE (three-way temporal join)
    cfo_hit = None
    cfo_near = []
    for cfo in sorted(data.current_roles_at(cid, {"CFO"}), key=lambda x: (x["start_date"], x["role_id"])):
        if not (T_18M <= cfo["start_date"] <= T):
            continue
        lo = add_months(cfo["start_date"], -12)
        found = None
        priors = []
        for p in sorted(data.roles_by_person[cfo["person_id"]], key=lambda x: (x["start_date"], x["role_id"])):
            if p["org_id"] == cid:
                continue
            pend = eff_end(p["end_date"])
            if not (lo <= pend <= cfo["start_date"]):
                continue
            priors.append(p)
            for o in sorted(data.own_by_company.get(p["org_id"], []), key=lambda o: (o["start_date"], o["ownership_id"])):
                ov = (min(pend, eff_end(o["end_date"])) - max(p["start_date"], o["start_date"])).days
                if ov >= 1:
                    found = (p, o)
                    break
            if found:
                break
        if found:
            cfo_hit = (cfo, found[0], found[1])
            break
        cfo_near.append((cfo, priors))
    if cfo_hit:
        cfo, p, o = cfo_hit
        f = data.fund[o["fund_id"]]
        comps.append({"component": "R_CFO_FROM_PE", "points": 15,
                      "evidence": (f"CFO {data.pname(cfo['person_id'])} started {cfo['start_date']}; previously "
                                   f"{p['role_type']} at {data.org_name(p['org_id'])} {p['start_date']} to {fmt_end(p['end_date'])}, "
                                   f"owned by {f['name']} ({o['start_date']} to {fmt_end(o['end_date'])}) during that role")})
    else:
        for cfo, priors in cfo_near:
            if priors:
                pr = "; ".join(f"{data.org_name(p['org_id'])} {p['start_date']} to {fmt_end(p['end_date'])}" for p in priors)
                notes.append(f"R_CFO_FROM_PE not awarded: CFO {data.pname(cfo['person_id'])} hired {cfo['start_date']} from "
                             f"{pr}, which had no sponsor ownership during that role")
            else:
                notes.append(f"R_CFO_FROM_PE not awarded: CFO {data.pname(cfo['person_id'])} hired {cfo['start_date']} "
                             f"with no prior role ending in the 12 months before")
        for cfo in data.current_roles_at(cid, {"CFO"}):
            if cfo["start_date"] < T_18M:
                notes.append(f"R_CFO_FROM_PE not awarded: CFO {data.pname(cfo['person_id'])} in seat since {cfo['start_date']}")

    # --- R_EXIT_WINDOW
    cur_own = data.current_ownerships(cid)
    exit_hit = None
    for o in cur_own:
        f = data.fund[o["fund_id"]]
        if o["start_date"] <= T_5Y and f["vintage_year"] <= VINTAGE_CUT:
            exit_hit = o
            break
    if exit_hit:
        f = data.fund[exit_hit["fund_id"]]
        held = years((T - exit_hit["start_date"]).days)
        comps.append({"component": "R_EXIT_WINDOW", "points": 15,
                      "evidence": f"{f['name']}, vintage {f['vintage_year']}, held since {exit_hit['start_date']} = {held:.1f} years"})

    # --- R_BANKER
    sigs = data.signals_by_company.get(cid, [])
    banker = sorted([s for s in sigs if s["signal_type"] == "BANKER_ENGAGED" and T_6M <= s["signal_date"] <= T],
                    key=lambda s: (s["signal_date"], s["signal_id"]), reverse=True)
    if banker:
        s = banker[0]
        who = f" ({data.org_name(s['intermediary_id'])})" if s["intermediary_id"] else ""
        comps.append({"component": "R_BANKER", "points": 10, "evidence": f"BANKER_ENGAGED {s['signal_date']}{who}"})
    # --- R_DEBT
    debt = sorted([s for s in sigs if s["signal_type"] == "DEBT_MATURITY" and s["signal_date"] <= T
                   and s["event_date"] is not None and T < s["event_date"] <= T_P18M],
                  key=lambda s: (s["event_date"], s["signal_id"]))
    if debt:
        s = debt[0]
        comps.append({"component": "R_DEBT", "points": 10,
                      "evidence": f"DEBT_MATURITY signalled {s['signal_date']}, matures {s['event_date']}"})

    # --- R_SUCCESSION
    ceos = data.current_roles_at(cid, {"CEO"})
    pres_coo = data.current_roles_at(cid, {"President", "COO"})
    long_founders = [x for x in ceos if x["is_founder"] and x["start_date"] <= T_15Y]
    if long_founders and not pres_coo:
        x = sorted(long_founders, key=lambda x: (x["start_date"], x["role_id"]))[0]
        comps.append({"component": "R_SUCCESSION", "points": 10,
                      "evidence": (f"founder CEO {data.pname(x['person_id'])} since {x['start_date']} = "
                                   f"{years((T - x['start_date']).days):.2f} years, no current President/COO")})
    elif long_founders and pres_coo:
        pc = sorted(pres_coo, key=lambda x: (x["start_date"], x["role_id"]))[0]
        notes.append(f"R_SUCCESSION not awarded: founder CEO since {long_founders[0]['start_date']}, but a current "
                     f"{pc['role_type']} ({data.pname(pc['person_id'])}) since {pc['start_date']}")

    # --- R_NEW_DIRECTOR
    owner_sponsors = {data.fund[o["fund_id"]]["sponsor_id"] for o in cur_own}
    nd = None
    for b in sorted([x for x in data.roles_by_org.get(cid, []) if x["role_type"] == "Board" and T_12M <= x["start_date"] <= T],
                    key=lambda x: (x["start_date"], x["role_id"])):
        pid = b["person_id"]
        other_here = [x for x in data.current_roles_at(cid) if x["person_id"] == pid and x["role_type"] != "Board"]
        at_owner = [x for x in data.roles_by_person[pid] if x["org_id"] in owner_sponsors and is_current(x["start_date"], x["end_date"])]
        if other_here or at_owner:
            notes.append(f"R_NEW_DIRECTOR not counted for {data.pname(pid)} (board {b['start_date']}): "
                         + ("holds a non-Board role at the company" if other_here else "holds a current role at the owning sponsor"))
            continue
        nd = b
        break
    if nd:
        comps.append({"component": "R_NEW_DIRECTOR", "points": 5,
                      "evidence": f"board seat {data.pname(nd['person_id'])} ({nd['title']}) since {nd['start_date']}"})

    # --- A_CRM
    holders = data.current_role_holders(cid)
    crm_hits = sorted([x for x in data.crm if x["sentiment"] == "positive" and T_24M <= x["interaction_date"] <= T
                       and (x["counterparty_org_id"] == cid or (x["counterparty_person_id"] in holders))],
                      key=lambda x: (x["interaction_date"], x["interaction_id"]), reverse=True)
    if crm_hits:
        x = crm_hits[0]
        lvl = (f"person-level with {data.pname(x['counterparty_person_id'])}" if x["counterparty_person_id"]
               else "org-level")
        comps.append({"component": "A_CRM", "points": 10,
                      "evidence": f"positive {lvl} {x['channel']} {x['interaction_date']} by {data.pname(x['our_person_id'])}"})
    else:
        touch = sorted([x for x in data.crm if x["counterparty_org_id"] == cid or x["counterparty_person_id"] in holders],
                       key=lambda x: (x["interaction_date"], x["interaction_id"]), reverse=True)
        if touch:
            x = touch[0]
            notes.append(f"A_CRM not awarded: last interaction {x['interaction_date']} {x['sentiment']}"
                         + ("" if x["interaction_date"] >= T_24M else ", outside 24 months"))

    fit = sum(x["points"] for x in comps if x["component"].startswith("FIT_"))
    readiness_raw = sum(x["points"] for x in comps if x["component"].startswith("R_"))
    readiness = min(READINESS_CAP, readiness_raw)
    access = sum(x["points"] for x in comps if x["component"].startswith("A_"))
    score = fit + readiness + access

    # why-not templates (a) and (b)
    in12 = [s for s in sigs if T_12M <= s["signal_date"] <= T]
    has_banker = any(x["component"] == "R_BANKER" for x in comps)
    has_debt = any(x["component"] == "R_DEBT" for x in comps)
    if len(in12) >= 3 and not has_banker and not has_debt:
        notes.append(f"{len(in12)} signals in the last 12 months, none a scored readiness type "
                     f"({fmt_types([s['signal_type'] for s in in12])})")
    if cur_own and not exit_hit:
        o = cur_own[0]
        notes.append(f"sponsor-owned since {o['start_date']} ({years((T - o['start_date']).days):.1f} years); exit window "
                     f"needs 5+ years held and fund vintage <= {VINTAGE_CUT}")

    not_in_crm = (cid not in data.pipeline) and not any(
        x["counterparty_org_id"] == cid or x["counterparty_person_id"] in holders for x in data.crm)

    return {
        "company_id": cid,
        "name": c["name"],
        "niche": data.sector[c["sector_id"]]["name"],
        "thesis_area": thesis.area_name(area_id),
        "thesis_area_id": area_id,
        "ebitda_musd": e,
        "revenue_musd": rev,
        "margin_pct": r(margin, 2),
        "fit": fit,
        "readiness": readiness,
        "readiness_uncapped": readiness_raw,
        "access": access,
        "score": score,
        "tier": tier_of(score),
        "components": comps,
        "notes": notes,
        "not_in_crm": not_in_crm,
        "in_pipeline": cid in data.pipeline,
        "why": "; ".join(f"{x['component']} {x['points']} ({x['evidence']})" for x in comps),
    }


def tier_of(score: int) -> str:
    return "A" if score >= TIER_A else ("B" if score >= TIER_B else "C")


def rank_key(x: dict):
    return (-x["score"], -x["readiness"], -x["fit"], x["name"])


def q_score(data: Data, thesis: Thesis) -> dict:
    scored, ineligible = [], []
    for cid in sorted(data.company):
        c = data.company[cid]
        reasons = ineligibility_reasons(data, thesis, c)
        if reasons:
            cls = thesis.classify(c["sector_id"])
            ineligible.append({"company_id": cid, "name": c["name"], "niche": data.sector[c["sector_id"]]["name"],
                               "under_fund_iv_focus": cls["under_include"], "reasons": reasons})
        else:
            scored.append(score_company(data, thesis, c))
    scored.sort(key=rank_key)
    for i, x in enumerate(scored, 1):
        x["rank"] = i
    tier_a = [x for x in scored if x["tier"] == "A"]
    return {
        "question": "Which companies fit the Fund IV thesis and look ready to transact in the next 12-18 months, and why each one?",
        "answer": {
            "tier_a": [{k: x[k] for k in ("rank", "company_id", "name", "score", "fit", "readiness", "access", "tier",
                                          "not_in_crm", "thesis_area", "niche", "components", "notes", "why")} for x in tier_a],
            "tier_a_ids": [x["company_id"] for x in tier_a],
            "not_in_crm_tier_a": [x["name"] for x in tier_a if x["not_in_crm"]],
        },
        "all_scored": [{k: x[k] for k in ("rank", "company_id", "name", "score", "fit", "readiness", "access", "tier",
                                          "not_in_crm", "thesis_area", "niche", "components", "notes")} for x in scored],
        "ineligible": ineligible,
        "_scored_index": {x["company_id"]: x for x in scored},
    }


# ----------------------------------------------------------------------------------------------
# Knows (Q-PATH rules)
# ----------------------------------------------------------------------------------------------
def our_seeds(data: Data) -> list[str]:
    return sorted({x["person_id"] for x in data.current_roles_at(data.nw_id, {"Deal Team", "Operating Partner"})})


def build_knows(data: Data, seeds: set[str]) -> dict:
    ev = defaultdict(list)  # (a, b) with a < b -> evidence list

    def add(a, b, item):
        if a == b:
            return
        key = (a, b) if a < b else (b, a)
        ev[key].append(item)

    # K1 tenure overlap (same org, >= 365 days, open end = T)
    for org_id in sorted(data.roles_by_org):
        rs = data.roles_by_org[org_id]
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                if a["person_id"] == b["person_id"]:
                    continue
                s = max(a["start_date"], b["start_date"])
                e = min(eff_end(a["end_date"]), eff_end(b["end_date"]))
                days = (e - s).days
                if days < 365:
                    continue
                strength = recency(e) * min(1.0, 0.4 + 0.15 * days / 365.25)
                both_board = a["role_type"] == "Board" and b["role_type"] == "Board"
                open_end = a["end_date"] is None and b["end_date"] is None
                label = "board co-service" if both_board else "tenure overlap"
                add(a["person_id"], b["person_id"], {
                    "type": "K1", "label": label, "strength": strength,
                    "org_id": org_id, "org": data.org_name(org_id),
                    "overlap_start": s.isoformat(), "overlap_end": "present" if open_end else e.isoformat(),
                    "overlap_days": days, "overlap_years": round(years(days), 2), "recency": recency(e),
                    "roles": sorted([f"{data.pname(a['person_id'])} {a['role_type']} {a['start_date']} to {fmt_end(a['end_date'])}",
                                     f"{data.pname(b['person_id'])} {b['role_type']} {b['start_date']} to {fmt_end(b['end_date'])}"]),
                    "text": (f"K1 {label}: {data.org_name(org_id)}, {s} to {'present' if open_end else e}, "
                             f"{years(days):.2f} years, recency {recency(e)} -> {strength:.3f}"),
                })

    # K2 deal co-participation
    for tid in sorted(data.txn):
        t = data.txn[tid]
        leads = sorted({(p["lead_person_id"], p["party_role"], p["org_id"]) for p in data.parties_by_txn[tid] if p["lead_person_id"]})
        strength = 0.7 * recency(t["close_date"])
        desc = (f"{t['structure']} of {data.org_name(t['target_id'])} closed {t['close_date']}")
        for i in range(len(leads)):
            for j in range(i + 1, len(leads)):
                if leads[i][0] == leads[j][0]:
                    continue
                add(leads[i][0], leads[j][0], {
                    "type": "K2", "label": "deal co-participation (both lead persons)", "strength": strength, "txn_id": tid,
                    "text": (f"K2: both lead persons on {desc} ({leads[i][1]} {data.org_name(leads[i][2])}; "
                             f"{leads[j][1]} {data.org_name(leads[j][2])}) -> {strength:.3f}")})
        execs = [x for x in data.roles_by_org.get(t["target_id"], []) if x["role_type"] in {"CEO", "CFO"}
                 and x["start_date"] <= t["close_date"] <= eff_end(x["end_date"])]
        for (lp, lrole, lorg) in leads:
            for x in execs:
                if x["person_id"] == lp:
                    continue
                add(lp, x["person_id"], {
                    "type": "K2", "label": "deal co-participation (lead person and target executive)", "strength": strength,
                    "txn_id": tid,
                    "text": (f"K2: {data.pname(lp)} was lead {lrole} ({data.org_name(lorg)}) on {desc} while "
                             f"{data.pname(x['person_id'])} was {x['role_type']} -> {strength:.3f}")})

    # K3 positive person-level CRM by a seed, in [T-24m, T]
    cnt = defaultdict(list)
    for x in data.crm:
        if (x["sentiment"] == "positive" and x["our_person_id"] in seeds and x["counterparty_person_id"]
                and T_24M <= x["interaction_date"] <= T):
            cnt[(x["our_person_id"], x["counterparty_person_id"])].append(x["interaction_date"])
    for (a, b), ds in sorted(cnt.items()):
        n = len(ds)
        strength = 0.6 if n == 1 else (0.8 if n == 2 else 1.0)
        add(a, b, {"type": "K3", "label": "positive CRM", "strength": strength, "count": n,
                   "first": min(ds).isoformat(), "last": max(ds).isoformat(),
                   "text": f"K3: {n} positive meetings {min(ds)} to {max(ds)} -> {strength:.2f}"})

    knows = {}
    for key in sorted(ev):
        items = sorted(ev[key], key=lambda i: (-i["strength"], i["type"], i["text"]))
        knows[key] = {"strength": items[0]["strength"], "evidence": items}
    return knows


def knows_graph(data: Data, knows: dict) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(sorted(data.person))  # node_concept = Person
    for (a, b) in sorted(knows):
        g.add_edge(a, b, strength=knows[(a, b)]["strength"])
    return g


def bfs_from_set(g: nx.Graph, sources) -> dict:
    srcs = sorted(s for s in sources if s in g)
    if not srcs:
        return {}
    return dict(nx.multi_source_dijkstra_path_length(g, srcs))


def shortest_seed_paths(g: nx.Graph, dseed: dict, target: str) -> list[list[str]]:
    """All shortest paths from the seed set to target, via the layered identity d(s,m)+d(m,t)=d(s,t)."""
    L = dseed.get(target)
    if L is None:
        return []
    out = []

    def back(node, acc):
        k = dseed[node]
        if k == 0:
            out.append(list(reversed(acc)))
            return
        for nb in sorted(g.neighbors(node)):
            if dseed.get(nb) == k - 1:
                back(nb, acc + [nb])

    back(target, [target])
    return sorted(out)


def path_strength(knows: dict, path: list[str]) -> float:
    s = 1.0
    for a, b in zip(path, path[1:]):
        s *= knows[(a, b) if a < b else (b, a)]["strength"]
    return s


def describe_path(data: Data, knows: dict, path: list[str]) -> dict:
    hops = []
    for a, b in zip(path, path[1:]):
        k = knows[(a, b) if a < b else (b, a)]
        hops.append({"from_id": a, "from": data.pname(a), "to_id": b, "to": data.pname(b),
                     "strength": r(k["strength"], 4),
                     "evidence": [{kk: vv for kk, vv in e.items() if kk != "strength"} | {"strength": r(e["strength"], 4)}
                                  for e in k["evidence"]]})
    s = path_strength(knows, path)
    text = data.pname(path[0])
    for h in hops:
        text += f" -[{h['evidence'][0]['text']}]- {h['to']}"
    return {"persons": [data.pname(p) for p in path], "person_ids": path, "hops": len(path) - 1,
            "strength": r(s, 4), "hop_detail": hops, "text": text}


def decision_makers(data: Data, cid: str) -> list[dict]:
    out = []
    for x in sorted(data.current_roles_at(cid, {"CEO"}), key=lambda x: (x["start_date"], x["person_id"])):
        out.append({"person_id": x["person_id"], "name": data.pname(x["person_id"]), "kind": "CEO", "via": None})
    for o in data.current_ownerships(cid):
        sp = data.fund[o["fund_id"]]["sponsor_id"]
        board = {x["person_id"] for x in data.current_roles_at(cid, {"Board"})}
        dealt = {x["person_id"] for x in data.current_roles_at(sp, {"Deal Team"})}
        for pid in sorted(board & dealt, key=lambda p: data.pname(p)):
            if any(d["person_id"] == pid and d["kind"] == "OWNER_DESIGNEE" for d in out):
                continue
            out.append({"person_id": pid, "name": data.pname(pid), "kind": "OWNER_DESIGNEE",
                        "via": f"{data.fund[o['fund_id']]['name']} ({data.org_name(sp)})"})
    return out


def closest_intermediary(data: Data, cid: str) -> dict | None:
    ties = []
    for s in data.signals_by_company.get(cid, []):
        if s["signal_type"] == "BANKER_ENGAGED" and s["intermediary_id"] and T_5Y <= s["signal_date"] <= T:
            ties.append((s["signal_date"], s["intermediary_id"], f"BANKER_ENGAGED {s['signal_date']}"))
    for t in data.txn_by_target.get(cid, []):
        if not (T_5Y <= t["close_date"] <= T):
            continue
        for p in data.parties_by_txn[t["txn_id"]]:
            if p["party_role"] in ADVISOR_ROLES and p["org_id"] in data.intermediary:
                ties.append((t["close_date"], p["org_id"], f"{p['party_role']} on the {t['close_date']} {t['structure']}"))
    if not ties:
        return None
    by_int = defaultdict(list)
    for d, i, txt in ties:
        by_int[i].append((d, txt))
    best = sorted(by_int, key=lambda i: (-max(d for d, _ in by_int[i]).toordinal(), data.org_name(i)))
    win = best[0]
    return {"intermediary_id": win, "name": data.org_name(win),
            "most_recent_tie": max(d for d, _ in by_int[win]).isoformat(),
            "evidence": [txt for d, txt in sorted(by_int[win], reverse=True)],
            "all_intermediaries_with_ties": [data.org_name(i) for i in best]}


def q_path(data: Data, scored: list[dict], knows: dict, g: nx.Graph, seeds: list[str], dseed: dict) -> dict:
    top3 = scored[:3]
    per_seed = {s: dict(nx.single_source_shortest_path_length(g, s)) for s in seeds}
    rows_out, targets, invariants = [], [], []
    for t in top3:
        cid = t["company_id"]
        dms = decision_makers(data, cid)
        trows = []
        for dm in dms:
            pid = dm["person_id"]
            L = dseed.get(pid)
            paths = shortest_seed_paths(g, dseed, pid) if (L is not None and L <= 3) else []
            # cross-check by simple-path enumeration (cutoff 3) from every seed
            enum = set()
            if L is not None and L <= 3:
                for s in seeds:
                    if s == pid:
                        enum.add((s,))
                        continue
                    for p in nx.all_simple_paths(g, s, pid, cutoff=3):
                        if len(p) - 1 == L:
                            enum.add(tuple(p))
            ranked = sorted(paths, key=lambda p: (-round(path_strength(knows, p), 9), [data.pname(x) for x in p]))
            within = L is not None and L <= 3
            row = {"target_rank": t["rank"], "target_id": cid, "target": t["name"],
                   "decision_maker_id": pid, "decision_maker": dm["name"], "kind": dm["kind"], "owner_via": dm["via"],
                   "hops": L, "within_3_hops": within,
                   "best_path": describe_path(data, knows, ranked[0]) if within and ranked else None,
                   "alternates": [describe_path(data, knows, p) for p in ranked[1:3]] if within else [],
                   "path_strength": r(path_strength(knows, ranked[0]), 4) if within and ranked else None,
                   "message": None}
            if not within:
                row["message"] = ("No path within 3 hops" + (f" (seed distance {L})" if L is not None else " (unreachable)"))
            trows.append(row)
            invariants.append({
                "target": t["name"], "decision_maker": dm["name"], "kind": dm["kind"], "seed_distance": L,
                "n_shortest_paths_bfs": len(paths), "n_shortest_paths_enum": len(enum),
                "bfs_equals_enumeration": set(map(tuple, paths)) == enum,
                "neighbors_at_seed_distance_L_minus_1": (sorted(data.pname(n) for n in g.neighbors(pid) if L is not None and dseed.get(n) == L - 1)
                                                         if L is not None else []),
                "all_neighbors_with_seed_distance": sorted([[data.pname(n), dseed.get(n)] for n in g.neighbors(pid)],
                                                           key=lambda x: (x[1] if x[1] is not None else 99, x[0])),
                "nearest_seeds": sorted(data.pname(s) for s in seeds if per_seed[s].get(pid) == L) if L is not None else [],
            })
        cold = all(not x["within_3_hops"] for x in trows)
        ci = closest_intermediary(data, cid)
        targets.append({"target_rank": t["rank"], "target_id": cid, "target": t["name"], "cold": cold,
                        "closest_intermediary": ci if cold else None,
                        "closest_intermediary_any": ci})
        rows_out.extend(trows)
    seeds_adjacent_to_ceos = {}
    for t in top3:
        for dm in decision_makers(data, t["company_id"]):
            if dm["kind"] == "CEO":
                seeds_adjacent_to_ceos[dm["name"]] = sorted(data.pname(s) for s in seeds if g.has_edge(s, dm["person_id"]))
    return {
        "question": "For our top three, what is our warmest path to each CEO, and through whom? And if sponsor-owned, do we know the owner's deal partner?",
        "answer": {"rows": rows_out, "targets": targets},
        "diagnostics": {
            "seeds": [{"person_id": s, "name": data.pname(s)} for s in seeds],
            "knows_graph": {"num_nodes": g.number_of_nodes(), "num_edges": g.number_of_edges()},
            "path_invariants": invariants,
            "seeds_adjacent_to_top3_ceos": seeds_adjacent_to_ceos,
        },
    }


# ----------------------------------------------------------------------------------------------
# Q-FLOW
# ----------------------------------------------------------------------------------------------
def pagerank_power(g: nx.Graph, alpha=0.85, tol=1e-06, max_iter=200) -> dict:
    """Unweighted PageRank by power iteration (networkx reference algorithm; scipy is not installed).

    Uniform start and teleport, dangling mass spread uniformly, stop when L1 change < N * tol.
    Nodes are visited in sorted order so the floating-point sums are deterministic.
    """
    nodes = sorted(g.nodes)
    n = len(nodes)
    if n == 0:
        return {}
    nbrs = {u: sorted(g.neighbors(u)) for u in nodes}
    x = {u: 1.0 / n for u in nodes}
    for _ in range(max_iter):
        last = x
        x = {u: 0.0 for u in nodes}
        dangle = alpha * sum(last[u] for u in nodes if not nbrs[u])
        for u in nodes:
            if nbrs[u]:
                share = alpha * last[u] / len(nbrs[u])
                for v in nbrs[u]:
                    x[v] += share
        for u in nodes:
            x[u] += dangle / n + (1.0 - alpha) / n
        if sum(abs(x[u] - last[u]) for u in nodes) < n * tol:
            return x
    raise RuntimeError("pagerank did not converge")


def party_node(data: Data, p: dict) -> str:
    if p["org_type"] == "sponsor" and p["fund_id"] and p["fund_id"] in data.fund:
        return data.fund[p["fund_id"]]["sponsor_id"]  # a fund maps to its sponsor
    return p["org_id"]


def q_flow(data: Data, thesis: Thesis) -> dict:
    in_scope = []
    dropped_by_exclude = []
    for tid in sorted(data.txn):
        t = data.txn[tid]
        if not (T_5Y <= t["close_date"] <= T):
            continue
        cls = thesis.classify(data.company[t["target_id"]]["sector_id"])
        if cls["in_thesis"]:
            in_scope.append(t)
        elif cls["under_include"]:
            dropped_by_exclude.append(tid)
    edges = set()
    edge_txns = defaultdict(set)
    int_deals = defaultdict(set)
    for t in in_scope:
        ps = data.parties_by_txn[t["txn_id"]]
        tgt = t["target_id"]
        adv = sorted({party_node(data, p) for p in ps if p["party_role"] in ADVISOR_ROLES})
        buy = sorted({party_node(data, p) for p in ps if p["party_role"] == "buyer"})
        sel = sorted({party_node(data, p) for p in ps if p["party_role"] == "seller"})
        own = sorted({party_node(data, p) for p in ps if p["party_role"] == "owner"})
        pairs = []
        for a in adv:
            pairs.append((a, tgt))
            pairs += [(a, b) for b in buy] + [(a, s) for s in sel] + [(a, o) for o in own]
            if a in data.intermediary:
                int_deals[a].add(t["txn_id"])
        pairs += [(b, tgt) for b in buy] + [(o, tgt) for o in own]  # owner stands in for buyer in a recap
        for u, v in pairs:
            if u == v:
                continue
            e = (u, v) if u < v else (v, u)
            edges.add(e)
            edge_txns[e].add(t["txn_id"])
    g = nx.Graph()
    g.add_edges_from(sorted(edges))  # nodes = edge endpoints
    n_nodes, n_edges = g.number_of_nodes(), g.number_of_edges()
    assert n_nodes <= 16000, "num_pivots=16000 must cover |V|"
    bc = nx.betweenness_centrality(g, normalized=False)
    pr = pagerank_power(g, alpha=0.85, tol=1e-06, max_iter=200)

    # touchpoints over ALL intermediary rows
    tp = {}
    tp_split = {}
    for i in sorted(data.intermediary):
        holders = data.current_role_holders(i)
        hits = [x for x in data.crm if T_24M <= x["interaction_date"] <= T
                and (x["counterparty_org_id"] == i or x["counterparty_person_id"] in holders)]
        tp[i] = len(hits)
        tp_split[i] = {"person_level": sum(1 for x in hits if x["counterparty_person_id"]),
                       "org_level": sum(1 for x in hits if not x["counterparty_person_id"]),
                       "positive": sum(1 for x in hits if x["sentiment"] == "positive")}
    n_int_all = len(data.intermediary)
    sorted_tp = sorted(tp.values())
    q1_pos = math.ceil(0.25 * n_int_all)
    q1 = sorted_tp[q1_pos - 1]

    ints = sorted([n for n in g.nodes if n in data.intermediary], key=lambda i: (-round(bc[i], 9), data.org_name(i)))
    n_int = len(ints)
    k = math.ceil(0.10 * n_int)
    all_5y = defaultdict(set)
    for t in data.txn.values():
        if T_5Y <= t["close_date"] <= T:
            for p in data.parties_by_txn[t["txn_id"]]:
                if p["party_role"] in ADVISOR_ROLES and p["org_id"] in data.intermediary:
                    all_5y[p["org_id"]].add(t["txn_id"])
    league = []
    for pos, i in enumerate(ints, 1):
        comp_rank = 1 + sum(1 for j in ints if round(bc[j], 9) > round(bc[i], 9))
        nbr_sponsors = sorted({data.org_name(n) for n in g.neighbors(i) if n in data.sponsor})
        gap = pos <= k and tp[i] <= q1
        league.append({
            "rank": pos, "rank_competition": comp_rank, "intermediary_id": i, "name": data.org_name(i),
            "betweenness": r(bc[i]), "pagerank": r(pr[i]), "degree": g.degree(i),
            "deals_in_window_thesis": len(int_deals[i]), "deals_5y_all_sectors": len(all_5y[i]),
            "touchpoints_24m": tp[i], "touchpoints_detail": tp_split[i],
            "adjacent_sponsors": nbr_sponsors, "top_decile": pos <= k, "coverage_gap": gap,
            "why": (f"betweenness {bc[i]:.2f} (rank {pos} of {n_int} intermediaries), {len(int_deals[i])} thesis deals in 5y, "
                    f"{tp[i]} touchpoints in 24m (Q1 = {q1})" + ("; COVERAGE GAP: top decile and touchpoints <= Q1" if gap else "")),
        })
    return {
        "question": "Which intermediaries actually bridge deal flow between founders and sponsors in our sectors, and where is our coverage weakest?",
        "answer": {
            "top5": league[:5],
            "coverage_gaps": [{"intermediary_id": x["intermediary_id"], "name": x["name"], "rank": x["rank"],
                               "touchpoints_24m": x["touchpoints_24m"]} for x in league if x["coverage_gap"]],
        },
        "intermediary_ranking": league,
        "diagnostics": {
            "transactions_in_scope": len(in_scope),
            "transactions_dropped_by_exclude_node": dropped_by_exclude, "num_nodes": n_nodes, "num_edges": n_edges,
            "n_intermediaries_in_graph": n_int, "top_decile_size": k,
            "n_intermediaries_total": n_int_all, "q1_position": q1_pos, "q1_touchpoints": q1,
            "touchpoint_distribution": {str(v): sorted_tp.count(v) for v in sorted(set(sorted_tp))},
            "betweenness": "networkx exact Brandes, normalized=False (unordered pairs, undirected)",
            "pagerank": "power-iteration pagerank (networkx reference algorithm), alpha=0.85 tol=1e-6 max_iter=200",
        },
    }


# ----------------------------------------------------------------------------------------------
# Q-CONFLICT
# ----------------------------------------------------------------------------------------------
def commercial_graph(data: Data):
    g = nx.Graph()
    g.add_nodes_from(sorted(data.company))  # node_concept = Company
    lk = defaultdict(list)
    for x in data.links:
        u, v = x["supplier_id"], x["customer_id"]
        if u == v:
            continue
        g.add_edge(u, v)
        lk[(u, v) if u < v else (v, u)].append(x)
    return g, lk


def nw_holdings(data: Data) -> list[dict]:
    out = []
    for o in data.ownership:
        if o["fund_id"] in data.nw_funds and is_current(o["start_date"], o["end_date"]):
            out.append(o)
    return sorted(out, key=lambda o: (o["company_id"], o["fund_id"], o["ownership_id"]))


def link_phrase(data: Data, a: str, b: str, lk: dict) -> list[str]:
    """Describe the link(s) between a and b from a's point of view."""
    out = []
    for x in lk[(a, b) if a < b else (b, a)]:
        if x["supplier_id"] == a:
            out.append(f"{data.org_name(a)} supplies {data.org_name(b)}")
        else:
            out.append(f"{data.org_name(a)} buys from {data.org_name(b)}")
    return out


def q_conflict(data: Data, thesis: Thesis, scored_index: dict) -> dict:
    # The subject is the target "we are preparing an IOI" on: the unique PIPELINE row with stage "IOI prep".
    # R05 may rename companies, so the Tier-1 prompt name is only a secondary lookup.
    ioi = sorted(c for c, p in data.pipeline.items() if p["stage"] == "IOI prep")
    by_name = sorted(c for c in data.company if data.company[c]["name"] == CONFLICT_SUBJECT_NAME)
    if len(ioi) == 1:
        subj, subject_source = ioi[0], "unique PIPELINE row with stage IOI prep"
    elif len(by_name) == 1:
        subj, subject_source = by_name[0], f"company name {CONFLICT_SUBJECT_NAME!r}"
    else:
        raise SystemExit(f"oracle: Q-CONFLICT subject not identifiable (IOI prep rows {ioi}, name hits {by_name})")
    sx = scored_index.get(subj)
    banker_ints = sorted({data.org_name(s["intermediary_id"]) for s in data.signals_by_company.get(subj, [])
                          if s["signal_type"] == "BANKER_ENGAGED" and s["intermediary_id"] and T_6M <= s["signal_date"] <= T})
    subject_checks = {"q_score_rank": sx["rank"] if sx else None, "q_score_tier": sx["tier"] if sx else None,
                      "banker_engaged_by": banker_ints, "name_matches_prompt": data.company[subj]["name"] == CONFLICT_SUBJECT_NAME}
    g, lk = commercial_graph(data)
    d = dict(nx.single_source_shortest_path_length(g, subj))
    holds = nw_holdings(data)
    exposures = []
    for o in holds:
        cid = o["company_id"]
        dist = d.get(cid)
        if dist is None or dist > 2 or cid == subj:
            continue
        f = data.fund[o["fund_id"]]
        if dist == 1:
            kind = "CONFLICT - cross-fund review" if o["fund_id"] != data.fund_iv else "SAME-FUND LINK"
            evid = []
            for x in lk[(subj, cid) if subj < cid else (cid, subj)]:
                evid.append(f"{link_phrase(data, subj, cid, {(subj, cid) if subj < cid else (cid, subj): [x]})[0]} "
                            f"(COMMERCIAL_LINK {x['link_id']}: supplier {data.org_name(x['supplier_id'])}, customer "
                            f"{data.org_name(x['customer_id'])}, {x['value_band']})")
            sub = None
        else:
            kind = "SHARED COUNTERPARTY (informational)"
            evid, subs = [], set()
            for m in sorted(set(g.neighbors(subj)) & set(g.neighbors(cid)), key=lambda m: data.org_name(m)):
                l1 = lk[(subj, m) if subj < m else (m, subj)]
                l2 = lk[(m, cid) if m < cid else (cid, m)]
                subj_sup = any(x["supplier_id"] == subj for x in l1)
                subj_cus = any(x["customer_id"] == subj for x in l1)
                hold_sup = any(x["supplier_id"] == cid for x in l2)
                hold_cus = any(x["customer_id"] == cid for x in l2)
                if subj_sup and hold_sup:
                    subs.add("shared customer")
                if subj_cus and hold_cus:
                    subs.add("shared supplier")
                if (subj_sup and hold_cus) or (subj_cus and hold_sup):
                    subs.add("supply chain (2 links)")
                evid.append("; ".join(link_phrase(data, subj, m, lk)) + "; " + "; ".join(link_phrase(data, m, cid, lk)))
            sub = sorted(subs)
        exposures.append({
            "company_id": cid, "name": data.company[cid]["name"], "fund_id": o["fund_id"], "fund": f["name"],
            "held_since": o["start_date"].isoformat(), "commercial_distance": dist, "kind": kind,
            "subkind": sub, "evidence": evid})
    exposures.sort(key=lambda x: (x["commercial_distance"], x["name"], x["fund"]))
    for i, x in enumerate(exposures, 1):
        x["row"] = i

    # Concentration (Fund IV, thesis areas)
    fiv = data.fund[data.fund_iv]
    size = fiv["size_musd"]
    guide = fiv["area_guideline_pct"]
    areas = {a: 0.0 for a in thesis.include}
    holdings_iv = []
    outside = 0.0
    for o in holds:
        if o["fund_id"] != data.fund_iv:
            continue
        c = data.company[o["company_id"]]
        a = thesis.classify(c["sector_id"])["area_id"]
        eq = o["equity_invested_musd"] or 0.0
        holdings_iv.append({"company_id": c["company_id"], "name": c["name"], "thesis_area": thesis.area_name(a),
                            "niche": data.sector[c["sector_id"]]["name"], "since": o["start_date"].isoformat(),
                            "equity_musd": eq, "pct_of_fund": r(eq / size * 100, 4)})
        if a in areas:
            areas[a] += eq
        else:
            outside += eq
    holdings_iv.sort(key=lambda x: (-x["equity_musd"], x["name"]))
    subj_area = thesis.classify(data.company[subj]["sector_id"])["area_id"]
    check = (data.pipeline.get(subj) or {}).get("est_equity_check_musd") or 0.0
    conc = []
    for a in sorted(areas, key=lambda a: (-areas[a], thesis.area_name(a))):
        before = areas[a]
        after = before + (check if a == subj_area else 0.0)
        cap = guide / 100.0 * size if guide is not None else None
        conc.append({
            "thesis_area_id": a, "thesis_area": thesis.area_name(a),
            "before_musd": r(before, 2), "before_pct": r(before / size * 100, 4),
            "with_subject_musd": r(after, 2), "with_subject_pct": r(after / size * 100, 4),
            "guideline_pct": guide, "guideline_musd": r(cap, 2),
            "breach": (after / size * 100 > guide) if guide is not None else False,
            "headroom_musd": r(cap - before, 2) if cap is not None else None,
            "over_by_musd": r(after - cap, 2) if cap is not None and after > cap else None,
            "subject_area": a == subj_area,
        })
    return {
        "question": "Before we bid on Keystone, does it conflict with anything we own, and would it push Fund IV over its sector concentration guideline?",
        "answer": {
            "subject": {"company_id": subj, "name": data.company[subj]["name"], "thesis_area": thesis.area_name(subj_area),
                        "est_equity_check_musd": check, "identified_by": subject_source, "checks": subject_checks},
            "exposures": exposures,
            "concentration": conc,
            "breaches": [x["thesis_area"] for x in conc if x["breach"]],
        },
        "diagnostics": {
            "commercial_graph": {"num_nodes": g.number_of_nodes(), "num_edges": g.number_of_edges()},
            "fund_iv": {"fund_id": data.fund_iv, "name": fiv["name"], "size_musd": size, "area_guideline_pct": guide,
                        "holdings": holdings_iv, "outside_thesis_musd": outside,
                        "total_deployed_musd": r(sum(h["equity_musd"] for h in holdings_iv), 2)},
            "current_northwind_holdings_distance": sorted(
                [{"name": data.company[o["company_id"]]["name"], "fund": data.fund[o["fund_id"]]["name"],
                  "commercial_distance": d.get(o["company_id"])} for o in holds],
                key=lambda x: (x["commercial_distance"] if x["commercial_distance"] is not None else 99, x["name"])),
            "subject_neighbors": sorted(
                [{"name": data.org_name(n), "relation": link_phrase(data, subj, n, lk)} for n in g.neighbors(subj)],
                key=lambda x: x["name"]),
        },
    }


# ----------------------------------------------------------------------------------------------
# FINALE
# ----------------------------------------------------------------------------------------------
def fund_holding_links(data: Data, cid: str, fund_id: str) -> list[str]:
    held = {o["company_id"]: o for o in nw_holdings(data) if o["fund_id"] == fund_id}
    out = []
    for x in data.links:
        other = x["customer_id"] if x["supplier_id"] == cid else (x["supplier_id"] if x["customer_id"] == cid else None)
        if other is None or other not in held:
            continue
        o = held[other]
        verb = "supplies" if x["supplier_id"] == cid else "buys from"
        out.append(f"{data.company[cid]['name']} {verb} {data.company[other]['name']} "
                   f"({data.fund[fund_id]['name']} since {o['start_date']})")
    return sorted(out)


def finale(data: Data, scored: list[dict], dseed: dict, g: nx.Graph, knows: dict) -> dict:
    rows_out = []
    for x in scored:
        cid = x["company_id"]
        ceos = [y["person_id"] for y in data.current_roles_at(cid, {"CEO"})]
        ds = [dseed[p] for p in ceos if p in dseed]
        ceo_d = min(ds) if ds else None
        warm = ceo_d is not None and ceo_d <= 2
        conflicts = fund_holding_links(data, cid, data.fund_iii)
        new_score = x["score"] + (10 if warm else 0)
        warm_ev = None
        if warm:
            best_ceo = sorted([p for p in ceos if dseed.get(p) == ceo_d])[0]
            paths = sorted(shortest_seed_paths(g, dseed, best_ceo),
                           key=lambda p: (-round(path_strength(knows, p), 9), [data.pname(q) for q in p]))
            warm_ev = describe_path(data, knows, paths[0])
        rows_out.append({
            "company_id": cid, "name": x["name"], "act1_rank": x["rank"], "act1_score": x["score"], "act1_tier": x["tier"],
            "fit": x["fit"], "readiness": x["readiness"], "access": x["access"] + (10 if warm else 0),
            "ceo_seed_distance": ceo_d, "A_WARM_PATH": 10 if warm else 0,
            "warm_path": warm_ev, "score": new_score, "tier": tier_of(new_score),
            "conflict": bool(conflicts), "conflict_flag": "Conflict - cross-fund review" if conflicts else None,
            "conflict_evidence": conflicts,
        })
    rows_out.sort(key=rank_key)
    tier_a = [y for y in rows_out if y["tier"] == "A" and not y["conflict"]]
    for i, y in enumerate(tier_a, 1):
        y["rank"] = i
    act1_a = {x["company_id"] for x in scored if x["tier"] == "A"}
    for y in tier_a:
        ch = []
        if y["A_WARM_PATH"]:
            ch.append(f"+10 warm path (CEO at {y['ceo_seed_distance']} hops)")
        if y["company_id"] not in act1_a:
            ch.append(f"rises from Tier {y['act1_tier']} ({y['act1_score']}) into Tier A")
        elif y["rank"] != y["act1_rank"]:
            ch.append(f"moves from #{y['act1_rank']} to #{y['rank']}")
        if not y["A_WARM_PATH"]:
            ch.insert(0, "no score change" + (f" (CEO at {y['ceo_seed_distance']} hops)" if y["ceo_seed_distance"] is not None
                                              else " (CEO unreachable from seeds)"))
        y["change"] = "; ".join(ch)
    flagged = [y for y in rows_out if y["conflict"]]
    keep = ("rank", "company_id", "name", "score", "fit", "readiness", "access", "A_WARM_PATH", "ceo_seed_distance",
            "act1_rank", "act1_score", "act1_tier", "change", "warm_path")
    return {
        "question": "Add +10 access for a CEO within two Knows hops of a seed; flag Fund III customers/suppliers as conflicts and take them off Tier A.",
        "answer": {
            "tier_a": [{k: y[k] for k in keep} for y in tier_a],
            "tier_a_ids": [y["company_id"] for y in tier_a],
            "flagged": [{"company_id": y["company_id"], "name": y["name"], "score": y["score"], "tier_by_score": y["tier"],
                         "flag": y["conflict_flag"], "evidence": y["conflict_evidence"]} for y in flagged],
            "flagged_off_tier_a": [{"company_id": y["company_id"], "name": y["name"], "score": y["score"],
                                    "act1_rank": y["act1_rank"], "flag": y["conflict_flag"], "evidence": y["conflict_evidence"]}
                                   for y in flagged if y["tier"] == "A"],
        },
        "_rows": rows_out,
    }


def guards(data: Data, scored: list[dict], dseed: dict, g: nx.Graph, seeds: list[str]) -> dict:
    nw_any = sorted({x["person_id"] for x in data.roles_by_org.get(data.nw_id, [])})
    dseed_any = bfs_from_set(g, nw_any)

    def mind(pids, dd):
        vals = [dd[p] for p in pids if p in dd]
        return min(vals) if vals else None

    readings = {"ceo_only": set(), "any_current_role_holder": set(), "decision_makers": set(), "any_northwind_person_ceo": set()}
    detail = []
    f1 = []
    for x in scored:
        cid = x["company_id"]
        ceos = [y["person_id"] for y in data.current_roles_at(cid, {"CEO"})]
        holders = sorted(data.current_role_holders(cid))
        dms = [y["person_id"] for y in decision_makers(data, cid)]
        dc, dh, dd, dn = mind(ceos, dseed), mind(holders, dseed), mind(dms, dseed), mind(ceos, dseed_any)
        for name, v in (("ceo_only", dc), ("any_current_role_holder", dh), ("decision_makers", dd), ("any_northwind_person_ceo", dn)):
            if v is not None and v <= 2 and x["score"] >= 60:
                readings[name].add(x["name"])
        if x["score"] >= 60:
            detail.append({"name": x["name"], "act1_score": x["score"], "ceo_d": dc, "min_role_holder_d": dh,
                           "min_decision_maker_d": dd, "ceo_d_any_northwind_person": dn,
                           "role_holders_d": sorted([[data.pname(p), dseed.get(p)] for p in holders],
                                                    key=lambda z: (z[1] if z[1] is not None else 99, z[0]))})
        if 60 <= x["score"] <= 69:
            f1.append({"name": x["name"], "act1_score": x["score"], "ceo_d": dc, "min_role_holder_d": dh,
                       "riser": dc is not None and dc <= 2})
    risers = [z for z in f1 if z["riser"]]
    non_risers_ok = all(z["min_role_holder_d"] is None or z["min_role_holder_d"] >= 3 for z in f1 if not z["riser"])
    sets = {k: sorted(v) for k, v in readings.items()}
    return {
        "guard_F1": {"companies_scoring_60_69": f1, "n_risers": len(risers),
                     "holds": len(risers) <= 1 and non_risers_ok,
                     "rule": "at most one 60-69 scorer reaches its CEO within 2 hops; every other 60-69 scorer has all current role-holders at seed distance >= 3"},
        "guard_F2": {"warm_sets_by_reading_score_ge_60": sets,
                     "holds": len({tuple(v) for v in sets.values()}) == 1,
                     "per_company": detail},
    }


# ----------------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------------
def build() -> dict:
    data = Data()
    thesis = Thesis(data)
    qs = q_score(data, thesis)
    scored_index = qs.pop("_scored_index")
    scored = sorted(scored_index.values(), key=rank_key)

    seeds = our_seeds(data)
    knows = build_knows(data, set(seeds))
    g = knows_graph(data, knows)
    dseed = bfs_from_set(g, seeds)

    qp = q_path(data, scored, knows, g, seeds, dseed)
    qf = q_flow(data, thesis)
    qc = q_conflict(data, thesis, scored_index)
    fn = finale(data, scored, dseed, g, knows)
    fn.pop("_rows")
    gd = guards(data, scored, dseed, g, seeds)

    return {
        "producer": "data/oracle.py (R06, independent pandas/networkx implementation of QUESTIONS.md v2)",
        "as_of_date": AS_OF.isoformat(),
        "inputs": {"manifest_sha256": data.manifest_sha256, "manifest_consistent": not data.manifest_mismatches,
                   "manifest_mismatches": data.manifest_mismatches, "csv_sha256": data.csv_sha256},
        "context": {
            "northwind_sponsor_id": data.nw_id, "fund_iv_id": data.fund_iv, "fund_iii_id": data.fund_iii,
            "fund_iv_focus": {"include": {thesis.area_name(a): b for a, b in sorted(thesis.include.items())},
                              "exclude": sorted(thesis.area_name(a) for a in thesis.exclude)},
        },
        "Q-SCORE": qs,
        "Q-PATH": qp,
        "Q-FLOW": qf,
        "Q-CONFLICT": qc,
        "FINALE": fn | {"guards": gd},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)
    out = build()
    text = json.dumps(out, indent=2, ensure_ascii=False, default=str) + "\n"
    if chr(0x2014) in text:
        raise SystemExit("oracle: em dash in output")
    Path(a.out).write_text(text)
    # short console summary
    qs, qp, qf, qc, fn = out["Q-SCORE"], out["Q-PATH"], out["Q-FLOW"], out["Q-CONFLICT"], out["FINALE"]
    print("Q-SCORE Tier A:", "; ".join(f"{x['rank']}. {x['name']} {x['score']}" for x in qs["answer"]["tier_a"]))
    print("  not in CRM:", qs["answer"]["not_in_crm_tier_a"])
    for x in qp["answer"]["rows"]:
        print(f"Q-PATH {x['target']} / {x['decision_maker']} ({x['kind']}): hops={x['hops']} strength={x['path_strength']}"
              + (f" alts={[a['strength'] for a in x['alternates']]}" if x["alternates"] else ""))
    for t in qp["answer"]["targets"]:
        if t["cold"]:
            print(f"  cold: {t['target']} closest intermediary = {t['closest_intermediary'] and t['closest_intermediary']['name']}")
    print("Q-FLOW top5:", "; ".join(f"{x['rank']}. {x['name']} bc={x['betweenness']:.1f} tp={x['touchpoints_24m']}" for x in qf["answer"]["top5"]),
          "| gaps:", [x["name"] for x in qf["answer"]["coverage_gaps"]])
    print("Q-CONFLICT:", [(x["name"], x["commercial_distance"], x["kind"]) for x in qc["answer"]["exposures"]],
          "| breaches:", qc["answer"]["breaches"])
    print("FINALE Tier A:", "; ".join(f"{x['rank']}. {x['name']} {x['score']}" for x in fn["answer"]["tier_a"]),
          "| flagged off Tier A:", [x["name"] for x in fn["answer"]["flagged_off_tier_a"]],
          "| all flagged:", [x["name"] for x in fn["answer"]["flagged"]])
    if out["inputs"]["manifest_mismatches"]:
        print("WARNING manifest mismatches:", out["inputs"]["manifest_mismatches"])
    print("Guards: F1", fn["guards"]["guard_F1"]["holds"], "F2", fn["guards"]["guard_F2"]["holds"])
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
