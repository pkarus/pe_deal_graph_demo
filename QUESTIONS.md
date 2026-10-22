# QUESTIONS.md - Hero questions for the Northwind deal-graph demo (R03, attempt 1)

Owner: R03 Question Designer. Readers: R04 (critic), R05 (generator), R06 (oracle), R08-R11, R14-R16.
All data is synthetic. Every name below is illustrative. R05 picks the final fictional names and runs the collision check. Every entity has a stable **role key** (for example `T_WARM`). The keys live only in `data/golden/`. They never become IDs or columns in Snowflake.

## 0. Conventions that every question uses

### 0.1 The clock

`AS_OF = 2026-10-01` (CONFIG `AS_OF_DATE`). No rule calls `today()`. Every window is defined relative to `AS_OF`. The resolved dates below are convenience copies only. If `AS_OF` changes, recompute them and leave the rules as written.

| Symbol | Definition | Resolved |
|---|---|---|
| `T` | AS_OF | 2026-10-01 |
| `T-6m` | AS_OF minus 6 months | 2026-04-01 |
| `T-12m` | AS_OF minus 12 months | 2025-10-01 |
| `T-18m` | AS_OF minus 18 months | 2025-04-01 |
| `T-24m` | AS_OF minus 24 months | 2024-10-01 |
| `T-5y` | AS_OF minus 5 years | 2021-10-01 |
| `T-10y` | AS_OF minus 10 years | 2016-10-01 |
| `T-15y` | AS_OF minus 15 years | 2011-10-01 |
| `T-20y` | AS_OF minus 20 years | 2006-10-01 |
| `T+18m` | AS_OF plus 18 months | 2028-04-01 |
| `VINTAGE_CUT` | year(AS_OF) - 8 | 2018 |

Windows are closed on both ends (`start <= d <= end`) unless stated otherwise. An open role or ownership end date (NULL) means "still current". It is evaluated as `T`.

### 0.2 Corrections adopted from the R02 domain brief (section 5 of `research/domain_brief.md`)

- **Exit window** = the sponsor has held the company for 5+ years **and** the owning fund is 8+ years past vintage. Five years alone is not a signal.
- **Add-on share**: on stage say "most US buyout deals are add-ons" or "the majority". Never show a number.
- **Competition**: Affinity **and DealCloud** both advertise warm-intro paths. Q-PATH is never pitched as "we find intros". The pitch is composition: fit plus readiness plus access plus portfolio context, with evidence on every hop, in their Snowflake.
- **Transaction type is three columns**: `deal_role` (platform, add_on), `seller_type` (founder_family, sponsor, corporate) and `structure` (control_buyout, majority_recap, minority, dividend_recap). A recap is identified by `structure`, never by a single `type` column.
- Multiples stay within 6-12.5x. "Auctions price out returns" is never said. Say "firms invest in off-market flow to avoid fully competitive auctions".

### 0.3 Data elements the questions need (R05 owns the final schema)

These are additions to section 8.1. Each one is small. Total rows stay under the 16,000 cap.

| Element | Why |
|---|---|
| `SECTOR(sector_id, name, level, parent_id)`: 3 levels (sector > subsector > niche); companies attach to a niche | hierarchy closure (Q-SCORE, Q-ADDON, Q-FLOW) |
| `FUND_FOCUS(fund_id, sector_id, mode in {include, exclude}, margin_benchmark_pct)`: Fund IV includes nodes at **mixed levels** | thesis tree; margin benchmark per focus area |
| `REGION(region_id, name, level, parent_id)`: state > census region > US | US-only gate, whitespace states |
| `COMPANY(company_id, name, sector_id, hq_region_id, revenue_musd, ebitda_musd, is_public)` | fit |
| `COMPANY_SITE(company_id, region_id)`: operating states, roughly 300-600 rows | Q-ADDON whitespace |
| `ROLE_HISTORY(role_id, person_id, org_id, role_type, start_date, end_date, is_founder)`; role_type in {CEO, CFO, COO, President, Board, Operating Partner, Deal Team, Banker} | Knows, readiness |
| `OWNERSHIP(company_id, fund_id, start_date, end_date, equity_invested_musd)` | exit window, conflicts, concentration |
| `FUND(fund_id, sponsor_id, name, vintage_year, size_musd)` | exit window |
| `TRANSACTION(txn_id, target_id, close_date, deal_role, seller_type, structure, ev_musd, ev_ebitda)` | Q-FLOW, recaps |
| `TRANSACTION_PARTY(txn_id, org_id, party_role in {buyer, seller, sell_side_advisor, buy_side_advisor, lender_arranger, co_investor}, fund_id NULL, lead_person_id NULL)` | the deal graph; person-level deal co-participation |
| `COMMERCIAL_LINK(supplier_id, customer_id, value_band)` | Q-ADDON, conflicts |
| `CRM_INTERACTION(interaction_id, our_person_id, counterparty_person_id NULL, counterparty_org_id NULL, date, channel, sentiment in {positive, neutral, negative})` | access, Knows, coverage |
| `PIPELINE(company_id, stage, est_equity_check_musd)` | "not in CRM", Q-CONFLICT |
| `COMPANY_SIGNAL(signal_id, company_id, signal_type, signal_date, event_date NULL, intermediary_id NULL)`. Scored types: BANKER_ENGAGED, DEBT_MATURITY. Unscored noise types: ADDON_ANNOUNCED, PRESS_RELEASE, HIRING_SURGE, AWARD, DEBT_REFINANCED | readiness; naive screen |

"Northwind people" (`OUR_SEEDS`) are persons with a **current** Northwind role of type Deal Team or Operating Partner. Managing Partners and MDs are Deal Team.

### 0.4 Verified API surface (installed package, not memory)

Command and output, verbatim (relationalai 1.27.1, Python 3.13 venv):

```
$ .venv/bin/python -c "from relationalai.semantics.reasoners.graph import Graph; print(sorted(m for m in dir(Graph) if not m.startswith('_')))"
['Edge', 'EdgeDst', 'EdgeSrc', 'EdgeWeight', 'Node', 'adamic_adar', 'average_clustering_coefficient', 'betweenness_centrality', 'common_neighbor', 'cosine_similarity', 'debug_edges_missing_required_weight', 'debug_edges_with_invalid_weight', 'debug_edges_with_superfluous_weight', 'debug_edges_without_destinations', 'debug_edges_without_sources', 'debug_multi_edges', 'degree', 'degree_centrality', 'diameter_range', 'directed', 'distance', 'eigenvector_centrality', 'indegree', 'infomap', 'inneighbor', 'is_acyclic', 'is_connected', 'jaccard_similarity', 'label_propagation', 'library', 'local_clustering_coefficient', 'louvain', 'neighbor', 'num_edges', 'num_nodes', 'num_triangles', 'outdegree', 'outneighbor', 'pagerank', 'preferential_attachment', 'reachable', 'triangle', 'triangle_count', 'unique_triangle', 'weakly_connected_component', 'weighted', 'weighted_degree', 'weighted_indegree', 'weighted_outdegree']
```

