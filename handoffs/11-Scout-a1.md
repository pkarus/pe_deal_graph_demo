# 11-Scout-a1 - PyRel API Scout (R10 support)

## Status

PASS. All 12 idioms ran on the live engine pe_demo_logic with relationalai 1.27.1 and the default legacy LQP compiler. Two full runs, in separate processes, gave identical outputs (`diff -r` clean). Exact betweenness and pagerank match networkx. The SCOUT_* tables are dropped (`SHOW TABLES LIKE 'SCOUT%'` returns no data).

## What I built (paths)

- /Users/piotrkraus/rai-repos/pe_deal_graph_demo/research/pyrel_cheatsheet.md is the deliverable: 316 lines of verified snippets, their outputs, timings, a do-not-do list and the skill-vs-package table.
- /Users/piotrkraus/rai-repos/pe_deal_graph_demo/scripts/scout/scout_tables.py creates or drops 6 toy tables. Their types mirror data/schema.sql: VARCHAR ids, NUMBER(10,2), NUMBER(1), BOOLEAN and nullable DATE.
- /Users/piotrkraus/rai-repos/pe_deal_graph_demo/scripts/scout/scout_model.py is the toy model plus the query harness.
- /Users/piotrkraus/rai-repos/pe_deal_graph_demo/scripts/scout/probe_inline.py probes inline-data nulls, string_join and mixed rank on both compilers.
- /Users/piotrkraus/rai-repos/pe_deal_graph_demo/scripts/scout/out/run1/, run2/ hold CSV outputs plus `_timings.csv`. run1.log and run2.log are the full logs. The dev1, dev2 and dev3 folders are stale iterations: the harness denied `rm`, so delete them later or ignore them.
- DECISIONS.md: 8 Scout lines appended.

## How to verify (exact commands)

```
cd /Users/piotrkraus/rai-repos/pe_deal_graph_demo
.venv/bin/python scripts/scout/scout_tables.py create
.venv/bin/python scripts/scout/scout_model.py run1 && .venv/bin/python scripts/scout/scout_model.py run2   # ~2.5 min each
diff -r -x _timings.csv scripts/scout/out/run1 scripts/scout/out/run2 && echo IDENTICAL
.venv/bin/python scripts/scout/probe_inline.py; RAI_LQP_COMPILER=direct .venv/bin/python scripts/scout/probe_inline.py
.venv/bin/python scripts/scout/scout_tables.py drop
```

## Decisions and assumptions

- The package wins over the skills. Conflicts are in cheatsheet section 14 and DECISIONS.md.
- I stayed on the legacy compiler (the default). `direct` is a dev escape hatch with different semantics.
- ">= 12 months" was tested as `>= 365` days of overlap.
- K1 strength (min(1, years/4), halved when the overlap ended more than 10 years ago), K3 (0.4 + 0.2n) and K2 (0.7) are toy formulas. Only the idioms carry over; R09 uses the QUESTIONS.md formulas.

## Known issues

- MAJOR for R09: `X.q | default` inside define silently yields nothing when X.q is missing, and `aggs.string_join` does not compile. Use the two-rule `not_()` default and per-component strings (cheatsheet sections 3, 6 and 13).
- MAJOR for R09/R11: mixed asc/desc orderings in `rank`/`limit` are rejected. Negate the numeric keys. Ties need a unique final key.
- MAJOR for anyone using inline `model.data()` (tests, focus lists, finale data): a row with any `""` or None cell vanishes. Snowflake tables are fine.
- MINOR: `filter_by` is deprecated in favor of `lookup`. The verified snippets still use `filter_by`. `lookup` is untested on the engine.
- MINOR: RAI data streams created for the 6 dropped SCOUT_* tables may linger in the RAI app. No CLI command exists to list or delete them in 1.27.1, and I did not touch the app.
- INFO: the first graph query costs about 54 s, and the first query of a process about 21 s (44-72 s when new tables are being streamed). `make warm` should run one graph query.

## What the next agent must know

- R08: subtypes via `extends=[Organization]`, with `Company.new(org_id=...)`, work. Polymorphic FKs resolve through `Organization.filter_by(org_id=...)`. Bind nullable columns in their own `define`. For a self-FK (Sector parent), use two `.ref()`s.
- R09: copy cheatsheet sections 2-6. The recursion needs no special syntax. Tenure overlap is the four-way `math.minimum` of `period_days`. Use `dt.date(2026, 10, 1)` for AS_OF.
- R10: `distance(from_=unary_rel)` twice, plus the identity join, works. Unreachable pairs have no row. Jaccard omits zero pairs. Use `betweenness_centrality(num_pivots >= num_nodes())`: it is exact and matches `nx.betweenness_centrality(normalized=False)`. Louvain is seeded and stable.
- R11: sort every DataFrame in pandas before comparing. `select` returns NaN for missing properties rather than dropping the row.
