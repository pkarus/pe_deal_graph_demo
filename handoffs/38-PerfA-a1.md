# 38-PerfA-a1 - Performance Scout A (relationalai latest vs 1.27.1)

## Status

PASS (scout scope). relationalai **1.36.0** (PyPI latest, released 2026-10-20) runs this repo with **zero source changes**: `scripts/check_rules.py --graphs --finale` = 67 pass / 0 fail, and every hero function returns byte-identical output to 1.27.1 (same sha256 per function). It is **not measurably faster**: warm calls are within noise except q_path (25 s vs 45 s, one sample each), cold calls are mixed. Recommendation: **UPGRADE LATER** (after the demo), not today. `pytest tests/test_hero.py` = 44 passed / 0 failed (368.6 s) and `scripts/check_graphs.py` = 48 pass / 0 fail (164 s), both on 1.36.0 against the copy model.

Nothing in the main repo, its .venv, raiconfig.yaml or uv.lock was modified. All work was done in /private/tmp/pe_perf_a/ against the RAI model `pe_deal_graph_perf_a` (main model `pe_deal_graph` never touched). Only engine used: pe_demo_logic. No new engine, no DDL.

## What I built (paths)

- /private/tmp/pe_perf_a/ - rsync copy (no .venv, no .git) plus a plain copy of raiconfig.yaml; a throwaway local git repo for diffs (raiconfig.yaml is gitignored there too).
- /private/tmp/pe_perf_a/.venv - Python 3.13.13, relationalai 1.36.0 (lqp 0.5.7, snowflake-connector 4.8.0, snowpark 1.55.2), via `uv sync`.
- /private/tmp/pe_perf_a/perf_out/time_hero.py - timing harness: one fresh process per hero fn, call 1 = cold, call 2 = warm, sha256 of the result CSV, 60 s retry on lock/503.
- /private/tmp/pe_perf_a/perf_out/{timings.jsonl,timings_new.log,timings_old.log,new_check_rules.log,new_pytest.log,new_check_graphs.log}
- /private/tmp/pe_perf_a_notes/*.txt - stripped release notes 1.28.0-1.36.0 from docs.relational.ai.

## How to verify (exact commands)

```
cd /private/tmp/pe_perf_a
.venv/bin/python -c "import relationalai; print(relationalai.__version__)"        # 1.36.0
.venv/bin/python scripts/check_rules.py --graphs --finale                          # SUMMARY: 67 pass, 0 fail
.venv/bin/python -m pytest tests/test_hero.py -q -p no:cacheprovider
.venv/bin/python scripts/check_graphs.py
perf_out/run_timings.sh .venv/bin/python new-1.36.0
perf_out/run_timings.sh /Users/piotrkraus/rai-repos/pe_deal_graph_demo/.venv/bin/python old-1.27.1   # read-only use of the main venv
```

## Diff to apply (upgrade = dependency pin only)

```diff
--- a/pyproject.toml
+++ b/pyproject.toml
@@ dependencies = [
-    "relationalai==1.27.1",
+    "relationalai==1.36.0",
 ]
```
then `uv lock && uv sync`. uv.lock changes (69+/215-): relationalai 1.27.1 -> 1.36.0; sqlglot 30.24.0 -> 28.10.1 (downgrade, pinned by relationalai); zstandard 0.25.0 added (request compression, 1.35.3); fastapi, starlette, uvicorn, uvloop, httptools, watchfiles, annotated-doc and opentelemetry-{api,sdk,semantic-conventions} removed (OpenTelemetry became an optional extra in 1.33.0). lqp unchanged at 0.5.7.

Harness-only change in the copy (NOT part of the upgrade): `pe_deal_graph/model/core.py` line 45 `Model("pe_deal_graph")` -> `Model(os.environ.get("PERF_MODEL", "pe_deal_graph_perf_a"))`, to keep off the main model.

No code fix was needed: nothing broke.

## Latency (same data, same model `pe_deal_graph_perf_a`, engine pe_demo_logic shared with another agent's tests)

Cold = first call in a fresh Python process (includes local compile + model install/sync); warm = second call in the same process. One sample per cell; 1.36.0 ran 11:44-11:54, 1.27.1 ran 11:54-12:04. Output sha256 identical between versions for every fn.

| Hero fn | 1.27.1 cold | 1.36.0 cold | 1.27.1 warm | 1.36.0 warm | R20 baseline (1.27.1, main model) first / ready |
|---|---|---|---|---|---|
| q_score | 88.0 | 114.7 | 17.5 | 10.2 | 64.2 / 10.8 |
| q_path | 101.7 | 105.1 | 45.3 | 25.2 | 46.5 / 38.8 |
| q_flow | 66.1 | 63.6 | 22.9 | 23.8 | 20.8 / 24.6 |
| q_conflict | 79.6 | 69.6 | 28.1 | 25.8 | 27.0 / 28.8 |
| finale_rescore | 115.8 | 109.1 | 14.2 | 19.1 | 67.7 / 13.5 |
| **sum** | 451.2 | 462.1 | 128.0 | 104.1 | |

Reading: cold sum is flat (+2%), warm sum is 19% lower on 1.36.0 but almost all of that is q_path (-20 s) and q_score (-7 s) against finale (+5 s); with one sample each under engine contention this is inside the noise band seen in R20 (q_flow/q_conflict "ready" was slower than "first" there). The cold numbers are higher than R20's because this model name was new to the engine (the first ever query on 1.36.0, inside check_rules, spent 226 s on "Initializing data index"; the full check_rules took 881 s). Warm cost is dominated by engine round trips (5-12 per hero fn), which a client upgrade does not change.

## Breaking / relevant changes 1.27.1 -> 1.36.0 (from release notes + installed source)

- **Compiler**: default is still `reasoners.logic.lqp.compiler = legacy` in 1.36.0 (config_reasoners_fields.py, `RAI_LQP_COMPILER` override unchanged). 1.36.0 only fixes some `direct`-compiler filter cases. Our "stay on legacy" rule holds.
- **filter_by vs lookup**: `filter_by` still works and still emits the same DeprecationWarning ("use .lookup(...)"); not removed. core.py has 50 `filter_by(` calls; no change needed now.
- **string_join**: 1.36.0's legacy LQP translator now has `_translate_string_join` (1.27.1 asserted "only support (sum,count,avg,min,max)"). Cheatsheet trap 13.3 is probably lifted on 1.36.0, UNVERIFIED on the engine (no test run). Ordering semantics must be checked before relying on it (cheatsheet 13.11 saw unexpected order on `direct`).
- **rank / aggregates**: "Mixed orderings in rank/cumsum are not supported yet" still raised in 1.36.0 (trap 13.4 holds; keep `asc(0 - x)`). 1.36.0 rank fixes (ties share a rank, 10,10,20 -> 1,1,2) are stated for deployed/Snowflake-SQL models only; our ranks end with a unique key so ties cannot occur anyway, and check_rules ranks matched golden. New aggregates: geometric_mean (1.30.4), variance (1.31.0), percentile/median (1.32.0) - would replace our rank/count decile workaround, optional. 1.30.3 fixed "aggregate ignored a union filter / unary relationship in where()" and "aggregate over a cycle of relationships could fail to complete" (relevant to Knows); our results were unchanged.
- **Graph API**: no public method changes (diff of `def` names in reasoners/graph shows only two internal helpers added). distance/jaccard/louvain/betweenness/pagerank outputs identical. 1.29.0 made `path()` compile faster (we do not use `path()`). 1.35.2/1.36.0 graph changes are deployment-output naming only.
- **Data streams**: no breaking change found for `wait_for_stream_sync`/`model.Table`; 1.35.3 compresses Logic Reasoner requests (zstandard). Streams on the new model name were created and synced without action.
- **Deployment**: large churn 1.28-1.36 (op log on by default from 1.28.0, `_INTERNAL_` object names, views instead of tables, standalone properties as tables in 1.34.0, privilege pre-checks). We do not deploy (deployment: block stays commented out per R01 a3), so none applies; if anyone re-enables `deployment:` the behavior is very different from 1.27.1.
- **Concurrency**: 1.33.0 fixes concurrent queries on one model from multiple threads (Unground Variable / empty / hang). Relevant only if ask.py's server ever runs queries in parallel.
- **Other**: Python 3.14 support (1.33.0); 1.30.4 `select()` of a single literal function call now returns a null row instead of none (we do not do this); prescriptive breaking changes (1.29.0, 1.32.0, 1.36.0) do not apply (no prescriptive).
- 1.36.0 progress output is far more verbose (live "Evaluating relations: n / m" lines); ask.py swallows RAI progress, but any script that tees stdout will get large logs (check_rules log was 1 MB).

## Decisions and assumptions

- Used the same copy model name for both versions so data and installed state are shared; 1.36.0 ran first (it also paid the one-time model init inside check_rules), 1.27.1 second. Each version's cold call therefore includes re-installing its own compiled rules.
- One timing sample per cell because of the 45-minute budget and the engine being shared with another agent's tests.
- PerfA lines appended to DECISIONS.md.

## Known issues

- MINOR: timings are single samples under contention; the q_path warm gain (45 -> 25 s) is the only signal worth re-measuring, with 3 samples per version on an idle engine, after the demo.
- MINOR: models `pe_deal_graph_perf_a` now exists on pe_demo_logic (engine-side state only, no Snowflake DDL). It can be left or deleted later; it does not touch `pe_deal_graph`.
- INFO: 1.36.0 does not lift the legacy limits we work around except possibly string_join (unverified).

## What the next agent must know

- RECOMMENDATION: **UPGRADE LATER**. 1.36.0 is a drop-in replacement (pin-only diff above, 0 code changes, identical answers), but it gives no reliable speed-up, and switching the client on demo day (hard stop 14:00) invalidates the warm/rehearsal evidence and the R20 latency numbers for no gain. Re-evaluate after the demo: apply the pin, `uv sync`, run `make test` twice + `make warm`, then try `aggs.string_join` on legacy.
- Do not expect a client upgrade to fix latency: warm time is 5-12 engine round trips per fn; reducing round trips in queries.py (fewer separate `to_df()` calls per hero fn) is the lever, not the package version.

## Late results (1.36.0, copy model, 12:05-12:13)

- `pytest tests/test_hero.py -q -p no:cacheprovider`: 44 passed, 61 warnings (filter_by DeprecationWarnings), 368.57 s.
- `scripts/check_graphs.py`: GRAPH CHECK PASS: 48 pass, 0 fail (164 s).
- `scripts/check_rules.py --graphs --finale`: SUMMARY: 67 pass, 0 fail (881 s, includes first-ever model init).
