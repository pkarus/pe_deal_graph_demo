# Experiments log: deploy mode, scale, communities, any-to-any paths

Chronological record of the experiments built on top of the original demo (Nov 3–5, 2026).
Everything here uses synthetic data. Each result is a single run unless stated otherwise.
**Schema, role, warehouse and engine names below are the values from the author's own
setup**; in code they now come from `pe_deal_graph/settings.py` (see the README).
Evidence files referenced here are per-run records in `artifacts/` on the author's machine;
they are not committed (each setup writes its own when it runs the same commands).

Contents: summary table first, then each experiment in the order it was run.

## Summary

| Area | Result |
|---|---|
| Warm-path distances from the 5 team seeds, deploy mode | Works; 4,300 rows on demo data, all matched the independent oracle |
| Distances at 10K / 100K / 1M people (13M connections) | Refresh 4m 44s / 4m 20s / 8m 03s on X-Small; all distances matched |
| Lookups on precomputed distances | ~44–49 ms median server time (warm, cached) at 100K and 1M |
| Communities (Louvain) + exact within-community betweenness, 1 level | 10K 4m 07s / 100K 7m 32s / 1M 28m 59s; all scores matched |
| Same with 5 levels / seed 7 (the demo setting) at 100K | 25-min limit: timed out. 40-min limit: **passed in 48m 58s**; largest community 1,700 vs 43 |
| Reduced exports (2 tables instead of 72) at 100K, 1 level | Refresh 7m 32s → 5m 15s, identical results |
| Any person → any person, live (`q_person_path`) | 21/21 cases matched, 1–20 hops, ties, reverse, unreachable, self |
| Cortex agent (`PE_GRAPH_ASSISTANT`) | Answers warm-path and community questions from deployed tables; routes match the original demo |
| **Any person → any person, stored procedure (`PERSON_PATH`)** | **~1.2 s at 2.5K and 100K, 2.6 s at 1M, 3.7 s at 10M** (median, X-Small warehouse, no engine); every answer checked |
| **5-level communities + within-community betweenness, hybrid (exact small / sampled large)** | **100K 2m 28s, 1M 9m 08s, 10M 45m 18s** first run; **14–35 s** when the same query is re-run; 10M previously timed out |

## Any-to-any path procedure and scalable communities — November 9–10, 2026

Follow-up to the team sync guidance (re-run the same query to separate indexing from compute,
limit hop depth, write results back, test in orders of magnitude) and to the request for
community detection plus betweenness at scale. Everything below reads the `KNOWS` and `PERSON`
tables that the existing deployments already materialized; no deployment was changed.
New objects live in one extra schema per fixture, `<deployment schema>_PATHS`.

### 1. `PERSON_PATH(source_id, target_id, max_hops, min_strength)` — stored procedure

`scripts/person_path_proc.py`. A JavaScript procedure (SELECT only) that runs a bidirectional
breadth-first search over a both-directions copy of `KNOWS` sorted by source person, then keeps
the strongest of the shortest routes (product of tie strengths, the warm-path ranking rule) and
reports how many shortest routes exist, with per-hop evidence. `max_hops` (default 12) caps the
depth; `min_strength` (default 0.0) ignores weaker ties, so threshold experiments need no
redeploy. No reasoner is started.

| People | Knows pairs | Edge table build | Cases | Passed | Median | p95 | Max | Typical distance |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2,506 | 2,525 | 1 s | 65 | 65 | 1.21 s | 1.75 s | 1.92 s | 1–15 hops |
| 100,000 | 1,297,797 | 3 s | 65 | 65 | 1.13 s | 1.56 s | 2.57 s | 3–5 hops |
| 1,000,000 | 12,983,446 | 18 s | 65 | 65 | 2.65 s | 4.60 s | 6.19 s | 4–6 hops |
| 10,000,000 | 129,700,057 | 216 s | 60 | 60 | 3.68 s | 5.88 s | 7.96 s | 5–7 hops |

Times are client wall-clock per `CALL` on `RAI_XS` (X-Small), single runs. The previous live
route (`q_person_path`) took 40–70 s per call on the 2.5K demo data.

How each size was checked:
- 2.5K, 100K, 1M: every answer compared with an independent local calculation over the edge list
  (distance, status, that every hop is a real pair, that the strength is the best possible, and
  the number of shortest routes). Includes self, reverse direction, an isolated person, an
  unknown id.
- 100K with `min_strength` 0.8 and 0.95: 35/35 each, same checks on the thresholded graph.
- 10M (too large to copy locally): 40 sampled rows of the stored five-seed distance table
  (itself validated row by row earlier) plus 10 non-seed pairs in both directions; all 279 hops
  confirmed as rows of `KNOWS`. **Strength optimality is not independently verified at 10M.**
- Known demo pairs reproduce the earlier results (20 hops, strength 0.007666; 4 hops with 5 tied
  routes, strength 0.49).

Limits: a search stops with `search_too_large` after reading 3M edges (dense real data with a
high hop cap); the edge table must be rebuilt after a deployment refresh (`--install`); the
synthetic graph has maximum degree 57.

```bash
env -u DEBUG .venv/bin/python scripts/person_path_proc.py --fixture connected1m --install
env -u DEBUG .venv/bin/python scripts/person_path_proc.py --fixture connected1m --call P19079 SCALE_P000000042
env -u DEBUG .venv/bin/python scripts/person_path_proc.py --fixture connected1m --stress 60 --json artifacts/person_path_1m.json
env -u DEBUG .venv/bin/python scripts/person_path_proc.py --fixture connected10m --stress-persisted 40 --json artifacts/person_path_10m.json
```

### 2. Communities and within-community betweenness that scale

`pe_deal_graph/communities.py` + `scripts/community_scale.py`. Exact betweenness keeps a row per
(pivot, reachable person), so it grows with the square of community size: fine for one Louvain
level (communities of ~40), 49 minutes at 100K with five levels, a timeout at 10M. The hybrid
scores communities of up to 200 people exactly and larger ones from sampled pivots drawn only
from their own members. The run is an ordinary query on the Logic reasoner over the materialized
graph (no role rules re-run) and the result is written to a table with a `SAMPLED` flag.

All runs: five Louvain levels, seed 7, reasoner `HIGHMEM_X64_S`, warehouse X-Small.

| People | Pivots (large communities) | First run | Same query re-run | Communities | Largest | Modularity |
|---:|---:|---:|---:|---:|---:|---:|
| 2,506 | 200 (exact up to 30) | 289 s | 14.5 s | 967 | 66 | 0.94 |
| 100,000 | 5,000 | 148 s | 13.6 s | 134 | 1,347 | 0.39 |
| 100,000 | 20,000 | 78 s (graph already loaded) | — | 134 | 1,347 | 0.39 |
| 1,000,000 | 50,000 | 548 s | 21.2 s | 760 | 4,979 | 0.39 |
| 10,000,000 | 100,000 | 2,718 s (45m 18s) | 34.6 s | 12,072 | 19,143 | 0.39 |

For comparison, the exact version at 100K with the same five levels took 48m 58s, and exact at
1M was only ever run with one level (28m 59s). At 10M the exact version timed out at 40 minutes
even with one level; the hybrid completed with five.

**Re-running the same query on the same reasoner is 10–80x faster.** The first run pays for
loading and indexing the source tables (and, on the 2.5K demo, that is nearly all of the 289 s);
the algorithms themselves are a small part. This is the check suggested in the team sync, and it
means the earlier "slow" numbers mostly measured one-time loading, not graph computation.

Accuracy, checked locally with NetworkX against exact scores on the reasoner's own partition:
- Exactly-scored communities: all recomputed ones match (max error 7e-7 at 2.5K, 2.5e-6 at 1M,
  7e-8 over 200 communities at 10M).
- Sampled communities (largest, smallest and random ones): the true top connector is always
  inside the sampled top 10 (top 1% for big communities). Top-10 overlap with exact:
  40–90% at 100K with 5,000 pivots, 70–100% with 20,000 pivots, 60–83% at 1M with 50,000 pivots,
  67–90% at 10M with 100,000 pivots (70% of the top 191 in the largest, 19,143-person community).
  Rank correlation is 0.68–0.88; it is held down by the ~70% of people whose exact score is zero.
- At 10M the graph is too large to copy locally: row counts and modularity were computed in
  Snowflake and the five sampled plus 200 exact communities were recomputed locally from their own edges.
- So sampled scores are good for "who are the main connectors in this group" and not for exact
  values or fine ordering. More pivots buy accuracy roughly linearly in cost.

Not done: PageRank on the people graph (the earlier POV used it; the hybrid above answers the
same "best connected in a group" question).

Reasoner size (the other team-sync suggestion) is **not settled**. A separate Medium reasoner,
`alaa_pe_deal_graph_m` (HIGHMEM_X64_M, 15-minute auto-suspend), was created so the shared Small
one was not resized. The same 1M query on it returned in 43 s because the results were already
cached for that model, which says nothing about size. With a new seed (11) to force real work it
took 226 s with the graph already loaded. The matching fresh-seed run on the Small reasoner has
not been done, so there is no like-for-like comparison yet.

```bash
env -u DEBUG .venv/bin/python scripts/community_scale.py --fixture connected1m --prepare
env -u DEBUG .venv/bin/python scripts/community_scale.py --fixture connected1m --levels 5 --seed 7 --pivots 50000 \
    --run --repeat 2 --json artifacts/community_scale_1m_l5.json
env -u DEBUG .venv/bin/python scripts/community_scale.py --fixture connected1m --levels 5 --seed 7 --pivots 50000 \
    --validate --json artifacts/community_scale_1m_l5.json
```

### 3. Smaller fixes made at the same time

- `PE_MIN_TIE_STRENGTH` (0–1) sets the warm-path graph threshold without editing code; the
  default stays the literal 0.0 that `check_graphs.py` reads.
- `PE_K1_MAX_ORG_ROLES=N` (off by default) skips tenure ties at organizations with more than N
  roles, and `scripts/knows_preflight.py` reports how many role pairs the tenure rule would
  compare on a given `ROLE_HISTORY` table. The scale fixtures cap a workplace at 16 roles (13M
  and 130M candidate pairs at 1M and 10M people); one real employer with 100,000 roles would add
  5 billion. **The cap compiles but has not been run on the engine, and no skewed fixture exists
  yet.**
- The Cortex procedure grouped roles per person with a nested scan (people x roles); it now
  groups once. The deployed procedure is unchanged until `pe_cortex_agent.py deploy` is re-run.
- `raiconfig.yaml` and the example/backup copies no longer contain the access token; it is in
  `~/.snowflake/pat_token_pe_demo` (mode 600) via `token_file_path`, which is also what
  `data/load.py` expects.
- Still open: the SQL deploy path needs the `Lowerer._coalesce_target_query` patch in
  `check_graphs.py` (recursive minimum distance does not converge on cycles in SDK 1.27.1); warm
  paths still enumerate every shortest route before ranking; a 2M fixture was not built.

## Five-level Louvain at 100K with a 40-minute limit — November 5, 2026

Same data and settings as the failed run below (100K people, 5 levels, seed 7, exact
betweenness, full exports); only the Logic timeout (40 min) and task limit (50 min) changed.

