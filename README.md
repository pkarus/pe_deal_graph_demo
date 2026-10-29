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
