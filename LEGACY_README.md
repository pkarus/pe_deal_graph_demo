# Working-folder status — November 12, 2026

The new [Corporate People Graph Explorer](pyrel_semantic_graph_explorer/README.md) runs locally at `http://127.0.0.1:3000`. Start it with `bash pyrel_semantic_graph_explorer/start.sh`. It uses the separate corporate 1M source schema, PyRel employment rules, and native RAI graph distance for on-demand one-hop neighborhoods. Existing datasets and Cortex agents remain unchanged.

This is the active experiment folder. `pe_deal_graph_demo-main` is a separate general demo and was left untouched.

Housekeeping is retiring old scale experiments and superseded precomputed deployments. The instructions below are historical: **do not run old deployment/refresh commands to recreate retired schemas**. Current connection requests use the on-demand `FIND_CONNECTION` procedure in `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_1M_INTRO_TEST`. Graph feature work is paused during cleanup.

See [the cleanup report](docs/housekeeping/README.md) for retained inputs, removed artifacts, and verification. Scale CSVs are generated inputs, not permanent project assets; compact manifests remain in `docs/housekeeping/`. The small 10K regression fixture is retained because local tests still use it.

## Corporate employment dataset — local generation

The new corporate mode generates 1M people across 1,000 fictional large companies, with 1–6 distinct employers per career and mean observed tenure near four years. It replaces the small-workplace assumption for this new fixture. Existing baseline and scale modes remain available for regression tests.

```bash
.venv/bin/python data/generate.py --corporate --people 1000000 --companies 1000 --seed 42 --out data/corporate_1m_1000_companies
.venv/bin/python data/generate.py --corporate-check --out data/corporate_1m_1000_companies
```

Generation refuses an existing destination. This workflow is local only; it does not replace the Snowflake data, RAI model, or current agent. See [corporate data assumptions and validation](docs/CORPORATE_DATA.md). The existing employer-overlap rule needs a workload and relationship-quality review before applying it to these large employers.

---

# Northwind deal-graph demo

A live demo of a private equity deal-graph built on RelationalAI (PyRel 1.27.1) running inside Snowflake. Northwind Equity Partners is a fictional US lower-mid-market buyout firm (Fund III, 2019, harvesting; Fund IV, 2023, $1.2B, investing). All companies, people, sponsors and banks are synthetic. Every date rule is relative to `AS_OF = 2026-10-01`, never today.

## If you are an agent scanning this repo

Read this section first. Do not explore the repo.