| | 1 level / seed 42 | 5 levels / seed 7 |
|---|---|---|
| Result | Passed | **Passed**; all 100,000 scores matched the oracle (max error 8.4e-9) |
| Total refresh | 7m 32s | **48m 58s** (Logic transaction 36m 54s) |
| Communities | 13,784 | 136 |
| Largest community | 43 | 1,700 |
| Modularity | 0.32 | 0.39 |

Bigger communities make exact betweenness much more expensive. Five levels at 1M on this
setup is not expected to fit in a reasonable time. Evidence:
`artifacts/people_communities_connected_100k_5_7_timeout40.json` (local only).

**Why ~70% of people have zero internal betweenness here.** A person's betweenness inside
a community is zero exactly when all their contacts in that community already know each
other (checked: 100% of a 2,000-person zero sample, 0% of the non-zero sample). In the
synthetic generator every workplace is a fully connected group, and 88% of zero-score
people have only one of their ~3 workplaces inside their community; 60% of all
connections cross communities. The scores are correct; the pattern comes from the
generator's random careers, so scale-fixture community results are for timing only.

## Any person to any person — November 5, 2026

`q_person_path(source_id, target_id)` computes the shortest route between any two people
live on the engine (not deployed; a deployment only serves the sources it was built with).
Checked with `scripts/guarded_knows_count.py --source-id ... --target-id ... --execute`.

- Fix: when several shortest routes tie, it now returns the **strongest** one (highest
  product of tie strengths, the warm-path ranking rule), plus `route_strength`. The
  checker compares that strength with the oracle's best. Example: Elena Marsh → Ruth
  Adeyemi now goes via Marcus Whitfield (0.70) instead of Harold Becker (0.49).
- Stress test: 21 pairs, 1–20 hops, 2/4/5/10-way ties, reverse direction, a small separate
  group, two unreachable cases and self. **All 21 passed** on length and strength.
- Cost: about 40–70 s per call with this script (each call reloads the model), versus
  ~50 ms for precomputed team lookups. Precomputing every pair on the demo data would be
  744,378 rows; at 1M people every pair is not feasible.



## Distance lookup benchmark — lookup over two precomputed sources

Historical benchmark of the previous two-source materialization. The deployed table now contains the OurSeed materialization described below; the two-source benchmark's completeness check intentionally rejects that different source set.

Measured 2026-11-04T10:21:09.925716-05:00 (America/New_York), using direct Snowflake connector SQL against the existing RelationalAI-materialized table `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_DEPLOY.PERSONDISTANCEPROBE`. No model imports, distance recomputation, refresh, sync, session-setting changes, or data writes. Both precomputed sources were checked: five reads for each of seven oracle-selected cases per source, **70/70 passed**. The full **1,720 rows matched the local oracle** before timing and were unchanged afterward. Unreachable means no row for an existing oracle person, with source completeness verified first.

```bash
env -u DEBUG .venv/bin/python scripts/check_graphs.py --benchmark-distance-lookups
```

```sql
SELECT HOPS FROM ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_DEPLOY.PERSONDISTANCEPROBE WHERE SOURCE_ID = %s AND TARGET_ID = %s;
```

All timings below are milliseconds. **Snowflake** is query-history `TOTAL_ELAPSED_TIME` (server elapsed time, including compilation/queue/execution). **Python** is `perf_counter` around connector execute + fetch, including client/network overhead. Neither includes connection setup, oracle preparation, preflight, or later timing-metadata collection. Each median uses only runs 2–5 of that case.

| Source | Target | Oracle case | Snowflake first | Snowflake median 2–5 | Python first | Python median 2–5 |
|---|---|---|---:|---:|---:|---:|
| P10034 | P31852 | 1 hops | 62.0 | 35.0 | 151.4 | 130.9 |
| P10034 | P37083 | 2 hops | 45.0 | 41.0 | 140.5 | 148.7 |
| P10034 | P10451 | 3 hops | 35.0 | 38.0 | 129.2 | 137.8 |
| P10034 | P19694 | 4 hops | 46.0 | 44.0 | 139.8 | 160.6 |
| P10034 | P11562 | 5 hops | 34.0 | 41.0 | 130.5 | 136.5 |
| P10034 | P10034 | self | 31.0 | 36.0 | 126.1 | 131.3 |
| P10034 | P10001 | unreachable | 38.0 | 43.0 | 134.6 | 135.5 |
| P10451 | P38242 | 1 hops | 26.0 | 36.0 | 118.7 | 130.8 |
| P10451 | P19318 | 2 hops | 38.0 | 36.5 | 130.3 | 149.0 |
| P10451 | P10034 | 3 hops | 37.0 | 36.0 | 154.8 | 148.5 |
| P10451 | P11562 | 4 hops | 36.0 | 47.5 | 131.1 | 200.8 |
| P10451 | P10144 | 5 hops | 53.0 | 38.5 | 143.7 | 141.1 |
| P10451 | P10451 | self | 52.0 | 37.0 | 147.7 | 138.1 |
| P10451 | P10001 | unreachable | 35.0 | 40.0 | 239.2 | 135.8 |

Excluded setup/collection costs: local imports/configuration/oracle preparation **727.7 ms**; connection/authentication **2528.9 ms**; read-only preflight **1268.9 ms**; query-history collection plus final table comparison **682.1 ms**. Role `RAI_USER`, warehouse `RAI_XS` (X-Small), benchmark session `1511703988946354`.

Cache context: `USE_CACHED_RESULT=true` (default true, unchanged). Warehouse state at preflight: `STARTED`, auto-suspend 300 seconds, auto-resume true. No caches were disabled or flushed. The preflight read all materialized rows; additionally, an earlier 70-lookup batch passed correctness checks but failed timing collection because this Information Schema history interface lacks `PERCENTAGE_SCANNED_FROM_CACHE`. The table above is the subsequent complete measured batch. **First run does not mean cold**; these observations do not establish whether a particular lookup reused the result cache or warehouse data cache. They measure lookup over two precomputed sources, not graph-computation latency or arbitrary-source shortest-path performance.

## OurSeed distance materialization — November 4, 2026

The existing `copied-distance-probe` now selects sources from `OurSeed`, preserving the existing source-relation name and using `knows_graph.distance(from_=probe_sources)`. It does not request all-pairs distances. The recursive minimum-distance compatibility fix, normalized role/ownership date views, threshold 0.0, and existing three experiment schemas are preserved. Deployment uses `RAI_USER` on `RAI_XS`; original source tables were not modified.

- Verified seed membership against both the independent CSV oracle and the deployed `OurSeed` view: **5**, IDs `P19079`, `P25319`, `P26028`, `P26070`, `P95007`. Membership is derived from rules, not hard-coded in the probe.
- **4,300 reachable distance rows**, 860 per source, including 5 self rows (4,295 non-self rows).
- **PASS:** every `(source_id, target_id, hops)` matches independent per-seed BFS. Validation rejects missing/extra rows, duplicate pairs, non-seed sources, incorrect distances, and mismatched seed membership.
- One manual refresh, query ID `01c83040-010c-d050-0005-5ee313510d6e`. Snowflake task execution: **454.641 seconds**; scheduled-to-completion: **455.400 seconds**. Python observed submission/polling duration: **465.729 seconds**, excluding deployment and post-refresh validation.
- Validation before live execution: 38 offline tests passed, including minimum-distance convergence for all current seeds and both date-normalization tests. Offline compilation produced 26 SQL-only blocks and confirmed that the probe-source population joins `Person` to `OurSeed`.

```bash
env -u DEBUG .venv/bin/python scripts/check_graphs.py --run-copied-distance-probe --execute --refresh
```

This command deploys and submits a refresh; it is not a read-only check. Automatic/recurring refresh remains disabled.


## Connected 10K-person local fixture

Generated in `data/scale_connected_10k` with deterministic seed 42. This is a separate opt-in mode in the existing generator; the demo CSVs, golden files, and `data/scale_10k` sparse fixture remain byte-for-byte unchanged. No Snowflake or RAI work was performed.

```bash
env -u DEBUG .venv/bin/python data/generate.py --scale-connected --people 10000 --workplace-size 16 --seed 42 --out data/scale_connected_10k
env -u DEBUG .venv/bin/python data/generate.py --scale-check --out data/scale_connected_10k
```

Generation refuses an existing destination; use a fresh output directory to regenerate. Validation reads the generated CSVs through the independent `data/oracle.py` K1/K2/K3 rules and single-source BFS, with threshold 0.0.

| Measurement | Oracle-validated result |
|---|---:|
| People | 10,000 |
| Roles | 30,169 |
| People with 2 / 3 / 4 roles | 3,248 / 3,335 / 3,417 |
| Unique undirected person connections | 131,904 |
| Team seeds | 5, preserving existing IDs and names |
| Company workplaces | 4227 |
| Participants per workplace | 1–16; only 3 private one-person workplaces |
| People with overlapping roles at distinct organizations (at least 365 days) | 10,000 |
| Largest connected component | 9,999 people (99.99%) |
| Other component | 1 intentionally isolated person |
| Degree mean / median | 26.3808 / 26 |
| Degree p90 / p95 / p99 / maximum | 42 / 45 / 53 / 57 |
| CSV bytes / total fixture bytes | 4,737,075 / 4,743,932 |

Percentiles use nearest rank. Degree distribution (people per degree band):

| Degree | People |
|---|---:|
| 0 | 1 |
| 1–9 | 512 |
| 10–19 | 2,557 |
| 20–29 | 3,187 |
| 30–39 | 2,437 |
| 40–49 | 1,134 |
| 50–59 | 172 |

The five team seeds are `P19079`, `P25319`, `P26028`, `P26070`, and `P95007`. Their current Northwind team-role types are preserved. Historical company roles use overlapping career windows; at least one mover links every home workplace to the next, and additional bounded workplace groups add varied career connections. The 16-person cap includes incoming movers, so a single workplace cannot become a giant clique. With the cap and 2–4 roles held fixed, direct degree is bounded by 60 and potential connections grow linearly with people rather than quadratically.

The six-person planted chain attaches to the main network only at `SCALE_P000000000`; nodes 1–5 receive no outside links. Bulk career links therefore cannot shorten its paths. `SCALE_P000000006` has two private roles and remains truly unreachable, not missing from the data. A fully connected graph cannot also contain an unreachable pair, hence the intentional one-person exception.

All **14 cases** passed shortest-distance and route-edge checks after all links were added:

| Expected distance | Target from non-seed SCALE_P000000000 | Target from team seed P19079 |
|---|---|---|
| 1 | SCALE_P000000001 | SCALE_P000000000 |
| 2 | SCALE_P000000002 | SCALE_P000000001 |
| 3 | SCALE_P000000003 | SCALE_P000000002 |
| 4 | SCALE_P000000004 | SCALE_P000000003 |
| 5 | SCALE_P000000005 | SCALE_P000000004 |
| Self: 0 | SCALE_P000000000 | P19079 |
| Unreachable | SCALE_P000000006 | SCALE_P000000006 |

Exact routes, seed IDs, CSV sizes/counts/checksums and generation parameters are in `data/scale_connected_10k/MANIFEST.json`; `--scale-check` also reports the complete degree histogram and workplace/role distributions. Validation: **11 tests passed**, including protected-path separation, explicit shortcut rejection even with updated manifest hashes/counts, primary-key uniqueness, unchanged protected fixtures, and deterministic generation. A second full 10K generation matched every output byte.