Signatures we rely on (`inspect.signature`):

```
Graph.__init__(self, model, *, directed: bool, weighted: bool, aggregator=None, node_concept=None, edge_concept=None, edge_src_relationship=None, edge_dst_relationship=None, edge_weight_relationship=None)
distance(self, *, full=None, from_=None, to=None, between=None) -> Relationship          # distance(start, end, length); Integer length when unweighted
jaccard_similarity(self, *, full=None, from_=None, to=None, between=None) -> Relationship # jaccard_similarity(u, v, score)
louvain(self, max_levels=1, max_sweeps=20, level_tolerance=0.01, sweep_tolerance=0.0001, randomization_seed=8675309, *, diagnostic_info=False)
betweenness_centrality(self, num_pivots=100, *, diagnostic_info=False)
pagerank(self, damping_factor=0.85, tolerance=1e-06, max_iter=200, *, diagnostic_info=False)
reachable(self, *, full=None, from_=None, to=None, between=None)
weakly_connected_component(self, *, of=None)
Model.path(self, *args) -> PathPattern ; PathPattern methods: all, all_paths, all_shortest, any, any_shortest, exists, repeat, where
std.datetime.date: add, subtract, diff(part, start, end), period_days(start, end), fromisoformat
std.aggregates: count, sum, min, max, avg, rank, rank_desc, top, bottom, string_join, per
```

**Where sections 5 and 7 assume something the package does not do (design adjusted):**

1. **`distance` cannot combine `from_` and `to`.** The docstring says simultaneous use "is not yet supported", and `between` raises. Path reconstruction therefore uses two single-sided calls on the **undirected** Knows graph: `distance(from_=OurSeeds)` and `distance(from_=TargetCEOs)`. Because the graph is undirected, d(m, t) = d(t, m). A node m lies on a shortest s-t path iff `d(s,m) + d(t,m) = d(s,t)`. The concrete hop sequences for length 2 or 3 then come from fixed-length Knows joins in rules (section 5 R10 still holds).
2. **Shortest-path selectors raise.** `path(...).any_shortest()`, `all_shortest()`, `any()`, `exists()`, `all().count()`, `undirected()` and `reverse()` all raise `PathAPINotImplemented` in 1.27.1. What does exist (PREVIEW) is enumeration: `model.path(Person.knows.repeat(1, 3)).all().paths()`. The skill text shows `.all_paths()`, which the package marks **deprecated**: write `.all().paths()` (the package wins). R10 may use enumeration only as a cross-check, filtered to `length == distance`. Because `undirected()` is not implemented, Knows must then be materialized in both directions. The primary method is item 1.
3. **`betweenness_centrality` is sampled by default.** It uses 100 random pivots (Brandes-Pich), which makes it non-deterministic and approximate on graphs with more than 100 nodes. It becomes exact Brandes only when `num_pivots >= |V|`. Q-FLOW therefore calls `betweenness_centrality(num_pivots=N)` with `N >= num_nodes()`, read first and asserted. Values are unnormalized: for each unordered pair in an undirected graph the count matches networkx `betweenness_centrality(G, normalized=False)`. Weighted graphs raise `NotImplementedError`, so the deal-flow graph is unweighted.
4. **`louvain` is seeded** (`randomization_seed=8675309`), so it is repeatable for identical input. A data change can still move labels. Louvain is used for explorer coloring only, with no golden assertion on labels.
5. **`jaccard_similarity` drops pairs with no shared neighbor.** "Structurally unsupported" pairs are absent, not 0.0. The Q-ADDON decoy is therefore asserted as **absent from the similarity result**. `from_` plus `to` is allowed for Jaccard (unlike distance).
6. There is no `shortest_path` method on `Graph`. Nothing in this file assumes one.

---

## 1. The story in one breath (section 7.5 arc)

"Your CRM has about 200 companies in pipeline; the market has about 1,200 in your sweet spot."

- **Act 1, Q-SCORE**: six Tier-A targets, two of them not in your CRM.
- **Act 2, Q-PATH**: for the top three, the #1 is three hops away through a banker, the #2 is two hops away through our Operating Partner (with a stale tie correctly ranked second), and the #3 is honestly **cold**, even though a shared-employer SQL join says "warm".
- **Act 3, Q-ADDON**: the best Granite add-on is in a sibling niche that a same-niche SQL screen never sees.
- **Act 4, Q-FLOW**: the boutique that controls founder-owned healthcare flow is one we have touched once in two years, and it ran the cold #3 target's last recap. That gives the room the way in.
- **Finale**: one sentence of new rules. The warm path flips the top of the list, the Q-SCORE conflict lookalike drops out, and a Tier-B name rises into Tier A.

---

## 2. Planted cast (shared across questions)

The scored components are defined in Q-SCORE. Score = Fit + Readiness + Access. Tier A >= 70, B 50-69, C < 50.

| Key | Illustrative name | Thesis area > niche | EBITDA $M / revenue $M | Ownership (as of T) | In PIPELINE | Fit | Readiness | Access (CRM) | Q-SCORE total | Q-SCORE rank |
|---|---|---|---|---|---|---|---|---|---|---|
| T_BANKER | Larkspur Revenue Partners | Tech-enabled business services > Healthcare Revenue Cycle Services | 26.0 / 130 | Ironbridge Capital Fund I (vintage 2016) since 2019-04-15 (majority recap) | yes | 30 | 50 | 10 | **90** | 1 |
| T_WARM | Bayside Pediatric Therapy Group | Healthcare services > Pediatric Therapy Clinics | 22.0 / 140 | founder-owned | yes | 30 | 45 | 10 | **85** | 2 |
| T_COLD | Saltmarsh Home Infusion | Healthcare services > Home Infusion Services | 18.0 / 115 | Copperline Partners Fund II (vintage 2017) since 2020-09-01 (control buyout) | **no** | 30 | 50 | 0 | **80** | 3 |
| CONF | Keystone Clinical Supply | Specialty distribution > Medical & Lab Supply Distribution | 14.0 / 140 | founder-owned | yes (Tracking) | 30 | 45 | 0 | **75** | 4 |
| T_5 | Quarry Records Retrieval | Tech-enabled business services > Records Retrieval & Litigation Support | 8.5 / 42 | founder-owned | yes | 25 | 40 | 10 | **75** | 5 |
| T_6 | Fenwick Food Safety Labs | Industrial TIC > Food Safety Testing | 12.0 / 66 | Tamarack Equity Fund II (vintage 2015) since 2020-06-30 | **no** | 30 | 40 | 0 | **70** | 6 |
| NM_B | Alder Creek Dental Partners | Healthcare services > Dental Service Organizations | 16.0 / 100 | founder-owned | yes (Tracking) | 30 | 35 | 0 | 65 (Tier B) | - |

