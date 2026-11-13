---
status: complete
created: 2026-11-12
feature: corporate-graph-explorer
---

# Corporate people graph explorer

Authorization: copy the specified local PyRel explorer into this repository; use the new corporate dataset and build its graph. The user explicitly requires RAI graph calculations and logic rules for neighborhoods. Existing Snowflake data and agent inputs must remain intact.

## REQ-001: Local interface

WHEN the explorer starts, THE SYSTEM SHALL display the corporate people graph using the copied Next.js/Cytoscape interface, with person search, career history, relationship evidence, and click-to-recenter exploration.

## REQ-002: RAI computation

WHEN a neighborhood is requested, THE SYSTEM SHALL derive K1 employment-overlap relationships in PyRel and execute native RAI graph distance on the incident graph, SO THAT neither Python nor browser code calculates connectivity.

- One-hop neighborhoods are computed against all career records; no sampling before rule evaluation.
- Use the existing K1 rule: at least 365 days overlap, open employment ending at 2026-10-01, tenure strength with existing recency factors, strongest evidence per pair.
- The graph is undirected. Display shared-employment inference, not confirmed personal acquaintance.
- Display limits apply after RAI calculation; show total versus displayed neighbors.
- Compute each requested incident graph on demand instead of materializing billions of global pairs. Do not claim a full global graph export or multi-hop computation.
- No SQL/Python/NetworkX fallback for relationship derivation or neighborhood calculation. Source lookup and display formatting may use SQL/Python.

## REQ-003: Isolation and provenance

WHEN source data is loaded, THE SYSTEM SHALL create a dedicated corporate source schema, validate row counts and career statistics, and preserve existing schemas and agent definitions. Keep credentials on the server. Bind local services to loopback.

## Validation

- Verify overlap intervals, open jobs, recency, self-edge rejection and duplicate pair aggregation against an independent full-source CSV oracle.
- Execute an actual corporate RAI neighborhood and retain evidence of the algorithm, source schema and results.
- Build the UI and exercise search, neighborhood and career display through the local app.

## Completed evidence

- Copied 50 upstream files, preserving the original README and source directory.
- All 17 tables loaded into `ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CORPORATE_1M_SRC`; exact manifest counts and career statistics validated.
- Native RAI job `01c85f21-040d-33b7-0005-5ee3146d50be`: 4,859 neighbors for `CORP_P000002008`; all IDs, strengths, overlap dates/days, native counts, and evidence multiplicity match an independent full-CSV oracle.
- Native RAI job `01c85f24-040d-3184-0005-5ee3146d6322`: 8,009 neighbors / 8,014 strongest witnesses for `CORP_P000000373`, with the same complete oracle checks passing.
- Minimum strength 0.8 returns 1,624 neighbors for the default person; matches the independently validated full result.
- Next.js production build and targeted lint pass. Source lookup, timeline, browser proxy, graph rendering, and Safari display checked.
- Startup script and operator instructions are in `pyrel_semantic_graph_explorer/`.

