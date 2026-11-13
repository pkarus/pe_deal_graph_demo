# Corporate PE introductions

Agent: `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CORPORATE_AGENT.CORPORATE_INTRODUCTIONS`.

The agent resolves people with SQL, authors restricted read-only PyRel, and sends it to `EXECUTE_PYREL`. The supplied query invokes native RAI `Graph.distance` and the shared introduction rules. All production relationship scores, paths, communities and centrality are computed in RAI. Python formats and orders returned values; independent SQL/Python oracles are test code and are excluded from deployment.

## Shared scores: corporate-affinity-v5

`scoring.py` is the single scoring model used by the agent and local explorer. All dates are clipped to an as-of date, no later than the synthetic snapshot **2026-10-01**.

1. Employment evidence requires at least 365 concurrent days at the same corporate employer. Current PE employment alone does not create connections.
2. Each person's employed career duration is the union of their employment intervals; concurrent jobs count once.
3. Workplace factors are 1 for the same onsite office, 0.6 for the same synthetic city in different offices, and 0.25 for different locations or remote/unknown company-only evidence.
4. Shared periods in the most recent two years have recency factor 1.
5. Periods 2–5 years ago have factor 0.8.
6. Periods 5–10 years ago have factor 0.5.
7. Periods 10–15 years ago have factor 0.25.
8. Older periods have factor 0.1. Each shared interval is split across all applicable bands; a recent ending never makes an entire long collaboration recent.
9. Friendship is deferred. The source facts remain available, but do not affect scores, create edges or expand scope.
10. Give the original employment score full weight instead of its former .75 multiplier. Duplicate shared intervals count once; concurrent location evidence uses the strongest supported factor for that interval.

```text
effective_years = sum(unique_shared_days × spatial_factor × decay_factor) / 365.25
mean_career_years = (career_years_A + career_years_B) / 2
career_fraction = min(effective_years / mean_career_years, 1)   # zero if no career
squared_duration = min(effective_years / 10, 1)²
time_score = 0.5 × career_fraction + 0.5 × squared_duration
raw_strength = time_score   # original v4 rules, unchanged
strength = sqrt(sqrt(raw_strength))   # normalized display and query-filter scale
```

V4 reassigned the unused friendship share to employment: a 33⅓% uplift to its old contribution, with unchanged employment ranking. All original recency/location factors, effective years, complete career denominator and squared duration remain intact. The rejected v3 high-score calibration is not active. V5 adds only a fixed fourth-root normalization in native RAI. It preserves raw scores and strict ordering, maps 0 to 0 and 1 to 1, and is independent of the query results. `strength` is normalized; `raw_strength` and all raw contributions are retained. Raw .000389969711576 maps to normalized .14052633485. These are presentation-scale values, not calibrated probabilities or percentiles. This hybrid retains career normalization while preventing a short career from automatically outranking a substantially longer collaboration. Scores are symmetric, bounded in [0,1], and heuristic rather than probabilities. `presentation.py` exposes every component and all native RAI temporal slices; it does not recompute scores.

## Source data

Original corporate careers and the older agent are preserved. New physical tables in the isolated corporate agent schema hold the enrichment:

| Table | Rows | Meaning |
|---|---:|---|
| TEAM_MEMBER | 100 | Separate PE employees |
| TEAM_ROLE_HISTORY | 450 | 3–4 previous corporate employers plus current PE role |
| WORKPLACE_V2 | 3,372,048 | Original corporate and PE careers with synthetic workplace assignments |
| OFFICE_V2 | 20,898 | Synthetic office/city facts |
| FRIENDSHIP_V2 | 1,910,282 | Explicit synthetic positive friendship assertions and dates |
| LEADERSHIP_COHORT_V2 | 2,100 | 100 PE employees, 1,000 current CEOs, 1,000 synthetic Heads of Data |

Enrichment is deterministic (`data/corporate_enrichment.py`, seed 74130), stored locally under `data/corporate_enrichment_v2`, and loaded into separate Snowflake tables. Workplace facts exactly preserve original employment fields. Ten percent of roles are remote. Locations and friendships are fictional generated facts, not real-world inferences.

`HEAD_OF_DATA` is an explicitly synthetic designation based on each company's current Data Analytics leaders. CEO titles are original corporate roles. SQL union views support lookups; RAI reads physical base tables.

## Routes and structural analytics

Raw products determine route selection. Because `(a×b)^(1/4)=a^(1/4)×b^(1/4)`, normalized leg scores also multiply to the normalized route score; normalization alone preserves selected paths and rankings. Requested minimum strength filters use the normalized scale unless explicitly stated as raw. Default introduction ranking is the **strongest product across every eligible one-, two- or three-hop route**, then fewest hops, then deterministic path ID. `shortest_route` provides an explicit fewest-hops alternative. Native distance establishes reachability independently of the selected route's hop count. Both `minimum_hops` and selected-route `hops` are returned: a stronger multi-hop route can coexist with a weaker direct edge. The introduction model derives exact co-employment neighbors of the sources and target in RAI, then uses admissible native upper bounds to avoid scoring middle edges that cannot improve the best shorter route. The bound multiplies summed shared time (even duplicated time) by the maximum possible location and recency factors for that pair, then applies the same monotone formula. These maxima conservatively bound every contributing period; a small comparison guard protects against floating-point rounding. Sources with no shorter route retain every qualifying middle edge. This preserves strongest routes and distances up to three hops. All eligible people retain complete careers for the denominator. No neighbor count cap is used; simple routes cannot repeat a person. Scoring remains `corporate-affinity-v5`; routing is separately versioned as `corporate-routes-v2-three-hops`. Each starting person contributes one selected witness, not a count of every possible route. Empty results mean no qualifying path within three hops, not global disconnection.