Ties are broken by: score desc, then readiness desc, then fit desc, then company name asc. CONF and T_5 tie at 75. CONF ranks first because its readiness is 45 against 40.

Other planted actors:

| Key | Illustrative name | Role |
|---|---|---|
| NW | Northwind Equity Partners | us (Sponsor); Fund II (vintage 2014, historical), Fund III (vintage 2019, harvesting), Fund IV (vintage 2023, $1,200M) |
| OP | Marcus Whitfield | Northwind Operating Partner (current) |
| MP | Dana Okafor | Northwind Managing Partner (Deal Team, current) |
| VP | Priya Raman | Northwind Vice President (Deal Team, current since 2017-02-01) |
| MD_MER | Tom Brennan | Northwind Managing Director (Deal Team, current) |
| OP2 | Grace Liu | Northwind Operating Partner (current) |
| BRIGHT | Brightwater Dental | former Northwind Fund II portfolio company (Fund II 2014-06-30 to 2020-02-14; then Ridgeback Partners Fund III 2020-02-14 to present) |
| CFO_W | Elena Marsh | T_WARM CFO since 2025-06-01; Brightwater CFO 2015-03-01 to 2025-04-30 |
| CEO_W | Daniel Reyes | T_WARM founder CEO since 2008-01-01 |
| X_STALE | Walter Kim | T_WARM Board since 2023-01-15; at Old Harbor Health 1997-01-06 to 2001-12-14 |
| Y_BANK | Sofia Brandt | Banker at Cedar Row Partners since 2017-01-09; at Lakeshore Securities 2012-06-04 to 2016-12-16 |
| B_BANK | Nathan Cole | Managing Director, Cedar Row Partners since 2014-05-01; lead sell-side banker on T_BANKER's 2019-04-15 majority recap |
| CEO_B | Ruth Adeyemi | T_BANKER founder CEO since 2005-03-01 (has a COO since 2020-02-03) |
| CEO_C | Victor Hale | T_COLD CEO since 2020-11-02; Meridian Lab Services 2013-03-04 to 2020-08-31 |
| HL | Harbor Lane Advisors | healthcare-services boutique; arranged T_COLD's 2023-05-18 dividend recap |
| HL_MD | Celia Navarro | Harbor Lane MD, lead on T_COLD's dividend recap |
| CEDAR | Cedar Row Partners | boutique; betweenness #1; well covered by us |
| BIGBANK | Continental Capital Markets | high-volume bank, 60 deals in 5 years, mostly outside thesis sectors |
| PINE | Pinecrest Dental Partners | Northwind Fund III portfolio company since 2020-07-01; CONF supplies it |
| GRANITE | Granite Testing Group | Northwind Fund IV platform since 2024-03-15; niche Materials Testing (Industrial TIC) |
| A1 | Clearwater Environmental Labs | founder-owned, niche Environmental Testing (sibling of Materials Testing) |
| D_SAME | Bedrock Materials Testing | founder-owned, same niche and same states as Granite, zero shared customers |
| D_VET | Pembrook Veterinary Pharmaceuticals | niche Veterinary Pharmaceuticals under Life Sciences (outside the thesis) |
| D_BIG | Northgate Behavioral Health | thesis niche, every signal, EBITDA 44.0 (above band) |
| D_SHORT | Cobalt Urgent Care Partners | thesis niche; sponsor bought it 2025-04-01 (held 1.5 years); five recent unscored signal rows |

---

## 3. Hero questions

### Q-SCORE (rules). Act 1

**Business question (MD voice).** "Which companies fit the Fund IV thesis and look ready to transact in the next 12-18 months, and why each one?"

**Reasoner and technique.** Rules (`rai-rules-authoring`), derived properties only. No graph.
- *Hierarchy closure (recursive rule).* `Sector.ancestor_or_self` is the transitive closure over `SECTOR.parent_id`. A niche n is **in thesis** for Fund IV iff some ancestor-or-self of n is a Fund IV `include` focus node **and** no ancestor-or-self is an `exclude` node. Fund IV focus nodes sit at **mixed levels**:
  - Healthcare Services (level 1, include, margin benchmark 14%)
  - Tech-Enabled Business Services (level 2 under Business Services, include, 18%)
  - Testing, Inspection & Certification (level 2 under Industrials, include, 17%)
  - Specialty Distribution (level 2 under Distribution, include, 9%)
  - Skilled Nursing Facilities (level 3 under Healthcare Services, **exclude**)
- *US gate.* The HQ region's closure reaches the US node.
- *Eligibility* (all must hold): in thesis; `5.0 <= ebitda_musd <= 40.0`; US; `is_public = false`; not currently owned by any Northwind fund.
- *Classification and derivation rules, each one a named component with an explanation string:*

| Component | Points | Rule (dates relative to T) |
|---|---|---|
| FIT_THESIS | 15 | eligible (always 15 when eligible) |
| FIT_EBITDA | 10 or 5 | 10 if `10.0 <= ebitda <= 30.0`; 5 if in `[5.0, 10.0)` or `(30.0, 40.0]` |
| FIT_MARGIN | 5 | `ebitda / revenue >= margin_benchmark_pct` of the matching focus node |
| R_CFO_FROM_PE | 15 | A current CFO role starts in [T-18m, T], **and** the same person held a role at a different org whose end date falls in [cfo_start - 12 months, cfo_start], **and** that org had a sponsor-fund ownership interval overlapping that role by 1 day or more. This is a temporal join: the employer was PE-backed *while the person was there*. |
| R_EXIT_WINDOW | 15 | Current owner is a sponsor fund, the ownership start is on or before T-5y, **and** the fund's `vintage_year <= VINTAGE_CUT` (2018) |
| R_BANKER | 10 | A BANKER_ENGAGED signal with `signal_date` in [T-6m, T] |
| R_DEBT | 10 | A DEBT_MATURITY signal with `signal_date <= T` and `event_date` in (T, T+18m] |
| R_SUCCESSION | 10 | The current CEO role has `is_founder = true` and starts on or before T-15y, **and** no current President or COO role exists at the company. This uses tenure, never age. |
| R_NEW_DIRECTOR | 5 | A Board role at the company starts in [T-12m, T]. The person holds no non-Board role at the company and no current role at the sponsor that owns the company. |
| A_CRM | 10 | At least one CRM interaction with sentiment positive, dated in [T-24m, T], whose counterparty is the company itself or a person holding a current role at the company |
| A_WARM_PATH | 10 | **Finale only** (not in Act 1) |

