# Corporate People Graph Explorer

Local visualization of the new 1M-person / 1,000-company corporate dataset. Adapted from `field-pov/field_applications/pyrel_semantic_graph_explorer` on November 12, 2026. The source directory was not edited; its documentation is preserved in `UPSTREAM_README.md`.

## Start

From the repository root:

```bash
bash pyrel_semantic_graph_explorer/start.sh
```

Open **http://127.0.0.1:3000**. The API listens on **127.0.0.1:8000**. Ctrl-C stops the local services started by the script. Logs are in `.runtime/`. Keep the existing `raiconfig.yaml` and PAT file on the server; they are never sent to the browser.

The current workspace already has the dependencies. On a fresh checkout:

```bash
uv sync --python 3.13
uv pip install --python .venv/bin/python -r pyrel_semantic_graph_explorer/service/requirements-corporate.txt
cd pyrel_semantic_graph_explorer/ui-next
npm ci
```

Node.js 20.9+ is required. This machine's launcher also discovers the bundled Codex Node runtime if `node` is absent from PATH. npm installs the UI dependencies; it does not calculate relationships or neighborhoods.

New calculations require the configured RAI logic reasoner to be READY. It retains its existing 30-minute auto-suspend setting. To resume it explicitly from the repository root:

```bash
env -u DEBUG RAI_CONFIG_FILE_PATH="$PWD/raiconfig.yaml" .venv/bin/rai reasoners resume --name alaa_pe_deal_graph_experiment --type Logic
```

The API returns a clear error when the reasoner is unavailable; it never falls back to Python or SQL graph calculations. Previously computed RAI results are cached locally with their calculation time and model/data fingerprint. Use **Recalculate** for a fresh execution.

## Use

- Start with Vikram Z. Kessler or **Our PE team**, or search by person, ID or company.
- Click a node or use **Inspect a visible person** to see career dates, workplace assignments and cohort metrics. Choose **Explore their network** to recenter.
- Click an edge or **Inspect strongest visible connection** for every contribution to its score: overlap, spatial factor, temporal bands, career normalization and squared duration. Friendship is deferred.
- Change the as-of date, minimum strength and displayed neighbor count. Rendering limits never change the total calculated by RAI.
- **Communities & bridges** shows a validated native RAI snapshot. Color indicates community, node size indicates cohort betweenness and edge width indicates relationship strength.
- Names can repeat; person IDs distinguish records. All people, locations and friendships are synthetic.

## People and employment

The shared ontology contains Person, Company, Employment, OurTeamMember, Connection and IntroductionRoute. “Our PE team” is the OurTeamMember subset of Person, backed by the separate team roster. Each Employment links its person and company and carries the job dates, title and location. The graph displays Connection instances between people; clicking one opens the employment evidence and score breakdown. IntroductionRoute describes the paths returned by the agent. The neighborhood view remains a one-hop view.

## Where computation happens

`corporate_agent/scoring.py` is the single shared scoring model for this explorer and the Snowflake agent. `pe_deal_graph/corporate_graph.py` adds native RAI `Graph.distance` to obtain exact one-hop incident neighborhoods. Python formats results and Cytoscape draws them.

```text
effective_years = sum(unique_shared_days × spatial_factor × temporal_decay) / 365.25
career_fraction = min(effective_years / mean_employed_career_years, 1)
squared_duration = min(effective_years / 10, 1)²
raw_strength = 0.5 × career_fraction + 0.5 × squared_duration
strength = sqrt(sqrt(raw_strength))   # fixed fourth-root normalization; friendship deferred
```

Shared employment requires at least 365 overlapping days. Workplace factors are 1 for the same onsite office, 0.6 for different offices in the same synthetic city, and 0.25 for company-only evidence. Temporal bands are 0–2 years ×1, 2–5 ×0.8, 5–10 ×0.5, 10–15 ×0.25 and older ×0.1. Concurrent intervals count once; dated slices can cross several decay bands. The [shared model documentation](../corporate_agent/README.md) explains all ten rules.

Neighborhoods contain the center's incident edges; links between neighbors are outside that view. The separate communities view uses all 2,100 leadership-cohort people (100 PE employees, 1,000 CEOs, 1,000 synthetic Heads of Data), retaining edges with raw strength ≥(.02/.75), equivalent to normalized strength ≥.404103. Weighted Louvain and exact **unweighted** betweenness run in RAI. Metrics cover that cohort, not the full million-person population, and never enter the relationship score. The viewer displays a subset of nodes while retaining full-cohort metrics.

The generic upstream service and `/semantic` UI remain as reference. They are not the corporate service. Production imports no NetworkX graph-calculation fallback.

## Data and validation

Original corporate CSVs are regenerated under `data/corporate_1m_1000_companies/` and are omitted from this GitHub copy, with their existing Snowflake schema `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CORPORATE_1M_SRC`. Separate PE histories and v2 enrichment reside in `PE_DEAL_GRAPH_EXPERIMENT_CORPORATE_AGENT`, with generated files in `data/pe_team_100/` and `data/corporate_enrichment_v2/`. Existing corporate careers and the older agent are preserved.

Current validation artifacts:

- `artifacts/corporate_affinity_v5_acceptance.json`: native scoring, routing, normalization and analytics checks.
- `artifacts/corporate_agent_acceptance_v5.json`: existing live agent questions and native execution references.
- `artifacts/corporate_presentation_acceptance.json`: live natural response wording with unchanged paths and scores.
- `artifacts/normalized_score_cluster_investigation.json`: strongest-25 selection and fourth-root compression.

These are retained records of prior runs, not tests executed by the packaging process. Earlier v1/v2 artifacts describe superseded scoring versions. Independent SQL/Python oracles are testing utilities only and do not provide production graph results. Three-hop work remains experimental; the active agent searches up to two hops.
