"""Scout: toy PyRel model that verifies the idioms P3/P4 need, on the live engine.

Prereq: .venv/bin/python scripts/scout/scout_tables.py create
Run:    .venv/bin/python scripts/scout/scout_model.py <tag>      (writes scripts/scout/out/<tag>/*.csv)
Then:   diff -r scripts/scout/out/run1 scripts/scout/out/run2     (determinism)
Drop:   .venv/bin/python scripts/scout/scout_tables.py drop
"""
import datetime as pydt
import sys
import time
import traceback
from pathlib import Path

import pandas as pd
from relationalai.semantics import Float, Integer, Model, String, Date, distinct
from relationalai.semantics.reasoners.graph import Graph
from relationalai.semantics.std import aggregates as aggs
from relationalai.semantics.std import datetime as dt
from relationalai.semantics.std import floats, math, numbers, strings
from relationalai.semantics.std.aggregates import asc, desc, rank

S = "RAI_DEMO_PE_DEALS.DEAL_GRAPH"
AS_OF = dt.date(2026, 10, 1)  # PyRel date expression; a python datetime.date literal fails to compile

model = Model("pe_scout")

# ---------------------------------------------------------------- 1. concepts + Snowflake bindings
Organization = model.Concept("Organization", identify_by={"org_id": String})
Organization.name = model.Property(f"{Organization} has {String:name}")
Company = model.Concept("Company", extends=[Organization])
Sponsor = model.Concept("Sponsor", extends=[Organization])
Intermediary = model.Concept("Intermediary", extends=[Organization])

Sector = model.Concept("Sector", identify_by={"sector_id": String})
Sector.name = model.Property(f"{Sector} has {String:name}")
Sector.level = model.Property(f"{Sector} has {Integer:level}")
Sector.parent = model.Property(f"{Sector} has parent {Sector:parent}")

Company.sector = model.Property(f"{Company} operates in {Sector:sector}")
Company.ebitda = model.Property(f"{Company} has {Float:ebitda}")
Company.is_founder_owned = model.Relationship(f"{Company} is founder owned")
Sponsor.aum = model.Property(f"{Sponsor} has {Float:aum}")
Intermediary.itype = model.Property(f"{Intermediary} has {String:itype}")

Person = model.Concept("Person", identify_by={"person_id": String})
Person.name = model.Property(f"{Person} has {String:name}")

Role = model.Concept("Role", identify_by={"role_id": String})
Role.person = model.Property(f"{Role} held by {Person:person}")
Role.org = model.Property(f"{Role} at {Organization:org}")
Role.role_type = model.Property(f"{Role} has {String:role_type}")
Role.start = model.Property(f"{Role} starts {Date:start}")
Role.end = model.Property(f"{Role} ends {Date:end}")
Role.eff_end = model.Property(f"{Role} effectively ends {Date:eff_end}")

sec = model.Table(f"{S}.SCOUT_SECTOR")
model.define(s := Sector.new(sector_id=sec.SECTOR_ID), s.name(sec.NAME), s.level(sec.LEVEL))
child, par = Sector.ref(), Sector.ref()
model.where(child.sector_id == sec.SECTOR_ID, par.sector_id == sec.PARENT_ID).define(child.parent(par))

co = model.Table(f"{S}.SCOUT_COMPANY")
model.define(c := Company.new(org_id=co.COMPANY_ID), c.name(co.NAME),
             c.sector(Sector.filter_by(sector_id=co.SECTOR_ID)))
model.define(Company.filter_by(org_id=co.COMPANY_ID).ebitda(co.EBITDA_MUSD))  # nullable: separate define
model.where(co.IS_FOUNDER_OWNED == True).define(Company.filter_by(org_id=co.COMPANY_ID).is_founder_owned())  # noqa: E712