1. **Answering deal-team questions:** work from `demo_workspace/` and follow `demo_workspace/CLAUDE.md`. It is the source of truth for the presenter session: which prebuilt function answers which question, the answer format, and the rules for ad-hoc questions and the Finale.
2. **Hero questions** are answered by running a prebuilt function, once, in the foreground, from `demo_workspace/`:

   | Question is about | Run |
   |---|---|
   | Thesis fit, readiness, Tier A, score components, not in CRM | `uv run python ask.py q_score` |
   | Warm path, introductions, who knows the CEO (and the owner's board designee) | `uv run python ask.py q_path` |
   | Intermediaries, bankers, deal flow, bridges, coverage gaps | `uv run python ask.py q_flow` |
   | Conflicts with what we own, concentration guideline, a bid on Tessmark Clinical Supply | `uv run python ask.py q_conflict` |
   | Backup: add-ons for Ironvale Testing Group | `uv run python ask.py q_addon` |
   | Finale fallback: warm-path points plus conflict flag, re-score | `uv run python ask.py finale_rescore` |

   `uv run python ask.py --list` shows what exists. Answer only from the rows returned.
3. **Engine unreachable** (`ask.py` exits 3): run `uv run python ask.py --from-exports <function>` and say the live engine is not reachable and this is the precomputed governed export. Do not retry live.
4. **New questions or rules:** load the RAI skill first (`rai-querying`, `rai-rules-authoring`, `rai-graph-analysis`), then write PyRel against the existing model in `demo_workspace/scratch/<name>.py`. Never write SQL. `ONTOLOGY.md` lists the usable names; `demo_workspace/query_bank.md` has the query patterns.
5. **Python:** always `uv run python ...`. The venv is `.venv` (Python 3.13, relationalai 1.27.1). Do not install packages, do not use `pip`, do not touch the engine or Snowflake directly.
6. **Wording that matters:** a conflict flag ("Conflict - cross-fund review") means "on hold until cross-fund clearance", not removed or disqualified. Tier A names with no pipeline entry and no CRM touch have "no coverage". In `q_path`, any returned path up to 3 hops is a warm path; the 2-hop limit applies only to the Finale access-points rule.
7. **Never commit** `raiconfig.yaml` or any token file. They are gitignored and hold the Snowflake connection and programmatic access token.

## Layout

| Path | What it is |
|---|---|
| `demo_workspace/` | Presenter session: `CLAUDE.md`, `ask.py`, `prompts.md`, `query_bank.md`, `scratch/` |
| `pe_deal_graph/model/` | The model: `core.py` concepts, `rules.py` derived rules (docstrings are the business definitions), `graphs.py` graphs |
| `pe_deal_graph/queries.py` | The hero queries |
| `exports/` | Precomputed governed exports used by `--from-exports` and the offline explorer |
| `artifacts/` | Offline Deal Graph Explorer and run-of-show HTML (rebuilt by `make artifacts`) |
| `data/` | Synthetic source data and golden expected answers |
| `ONTOLOGY.md`, `QUESTIONS.md` | Ontology reference and the demo questions |
| `RUNBOOK.md`, `TEST_PLAN.md` | Operating the demo; fresh checkout to live in five commands |
| `Makefile`, `scripts/`, `tests/` | Setup, warm-up, checks and rehearsal |

## Running it yourself

You need a Snowflake account with the RelationalAI native app, the `pe_demo_logic` engine, and your own `raiconfig.yaml` (not in the repo). See `RUNBOOK.md` for the full sequence; in short:

```bash
uv sync --python 3.13
make warm
cd demo_workspace && claude
```

Without a live engine, `uv run python ask.py --from-exports q_score` (and the other functions) still works from `exports/`.

## Data and privacy

Everything here is synthetic. In a real deployment the data, the model and the reasoning run inside the customer's Snowflake account; the agent sees only the result rows of the queries it runs.

## Settings: running on your own Snowflake setup

Database, schema, roles, warehouse and engine names are not hard-coded. They come from
`pe_deal_graph/settings.py`, which reads, in order: `PE_*` environment variables, an optional
`pe_settings.yaml` (copy `pe_settings.example.yaml`; gitignored), your `raiconfig.yaml`, then the
original demo defaults (`RAI_DEMO_PE_DEALS.DEAL_GRAPH`, engine `pe_demo_logic`).

```bash
.venv/bin/python -c "from pe_deal_graph import settings; print(settings.describe())"
```

Experiment outputs go to sibling schemas named `<schema>_<SUFFIX>` in the same database
(for example `DEAL_GRAPH_DEPLOY`, `DEAL_GRAPH_COMMUNITY`). If deployments must run under a
different role from the one in `raiconfig.yaml`, set `deploy_role` in `pe_settings.yaml`.

## Deploy-mode, scale and any-to-any extensions

Added on top of the original demo; the hero queries and presenter flow above are unchanged.

| What | Where |
|---|---|
| Shortest route between **any two people**, strongest among ties | `q_person_path()` in `pe_deal_graph/queries.py` |
| Deploy-mode distances, communities and betweenness; scale runs; lookup benchmarks | `scripts/check_graphs.py` |
| Deployed target/decision-maker rules | `scripts/check_rules.py` |
| Snowflake Cortex agent over the deployed results (`PE_GRAPH_ASSISTANT`) | `scripts/pe_cortex_agent.py` |
| Safety-checked live runs (engine must be READY; never resumes or resets anything) | `scripts/guarded_knows_count.py`, `scripts/guarded_people_count.py` |
| Synthetic scale fixtures (10K to 1M people) and loading | `data/generate.py --scale-connected`, `data/load.py` |

Headline results (synthetic data, single runs, X-Small warehouse):

- Warm-path distances from the 5 team seeds: 1M people / 13M connections refresh in ~8 min; every distance matched an independent check; lookups ~50 ms.
- Communities + exact within-community betweenness: works to 1M with 1 Louvain level (~29 min). The demo's 5 levels takes ~49 min at 100K because communities grow to ~1,700 people.
- Any two people, live: 21/21 stress cases from 1 to 20 hops matched, including strongest-route ties.

Full details, limits and evidence: [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

### Setting it up on a new account

Run from the repo root after `uv sync`, with your `raiconfig.yaml` in place. Each command without
`--execute` only prints what it would do. Every step creates fresh schemas and refuses to overwrite
existing ones; refreshes are manual (no schedules). The engine must be READY for live steps.

```bash
.venv/bin/python -c "from pe_deal_graph import settings; print(settings.describe())"   # check names
.venv/bin/python data/load.py --fixture baseline --execute             # demo CSVs -> <schema>_DEPLOY_SRC
.venv/bin/python scripts/check_graphs.py --run-copied-distance-probe --execute --refresh   # seed distances
.venv/bin/python scripts/check_graphs.py --run-community-probe --community-levels 5 --community-seed 7 \
    --execute --refresh --json artifacts/people_communities_baseline_5_7.json             # communities
.venv/bin/python scripts/check_rules.py --deploy-target-rules --execute --refresh         # Tier A targets
.venv/bin/python scripts/pe_cortex_agent.py deploy                                         # Cortex agent
```

Scale fixtures: `data/generate.py --scale-connected --people 100000 --workplace-size 16 --seed 42 --out data/scale_connected_100k`,
then `data/load.py --fixture connected100k --execute` and the same runners with `--fixture connected100k`.

Any two people, from the deployed tables (stored procedure, 1–4 s, no engine; see `docs/EXPERIMENTS.md`):

```bash
env -u DEBUG .venv/bin/python scripts/person_path_proc.py --fixture baseline --install
env -u DEBUG .venv/bin/python scripts/person_path_proc.py --fixture baseline --call P19465 P67052
```

Communities and within-community connectors at scale (exact for small communities, sampled for large):

```bash
env -u DEBUG .venv/bin/python scripts/community_scale.py --fixture connected100k --prepare
env -u DEBUG .venv/bin/python scripts/community_scale.py --fixture connected100k --levels 5 --seed 7 --pivots 5000 --run --repeat 2
```

Before modelling real employment data, check the tenure rule's workload: `scripts/knows_preflight.py --table DB.SCHEMA.ROLE_HISTORY`.

Example (any two people, live on the engine, 40–70 s; engine must be READY):

```bash
env -u DEBUG .venv/bin/python scripts/guarded_knows_count.py --source-id P19465 --target-id P67052 --execute
```
