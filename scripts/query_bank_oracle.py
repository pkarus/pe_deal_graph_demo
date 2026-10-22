"""Offline pandas oracle for demo_workspace/query_bank.md (owner: R14).

Reads only data/csv/ (the loaded noisy data). Never touches the RAI engine or Snowflake.
Re-implements the QUESTIONS.md v2 rules it needs (eligibility, score components, Knows, seed distance,
deal flow) independently of pe_deal_graph/, then prints the expected answer for every query-bank question.
Self-check: the scored universe, tier counts and Tier A list must match exports/q_score.json.

Run: .venv/bin/python scripts/query_bank_oracle.py
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "csv"
T = pd.Timestamp("2026-10-01")
OUR = "Northwind Equity Partners"


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(CSV / f"{name}.csv", dtype=str, keep_default_na=False).replace("", None)


def dates(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_datetime(df[c])
    return df


co = load("COMPANY")
for c in ("revenue_musd", "ebitda_musd"):
    co[c] = co[c].astype(float)
sec, reg, spo, fund, ff = load("SECTOR"), load("REGION"), load("SPONSOR"), load("FUND"), load("FUND_FOCUS")
inter, person = load("INTERMEDIARY"), load("PERSON")
role = dates(load("ROLE_HISTORY"), "start_date", "end_date")
own = dates(load("OWNERSHIP"), "start_date", "end_date")
own["equity_invested_musd"] = own["equity_invested_musd"].astype(float)
sig = dates(load("COMPANY_SIGNAL"), "signal_date", "event_date")
crm = dates(load("CRM_INTERACTION"), "interaction_date")
pipe = load("PIPELINE")
txn = dates(load("TRANSACTION"), "close_date")
party = load("TRANSACTION_PARTY")
links = load("COMMERCIAL_LINK")
fund["vintage_year"] = fund["vintage_year"].astype(int)
for c in ("size_musd", "ebitda_min_musd", "ebitda_max_musd"):
    fund[c] = fund[c].astype(float)

pname = dict(zip(person.person_id, person.full_name))
oname = {**dict(zip(co.company_id, co.name)), **dict(zip(spo.sponsor_id, spo.name)),
         **dict(zip(inter.intermediary_id, inter.name))}
fname = dict(zip(fund.fund_id, fund.name))
fund_sponsor = dict(zip(fund.fund_id, fund.sponsor_id))
pid = {v: k for k, v in pname.items()}
cid = {v: k for k, v in zip(co.company_id, co.name)}
role["eff_end"] = role["end_date"].fillna(T)
role["current"] = (role.start_date <= T) & (role.eff_end >= T)
role.loc[role.end_date.notna() & (role.end_date <= T), "current"] = False  # ended on or before AS_OF
own["eff_end"] = own["end_date"].fillna(T)
own["current"] = (own.start_date <= T) & (own.end_date.isna() | (own.end_date > T))


def ancestors(df: pd.DataFrame, idcol: str) -> dict[str, set[str]]:
    par = dict(zip(df[idcol], df.parent_id))
    out = {}
    for n in par:
        s, x = {n}, par[n]
        while x:
            s.add(x)
            x = par.get(x)
        out[n] = s
    return out


sec_anc, reg_anc = ancestors(sec, "sector_id"), ancestors(reg, "region_id")
sec_name, sec_level = dict(zip(sec.sector_id, sec.name)), dict(zip(sec.sector_id, sec.level.astype(int)))
our_sid = spo.loc[spo.name == OUR, "sponsor_id"].item()
our_funds = set(fund.loc[fund.sponsor_id == our_sid, "fund_id"])
bf = fund[fund.fund_id.isin(our_funds)].sort_values("vintage_year").iloc[-1]
inc = ff[(ff.fund_id == bf.fund_id) & (ff["mode"] == "include")]
exc = set(ff[(ff.fund_id == bf.fund_id) & (ff["mode"] == "exclude")].sector_id)
inc_bench = dict(zip(inc.sector_id, inc.margin_benchmark_pct.astype(float)))

nw_hold = own[own.current & own.fund_id.isin(our_funds)]
majority = own[own.current & (own.stake_type == "majority")]
cur_owner_fund = dict(zip(majority.company_id, majority.fund_id))
cur_owner_start = dict(zip(majority.company_id, majority.start_date))


def thesis(sector_id):
    anc = sec_anc.get(sector_id, set())
    if anc & exc or not anc & set(inc_bench):
        return None
    return max(anc & set(inc_bench), key=lambda s: sec_level[s])  # deepest include node


co["thesis_area"] = co.sector_id.map(thesis)
co["is_us"] = co.hq_region_id.map(lambda r: "US" in reg_anc.get(r, set()))
co["public"] = co.is_public.str.upper() == "TRUE"
co["ours"] = co.company_id.isin(nw_hold.company_id)
co["in_band"] = co.ebitda_musd.between(bf.ebitda_min_musd, bf.ebitda_max_musd)


def ineligible_reason(r):
    if pd.isna(r.thesis_area):
        n = sec_name.get(r.sector_id, "?")
        return (f"niche {n} is excluded from the Fund IV thesis" if sec_anc.get(r.sector_id, set()) & exc
                else f"niche {n} is outside the Fund IV thesis tree")
    if not r.in_band:
        return f"EBITDA ${r.ebitda_musd:.1f}M is outside the ${bf.ebitda_min_musd:.0f}-{bf.ebitda_max_musd:.0f}M band"
    if not r.is_us:
        return "not US"
    if r.public:
        return "public"
    if r.ours:
        return "already a Northwind holding"
    return None


co["ineligible"] = co.apply(ineligible_reason, axis=1)
elig = co[co.ineligible.isna()].copy()
E = set(elig.company_id)

# ---------------- score components (QUESTIONS.md Q-SCORE) ----------------
comp = defaultdict(dict)  # company -> code -> (points, evidence)
for r in elig.itertuples():
    comp[r.company_id]["FIT_THESIS"] = (15, sec_name[r.thesis_area])
    comp[r.company_id]["FIT_EBITDA"] = (10 if 10.0 <= r.ebitda_musd <= 30.0 else 5, f"EBITDA ${r.ebitda_musd}M")
    if r.revenue_musd and 100 * r.ebitda_musd / r.revenue_musd >= inc_bench[r.thesis_area]:
        comp[r.company_id]["FIT_MARGIN"] = (5, f"{100 * r.ebitda_musd / r.revenue_musd:.1f}% vs {inc_bench[r.thesis_area]}%")

cur = role[role.current]
for r in cur[(cur.role_type == "CFO") & cur.org_id.isin(E)].itertuples():
    if not (T - pd.DateOffset(months=18) <= r.start_date <= T):
        continue
    prev = role[(role.person_id == r.person_id) & (role.org_id != r.org_id) & role.end_date.notna()
                & (role.end_date >= r.start_date - pd.DateOffset(months=12)) & (role.end_date <= r.start_date)]
    for p in prev.itertuples():
        o = own[own.company_id == p.org_id]
        o = o[(o[["eff_end"]].min(axis=1).clip(upper=p.end_date) - o.start_date.clip(lower=p.start_date)).dt.days >= 1]
        if len(o):
            f = o.iloc[0].fund_id
            comp[r.org_id]["R_CFO_FROM_PE"] = (15, f"CFO {pname[r.person_id]} hired {r.start_date.date()} from "
                                                   f"{oname[p.org_id]} ({fname[f]})")
# rules.py R_EXIT_WINDOW: any current ownership (majority or minority) held 5+ years by a fund of vintage <= 2018
cur_own = own[own.current & own.company_id.isin(E)].sort_values("start_date")
for o in cur_own.itertuples():
    fv = fund.set_index("fund_id").loc[o.fund_id]
    if o.company_id not in comp or "R_EXIT_WINDOW" in comp[o.company_id]:
        pass
    if o.start_date <= T - pd.DateOffset(years=5) and fv.vintage_year <= 2018 and "R_EXIT_WINDOW" not in comp[o.company_id]:
        comp[o.company_id]["R_EXIT_WINDOW"] = (15, f"{fname[o.fund_id]} ({o.stake_type}), vintage {fv.vintage_year}, held since "
                                                  f"{o.start_date.date()} = {(T - o.start_date).days / 365.25:.1f} years")
s = sig[sig.company_id.isin(E)]
for r in s[(s.signal_type == "BANKER_ENGAGED") & s.signal_date.between(T - pd.DateOffset(months=6), T)].itertuples():
    comp[r.company_id]["R_BANKER"] = (10, f"{r.signal_date.date()} {oname.get(r.intermediary_id, '')}")
for r in s[(s.signal_type == "DEBT_MATURITY") & (s.signal_date <= T) & (s.event_date > T)
           & (s.event_date <= T + pd.DateOffset(months=18))].itertuples():
    comp[r.company_id]["R_DEBT"] = (10, f"matures {r.event_date.date()}")
for r in cur[(cur.role_type == "CEO") & cur.org_id.isin(E)].itertuples():
    pc = cur[(cur.org_id == r.org_id) & cur.role_type.isin(["President", "COO"])]
    if str(r.is_founder).upper() == "TRUE" and r.start_date <= T - pd.DateOffset(years=15) and pc.empty:
        comp[r.org_id]["R_SUCCESSION"] = (10, f"founder CEO {pname[r.person_id]} since {r.start_date.date()}")
for r in role[(role.role_type == "Board") & role.org_id.isin(E)
              & role.start_date.between(T - pd.DateOffset(months=12), T)].itertuples():
    other = role[(role.person_id == r.person_id) & (role.org_id == r.org_id) & (role.role_type != "Board")]
    osp = fund_sponsor.get(cur_owner_fund.get(r.org_id))
    at_sp = cur[(cur.person_id == r.person_id) & (cur.org_id == osp)] if osp else cur.iloc[0:0]
    if other.empty and at_sp.empty:
        comp[r.org_id]["R_NEW_DIRECTOR"] = (5, f"director {pname[r.person_id]} from {r.start_date.date()}")
cur_people = cur.groupby("org_id").person_id.apply(set).to_dict()
pos = crm[(crm.sentiment == "positive") & crm.interaction_date.between(T - pd.DateOffset(months=24), T)]
for c in E:
    hit = pos[(pos.counterparty_org_id == c) | pos.counterparty_person_id.isin(cur_people.get(c, set()))]
    if len(hit):
        comp[c]["A_CRM"] = (10, f"positive {hit.interaction_date.max().date()}")

READ = ("R_CFO_FROM_PE", "R_EXIT_WINDOW", "R_BANKER", "R_DEBT", "R_SUCCESSION", "R_NEW_DIRECTOR")
RPTS = dict(R_CFO_FROM_PE=15, R_EXIT_WINDOW=15, R_BANKER=10, R_DEBT=10, R_SUCCESSION=10, R_NEW_DIRECTOR=5)
rows = []
for c in E:
    k = comp[c]
    fit = sum(k[x][0] for x in k if x.startswith("FIT"))
    rd = min(50, sum(k[x][0] for x in k if x.startswith("R_")))
    ac = k.get("A_CRM", (0,))[0]
    sc = fit + rd + ac
    rows.append(dict(company_id=c, name=oname[c], score=sc, fit=fit, readiness=rd, access=ac,
                     tier="A" if sc >= 70 else "B" if sc >= 50 else "C"))
sc = pd.DataFrame(rows).sort_values(["score", "readiness", "fit", "name"], ascending=[False, False, False, True])
sc = sc.reset_index(drop=True)
in_crm = set(pipe.company_id) | set(crm.counterparty_org_id.dropna())
for c, ppl in cur_people.items():
    if set(crm.counterparty_person_id.dropna()) & ppl:
        in_crm.add(c)
sc["in_crm"] = sc.company_id.isin(in_crm)
S = sc.set_index("company_id")

# self-check against the governed export
ex = json.load(open(ROOT / "exports" / "q_score.json"))
exp_rows = {r["name"]: r["score"] for r in ex["rows"]}
mine = {r.name: r.score for r in sc.itertuples() if r.tier in "AB"}
check = dict(scored=(len(sc), ex["summary"]["scored"]),
             tierA=((sc.tier == "A").sum(), ex["summary"]["tier_a"]),
             tierB=((sc.tier == "B").sum(), ex["summary"]["tier_b"]),
             tierAB_scores_match=(mine == exp_rows, True))
print("SELF-CHECK vs exports/q_score.json:", check)
if mine != exp_rows:
    print("  diff:", {k: (mine.get(k), exp_rows.get(k)) for k in set(mine) | set(exp_rows) if mine.get(k) != exp_rows.get(k)})

# ---------------- Knows and seed distance (QUESTIONS.md Q-PATH) ----------------
def recency(d):
    return 1.0 if d >= T - pd.DateOffset(years=10) else 0.7 if d >= T - pd.DateOffset(years=20) else 0.4


edges = defaultdict(float)  # (p1, p2) sorted -> strength
ev = {}


def add(a, b, w, label):
    if a == b:
        return
    k = tuple(sorted((a, b)))
    if w > edges[k]:
        edges[k], ev[k] = w, label


for org, g in role.groupby("org_id"):
    g = g.to_dict("records")
    for i in range(len(g)):
        for j in range(i + 1, len(g)):
            a, b = g[i], g[j]
            if a["person_id"] == b["person_id"]:
                continue
            e, s0 = min(a["eff_end"], b["eff_end"]), max(a["start_date"], b["start_date"])
            d = (e - s0).days
            if d >= 365:
                add(a["person_id"], b["person_id"], recency(e) * min(1.0, 0.4 + 0.15 * d / 365.25),
                    f"K1 {oname.get(org, org)} {s0.date()} to {e.date()}")
for t in txn.itertuples():
    leads = set(party[party.txn_id == t.txn_id].lead_person_id.dropna())
    execs = set(role[(role.org_id == t.target_id) & role.role_type.isin(["CEO", "CFO"])
                     & (role.start_date <= t.close_date) & (role.eff_end >= t.close_date)].person_id)
    w = 0.7 * recency(t.close_date)
    for a in leads:
        for b in leads | execs:
            add(a, b, w, f"K2 {t.txn_id} {oname.get(t.target_id)} {t.close_date.date()}")
seeds = set(cur[(cur.org_id == our_sid) & cur.role_type.isin(["Deal Team", "Operating Partner"])].person_id)
pp = pos[pos.counterparty_person_id.notna() & pos.our_person_id.isin(seeds)]
for (a, b), n in pp.groupby(["our_person_id", "counterparty_person_id"]).size().items():
    add(a, b, {1: 0.6, 2: 0.8}.get(n, 1.0), f"K3 {n} positive")
adj = defaultdict(set)
for a, b in edges:
    adj[a].add(b)
    adj[b].add(a)


def bfs(src):
    dist, q = {src: 0}, deque([src])
    while q:
        x = q.popleft()
        for y in adj[x]:
            if y not in dist:
                dist[y] = dist[x] + 1
                q.append(y)
    return dist


def seeds_within(target, k):
    d = bfs(pid[target])
    return sorted((d[s], pname[s]) for s in seeds if s in d and d[s] <= k)


def paths(src, dst, k):
    out, stack = [], [(src, [src])]
    while stack:
        x, p = stack.pop()
        if x == dst:
            out.append(p)
            continue
        if len(p) <= k:
            for y in adj[x]:
                if y not in p:
                    stack.append((y, p + [y]))
    return out


def show(title, df_or_text):
    print(f"\n=== {title}")
    print(df_or_text.to_string(index=False) if isinstance(df_or_text, pd.DataFrame) else df_or_text)


def comps_str(c):
    return ", ".join(f"{k} {v[0]}" for k, v in comp[c].items())


# ---------------- the query bank ----------------
# Q1 lookup: Texas, Tier A or B (a $10-25M EBITDA band would surface the Cobalt Urgent Care decoy at Tier C)
tx = elig[(elig.hq_region_id == "US-TX") & elig.company_id.isin(sc[sc.tier.isin(["A", "B"])].company_id)]
q1 = S.loc[list(tx.company_id), ["name", "score", "tier"]].join(tx.set_index("company_id")[["ebitda_musd"]])
show("Q1 Fund IV Tier A/B targets HQ Texas", q1.sort_values(["score", "name"], ascending=[False, True]))
show("Q1b Texas companies with EBITDA 10-30 that a naive screen would add (Tier C or ineligible)",
     co[(co.hq_region_id == "US-TX") & co.ebitda_musd.between(10, 30) & ~co.company_id.isin(tx.company_id)]
     .assign(tier=lambda d: d.company_id.map(S.tier))[["name", "ebitda_musd", "tier", "ineligible"]].head(40))

# Q2 rule: Tier B one readiness component from Tier A
r2 = []
for r in sc[sc.tier == "B"].itertuples():
    for code in READ:
        if code in comp[r.company_id]:
            continue
        if code == "R_EXIT_WINDOW" and r.company_id not in set(own[own.current].company_id):
            continue  # founder-owned: no sponsor clock to run out
        gain = min(50, r.readiness + RPTS[code]) - r.readiness
        if r.score + gain >= 70:
            r2.append((r.name, r.score, r.readiness, code, gain))
show("Q2 Tier B one missing readiness component away from Tier A",
     pd.DataFrame(r2, columns=["name", "score", "readiness", "missing", "gain"]))
show("Q2b Tier B list", sc[sc.tier == "B"][["name", "score", "fit", "readiness", "access"]])

# Q3 rule: CFO from PE-backed company
q3 = [(oname[c], S.loc[c, "score"], S.loc[c, "tier"], comp[c]["R_CFO_FROM_PE"][1]) for c in E if "R_CFO_FROM_PE" in comp[c]]
show("Q3 eligible targets with R_CFO_FROM_PE", pd.DataFrame(q3, columns=["name", "score", "tier", "evidence"])
     .sort_values(["score", "name"], ascending=[False, True]))

# Q4 rule: sponsor exit window
q4 = [(oname[c], S.loc[c, "score"], S.loc[c, "tier"], comp[c]["R_EXIT_WINDOW"][1]) for c in E if "R_EXIT_WINDOW" in comp[c]]
show("Q4 eligible targets with R_EXIT_WINDOW", pd.DataFrame(q4, columns=["name", "score", "tier", "evidence"])
     .sort_values(["score", "name"], ascending=[False, True]))
cob = cid["Cobalt Urgent Care Partners"]
show("Q4b Cobalt (decoy) owner", f"owner {fname.get(cur_owner_fund.get(cob))} since {cur_owner_start.get(cob)}; eligible={cob in E}")

# Q5 why: Fenwick
fen = cid["Fenwick Food Safety Labs"]
show("Q5 Fenwick Food Safety Labs", f"{S.loc[fen].to_dict()}\n" + "\n".join(f"  {k} {v}" for k, v in comp[fen].items())
     + f"\n  pipeline row: {fen in set(pipe.company_id)}; CRM touches on org or current people: "
       f"{len(crm[(crm.counterparty_org_id == fen) | crm.counterparty_person_id.isin(cur_people.get(fen, set()))])}")

# Q6 why: Northgate
ng = co[co.name == "Northgate Behavioral Health"].iloc[0]
show("Q6 Northgate Behavioral Health", f"ebitda {ng.ebitda_musd}, reason: {ng.ineligible}")

# Q7 lookup: current roles at Saltmarsh
sm = cid["Saltmarsh Home Infusion"]
q7 = cur[cur.org_id == sm][["person_id", "role_type", "title", "start_date"]].copy()
q7["name"] = q7.person_id.map(pname)
q7["also_current_at"] = q7.person_id.map(lambda p: ", ".join(sorted(oname.get(o, o) for o in cur[(cur.person_id == p) & (cur.org_id != sm)].org_id)))
show("Q7 current roles at Saltmarsh Home Infusion", q7[["name", "role_type", "title", "start_date", "also_current_at"]].sort_values(["role_type", "name"]))
show("Q7b owner", f"{fname.get(cur_owner_fund.get(sm))} since {cur_owner_start.get(sm)}")

# Q8 graph: our people within 2 hops of Daniel Reyes
show("Q8 seeds within 2 hops of Daniel Reyes", seeds_within("Daniel Reyes", 2))
for s_ in seeds_within("Daniel Reyes", 2):
    for p in paths(pid[s_[1]], pid["Daniel Reyes"], 2):
        print("   ", " > ".join(pname[x] for x in p), [round(edges[tuple(sorted(z))], 3) for z in zip(p, p[1:])],
              [ev[tuple(sorted(z))] for z in zip(p, p[1:])])
show("Q8b seeds within 3 hops of Daniel Reyes", seeds_within("Daniel Reyes", 3))

# Q9 graph: who on our team is closest to Harbor Lane's people
hl = [k for k, v in oname.items() if v == "Harbor Lane Advisors"][0]
hl_people = sorted(cur_people.get(hl, set()))
for p in hl_people:
    print(f"\n=== Q9 Harbor Lane current person {pname[p]} ({cur[(cur.person_id == p) & (cur.org_id == hl)].title.tolist()}); "
          f"seeds within 3: {seeds_within(pname[p], 3)}")

# Q10 why: Tom Harlowe and Victor Hale at Varnell
var = cid["Varnell Lab Services"]
show("Q10 roles at Varnell Lab Services for Tom Harlowe and Victor Hale",
     role[(role.org_id == var) & role.person_id.isin([pid["Tom Harlowe"], pid["Victor Hale"]])]
     .assign(name=lambda d: d.person_id.map(pname))[["name", "role_type", "start_date", "end_date"]])
show("Q10b Tom Harlowe current roles", cur[cur.person_id == pid["Tom Harlowe"]][["org_id", "role_type", "title"]]
     .assign(org=lambda d: d.org_id.map(oname)))
k = tuple(sorted((pid["Tom Harlowe"], pid["Victor Hale"])))
show("Q10c Knows edge Tom Harlowe-Victor Hale", f"{k in edges}; hops from seeds to Victor Hale: "
     f"{min([bfs(s_).get(pid['Victor Hale'], 99) for s_ in seeds])}")

# Q11 lookup: CRM touchpoints with Harbor Lane in 24 months
win = crm[crm.interaction_date.between(T - pd.DateOffset(months=24), T)]
q11 = win[(win.counterparty_org_id == hl) | win.counterparty_person_id.isin(cur_people.get(hl, set()))].copy()
q11["our_person"] = q11.our_person_id.map(pname)
q11["counterparty"] = q11.counterparty_person_id.map(pname)
show("Q11 CRM touchpoints with Harbor Lane Advisors, 24 months", q11[["interaction_date", "our_person", "counterparty", "channel", "sentiment"]])
cr = [k for k, v in oname.items() if v == "Cedar Row Partners"][0]
show("Q11b Cedar Row touchpoints 24m", len(win[(win.counterparty_org_id == cr) | win.counterparty_person_id.isin(cur_people.get(cr, set()))]))

# Q12 graph: Harbor Lane deal-flow partners (DealFlowTransaction, advisor roles)
ADV = {"sell_side_advisor", "buy_side_advisor", "debt_advisor"}
th = set(co[co.thesis_area.notna()].company_id)
dft = txn[txn.close_date.between(T - pd.DateOffset(years=5), T) & txn.target_id.isin(th)]
hl_txn = party[(party.org_id == hl) & party.party_role.isin(ADV) & party.txn_id.isin(dft.txn_id)].txn_id.unique()
q12 = []
for t in hl_txn:
    tr = dft[dft.txn_id == t].iloc[0]
    pr = party[party.txn_id == t]
    for p in pr.itertuples():
        if p.org_id != hl:
            q12.append((t, tr.close_date.date(), oname[tr.target_id], tr.deal_role, tr.seller_type, p.party_role,
                        oname.get(p.org_id, p.org_id), "sponsor" if p.org_id in set(spo.sponsor_id) else p.org_type))
q12 = pd.DataFrame(q12, columns=["txn", "close", "target", "deal_role", "seller_type", "party_role", "org", "org_type"])
show(f"Q12 Harbor Lane thesis deals in 5y ({len(hl_txn)})", q12.sort_values(["close", "party_role"]))
show("Q12b distinct sponsors on Harbor Lane deals", sorted(q12[q12.org_type == "sponsor"].org.unique()))

# Q13 lookup: Fund IV holdings today
q13 = nw_hold[nw_hold.fund_id == bf.fund_id].copy()
q13["name"] = q13.company_id.map(oname)
q13["thesis_area"] = q13.company_id.map(dict(zip(co.company_id, co.thesis_area))).map(lambda s: sec_name.get(s))
show(f"Q13 {bf['name']} current holdings (size {bf.size_musd})",
     q13[["name", "start_date", "stake_type", "equity_invested_musd", "thesis_area"]].sort_values("equity_invested_musd", ascending=False))
show("Q13b all Northwind holdings by fund", nw_hold.assign(fund=lambda d: d.fund_id.map(fname), name=lambda d: d.company_id.map(oname))
     .groupby("fund").name.apply(lambda x: ", ".join(sorted(x))))
show("Q13c Cobbleton ownership rows", own[own.company_id == cid["Cobbleton Dental Group"]][["fund_id", "start_date", "end_date"]]
     .assign(fund=lambda d: d.fund_id.map(fname)))

# Q14 lookup: CRM touchpoints with Tessmark in last 12 months
ts = cid["Tessmark Clinical Supply"]
w12 = crm[crm.interaction_date.between(T - pd.DateOffset(months=12), T)]
q14 = w12[(w12.counterparty_org_id == ts) | w12.counterparty_person_id.isin(cur_people.get(ts, set()))].copy()
q14["our_person"] = q14.our_person_id.map(pname)
q14["counterparty"] = q14.counterparty_person_id.map(pname)
show("Q14 CRM touchpoints with Tessmark Clinical Supply, 12 months", q14[["interaction_date", "our_person", "counterparty", "channel", "sentiment"]])
show("Q14b pipeline Tessmark", pipe[pipe.company_id == ts].assign(owner=lambda d: d.owner_person_id.map(pname)))