sp = model.Table(f"{S}.SCOUT_SPONSOR")
model.define(x := Sponsor.new(org_id=sp.SPONSOR_ID), x.name(sp.NAME), x.aum(sp.AUM_MUSD))
im = model.Table(f"{S}.SCOUT_INTERMEDIARY")
model.define(x := Intermediary.new(org_id=im.INTERMEDIARY_ID), x.name(im.NAME), x.itype(im.INTERMEDIARY_TYPE))

pe = model.Table(f"{S}.SCOUT_PERSON")
model.define(x := Person.new(person_id=pe.PERSON_ID), x.name(pe.NAME))

ro = model.Table(f"{S}.SCOUT_ROLE")
model.define(r := Role.new(role_id=ro.ROLE_ID),
             r.person(Person.filter_by(person_id=ro.PERSON_ID)),
             r.org(Organization.filter_by(org_id=ro.ORG_ID)),
             r.role_type(ro.ROLE_TYPE), r.start(ro.START_DATE))
model.define(Role.filter_by(role_id=ro.ROLE_ID).end(ro.END_DATE))
Role.eff_end_match = model.Property(f"{Role} match-ends {Date:eff_end_match}")
model.define(Role.eff_end_match(Role.end | AS_OF))  # probe: '|' fallback with a date expression
model.define(Role.eff_end(Role.end))  # two-rule fallback: open end date -> AS_OF
model.where(model.not_(Role.end)).define(Role.eff_end(AS_OF))

# ---------------------------------------------------------------- 2. recursive closure
Sector.ancestor = model.Relationship(f"{Sector} has ancestor {Sector:anc}")
Sector.under = model.Relationship(f"{Sector} is under or equal to {Sector:top}")
s1, s2, s3 = Sector.ref(), Sector.ref(), Sector.ref()
model.where(s1.parent(s2)).define(s1.ancestor(s2))
model.where(s1.parent(s2), s2.ancestor(s3)).define(s1.ancestor(s3))  # recursion
model.define(Sector.under(Sector))
model.where(Sector.ancestor(s3)).define(Sector.under(s3))

focus = model.data(pd.DataFrame({"sector_id": ["SC2", "SC6", "SC4"], "mode": ["include", "include", "exclude"]}))
Sector.is_include = model.Relationship(f"{Sector} is a thesis include node")
Sector.is_exclude = model.Relationship(f"{Sector} is a thesis exclude node")
model.where(Sector.sector_id == focus.sector_id, focus.mode == "include").define(Sector.is_include())
model.where(Sector.sector_id == focus.sector_id, focus.mode == "exclude").define(Sector.is_exclude())

Company.in_thesis = model.Relationship(f"{Company} is in thesis")
niche, inc, exc = Sector.ref(), Sector.ref(), Sector.ref()
model.where(Company.sector(niche), niche.under(inc), inc.is_include(),
            model.not_(niche.under(exc), exc.is_exclude())).define(Company.in_thesis())

# ---------------------------------------------------------------- 3. dates: tenure overlap
Overlap = model.Concept("Overlap", identify_by={"r1": Role, "r2": Role})
Overlap.days = model.Property(f"{Overlap} lasts {Integer:days}")
Overlap.years = model.Property(f"{Overlap} lasts {Float:years}")
Overlap.gap_days = model.Property(f"{Overlap} ended {Integer:gap_days} days before AS_OF")
ra, rb = Role.ref(), Role.ref()
pa, pb = Person.ref(), Person.ref()
pd_ = dt.date.period_days
# overlap = min(e1,e2) - max(s1,s2) = min over the four (end - start) differences
ov_days = math.minimum(math.minimum(pd_(ra.start, ra.eff_end), pd_(rb.start, rb.eff_end)),
                       math.minimum(pd_(rb.start, ra.eff_end), pd_(ra.start, rb.eff_end)))
