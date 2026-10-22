# PyRel cheatsheet for P3/P4 (verified on relationalai 1.27.1, live engine pe_demo_logic)

Owner: Scout (R10 support). Run on 2026-10-22, against RAI_DEMO_PE_DEALS.DEAL_GRAPH SCOUT_* toy tables (now dropped).
Every snippet below comes from `scripts/scout/scout_model.py` or `scripts/scout/probe_inline.py`, and each one
ran with the output shown. Full outputs are in `scripts/scout/out/run1/*.csv`, and `run2` is identical
(`diff -r` is clean). The rule throughout: the package wins over the skills, and the conflicts are listed in section 14.

Compiler: default `reasoners.logic.lqp.compiler = legacy`. Every limitation below is for **legacy** unless it says otherwise.

## 0. Timing (wall clock, warm engine, toy data)

| Step | secs |
|---|---|
| First query of a fresh process (compile + new streams for 6 new tables) | 44-72 (first ever), 21-23 (later) |
| Each later rules query | 2.6-4 |
| First graph query (`num_nodes`/`num_edges` on 4 graphs, 8 selects) | 54 |
| distance / jaccard / path joins | 3-6 |
| louvain | 9 |
| betweenness (exact) + pagerank | 13-19 |

Local compile errors (unsupported construct) fail in about 1 s, before the engine is touched. One bad rule anywhere in the model fails
**every** query, because each query compiles all `define()`s.

## 1. Concepts, subtypes, Snowflake bindings

```python
from relationalai.semantics import Float, Integer, Model, String, Date, distinct
from relationalai.semantics.std import aggregates as aggs, datetime as dt, floats, math, numbers, strings
from relationalai.semantics.std.aggregates import asc, desc, rank
from relationalai.semantics.reasoners.graph import Graph
S = "RAI_DEMO_PE_DEALS.DEAL_GRAPH"
AS_OF = dt.date(2026, 10, 1)          # PyRel expression. NOT datetime.date(...) (see section 13)
model = Model("pe_scout")

Organization = model.Concept("Organization", identify_by={"org_id": String})
Organization.name = model.Property(f"{Organization} has {String:name}")
Company = model.Concept("Company", extends=[Organization])        # inherits org_id identity
Sponsor = model.Concept("Sponsor", extends=[Organization])
Intermediary = model.Concept("Intermediary", extends=[Organization])
Company.sector = model.Property(f"{Company} operates in {Sector:sector}")
Company.ebitda = model.Property(f"{Company} has {Float:ebitda}")   # Snowflake NUMBER(10,2) -> Float works
Company.is_founder_owned = model.Relationship(f"{Company} is founder owned")  # BOOLEAN -> unary flag
Sector.level = model.Property(f"{Sector} has {Integer:level}")     # NUMBER(1) -> Integer works
Role.start = model.Property(f"{Role} starts {Date:start}")         # DATE -> Date works
Role.org = model.Property(f"{Role} at {Organization:org}")         # polymorphic FK -> supertype

co = model.Table(f"{S}.SCOUT_COMPANY")                              # columns are UPPERCASE
model.define(c := Company.new(org_id=co.COMPANY_ID), c.name(co.NAME),
             c.sector(Sector.filter_by(sector_id=co.SECTOR_ID)))
model.define(Company.filter_by(org_id=co.COMPANY_ID).ebitda(co.EBITDA_MUSD))   # nullable col: own define
model.where(co.IS_FOUNDER_OWNED == True).define(Company.filter_by(org_id=co.COMPANY_ID).is_founder_owned())
ro = model.Table(f"{S}.SCOUT_ROLE")
model.define(r := Role.new(role_id=ro.ROLE_ID), r.person(Person.filter_by(person_id=ro.PERSON_ID)),
             r.org(Organization.filter_by(org_id=ro.ORG_ID)),            # resolves Company/Sponsor/Intermediary
             r.role_type(ro.ROLE_TYPE), r.start(ro.START_DATE))
model.define(Role.filter_by(role_id=ro.ROLE_ID).end(ro.END_DATE))           # NULL end -> no fact
# self-FK: use two refs, not two filter_by on the same concept (filter_by binds the base variable)
child, par = Sector.ref(), Sector.ref()
model.where(child.sector_id == sec.SECTOR_ID, par.sector_id == sec.PARENT_ID).define(child.parent(par))
```
Output: `orgs 18, companies 13, sponsors 2, intermediaries 3, persons 9, roles 13, sectors 11`, which matches the
source rows. The C10 row (NULL EBITDA) and the open-ended roles (NULL END_DATE) all loaded.
`aggs.count(Company)` on a subtype works in `select`. The skill's "count the parent" warning did not apply here.

