# Corporate employment fixture

The user requested approximately 1,000 large companies and careers spanning 1–6 distinct companies, with average tenure around four years. The generator produces one million people by default and only writes local files. A subsequent authorized graph-explorer task loaded this fixture into its own Snowflake schema. It is a synthetic large-corporation model, not a reconstruction of actual Fortune companies or a statistically fitted labor-market dataset.

## Generate and check

```bash
.venv/bin/python data/generate.py --corporate --people 1000000 --companies 1000 --seed 42 --out data/corporate_1m_1000_companies
.venv/bin/python data/generate.py --corporate-check --out data/corporate_1m_1000_companies
```

Use a new destination for every run. `--people`, `--companies`, and `--seed` support smaller tests; at least six companies and two people per company are required. No command in this workflow opens a Snowflake or RAI session.

## Population and careers

- Exactly 1,000 companies and 1,000,000 people at the default size.
- Eleven industry groups with three-level sector references and headquarters across US states/DC; companies also have multiple operating locations.
- Uneven simulated enterprise sizes, public/private flags, sector-dependent revenue and margins, and varied founding years.
- Each company has a designated current CEO and CFO whose career history spans at least 15 years.
- Each person has 1–6 distinct employers, one current job, chronological employment records, possible gaps between jobs, and no overlapping primary employment. Career spans are at most 42 years.
- Employer-count weights are 12%, 18%, 24%, 22%, 15%, and 9% for 1–6 employers. The expected nonexecutive mean is 3.37; the realized mean is measured from the output.
- Tenures are variable, with a discrete gamma-like distribution calibrated around 48 months, plus day-level variation. Current employment has a blank end date; its elapsed tenure is measured through the fixed as-of date, October 1, 2026. Career-span and executive-experience constraints slightly change the realized distribution.
- Historical employer selection favors the current employer's industry but permits moves to other industries. No employment starts before a company's founding year.
- Company `employees` represents simulated total enterprise headcount. The one-million-person dataset represents tracked professionals within those workforces, rather than an exhaustive census of every employee. The validator checks that current tracked employees never exceed company headcount.
- Names and IDs are fictional. Person IDs are unique; names may repeat, as in real enterprise data.

## Files and compatibility

The directory contains the same 17 source-table CSV layouts as `data/schema.sql`, plus `MANIFEST.json` and `VALIDATION.json`. The populated tables are `PERSON`, `COMPANY`, `ROLE_HISTORY`, `COMPANY_SITE`, `SECTOR`, and `REGION`. The PE fund, sponsor, ownership, deal, CRM, pipeline, signal, and commercial-link tables have headers but no data: this fixture generates corporate employment, not the original planted PE stories.

The dedicated `scripts/load_corporate_explorer.py` loader creates `<DATABASE>.<BASE_SCHEMA>_CORPORATE_1M_SRC` and refuses an existing schema. All 17 tables were loaded and validated on November 12, 2026. The existing Snowflake datasets and Cortex agent are unchanged. The local [graph explorer](../pyrel_semantic_graph_explorer/README.md) uses the new schema.

## Validation and RAI

The subsequent explorer uses `pe_deal_graph/corporate_graph.py`: scoped K1 rules followed by native RAI `Graph.distance`. One-hop incident graphs are calculated on demand across the full source fixture; display caps are applied afterwards. This avoids materializing the entire global pair join. See the explorer README for live validation and scope.

`--corporate-check` rereads every CSV, verifies SHA-256 hashes and headers, and checks counts, primary keys, foreign references, company financials and sites, career ordering, distinct employers, current jobs, employer founding dates, headcount bounds, and measured tenure. Full-scale mean observed tenure must be within 0.10 years of four years; small fixtures allow sampling tolerance.

The report distinguishes completed-job tenure from elapsed current-job tenure. It also records the distribution of employer counts, current employees per company, industry/HQ coverage, and all table counts.

No person-to-person graph is generated in Python. RAI remains responsible for graph construction and algorithms. The existing K1 rule joins people with overlapping employment at the same organization. At large employers this can imply unrealistic acquaintance and many billions of candidate role pairs. Validation reports the exact candidate-pair workload, `sum(n*(n-1)/2)` across employer role counts, without materializing edges. It is not a unique-edge count or an RAI performance measurement. Team, location, project, or other relationship evidence should be considered before deploying that rule against this fixture; no graph rule is changed by generation.
