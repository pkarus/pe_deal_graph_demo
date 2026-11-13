---
status: complete
created: 2026-11-12
feature: corporate-careers
---

# Corporate career dataset

Authorization: the user requested regeneration and explicitly chose “Generate and validate first; keep current Snowflake data.” This scope includes local implementation, generation, and validation.

## REQ-001: Population

WHEN corporate generation is requested, THE SYSTEM SHALL produce 1,000,000 fictional people and 1,000 fictional large companies by default, SO THAT the employer population resembles a large-corporation universe instead of thousands of tiny workplaces.

- Exact default counts; configurable smaller fixtures for testing.
- Varied industry groups, US headquarters, company sizes, financials, names, and founding years.
- These are synthetic assumptions, not records of actual Fortune-ranked companies.

## REQ-002: Careers

WHEN a person is generated, THE SYSTEM SHALL assign 1–6 distinct company employers, chronological non-overlapping employment intervals, and one current job, SO THAT career changes are represented consistently.

- Employer-count probabilities: 12%, 18%, 24%, 22%, 15%, 9% for 1–6 employers; expected mean 3.37.
- Mean observed tenure approximately four years across employment records (within 0.10 years at full scale); open jobs end at the fixed model date for this calculation.
- Variable tenure, employment gaps, industry-biased moves, career progression, and career spans no greater than 42 years.
- No job begins before the employer's founding year.
- One designated current CEO and CFO per company with at least 15 years of career history.

## REQ-003: Compatibility and validation

WHEN files are written, THE SYSTEM SHALL preserve the existing 17 source-table column layouts and emit counts, SHA-256 hashes, assumptions, and an independently recomputed validation report.

- CSV validation checks identifiers, uniqueness, references, dates, career/employer counts, current jobs, company coverage, headcount bounds, and measured tenure.
- Company employees represent simulated total enterprise headcount; the one million tracked professionals form a sample of that workforce.
- Unrequested PE deal/CRM/fund data remain explicitly empty; this fixture targets corporate employment, not the original planted PE stories.
- Report the existing RAI co-employment rule's candidate-pair workload without materializing graph edges or running graph algorithms.

## REQ-004: Isolation

WHEN generation or validation runs, THE SYSTEM SHALL write only a new local output directory and local evidence, SO THAT existing datasets, Snowflake objects, RAI deployments, and agent inputs remain unchanged.

- Refuse existing output directories and protected baseline/golden paths.
- Fixed seed and as-of date; reproducible files.
- No Snowflake or RAI connection is opened by this workflow.

## Acceptance

- [x] Generator and meaningful regression tests pass: 29 tests.
- [x] Complete one-million-person fixture generated: 1,000 companies and 3,371,598 employment records.
- [x] Full streaming validation passes: 1–6 distinct employers, mean 3.371598; mean observed tenure 4.032468 years.
- [x] Existing small fixture hashes are unchanged: 74 files verified.

## Implementation

Add a separate corporate mode to `data/generate.py`, implemented in `data/corporate.py`; add tests in `tests/test_corporate_generator.py`. Preserve existing scale modes. Generate into `data/corporate_1m_1000_companies/`. Large generated CSVs are ignored by version control; retain code, specification, and compact validation evidence.

## Result

The full 423,113,825-byte CSV dataset passed validation. It covers 11 industry groups and all 50 states plus DC, with 170–5,015 tracked current employees per company and one current CEO/CFO per company. The existing employer-only RAI rule has 10,431,461,163 candidate role pairs before date filtering. No graph edges were generated, and neither Snowflake nor the agent was changed. Evidence: `artifacts/corporate_1m_1000_companies_VALIDATION.json` and `artifacts/corporate_generation_verification_20261112.json`.
