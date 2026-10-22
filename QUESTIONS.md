# QUESTIONS.md - Hero questions for the Northwind deal-graph demo (v2: R03 attempt 1, revised by R20 Fixer attempt 1)

Owner: R03 Question Designer (v2 edits by R20 under R03 write rights). Readers: R04 (critic), R05 (generator), R06 (oracle), R08-R11, R14-R16.
All data is synthetic. Every name below is illustrative. R05 picks the final fictional names and runs the collision check. Every entity has a stable **role key** (for example `T_WARM`). The keys live only in `data/golden/`. They never become IDs or columns in Snowflake.

## v2 changelog (R20, 2026-10-22, against R04 scorecard `handoffs/05-R04-a1.md`)

Every changed section carries a "v2 change" note. Numbers in brackets are R04 finding numbers.

**Arc and hero set**
1. [1] **Q-ADDON demoted to backup. Q-CONFLICT promoted to hero, Act 4.** New order: Q-SCORE -> Q-PATH -> Q-FLOW -> Q-CONFLICT -> Finale (degrade ladder step 1; the orchestrator logs it in STATE.json). `hero_questions` becomes `["Q-SCORE", "Q-PATH", "Q-FLOW", "Q-CONFLICT"]`.
2. [2] Q-CONFLICT rebuilt:
   - The cap is now Fund IV's internal IC guideline of 35% of commitments per thesis area, not an LPA limit.
   - Fund IV holdings are listed by name, niche and equity.
   - Commercial reach is computed by `distance(from_=)` with typed exposure rows and path evidence.
   - Brightwater (a former Fund II company) is a time-bounded-ownership decoy.
   - There is a distance-3 bound check (Redfern).
   - The explorer gets a new "Conflict check" view: ego graph plus concentration gauge.
   - New chain: Cedar Row is engaged on Keystone (Q-FLOW -> Q-CONFLICT).

**MAJOR fixes**
3. [3] Q-FLOW: the Tier-1 prompt no longer asks for the league table and asks for the top five bridges. BIGBANK is pinned at betweenness rank >= 11 among intermediaries, so a correct answer never names it. The league table moves to a Tier-2 prompt and to the explorer.
4. [4] Q-SCORE naive screen:
   - The keyword list now includes `%clinic%`.
   - Membership is stated for every cast row: the screen misses exactly {T_COLD, T_5} among Tier A.
   - Every cast signal row is listed with dates.
   - The naive top three are pinned: D_SHORT, D_VET, D_SNF.
5. [6] Q-PATH:
   - Decision-makers = current CEO, plus, for sponsor-owned targets, the owner's board designees (Owen Lacey for Ironbridge, Graham Pike for Copperline).
   - "We know Copperline" is answered as a row, with invariants d >= 4.
   - The path is the CEO path. CFOs and COOs are not targets; they appear only as hops.
6. [7] Cedar Row:
   - All 14 touchpoints are specified: 10 person-level Priya Raman <-> Sofia Brandt (7 positive), 4 org-level neutral.
   - The T_BANKER path strength becomes **0.700** (was 0.490).
   - "Exactly one shortest path" invariants, stated per neighbor set, make each golden strength the provable maximum.
7. [5, 8, 9] Finale:
   - Guard F1: NM_B is the only Act-1 score in [60, 69] in the signal layer.
   - Guard F2: d(seeds, every current role-holder) >= 3 for every other cast company that could matter.
   - "Reach" is defined as CEO-only distance <= 2. F2 makes every other reading give the same set.
   - The prompt is reworded to "flag it and take it off the Tier A list", which matches the golden.
   - The decoy check for CONF is row-based.

**MINOR fixes**
8. [10] Added decoy D_SNF (Linden Hollow Senior Care, Skilled Nursing Facilities, the nested exclude).
9. [11] D_SHORT: revenue, CRM status and an explanation template backed by rules.
10. [12] X_STALE -> CEO_W and Z -> NM_B CEO are relabelled K1 tenure overlap (not board co-service). The X_STALE hop is 0.956 (was printed 0.957; the path is still 0.287).
11. [13] Q1 is pinned at 1 with an exact touchpoint distribution. The other top-decile intermediaries have >= 3 touchpoints.
12. [14] Betweenness: R10 passes `num_pivots=16000`, a constant >= any possible |V|. R11 asserts ranks only.
13. [15] Harbor Lane is `debt_advisor` on the recap and Copperline is party `owner`. On stage say "advised".
14. [16]
    - Priya Raman is now a Partner.
    - CFO_FROM_PE is removed from CONF and NM_B: 4 of 7 cast now have it. CONF now ranks #5 and T_5 #4 (readiness tie-break).
    - BIGBANK has about 40 deals overall, not 60.
15. [17] A rule now backs the cold banner (`ClosestIntermediary`).
16. [18] Moot: the Q-ADDON -> Q-FLOW bridge line is deleted.
17. Brightwater is pinned at EBITDA 45.0 (ineligible). Lakemont, Old Harbor and Meridian are pinned ineligible. The former Brightwater deal lead is a non-seed (Harold Becker).
18. A "Rehearsal check (9.3)" line per Tier-1 prompt names the must-appear and must-not-appear entities.

**Unchanged on purpose**
- Section 0.4 (verified API surface): two single-sided distance calls; `num_pivots >= |V|`; Louvain is visual only.
- The scoring model and weights, the T_WARM paths (0.600 / 0.287) and the HL story.

---

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

> v2 change: TRANSACTION_PARTY roles now include `debt_advisor` and `owner`, and `lender_arranger` is gone (R04 item 15). FUND_FOCUS carries the concentration guideline. PIPELINE stage and check are used by Q-CONFLICT.

These are additions to section 8.1. Each one is small. Total rows stay under the 16,000 cap.

| Element | Why |
|---|---|
| `SECTOR(sector_id, name, level, parent_id)`: 3 levels (sector > subsector > niche); companies attach to a niche | hierarchy closure (Q-SCORE, Q-FLOW, Q-CONFLICT) |
| `FUND_FOCUS(fund_id, sector_id, mode in {include, exclude}, margin_benchmark_pct)`: Fund IV includes nodes at **mixed levels** | thesis tree; margin benchmark; thesis area for concentration |
| `FUND(fund_id, sponsor_id, name, vintage_year, size_musd, area_guideline_pct NULL)`: Fund IV `area_guideline_pct` = 35 | Q-CONFLICT concentration guideline |
| `REGION(region_id, name, level, parent_id)`: state > census region > US | US-only gate, whitespace states (backup) |
| `COMPANY(company_id, name, sector_id, hq_region_id, revenue_musd, ebitda_musd, is_public)` | fit |
| `COMPANY_SITE(company_id, region_id)`: operating states, roughly 300-600 rows | Q-ADDON backup whitespace |
| `ROLE_HISTORY(role_id, person_id, org_id, role_type, start_date, end_date, is_founder)`; role_type in {CEO, CFO, COO, President, Board, Operating Partner, Deal Team, Banker} | Knows, readiness, decision-makers |
| `OWNERSHIP(company_id, fund_id, start_date, end_date, equity_invested_musd)` | exit window, conflicts, concentration |
| `TRANSACTION(txn_id, target_id, close_date, deal_role, seller_type, structure, ev_musd, ev_ebitda)` | Q-FLOW, recaps |
| `TRANSACTION_PARTY(txn_id, org_id, party_role in {buyer, seller, owner, sell_side_advisor, buy_side_advisor, debt_advisor, lender, co_investor}, fund_id NULL, lead_person_id NULL)`. `owner` = the sponsor fund holding the target in a recap with no change of control. | the deal graph; person-level deal co-participation |
| `COMMERCIAL_LINK(supplier_id, customer_id, value_band)`: all rows are current relationships | Q-CONFLICT, Finale, Q-ADDON backup |
| `CRM_INTERACTION(interaction_id, our_person_id, counterparty_person_id NULL, counterparty_org_id NULL, date, channel, sentiment in {positive, neutral, negative})` | access, Knows, coverage |
| `PIPELINE(company_id, stage, est_equity_check_musd)` | "not in CRM", Q-CONFLICT pending check |
| `COMPANY_SIGNAL(signal_id, company_id, signal_type, signal_date, event_date NULL, intermediary_id NULL)`. Scored types: BANKER_ENGAGED, DEBT_MATURITY. Unscored noise types: ADDON_ANNOUNCED, PRESS_RELEASE, HIRING_SURGE, AWARD, DEBT_REFINANCED | readiness; naive screen; closest intermediary |

"Northwind people" (`OUR_SEEDS`) are persons with a **current** Northwind role of type Deal Team or Operating Partner. Managing Partners, Partners and MDs are Deal Team.

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

> v2 notes on 0.4 (the facts above are unchanged):
> - Item 1: in Q-PATH the second single-sided call is seeded from the top-three **decision-makers** (CEOs plus owner designees, see Q-PATH). It is still exactly one `from_=` per call.
> - Item 3: R10 passes `num_pivots=16000`, the total row cap (R04 item 14; build-time probe OK). The deal-flow graph's nodes are organizations (at most about 1,300), so 16000 >= |V| always holds. R10 still asserts `num_nodes() <= 16000`. R11 asserts betweenness **ranks** only, never raw values.
> - Q-CONFLICT (new hero) uses `distance(from_={CONF})` on the commercial graph: one single-sided call.

---

## 1. The story in one breath (section 7.5 arc)

> v2 change: Q-ADDON is replaced by Q-CONFLICT as Act 4, and Q-FLOW moves to Act 3.

"Your CRM has about 200 companies in pipeline; the market has about 1,200 in your sweet spot."

- **Act 1, Q-SCORE (3 min)**: six Tier-A targets. Two are not in your CRM (Saltmarsh, Fenwick). Two are missed by the keyword screen (Saltmarsh, Quarry). The screen's top three are all wrong.
- **Act 2, Q-PATH (3 min)**: for the top three:
  - #1 Larkspur is three hops away through a banker Priya Raman knows well.
  - #2 Bayside is two hops away through our Operating Partner; a stale 1990s tie is correctly ranked second.
  - #3 Saltmarsh is honestly **cold**, both to its CEO and to Copperline's board designee, even though a shared-employer SQL join says "warm". The intermediary closest to Saltmarsh is Harbor Lane.