model.where(ra.org == rb.org, ra.person(pa), rb.person(pb), pa.person_id < pb.person_id,
            d := ov_days, d >= 365).define(
    o := Overlap.new(r1=ra, r2=rb), o.days(d), o.years(floats.float(d) / 365.25),
    o.gap_days(math.maximum(pd_(ra.eff_end, AS_OF), pd_(rb.eff_end, AS_OF))))

# ---------------------------------------------------------------- 4. Knows from several sources
Tie = model.Concept("Tie", identify_by={"a": Person, "b": Person, "kind": String, "key": String})
Tie.strength = model.Property(f"{Tie} has {Float:strength}")
Tie.evidence = model.Property(f"{Tie} has {String:evidence}")

# K1: overlapping tenure >= 12 months at the same org; decays by half when it ended > 10 years ago
ov, org = Overlap.ref(), Organization.ref()
k1_base = math.minimum(1.0, ov.years / 4.0)
k1_ev = strings.concat("K1 overlap at ", org.name, ", ", strings.string(math.round(ov.years, 2)), " years")
model.where(ov.r1(ra), ov.r2(rb), ra.person(pa), rb.person(pb), ra.org(org), ov.gap_days <= 3652).define(
    t := Tie.new(a=pa, b=pb, kind="K1", key=strings.concat(ra.role_id, "-", rb.role_id)),
    t.strength(k1_base), t.evidence(k1_ev))
model.where(ov.r1(ra), ov.r2(rb), ra.person(pa), rb.person(pb), ra.org(org), ov.gap_days > 3652).define(
    t := Tie.new(a=pa, b=pb, kind="K1", key=strings.concat(ra.role_id, "-", rb.role_id)),
    t.strength(k1_base * 0.5), t.evidence(strings.concat(k1_ev, " (stale)")))

# K2: deal co-participation (inline data)
deal_rows = model.data(pd.DataFrame({"deal_id": ["D9", "D9"], "person_id": ["P8", "P9"]}))
deal2 = model.data(pd.DataFrame({"deal_id": ["D9", "D9"], "person_id": ["P8", "P9"]}))
model.where(deal_rows.deal_id == deal2.deal_id, pa.person_id == deal_rows.person_id,
            pb.person_id == deal2.person_id, pa.person_id < pb.person_id).define(
    t := Tie.new(a=pa, b=pb, kind="K2", key=deal_rows.deal_id),
    t.strength(0.7), t.evidence(strings.concat("K2 co-participated in deal ", deal_rows.deal_id)))

# K3: positive CRM interactions inside [AS_OF - 24 months, AS_OF]
Interaction = model.Concept("Interaction", identify_by={"ix_id": String})
Interaction.by = model.Property(f"{Interaction} logged by {Person:by}")
Interaction.other = model.Property(f"{Interaction} with {Person:other}")
Interaction.on = model.Property(f"{Interaction} on {Date:on}")
Interaction.sentiment = model.Property(f"{Interaction} has {String:sentiment}")
ixd = model.data(pd.DataFrame({
    "ix_id": ["X1", "X2", "X3", "X4"], "by": ["P4", "P4", "P1", "P4"], "other": ["P8", "P8", "P5", "P9"],
    "on": ["2026-05-01", "2025-11-15", "2023-01-10", "2026-02-01"],
    "sentiment": ["positive", "positive", "positive", "negative"]}))
model.define(x := Interaction.new(ix_id=ixd.ix_id), x.by(Person.filter_by(person_id=ixd.by)),
             x.other(Person.filter_by(person_id=ixd.other)), x.on(dt.date.fromisoformat(ixd.on)),
             x.sentiment(ixd.sentiment))
WSTART = dt.date.subtract(AS_OF, dt.months(24))
ix = Interaction.ref()
n_pos = aggs.count(ix).per(pa, pb).where(ix.by(pa), ix.other(pb), ix.sentiment == "positive",
                                          ix.on >= WSTART, ix.on <= AS_OF)