Fit = FIT_* (max 30). Readiness = sum of R_* capped at 50. Access = A_* (max 20). Score = Fit + Readiness + Access (max 100). Tier: A if >= 70, B if 50-69, C if < 50. Ineligible companies get no score. They get an explanation ("EBITDA $44.0M is above the $40M band"). Every row carries a `why` string listing each awarded component with its evidence, for example "CFO hired 2025-06-01 from Brightwater Dental (PE-backed 2015-2025)".

**Planted answer spec (golden).** Exactly 6 Tier-A companies, ordered:

| Rank | Key | Score | Components awarded (evidence) | Not in CRM |
|---|---|---|---|---|
| 1 | T_BANKER | 90 | THESIS 15, EBITDA 10, MARGIN 5 (20.0% vs 18%); EXIT_WINDOW 15 (Ironbridge Fund I, vintage 2016, held since 2019-04-15 = 7.5 years); BANKER 10 (Cedar Row, 2026-08-10); DEBT 10 (matures 2027-09-30); CFO_FROM_PE 15 (CFO started 2025-07-01, came from a sponsor-backed company); A_CRM 10 (positive org-level meeting 2026-05-20). SUCCESSION not awarded (a COO has been in place since 2020-02-03; a visible near-miss). | |
| 2 | T_WARM | 85 | THESIS 15, EBITDA 10, MARGIN 5 (15.7% vs 14%); CFO_FROM_PE 15 (Elena Marsh, 2025-06-01, from Brightwater Dental, sponsor-owned through her tenure); SUCCESSION 10 (founder CEO since 2008-01-01 = 18.75 years, no President/COO); DEBT 10 (2027-06-30); BANKER 10 (2026-05-15); A_CRM 10 (positive org-level meeting 2026-03-12) | |
| 3 | T_COLD | 80 | THESIS 15, EBITDA 10, MARGIN 5 (15.7% vs 14%); EXIT_WINDOW 15 (Copperline Fund II, vintage 2017, held since 2020-09-01 = 6.1 years); BANKER 10 (Harbor Lane, 2026-07-14); DEBT 10 (2027-12-31); CFO_FROM_PE 15 (CFO started 2025-11-03); A_CRM 0 | **yes** |
| 4 | CONF | 75 | THESIS 15, EBITDA 10, MARGIN 5 (10.0% vs 9%); SUCCESSION 10 (founder CEO since 1999-05-01); BANKER 10 (2026-06-02); DEBT 10 (2028-02-28); CFO_FROM_PE 15 (2025-08-18); A_CRM 0 (PIPELINE "Tracking", last interaction 2023-02-10 neutral, outside 24 months) | |
| 5 | T_5 | 75 | THESIS 15, EBITDA 5 (8.5, edge of band), MARGIN 5 (20.2% vs 18%); CFO_FROM_PE 15 (2025-05-05); SUCCESSION 10 (founder CEO since 2009-09-01); DEBT 10 (2027-03-31); NEW_DIRECTOR 5 (board seat 2026-03-16, see Q-COMPETE); A_CRM 10 (2025-12-04) | |
| 6 | T_6 | 70 | THESIS 15, EBITDA 10, MARGIN 5 (18.2% vs 17%); EXIT_WINDOW 15 (Tamarack Fund II, vintage 2015, held since 2020-06-30); BANKER 10 (2026-09-08); DEBT 10 (2027-08-15); NEW_DIRECTOR 5 (2026-01-20); A_CRM 0 | **yes** |

- NM_B scores 65 (Tier B): Fit 30; SUCCESSION 10 (founder CEO since 2006-03-01), DEBT 10, CFO_FROM_PE 15 (CFO since 2025-05-12); A_CRM 0. It is the finale riser.
- "Not in CRM" means no PIPELINE row and no CRM_INTERACTION touching the company or its people. Exactly {T_COLD, T_6}.
- `must_not_contain` (Tier A): D_VET, D_BIG, D_SHORT, NM_B, D_SAME, A1.

**Decoy spec.** The naive SQL screen (R11 writes it as `data/naive_sql/q_score.sql`) is what an analyst writes against flat tables:
1. A keyword sector match on the **niche or company name** (`ILIKE` any of `%health%`, `%medical%`, `%veterinar%`, `%dental%`, `%testing%`, `%inspection%`, `%distribution%`, `%care%`), because there is no hierarchy.
2. `ebitda_musd BETWEEN 5 AND 40`, with the HQ state in a hard-coded US state list.
3. Ranked by `COUNT(*)` of COMPANY_SIGNAL rows with `signal_date >= T-12m` (any type).

What it gets wrong:
- **D_VET** (niche Veterinary Pharmaceuticals under Life Sciences > Pharmaceutical Manufacturing; EBITDA 15.0; signals BANKER_ENGAGED 2026-06-20, DEBT_MATURITY event 2027-10-31, PRESS_RELEASE, AWARD in the last 12 months). The `%veterinar%` keyword includes it, and 4 recent signals put it near the top. RAI excludes it: its niche's ancestors never reach a Fund IV focus node. The thesis tree does contain a real "Veterinary Clinics" niche under Healthcare Services > Animal Health Services, which is why the keyword exists.
- **D_SHORT** (thesis niche Urgent Care Clinics; EBITDA 20.0; owned by a sponsor fund of vintage 2021 since 2025-04-01; 5 signal rows in the last 12 months: ADDON_ANNOUNCED x3, DEBT_REFINANCED, PRESS_RELEASE). It tops the signal-count ranking. RAI scores it Fit 30 + Readiness 0 = 30, Tier C, and the explanation says "sponsor bought it 18 months ago; activity is add-ons, not a sale".
- **Misses and misranks**: the screen **misses** T_5, because its niche "Records Retrieval & Litigation Support" and its company name contain no keyword. It **misranks** the rest: T_BANKER is included (its niche matches `%health%`) but ordered by raw row count, not by dated readiness. R05: T_5's niche and company names must contain none of the keywords above.
- **D_BIG** (thesis niche Behavioral Health Clinics; EBITDA 44.0; every readiness signal) is a **near-miss, not a SQL decoy**, because the SQL band also drops it. RAI shows it as ineligible with the reason, so the rules visibly do the work (section 8.3).