`filter_by` prints a DeprecationWarning (`use Organization.lookup(...)`). `lookup` uses a **fresh ref**, while
`filter_by` constrains the base variable. Everything above ran with `filter_by`. A `lookup` rewrite is UNVERIFIED on the engine.

## 2. Recursive closure (sector > subsector > niche) and thesis membership

```python
Sector.ancestor = model.Relationship(f"{Sector} has ancestor {Sector:anc}")
Sector.under = model.Relationship(f"{Sector} is under or equal to {Sector:top}")   # reflexive
s1, s2, s3 = Sector.ref(), Sector.ref(), Sector.ref()
model.where(s1.parent(s2)).define(s1.ancestor(s2))
model.where(s1.parent(s2), s2.ancestor(s3)).define(s1.ancestor(s3))        # recursion just works
model.define(Sector.under(Sector))
model.where(Sector.ancestor(s3)).define(Sector.under(s3))

niche, inc, exc = Sector.ref(), Sector.ref(), Sector.ref()
model.where(Company.sector(niche), niche.under(inc), inc.is_include(),
            model.not_(niche.under(exc), exc.is_exclude())).define(Company.in_thesis())   # nested exclude
```
Output: 13 ancestor pairs (for example SC3->SC2, SC3->SC1, SC10->SC11, SC10->SC9). With include {SC2, SC6} and exclude {SC4},
the thesis is C1, C2, C3, C4, C5, C7, C8, C9, C10. The excluded-niche companies C11-C13 and the vet-pharma decoy C6 are out.

## 3. Dates against AS_OF: open ends, tenure overlap, windows

```python
model.define(Role.eff_end(Role.end))                                   # two-rule default for open end
model.where(model.not_(Role.end)).define(Role.eff_end(AS_OF))          # (Role.end | AS_OF does NOT work)

pd_ = dt.date.period_days                                              # Integer days, end - start
# overlap = min(e1,e2) - max(s1,s2) = min of the four (end - start) differences; no date min/max needed
ov_days = math.minimum(math.minimum(pd_(ra.start, ra.eff_end), pd_(rb.start, rb.eff_end)),
                       math.minimum(pd_(rb.start, ra.eff_end), pd_(ra.start, rb.eff_end)))
model.where(ra.org == rb.org, ra.person(pa), rb.person(pb), pa.person_id < pb.person_id,
            d := ov_days, d >= 365).define(
    o := Overlap.new(r1=ra, r2=rb), o.days(d), o.years(floats.float(d) / 365.25),
    o.gap_days(math.maximum(pd_(ra.eff_end, AS_OF), pd_(rb.eff_end, AS_OF))))   # days since overlap ended
WSTART = dt.date.subtract(AS_OF, dt.months(24))                        # also dt.date.add, dt.years, dt.days
Interaction.on <- dt.date.fromisoformat(ixd.on)                        # ISO strings from inline data -> Date
```
Output (03_overlap):
```
Dana Okafor Elena Marsh 1582 4.33 2650 | Dana Okafor Tom Brennan 2460 6.74 0 | Elena Marsh Walter Kim 487 1.33 0
Grace Liu Ivy Iron 1460 4.00 1735      | Walter Kim Grace Liu 1644 4.50 0    | Elena Marsh Grace Liu 487 1.33 0
```
These pairs were correctly rejected: Tom/Victor (shared employer, 2008-2011 versus 2013-2020, negative overlap) and Tom/Sam (181 days, under 12 months).
`math.minimum`/`maximum` accept only numbers, not Dates, so do the date math in `period_days` space.
`dt.date.diff("month", a, b)` exists but is UNVERIFIED. ">= 12 months" was tested as `>= 365` days.