model.where(n := n_pos, pa.person_id < pb.person_id).define(
    t := Tie.new(a=pa, b=pb, kind="K3", key="crm"),
    t.strength(math.minimum(1.0, 0.4 + 0.2 * floats.float(n))),
    t.evidence(strings.concat("K3 ", strings.string(n), " positive interactions in 24m")))

Knows = model.Concept("Knows", identify_by={"p1": Person, "p2": Person})
Knows.strength = model.Property(f"{Knows} has {Float:strength}")
Knows.n_sources = model.Property(f"{Knows} has {Integer:n_sources}")
Knows.evidence = model.Property(f"{Knows} has {String:evidence}")
model.define(Knows.new(p1=Tie.a, p2=Tie.b))
tt = Tie.ref()
model.where(tt.a == Knows.p1, tt.b == Knows.p2).define(
    Knows.strength(aggs.max(tt.strength).per(Knows)),
    Knows.n_sources(aggs.count(tt).per(Knows)),
)
# aggs.string_join is NOT supported by the default (legacy) LQP compiler -> argmax evidence via rank()
model.where(tt.a == Knows.p1, tt.b == Knows.p2,
            rank(asc(0.0 - tt.strength), asc(tt.kind), asc(tt.key)).per(Knows) == 1).define(
    Knows.evidence(tt.evidence))
Person.knows = model.Relationship(f"{Person} knows {Person:other}")  # symmetric view for joins
model.where(Knows.p1(pa), Knows.p2(pb)).define(pa.knows(pb), pb.knows(pa))

# ---------------------------------------------------------------- 5/6. aggregates, score, tiers, explanation
Company.ebitda_rank = model.Property(f"{Company} has {Integer:ebitda_rank}")
Company.ebitda_decile = model.Property(f"{Company} has {Integer:ebitda_decile}")
# mixed asc/desc in one rank() is unsupported (legacy LQP): negate the numeric key and keep all asc
model.define(Company.ebitda_rank(rank(asc(0.0 - Company.ebitda), asc(Company.name))))
n_with_ebitda = aggs.count(Company).where(Company.ebitda)
model.define(Company.ebitda_decile(numbers.integer(math.ceil(10.0 * floats.float(Company.ebitda_rank)
                                                             / floats.float(n_with_ebitda)))))

Component = model.Concept("Component", identify_by={"company": Company, "code": String})
Component.points = model.Property(f"{Component} is worth {Integer:points}")
Component.label = model.Property(f"{Component} has {String:label}")
model.where(Company.in_thesis()).define(
    k := Component.new(company=Company, code="FIT_THESIS"), k.points(15), k.label("thesis fit 15"))
model.where(Company.ebitda >= 5.0, Company.ebitda <= 40.0).define(
    k := Component.new(company=Company, code="FIT_EBITDA"), k.points(10),
    k.label(strings.concat("EBITDA ", strings.string(Company.ebitda), "M in band 10")))
model.where(Company.is_founder_owned()).define(
    k := Component.new(company=Company, code="READY_FOUNDER"), k.points(10), k.label("founder owned 10"))

Company.score = model.Property(f"{Company} has {Integer:score}")
Company.tier = model.Property(f"{Company} has {String:tier}")
Company.why = model.Property(f"{Company} has {String:why}")
cp = Component.ref()
model.define(Company.score(aggs.sum(cp.points).per(Company).where(cp.company == Company) | 0))
model.where(Company.score >= 30).define(Company.tier("A"))
model.where(Company.score >= 20, Company.score < 30).define(Company.tier("B"))
model.where(Company.score < 20).define(Company.tier("C"))
# explanation: one optional label property per named component, concatenated with "" fallbacks
Company.why_thesis = model.Property(f"{Company} has {String:why_thesis}")
Company.why_ebitda = model.Property(f"{Company} has {String:why_ebitda}")
Company.why_founder = model.Property(f"{Company} has {String:why_founder}")
for code, prop in [("FIT_THESIS", Company.why_thesis), ("FIT_EBITDA", Company.why_ebitda),
                   ("READY_FOUNDER", Company.why_founder)]:
    model.where(cp.company == Company, cp.code == code).define(prop(Company, strings.concat(cp.label, "; ")))
    # 'prop | ""' does NOT default a missing property inside define (rows vanish); use not_() instead
    k_ = Component.ref()
    model.where(model.not_(k_.company == Company, k_.code == code)).define(prop(Company, ""))
