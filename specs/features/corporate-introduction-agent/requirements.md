---
status: complete
created: 2026-11-12
feature: corporate-introduction-agent
---

# Corporate PE introduction agent

User authorized deployment and live agent tests. The team is a PE firm with 80–100 employees, historical careers at 3–4 broad-dataset employers, mean tenure about four years, and real dated overlaps with corporate people. Store team data separately.

WHEN a team question is asked, THE SYSTEM SHALL resolve a separate 100-person fictional PE team and its generated historical employment, preserving the original corporate source tables.

WHEN an introduction or pair-connection question is asked, THE AGENT SHALL author a read-only PyRel query, execute it in a Snowflake custom tool against RAI rules and the native graph reasoner, and return connection, target, strength, reasons and hop count. The tool must reject arbitrary Python and never substitute Python/SQL traversal or cached answers.

WHEN paths are computed, THE SYSTEM SHALL find exact direct and two-hop paths using all source/target incident edges, rank shortest paths then strongest product, and state the two-hop search limit. No result within the limit is not proof of global disconnection. Current PE team membership alone must not create a clique.

WHEN a company leader is requested, THE SYSTEM SHALL resolve IDs from source facts. CEOs already exist. Any added head-of-data designation must be an explicit synthetic supplemental fact, with one current Data Analytics leader per company and provenance.

WHEN a query runs, THE SYSTEM SHALL retain the generated PyRel, request ID, runtime hash, native transaction IDs, Snowflake query IDs, outputs and engine state, so the response can be traced to RELATIONALAI.API.TRANSACTIONS, RELATIONALAI.API.ENGINES, and Snowflake query history.

Acceptance: invoke the deployed agent with all three requested question types, validate generated DSL and native execution, compare returned evidence with career records, and include a multi-hop example and an ambiguous/missing-target control.

Validated 2026-11-12 (local date): all three real agent conversations passed under RAI_USER with secondary roles disabled. CEO: 99 starting people within two hops; named pair: 2 hops and strength 0.8521560575 with agent-authored `strength >= 0.8`; synthetic Head of Data: 97 starting people within two hops. All 11 displayed paths matched the independent SQL oracle, including shortest hop count, strongest product, deterministic witness and dated evidence. Native transactions and parent Snowflake CALLs were verified. Missing-company lookup returned no target and invoked no graph query. All 100 team rows and 450 career rows matched local CSVs field-for-field; the original agent specification remained unchanged. Eighteen local tests passed.

Evidence: `artifacts/corporate_agent_acceptance.json`, `artifacts/corporate_pe_team_local_snowflake_match.json`, `artifacts/corporate_agent_preservation_check.json`. Runnable inspection: `sql/corporate_agent_audit.sql`. Native child statements are visible through RAI API transactions; public information-schema history exposes the parent tool CALLs.

## 2026-11-13 amendment — authorized by user

Status: implementing. Supersedes the original two-hop/default-shortest and mandatory boilerplate requirements.

WHEN an introduction is requested, THE SYSTEM SHALL evaluate simple paths of one, two, or three edges in RAI, defaulting to strongest raw product and deterministic fewest-hop/lexical tie breaking. Complete careers and original v5 scores remain unchanged. Both source and target neighbors must be included. All qualifying middle edges must be considered; admissible native score bounds may skip only edges that cannot improve an already-found shorter route. Sources without shorter routes retain full three-hop reachability. No heuristic neighbor cap is permitted.

WHEN answering, THE AGENT SHALL bold the recommended starting person and explain each employment link in natural sentences using names, companies and dates. It SHALL retain normalized strengths, person IDs, request ID and native RAI transaction references. It SHALL show generic limitations and scoring mechanics only when asked; bounded no-result and actual errors remain explicit.

WHEN displaying a limited neighborhood, THE EXPLORER SHALL label it as the strongest N connections and distinguish a minimum-strength filter from the display limit. No scoring recalibration is authorized by the investigation.

Acceptance: native three-edge-only fixture, independent SQL route/evidence checks, three live Cortex question types, payload size with ten three-edge routes, and visible selection labels.

Execution note: the initial unpruned full-team test exceeded the native eight-minute timeout; its retry was canceled. Admissible pruning is implemented entirely in PyRel: first use outer-edge product as an upper bound; then apply the unchanged monotone score formula to summed raw shared time as a tighter middle-edge upper bound. A 1e-12 guard admits borderline candidates to avoid unsafe floating-point pruning. Both stronger-three-hop and three-hop-only native fixtures pass. Full-team validation remains in progress.

Deployment status: three-hop rollout deferred after full-team timeouts. The active runtime was restored to the validated two-hop implementation; natural response wording and score-selection clarity are retained. Experimental code and evidence are preserved separately. This amendment is not marked complete.

Presentation acceptance: live Cortex request `4d7a00c0-5027-4e1c-8d17-2d3321cfd79f` returned natural dated employment explanations, bold starting names, no generic limits boilerplate, and the request/native transaction references. Its five paths and scores are unchanged from v5 and passed the independent Snowflake SQL route oracle plus every per-edge component check. Evidence: `artifacts/corporate_presentation_acceptance.json`. Explorer selection labels passed TypeScript, production build and served-page checks. A temporary medium-engine three-hop benchmark is prepared separately and awaits explicit paid-compute approval; it has not run.