### Baseline people communities and internal connectors

Local extension requirements: when community analysis is requested, expose the Louvain level
limit and seed, compare partition quality and seed stability, and locate `OurSeed` and
decision-makers of Tier A targets (`DecisionMaker`). Validate every internal betweenness score.
Offline runs must use saved RAI rows and explicitly labeled NetworkX references; missing RAI
comparisons remain pending. Keep distance/date fixes, deployments, fixtures and scale evidence intact.

`--communities` now runs locally by default, using [saved RAI rows and the comparison report](artifacts/people_communities.json). The verified baseline has **2,506 people / 2,525 unweighted Knows connections** at threshold 0.0. RAI seed 42 with `max_levels=1` produced **1,214 communities**, **603 singletons** (all isolates), maximum size 16 and modularity **0.783163**. Every saved internal score passes independent NetworkX Brandes validation.

```bash
# Offline replay of all six completed RAI settings and local NetworkX references.
env -u DEBUG .venv/bin/python scripts/guarded_knows_count.py --communities \
  --louvain-max-levels 1 5 --louvain-seeds 42 7 99 \
  --community-results artifacts/people_communities_live.json
```

`--community-output` must name a new file. Each completed live query is saved before numerical validation, allowing later local analysis via `--community-results`. Offline mode imports no live model/client. The live path retains existing source, engine and mutation guards; it does not resume the engine, deploy or refresh anything. The helper in `graphs.py` remains opt-in and does not alter distance definitions.

The installed RAI SDK 1.27.1 supports `max_levels` and `randomization_seed`. Other Louvain options remain at its defaults: `max_sweeps=20`, `level_tolerance=0.01`, `sweep_tolerance=0.0001`. A level cap does not prove convergence. NetworkX 3.7 uses `max_level`, `seed`, `weight=None`, `resolution=1`, `threshold=1e-7`; its partitions need not match RAI. Local five-level references give **966 communities**, modularity **0.935806–0.936901**, largest size **65–70**, and the same 603 singletons. The live comparison is now complete: five new RAI runs, with cap 1 / seed 42 reused. All six partitions and 15,036 internal scores passed validation; results and query IDs are in [the live artifact](artifacts/people_communities_live.json).

**No setting is established as the most useful.** On this synthetic dataset, the highest observed modularity is cap 5 / seed 99 (0.936798). Mean pairwise ARI across the three seeds, excluding isolates, is higher at cap 1 (0.914151) than cap 5 (0.886162). Within the three cap-5 runs, seed 7 has the highest mean agreement with its two peers (ARI 0.908910) and the highest exploratory focused-person Jaccard (0.873909). Those are descriptive comparisons, not validation of business usefulness. All five team seeds are co-assigned at cap 5 in 3/3 runs; Larkspur's decision-makers share that community in 2/3. Co-assignment is not a success criterion. No community ground truth, introduction outcomes or real-world influence were evaluated. Internal betweenness validation establishes numerical agreement for each chosen partition, not that the partition represents meaningful social groups.

Betweenness is exact and unnormalized **inside each community**: RAI uses `num_pivots=16000 >= 2506` on the disjoint union of community-induced graphs. NetworkX checks each induced graph with `k=None`, `normalized=False`, `weight=None`, `endpoints=False`. Sampling is disabled and pivot counts below the full node count are rejected. Every score must satisfy `abs(actual - expected) <= max(2e-6 * max(abs(actual), abs(expected)), 1e-5)`. Only independently confirmed mathematical zeros are displayed as zero (36 saved roundoff values); raw scores remain in the artifact. Ranks use three decimal places, then name and ID. All-zero groups have no distinguished connector.

Reports include size distributions, modularity, pairwise adjusted Rand stability (also excluding isolates), and top three internal connectors for communities containing the five `OurSeed` members or **decision-makers of Tier A targets (`DecisionMaker`)**. Scope follows the existing model's 2026-10-01 date and Act 1 scores: current CEO plus majority-owning sponsor board designee, eligible target score at least 70. Display community numbers are specific to each partition. [Completed live comparison, stability and decision-maker mapping](artifacts/rai_initialization_investigation.md#live-community-comparison--2026-11-04). [Preserved original RAI connector report](artifacts/rai_initialization_investigation.md#baseline-rai-people-community-results--2026-11-04).

The separate `copied-community-probe` profile deploys the same baseline algorithms
(one Louvain level, seed 42, 16,000 betweenness pivots) using the existing copied sources
and date-normalization views. It has its own model name, output schema
`ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_COMMUNITY`, and sibling `_META` schema.
The installed SDK 1.27.1 compiles this model with `deployment.outputs.reasoner=logic`
and `compiler.safe_recursion=false`, set only in the runner's configuration. Automatic
routing failed with a mixed-reasoner dependency error; the default recursion setting
also rejected the combined pipeline. No algorithm was replaced.

`env -u DEBUG .venv/bin/python scripts/check_graphs.py --run-community-probe` prints
the deployment settings without connecting. Adding `--execute --refresh` installs
into **fresh** community schemas and requests one manual baseline refresh. The runner
rejects existing targets, non-baseline fixtures and automatic task retries. It verifies
the complete copied source values before deployment and fingerprints original/copied
inputs plus the distance rows, plan, refresh log and task definition before and after.
Fresh community scores and edges must pass the existing independent validator;
saved RAI rows are used only for a partition-agreement comparison.

**Repaired refresh (2026-11-04): succeeded and saved results validated.**
The first attempt failed because the SDK's export helper passed an unquoted
`non-rescaled_betweenness` column name to `PERSIST_FROM_STAGE`. The scoped fix in
`community_export_procedure_sql()` quotes temporary CSV column names and their
subsequent projections using the helper's existing identifier renderer. It changes
only the community export procedure; the stored RAI plan and all model files are
byte-for-byte unchanged. The installed SDK files were not modified.

The new refresh populated `PERSON` and `PERSONCOMMUNITYPROBE` with 2,506 rows each,
and `KNOWS` with 2,525 rows. All fresh edges and all 2,506 internal scores passed
independent validation after being saved and read back from JSON. The partition
matches the previous deployed partial output (ARI 1.0): 1,214 communities,
603 singletons, maximum size 14, modularity 0.778945. It remains different from
the original interactive seed-42 baseline (non-isolated ARI 0.902261); that earlier
difference was not resolved or attributed to a cause by this repair.

The successful task took 245.835 seconds. Source/distance preservation checks passed;
the existing 4,300 distance rows and distance plan, refresh log and task metadata
are unchanged. Automatic scheduling remains off. **63 offline tests passed.**
[Validated refresh evidence](artifacts/people_communities_refresh_fixed.json).
[Preserved failed-attempt evidence](artifacts/people_communities_deployment.json).

The existing-deployment repair entry point is `--repair-community-export`;
without `--execute` it only prints the intended changes. The executed command was:

```bash
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python scripts/check_graphs.py \
  --repair-community-export --execute --refresh
```

It saves to `artifacts/people_communities_refresh_fixed.json` and refuses to overwrite
existing evidence. A further authorized run needs a new `--json` path. The repair
checks the existing helper against SDK 1.27.1 and the saved RAI plan before changing
anything. A direct SDK redeploy can regenerate the original helper; the project
community deployment runner reapplies the fix. Review or remove this compatibility
fix when the upstream helper handles quoted stage/projection identifiers.

### Sparse 10K five-seed deployment

The original `data/scale_10k` has zero team seeds and remains unchanged. The authorized separate `data/scale_sparse_seed_10k` variant replaces five bulk person IDs with the baseline team IDs, in five distinct workplaces, and adds five current Northwind team roles. Its oracle reports 10,000 people, 10,009 roles, 34,987 connections, and 200 reachable distance rows including five self rows. Existing planted paths still pass.

Loaded and value-verified all 17 tables in `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_SPARSE_10K_SRC`; model outputs and metadata are in sibling `PE_DEAL_GRAPH_EXPERIMENT_SPARSE_10K` and `_META` schemas. Provisioning used `RAI_DEFAULT_ROLE`, deployment used `RAI_USER`/`RAI_XS`, with the existing date and distance compiler fixes. One manual refresh succeeded; all 200 rows matched the oracle. Snowflake execution: **225.300 seconds**; scheduled-to-complete: **225.835 seconds**; query ID `01c83065-010c-d1b5-0005-5ee31350b306`. Automatic refresh remains disabled. The connected fixture was subsequently loaded and validated after the baseline community analysis; see the comparison below.

### Sparse versus connected 10K: completed deployment comparison

Both use the existing five-seed RAI distance model, threshold 0.0, and the existing date/distance fixes. All source CSV values were compared with the 17 loaded tables before deployment. Every materialized distance pair and value was compared with independent per-seed BFS, including self rows, missing/extra pairs, and duplicates. Materialized Knows counts also matched the oracle.

| Measurement | Sparse five-seed variant | Connected fixture |
|---|---:|---:|
| People | 10,000 | 10,000 |
| Roles | 10,009 | 30,169 |
| Unique undirected Knows connections | 34,987 | 131,904 |
| Verified OurSeed members | 5 | 5 |
| Reachable distance rows, including self | 200 | 49,995 |
| Self rows | 5 | 5 |
| Snowflake refresh execution seconds | 225.300 | 284.308 |
| Scheduled-to-complete seconds | 225.835 | 285.068 |
| Python observed refresh seconds (includes polling) | 232.245 | 288.591 |
| Full distance correctness | PASS | PASS |
| Manual refreshes executed | 1 | 1 |

These are observed single-run timings on RAI_XS, not controlled cold-cache benchmarks. The source schemas are `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_SPARSE_10K_SRC` and `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_10K_SRC`; each has sibling output (without `_SRC`) and metadata (`_META`) schemas. Provisioning used RAI_DEFAULT_ROLE and deployment RAI_USER, with schema-scoped privileges only. Connected refresh query: `01c8307c-010c-d050-0005-5ee3135244fa`.

The existing baseline's 4,300 materialized distances remained identical by content hash. Original demo and sparse CSVs remain unchanged. All refresh tasks remain suspended with no schedule; no recurring refresh, stream reset/deletion, original-data overwrite, SDK modification, or shared-infrastructure setting change was performed. The only explicit engine action was the separately authorized resume for baseline community analysis.

The existing commands now select only allowlisted fixture targets. Loading refuses existing schemas; deployment refuses nonempty fresh fixture output targets. Do not rerun creation commands against these completed deployments:

```bash
# Fresh targets only; shown for reproducibility, already executed once for each fixture.
env -u DEBUG .venv/bin/python data/load.py --fixture sparse --execute
env -u DEBUG .venv/bin/python scripts/check_graphs.py --fixture sparse --run-copied-distance-probe --execute --refresh
env -u DEBUG .venv/bin/python data/load.py --fixture connected --execute
env -u DEBUG .venv/bin/python scripts/check_graphs.py --fixture connected --run-copied-distance-probe --execute --refresh
```

### Dedicated PE Cortex agent over persisted baseline results