model.define(Company.why(strings.concat(Company.why_thesis, Company.why_ebitda,
                                        Company.why_founder, "score ", strings.string(Company.score))))
Company.n_none = model.Property(f"{Company} has {Integer:n_none}")  # probe: aggregate '| 0' on empty group
model.define(Company.n_none(aggs.count(cp).per(Company).where(cp.company == Company, cp.code == "NONE") | 0))

# ---------------------------------------------------------------- 7-11. graphs
g_knows = Graph(model, directed=False, weighted=False, node_concept=Person)
model.define(g_knows.Edge.new(src=Knows.p1, dst=Knows.p2))
g_knows_w = Graph(model, directed=False, weighted=True, node_concept=Person)
model.define(g_knows_w.Edge.new(src=Knows.p1, dst=Knows.p2, weight=Knows.strength))

is_seed = model.Relationship(f"{Person:node} is a Northwind seed")
is_target_ceo = model.Relationship(f"{Person:node} is a target CEO")
rs = Role.ref()
model.where(rs.person(Person), rs.org(org), org.org_id == "S1",
            rs.role_type.in_(["Operating Partner", "Deal Team"]), model.not_(rs.end)).define(is_seed(Person))
model.where(Person.person_id.in_(["P3", "P5"])).define(is_target_ceo(Person))
d_seed = g_knows.distance(from_=is_seed)
d_tgt = g_knows.distance(from_=is_target_ceo)

# commercial bipartite graph over companies (supplier - customer)
links = model.data(pd.DataFrame({
    "sup": ["C4", "C4", "C4", "C4", "C5", "C5", "C5", "C5", "C3", "C3", "C7", "C7"],
    "cus": ["C8", "C9", "C10", "C11", "C8", "C9", "C10", "C12", "C11", "C13", "C12", "C13"]}))
g_comm = Graph(model, directed=False, weighted=False, node_concept=Company)
ca, cb = Company.ref(), Company.ref()
model.where(ca.org_id == links.sup, cb.org_id == links.cus).define(g_comm.Edge.new(src=ca, dst=cb))
is_platform = model.Relationship(f"{Company:node} is the platform")
model.where(Company.org_id == "C4").define(is_platform(Company))
jac = g_comm.jaccard_similarity(from_=is_platform)

# deal-flow graph over all organizations (advisor-target and buyer-target edges)
deals = model.data(pd.DataFrame({
    "deal_id": ["D1", "D2", "D3", "D4", "D5", "D6"],
    "advisor": ["I1", "I1", "I2", "I3", "I3", "I3"],
    "buyer": ["S1", "S2", "S1", "S2", "", ""],
    "target": ["C2", "C3", "C1", "C6", "C11", "C12"]}))
g_flow = Graph(model, directed=False, weighted=False, node_concept=Organization)
oa, ob = Organization.ref(), Organization.ref()
model.where(oa.org_id == deals.advisor, ob.org_id == deals.target).define(g_flow.Edge.new(src=oa, dst=ob))
model.where(oa.org_id == deals.buyer, ob.org_id == deals.target).define(g_flow.Edge.new(src=oa, dst=ob))


# ---------------------------------------------------------------- query harness
OUT = Path(__file__).parent / "out" / (sys.argv[1] if len(sys.argv) > 1 else "run1")
OUT.mkdir(parents=True, exist_ok=True)
TIMINGS = []