## 4. Derived Knows(p1, p2) from several rule sources, with strength and evidence

```python
Tie = model.Concept("Tie", identify_by={"a": Person, "b": Person, "kind": String, "key": String})
# K1 tenure overlap (two exclusive rules: fresh vs stale, stale halves strength)
model.where(ov.r1(ra), ov.r2(rb), ra.person(pa), rb.person(pb), ra.org(org), ov.gap_days <= 3652).define(
    t := Tie.new(a=pa, b=pb, kind="K1", key=strings.concat(ra.role_id, "-", rb.role_id)),
    t.strength(math.minimum(1.0, ov.years / 4.0)),
    t.evidence(strings.concat("K1 overlap at ", org.name, ", ", strings.string(math.round(ov.years, 2)), " years")))
# K3 count of positive interactions in window, grouped per pair (HAVING-style bind with :=)
n_pos = aggs.count(ix).per(pa, pb).where(ix.by(pa), ix.other(pb), ix.sentiment == "positive",
                                          ix.on >= WSTART, ix.on <= AS_OF)
model.where(n := n_pos, pa.person_id < pb.person_id).define(
    t := Tie.new(a=pa, b=pb, kind="K3", key="crm"),
    t.strength(math.minimum(1.0, 0.4 + 0.2 * floats.float(n))), t.evidence(...))
Knows = model.Concept("Knows", identify_by={"p1": Person, "p2": Person})
model.define(Knows.new(p1=Tie.a, p2=Tie.b))
tt = Tie.ref()
model.where(tt.a == Knows.p1, tt.b == Knows.p2).define(
    Knows.strength(aggs.max(tt.strength).per(Knows)), Knows.n_sources(aggs.count(tt).per(Knows)))
# evidence of the strongest tie (argmax). string_join is NOT available on legacy (section 13)
model.where(tt.a == Knows.p1, tt.b == Knows.p2,
            rank(asc(0.0 - tt.strength), asc(tt.kind), asc(tt.key)).per(Knows) == 1).define(
    Knows.evidence(tt.evidence))
Person.knows = model.Relationship(f"{Person} knows {Person:other}")        # symmetric view for path joins
model.where(Knows.p1(pa), Knows.p2(pb)).define(pa.knows(pb), pb.knows(pa))
```
Output (04_knows, 8 edges):
```
P1 P2 1.000 K1 overlap at Brightwater Dental, 4.33 years    P4 P8 0.800 K3 2 positive interactions in 24m
P2 P3 0.333 K1 overlap at Walnut Dental, 1.33 years         P8 P9 0.700 K2 co-participated in deal D9
```
The interaction from 2023-01-10 (outside 24 months) and the negative one were both excluded. Keep one ordering (`p1.id < p2.id`) in `Knows`
for undirected graphs, and use the symmetric `Person.knows` for hop joins.

## 5. Aggregations, rank, decile, top-k, tie-breaks