- **Act 3, Q-FLOW (3 min)**: Harbor Lane bridges founder-owned healthcare flow to five sponsors, and we have touched it once in two years: the only coverage gap. Cedar Row, the #1 bridge, is well covered.
- **Act 4, Q-CONFLICT (2 min)**: Cedar Row has just been engaged on Keystone (#5). Before an IOI, Keystone turns out to:
  - supply a Fund III company (a cross-fund conflict);
  - share a customer with Granite (informational);
  - push Fund IV's Specialty Distribution exposure to 36.7%, over the 35% guideline.
  The SQL check flags the wrong company (Brightwater, sold in 2020) and sees no concentration issue.
- **Finale (3 min)**: two sentences of new rules for every target. The warm path flips the top of the list (Bayside #1), Alder Creek rises from Tier B into Tier A, and Keystone is flagged and taken off Tier A.

---

## 2. Planted cast (shared across questions)

> v2 change:
> - CONF: readiness 35 without CFO_FROM_PE, gaining NEW_DIRECTOR 5; A_CRM 10; Act-1 rank 5.
> - T_5: Act-1 rank 4.
> - NM_B: readiness 35 without CFO_FROM_PE (now BANKER 10 + NEW_DIRECTOR 5).
> - New actors: D_SNF, owner designees, Fund IV holdings, Q-CONFLICT neighbors, the pinned supporting cast.
> - VP Priya Raman is now a Partner.

The scored components are defined in Q-SCORE. Score = Fit + Readiness + Access. Tier A >= 70, B 50-69, C < 50.

| Key | Illustrative name | Thesis area > niche | EBITDA $M / revenue $M | Ownership (as of T) | In PIPELINE | Fit | Readiness | Access (CRM) | Q-SCORE total | Q-SCORE rank |
|---|---|---|---|---|---|---|---|---|---|---|
| T_BANKER | Larkspur Revenue Partners | Tech-enabled business services > Healthcare Revenue Cycle Services | 26.0 / 130 | Ironbridge Capital Fund I (vintage 2016) since 2019-04-15 (majority recap) | yes | 30 | 50 | 10 | **90** | 1 |
| T_WARM | Bayside Pediatric Therapy Group | Healthcare services > Pediatric Therapy Clinics | 22.0 / 140 | founder-owned | yes | 30 | 45 | 10 | **85** | 2 |
| T_COLD | Saltmarsh Home Infusion | Healthcare services > Home Infusion Services | 18.0 / 115 | Copperline Partners Fund II (vintage 2017) since 2020-09-01 (control buyout) | **no** | 30 | 50 | 0 | **80** | 3 |
| T_5 | Quarry Records Retrieval | Tech-enabled business services > Records Retrieval & Litigation Support | 8.5 / 42 | founder-owned | yes | 25 | 40 | 10 | **75** | 4 |
| CONF | Keystone Clinical Supply | Specialty distribution > Medical & Lab Supply Distribution | 14.0 / 140 | founder-owned | yes (stage "IOI prep", est. equity check $55M) | 30 | 35 | 10 | **75** | 5 |
| T_6 | Fenwick Food Safety Labs | Industrial TIC > Food Safety Testing | 12.0 / 66 | Tamarack Equity Fund II (vintage 2015) since 2020-06-30 | **no** | 30 | 40 | 0 | **70** | 6 |
| NM_B | Alder Creek Dental Partners | Healthcare services > Dental Service Organizations | 16.0 / 100 | founder-owned | yes (Tracking) | 30 | 35 | 0 | 65 (Tier B) | - |

Ties are broken by score desc, then readiness desc, then fit desc, then company name asc. T_5 and CONF tie at 75; T_5 ranks first on readiness, 40 against 35.

Other planted actors:

| Key | Illustrative name | Role |
|---|---|---|
| NW | Northwind Equity Partners | us (Sponsor). Funds: Fund II (vintage 2014, fully realized, **no current holdings**); Fund III (vintage 2019, harvesting); Fund IV (vintage 2023, $1,200M, `area_guideline_pct` 35) |
| OP | Marcus Whitfield | Northwind Operating Partner (current) |
| MP | Dana Okafor | Northwind Managing Partner (Deal Team, current) |
| VP | Priya Raman | Northwind **Partner** (Deal Team, current since 2017-02-01). The key stays `VP` for continuity. |
| MD_MER | Tom Brennan | Northwind Managing Director (Deal Team, current) |
| OP2 | Grace Liu | Northwind Operating Partner (current) |
| EX_NW | Harold Becker | **Former** Northwind partner (Deal Team 2006-01-09 to 2021-03-31, so not a seed). Northwind's `lead_person_id` on the 2014 Brightwater buy and the 2020 sale. |
| BRIGHT | Brightwater Dental | Former Northwind Fund II portfolio company (Fund II 2014-06-30 to 2020-02-14; then Ridgeback Partners Fund III, vintage 2019, 2020-02-14 to present). **EBITDA 45.0 / revenue 300: ineligible (above band).** CONF supplies it (Q-CONFLICT decoy). |
| CFO_W | Elena Marsh | T_WARM CFO since 2025-06-01; Brightwater CFO 2015-03-01 to 2025-04-30 |
| CEO_W | Daniel Reyes | T_WARM founder CEO since 2008-01-01 |
| X_STALE | Walter Kim | T_WARM Board since 2023-01-15; at Old Harbor Health 1997-01-06 to 2001-12-14 |
| Y_BANK | Sofia Brandt | Banker at Cedar Row Partners since 2017-01-09; at Lakeshore Securities 2012-06-04 to 2016-12-16 |
| B_BANK | Nathan Cole | Managing Director, Cedar Row Partners since 2014-05-01; lead sell-side banker on T_BANKER's 2019-04-15 majority recap |
| CEO_B | Ruth Adeyemi | T_BANKER founder CEO since 2005-03-01 (has a COO since 2020-02-03) |
| OWN_B | Owen Lacey | Ironbridge Capital Deal Team since 2012-01-09; Board at T_BANKER since 2021-06-01 (owner designee). He was **not** a lead person on the 2019 recap. |
| IB_LEAD | Martin Greer | Ironbridge Deal Team 2010-03-01 to 2021-05-31 and Board at T_BANKER 2019-04-15 to 2021-05-31; Ironbridge's `lead_person_id` on the 2019 recap. He has no current role anywhere relevant, so he is not a decision-maker. |
| CEO_C | Victor Hale | T_COLD CEO since 2020-11-02; Meridian Lab Services 2013-03-04 to 2020-08-31 |
| OWN_C | Graham Pike | Copperline Partners Deal Team since 2014-06-02; Board at T_COLD since 2020-09-01 (owner designee) |
| HL | Harbor Lane Advisors | healthcare-services boutique. `debt_advisor` on T_COLD's 2023-05-18 dividend recap; BANKER_ENGAGED on T_COLD 2026-07-14 |
| HL_MD | Celia Navarro | Harbor Lane MD, lead on T_COLD's dividend recap |
| CEDAR | Cedar Row Partners | boutique; betweenness #1; well covered (14 touchpoints, all specified in Q-PATH). BANKER_ENGAGED on T_BANKER 2026-08-10 and CONF 2026-06-02 |
| BIGBANK | Continental Capital Markets | high-volume bank, **about 40** deals in 5 years (8 in thesis sectors) |
| PINE | Pinecrest Dental Partners | Northwind Fund III portfolio company since 2020-07-01; CONF supplies it |
| REDFERN | Redfern Imaging Centers | Northwind Fund III portfolio company since 2021-03-01; commercial distance exactly 3 from CONF (bound check) |
| GRANITE | Granite Testing Group | Northwind Fund IV platform since 2024-03-15, equity $150M; niche Materials Testing (Industrial TIC) |
| MEADOW | Meadowbrook Physical Therapy | Fund IV since 2023-09-12, equity $110M; Healthcare services > Physical Therapy Clinics |
| DIST1 | Tidewater Chemical Distribution | Fund IV since 2023-11-01, equity $140M; Specialty distribution > Specialty Chemicals Distribution |
| DIST2 | Juniper Industrial Supply | Fund IV since 2024-08-20, equity $125M; Specialty distribution > Industrial MRO Distribution |
| DIST3 | Sable Ingredients Co | Fund IV since 2025-06-02, equity $120M; Specialty distribution > Specialty Food Ingredients Distribution |
| C07 | Bluestem Engineering Group | civil engineering firm with in-house labs; buys from GRANITE (one of its 15 customers) and from CONF |
| H1 | Ashby Community Hospital | CONF customer; also buys from H2 |
| H2 | Fairmont Medical Linen | supplies H1 and REDFERN (gives REDFERN distance 3) |
| A1 | Clearwater Environmental Labs | founder-owned, niche Environmental Testing (Q-ADDON backup) |
| D_SAME | Bedrock Materials Testing | founder-owned, same niche and states as Granite, zero shared customers (Q-ADDON backup) |
| D_VET | Pembrook Veterinary Pharmaceuticals | niche Veterinary Pharmaceuticals under Life Sciences (outside the thesis) |
| D_SNF | Linden Hollow Senior Care | niche Skilled Nursing Facilities (Healthcare services > Post-Acute Care > SNF: the nested **exclude**); EBITDA 12.0 / revenue 150; founder-owned; not in PIPELINE |
| D_BIG | Northgate Behavioral Health | thesis niche, every signal, EBITDA 44.0 (above band) |
| D_SHORT | Cobalt Urgent Care Partners | thesis niche Urgent Care Clinics; EBITDA 20.0 / revenue 125; a sponsor fund (vintage 2021) bought it 2025-04-01 (held 1.5 years); no PIPELINE row and no CRM interaction; five recent unscored signal rows |
| LAKEMONT | Lakemont Orthodontics | OP2 and Z's former employer; EBITDA 3.5: ineligible (below band) |
| OLDHARBOR | Old Harbor Health | MP and X_STALE's former employer; `is_public = true`: ineligible |
| MERIDIAN | Meridian Lab Services | MD_MER and CEO_C's former employer; EBITDA 60.0: ineligible |

**Supporting cast scores (v2, Guard F1).** Every other eligible cast company scores **55 or less** in Act 1: A1, A2, A3, D_SAME, Keel Industrial Testing, D_SHORT (30). R05 picks their components. All are Tier B or C, and none is in [60, 69].

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
  - Skilled Nursing Facilities (level 3 under Healthcare Services > Post-Acute Care, **exclude**)
- The **thesis area** of an in-thesis company is the `include` focus node above its niche. It is reused by Q-CONFLICT concentration.
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

Fit = FIT_* (max 30). Readiness = sum of R_* capped at 50. Access = A_* (max 20). Score = Fit + Readiness + Access (max 100). Tier: A if >= 70, B if 50-69, C if < 50.

Ineligible companies get no score. They get an explanation, for example "EBITDA $44.0M is above the $40M band" or "niche Skilled Nursing Facilities is excluded from the Fund IV thesis".

Every row carries a `why` string listing each awarded component with its evidence, for example "CFO hired 2025-06-01 from Brightwater Dental (PE-backed 2015-2025)".

> v2 change (R04 item 11): two "why not" templates, both backed by rules.
> - **(a) Unscored activity**: "N signals in the last 12 months, none a scored readiness type (<types>)". It is emitted when a scored company has 3 or more COMPANY_SIGNAL rows in [T-12m, T] and R_BANKER = R_DEBT = 0.
> - **(b) Exit window not met**: "sponsor-owned since <date> (<x.x> years); exit window needs 5+ years held and fund vintage <= 2018". It is emitted for sponsor-owned scored companies without R_EXIT_WINDOW.
>
> For D_SHORT the two together read: "5 signals in the last 12 months, none a scored readiness type (ADDON_ANNOUNCED x3, DEBT_REFINANCED, PRESS_RELEASE); sponsor-owned since 2025-04-01 (1.5 years)". The v1 free-text "activity is add-ons, not a sale" is dropped.

**Planted answer spec (golden).** Exactly 6 Tier-A companies, ordered:

> v2 change: CONF and T_5 swap ranks 4 and 5; CONF's components changed; NM_B's components changed (its score is unchanged at 65).

| Rank | Key | Score | Components awarded (evidence) | Not in CRM |
|---|---|---|---|---|
| 1 | T_BANKER | 90 | THESIS 15, EBITDA 10, MARGIN 5 (20.0% vs 18%); EXIT_WINDOW 15 (Ironbridge Fund I, vintage 2016, held since 2019-04-15 = 7.5 years); BANKER 10 (Cedar Row, 2026-08-10); DEBT 10 (matures 2027-09-30); CFO_FROM_PE 15 (CFO started 2025-07-01, came from a sponsor-backed company); A_CRM 10 (positive org-level meeting 2026-05-20). SUCCESSION not awarded (a COO has been in place since 2020-02-03; a visible near-miss). | |
| 2 | T_WARM | 85 | THESIS 15, EBITDA 10, MARGIN 5 (15.7% vs 14%); CFO_FROM_PE 15 (Elena Marsh, 2025-06-01, from Brightwater Dental, sponsor-owned through her tenure); SUCCESSION 10 (founder CEO since 2008-01-01 = 18.75 years, no President/COO); DEBT 10 (2027-06-30); BANKER 10 (2026-05-15); A_CRM 10 (positive org-level meeting 2026-03-12) | |
| 3 | T_COLD | 80 | THESIS 15, EBITDA 10, MARGIN 5 (15.7% vs 14%); EXIT_WINDOW 15 (Copperline Fund II, vintage 2017, held since 2020-09-01 = 6.1 years); BANKER 10 (Harbor Lane, 2026-07-14); DEBT 10 (2027-12-31); CFO_FROM_PE 15 (CFO started 2025-11-03); A_CRM 0 | **yes** |
| 4 | T_5 | 75 | THESIS 15, EBITDA 5 (8.5, edge of band), MARGIN 5 (20.2% vs 18%); CFO_FROM_PE 15 (2025-05-05); SUCCESSION 10 (founder CEO since 2009-09-01); DEBT 10 (2027-03-31); NEW_DIRECTOR 5 (board seat 2026-03-16, see Q-COMPETE); A_CRM 10 (2025-12-04) | |
| 5 | CONF | 75 | THESIS 15, EBITDA 10, MARGIN 5 (10.0% vs 9%); SUCCESSION 10 (founder CEO since 1999-05-01, no President/COO); BANKER 10 (Cedar Row, 2026-06-02); DEBT 10 (2028-02-28); NEW_DIRECTOR 5 (independent director Helen Voss, 2026-02-17); A_CRM 10 (positive org-level meeting 2026-06-10). CFO_FROM_PE not awarded (CFO in seat since 2016). | |
| 6 | T_6 | 70 | THESIS 15, EBITDA 10, MARGIN 5 (18.2% vs 17%); EXIT_WINDOW 15 (Tamarack Fund II, vintage 2015, held since 2020-06-30); BANKER 10 (2026-09-08); DEBT 10 (2027-08-15); NEW_DIRECTOR 5 (2026-01-20, holds no Tamarack role); A_CRM 0 | **yes** |

- **NM_B scores 65 (Tier B).** It is the finale riser.
  - Fit 30.
  - SUCCESSION 10 (founder CEO since 2006-03-01).
  - DEBT 10 (2027-11-30).
  - BANKER 10 (2026-07-29).
  - NEW_DIRECTOR 5 (independent director Iris Calloway, 2026-03-02).
  - A_CRM 0: last interaction 2023-02-10, neutral, outside 24 months, a near-miss.
  - CFO_FROM_PE is a **near-miss**: the CFO was hired 2025-05-12 from a founder-owned company that had no sponsor ownership during her tenure, so the temporal join correctly rejects it.
- "Not in CRM" means no PIPELINE row and no CRM_INTERACTION touching the company or its people. Exactly {T_COLD, T_6}.
- `must_not_contain` (Tier A): D_VET, D_SNF, D_BIG, D_SHORT, NM_B, D_SAME, A1, BRIGHT.

**Signal rows for every cast company (v2 change, R04 item 4: complete list, so the naive order is computable).** Window for the naive count: `signal_date` in [T-12m, T] = [2025-10-01, 2026-10-01].

| Key | Rows (type signal_date [event_date] {intermediary}) | Count in window |
|---|---|---|
| T_BANKER | BANKER_ENGAGED 2026-08-10 {CEDAR}; DEBT_MATURITY 2026-02-15 [2027-09-30] | 2 |
| T_WARM | BANKER_ENGAGED 2026-05-15; DEBT_MATURITY 2026-01-20 [2027-06-30] | 2 |
| T_COLD | BANKER_ENGAGED 2026-07-14 {HL}; DEBT_MATURITY 2026-03-10 [2027-12-31] | 2 |
| T_5 | DEBT_MATURITY 2026-04-22 [2027-03-31] | 1 |
| CONF | BANKER_ENGAGED 2026-06-02 {CEDAR}; DEBT_MATURITY 2025-11-05 [2028-02-28] | 2 |
| T_6 | BANKER_ENGAGED 2026-09-08; DEBT_MATURITY 2026-02-02 [2027-08-15] | 2 |
| NM_B | BANKER_ENGAGED 2026-07-29; DEBT_MATURITY 2026-05-06 [2027-11-30] | 2 |
| D_VET | BANKER_ENGAGED 2026-06-20; DEBT_MATURITY 2026-01-12 [2027-10-31]; PRESS_RELEASE 2026-02-09; AWARD 2026-08-25 | 4 |
| D_SHORT | ADDON_ANNOUNCED 2025-11-18, 2026-03-03, 2026-07-21; DEBT_REFINANCED 2026-05-14; PRESS_RELEASE 2026-08-05 | 5 |
| D_SNF | BANKER_ENGAGED 2026-04-08; DEBT_MATURITY 2026-03-01 [2027-05-31]; HIRING_SURGE 2026-06-10 | 3 |
| D_BIG | BANKER_ENGAGED 2026-05-01; DEBT_MATURITY 2026-02-20 [2027-04-30]; PRESS_RELEASE 2026-03-15; AWARD 2026-07-01 | 4 (out of band) |

Every BANKER_ENGAGED row without a named intermediary uses a context boutique, never HL, CEDAR or BIGBANK.

**Decoy spec.** R11 writes the naive SQL screen as `data/naive_sql/q_score.sql`. It is what an analyst writes against flat tables:
1. A keyword sector match on the **niche name or company name**: `ILIKE` any of `%health%`, `%medical%`, `%clinic%`, `%dental%`, `%veterinar%`, `%care%`, `%testing%`, `%inspection%`, `%distribution%`. This is needed because there is no hierarchy. (v2 change: `%clinic%` is added.)
2. `ebitda_musd BETWEEN 5 AND 40`, with the HQ state in a hard-coded US state list, excluding companies with a current Northwind OWNERSHIP row.
3. Ranked by `COUNT(*)` of COMPANY_SIGNAL rows with `signal_date >= T-12m` (any type), then by name asc.

> v2 change: exact membership of every cast row in the naive screen (verified by script against the names above):
> - **Included**, in naive order:
>   1. D_SHORT (5)
>   2. D_VET (4)
>   3. D_SNF (3)
>   4. NM_B (2)
>   5. T_WARM (2)
>   6. T_6 (2)
>   7. CONF (2)
>   8. T_BANKER (2)
>
>   Then, among 0-signal names, A1 and D_SAME.
> - **Missed** (no keyword in name or niche): **T_COLD** ("Saltmarsh Home Infusion" / "Home Infusion Services") and **T_5** ("Quarry Records Retrieval" / "Records Retrieval & Litigation Support").
> - **Excluded by the band**: D_BIG (44.0) and BRIGHT (45.0).
> - **Pinned noise rule for R12**: no non-cast company in the naive result has 3 or more signal rows in the window. The naive top three are therefore exactly D_SHORT, D_VET, D_SNF, all wrong. R05: T_COLD's and T_5's company and niche names must contain none of the keywords.

What it gets wrong:
- **D_SHORT** tops the signal-count ranking with 5 rows, all unscored types. RAI scores it Fit 30 + Readiness 0 + Access 0 = 30, Tier C, with the two "why not" templates above.
- **D_VET** (niche Veterinary Pharmaceuticals under Life Sciences > Pharmaceutical Manufacturing; EBITDA 15.0). The `%veterinar%` keyword includes it. RAI excludes it because its niche's ancestors never reach a Fund IV focus node. The thesis tree does contain a real "Veterinary Clinics" niche under Healthcare Services > Animal Health Services, which is why the keyword exists. This is a keyword strawman, kept because section 7.3 asks for it.
- **D_SNF** (v2, R04 item 10) is the strong thesis decoy. A sector-level screen (anything under Healthcare Services) includes it as well as the keyword screen. Only the nested `exclude` node removes it. RAI says "niche Skilled Nursing Facilities is excluded from the Fund IV thesis". This shows the mixed-level include/exclude doing work.
- **Misses and misranks**: the screen misses T_COLD and T_5, two of the six. Saltmarsh is missed by both the CRM and the screen. The screen ranks NM_B (Tier B) above every Tier-A name, because it counts rows instead of dated, typed readiness.
- **D_BIG** (thesis niche Behavioral Health Clinics; EBITDA 44.0; every readiness signal) is a **near-miss, not a SQL decoy**, because the SQL band also drops it. RAI shows it as ineligible with the reason, so the rules visibly do the work (section 8.3).

**Why SQL alone fails.**
- The thesis is a hierarchy with mixed-level includes and a nested exclude (recursion).
- CFO_FROM_PE is a three-way temporal join: the CFO role, the prior role, and the prior employer's ownership interval *during* that role.
- The exit window joins ownership to fund vintage.

All of it must yield per-point explanations from one governed definition that Q-PATH, Q-CONFLICT and the finale reuse. A recursive CTE can do any single piece; the point is one model, many questions, every point explained.

**Explorer view.** Scorecard:
- The ranked list with A/B/C tier chips.
- A stacked bar per company (Fit / Readiness / Access). Hovering shows each component's evidence.
- A "not in CRM" badge on T_COLD and T_6.
- A toggle reveals the naive SQL list next to it, with D_SHORT, D_VET and D_SNF struck through and the reason shown, and T_COLD and T_5 marked "missed by screen".
- The side panel shows each rule's business-language docstring.

**Tier-1 prompt (Claude Code).**
> Which companies fit the Fund IV thesis and look ready to transact in the next 12 to 18 months? Show the Tier A list with the score components behind each one, and flag any that are not in our CRM.

**Rehearsal check (9.3).**
- Must appear: Larkspur Revenue Partners, Bayside Pediatric Therapy Group, Saltmarsh Home Infusion, Quarry Records Retrieval, Keystone Clinical Supply, Fenwick Food Safety Labs.
- Must not appear: Pembrook Veterinary Pharmaceuticals, Cobalt Urgent Care Partners, Linden Hollow Senior Care.
- R11's `q_score()` returns Tier-A rows only.

Tier-2 ad-lib suggestion: "Only show the healthcare services names." (Answer: Bayside, Saltmarsh.) Second suggestion: "What would a keyword screen have given us?" Here naming the decoys is correct, so the check is row-based.

**Chains into Q-PATH.** "Two of your six best targets are names your CRM has never logged. Knowing who to call is half the job; the other half is who makes the introduction. Take the top three."

---

### Q-PATH (graph + rules). Act 2

**Business question (MD voice).** "For our top three, what is our warmest path to each CEO, and through whom? And if the company is sponsor-owned, do we know the owner's deal partner?"

> v2 change (R04 item 6): the path target is a set of **decision-makers**, not only the CEO.
> - **CEO** = the person holding a current CEO role at the target.
> - **OWNER_DESIGNEE** = only for sponsor-owned targets: a person who holds a current Board role at the target **and** a current Deal Team role at the sponsor whose fund currently owns it.
>
> CFOs, COOs and independent directors are **not** decision-makers: they appear only as hops. This is decided as "CEO plus owner designee", not "any senior exec", because a founder CEO or the sponsor's board partner decides on a sale; an intro to a CFO is a route, not an outcome. The answer reports the CEO path and, for sponsor-owned targets, one extra row for the owner designee. This answers the partner's first objection ("we know Copperline") with data.

**Reasoner and technique.**
- *Rules: `Knows(Person, Person)`* is symmetric, with typed evidence and a strength in [0, 1]. Strength is the max over evidence. Let `recency(d)` = 1.0 if d >= T-10y, 0.7 if d >= T-20y, else 0.4.
  - **K1 tenure overlap**: two roles at the same org with `min(end1, end2) - max(start1, start2) >= 365` days (open end = T). Strength = `recency(overlap_end) * min(1.0, 0.4 + 0.15 * overlap_days / 365.25)`. The evidence label is "board co-service" only when **both** roles are Board; otherwise it is "tenure overlap".
  - **K2 deal co-participation**: both persons are `lead_person_id` on the same transaction, **or** one is a lead person and the other held a CEO/CFO role at the target on `close_date`. Strength = `0.7 * recency(close_date)`.
  - **K3 positive CRM**: an OUR_SEEDS person had 1 or more `positive` person-level interactions with the other person in [T-24m, T]. Strength 0.6 for 1, 0.8 for 2, 1.0 for 3 or more.
- `DecisionMaker(target, person, kind)` as defined above. `ClosestIntermediary(company)` (v2, R04 item 17) = the intermediary with the most recent dated tie to the company in [T-5y, T]. A tie is a BANKER_ENGAGED signal (`signal_date`, `intermediary_id`) or an advisor party (`sell_side_advisor`, `buy_side_advisor`, `debt_advisor`) on a transaction targeting the company (`close_date`). It is shown only for cold targets.
- *Graph*: `Graph(model, directed=False, weighted=False, node_concept=Person)`. Edges come from Knows, one edge per unordered pair (`id <` guard). Validate `num_nodes()` and `num_edges()` first.
  - `d_seed = graph.distance(from_=OurSeeds)` and `d_dm = graph.distance(from_=TopThreeDecisionMakers)`. These are two single-sided calls (see 0.4 item 1).
  - L(target, dm) = min over seeds of d(seed, dm), per decision-maker.
  - Path nodes satisfy `d(s,m) + d(dm,m) = L`. Rules join Knows chains of length L (L <= 3) through those nodes to produce explicit paths.
- *Rules again*: path strength = product of hop strengths. Show the best path and up to 2 alternates of the same length, ranked by strength. Report "no path within 3 hops" when L > 3 or the person is unreachable.

**Planted answer spec (golden).** Targets in Q-SCORE rank order:

> v2 change: the T_BANKER path strength is now **0.700** (K3 evidence on the first hop); owner-designee rows are added; the X_STALE hop is 0.956; labels are corrected.

| Target | Decision-maker | Hops | Best path (each hop with evidence) | Path strength | Alternates |
|---|---|---|---|---|---|
| T_BANKER | CEO_B Ruth Adeyemi | **3** | VP Priya Raman -[K1: Lakeshore Securities, overlap 2012-06-04 to 2016-06-30, 4.07 years, recency 0.7 -> 0.70; **K3: 7 positive meetings 2024-11 to 2026-09 -> 1.00**; strength = max = 1.00]- Y_BANK Sofia Brandt -[K1: Cedar Row Partners, 2017-01-09 to present, 9.72 years -> 1.00]- B_BANK Nathan Cole -[K2: lead sell-side banker on T_BANKER majority recap closed 2019-04-15 while she was CEO -> 0.70]- CEO_B | **0.700** | none (provably the only 3-hop path) |
| T_BANKER | OWN_B Owen Lacey (Ironbridge) | **>= 4** | "No path within 3 hops to Ironbridge's board designee." | - | - |
| T_WARM | CEO_W Daniel Reyes | **2** | OP Marcus Whitfield -[K1 tenure overlap: Brightwater Dental, 2015-03-01 to 2019-06-30, 4.33 years -> 1.00]- CFO_W Elena Marsh -[K1 tenure overlap: T_WARM, 2025-06-01 to present, 1.33 years -> 0.60]- CEO_W | **0.600** | MP Dana Okafor -[K1: Old Harbor Health, 1998-03-01 to 2000-06-30, 2.33 years, recency 0.4 -> 0.300]- X_STALE Walter Kim -[K1 tenure overlap (Board and CEO) at T_WARM, 2023-01-15 to present, 3.71 years -> 0.956]- CEO_W = **0.287** (rank 2 of 2) |
| T_COLD | CEO_C Victor Hale | **none within 3** | "Cold." | - | - |
| T_COLD | OWN_C Graham Pike (Copperline) | **none within 3** | "We do not know Copperline's deal partner on this asset either." Then `ClosestIntermediary` = **Harbor Lane Advisors** (engaged 2026-07-14; debt advisor on the 2023-05-18 dividend recap). This line is the hand-off to Q-FLOW. | - | - |

Role intervals R05 must plant exactly:
- OP Marcus Whitfield: Board at Brightwater 2014-09-15 to 2019-06-30.
- Dana Okafor: Old Harbor Health 1998-03-01 to 2000-06-30.
- Walter Kim: Old Harbor Health 1997-01-06 to 2001-12-14.
- Priya Raman: Lakeshore Securities 2011-07-01 to 2016-06-30.
- Plus the dates in section 2.

**Cedar Row touchpoints, all 14 in [T-24m, T] (v2, R04 item 7).**
- **10 person-level**: `our_person_id` = VP Priya Raman, `counterparty_person_id` = Y_BANK Sofia Brandt. 7 positive and 3 neutral, spread 2024-11 to 2026-09.
- **4 org-level**: `counterparty_org_id` = CEDAR, person NULL, neutral. 2 by MP Dana Okafor (annual coverage reviews) and 2 by MD_MER Tom Brennan (conference meetings).
- No other CRM interaction in the whole dataset has a Cedar Row person as counterparty.

**Invariants (they must survive the P5 noise; R06 asserts each one by BFS and enumeration).**
- *T_BANKER: exactly one shortest path, so 0.700 is provably the maximum.*
  - d(seeds, CEO_B) = 3.
  - The Knows neighbors of CEO_B at seed-distance 2 are exactly {B_BANK}.
  - The Knows neighbors of B_BANK at seed-distance 1 are exactly {Y_BANK}.
  - The seeds adjacent to Y_BANK are exactly {VP}.
  - So the set of 3-hop seed paths to CEO_B is exactly {VP - Y_BANK - B_BANK - CEO_B}. Every other Knows neighbor of CEO_B (COO, CFO, board members, other bankers) has seed-distance >= 3.
- *T_WARM: exactly two shortest paths, so 0.600 is the maximum.*
  - d(seeds, CEO_W) = 2.
  - The Knows neighbors of CEO_W at seed-distance 1 are exactly {CFO_W, X_STALE}.
  - The seeds adjacent to CFO_W are exactly {OP}, and the seeds adjacent to X_STALE are exactly {MP}.
  - EX_NW Harold Becker (not a seed) is Northwind's lead on the Brightwater transactions. So no seed has a K2 edge to CFO_W, and no other Northwind seed held a Brightwater role overlapping CFO_W's by 365 days or more.
- *T_COLD:*
  - d(seeds, CEO_C) >= 4 or unreachable.
  - d(seeds, OWN_C) >= 4 or unreachable.
  - HL is the only intermediary with a tie to T_COLD in [T-5y, T].
- *Owner designees:*
  - d(seeds, OWN_B) >= 4. Its nearest neighbors are CEO_B (board overlap since 2021-06-01) and IB_LEAD Martin Greer (Ironbridge overlap 2012-2021). Both are at seed-distance 3, and IB_LEAD gets there through the K2 edge with Nathan Cole on the 2019 recap. This is why OWN_B must not be a lead person on that recap.
  - d(seeds, HL_MD) >= 3 and d(seeds, every lead person on Copperline's 2020 buy of T_COLD) >= 3. OWN_C is Copperline's lead person on the 2020 buy and on the 2023 recap (as `owner`), so these keep d(seeds, OWN_C) >= 4.
- No OUR_SEEDS person is within 1 hop of CEO_W, CEO_B or CEO_C.
- All hero A_CRM touches in Q-SCORE are **org-level** (`counterparty_org_id` set, person NULL), so they create no Knows edge.
- Harbor Lane's single touchpoint in the last 24 months is org-level and `neutral` (2025-11-20).
- No CRM interaction of any sentiment has B_BANK, HL_MD, OWN_B, OWN_C or any target CEO as counterparty. The only seed with a K3 edge to a Cedar Row person is VP, and the only such person is Y_BANK.
- `must_not_contain`:
  - any path to CEO_C or OWN_C;
  - any path using Meridian Lab Services;
  - the stale path ranked first for T_WARM;
  - any T_BANKER alternate.

**Decoy spec.**
- **False warm intro (shared employer, no overlap).**
  - MD_MER Tom Brennan was at Meridian Lab Services 2008-01-07 to 2011-06-30. CEO_C Victor Hale was there 2013-03-04 to 2020-08-31.
  - The naive SQL (`data/naive_sql/q_path.sql`) self-joins ROLE_HISTORY on `org_id`, with one side in OUR_SEEDS and the other a target CEO, ignoring dates. It reports "Tom Brennan knows Victor Hale via Meridian", a 1-hop warm intro to the target RAI calls cold.
  - The rule rejects it: the intervals never overlap, by a gap of 613 days.
- **Stale tie.** Dana Okafor and Walter Kim overlapped 1998-2000. The tie exists and appears as T_WARM's alternate, but at 0.287 it ranks below the fresh 0.600 Brightwater path. A count-of-connections approach would treat them as equal.
- **"We know the sponsor."** (v2) An org-level CRM touch with Copperline is allowed in the data: one neutral meeting by MP, 2025-03-04. A CRM search for "Copperline" therefore says "we know them". The rule answers with the person who decides: Graham Pike, the owner designee, is more than 3 hops away.

**Why SQL alone fails.** Every hop needs interval overlap with a duration threshold. Path length is variable: 3 for one target, 2 for another, none for the third. The evidence must survive per hop. Decision-makers depend on current ownership. A shared-employer join confuses "same company" with "knew each other".

**Explorer view.** Warm path:
- Pick a target and the shortest paths from Northwind people light up. Each edge is labeled with its evidence ("Overlapped at Brightwater Dental, 2015-03 to 2019-06, 4.3 years").
- The alternate path is dimmed, with its strength.
- Owner designees appear as a second target node with their own "no path within 3 hops" chip.
- For T_COLD, a "no path within 3 hops" banner shows:
  - the struck-through Meridian claim ("shared employer, never overlapped: 2008-2011 vs 2013-2020");
  - the Copperline row;
  - a link "Closest intermediary: Harbor Lane -> Deal flow".

**Tier-1 prompt (Claude Code).**
> For our top three targets, what is our warmest path to each CEO, and through whom? Show every hop with its evidence, check the owner's board designee for sponsor-owned targets, and say plainly if a target is cold.

**Rehearsal check (9.3).**
- Must appear: Ruth Adeyemi, Priya Raman, Sofia Brandt, Nathan Cole, Daniel Reyes, Marcus Whitfield, Elena Marsh, Victor Hale, Graham Pike.
- Must not appear: Tom Brennan, Meridian Lab Services. `q_path()` returns paths and cold rows only, never rejected candidate ties.
- Row check: Walter Kim may appear only as the second-ranked T_WARM alternate.

Tier-2 ad-lib suggestions:
- "Why isn't Tom Brennan's Meridian connection a path to Victor Hale?" Here naming the decoy is correct, so the check is row-based.
- "We know Copperline. Doesn't that get us into Saltmarsh?"

**Chains into Q-FLOW.** "Two of three are reachable this quarter. Saltmarsh is cold to us, and we don't know Copperline's partner either. But it is not cold to everyone: Harbor Lane is engaged on it and advised its 2023 recap. Which intermediaries actually move deals in our sectors, and are we covering them?"

---

### Q-FLOW (graph + rules). Act 3

> v2 change: Q-FLOW is now Act 3 (it was Act 4). The Tier-1 prompt changed (R04 item 3). BIGBANK is pinned at rank >= 11 with about 40 deals. Q1 is pinned. HL is `debt_advisor`. The business question uses "bridge".

**Business question (MD voice).** "Which intermediaries actually bridge deal flow between founders and sponsors in our sectors, and where is our coverage weakest?"

**Reasoner and technique.**
- *Rules (graph input)*:
  - Transactions with `close_date` in [T-5y, T] whose target niche is in the Fund IV thesis tree. This reuses the Q-SCORE closure.
  - Nodes: Organizations (Intermediary, Sponsor, Company). A fund maps to its sponsor.
  - Edges: one per distinct unordered pair among {advisor-target, advisor-buyer, advisor-seller, advisor-owner, buyer-target}.
  - The advisor is any party with role `sell_side_advisor`, `buy_side_advisor` or `debt_advisor`. Lenders are not advisors.
  - For an add-on the buyer is the platform company. For a recap with no change of control, the `owner` party stands in for buyer and seller.
- *Graph*: `Graph(model, directed=False, weighted=False)`. Validate the node and edge counts first. Then:
  - `graph.betweenness_centrality(num_pivots=16000)`: exact Brandes, deterministic, because 16000 >= |V| (see 0.4 item 3 and the v2 note).
  - `graph.pagerank()` as a secondary "reach" column. It is displayed only; there is no golden ranking on it.
  - Rank intermediaries by betweenness.
- *Rules (`CoverageGap`)*:
  - `touchpoints_24m(i)` = count of CRM interactions in [T-24m, T] with org i or with a person holding a current role at i.
  - An intermediary is a gap iff its betweenness rank among intermediaries is `<= ceil(0.10 * N_int_in_graph)` (top decile) **and** `touchpoints_24m <= Q1`.
  - Q1 is the value at position `ceil(0.25 * N_int)` in the ascending sorted touchpoint list over **all** INTERMEDIARY rows (bottom quartile).

**Planted answer spec (golden).**

| Intermediary | Deals in window (thesis sectors) | Betweenness rank (intermediaries) | Touchpoints 24m | Coverage gap |
|---|---|---|---|---|
| CEDAR Cedar Row Partners | about 14 | **1** | 14 (10 person-level with Sofia Brandt, 4 org-level) | no |
| HL Harbor Lane Advisors | **9** | **2** | **1** (org-level, neutral, 2025-11-20) | **yes (the only gap)** |
| BIGBANK Continental Capital Markets | 8 in thesis (**about 40** overall) | **>= 11** | 9 | no |

- **HL's 9 in-window deals**:
  - 8 sell-side mandates for founder-owned healthcare-services companies (`seller_type = founder_family`), sold to buyers belonging to **5 distinct sponsors**.
  - T_COLD's dividend recap (`structure = dividend_recap`, 2023-05-18). HL is `debt_advisor` with `lead_person_id` = HL_MD. Copperline Partners Fund II is `owner`, and Copperline is one of the 5 sponsors.
  - On stage say "Harbor Lane advised Saltmarsh's 2023 recap".
- **Construction guidance for R05**:
  - Those 5 sponsors have at most 2 other in-window thesis deals each, all with other advisors, so HL is their main bridge into the rest of the graph.
  - Keep `N_int_in_graph` between 31 and 40, so the top decile is exactly 4 intermediaries.
  - BIGBANK's 8 thesis deals are with large sponsors that use many other advisors. Tune until networkx exact betweenness gives CEDAR 1, HL 2 and BIGBANK >= 11. R06 confirms independently.
- **Q1 pinned at 1 (v2, R04 item 13).** Over the 50 INTERMEDIARY rows, exactly 8 have 0 touchpoints and at least 5 have exactly 1 (HL among them). Position ceil(0.25 x 50) = 13 is then 1. If R05 changes the row count N, keep "count with 0 < ceil(0.25 N) <= count with <= 1".
- The other two top-decile intermediaries (ranks 3 and 4, context boutiques named by R05) have **3 or more** touchpoints each (suggested 7 and 4). So HL is the only gap. Ranks 3 and beyond carry no golden order.
- `must_not_contain` (gaps): CEDAR, BIGBANK.
- Closing the loop: **HL advised T_COLD's last recap** and is `ClosestIntermediary(T_COLD)` in Q-PATH.

**Decoy spec.** The naive SQL (`data/naive_sql/q_flow.sql`) is a league table: `COUNT(DISTINCT txn_id)` per advisor over **all** transactions in the last 5 years, sorted desc.
- **BIGBANK tops it with about 40 deals**, and HL sits around 10th with 9.
- In the sector-scoped network, BIGBANK's 8 thesis deals connect sponsors that are already well connected, so it bridges little and ranks 11th or lower.
- The league table also cannot see that we have touched HL once.

**Why SQL alone fails.** Betweenness is a global property: the share of all shortest paths through a node. It cannot be computed from a node's own rows, and volume is not control. The coverage gap then combines a graph metric with a dated CRM count in one rule.

**Explorer view.** Deal flow:
- Intermediaries, sponsors and companies in thesis sectors. Intermediaries are sized by betweenness, with a touchpoint-count ring overlay.
- The coverage gap (HL) is outlined in red.
- Clicking HL lists its 9 deals, highlights T_COLD's recap edge and links back to T_COLD's "cold" card in the warm-path view.
- A side table, behind a "Compare with league table" toggle, puts the naive league table (BIGBANK first) next to the betweenness ranking. The explorer is not subject to the 9.3 name check.

**Tier-1 prompt (Claude Code).** (v2 change: no league-table comparison; asks for the top five.)
> Which intermediaries actually bridge deal flow in our Fund IV sectors, and where is our coverage weakest? Show the five that bridge the most deal flow, our touchpoints with each over the last 24 months, and any coverage gap.

**Rehearsal check (9.3).**
- Must appear: Cedar Row Partners, Harbor Lane Advisors.
- Must not appear: Continental Capital Markets. It ranks >= 11, so it is never in a top-5 or top-10 table.
- R14: `demo_workspace/CLAUDE.md` must not tell Claude to add a league-table contrast to Tier-1 answers.

Tier-2 ad-lib suggestions:
- "How does that compare with a simple deal-count league table?" Expected: Continental Capital Markets tops the count with about 40 deals and is not a top-decile bridge. Naming it is correct here, so the check is row-based.
- "Which of Harbor Lane's deals involve companies on our Tier A list?" (Answer: Saltmarsh.)

**Chains into Q-CONFLICT.** "Harbor Lane is the gap: one call this week. Cedar Row is the opposite: our best-covered bridge. Cedar Row has just been engaged on Keystone, #5 on our list, and we are preparing an IOI. Before we spend Cedar Row's time, the question every IC asks first: does it conflict with anything we own, and does it fit the fund?"

---

### Q-CONFLICT (graph + rules). Act 4

> v2 change: promoted from backup to hero (R04 item 1). Rebuilt per R04 item 2:
> - (a) the cap is a 35% IC guideline per thesis area;
> - (b) the holdings are listed;
> - (c) a strong explorer view;
> - (d) final names, and no decoy-inviting wording.

**Business question (MD voice).** "Before we bid on Keystone, does it conflict with anything we own, and would it push Fund IV over its sector concentration guideline?"

**Reasoner and technique.**
- *Graph*: the commercial graph, `Graph(model, directed=False, weighted=False, node_concept=Company)`. Edges come from COMMERCIAL_LINK (supplier-customer, direction dropped, kept as evidence). This is the same construction as the Q-ADDON backup's graph: one graph, two uses. Validate `num_nodes()` and `num_edges()` first. Then:
  - `d_conf = graph.distance(from_=SubjectSet)`, SubjectSet = {CONF}: a single-sided call.
- *Rules*:
  - `NorthwindHolding(company, fund)`: a **current** OWNERSHIP (end NULL or > T) by a Northwind fund. Time-bounded: "ever owned" does not count.
  - `PortfolioExposure(subject, company, fund, d, kind, evidence)` for every NorthwindHolding with `d_conf <= 2`:
    - **CONFLICT - cross-fund review** iff d = 1 and the fund is not Fund IV (the buying fund). Buying a direct supplier or customer of another Northwind fund's company is a cross-fund related-party matter for the conflicts committee and, if required, the LPAC.
    - **SAME-FUND LINK** iff d = 1 and the fund is Fund IV (none planted).
    - **SHARED COUNTERPARTY (informational)** iff d = 2.
    - Evidence comes from a two-link rule join through the middle company, with link directions ("Keystone supplies Bluestem; Bluestem buys from Granite").
  - `ThesisArea(company)` = the Fund IV include node above the niche (the Q-SCORE closure, mixed levels).
  - `AreaExposure(area)` = sum of `equity_invested_musd` over current Fund IV holdings in the area, divided by Fund IV `size_musd`.
  - `ProFormaExposure(area)` adds the subject's `PIPELINE.est_equity_check_musd` when the subject's thesis area is that area.
  - **Guideline breach** iff pro forma > `area_guideline_pct` (35%). Headroom = 35% x size - current exposure.

**Fund IV current holdings (exact, for the oracle).** Fund IV size $1,200M.

| Holding | Thesis area > niche | Since | Equity $M | % of fund |
|---|---|---|---|---|
| GRANITE Granite Testing Group | TIC > Materials Testing | 2024-03-15 | 150 | 12.5% |
| MEADOW Meadowbrook Physical Therapy | Healthcare Services > Physical Therapy Clinics | 2023-09-12 | 110 | 9.2% |
| DIST1 Tidewater Chemical Distribution | Specialty Distribution > Specialty Chemicals Distribution | 2023-11-01 | 140 | 11.7% |
| DIST2 Juniper Industrial Supply | Specialty Distribution > Industrial MRO Distribution | 2024-08-20 | 125 | 10.4% |
| DIST3 Sable Ingredients Co | Specialty Distribution > Specialty Food Ingredients Distribution | 2025-06-02 | 120 | 10.0% |
| Total deployed | | | 645 | 53.8% |

Fund IV holds nothing else. Fund III's current holdings include PINE and REDFERN, plus noise. Fund II has no current holdings.

**Planted answer spec (golden).**

| Row | Company | Fund | Commercial distance | Kind | Evidence |
|---|---|---|---|---|---|
| 1 | PINE Pinecrest Dental Partners | Fund III (since 2020-07-01) | 1 | **CONFLICT - cross-fund review** | Keystone supplies Pinecrest (COMMERCIAL_LINK supplier CONF, customer PINE) |
| 2 | GRANITE Granite Testing Group | Fund IV (since 2024-03-15) | 2 | informational: shared customer | Keystone supplies Bluestem Engineering Group (C07); Bluestem buys from Granite |

| Concentration (Fund IV, guideline 35%) | Before | With Keystone ($55M check) |
|---|---|---|
| **Specialty Distribution** | $385M = 32.1% | **$440M = 36.7% -> breach** (headroom $35M; over by $20M) |
| TIC | 12.5% | 12.5% |
| Healthcare Services | 9.2% | 9.2% |
| Tech-Enabled Business Services | 0.0% | 0.0% |

- **So what (talk track):** "Keystone is a real Tier-A target, but it needs cross-fund review because it supplies Pinecrest, and at a $55M check it takes Specialty Distribution over our 35% guideline. Either size the check at $35M or less and syndicate the rest as co-invest, or take it to IC as an exception."
- **CONF's commercial neighborhood (exact).** Customers: PINE, C07, H1, BRIGHT, plus 4 context customers. Suppliers: 2 context manufacturers. None of the context neighbors is a Northwind holding or adjacent to one, except C07 (adjacent to GRANITE).
- **Invariants (R12 must preserve):**
  - The set of NorthwindHolding companies at commercial distance <= 2 from CONF is exactly {PINE (1), GRANITE (2)}.
  - REDFERN is at distance exactly 3 (CONF - H1 - H2 - REDFERN: CONF supplies H1, H2 supplies H1, H2 supplies REDFERN).
  - BRIGHT is at distance 1 and is **not** a current Northwind holding.
  - No noise link touches CONF, PINE, C07, H1, H2 or REDFERN.
- `must_not_contain` (exposure rows): REDFERN (distance 3, the bound check) and BRIGHT (former holding).

**Decoy spec.** The naive SQL (`data/naive_sql/q_conflict.sql`) is what an associate writes:
1. Join COMMERCIAL_LINK (either direction, 1 hop) to every Northwind OWNERSHIP row, **without** the current-ownership filter. Result: {PINE, **BRIGHT**}. BRIGHT is a false alarm, because Northwind sold Brightwater on 2020-02-14. The query also **misses** GRANITE, which is 2 hops away.
2. Concentration by `GROUP BY` the company's own sector (niche), adding Keystone's check to its niche. The largest niche is Specialty Chemicals Distribution at 11.7%, and Keystone's niche goes to 4.6%. Result: "no concentration issue". It **misses the breach**, because the guideline applies to the thesis area, which needs the hierarchy rollup.

The naive answer is "one conflict, one false conflict, no concentration issue". The model's answer is "one conflict, one informational link, a guideline breach of $20M".

**Why SQL alone fails.**
- Bounded multi-hop reach over commercial links, with path evidence per exposure.
- Ownership that must be current at T, not ever.
- Classification by which fund holds the exposed company.
- A concentration rollup to mixed-level thesis areas, reused from Act 1.

All of this is one governed definition that the Finale then applies to every target in one sentence. Each piece is a few joins; the value is that the model already knows what "ours", "current" and "thesis area" mean.

**Explorer view: "Conflict check" (new; replaces the add-on map on the hero path).**
- Keystone is in the center, with its 2-hop commercial ego graph.
- The PINE edge is solid red ("supplies; Fund III; cross-fund review").
- CONF - Bluestem - Granite is dashed amber ("shared customer; informational").
- The Brightwater edge is grey, with a struck-through "Northwind portfolio" tag and "sold 2020-02-14".
- Redfern sits at the 3-hop rim, greyed, with "outside the 2-hop check".
- Beside it, a before/after **concentration gauge**: one bar per thesis area, a dashed 35% line, and Specialty Distribution crossing it (32.1% -> 36.7%) with "headroom $35M".
- The side panel shows the rule docstrings for NorthwindHolding, PortfolioExposure and the guideline.
- R15: section 7.4 lists an add-on map; build the Conflict check view for Act 4 and keep the add-on map only as an optional view for the backup.

**Tier-1 prompt (Claude Code).**
> Before we bid on Keystone Clinical Supply, does it conflict with anything we own, and would the deal push Fund IV over its sector concentration guideline?

**Rehearsal check (9.3).**
- Must appear: Keystone Clinical Supply, Pinecrest Dental Partners, Granite Testing Group, Specialty Distribution.
- Must not appear: Brightwater Dental, Redfern Imaging Centers. `q_conflict()` returns only current-holding exposure rows and the area table, so neither name is in its output.

Tier-2 ad-lib suggestion: "Our old portfolio list says Brightwater is a Keystone conflict. Is it?" Expected: no, Brightwater was sold 2020-02-14. Naming it is correct here, so the check is row-based. Second suggestion: "What is the largest check we could write without breaching the guideline?" (Answer: $35M.)

**Chains into the Finale.** "That check should not depend on someone remembering to ask it. Let's make it part of the score for every target, together with what we learned about access in Act 2."

---

### Finale (rules composing graph output; Tier-2 live authoring)

> v2 change (R04 items 5, 8, 9):
> - The prompt is reworded to define "reach" (CEO, two hops) and to say "flag it and take it off the Tier A list", matching the golden.
> - Guards F1 and F2 are added.
> - The decoy check is row-based.
> - The conflict rule reuses the Q-CONFLICT definitions.

**Prompt the presenter types (verbatim).** This refines the section 7.3 wording so the golden answer and the words match.
> Add two rules and re-score. One: a target gets 10 access points if one of our deal team or operating partners can reach its CEO in two hops or fewer. Two: any target that is a customer or supplier of a current Fund III portfolio company is a conflict, so flag it and take it off the Tier A list.

**Technique.**
- Claude Code uses `rai-rules-authoring` to add two derived properties.
- **`A_WARM_PATH = 10`** iff min over OUR_SEEDS of `d_seed(seed, current CEO) <= 2`.
  - It reuses the Q-PATH `distance(from_=OurSeeds)` relationship, so a graph output feeds a rule.
  - **"Reach" is defined as CEO-only, Knows distance, any seed.** R09's FINALE docstring says exactly this.
  - Guard F2 makes the other readings give the identical set {T_WARM, NM_B}: "any current role-holder", "decision-makers incl. owner designee", "any Northwind person".
- **`Conflict(company)`** iff a COMMERCIAL_LINK exists in either direction between the company and a `NorthwindHolding` of Fund III. This is Q-CONFLICT's `PortfolioExposure` with d = 1, Fund III.
  - Conflicted companies keep their score.
  - They get the flag "Conflict - cross-fund review" and are removed from the Tier-A list ("flag and take off Tier A").
  - The demo says: "the score did not change; the eligibility to be on Monday's call list did".
- Score and tier are then re-derived.
- **Fallback**: R09 ships the same two rules in `rules.py` behind a `FINALE` flag, and `queries.py` has `finale_rescore()`. A failed live authoring step still lands on the identical answer.

**Planted answer spec (golden).** Tier A after the finale:

| Rank | Key | Score | Change |
|---|---|---|---|
| 1 | T_WARM | **95** | +10 warm path (CEO at 2 hops); moves from #2 to #1 |
| 2 | T_BANKER | 90 | CEO at 3 hops, no change; drops from #1 to #2 |
| 3 | T_COLD | 80 | cold, no change |
| 4 | T_5 | 75 | no change (CEO at >= 3) |
| 5 | NM_B | **75** | +10 warm path; **rises from Tier B (65) into Tier A**; ranks below T_5 on readiness (35 vs 40) |
| 6 | T_6 | 70 | no change (CEO at >= 3) |
| - | CONF | (75, score unchanged) | **flagged "Conflict - cross-fund review" and off the Tier-A list**: supplies PINE Pinecrest Dental Partners (Fund III since 2020-07-01) |

- NM_B's planted path:
  - OP2 Grace Liu -[K1 tenure overlap: Lakemont Orthodontics, 2016-02-01 to 2020-05-31, 4.33 years -> 1.00]- Z (Board at NM_B since 2022-04-01; at Lakemont 2015-08-03 to 2021-03-31).
  - Z -[K1 tenure overlap (Board and CEO) at NM_B, 2022-04-01 to present, 4.50 years -> 1.00]- NM_B CEO (founder since 2006-03-01).
  - d = 2. The Knows neighbors of the NM_B CEO at seed-distance 1 are exactly {Z}, and the seeds adjacent to Z are exactly {OP2}.
- **Guard F1 (no other riser).** In the signal layer, NM_B is the **only** scored company with an Act-1 score in [60, 69]. R12 may add 60-69 scorers in P5 only if Guard F2 holds for them. R06 asserts: for every scored company other than NM_B with an Act-1 score in [60, 69], every current role-holder has seed-distance >= 3.
- **Guard F2 (reach readings agree).** For T_BANKER, T_COLD, T_5, T_6 and CONF, every person holding a current role of any type at the company has seed-distance >= 3. This includes CEO, CFO, COO, Board and owner designees. For T_BANKER the CEO is exactly 3. For T_COLD, the CEO and OWN_C are >= 4.
- **Brightwater** is ineligible (EBITDA 45.0), so it cannot rise despite its old ties to OP and CFO_W.
- **Conflict guard.** No Tier-A or NM_B company except CONF has a COMMERCIAL_LINK to any current Fund III holding. CONF's link to PINE is CONF as supplier, PINE as customer.
- `must_not_contain` (Tier-A rows after the finale): CONF. The decoy check is **row-based**: Keystone must be named as flagged and must not be in the Tier-A rows (R11, R17).

**Rehearsal check (9.3, Tier-2 at 2 of 3).** Must appear: Bayside Pediatric Therapy Group, Larkspur Revenue Partners, Saltmarsh Home Infusion, Quarry Records Retrieval, Alder Creek Dental Partners, Fenwick Food Safety Labs, Keystone Clinical Supply (as flagged). Row check: Keystone is not among the Tier-A rows.

**Decoy spec.** CONF is the Q-SCORE Tier-A lookalike. Every point it earned in Act 1 was real. Act 4 showed the conflict for one name, on request. The finale makes the same check automatic for every target. Neither a CRM nor a thesis screen joins pipeline targets to the *other* fund's portfolio supply chain.

**Why SQL alone fails.** The new access points come from a graph distance computed in Act 2. The conflict comes from commercial links joined to time-bounded fund ownership, defined in Act 4. Both slot into the existing score as named, explained components. The ranking changes in two sentences, with no new pipeline.

**Explorer view.** The scorecard re-renders with a "Finale" toggle. Before and after columns show the rank movement arrows: T_WARM up, NM_B new, CONF struck with a "Conflict - cross-fund review" chip. Clicking CONF jumps to the Conflict check view.

**Chains into the close.** "Governed, explainable, in your Snowflake; and Claude is the interface."

---

## 4. Backups (2)

> v2 change: the backups are now **Q-ADDON** (demoted from hero) and **Q-COMPETE**. Q-CONFLICT moved to the hero set. Q-EXEC stays rejected: career-path similarity is hard to plant so that an independent oracle agrees on a ranking, it overlaps with Q-PATH, and its "so what" is the weakest for a partner.

### Q-ADDON (graph). Backup (demoted in v2)

> v2 change: demoted. R04 scored Reasoning necessity 2: Jaccard from one platform node is a single self-join GROUP BY, and the planted order equals the raw shared count. R20 considered re-planting so that size normalization changes the order, but any single-source Jaccard or Adamic-Adar remains one SQL query. It is kept as a backup because its data (GRANITE's neighborhood) is needed anyway for Q-CONFLICT (C07). Use it only for a Tier-2 "what should Granite buy next?" ad-lib. The v1 bridge line into Q-FLOW is deleted (R04 item 18).

**Business question.** "Which add-ons best extend our Granite Testing platform, beyond the obvious same-niche names?"

**Technique.**
- *Graph*: the commercial graph above. Run `graph.jaccard_similarity(from_=PlatformSet)` with `PlatformSet` = {GRANITE}, and filter out self-pairs. `graph.louvain()` (default seed) colors the ecosystem in the explorer only.
- *Rules*:
  - **Candidate eligibility**: the niche shares GRANITE's TIC ancestor by closure; no current sponsor-fund ownership; `ebitda_musd <= 15.0`; US HQ; no direct COMMERCIAL_LINK with GRANITE.
  - **Whitespace**: states in COMPANY_SITE for the candidate minus states for GRANITE.
  - The shared-customer list is the evidence.
  - Rank by Jaccard desc.

**Planted answer.** GRANITE's neighborhood is exactly 18 companies: customers C01-C15 (C07 = Bluestem Engineering Group) and suppliers S1-S3. Its sites are TX, OK, LA, AR.

| Rank | Key | Niche | Neighbors | Shared with GRANITE | Jaccard | Sites | Whitespace states |
|---|---|---|---|---|---|---|---|
| 1 | A1 Clearwater Environmental Labs | Environmental Testing | 10 (C01-C06 plus 4 own customers) | 6 | **6/22 = 0.2727** | TX, CO, UT, NM | **CO, UT, NM (3)** |
| 2 | A2 Ridgeline NDT Services | Non-Destructive Testing | 8 (C08, C09, C10 plus 5 own) | 3 | **3/23 = 0.1304** | TX, LA | none |
| 3 | A3 Summit Calibration Co | Calibration Services | 4 (C11, C12 plus 2 own) | 2 | **2/20 = 0.1000** | OK, KS | KS (1) |

- `must_not_contain`: D_SAME. It is absent from the similarity result because it shares no neighbor.
- R12 adds **no** COMMERCIAL_LINK incident to GRANITE, A1, A2, A3 or D_SAME. No other eligible candidate may reach Jaccard >= 0.10.
- The C07 link CONF -> C07 is not incident to GRANITE, so it leaves every value above unchanged.

**Decoy.** The naive SQL (`data/naive_sql/q_addon.sql`) takes companies in GRANITE's own niche with an HQ in GRANITE's states, ranked by revenue. Its top row is D_SAME Bedrock Materials Testing (EBITDA 9.0, revenue 55, sites TX, OK, LA). R04 notes this is a weak decoy, because a density tuck-in is not wrong in itself. That is accepted for a backup.

**Why SQL fails (honest version).** The candidate pool needs the hierarchy, and the ranking is a neighborhood similarity. Both can be written in SQL. The value is reuse of the same commercial graph as Q-CONFLICT.

**Explorer view.** An optional add-on map: GRANITE in the center, candidates sized by Jaccard and colored by Louvain community, and whitespace states.

**Tier-1 prompt.**
> Which add-ons best extend our Granite Testing platform, beyond the obvious same-niche names? Show the shared customers and the new states each one adds.

**Chains.** It is an optional ad-lib after Q-CONFLICT ("Granite came up as a shared customer; what should Granite buy next?").

### Q-COMPETE (rules + graph). Backup

> v2 change: only the references are updated. R04 scored it 18, Reasoning necessity 2. It remains a backup only.

**Business question.** "Which of our Tier-A targets are competitor sponsors already circling?"

**Technique.**
- *Rules*: `Circling(target, sponsor, evidence)` iff a person holds a **current** Operating Partner role at a non-Northwind sponsor **and** a Board role at the target that started within [T-24m, T].
- *Graph*: on the commercial graph, `graph.jaccard_similarity(from_=CompetitorPlatforms, to=TierATargets)`. The `from_` plus `to` combination is allowed for Jaccard.
  - CompetitorPlatforms = companies currently owned by a non-Northwind sponsor fund whose acquiring transaction has `deal_role = platform`.
  - "Platform fit" holds iff the score is >= 0.20.

**Planted answer.**
- T_5: Ashgrove Partners' Operating Partner Rafael Ortiz joined its board on 2026-03-16. This is the same fact that earned T_5 its NEW_DIRECTOR point, read two ways.
- T_6: Jaccard **0.30** with Keel Industrial Testing, Blackfern Capital's platform. R05 plants 6 shared out of a union of 20. Keel and T_6 have no links to GRANITE's or CONF's neighborhoods.
- Exactly {T_5, T_6}. Rafael Ortiz has seed-distance >= 3 (Guard F2 for T_5).

**Decoy.** T_BANKER's COO was an Operating Partner at Ashgrove from 2014 to 2019 (ended). The naive "ever worked at a competitor" join flags T_BANKER. The rule requires a current competitor role, so T_BANKER is `must_not_contain`. The COO has seed-distance >= 3 (Guard F2).

**Why SQL fails.** Temporal role logic plus neighborhood similarity to competitor platforms.

**Explorer view.** Scorecard with a "circled by" chip; add-on-map style view of T_6 next to Keel.

**Tier-1 prompt.**
> Which of our Tier A targets are competitor sponsors already circling, and what is the evidence?

**Chains.** It follows Q-SCORE as an "urgency" overlay if a partner asks "who else is looking?"

---

## 5. Guidance for downstream roles

> v2 change: this whole section is updated for the new hero set and the v2 numbers.

- **Orchestrator**: set `hero_questions` to `["Q-SCORE", "Q-PATH", "Q-FLOW", "Q-CONFLICT"]` and log degrade step 1 (Q-ADDON -> Q-CONFLICT) in `STATE.json.degradations`.
- **R05**:
  - Plant exactly the dates, values and invariants above. Keep every role key out of Snowflake. Shuffle IDs.
  - v2 deltas against any v1 data already generated:
    - CONF's components (no CFO_FROM_PE; NEW_DIRECTOR Helen Voss 2026-02-17; positive org-level CRM 2026-06-10; PIPELINE stage "IOI prep", check $55M).
    - NM_B's components (BANKER 2026-07-29; NEW_DIRECTOR Iris Calloway 2026-03-02; CFO hired from a founder-owned company; last CRM touch 2023-02-10 neutral).
    - The full signal table in Q-SCORE.
    - D_SNF.
    - Brightwater EBITDA 45.0 / revenue 300, and CONF supplies it.
    - Owner designees OWN_B and OWN_C.
    - EX_NW Harold Becker as Northwind's Brightwater lead.
    - The 14 Cedar Row touchpoints as specified.
    - HL `debt_advisor` and Copperline `owner` on the recap.
    - BIGBANK about 40 deals.
    - The Q1 distribution.
    - Fund IV holdings and `area_guideline_pct`.
    - C07 = Bluestem; H1, H2, REDFERN.
    - Lakemont, Old Harbor and Meridian pinned ineligible.
    - Fund II has no current holdings.
    - Priya Raman's title.
  - T_COLD's and T_5's names contain no naive keyword.
  - Any rename must be propagated to the Tier-1 prompt text and the rehearsal name lists through `golden/stories.md`. R14 writes `prompts.md` from the final names.
- **R06**: everything here can be computed in pandas and networkx.
  - Use `nx.betweenness_centrality(G, normalized=False)` (exact); assert ranks.
  - Use BFS for distance, and simple-path enumeration (cutoff 3) to prove the "exactly one / exactly two shortest paths" invariants.
  - Compare floats with abs tol 1e-3.
  - Path strengths: T_BANKER **0.700**; T_WARM 0.600 and 0.287; NM_B 1.000.
  - Concentration: 32.1% -> 36.7%.
  - Assert Guards F1 and F2.
- **R09/R10**:
  - The Q-PATH seed-distance relationship is reused by the finale. Do not compute it twice with different seeds.
  - The commercial graph is shared by Q-CONFLICT and the Q-ADDON backup.
  - Pass `num_pivots=16000` for betweenness.
  - Do not use `rank()` in graph selects. Sort in pandas (rai-graph-analysis pitfall).
  - Docstrings: the FINALE reach rule says "CEO, Knows distance from any Northwind deal-team or operating-partner seed, two hops or fewer". The Conflict rule says "a conflict flag keeps the score but takes the target off the Tier-A call list pending cross-fund review".
- **R11**: ranking assertions:
  - Q-SCORE: full order with the tie-break; T_5 before CONF.
  - Q-PATH: strength order, with no T_BANKER alternate.
  - Q-FLOW: CEDAR 1, HL 2, BIGBANK >= 11; ranks only.
  - Q-CONFLICT: the exact exposure rows and area percentages.
  - Finale: the full order, with CONF flagged and absent from the Tier-A rows.
  - PageRank and Louvain have no golden order.
  - The Finale decoy check is row-based. `q_conflict()` and `q_path()` must not return decoy names (see each rehearsal check).
- **R12**: noise must not break any invariant listed under each question. When in doubt, add noise away from:
  - GRANITE's neighborhood;
  - CONF's 3-hop commercial ball;
  - the 3-hop Knows balls around OUR_SEEDS;
  - HL's deal set.

  Do not add any company scoring 60-69 unless Guard F2 holds for it. Add no non-cast company with 3 or more signals in [T-12m, T].
- **R14**: use the v2 Tier-1 prompts verbatim, and the v2 Finale prompt. CLAUDE.md must not ask for league-table or "rejected tie" contrasts in Tier-1 answers. Those are Tier-2.
- **R15**: views are Scorecard, Warm path, Deal flow, **Conflict check** (new) and Finale toggle. The add-on map is optional, for the backup only.
- **R16**: the act order is Q-SCORE, Q-PATH, Q-FLOW, Q-CONFLICT, Finale, with the chain lines as written in each question.

## 6. Expected rubric scores (R20 self-assessment for R04 attempt 2; R04 decides)

| Question | Comp. | Surprise | Reasoning | Visual | Feasibility | Total | What moved since v1 |
|---|---|---|---|---|---|---|---|
| Q-SCORE | 5 | 4 | 3 | 4 | 5 | 21 | naive set exact; D_SNF exercises the nested exclude |
| Q-PATH | 5 | 4 | 4 | 5 | 4-5 | 22-23 | owner designee row; provable-max invariants; Cedar Row specified |
| Q-FLOW | 5 | 5 | 5 | 5 | 4 | 24 | "bridge" wording; prompt cannot surface the decoy; Q1 pinned |
| Q-CONFLICT | 5 | 4 | 3 | 4 | 5 | 21 | credible 35% IC guideline, listed holdings, time-bounded decoy, ego graph plus gauge |
| Finale | 5 | 4 | 4 | 4 | 4 | 21 | guards F1/F2, defined reach, prompt matches golden |