`analytics.py` runs native weighted Louvain (seed 42, max levels 5) and exact **unweighted** betweenness on the 2,100-person induced leadership graph, retaining raw scores ≥(.02/.75), approximately .026667, equivalent to normalized strength ≥.404103. Louvain and weighted degree continue using raw weights; the normalized display does not change the structural calculation. The installed native API does not support weighted betweenness. Degree and weighted degree are also native outputs. Centrality remains separate from relationship strength. Tiny negative floating-point betweenness residuals are clamped to zero in RAI; the independent all-source oracle validates every value with documented numerical tolerance.

These metrics describe this declared cohort, not the entire million-person network. Outside-cohort metrics are unavailable, not zero. The dated, versioned snapshot is independently checked before its run manifest is published to `NETWORK_RUNS_V2`; `NETWORK_ANALYTICS_V2` and `NETWORK_EDGES_V2` store native outputs. NetworkX is used only to independently validate betweenness and modularity, never to produce published analytics.

Business responses bold the recommended person, explain every employment link in natural sentences, and retain the normalized score and execution references. Generic limitations and calculation details are shown on request; actual errors and bounded no-result explanations remain explicit.

## Local explorer

Run `bash pyrel_semantic_graph_explorer/start.sh` and open http://127.0.0.1:3000. Person neighborhoods use native RAI distance; clicking an edge executes the shared pair model and displays its complete decomposition. The communities view reads the validated native snapshot. Colors indicate communities, size indicates cohort betweenness, and width indicates strength. Displayed subsets never change the scope of the underlying metrics. The person view selects the strongest N qualifying connections; “No minimum” removes the score cutoff, not the display limit. The visible count above the graph makes this selection explicit.

Cache keys include the scoring source, enrichment manifest, person/pair, threshold and as-of date. Saved results retain native transaction IDs. Node/npm are used only to build and serve the browser visualization.

## Deployment and validation

```sh
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python -m scripts.check_affinity_v5
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python -m corporate_agent.analytics
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python -m corporate_agent.deploy deploy
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python -m corporate_agent.deploy chat \
  --role RAI_USER --question 'Who can introduce us to the CEO of Aspenview Materials?' \
  --out artifacts/corporate_agent_chat.json
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python -m corporate_agent.validate REQUEST_ID
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python -m scripts.check_affinity_routes_v6
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/python -m scripts.check_corporate_agent_v6
```

The controlled fixture uses small physical Snowflake tables and the native RAI engine, including current null-ended jobs, concurrent jobs, remote locations, explicit friendship, future employment and recency. The SDK's inline data loader drops nullable rows, so it is unsuitable for this fixture. Native scores are compared with an independent interval-union implementation. Real introduction results are checked against independent Snowflake SQL and every returned edge component is checked separately.

## Audit

`QUERY_AUDIT` stores actual agent-authored PyRel, code and runtime hashes, endpoints, timestamps, status, the full result including every native edge decomposition, errors, native transaction IDs, Snowflake query IDs, session ID and observed engine state. The agent tool deduplicates shared edges and formats compact periods to fit Cortex's response limit; it never changes calculated scores. For larger responses, detailed periods remain in the audit and explorer while the tool retains all rows and numeric score factors. Successful responses require completed correlated native execution. No fallback is used on failure.

`sql/corporate_agent_audit.sql` traces responses. Public native views are **`RELATIONALAI.API.TRANSACTIONS`** and **`RELATIONALAI.API.ENGINES`**. Authored code is in the application audit; execution and engine metadata are in the native views. Every calculation is tagged with its agent request, explorer request, or analytics run ID in native `ATTRIBUTES`; captured query IDs provide an additional correlation path.

With the tested roles, information-schema history exposes parent tool CALLs; native child transactions are verified in the RAI API views. The agent tool-result envelope contains the exact parent CALL query ID. Session and enclosing timestamps link it to the audit record. The tool resumes only the configured engine, with a bounded wait, and never creates or switches engines.

## Release evidence

Current acceptance: `artifacts/corporate_affinity_v5_acceptance.json`. It references native normalization/scoring/routing fixtures, independent SQL checks, current/historical decomposition, real Cortex requests and native transaction logs. `artifacts/affinity_v5_normalization_comparison.json` checks unchanged raw scores, factors, routes, ranking and cohort graph against v4. V2/v4 evidence remains intact; rejected v3 is inactive.

Both raw and normalized values are retained in the audit and exposed by the local inspector. Native RAI computes both scales; Python formats results and performs independent validation only. Live requests take a few minutes; accepted request IDs are in the manifest.