def run(name, fn, sort=None):
    t0 = time.time()
    try:
        df = fn()
        if sort:
            df = df.sort_values(sort).reset_index(drop=True)
        secs = time.time() - t0
        TIMINGS.append((name, round(secs, 1), "OK", len(df)))
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"\n=== {name} ({secs:.1f}s, {len(df)} rows)\n{df.to_string(index=False)}", flush=True)
        return df
    except Exception as e:  # noqa: BLE001
        secs = time.time() - t0
        TIMINGS.append((name, round(secs, 1), "FAIL", repr(e)[:300]))
        print(f"\n=== {name} FAILED ({secs:.1f}s)\n{traceback.format_exc()[-3000:]}", flush=True)
        return None


def q_counts():
    return model.select(
        aggs.count(Organization).alias("orgs"), aggs.count(Company).alias("companies"),
        aggs.count(Sponsor).alias("sponsors"), aggs.count(Intermediary).alias("intermediaries"),
        aggs.count(Person).alias("persons"), aggs.count(Role).alias("roles"),
        aggs.count(Sector).alias("sectors")).to_df()


def q_org_types():
    return model.where(Role.org(org), Role.person(Person)).select(
        Role.role_id.alias("role_id"), Person.name.alias("person"), org.name.alias("org"),
        Role.start.alias("start"), Role.end.alias("end"), Role.eff_end.alias("eff_end"),
        Role.eff_end_match.alias("eff_end_match")).to_df()


def q_ancestors():
    return model.where(s1.ancestor(s2)).select(s1.sector_id.alias("sector"), s2.sector_id.alias("ancestor")).to_df()


def q_thesis():
    return model.where(Company.in_thesis()).select(Company.org_id.alias("company"), Company.name.alias("name")).to_df()


def q_overlap():
    return model.where(Overlap.r1(ra), Overlap.r2(rb), ra.person(pa), rb.person(pb)).select(
        pa.name.alias("p1"), pb.name.alias("p2"), Overlap.days.alias("days"),
        math.round(Overlap.years, 2).alias("years"), Overlap.gap_days.alias("gap_days")).to_df()


def q_knows():
    return model.where(Knows.p1(pa), Knows.p2(pb)).select(
        pa.person_id.alias("p1"), pb.person_id.alias("p2"), Knows.strength.alias("strength"),
        Knows.n_sources.alias("n_sources"), Knows.evidence.alias("evidence")).to_df()


def q_sector_aggs():
    top, cs = Sector.ref(), Sector.ref()
    return model.where(Company.sector(cs), cs.under(top), top.level == 1).select(distinct(
        top.name.alias("l1_sector"), aggs.count(Company).per(top).alias("n"),
        aggs.sum(Company.ebitda).per(top).alias("sum_ebitda"),
        aggs.max(Company.ebitda).per(top).alias("max_ebitda"))).to_df()


def q_rank_decile():
    return model.select(Company.org_id.alias("company"), Company.ebitda.alias("ebitda"),
                        Company.ebitda_rank.alias("rank"), Company.ebitda_decile.alias("decile")).to_df()


def q_score():
    return model.select(Company.org_id.alias("company"), Company.name.alias("name"),
                        Company.score.alias("score"), Company.tier.alias("tier"),
                        Company.n_none.alias("n_none"), Company.why.alias("why")).to_df()


def q_top3():
    return model.where(aggs.limit(3, asc(0 - Company.score), asc(Company.name))).select(
        Company.name.alias("name"), Company.score.alias("score"),
        rank(asc(0 - Company.score), asc(Company.name)).alias("rank")).to_df()


def q_graph_sizes():
    rows = []
    for gname, g in [("knows_unweighted", g_knows), ("knows_weighted", g_knows_w),
                     ("commercial", g_comm), ("dealflow", g_flow)]:
        nn = model.select(g.num_nodes().alias("n")).to_df()
        ne = model.select(g.num_edges().alias("n")).to_df()
        rows.append({"graph": gname, "num_nodes": int(nn["n"].iloc[0]), "num_edges": int(ne["n"].iloc[0])})
    return pd.DataFrame(rows)