Agent: `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_COMMUNITY.PE_GRAPH_ASSISTANT`.
Display name: **PE Graph Assistant — Synthetic Baseline**. In Snowsight, use role
`RAI_USER`, open **AI & ML → Agents**, select this agent, and enter a question in
its playground. [Snowflake agent UI instructions](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-manage#test-the-agent).

The agent has one custom tool, `PE_GRAPH_LOOKUP`, in the same existing PE schema.
It uses fixed SELECT statements under caller rights, reads the 4,300 persisted
`PERSONDISTANCEPROBE` rows and 2,506 `PERSONCOMMUNITYPROBE` rows, and verifies their
baseline fingerprints before answering. It neither imports a RAI model nor
recomputes, refreshes, or updates a graph. No Cortex Analyst, code execution,
external-access integration, stage, or new schema is needed.

All answers describe **synthetic PE demo data**, model date **2026-10-01**.
The five team people are the only precomputed distance sources. A missing pair
from a covered source to a known person means **UNREACHABLE** in this baseline;
there is no three-hop cutoff. A different source means **SOURCE_NOT_PRECOMPUTED**,
not unreachable. Unknown or ambiguous names and companies outside the persisted Tier A
scope have distinct statuses. Self-distance is zero.

The tool also returns shortest routes from the five team sources by following
persisted `KNOWS` edges whose stored source distances increase by one at each
step. It does not rerun the distance or community algorithms. Each returned route
includes shared names, IDs, current roles, edge strengths and the persisted
strongest evidence for each link. Route scores multiply the edge strengths;
shorter routes rank first, then higher product scores, then route IDs. These are
model heuristics, not probabilities of successful introductions. It counts all shortest routes, displays
one best route per equally closest source for team-wide questions, with complete
distance summaries for all sources; source-specific questions
can request up to 10 routes. It explicitly reports truncation. For two-hop questions, the intermediary list is complete even when
the displayed routes are limited.

Live checks verified these unique two-hop routes to Bayside CEO Daniel Reyes:

- Marcus Whitfield → Elena Marsh → Daniel Reyes: product score **0.600**.
- Dana Okafor → Walter Kim → Daniel Reyes: product score **0.286901**.

Elena’s persisted role history identifies her as Bayside CFO from **2025-06-01**,
current at the model date. Marcus’s link to Elena is evidenced by tenure overlap
at a former Northwind portfolio company from **2015-03-01 to 2019-06-30**.
Role context does not expand the model’s DecisionMaker definition. Target scoring
evidence is read from persisted `SCORECOMPONENT` rows.

Validation establishes agreement with the independent CSV oracle for tested
cases and reuse of the original product-of-strengths scoring rule. It does not
establish exact parity with every output of the original demo.

Community answers now identify the deployed **Louvain max_levels=5, seed=7**
partition, updated on November 5 after a successful refresh and full score
validation. The previous one-level/seed-42 deployment is historical. Neither
setting is presented as an established best partition; see the current demo
configuration section below for the fresh membership and connector results.

Validation: 30 offline agent tests passed; live route results matched the
independent CSV oracle, including self, unreachable and unsupported-source
cases. Three agent answers passed factual review. Evidence is in
`artifacts/pe_cortex_agent.json` under `path_validation`. Existing graph and target
outputs were preserved. Start a new agent Preview conversation to test the
updated tool without the earlier conversation's obsolete limitations.


The graph-only deployment profiles deliberately omitted the eligibility, scoring,
and decision-maker builders. Their declared `DECISIONMAKER` and `ELIGIBLETARGET`
tables were therefore empty, and company `TIER` values were unpopulated. The
`copied-target-rules` profile now enables the existing Act-1 and decision-maker
builders separately, without changing their function bodies or importing graphs.
Its authoritative persisted outputs are in
`ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_TARGETS`: `DECISIONMAKER`,
`ELIGIBLETARGET`, `COMPANY`, and `SCORECOMPONENT`. It reuses the same copied source
tables and existing date-normalization views. The old empty graph-profile target
tables remain unused so the working graph plans need not be changed.

One target refresh succeeded in **266.645 seconds**. Saved output rows passed
independent CSV-oracle validation: **248 eligible targets, 256 decision-makers,
826 score components, six Tier A targets, and nine Tier A mappings**. All eligible
scores, tiers, and pillar totals were compared. The raw oracle helper has one
additional non-majority-owner mapping (`C9820`, `P38163`) outside Tier A; the
existing model excludes it. That scope difference is recorded explicitly, and
the nine Tier A mappings match the raw oracle without adjustments.
[Target deployment and validation evidence](artifacts/target_rules_deployment.json).

The lookup procedure now reads `DECISIONMAKER` joined to `ELIGIBLETARGET` and
`COMPANY.TIER='A'` on each request. It embeds no target IDs or mapping snapshot,
and its fingerprint guard includes the target outputs. Eligibility and graph
algorithms are not recomputed during lookups. `DecisionMaker.hops` is not populated
by this target-only profile; hop answers continue to use the validated distance
table. Community membership uses raw persisted RAI labels, not report ordinals.

Connector scores are exact, unnormalized, unweighted, within-community betweenness
(16,000 RAI pivots, previously validated for every person at relative tolerance
`2e-6`, absolute tolerance `1e-5`). Scores display and rank to three decimals;
raw values are retained. Ties and omitted tied members are disclosed, and all-zero
communities do not identify a unique top connector. Scores do not establish
business influence or introduction success.

The implementation is [scripts/pe_cortex_agent.py](scripts/pe_cortex_agent.py);
deployment and question evidence are in [artifacts/pe_cortex_agent.json](artifacts/pe_cortex_agent.json).
The original nine representative live question cases were checked, including five retests after
correcting explanation wording; earlier responses are retained in the evidence.
The final answers cover reachable targets, unreachable targets, unsupported source
people, memberships, tied connectors, a singleton, an unknown person, self-distance,
and refusal to recompute. All returned values checked in the final tool traces
match the saved baseline. **21 lookup/target-rule tests and 63 existing regression tests passed.**
The 49 pre-existing agent inventory records and all checked source, distance,
community, task, plan, and refresh-log fingerprints remained unchanged. Model edits
only add the target builder selection and recognize its copied-source profile;
existing business-rule and graph-function bodies are unchanged.
After switching to persisted target outputs, **six target question cases passed
review**: the full Tier A catalog/provenance, Larkspur hops, Saltmarsh unreachable
decision-makers, a source without precomputed distances, team/target memberships,
and Larkspur's internal connectors. A direct lookup also rejects a known company
outside Tier A without calling it unreachable. One source-coverage explanation was
retested to avoid suggesting reverse-distance symmetry is invalid in an undirected
graph. Earlier answers and the original snapshot-backed configuration are retained
in the agent evidence. The new deployed procedure was read back and contains no
embedded target IDs or mapping snapshot.
Creation refuses existing objects. The following commands inspect or query the
existing agent; they do not redeploy a graph:

```bash
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python scripts/pe_cortex_agent.py prepare
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python scripts/pe_cortex_agent.py status
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python scripts/pe_cortex_agent.py chat \
  "Who are the top three internal connectors in Dana Okafor's community?"
```

The target deployment runner reuses `scripts/check_rules.py`. This command previews
its configuration and expected oracle counts without connecting:

```bash
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python scripts/check_rules.py --deploy-target-rules
```

Creation with `--execute --refresh` has already been completed and refuses existing
schemas. `--resume-target-deployment` is limited to a recorded failed deployment
with no executable plan or populated target tables. Both installation-guard failures
are retained in the evidence; neither ran a refresh. The target task is manual and
suspended, with automatic retries disabled. The successful refresh query was
`01c83175-010c-d509-0005-5ee313540d6a`. No distance or community refresh was run.

### Connected 100K distance scale test

One manual refresh on `RAI_XS` completed successfully. All **499,995** reachable
seed/person distances matched independent BFS, including five self rows. The five
team seeds are unchanged. Original demo and 10K fixture files were preserved.

| Connected fixture | People | Roles | Knows pairs | Distance rows | Refresh execution | Correctness |
|---|---:|---:|---:|---:|---:|---|
| 10K, earlier run | 10,000 | 30,169 | 131,904 | 49,995 | 284.308 s | PASS |
| 100K | 100,000 | 300,109 | 1,297,797 | 499,995 | 259.666 s | PASS |

The generated SQL plans match after substituting schema names. These are single
runs, not evidence that larger graphs are faster or that costs scale linearly.
Generation, loading, installation and result validation are excluded from refresh
execution time. The 100K distance block took 32.417 s; the largest input/ontology
block took 173.086 s. Block times can overlap and must not be summed as independent
components. Query ID: `01c8322f-010c-d50c-0005-5ee3135dc2f2`.

Fixture: `data/scale_connected_100k` (seed 42, workplace cap 16, 2–4 roles per
person). Local validation passed all 14 planted path cases; the largest component
has 99,999 people and one person is deliberately isolated. Maximum degree is 57.
This tests a connected graph with bounded workplace sizes, not a giant employer
clique or real client data. Outputs are in
`ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_100K`; sources and
metadata use its `_SRC` and `_META` schemas. Refresh remains manual.

```bash
# Fresh targets only: these commands were already executed for the 100K run.
env -u DEBUG .venv/bin/python data/generate.py --scale-connected --people 100000 --workplace-size 16 --seed 42 --out data/scale_connected_100k
env -u DEBUG .venv/bin/python data/generate.py --scale-check --out data/scale_connected_100k
env -u DEBUG .venv/bin/python data/load.py --fixture connected100k --execute
env -u DEBUG .venv/bin/python scripts/check_graphs.py --fixture connected100k --run-copied-distance-probe --execute --refresh
```

### Connected 10K communities and internal betweenness

One manual RAI Logic refresh succeeded in **247.439 seconds** on the existing
`alaa_pe_deal_graph_experiment` reasoner, using `RAI_XS` for Snowflake work.
Reasoner resume time is excluded. Louvain remained **max_levels=1, seed=42**;
internal betweenness used **16,000 pivots for 10,000 people** and was validated
against exact, unweighted, unnormalized NetworkX scores within each returned
community. No alternate algorithms or partition settings were substituted.

| People | Knows pairs | Communities | Largest | Singletons | Modularity | Score validation |
|---:|---:|---:|---:|---:|---:|---|
| 10,000 | 131,904 | 1,173 | 106 | 1 | 0.339335 | All 10,000 passed |

Maximum absolute score difference was approximately **1.20e-10**. The graph's
complete edge set matched the independent fixture oracle. These are descriptive
results for one synthetic partition, not evidence of community business meaning
or a preferred Louvain setting. This test does not change the agent's baseline
partition. Query ID: `01c8323b-010c-d50c-0005-5ee3135dce32`.

Outputs: `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_10K_COMMUNITY`
and its `_META` schema, reusing the existing connected-10K source tables. Both
new scale tasks remain suspended without schedules. Fingerprints confirm the
existing baseline sources, baseline distance/community outputs and previous
10K distance results stayed unchanged.

Evidence for both new tests is in
[people_communities_connected_10k.json](artifacts/people_communities_connected_10k.json),
including the 100K fixture validation, distance counts, SQL-plan comparison and
refresh log. The targeted checks passed: 13 scale tests and 59 graph/deployment
tests. No 1M-person run has been performed.

```bash
# Already executed once; this runner requires fresh output schemas.
env -u DEBUG .venv/bin/python scripts/check_graphs.py --fixture connected --run-community-probe --execute --refresh --json artifacts/people_communities_connected_10k.json
```

### Connected 100K persisted-distance lookup benchmark

**175/175 lookups passed**: all five team sources, each tested at 1–5 hops, self
and unreachable, with five runs per case. Before timing, all 499,995 stored
distances matched the independent BFS oracle. Table contents and the refresh
log were unchanged afterward; no graph refresh or model import occurred.

Times below are milliseconds. Each median pools runs 2–5 across five sources
(20 measurements per row). Per-case first runs and medians are saved in the
evidence, with every query ID.

| Case | Snowflake median | Python execute + fetch median |
|---|---:|---:|
| 1 hop | 44.0 | 146.8 |
| 2 hops | 41.5 | 145.9 |
| 3 hops | 39.5 | 137.5 |
| 4 hops | 43.5 | 144.6 |
| 5 hops | 50.0 | 147.9 |
| Self | 48.5 | 150.5 |
| Unreachable | 42.5 | 150.7 |

Across 140 repeated queries, the medians were **44.0 ms server** and **144.8 ms
Python**. Across the 35 first-per-case queries, medians were **82.0 ms server**
and **169.5 ms Python**. Slowest repeated query: **771 ms server / 878.4 ms
Python**; this is a finite sample, not a latency guarantee.

`RAI_XS` was started at measurement, X-Small, with `USE_CACHED_RESULT=true`.
The preflight reads warmed the table, so first-per-case results are **not cold
measurements**. Server time is `TOTAL_ELAPSED_TIME`; Python time includes
execute, fetch and network overhead. Authentication/connection (2,842.7 ms),
local oracle preparation (21,089.1 ms), and preflight (5,106.5 ms) are excluded.
These figures measure reads of precomputed five-source distances, not graph
calculation, concurrent-user load, or Cortex-agent response time.

Evidence is stored under `connected_100k_distance.lookup_benchmark` in
`artifacts/people_communities_connected_10k.json`. Four targeted benchmark/oracle
tests passed. Reproduce with:

```bash
env -u DEBUG .venv/bin/python scripts/check_graphs.py --fixture connected100k --benchmark-distance-lookups
```

### Connected 1M distance and lookup test

**Completed and validated:** 1,000,000 people, 3,000,696 roles, 422,153
organizations, and 12,983,446 Knows connections. All **4,999,995** reachable
distances from the five team sources matched independent BFS, including five
self rows. The graph has 999,999 people in its main component and one deliberate
isolate. All 14 planted path checks passed; workplace cap 16, maximum degree 57.

| Connected fixture | People | Knows pairs | Distance rows | Refresh execution |
|---|---:|---:|---:|---:|
| 10K | 10,000 | 131,904 | 49,995 | 284.308 s |
| 100K | 100,000 | 1,297,797 | 499,995 | 259.666 s |
| 1M | 1,000,000 | 12,983,446 | 4,999,995 | **483.175 s** |

One manual refresh per size on unchanged `RAI_XS` X-Small. The 1M SQL plan
matches 100K after substituting schema names. The distance block took 111.134 s;
tenure overlap took 49.192 s; the largest input/ontology block took 231.815 s.
Block durations can overlap and should not be summed as independent costs.
Query ID: `01c83276-010c-d050-0005-5ee3135fd952`. These single runs do not establish
a scaling law. Generation, load, deployment and local validation are excluded
from refresh execution time.

**175/175 lookups passed:** five sources × seven cases (1–5 hops, self,
unreachable) × five repetitions. The complete persisted distance table and
refresh log were unchanged after measurement.

| 1M lookup measure | Snowflake TOTAL_ELAPSED_TIME | Python execute + fetch |
|---|---:|---:|
| Median, first per case (35 runs) | 114 ms | 227.8 ms |
| Median, repeated runs 2–5 (140 runs) | **49 ms** | **151.3 ms** |
| p95, repeated runs | 90 ms | 235.1 ms |
| Maximum, repeated runs | 148 ms | 733.7 ms |

The earlier 100K repeated medians were 44 ms / 144.8 ms. Result caching was
enabled (`USE_CACHED_RESULT=true`) and preflight read all rows, warming the table;
first runs are not cold measurements. Authentication/connection (2,666.2 ms),
local oracle preparation (112,569.8 ms), and preflight (12,317.9 ms) are excluded
from per-lookup timings. These are stored-distance lookups, not graph recomputation,
concurrent-user load, or Cortex-agent response times.

Sources, outputs and metadata live in the separate `CONNECTED_1M_SRC`,
`CONNECTED_1M`, and `CONNECTED_1M_META` experiment schemas within
`ALAA_RELAPP_PERSISTENCE` (each prefixed `PE_DEAL_GRAPH_EXPERIMENT_`). The refresh
task is suspended with no schedule. Existing demo, community and previous scale
output fingerprints matched before/after. No warehouse resize, installed SDK
change, or saved configuration change was made.

For 1M setup, the loader uses non-overwriting `write_pandas` bulk uploads into
fresh tables and verifies all loaded values. Earlier smaller loads used INSERT
batches. The local oracle skips descriptive evidence at 1M to reduce memory,
while retaining identical connection rules and strengths; a baseline equivalence
test passed. All **74** targeted offline tests passed.

Full query IDs, per-case lookup timings, refresh logs, load receipts, fixture
checks and preservation evidence: [scale_1m.json](artifacts/scale_1m.json).
That distance-only experiment did not test million-person community detection/betweenness,
all-pairs distances, or giant workplace cliques. The later 1M community experiment
is documented below; the latter two limitations remain.

```bash
# Generation/load/deployment already executed once; these require fresh targets.
env -u DEBUG .venv/bin/python data/generate.py --scale-connected --people 1000000 --workplace-size 16 --seed 42 --out data/scale_connected_1m
env -u DEBUG .venv/bin/python data/generate.py --scale-check --out data/scale_connected_1m
env -u DEBUG .venv/bin/python data/load.py --fixture connected1m --execute
env -u DEBUG .venv/bin/python scripts/check_graphs.py --fixture connected1m --run-copied-distance-probe --execute --refresh
# Read-only benchmark can be repeated independently.
env -u DEBUG .venv/bin/python scripts/check_graphs.py --fixture connected1m --benchmark-distance-lookups
```


## Connected 100K community deployment — November 5, 2026

The isolated Logic deployment completed one manual refresh in **451.562 seconds
(7m 31.6s)** on the existing `alaa_pe_deal_graph_experiment` reasoner and `RAI_XS`.
Engine startup, installation and local validation are outside this refresh time.

- 100,000 people and all 1,297,797 undirected Knows edges matched the source oracle.
- Louvain retained the previous settings: one level, randomization seed 42.
  It produced 13,784 communities, largest size 43, two singleton communities,
  and modularity 0.321593540393195. The graph has one isolated person; a singleton
  community does not necessarily mean an isolated person.
- Within-community betweenness used **100,000 pivots**, covering every person
  (the SDK caps pivots at the graph's node count). All 100,000 scores matched exact,
  unnormalized NetworkX Brandes scores on the RAI partition's induced subgraphs.
  Maximum absolute error: 1.3002932064409833e-11; tolerance: relative 2e-6,
  absolute 1e-5. This validates the scores conditional on the partition, not the
  business meaning or optimality of that partition.
- Sources reuse `PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_100K_SRC`; outputs and metadata
  occupy `PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_100K_COMMUNITY` and its `_META` schema
  in `ALAA_RELAPP_PERSISTENCE`. Original inputs and existing baseline, sparse 10K,
  connected 10K, 100K and 1M deployment fingerprints matched before/after.
- The new task is suspended without a schedule. No warehouse resize, SDK upgrade,
  baseline agent change, or baseline community-setting change was made.
- Runtime reported `2026.11.2-1c01647`; runtime versions and cache/startup conditions
  were not controlled across sizes. Each timing below is one refresh, not a
  repeatable scaling law. Synthetic workplaces are capped at 16 participants,
  with 2–4 roles per person. Giant-employer cliques and real client data are untested.

### Scale results for review

| Calculation | People | Connections | Louvain levels / seed | Largest community | Refresh seconds | Validation | Main limit |
|---|---:|---:|---|---:|---:|---|---|
| Five-seed distances | 10,000 | 131,904 | — | — | 284.308 | All 49,995 distances matched oracle | Fixed five sources |
| Five-seed distances | 100,000 | 1,297,797 | — | — | 259.666 | All 499,995 distances matched oracle | Fixed five sources |
| Five-seed distances | 1,000,000 | 12,983,446 | — | — | 483.175 | All 4,999,995 distances matched oracle | Fixed five sources |
| Louvain + exact internal betweenness | 10,000 | 131,904 | 1 / 42 | 106 | 247.439 | All 10,000 scores matched oracle | Conditional on detected partition |
| Louvain + exact internal betweenness | 100,000 | 1,297,797 | 1 / 42 | 43 | 451.562 | All 100,000 scores matched oracle | Conditional on detected partition |
| Louvain + exact internal betweenness | 1,000,000 | 12,983,446 | 1 / 42 | 38 | 1,738.729 | All 1,000,000 scores matched oracle | Conditional on detected partition |
| Demo Louvain + exact internal betweenness | 2,506 | 2,525 | 5 / 7 | 66 | 293.492 | All 2,506 scores matched oracle | Different settings; not a scale comparison |

Distance deployments compile to SQL; community deployments use Logic. Their
refresh timings cover their respective full deployed pipelines, not isolated
algorithm execution. **The later 1M community run passed at one level/seed 42; five-level communities remain untested at 1M.**
These results do not establish global betweenness performance, real-world
introduction quality, Cortex latency, or concurrent-user capacity.

Evidence: [people_communities_connected_100k.json](artifacts/people_communities_connected_100k.json).
Refresh query ID: `01c8359b-010c-d809-0005-5ee31372ea7a`.
74 offline tests passed; the final graph-check suite also passed after adding an
actual SDK definition check with 100,000 pivots (60 graph tests).

```bash
# Already executed once. This command requires fresh output schemas and evidence.
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python scripts/check_graphs.py --fixture connected100k --run-community-probe --execute --refresh --json artifacts/people_communities_connected_100k.json
```


## Current demo community configuration — November 5, 2026

The baseline Cortex agent now serves the freshly deployed **Louvain max_levels=5,
seed=7** partition. This is the requested demo configuration, not a proven best
setting. The earlier one-level baseline sections above describe historical runs;
the 10K/100K scale tests remain one-level/seed-42 and are labeled in the table.

One baseline refresh succeeded in **293.492 seconds**, producing 967 communities
(largest 66; 603 singletons; modularity 0.9373465346534654). All 2,506 internal
betweenness scores matched the independent oracle. The fresh Bayside CEO community
has **58 members**, including all five team seeds; it is raw community ID 23 in
this deployment. This differs from the earlier experimental 53-person community:
matching settings do not guarantee an identical partition across runs/runtime versions.

Its leading internal scores are Dana Okafor 621.710, Priya Raman 602.362 and Tom
Harlowe 439.762. These are conditional graph scores, not proof of influence or
introduction success. The live agent returned the correct configuration, membership
count and scores. Its Bayside warm-path response still covered Marcus and Dana at
two hops and the other three seeds at three hops. Agent responses remained more
verbose than the requested 140-word default; numerical/content validation passed.

The original source data, distances, targets and previous scale outputs were
preserved. The community `PERSON` table also changed because it contains derived
community labels and betweenness columns; every source ID and name was checked
against the original copies, and those derived columns matched `PERSONCOMMUNITYPROBE`.
The agent's lookup fingerprints and metadata were updated after validation.

Evidence: [baseline five-level refresh](artifacts/people_communities_baseline_5_7.json)
and [agent validation](artifacts/pe_cortex_agent.json).

### Bounded community stress-test policy

The runner sets a 25-minute Logic query timeout and a 30-minute task timeout;
it monitors through 35 minutes to record the server outcome. No automatic retry,
engine resize, or switch to sampled pivots is permitted. On failure it saves the
SDK doctor report next to that run's evidence as `.debug.zip`, including plan,
trace, refresh log and available transaction progress. Open it with
`env -u DEBUG .venv/bin/rai debugger --host 127.0.0.1 --report <report.zip>`.
Capture was verified against a real baseline refresh: one plan row, a nonempty
trace, refresh log and transaction progress were collected successfully.

The existing polling deadline alone did not cancel a server task. The new
server-side limit uses Snowflake's [USER_TASK_TIMEOUT_MS](https://docs.snowflake.com/en/sql-reference/parameters#user-task-timeout-ms)
and the SDK's Logic query timeout; actual deployed values were verified.
The 1M comparison retains **one level/seed 42**, matching earlier scale runs;
it does not establish million-person performance for the five-level demo setting.


## Connected 1M community result — November 5, 2026

**Succeeded and independently validated.** One isolated manual Logic refresh
completed in **1,738.729 seconds (28m 58.7s)**, within the configured 30-minute
task limit. Query: `01c835c4-010c-d809-0005-5ee31374940e`. Settings: **Louvain
max_levels=1 / seed=42**, exact within-community betweenness using **1,000,000
pivots**. This retains the settings of the 10K/100K scale tests, not the demo
agent's separate five-level/seed-7 configuration.

| Check | Result |
|---|---:|
| People, complete unique IDs/names validated | 1,000,000 |
| Connections, full oracle edge-set match | 12,983,446 |
| Communities | 139,242 |
| Largest community | 38 |
| Singleton communities / isolated people | 6 / 1 |
| Modularity | 0.32028637010994243 |
| Internal betweenness scores independently validated | 1,000,000 |
| Maximum absolute score error | 8.526512829121202e-12 |

The oracle uses exact NetworkX Brandes on each RAI community-induced subgraph,
with unnormalized scores, no weights and endpoints excluded. Tolerance remains
relative 2e-6 / absolute 1e-5. Numerical agreement validates the scores given
the partition, not its meaning or usefulness. The largest community was small,
but the full refresh still took nearly 29 minutes. The measurement includes
input loading, rules, graph computation and output export; it does not identify
an isolated algorithm bottleneck.

Resource telemetry was filtered to the exact UTC task interval
`2026-11-05T15:00:25.218Z`–`15:29:23.947Z`: 174 memory samples peaked at **59.56%**
(mean 40.69%); 173 CPU samples peaked at **2.49%** (mean 0.74%). The metrics view
stores UTC `TIMESTAMP_NTZ`. Initial session-timezone-relative filters included
other activity and are superseded by these explicit UTC filters. These are sampled
reasoner metrics, not proof of the workload's bottleneck or absence of brief peaks.

The existing baseline agent/community, original sources, targets and all prior
scale/distance output fingerprints matched before/after. Outputs are isolated in
`ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_1M_COMMUNITY` and its
`_META` schema, reusing the previously validated `CONNECTED_1M_SRC` sources.
The new task is suspended without a schedule. No retry, reset, engine/warehouse
resize or algorithm substitution occurred. No failure dump was needed; the
capture path had already been tested against a real running baseline refresh.

Full evidence (large, includes every person and edge):
[people_communities_connected_1m.json](artifacts/people_communities_connected_1m.json).
The scale table above contains the consolidated results. All **105 offline tests**
passed, and the two live demo-agent checks passed factual review (verbosity remains
above the requested default). No real-client data, giant-employer cliques, global
betweenness, 1M five-level communities or concurrent-user performance was tested.


## 1M refresh timing breakdown — November 5, 2026

Read-only query history and native transaction timestamps explain the existing
**1,738.729-second** community refresh. No refresh or deployment was rerun.

| Phase | Wall time | Share |
|---|---:|---:|
| Input loading/readiness and startup (combined) | 121.308 s | 7.0% |
| Logic transaction: rules and graph computation | 1,177.154 s | 67.7% |
| Exporting results | 430.427 s | 24.8% |
| Polling transition and finalization | 9.840 s | 0.6% |

Percentages are rounded. The Logic transaction includes more than Louvain and
betweenness; these measurements do not isolate either algorithm's complete cost.
Progress records show internal shortest-distance evaluation (268.644 s), shortest-path
counts (149.230 s), and betweenness contributions (201.738 s). These are individual
stage durations, not an additive breakdown of the whole transaction.

The SDK exported **72 relations in nine batches of eight parallel calls**. The
430.427 seconds is the export window, not the sum of overlapping calls.
`PERSONCOMMUNITYPROBE` took **22.195 seconds** within that window. Intermediate
neighbor and weighted-edge exports took **97.013** and **95.754 seconds** respectively.
This identifies materialization overhead worth investigating; it does not prove
those outputs can be removed safely or predict the time saved.

The root SQL statement reports 1,738.026 seconds; task completion followed 0.703
seconds later. Its reported provisioning/repair/overload queue waits, transaction
blocking and query retry time were all zero. That does not exclude waits inside
the Logic engine. Evidence, query IDs and export timings are in
`people_communities_connected_1m.json`, under `refresh_timing_analysis`.

**Next experiment:** inspect which intermediate outputs are required, then test a
reduced export selection on the existing 100K fixture with identical algorithms,
levels, seed, exactness and compute. Validate the results before comparing refresh
phases. Do not change the working demo or jump to 10M yet. A five-level 100K test
and a denser-employer fixture remain separate experiments; neither is covered by
the current million-person result.

**Concise update for Piotr:**
> The connected synthetic tests reached 1M people and 12.98M connections. Five-seed
> distances refreshed in 8m 03s; Louvain plus exact within-community betweenness
> refreshed in 28m 59s, and all scores were independently validated. The scale
> runs use one Louvain level/seed 42, unlike the demo's five levels/seed 7. Of the
> 1M community refresh, 19m 37s was the Logic transaction and 7m 10s was exports.
> These are single-run results on bounded-degree synthetic data. Next is a controlled
> 100K test of export overhead, keeping the graph and algorithms unchanged.


## Reduced-export experiment at 100K — November 5, 2026

**Completed and independently validated.** The isolated experiment uses the same
100,000 people, 1,297,797 edges, one Louvain level/seed 42 and exact internal
betweenness with 100,000 pivots. Only Snowflake persistence was filtered: keep
`PERSONCOMMUNITYPROBE` and `KNOWS` after the unchanged Logic transaction. The full
compiled computation and its staged exports remain intact. This is a scoped
experimental procedure adjustment, not a public SDK output-selection setting;
installed SDK files and the model's algorithm/business-rule files were not edited.

| Phase | Original 100K | Reduced exports |
|---|---:|---:|
| Logic transaction | 130.085 s | 125.598 s |
| Snowflake result export window | 188.842 s | 25.281 s |
| Other startup/loading/polling/finalization | 132.635 s | 164.284 s |
| **Total refresh** | **451.562 s** | **315.163 s** |
| Persisted exports / parallel batches | 72 / 9 | 2 / 1 |

Total refresh was 136.399 seconds (30.2%) shorter in this pair of runs; export time
was 86.6% shorter. This is one run per variant at different times, not a repeated
benchmark or a promise of equivalent savings at 1M. Engine resume and deployment
are excluded from both refresh measurements. Similar Logic times support the
interpretation that this experiment changes persistence, not algorithm speed.

All 100,000 internal scores and the full 1,297,797-edge set passed the independent
oracle. The partition also matches the earlier 100K partition as sets of people:
13,784 communities, largest 43. Scores agree with the previous run within the
existing tolerances. The demo community/Knows outputs, original 100K community/Knows
outputs, protected original sources and baseline distance deployment retained their
checked fingerprints. The Cortex agent continues to use its baseline outputs.

The experiment occupies `PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_100K_COMMUNITY_LEAN`
and its `_META` schema in `ALAA_RELAPP_PERSISTENCE`, using existing copied sources,
`RAI_USER`, `RAI_XS` and the existing Logic reasoner. Skipped intermediate output
tables remain empty: this schema is an experiment, not a replacement for a full
model deployment. No scheduled refresh was enabled.

Installation initially stopped on a local SQL-escaping mismatch before any refresh;
fully qualified GET_DDL and correct backslash/quote escaping resolved it. The same
installed schemas were reused, and exactly one refresh was executed. The existing
runner/tests were extended; 67 offline checks passed, plus the real-DDL regression
and live validation. The failure diagnostic was preserved in the experiment's
`.debug.zip` artifact.

Evidence: [experiment and timing comparison](artifacts/people_communities_connected_100k_reduced_exports.json).
Successful task query: `01c83626-010c-d809-0005-5ee31376c842`.

**Next:** repeat the same 100K comparison before treating the saving as stable, or
ask the SDK team for supported output selection. Do not promote the filtered helper
to the demo or claim a million-person improvement without measuring it.


## Five-level Louvain at 100K — November 5, 2026

**Failed at the configured Logic transaction timeout.** One manual refresh used
100,000 synthetic people and the existing 1,297,797-edge fixture, with
`max_levels=5`, `randomization_seed=7`, and exact within-community betweenness
(`num_pivots=100000`). It retained the full export plan, source data, SDK version,
RAI_XS warehouse and existing HIGHMEM_X64_S reasoner. The two settings change
together, so this compares configurations rather than isolating a level-count effect.

| Configuration | Refresh outcome | Total refresh time |
|---|---|---:|
| One level / seed 42, full exports | Passed full oracle validation | 451.562 s (7m 31.6s) |
| Five levels / seed 7, full exports | Failed: Logic transaction timeout | 1,634.520 s (27m 14.5s) |

The Logic transaction was ABORTED with reason `transaction timeout`, after
1,508.684 seconds wall time; the configured limit was 25 minutes. Remaining time
was startup/loading and orchestration. No final Snowflake export calls ran.
There are **no validated community sizes, modularity or betweenness scores** for
this five-level 100K run. The result does not establish that the configuration
can never complete at 100K, or that it exhausted memory.

The debugger bundle contains the plan (1,093,161 bytes), trace (36,793,415 bytes),
refresh log and transaction progress. The longest recorded logical stage was
shortest-path counting used in betweenness (1,059.861 s). This is a diagnostic
lead, not a proven root cause: stages can overlap and their timestamps can end
at transaction abort. The root SQL statement reported zero provisioning, repair,
overload and transaction-blocking wait time; this does not exclude engine-internal
waits.

Original/copied baseline inputs, baseline distance outputs and deployment state,
the demo's community/Knows outputs, and both previous 100K community variants
retained their checked fingerprints. The experiment task remains suspended with
no schedule. No retry, sampling substitution, timeout increase, engine resize,
SDK edit or demo-agent change occurred. Existing runner/test files were extended
only to give non-default scale configurations their own output schemas; 11 focused
offline checks passed before execution.

Resources: `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_100K_COMMUNITY_L5_S7`
and its `_META` schema. These contain an unsuccessful experiment and must not be
presented as validated outputs.
Task query: `01c83639-010c-dae7-0005-5ee313773de6`.
Logic transaction: `01c8363b-010c-dae7-0005-5ee3137764be`.

Evidence: [run record](artifacts/people_communities_connected_100k_5_7.json) ·
[debugger bundle](artifacts/people_communities_connected_100k_5_7.debug.zip).

**Next:** review the captured plan with Piotr/the RAI team before running this
configuration at 1M. A follow-up that separates community detection from exact
betweenness could identify where the cost comes from; it was not run here.

**Update for Piotr:**
> Warm paths, communities and internal betweenness are deployed, and the one-level
> synthetic scale tests passed through 1M people/~13M connections. I also tested
> the demo's five-level/seed-7 configuration at 100K with exact betweenness. It hit
> our 25-minute Logic timeout, whereas the one-level 100K refresh completed in
> 7m 32s. I captured the query plan and progress; shortest-path counting is a lead
> to investigate before taking that configuration to 1M. Happy to walk through it.


## On-demand routes from raw records: local 10K experiment — November 10, 2026

`pe_deal_graph/person_path.py` provides `PersonPaths(directory).query(source, target)`.
It reads raw people and employment records and builds lookup indexes by person and employer.
It does not construct the full Knows graph or calculate distances before receiving a question.
Each search derives the visited person's connections using the existing K1 overlap and strength
formula. Breadth-first search finds the shortest distance, retaining one strongest prefix per
person to select a strongest shortest route without enumerating complete paths. The output
includes names, role IDs, overlap dates, strengths and the number of shortest person routes.
Search state is discarded between calls. CSV changes require constructing a new `PersonPaths`.

```bash
.venv/bin/python -m pe_deal_graph.person_path   --csv-dir data/scale_connected_10k   --source P19079 --target SCALE_P000000004

.venv/bin/python -m pytest tests/test_person_path_local.py -q
```

The existing 10K fixture has 10,000 people and 30,169 roles. All 82 cases passed against the
independent `data/oracle.py` graph and NetworkX shortest-route enumeration: planted routes,
random pairs, reverse directions, thresholds, self, unknown IDs, unreachable and hop limits.
Distance, maximum product score, route count, each edge and deterministic tie ordering were
checked. The oracle builds a full graph only for verification; the query never reads it.
Source CSV hashes were unchanged. Results: `artifacts/person_paths_on_demand_10k.json`.

Recorded on this local machine: CSV loading/indexing 0.078 s; median reachable query 0.054 s;
maximum query 0.514 s. Setup is separate from query time; no neighbor/result cache is used.
One five-hop query expanded 9,258 people, illustrating that an on-demand search can still
inspect most of the population. These local Python times are not comparable directly with
Snowflake calls or RAI refresh times.

Scope: this prototype implements K1 employment/board overlap. This fixture has no deal or CRM
records; datasets containing them are rejected rather than silently ignoring K2/K3 rules.
It calculates one requested route, not community detection or centrality. No Snowflake queries,
deployments, reasoner changes, or agent updates were made for this experiment.


### Community scores on request: local 10K check

The same `pe_deal_graph/person_path.py` now exposes `CommunityConnectors(records)`.
Construction builds a graph from K1 source records and finds Louvain communities with NetworkX
(maximum five levels, seed 7, unweighted). It calculates no betweenness at that stage.
`query(person_id)` calculates exact, unnormalized betweenness only inside the person's community.
Later requests for any member of that community reuse the scores. The cache exists only inside
that Python instance; a new data snapshot or different settings requires a new instance.

Recorded example: Marcus (`P19079`) -> Priya (`P25319`) -> `SCALE_P000004201` ->
`SCALE_P000004200`. Three hops, product 1.0, one shortest route; each hop has employment evidence.
This route is computed from raw records independently of the community preparation.

| Stage | Local elapsed time |
|---|---:|
| Load source records and indexes | 0.077 s |
| Requested route | 0.0073 s |
| Build full graph for community detection | 0.555 s |
| Detect 44 communities | 1.615 s |
| Exact scores for the requested 185-person community | 0.152 s |
| Repeat request using that community's scores | 0.000042 s |

Only one of 44 communities was scored. All 185 scores matched an independent implementation
of the shortest-path definition across 17,020 unordered pairs (maximum error 1.02e-11).
The graph's 131,904 edges matched the independent source-data oracle; the route's shortest
distance, strongest product and count matched too. Input CSV hashes were unchanged.
These are single local observations on a synthetic 10K graph, not RAI or Snowflake timings.
A local NetworkX partition need not equal the deployed RAI partition even with similar settings.

```python
from pe_deal_graph.person_path import PersonPaths, CommunityConnectors
records = PersonPaths("data/scale_connected_10k")
route = records.query("P19079", "SCALE_P000004200")
communities = CommunityConnectors(records)
first = communities.query("SCALE_P000004200")  # Computes just this community.
again = communities.query("SCALE_P000004200")  # Reuses its scores.
```

CLI: add `--community` to a local route command to also analyze the target's community.
Each CLI invocation is a fresh process. Reuse across questions requires retaining the
`CommunityConnectors` instance, as above. No hosted cache or agent integration was added.
Evidence: `artifacts/person_paths_community_on_demand_10k.json`.
Reproduce validation: `python -m pytest tests/test_person_path_local.py -k requested_community_10k`.


### 1M team-to-target request using saved RAI communities — November 10, 2026

Extended the existing `scripts/person_path_proc.py` with `team_introduction_1m` and
`SavedCommunity1M`. Reads current team roles to identify seeds, invokes the existing
SELECT-only path procedure for each seed, ranks by hops then strength, and fetches current
roles/company names for route participants. Community membership is read from the existing
`CONNECTED_1M_PATHS.PERSON_COMMUNITY_L5_S7_P50000_X200` output (RAI five-level/seed-7 run).
The optional exact calculation downloads only the requested community's internal edges and
scores its members with local NetworkX. Repeated requests in that Python instance reuse scores.

Live target: `SCALE_P000004200` (synthetic Person000004200). Returned routes:

| Team member | Hops | Product score | Procedure call |
|---|---:|---:|---:|
| Tom Harlowe | 5 | 0.648294 | 2.844 s |
| Grace Liu | 5 | 0.383223 | 1.891 s |
| Priya Raman | 6 | 0.962218 | 3.688 s |
| Dana Okafor | 6 | 0.890882 | 4.007 s |
| Marcus Whitfield | 6 | 0.526622 | 5.220 s |

The five route calls plus target/role work measured 19.530 s after team discovery; this excludes
connection setup, validation reads and community requests. All five distances matched the saved
validated seed-distance table; all 28 returned hops and their products were checked against KNOWS.
Every hop included evidence. Strength optimality was not independently recomputed for these five
queries. The procedure implementation had previously passed independent optimality tests.

Target community 557 has 648 members. Reading saved RAI sampled scores took 0.788 s. Requested
exact internal scores took 2.096 s: data reads/build 1.598 s, local calculation 0.498 s.
A repeat exact request took 0.164 s (includes membership lookup) with no centrality recalculation.
Only this community was calculated locally; Louvain was not rerun. Its first three ranked IDs
were identical between saved sampled and new exact scores, although score values differed.
This one community does not establish general approximation accuracy.

```bash
.venv/bin/python scripts/person_path_proc.py --fixture connected1m --team-to SCALE_P000004200
.venv/bin/python scripts/person_path_proc.py --fixture connected1m --team-to SCALE_P000004200 --exact-community
```

The first command reads existing RAI community scores; the second computes exact scores locally
for the target community. Each CLI invocation starts a new process. For repeated exact queries,
retain a `SavedCommunity1M(connection)` object and call `.query(person_id, exact=True)`.
It assumes the saved graph and partition remain unchanged; recreate it after a refresh.

The 1M source has 3,000,691 Employee roles, 3 Deal Team roles and 2 Operating Partner roles.
It has no CEO/CFO roles. Company-to-CEO resolution cannot be demonstrated with this fixture;
no executive roles were invented or inserted. This is the real 1M deployment's person-target
workflow, not agent integration. All live actions were reads or the existing read-only procedure.
No new schemas, graph refresh, reasoner resume/resize, grants or deployment changes occurred.
Evidence: `artifacts/team_target_1m_on_demand.json`. Focused offline saved-community cache test passed.

### 1M introduction evidence and threshold test — November 10, 2026

Created `PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_1M_INTRO_TEST` in
`ALAA_RELAPP_PERSISTENCE`. It reads the existing 1M Person and directed Knows
outputs through views. Three existing synthetic IDs receive display names only
in this test: Alex Morgan (`SCALE_P000004200`), Maya Chen (`SCALE_P000600001`),
and Jordan Ellis (`SCALE_P000600002`). Alex is a Director of Partnerships, not a
CEO. Two added employment roles, two deal-party records, and twelve CRM records
produce five added unordered connections. Six CRM records deliberately fail the
personal-connection rules: negative, neutral, too old, future, organization-only,
and recorded by a non-team person. All six exclusions passed.

The isolated SQL views apply the existing K1 employment-overlap, K2 lead-person
co-participation and K3 positive person-level CRM formulas to these small facts.
Every added pair, strength and evidence kind matches `data/oracle.py`. The
existing JavaScript `PERSON_PATH` implementation is reused without modification.
**This tests SQL/JavaScript queries over RAI-materialized base connections. It is
not a new native RAI enrichment run or a Cortex natural-language evaluation.**
No original tables, existing deployments, agents, engines, grants or schedules
were changed. Communities were not refreshed for the enriched graph.

Four question cases ran three times each on `RAI_XS`. All 36 underlying route
calls passed independent validation of shortest distance, strongest product,
chosen route and shortest-route count. The reference exhaustively enumerated
shortest routes in a sufficient neighborhood: all routes up to three hops are
covered by edges from the seeds, target, and target's immediate neighbors.
Every tested answer was within that bound. Only 1,489 directed rows were needed
for the unfiltered reference, and 1,120 at minimum link strength 0.75.

| Question | Verified answer | Hops | Product strength | First / median repeats |
|---|---|---:|---:|---:|
| Who on our team can connect us to Alex, and why? | Priya → Alex; one positive CRM interaction on 2026-09-15 | 1 | 0.600000 | 11.632 / 4.957 s |
| How can Marcus reach Alex, with evidence? | Marcus → Maya → Alex; three positive CRM interactions, then 1,004 days of employment overlap | 2 | 0.812320 | 1.046 / 1.043 s |
| Who should connect us when **every link** must be at least 0.75? | Marcus → Maya → Alex | 2 | 0.812320 | 15.327 / 6.085 s |
| How can Dana reach Alex, with evidence? | Dana → Jordan → Alex; two positive CRM interactions and lead roles on the 2025-06-01 recap | 2 | 0.560000 | 0.898 / 0.950 s |

The ranking remains fewest hops first, then strongest product. Priya therefore
wins without a threshold despite Marcus's larger product. At the 0.75 **link**
threshold, Priya's direct 0.6 link and Jordan–Alex's 0.7 link are excluded, so
Marcus wins. A link threshold is not a minimum route-product threshold.
Strengths are model heuristics, not introduction probabilities.

Times are full Python execute/fetch for the requested question. Team questions
make five sequential procedure calls; individual questions make one. Median
repeats means runs 2–3, not a broad performance distribution. Connection setup
(1.215 s), installation (8.255 s), independent validation and local report work
are excluded. The warehouse was warm, validation preceded timing, and result
caching was not disabled; the first measurements are **not cold-start timings**.
These are planted short-route correctness cases in a million-person background,
not evidence of dense-hub, worst-case, or real-customer performance.

Implementation: `scripts/intro_evidence_experiment.py`; eight offline tests in
`tests/test_intro_evidence_experiment.py`. Re-run queries without reinstalling:

```bash
.venv/bin/python scripts/intro_evidence_experiment.py --test --repeats 3
```

`--install` creates the isolated test schema once and rejects existing schemas.
Evidence with all answers, query IDs, timings and facts:
`artifacts/intro_evidence_1m.json`.

### Cortex agent for the enriched 1M test — November 10, 2026

Created a separate agent, **PE Introductions — Enriched 1M Test**:
`ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_1M_INTRO_TEST.PE_INTRO_1M_TEST`.
Open Snowsight with `RAI_USER`, then **AI & ML → Agents**, select this agent,
and use **Preview / the agent playground**. The four sample questions are saved
in its configuration. The original `PE_GRAPH_ASSISTANT` is unchanged.

The new `INTRO_LOOKUP` procedure resolves person names, invokes the existing
on-demand `PERSON_PATH` search, and returns a complete team summary. Detailed
paths are returned for the nearest team sources or the explicitly requested
person. Minimum strength applies to every individual link; ranking remains
fewest hops, then greatest product. No answer constants are embedded in the
agent instructions. The caller-rights procedure receives bound values rather
than arbitrary SQL. New access grants are confined to INTRO_TEST objects.

Named deal-party records resolve an ambiguity in the original text evidence:
Alex Morgan is the seller, Jordan Ellis the sell-side advisor. Both names and
roles are now returned together. The tool limits route detail to prevent
conclusions about undisplayed alternatives. Person-level CRM does not establish
that an interaction was a one-on-one meeting.

The final four **real Cortex requests**, each starting a fresh conversation,
passed numerical tool-result checks and factual review of the generated answer:

| Question | Answer | Full Cortex request |
|---|---|---:|
| Who on our team can connect us to Alex Morgan, and why? | Priya, 1 hop, 0.600; all five sources covered | 15.404 s |
| How can Marcus reach Alex Morgan? Give hops, strength and evidence. | Marcus → Maya → Alex, 2 hops, 0.812 | 12.737 s |
| Who can connect us when every link must be at least 0.75? | Marcus, 2 hops, 0.812; all five sources covered | 16.533 s |
| How can Dana reach Alex Morgan, and what supports those connections? | Dana → Jordan → Alex, 2 hops, 0.560; seller/advisor roles correct | 12.997 s |

Seven direct tool cases also passed: the four questions plus missing person,
invalid threshold and self-distance. All were executed as RAI_USER with
secondary roles disabled. Snowflake query history independently confirms
RAI_USER for all four actual Cortex tool calls. No tool response was truncated.
These are four tested questions, not proof of every possible natural-language
answer. Earlier responses and their correction notes are retained in the report.
The timings include tool execution and language generation, on a warm warehouse
with previous validation calls; they are not cold-start measurements.

Agent, original lookup definition, 4,300 baseline distance rows and 2,506 baseline
community rows retain their saved fingerprints. No original source data,
existing deployment, reasoner settings, recurring tasks or SDK files changed.
The new agent provides introductions only; community scores were not refreshed
for the added links and are not exposed by this agent.

Implementation: `scripts/intro_test_agent.py` (prepare/deploy/test/update commands).
Evidence and complete final answers: `artifacts/intro_test_agent.json`.
Only use `update` for this separately recorded test agent; the original demo
integration is not imported or modified. Retest with:

```bash
.venv/bin/python scripts/intro_test_agent.py test
```

Snowflake's [agent testing instructions](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-manage#test-the-agent)
describe opening the playground. The documentation search service was absent,
so official public documentation was used without installing account infrastructure.

### Attribute discovery added to the 1M test agent

`find_people` resolves a company name/ID and job-title/role phrase against the
1M source employment records plus the enrichment. It supports current-only or
historical-inclusive searches, CEO/CFO/COO/CTO title aliases, and explicit multiple
matches. The agent calls the existing introduction tool with the resolved ID.
No person's identity or executive title is guessed. Only the test agent changed.

Actual Cortex checks passed: Harbor's Director of Partnerships resolved to Alex
and recommended Priya (one hop, 0.600); Harbor's Head of Customer Operations
resolved to Maya and recommended Marcus (one hop, 1.000). Saltmarsh was correctly
reported absent from this 1M fixture. A direct lookup distinguished Harbor's
missing CEO role from a missing company. The original demo snapshot was unchanged.
These checks cover company/title discovery, not arbitrary attributes absent from
the data. Evidence: `artifacts/intro_attribute_tests.json`.
Reproduce setup with `python scripts/intro_test_agent.py attributes`.

### Enriched 1M test: 100 team employees (2026-11-10)

Extended only `CONNECTED_1M_INTRO_TEST` and its `PE_INTRO_1M_TEST` agent.
The base remains 1,000,000 people. The overlay now has 198 person labels,
242 role records (including 100 current team memberships and 40 former roles),
42 deal-party records and 211 CRM records. Twenty additional operating companies
have CEO, CFO, COO, business-development and partnerships roles. Harbor Analytics
remains available. These are deterministic synthetic additions, not real contacts
or enrichment of every person in the million-person fixture.

The 100 employees share a synthetic team workplace. This deliberately introduces
a team clique; it is not evidence of realistic workplace density or familiarity.
The existing independent rules agree on all 5,275 overlay evidence pairs. Final
edges take the strongest evidence across base and overlay without parallel pairs.

Team lookup now searches outward from the target once and finishes the entire
nearest-team layer. It ranks every source in that layer by the product of link
strengths and preserves ties. All 100 employees are eligible, but distances to
farther employees are not computed: they cannot win the hop-first ranking. A
named-source request still uses the existing two-person procedure. Search limits
are 12 hops / 300,000 read edges; reaching a limit is not reported as unreachable.

Four queries were checked against exhaustive NetworkX routes over all edges
needed for paths of up to three hops from all 100 seeds, then through Cortex:
Harbor's partnerships director, Cedarbridge Health's CEO, Willow Diagnostics'
CFO, and Cedarbridge's CEO with every link at least 0.75. Direct lookups took
2.23–3.78 seconds; Cortex responses took 16.85–21.08 seconds. These are four
individual observations on a warm environment, not latency percentiles or a
long-distance stress test. The threshold case has multiple tied winners, which
the agent reported.

RAI supplied the existing base graph. This extension derives synthetic evidence
with SQL and searches paths using JavaScript/Snowflake at request time. It does
not run a new RAI graph algorithm or refresh communities. The original demo's
agent definition, lookup procedure and distance/community output fingerprints
were unchanged. No engine changes, source reloads, commit or push occurred.

Reproduction (existing isolated schema only):

```bash
.venv/bin/python scripts/intro_test_agent.py expand
.venv/bin/python scripts/intro_test_agent.py test-expanded
```

Evidence: `artifacts/intro_expanded_1m.json`. Example playground question:
“Who among our 100 employees can connect us to the CFO of Willow Diagnostics,
and what supports that connection?”

### Revised introduction fixture and contact exploration (2026-11-12)

This replaces the November 10 synthetic overlay **only in
`CONNECTED_1M_INTRO_TEST`**. Start a new conversation in `PE_INTRO_1M_TEST`:
selected synthetic person IDs changed, so earlier chat answers describe the old
fixture. Original PE data, its agent, distance/community outputs and engine
settings were not changed.

The team still has 100 members. Membership is now separate from relationship
inference: sharing the team employer no longer generates 4,950 coworker pairs.
The resulting test graph has 10 undirected team-to-team edges. Selected seed and
executive IDs are deterministically dispersed across the background graph instead
of using consecutive IDs that encoded shared workplaces. The overlay has 203
labels, 254 roles with varied dates, 42 deal-party records, 73 CRM records and 100
team memberships. Some companies have no direct team CRM, contacts are not always
CEOs, historical overlaps vary, and five advisors replace the universal advisor
hub. All 209 derived overlay pairs match the independent Python evidence rules.

This is a more varied synthetic fixture, **not an empirically validated model of
professional relationships**. The unchanged million-person background retains
generic names, bounded workplaces and synthetic employment patterns. Co-employment
scores remain heuristics; membership, matching attributes and community labels do
not establish personal familiarity. No community refresh occurred.

New read-only tools (as RAI_USER):

- `SEARCH_PEOPLE`: combines name/ID, company, title, current/former/any employment
  and optional team membership. Role records are paginated, with both total role
  records and distinct-person counts. Former means ended by the model date;
  it does not silently include current roles. Acronyms are expanded before
  substring matching, so CTO does not match the letters inside Director.
- `PERSON_CONTACTS`: all one-hop contacts by default, including non-team people;
  optional minimum strength or team-only filter. Returns names, current roles,
  strongest score evidence, additional evidence and explicit deal-party roles.
  Deterministic pages contain at most 50 contacts and always expose totals and
  `next_page`. Caller inputs are bound; page numbers/limits are validated integers.
- Introduction search remains separate: nearest eligible team sources ranked
  by hops then strength. It is not an all-team distance histogram. The agent must
  not answer a >2-hop request with 2-hop examples or claim complete distances
  from partial source checks.

Validation: 13 offline tests; independent evidence scores; all 100 employees
recovered through attribute pagination; all Willow CEO contact pages compared
with graph IDs, strengths and evidence; minimum-strength and team-only filters;
former/absent roles; invalid pagination, unknown person and isolated person.
Four initial Cortex questions passed data review; an additional deal-role question
checks named seller/advisor evidence. The current Willow CEO has **22 direct
contacts, none on the team**; **18** meet strength >=0.75. Exactly **one** team
member is within two hops, while **99 are not within two hops** (that check alone
is not an exact distance or reachability claim for those 99). The first four
Cortex answers took approximately 12–35 seconds in a warm environment.

Reproduce locally against the isolated test schema:

```bash
.venv/bin/python scripts/intro_test_agent.py revise
.venv/bin/python scripts/intro_test_agent.py test-revised
```

`revise` replaces only generated facts in the test overlay transactionally and
updates its views/tools/agent. It does not reload source tables or modify shared
reasoners. Validation evidence is in `artifacts/intro_varied_1m.json`.
