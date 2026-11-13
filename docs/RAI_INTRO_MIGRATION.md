# PE introductions through RAI

Extend the existing PE model and enriched 1M test with 100 team members. Preserve
Piotr's concepts and names. RAI/PyRel must construct the graph, derive relationship
strengths, calculate requested introduction routes, detect communities and compute
within-community betweenness. The Cortex agent/stored procedure is the interface.
The current JavaScript BFS is a comparison baseline, not the final RAI implementation.

Use the installed ontology, PyRel, graph-analysis and deployment skills. Reuse
existing data and model definitions. Confirm supported APIs and actual reasoner
routing. Rank routes by fewest hops, then highest product of strengths; return
names, dated evidence, ties and explicit search limits. Resolve company/title/name
attributes and ambiguities. Community analysis must refer to the same enriched
graph, with exact versus sampled scores identified. Do not infer business usefulness
from community membership or equate centrality with the best route to a target.

Follow demo-maker's evidence practices: scoped questions, executable ontology,
independent correctness checks, recorded live query evidence and first/repeated
latency measurements. First use bounded cases, then the existing 1M fixture, before
switching the test agent. Do not claim that compilation or app visibility proves
RAI graph execution. No all-pairs precomputation is required.

This is a focused extension. Prediction, optimization, slides, regenerated synthetic
data and a complete new demo are outside the requested scope. A partial harness
run must not be described as a complete demo-maker validation pass.

Preserve the lab, original PE demo, colleagues' resources and working agents.
Do not resize or change shared engines, commit or push. Keep credentials out of
worker inputs, logs and artifacts. Apply the demo-maker evidence workflow directly in this project; no harness workers
are being launched. This focused extension does not require a new full demo.

The demo-maker workflow is applied directly to this scoped extension; no harness
workers were launched and no complete demo-maker harness pass is claimed.


## Local implementation — 2026-11-12

`pe_deal_graph/intro_rai.py` now provides the isolated test model. It reuses the
baseline RAI `CONNECTED_1M.KNOWS` output and reads the enrichment's raw role, CRM,
and deal facts. PyRel derives added strengths; it does not consume the test's
SQL-derived `ADDED_EVIDENCE` or `KNOWS_EDGES` views. This preserves the experiment's
current enrichment rules, including exclusion of membership-only EXP_TEAM roles.
It is not a fresh derivation of all baseline employment relationships.

For a resolved target ID, RAI `Graph.distance` computes single-target distances.
PyRel rules then retain the highest-product shortest route at each successive
layer, capped at 12 hops. This avoids enumerating every route and does not compute
all-pairs distances. The cap bounds route reconstruction, **not the distance
algorithm's work**. All team members are included; unreachable and beyond-cap
results are explicit. Python formats names and dated link evidence after RAI has
selected routes. It does not run BFS. One deterministic witness is returned per
source; alternate equal-score routes are not enumerated.

Louvain and within-community betweenness reuse `community_connectors` on this same
enriched graph. They are separate explicit calculations, not triggered by every
route request. No existing community output has been replaced.

## Live validation — 2026-11-12

The user authorized resuming `alaa_pe_deal_graph_experiment` at its existing
`HIGHMEM_X64_S` size. It reached READY without resizing or changing another engine.
The five enrichment source tables needed change tracking enabled for RAI ingestion;
only those test tables were altered. No source rows were changed.

Native PyRel validation passed:
- All 209 added unordered relationship strengths match the independent oracle.
- All 100 team distances and best-product scores match at thresholds 0 and 0.75.
- Named-source and zero-hop self cases also pass.
- Returned route edges, evidence, endpoints and products were checked. Independent
  SQL checks covered 376 unfiltered and 413 filtered returned directed edges.
- 29 offline checks pass, including isolated agent handoff behavior.

Observed direct RAI request times were 171.4 seconds (100 team members), 214.5 seconds
(threshold 0.75), 157.0 seconds (named source) and 120.0 seconds (self). These are
single observations, not stable performance benchmarks. Correctness does not imply
interactive latency.

The new test-only `PE_NATIVE_*` SDK procedures use the existing test schema and
reasoner. Their first validated catalog route call took 235.4 seconds. All three
returned rows, their route names, scores and evidence matched the independently
validated results, with `total_sources=100` and no truncation. The package initially
failed on conflicting telemetry versions; the new procedures now pin api/sdk 1.38.0
and semantic-conventions 0.59b0 to match Snowflake's preloaded runtime. Local SDK files
were not changed for this repair. The ZIP contains four explicit project modules,
not credentials or the working directory.

`prepare_native_rai_tools()` in `scripts/intro_test_agent.py` reproduces procedure
packaging without switching an agent. `native_rai_specification()` replaces only
the test agent's route tool and retains attribute search/contact browsing. Contact
browsing still reads saved connections; RAI performs introduction distance, strongest
shortest-route selection, and enrichment strength calculation. Python formats the
returned witnesses and evidence; no Python or JavaScript BFS is used by this route tool.

Agent handoff and natural-language validation are recorded separately in
`artifacts/intro_rai_agent_validation.json`. The pre-handoff spec is retained in
`artifacts/intro_agent_before_rai.json` for restoration. Do not describe the agent
as validated until that report confirms its answers. Core evidence is in
`artifacts/intro_rai_live.json` and `artifacts/intro_rai_procedure_result.json`.

No enriched community computation was run in this validation. The new community
query compiles, but its live correctness and sampled accuracy remain untested; the
agent must not expose old partitions as enriched-graph results. No all-pairs
precomputation, automatic refresh, engine resizing, commit or push is included.

## Test agent connected and checked

`ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_1M_INTRO_TEST.PE_INTRO_1M_TEST`
now invokes the native RAI route catalog. Two live Cortex questions passed review:
- Company/title resolution followed by native introduction search: 268.9 seconds.
  Kendall Adler → Avery Gupta-Reed → Avery Foster-Reed, 2 hops, score 0.6997946612.
  All 100 sources were compared; the tool returned the top three without truncation.
- Direct contacts including non-team members: 26.5 seconds. Five of 22 contacts
  returned with strengths/evidence and the remaining count explicitly disclosed.

The original demo agent/procedure/results and lab data hashes match their earlier
snapshots. The reasoner remained HIGHMEM_X64_S. No other engines were modified.
Latency remains a material limitation: this is a verified test interface, not a
claim of interactive performance or a benchmark across multiple targets.