**Why SQL alone fails.** The thesis is a hierarchy with mixed-level includes and a nested exclude (recursion). CFO_FROM_PE is a three-way temporal join (CFO role, prior role, the prior employer's ownership interval *during* that role). The exit window joins ownership to fund vintage. All of it must yield per-point explanations from one governed definition that Q-PATH and the finale reuse. A recursive CTE can do any single piece; the point is one model, many questions, every point explained.

**Explorer view.** Scorecard: the ranked list with A/B/C tier chips, a stacked bar per company (Fit / Readiness / Access) with hover showing each component's evidence, and a "not in CRM" badge on T_COLD and T_6. A toggle reveals the naive SQL list next to it, with D_VET and D_SHORT struck through and the reason shown. The side panel shows each rule's business-language docstring.

**Tier-1 prompt (Claude Code).**
> Which companies fit the Fund IV thesis and look ready to transact in the next 12 to 18 months? Show the Tier A list with the score components behind each one, and flag any that are not in our CRM.

Tier-2 ad-lib suggestion: "Only show the healthcare services names."

**Chains into Q-PATH.** "Two of your six best targets are names your CRM has never logged. Knowing who to call is half the job; the other half is who makes the introduction. Take the top three."

---

### Q-PATH (graph + rules). Act 2

**Business question (MD voice).** "For our top three, what is our warmest path to each CEO, and through whom?"

**Reasoner and technique.**
- *Rules: `Knows(Person, Person)`* is symmetric, with typed evidence and a strength in [0, 1]. Strength is the max over evidence. Let `recency(d)` = 1.0 if d >= T-10y, 0.7 if d >= T-20y, else 0.4.
  - **K1 tenure overlap** (`board co-service` when both roles are Board): two roles at the same org with `min(end1, end2) - max(start1, start2) >= 365` days (open end = T). Strength = `recency(overlap_end) * min(1.0, 0.4 + 0.15 * overlap_days / 365.25)`.
  - **K2 deal co-participation**: both persons are `lead_person_id` on the same transaction, **or** one is a lead person and the other held a CEO/CFO role at the target on `close_date`. Strength = `0.7 * recency(close_date)`.
  - **K3 positive CRM**: an OUR_SEEDS person had 1 or more `positive` person-level interactions with the other person in [T-24m, T]. Strength 0.6 for 1, 0.8 for 2, 1.0 for 3 or more.
- *Graph*: `Graph(model, directed=False, weighted=False, node_concept=Person)`. Edges come from Knows, one edge per unordered pair (`id <` guard). Validate `num_nodes()` and `num_edges()` first.
  - `d_seed = graph.distance(from_=OurSeeds)` and `d_ceo = graph.distance(from_=TopThreeCEOs)`. These are two single-sided calls (see 0.4 item 1).
  - L(target) = min over seeds of d(seed, CEO).
  - Path nodes satisfy `d(s,m) + d(ceo,m) = L`. Rules join Knows chains of length L (L <= 3) through those nodes to produce explicit paths.
- *Rules again*: path strength = product of hop strengths. Show the best path and up to 2 alternates of the same length, ranked by strength. Report "no path within 3 hops" when L > 3 or the CEO is unreachable.

**Planted answer spec (golden).** Targets in Q-SCORE rank order:

| Target | CEO | Hops | Best path (each hop with evidence) | Path strength | Alternates |
|---|---|---|---|---|---|
| T_BANKER | CEO_B Ruth Adeyemi | **3** | VP Priya Raman -[K1: Lakeshore Securities, overlap 2012-06-04 to 2016-06-30, 4.07 years, recency 0.7 -> 0.70]- Y_BANK Sofia Brandt -[K1: Cedar Row Partners, 2017-01-09 to present, 9.7 years -> 1.00]- B_BANK Nathan Cole -[K2: lead sell-side banker on T_BANKER majority recap closed 2019-04-15 while she was CEO -> 0.70]- CEO_B | **0.490** | none |
| T_WARM | CEO_W Daniel Reyes | **2** | OP Marcus Whitfield -[K1: Brightwater Dental, 2015-03-01 to 2019-06-30, 4.33 years -> 1.00]- CFO_W Elena Marsh -[K1: T_WARM, 2025-06-01 to present, 1.33 years -> 0.60]- CEO_W | **0.600** | MP Dana Okafor -[K1: Old Harbor Health, 1998-03-01 to 2000-06-30, 2.33 years, recency 0.4 -> 0.300]- X_STALE Walter Kim -[K1 board co-service at T_WARM, 2023-01-15 to present, 3.71 years -> 0.957]- CEO_W = **0.287** (rank 2 of 2) |
| T_COLD | CEO_C Victor Hale | **none within 3** | "Cold. The banker who knows this company best is Harbor Lane (arranged its 2023 dividend recap)." This line is the hand-off to Q-FLOW. | - | - |

Role intervals R05 must plant exactly:
- OP Marcus Whitfield: Board at Brightwater 2014-09-15 to 2019-06-30.
- Dana Okafor: Old Harbor Health 1998-03-01 to 2000-06-30.
- Walter Kim: Old Harbor Health 1997-01-06 to 2001-12-14.
- Priya Raman: Lakeshore Securities 2011-07-01 to 2016-06-30.
- Plus the dates in section 2.

Invariants (they must survive the P5 noise):
- No OUR_SEEDS person is within 1 hop of CEO_W or CEO_B. d(seeds, CEO_W) = 2 exactly. d(seeds, CEO_B) = 3 exactly. d(seeds, CEO_C) >= 4 or unreachable.
- All hero CRM touches (A_CRM in Q-SCORE) are **org-level** (`counterparty_org_id` set, person NULL), so they create no Knows edge.
- Harbor Lane's single touchpoint in the last 24 months is org-level and `neutral`, so it creates no Knows edge.
- No OUR_SEEDS person has a K3 edge to Y_BANK, B_BANK or HL_MD.
- The set of 2-hop seed paths to CEO_W is exactly the two listed (the OP path and the stale path). No OUR_SEEDS person is `lead_person_id` on any Brightwater transaction, so there is no K2 edge from a seed to CFO_W.
- `must_not_contain`: any path to CEO_C, any path using Meridian Lab Services, the stale path ranked first for T_WARM.

**Decoy spec.**
- **False warm intro (shared employer, no overlap).** MD_MER Tom Brennan was at Meridian Lab Services 2008-01-07 to 2011-06-30. CEO_C Victor Hale was there 2013-03-04 to 2020-08-31. The naive SQL (`data/naive_sql/q_path.sql`: self-join ROLE_HISTORY on `org_id`, one side in OUR_SEEDS, the other a target CEO, ignoring dates) reports "Tom Brennan knows Victor Hale via Meridian", a 1-hop warm intro to the target RAI calls cold. The rule rejects it: the intervals never overlap, by a gap of 613 days.
- **Stale tie.** Dana Okafor and Walter Kim overlapped 1998-2000. The tie exists and appears as T_WARM's alternate, but at 0.287 it ranks below the fresh 0.600 Brightwater path. A count-of-connections approach would treat them as equal.

**Why SQL alone fails.** Every hop needs interval overlap with a duration threshold. Path length is variable (2 for one target, 3 for another, none for the third). The evidence must survive per hop. A shared-employer join confuses "same company" with "knew each other".

**Explorer view.** Warm path: pick a target and the shortest paths from Northwind people light up. Each edge is labeled with its evidence ("Overlapped at Brightwater Dental, 2015-03 to 2019-06, 4.3 years"). The alternate path is dimmed with its strength. For T_COLD, a "no path within 3 hops" banner shows the struck-through Meridian claim ("shared employer, never overlapped: 2008-2011 vs 2013-2020") and a link "Who knows this company? -> Deal flow" that jumps to Harbor Lane.

**Tier-1 prompt (Claude Code).**
> For our top three targets, what is our warmest path to each CEO, and through whom? Show every hop with its evidence and say plainly if a target is cold.

Tier-2 ad-lib suggestion: "Why isn't Tom Brennan's Meridian connection a path to Victor Hale?"

**Chains into Q-ADDON.** "Two of three are reachable this quarter; Saltmarsh is cold, and we will come back to it. Platforms are only half of buy-and-build. Most deals in this market are add-ons. So what should Granite buy next?"

---

### Q-ADDON (graph). Act 3

**Business question (MD voice).** "Which add-ons best extend our Granite Testing platform, beyond the obvious same-niche names?"

**Reasoner and technique.**
- *Graph*: `Graph(model, directed=False, weighted=False, node_concept=Company)`. Edges come from COMMERCIAL_LINK (supplier-customer, direction dropped), so a node's neighbors are its customers and suppliers. Then:
  - `graph.jaccard_similarity(from_=PlatformSet)`, where `PlatformSet` = {GRANITE}. Self-pairs are filtered out.
  - `graph.louvain()` (default seed) colors the ecosystem in the explorer only.
- *Rules*:
  - **Candidate eligibility**: the niche shares GRANITE's level-2 ancestor (Testing, Inspection & Certification) by closure; no current sponsor-fund ownership; `ebitda_musd <= 15.0`; US HQ; no direct COMMERCIAL_LINK with GRANITE.
  - **Whitespace**: states in COMPANY_SITE for the candidate minus states for GRANITE.
  - **Shared-customer list**: the evidence.
  - Rank by Jaccard desc. Whitespace count is shown, not used to rank.

**Planted answer spec (golden).** GRANITE's neighborhood is exactly 18 companies: customers C01-C15 and suppliers S1-S3. Its sites are TX, OK, LA, AR.

| Rank | Key | Niche | Neighbors | Shared with GRANITE | Jaccard | Sites | Whitespace states |
|---|---|---|---|---|---|---|---|
| 1 | A1 Clearwater Environmental Labs | Environmental Testing | 10 (C01-C06 plus 4 own customers) | 6 | **6/22 = 0.2727** | TX, CO, UT, NM | **CO, UT, NM (3)** |
| 2 | A2 Ridgeline NDT Services | Non-Destructive Testing | 8 (C08, C09, C10 plus 5 own) | 3 | **3/23 = 0.1304** | TX, LA | none |
| 3 | A3 Summit Calibration Co | Calibration Services | 4 (C11, C12 plus 2 own) | 2 | **2/20 = 0.1000** | OK, KS | KS (1) |

- `must_not_contain`: D_SAME. It is absent from the similarity result because it shares no neighbor.
- R12 must add **no** COMMERCIAL_LINK incident to GRANITE, A1, A2, A3 or D_SAME. Then these values stay exact after noise.
- No other eligible candidate may reach Jaccard >= 0.10.

**Decoy spec.** The naive SQL (`data/naive_sql/q_addon.sql`): companies in GRANITE's **own niche** (Materials Testing) with an HQ state in GRANITE's states, ranked by revenue. The top row is **D_SAME Bedrock Materials Testing** (founder-owned, EBITDA 9.0, revenue 55, sites TX, OK, LA; zero customer overlap and zero new states). The screen never sees A1, because A1 sits in a sibling niche. RAI drops D_SAME: it adds no customers we can cross-sell and no new geography.

**Why SQL alone fails.** Similarity of commercial neighborhoods (shared customers over shared customers plus all others) is a set computation over a bipartite network for every candidate, not a join on a sector code. The candidate pool itself needs the hierarchy (siblings under TIC).

**Explorer view.** Add-on map: GRANITE in the center. Candidates are sized by Jaccard and colored by Louvain community. Shared customers are drawn as the bridges between them. A US mini-map highlights the whitespace states (CO, UT, NM for A1). D_SAME is shown greyed out, labeled "same niche, no overlap".

**Tier-1 prompt (Claude Code).**
> Which add-ons best extend our Granite Testing platform, beyond the obvious same-niche names? Rank them by shared customers and suppliers, and show the new states each one adds.

Tier-2 ad-lib suggestion: "Only show candidates that add at least two new states."

**Chains into Q-FLOW.** "Clearwater and Saltmarsh have one thing in common: neither came to us through a banker we cover. So who actually sees these deals first in our sectors, and are we covering them?"

---

### Q-FLOW (graph + rules). Act 4

**Business question (MD voice).** "Which intermediaries actually control deal flow in our sectors, and where is our coverage weakest?"

**Reasoner and technique.**
- *Rules (graph input)*:
  - Transactions with `close_date` in [T-5y, T] whose target niche is in the Fund IV thesis tree. This reuses the Q-SCORE closure.
  - Nodes: Organizations (Intermediary, Sponsor, Company). A fund maps to its sponsor.
  - Edges: one per distinct unordered pair among {advisor-target, advisor-buyer, advisor-seller, buyer-target}. The advisor is any party with role `sell_side_advisor`, `buy_side_advisor` or `lender_arranger`. For an add-on the buyer is the platform company.
- *Graph*: `Graph(model, directed=False, weighted=False)`. Validate the node and edge counts first. Then:
  - `graph.betweenness_centrality(num_pivots=N)` with `N >= num_nodes()` (exact Brandes, deterministic; see 0.4 item 3).
  - `graph.pagerank()` as a secondary "reach" column. It is displayed only; there is no golden ranking on it.
  - Rank intermediaries by betweenness.
- *Rules (`CoverageGap`)*:
  - `touchpoints_24m(i)` = count of CRM interactions in [T-24m, T] with org i or with a person holding a current role at i.
  - An intermediary is a gap iff its betweenness rank among intermediaries is `<= ceil(0.10 * N_int_in_graph)` (top decile) **and** `touchpoints_24m <= Q1`. Q1 is the value at position `ceil(0.25 * N_int)` in the ascending sorted touchpoint list over **all** INTERMEDIARY rows (bottom quartile).

**Planted answer spec (golden).**

| Intermediary | Deals in window (thesis sectors) | Betweenness rank (intermediaries) | Touchpoints 24m | Coverage gap |
|---|---|---|---|---|
| CEDAR Cedar Row Partners | about 14 | **1** | 14 | no |
| HL Harbor Lane Advisors | **9** | **2** | **1** (org-level, neutral, 2025-11-20) | **yes (the only gap)** |
| BIGBANK Continental Capital Markets | 8 in thesis (60 overall) | outside top decile (rank >= 8) | 9 | no |

- HL's 9 in-window deals: 8 sell-side mandates for founder-owned healthcare-services companies (`seller_type = founder_family`), sold to buyers belonging to **5 distinct sponsors**, plus T_COLD's dividend recap (`structure = dividend_recap`, 2023-05-18, sponsor Copperline, which is one of the 5).
- Construction guidance for R05: those 5 sponsors have at most 2 other in-window thesis deals each, all with other advisors, so HL is their main bridge into the rest of the graph. R05 tunes until networkx exact betweenness gives CEDAR 1 and HL 2. R06 confirms independently.
- R05 ensures Q1 >= 1, which means at least 25% of intermediaries have 1 touchpoint or fewer. Every other top-decile intermediary has touchpoints > Q1, so HL is the only gap.
- `must_not_contain` (gaps): CEDAR, BIGBANK.
- Closing the loop: **HL arranged T_COLD's last recap**. TRANSACTION `structure = dividend_recap`, target T_COLD, party HL as `lender_arranger`, `lead_person_id` = HL_MD.

**Decoy spec.** The naive SQL (`data/naive_sql/q_flow.sql`) is a league table: `COUNT(DISTINCT txn_id)` per advisor over **all** transactions in the last 5 years, sorted desc. **BIGBANK tops it with 60 deals**, and HL sits around 10th with 9. In the sector-scoped network, BIGBANK's 8 thesis deals are with large, well-connected sponsors that have many other advisors, so it bridges nothing and is not top decile. The league table also cannot see that we have touched HL once.

**Why SQL alone fails.** Betweenness is a global property: the share of all shortest paths through a node. It cannot be computed from a node's own rows, and volume is not control. The coverage gap then combines a graph metric with a dated CRM count in one rule.

**Explorer view.** Deal flow: intermediaries, sponsors and companies in thesis sectors. Intermediaries are sized by betweenness with a touchpoint-count ring overlay. The coverage gap (HL) is outlined in red. Clicking HL lists its 9 deals, highlights T_COLD's recap edge and links back to T_COLD's "cold" card in the warm-path view. A side table puts the naive league table (BIGBANK first) next to the betweenness ranking.

**Tier-1 prompt (Claude Code).**
> Which intermediaries actually control deal flow in our Fund IV sectors, and where is our coverage weakest? Compare against a simple deal-count league table.

Tier-2 ad-lib suggestion: "Which of Harbor Lane's deals involve companies on our Tier A list?" (Answer: T_COLD.)

**Chains into the Finale.** "Harbor Lane is the way into Saltmarsh, and a call this week fixes our biggest coverage gap. Now let's make what we just learned part of the score."

---

### Finale (rules composing graph output; Tier-2 live authoring)

**Prompt the presenter types (verbatim, from section 7.3).**
> Add a rule: targets we can reach in two hops or fewer get 10 access points, and flag any target that is a customer or supplier of a Fund III portfolio company as a conflict. Re-score.

**Technique.**
- Claude Code uses `rai-rules-authoring` to add two derived properties:
  - `A_WARM_PATH = 10` iff min over OUR_SEEDS of `distance(seed, current CEO) <= 2`. This reuses the Q-PATH `distance(from_=OurSeeds)` relationship, so a graph output feeds a rule.
  - `Conflict(company)` iff a COMMERCIAL_LINK exists in either direction between the company and a company with a **current** OWNERSHIP by Northwind Fund III. Conflicted companies get tier "Conflict - LPAC review" and leave the Tier-A list.
- Score and tier are then re-derived.
- Fallback: R09 ships the same two rules in `rules.py` behind a `FINALE` flag, and `queries.py` has `finale_rescore()`, so a failed live authoring step still lands on the identical answer.

**Planted answer spec (golden).** Tier A after the finale:

| Rank | Key | Score | Change |
|---|---|---|---|
| 1 | T_WARM | **95** | +10 warm path (2 hops); moves from #2 to #1 |
| 2 | T_BANKER | 90 | 3 hops, no change; drops from #1 to #2 |
| 3 | T_COLD | 80 | cold, no change |
| 4 | T_5 | 75 | no change (d >= 3) |
| 5 | NM_B | **75** | +10 warm path; **rises from Tier B (65) into Tier A** |
| 6 | T_6 | 70 | no change (d >= 3) |
| - | CONF | (75) | **flagged Conflict - LPAC review**: supplies PINE Pinecrest Dental Partners (Fund III since 2020-07-01) |

- NM_B's planted path: OP2 Grace Liu -[K1: Lakemont Orthodontics, 2016-02-01 to 2020-05-31, 4.33 years -> 1.00]- Z (Board at NM_B since 2022-04-01; at Lakemont 2015-08-03 to 2021-03-31) -[K1 board co-service, 4.5 years -> 1.00]- NM_B CEO (founder since 2006-03-01). d = 2.
- Invariants:
  - d(seeds, CEO of T_5, T_6, CONF) >= 3.
  - No Tier-A or NM_B company except CONF has a COMMERCIAL_LINK to any current Fund III portfolio company.
  - CONF's link to PINE is CONF as supplier, PINE as customer.
- `must_not_contain` (Tier A after the finale): CONF.

**Decoy spec.** CONF is the Q-SCORE Tier-A lookalike. Every point it earned in Act 1 was real, but the cross-fund relationship (Fund IV buying a supplier to a Fund III company) needs LPAC review. Neither a CRM nor a thesis screen joins pipeline targets to the *other* fund's portfolio supply chain.

**Why SQL alone fails.** The new access points come from a graph distance computed in Act 2, and the conflict comes from commercial links joined to time-bounded fund ownership. Both slot into the existing score as one more named, explained component. The ranking changes in a sentence, with no new pipeline.

**Explorer view.** The scorecard re-renders with a "Finale" toggle. Before and after columns show the rank movement arrows (T_WARM up, NM_B new, CONF struck with a "Conflict - LPAC" chip). Clicking CONF shows the CONF -> PINE supply edge.

**Chains into the close.** "Governed, explainable, in your Snowflake; and Claude is the interface."

---

## 4. Backups (2)

Selection: **Q-CONFLICT** and **Q-COMPETE**. Q-EXEC was rejected. Career-path similarity is hard to plant so that an independent oracle agrees on a ranking. It overlaps with Q-PATH ("who do we know"), and its answer ("this person ran a similar business") is the weakest "so what" for a partner.

### Q-CONFLICT (graph + rules)

**Business question.** "Before we bid on Keystone, does it conflict with anything we own, and would it breach Fund IV's sector concentration limit?"

**Technique.**
- *Graph*: `Graph(model, directed=False, weighted=False)` over Company and Fund nodes. Edges are COMMERCIAL_LINK pairs plus current OWNERSHIP (fund-company). Then `graph.distance(from_=SubjectSet)`, with SubjectSet = {CONF}. Report Northwind portfolio companies (current Fund III or IV ownership) at company-graph distance <= 2, counting commercial hops only. The fund node is the label, not a hop.
- *Rules*:
  - Concentration: Fund IV `equity_invested_musd` over current holdings, rolled up by the level-1 sector via closure, plus the subject's `PIPELINE.est_equity_check_musd`. The total is divided by Fund IV `size_musd`.
  - Breach iff the result exceeds 25%.

**Planted answer.**
- PINE: distance 1, Fund III, CONF supplies PINE. This is a **conflict**.
- GRANITE: distance 2, Fund IV, a shared customer C07 (CONF supplies C07; C07 is one of GRANITE's 15 customers). This is **informational**.
- Concentration: Fund IV holdings in Distribution total $262M (21.8% of $1,200M). Adding CONF's est. check of $45M gives $307M = **25.6% > 25%, a breach**.
- `must_not_contain`: any Northwind company at distance >= 3. R05 plants one Fund III company at exactly distance 3 from CONF as the bound check.

**Decoy.** The naive SQL checks whether CONF is owned by a Northwind fund (no, so "clear"). A flat `GROUP BY` on niche names also misses the breach: it never rolls the Distribution niches up into one level-1 sector, and each niche on its own stays under 25%.

**Why SQL fails.** Bounded multi-hop reachability over commercial plus ownership edges, plus a hierarchy rollup.

**Explorer view.** Global view centered on CONF with 2-hop expansion; edges are colored by type.

**Tier-1 prompt.**
> Before we bid on Keystone Clinical Supply, does it conflict with anything we own, and would it breach Fund IV's sector concentration limit?

**Chains.** It drops in after the finale as the "and here's what that flag is made of" follow-up.

### Q-COMPETE (rules + graph)

**Business question.** "Which of our Tier-A targets are competitor sponsors already circling?"

**Technique.**
- *Rules*: `Circling(target, sponsor, evidence)` iff a person holds a **current** Operating Partner role at a non-Northwind sponsor **and** a Board role at the target that started within [T-24m, T].
- *Graph*: on the Q-ADDON commercial graph, `graph.jaccard_similarity(from_=CompetitorPlatforms, to=TierATargets)`. The `from_` plus `to` combination is allowed for Jaccard. CompetitorPlatforms = companies currently owned by a non-Northwind sponsor fund whose acquiring transaction has `deal_role = platform`. "Platform fit" holds iff the score is >= 0.20.

**Planted answer.**
- T_5: Ashgrove Partners' Operating Partner Rafael Ortiz joined its board on 2026-03-16. This is the same fact that earned T_5 its NEW_DIRECTOR point, read two ways.
- T_6: Jaccard **0.30** with Keel Industrial Testing, Blackfern Capital's platform. R05 plants 6 shared out of a union of 20. Keel and T_6 have no links to GRANITE's neighborhood.
- Exactly {T_5, T_6}.

**Decoy.** T_BANKER's COO was an Operating Partner at Ashgrove from 2014 to 2019 (ended). The naive "ever worked at a competitor" join flags T_BANKER. The rule requires a current competitor role, so T_BANKER is `must_not_contain`.

**Why SQL fails.** Temporal role logic plus neighborhood similarity to competitor platforms.

**Explorer view.** Scorecard with a "circled by" chip; add-on-map style view of T_6 next to Keel.

**Tier-1 prompt.**
> Which of our Tier A targets are competitor sponsors already circling, and what is the evidence?

**Chains.** It follows Q-SCORE as an "urgency" overlay if a partner asks "who else is looking?"

---

## 5. Guidance for downstream roles

- **R05**:
  - Plant exactly the dates, values and invariants above. Keep every role key out of Snowflake. Shuffle IDs.
  - T_5's names contain no naive keyword.
  - Any rename of GRANITE, Keystone, Harbor Lane or the targets must be propagated to the Tier-1 prompt text through `golden/stories.md` (R14 writes `prompts.md` from the final names).
  - Fund II, Fund III and Fund IV rows exist for Northwind.
- **R06**: everything here can be computed in pandas and networkx.
  - Use `nx.betweenness_centrality(G, normalized=False)` (exact).
  - Use `nx.jaccard_coefficient` or a set computation on undirected neighbor sets.
  - Use BFS for distance.
  - Compare floats with abs tol 1e-3.
  - Path strengths: T_WARM 0.600 and 0.287; T_BANKER 0.490.
- **R09/R10**:
  - The Q-PATH distance relationship is reused by the finale. Do not compute it twice with different seeds.
  - Use `num_pivots >= num_nodes()` for betweenness.
  - Do not use `rank()` in graph selects. Sort in pandas (rai-graph-analysis pitfall).
- **R11**: ranking assertions are specified for Q-SCORE (full order with the tie-break), Q-PATH (strength order), Q-ADDON (A1 > A2 > A3) and Q-FLOW (CEDAR 1, HL 2). PageRank and Louvain have no golden order.
- **R12**: noise must not break any invariant listed under each question. When in doubt, add noise away from GRANITE's neighborhood, the 3-hop balls around OUR_SEEDS, and HL's deal set.