```python
top, cs = Sector.ref(), Sector.ref()
model.where(Company.sector(cs), cs.under(top), top.level == 1).select(distinct(
    top.name.alias("l1_sector"), aggs.count(Company).per(top).alias("n"),
    aggs.sum(Company.ebitda).per(top).alias("sum_ebitda"),
    aggs.max(Company.ebitda).per(top).alias("max_ebitda"))).to_df()
# rank: ALL keys must share one direction -> negate numeric keys for "desc, then name asc"
model.define(Company.ebitda_rank(rank(asc(0.0 - Company.ebitda), asc(Company.name))))
n_with = aggs.count(Company).where(Company.ebitda)
model.define(Company.ebitda_decile(numbers.integer(math.ceil(
    10.0 * floats.float(Company.ebitda_rank) / floats.float(n_with)))))
# top-k with tie-break
model.where(aggs.limit(3, asc(0 - Company.score), asc(Company.name))).select(
    Company.name.alias("name"), Company.score.alias("score"),
    rank(asc(0 - Company.score), asc(Company.name)).alias("rank")).to_df()
# empty-group default on an AGGREGATE does work:
model.define(Company.n_none(aggs.count(cp).per(Company).where(cp.company == Company, cp.code == "NONE") | 0))
```
Output: Healthcare n=5, sum 49.5, max 18.0. Industrials n=7, sum 108.0, max 44.0 (C10's NULL is counted in n but is not in the sum).
Ranks are unique (C11 and C12 both have 7.0, so they rank 9 and 10 by name). Decile C9 = ceil(10*11/12) = 10. Companies without EBITDA get no rank and no decile.
Top-3 at 35 points: Cust B, Envirolab, Samesite Testing, with Walnut Dental (also 35) cut by name. `n_none` = 0 for all rows.
There is no percentile aggregate. Use rank / count as above, and `ceil(0.25*N)`-position logic for quartiles.

## 6. Composite score from named components, tiers, explanation string

```python
Component = model.Concept("Component", identify_by={"company": Company, "code": String})
model.where(Company.in_thesis()).define(
    k := Component.new(company=Company, code="FIT_THESIS"), k.points(15), k.label("thesis fit 15"))
model.where(Company.ebitda >= 5.0, Company.ebitda <= 40.0).define(
    k := Component.new(company=Company, code="FIT_EBITDA"), k.points(10),
    k.label(strings.concat("EBITDA ", strings.string(Company.ebitda), "M in band 10")))
cp = Component.ref()
model.define(Company.score(aggs.sum(cp.points).per(Company).where(cp.company == Company) | 0))
model.where(Company.score >= 30).define(Company.tier("A"))
model.where(Company.score >= 20, Company.score < 30).define(Company.tier("B"))
model.where(Company.score < 20).define(Company.tier("C"))
# explanation: one String property per component, defaulted with not_() (NOT with | "")
for code, prop in [("FIT_THESIS", Company.why_thesis), ("FIT_EBITDA", Company.why_ebitda), ...]:
    model.where(cp.company == Company, cp.code == code).define(prop(Company, strings.concat(cp.label, "; ")))
    k_ = Component.ref()
    model.where(model.not_(k_.company == Company, k_.code == code)).define(prop(Company, ""))
model.define(Company.why(strings.concat(Company.why_thesis, Company.why_ebitda, Company.why_founder,
                                        "score ", strings.string(Company.score))))
```
Output: `C2 Walnut Dental 35 A "thesis fit 15; EBITDA 18.0M in band 10; founder owned 10; score 35"` and
`C10 Cust C 15 C "thesis fit 15; score 15"`. The finale adds one more `Component.new(...)` rule, and score, tier and why follow.
`strings.string(Float)` prints `18.0` and `4.5`, not padded. Use `math.round(x, 2)` first.

## 7. Graph over a derived relationship; weighted vs unweighted; size checks

```python
g_knows = Graph(model, directed=False, weighted=False, node_concept=Person)   # isolated persons included
model.define(g_knows.Edge.new(src=Knows.p1, dst=Knows.p2))
g_knows_w = Graph(model, directed=False, weighted=True, node_concept=Person)
model.define(g_knows_w.Edge.new(src=Knows.p1, dst=Knows.p2, weight=Knows.strength))   # Float weight
g_flow = Graph(model, directed=False, weighted=False, node_concept=Organization)   # supertype as nodes
model.where(oa.org_id == deals.advisor, ob.org_id == deals.target).define(g_flow.Edge.new(src=oa, dst=ob))
nn = model.select(g.num_nodes().alias("n")).to_df()       # one row, one int
ne = model.select(g.num_edges().alias("n")).to_df()
```
Output: knows 9 nodes / 8 edges (weighted and unweighted alike), commercial 13 / 12, dealflow 18 / 8.
Dealflow expected 10 edges. The two missing ones came from inline rows containing `""` (section 13).
`num_nodes()` counts every instance of `node_concept`, including isolated nodes.

## 8. distance(from_=) and the path identity

```python
is_seed = model.Relationship(f"{Person:node} is a Northwind seed")          # unary relationship over Node
model.where(rs.person(Person), rs.org(org), org.org_id == "S1",
            rs.role_type.in_(["Operating Partner", "Deal Team"]), model.not_(rs.end)).define(is_seed(Person))
d_seed = g_knows.distance(from_=is_seed)
d_tgt = g_knows.distance(from_=is_target_ceo)        # undirected => d(t, m) == d(m, t)
s, t, m = Person.ref(), Person.ref(), Person.ref(); a, b, L = Integer.ref(), Integer.ref(), Integer.ref()
model.where(d_seed(s, t, L), is_target_ceo(t), d_seed(s, m, a), d_tgt(t, m, b),
            a + b == L, a > 0, a < L).select(s.person_id.alias("seed"), t.person_id.alias("ceo"),
            L.alias("L"), m.person_id.alias("mid"), a.alias("d_seed_mid")).to_df()
# explicit 2-hop path with names
model.where(is_seed(s), is_target_ceo(t), s.knows(m), m.knows(t), d_seed(s, t, 2),
            model.not_(is_seed(m))).select(s.name.alias("seed"), m.name.alias("via"), t.name.alias("ceo"))
```
Output: dist `P1->P3 2, P4->P3 3`. The cold target P5 has **no row**, because unreachable pairs are absent, so use `model.not_` to say "cold".
Path nodes: `(P1,P3,L=2,mid=P2,1) (P4,P3,3,P1,1) (P4,P3,3,P2,2)`. 2-hop: `Dana Okafor -> Elena Marsh -> Walter Kim`.
`distance(from_=X, to=Y)` raises client-side: `ValueError: Simultaneous use of 'from_' and 'to' is not yet supported`.
An integer literal as a distance argument (`d_seed(s, t, 2)`) works as a filter.

## 9. jaccard_similarity from one node over a bipartite neighborhood

```python
g_comm = Graph(model, directed=False, weighted=False, node_concept=Company)
model.where(ca.org_id == links.sup, cb.org_id == links.cus).define(g_comm.Edge.new(src=ca, dst=cb))
is_platform = model.Relationship(f"{Company:node} is the platform")
model.where(Company.org_id == "C4").define(is_platform(Company))
jac = g_comm.jaccard_similarity(from_=is_platform)
u, v, sc = Company.ref(), Company.ref(), Float.ref()
model.where(jac(u, v, sc), u != v).select(u.org_id.alias("platform"), v.org_id.alias("candidate"), sc.alias("jaccard"))
```
Output: `C4 C5 0.6` (3 shared of 5), `C4 C3 0.2`. The zero-overlap decoy C7 is **absent** (it is not 0.0). The self-pair is filtered by `u != v`.

## 10. louvain with a fixed seed

```python
lab = g_comm.louvain(randomization_seed=42)
c_, l_ = Company.ref(), Integer.ref()
model.where(lab(c_, l_)).select(c_.org_id.alias("company"), l_.alias("community")).to_df()
```
Output: labels 1-7 (`C5,C9,C10 -> 1; C7,C12 -> 2; C4,C8 -> 3; C3,C11,C13 -> 4`; isolated C1, C2, C6 each get their own label).
The two runs were identical. Labels are arbitrary integers, so assert co-membership, not label values. The pandas column is Int128, so use `.astype(int)`.

## 11. betweenness_centrality (exact) and pagerank

```python
bc = g_flow.betweenness_centrality(num_pivots=1000)     # >= num_nodes() => exact Brandes
pr = g_flow.pagerank()
o_, b_, p_ = Organization.ref(), Float.ref(), Float.ref()
model.where(bc(o_, b_), pr(o_, p_)).select(o_.org_id.alias("org"), b_.alias("betweenness"), p_.alias("pagerank"))
```
Output, compared with networkx on the same 8 edges: `I1 16, C2 15, C3 15, S1 12, S2 12, C1 7, C6 7`, which
**exactly equals** `nx.betweenness_centrality(G, normalized=False)`. PageRank `I1 0.101954, C1 0.112537, C10 0.014493`
matches networkx to 6 decimals. Isolated nodes get bc 0.0 and pagerank (1-d)/N.
A RuleLoopWarning prints around the graph algorithm calls. It is harmless (library internals) and can be ignored.

## 12. Querying into pandas, deterministically

- Always `.alias()` every column, then `df.sort_values([...]).reset_index(drop=True)`. Row order out of `to_df()` is not guaranteed.
- `run1` and `run2` (separate processes) were byte-identical after sorting, for all 17 outputs including louvain and centrality.
- `select` is **left-outer** on properties: a missing value comes back as NaN/NaT/<NA>, and the row is not dropped
  (01_roles `end` = NaT for open roles). To drop such rows, filter with `where(X.prop)`.
- Date columns come back as pandas datetime64 (NaT for missing). Floats print full precision (0.333333).

## 13. Do not do this (each item was hit on 1.27.1)

1. `AS_OF = datetime.date(2026, 10, 1)` used in a rule fails with `AttributeError: 'datetime.date' object has no attribute '_source'`
   and breaks every query. Use `dt.date(2026, 10, 1)` (only str/int/float/bool are literal primitives).
2. `model.define(X.p(X.q | default))` when `X.q` is missing gives **no fact** (silently). Seen with `Role.end | AS_OF` and
   `Company.why_thesis | ""`. Use two rules: `define(X.p(X.q))` plus `where(model.not_(X.q)).define(X.p(default))`.
   (`aggs.<agg>(...).per(X) | 0` does work.)
3. `aggs.string_join(...)` in any rule or query fails with `AssertionError: only support ('sum','count','avg','min','max')` (legacy).
   Use argmax via `rank(...) == 1`, or per-component string properties plus `strings.concat`.
4. `rank(desc(a), asc(b))` or `aggs.limit(k, desc(a), asc(b))` fails with `Mixed orderings in rank/cumsum are not supported yet`.
   Write `rank(asc(0 - a), asc(b))`. The `direct` compiler also rejects mixed orderings.
5. `model.data(df)` where any cell in a row is `""` or None: on legacy the **whole row disappears**, even from rules
   that never read that column (probe: 3 rows in, 1 row visible). Snowflake `model.Table` rows with NULLs are fine.
   Never put empty or NULL cells in inline data. Split the frame or use a sentinel.
6. Combining `distance(from_=..., to=...)` raises a ValueError, and `between=` raises. Use two `from_` calls (section 8).
7. Expecting 0.0 for non-similar pairs from jaccard, or a distance row for unreachable nodes. Both are absent. Use `not_`.
8. `math.minimum`/`maximum` on Dates (Number only). Use `period_days` arithmetic.
9. Two `Concept.filter_by(...)` calls on the same concept in one rule (they share the base variable). Use `.ref()`s.
10. Relying on `rank()` without a unique final key. Ties are broken by an internal order. Always end with an id or name.
11. Re-adding `deployment:` to raiconfig, or switching `RAI_LQP_COMPILER=direct` project-wide. On `direct`, string_join
    ran but returned `D2,D1,D3`, which is not the documented ascending order. Stay on legacy.
12. One unsupported construct anywhere in a model fails all its queries. Develop new rules incrementally and keep the
    known-bad constructs above out of `rules.py`.

## 14. Skill vs package (package wins; logged in DECISIONS.md)

| Skill says | 1.27.1 does |
|---|---|
| `Entity.prop \| "unknown"` gives defaults (rai-rules-authoring) | No fact in `define` when prop is missing; use `not_()` |
| `string_join` is available (rai-querying recipe) | Not on the legacy compiler (the default) |
| `rank(desc(...))` plus `asc` tie-break examples | Mixed orderings rejected; negate the numeric key |
| `filter_by` is the FK idiom (rai-pyrel-coding) | Deprecated; `lookup` suggested (fresh ref semantics; UNVERIFIED on engine) |
| Louvain is non-deterministic (rai-graph-analysis) | Seeded (`randomization_seed`, default 8675309); identical across runs |
| `count(Subtype)` raises TyperError (rai-querying) | `aggs.count(Company)` on a subtype worked in `select` |
| Snowflake NUMBER(p,s>0) maps to Float | Confirmed: NUMBER(10,2) bound to Float without casting |

Reproduce: `scripts/scout/scout_tables.py create`, then `scripts/scout/scout_model.py run1 [sections]`, then
`scripts/scout/scout_tables.py drop`. Section filters: `01,02,...,11` (prefix match on query names).