def q_dist_seed():
    s, t, L = Person.ref(), Person.ref(), Integer.ref()
    return model.where(d_seed(s, t, L), is_target_ceo(t)).select(
        s.person_id.alias("seed"), t.person_id.alias("ceo"), L.alias("hops")).to_df()


def q_path_nodes():
    s, t, m = Person.ref(), Person.ref(), Person.ref()
    a, b, L = Integer.ref(), Integer.ref(), Integer.ref()
    return model.where(d_seed(s, t, L), is_target_ceo(t), d_seed(s, m, a), d_tgt(t, m, b),
                       a + b == L, a > 0, a < L).select(
        s.person_id.alias("seed"), t.person_id.alias("ceo"), L.alias("L"),
        m.person_id.alias("mid"), a.alias("d_seed_mid")).to_df()


def q_path_2hop():
    s, m, t = Person.ref(), Person.ref(), Person.ref()
    k1, k2 = Knows.ref(), Knows.ref()
    return model.where(is_seed(s), is_target_ceo(t), s.knows(m), m.knows(t), d_seed(s, t, 2),
                       model.not_(is_seed(m))).select(
        s.name.alias("seed"), m.name.alias("via"), t.name.alias("ceo")).to_df()


def q_jaccard():
    u, v, sc = Company.ref(), Company.ref(), Float.ref()
    return model.where(jac(u, v, sc), u != v).select(
        u.org_id.alias("platform"), v.org_id.alias("candidate"), sc.alias("jaccard")).to_df()


def q_louvain():
    lab = g_comm.louvain(randomization_seed=42)
    c_, l_ = Company.ref(), Integer.ref()
    return model.where(lab(c_, l_)).select(c_.org_id.alias("company"), l_.alias("community")).to_df()


def q_centrality():
    bc = g_flow.betweenness_centrality(num_pivots=1000)
    pr = g_flow.pagerank()
    o_, b_, p_ = Organization.ref(), Float.ref(), Float.ref()
    return model.where(bc(o_, b_), pr(o_, p_)).select(
        o_.org_id.alias("org"), b_.alias("betweenness"), p_.alias("pagerank")).to_df()


def q_from_and_to():
    g_knows.distance(from_=is_seed, to=is_target_ceo)
    return pd.DataFrame()


if __name__ == "__main__":
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    plan = [
        ("01_counts", q_counts, None), ("01_roles", q_org_types, ["role_id"]),
        ("02_ancestors", q_ancestors, ["sector", "ancestor"]), ("02_thesis", q_thesis, ["company"]),
        ("03_overlap", q_overlap, ["p1", "p2"]), ("04_knows", q_knows, ["p1", "p2"]),
        ("05_sector_aggs", q_sector_aggs, ["l1_sector"]), ("05_rank_decile", q_rank_decile, ["company"]),
        ("06_score", q_score, ["company"]), ("05_top3", q_top3, ["rank"]),
        ("07_graph_sizes", q_graph_sizes, ["graph"]), ("08_dist_seed", q_dist_seed, ["seed", "ceo"]),
        ("08_path_nodes", q_path_nodes, ["seed", "ceo", "mid"]), ("08_path_2hop", q_path_2hop, ["seed", "via"]),
        ("08_from_and_to", q_from_and_to, None),
        ("09_jaccard", q_jaccard, ["candidate"]), ("10_louvain", q_louvain, ["company"]),
        ("11_centrality", q_centrality, ["org"]),
    ]
    for name, fn, sort in plan:
        if only and not any(name.startswith(p) for p in only):
            continue
        run(name, fn, sort)
    print("\n=== TIMINGS")
    for row in TIMINGS:
        print(row)
    pd.DataFrame(TIMINGS, columns=["query", "secs", "status", "rows_or_error"]).to_csv(OUT / "_timings.csv", index=False)
