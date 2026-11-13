---
status: complete
created: 2026-11-12
feature: corporate-weighted-network
---

# Explainable corporate relationship scores and network structure

User approved the discussed implementation: shared RAI scoring first, then communities/betweenness, then combined agent and visualization. Authorization includes synthetic office/friendship enrichment and updating the new corporate agent; preserve the original corporate careers and older agent.

The connection score is 0.75 * time_score + 0.25 * confirmed_friendship. Effective shared years sum overlap days weighted by office/city proximity and five temporal bands (0–2:1, 2–5:.8, 5–10:.5, 10–15:.25, older:.1). Time score is half career-normalized effective overlap, half squared absolute duration capped at ten effective years. Career denominator is the mean of both people's employed years. Dates are clipped to the requested as-of date; no concurrent interval is double-counted. Unknown friendship means no confirmed bonus, not evidence of no friendship. Remote/unknown location uses explicitly labeled company-only evidence. Pair scores are symmetric and in [0,1].

All score components and graph algorithms execute through PyRel/RAI. Python/SQL may generate synthetic facts, load data, independently validate, and format results. No Python/SQL production score or traversal fallback. Agent-authored PyRel remains audited and invokes native graph reasoning. Default introduction ranking becomes strongest product within the exact two-hop search; fewest-hops mode remains available.

The local graph uses the same model and exposes all score components, individual shared employers, temporal slices, source location facts, friendship provenance, formula contributions, as-of date and scoring version. It supports the separate PE team as well as corporate people. Cache keys include model, source-enrichment version and as-of date.

Structural analytics cover a declared leadership cohort: all PE employees, current CEOs and designated Heads of Data, with all induced scored relationships above a documented threshold. Weighted Louvain runs natively. The installed native betweenness API is unweighted-only, so exact betweenness runs on the thresholded topology and is labeled as unweighted/cohort-specific. No global or weighted-betweenness claim. People outside the cohort have unavailable cohort metrics, not zero centrality. Metrics are separate from relationship scores and include threshold/date/version.

Acceptance: native fixture tests for arithmetic, symmetry, bounds, missing facts, recency boundaries and ranking; exact local/Snowflake enrichment checks; independent score/path oracle against real corporate data; native community/centrality provenance and independent centrality check; all three live agent questions; browser-verified edge decomposition and node analytics; successful type/build checks.

Completion evidence: `artifacts/corporate_affinity_v2_acceptance.json`. All three live question types, 16 returned paths, 7,190 native neighbor edges, ten score scenarios, strongest-versus-shortest behavior, historical scoring, native analytics, browser views, 19 unit tests and the production build are validated. Native communities/centrality retain the explicitly declared 2,100-person scope.


## REJECTED amendment — v3 calibration (superseded below)

Approved by the user's request to defer friendship, retain the other factors with gentler influence, and keep the result neutral rather than overly positive. The prior v2 75/25 composition and product route ranking above are DEPRECATED; their completed evidence is retained.

### REQ-001: Employment-gated, bounded score
WHEN a pair has at least 365 overlapping days at an eligible corporate employer, THE SYSTEM SHALL compute every component in RAI from unioned shared days and complete employed careers. No qualifying overlap SHALL mean no edge. Friendship SHALL neither create edges nor influence scores; its source table SHALL remain available for future work.

Let Y be unioned shared years, C=min(Y/mean employed career years,1), D=Y²/(Y²+9). R is the shared-day-weighted average recency value (0–2 years:1; 2–5:.9; 5–10:.75; 10–15:.6; older:.45). L is the shared-day-weighted workplace evidence value (same onsite office:1; same city/different offices:.8; different/remote/unknown:.5). The score SHALL be D × (.55 + .25R + .15L + .05C). Duration gates all contributions; context is not squared or multiplied in a chain. All four contributions SHALL be exposed separately. Scores are evidence-ranking heuristics, not probabilities or facts of personal acquaintance.

### REQ-002: Restrained calibration
WHEN evaluating controlled examples, THE SYSTEM SHALL place one recent shared year near .10, four recent years in the same office near .60, and four old years at different locations near .45–.50 (20-year careers). Long collaborations SHALL outrank brief ones under comparable conditions; old or remote evidence SHALL score lower than recent onsite evidence. Missing location SHALL not raise a score. Duplicate jobs SHALL not increase overlap or career duration.

### REQ-003: Explainable route prioritization
WHEN ranking introductions through two hops, THE SYSTEM SHALL use the direct edge score for one hop and .85 × min(edge scores) for two hops. The selected route SHALL never exceed its weakest link; minimum hop distance SHALL remain separate from selected route length. All computation SHALL remain in RAI. Friendship-only routes SHALL disappear.

### REQ-004: Consistent release and evidence
The agent, explorer, score explanations, validation oracles and native analytics SHALL use version corporate-affinity-v3. The 2,100-person cohort SHALL be recomputed at threshold .45 with weighted native Louvain and exact unweighted native betweenness. These metrics SHALL remain separate from strength. Earlier snapshots and source careers SHALL remain intact. Acceptance SHALL include native calibration fixtures, real SQL comparisons, all three live agent question types, response wording, and browser verification.


## Approved correction — preserve the original rules (v4)

The user rejected the v3 curve and softened factors because the resulting scores were too high. V3 is superseded, not an accepted release. Restore original location factors 1/.6/.25 and recency factors 1/.8/.5/.25/.1, effective shared years, complete mean career normalization, and squared `min(effective_years/10,1)` duration. Retain original product route ranking. Defer friendship without creating friendship-only edges. The ONLY calibration change from v2 employment is removing its .75 multiplier: `score=.5*career_fraction+.5*duration_component`. Thus every qualifying employment edge is exactly 4/3 of its former employment contribution, with unchanged employment ranking; do not artificially target high scores. Recompute native analytics at .02/.75 to preserve the previous employment threshold. Verify full real neighborhoods against both independent SQL and archived v2 employment components, plus native scoring/routing fixtures, live questions, historical decomposition, UI and native audit logs. Use corporate-affinity-v4.


V4 completion evidence: `artifacts/corporate_affinity_v4_acceptance.json`. All 7,188 real employment edges retain original effective overlap and ordering and equal the saved v2 employment contribution divided by .75. Eleven native scoring scenarios, original product route regression, current/historical decompositions, all three live agent questions (16 displayed paths), parent CALLs/native RAI logs, preserved source tables, and all 2,100 cohort metrics passed. Nineteen unit tests, TypeScript, production build and running viewer APIs passed. V4 browser rendering was not rechecked because Safari was in active use; the viewer serves the corrected version and requires a page refresh to replace previously loaded v3 results.


## Amendment — fixed normalization with preserved raw rules (v5)

### REQ-005: Consistent, monotone normalized scores
WHEN returning or displaying a connection or introduction route, THE SYSTEM SHALL compute `strength = sqrt(sqrt(raw_strength))` in RAI and retain `raw_strength` explicitly. The raw v4 overlap, career normalization, square, spatial/temporal rules and route multiplication SHALL remain unchanged. Normalization SHALL use fixed endpoints 0→0 and 1→1, independent of query result count, selected target, filters, dates, or neighborhood; it SHALL NOT imply probability. The sample raw route .000389969711576 SHALL normalize to approximately .14052633485. This fourth-root mapping is a presentation convention, not an empirically calibrated likelihood.

### REQ-006: Preserved ranking and route semantics
WHEN selecting routes, THE SYSTEM SHALL select using the unchanged raw scores, then expose both raw and normalized strengths through agent-authored PyRel. All strict rankings SHALL be preserved. Normalized product routes SHALL equal the product of normalized legs. Strength thresholds in the agent and viewer SHALL explicitly apply to the normalized scale. Existing source data and raw score explanations SHALL be retained.

### REQ-007: Consistent agent, explorer and analytics
WHEN presenting results, THE SYSTEM SHALL label normalized scores, retain raw scores and complete decomposition, and make the mapping visible. Community detection and betweenness SHALL keep the original raw-weight graph and equivalent raw threshold; published v5 display edges SHALL include both score scales. Tests SHALL compare every saved v4 employment edge/raw component and sampled route, verify normalized scale arithmetic and filtering, exercise all three live Cortex questions and confirm native audit records.


V5 completion evidence: `artifacts/corporate_affinity_v5_acceptance.json`. Native RAI normalization endpoints and 11 scoring scenarios passed; all 7,188 checked real edges retained identical raw components and ranking. The 951 cohort raw edges and all 2,100 degree/betweenness values remained unchanged. All three live Cortex question types returned the same v4 paths/raw scores and correctly labeled normalized table values; SQL oracles, full decomposition, raw/normalized route products, native transaction logs and parent CALLs passed. Current/historical inspector data, normalized filtering, 19 unit tests, TypeScript and production build passed. The local normalization labels and a normalized Cortex Preview table were observed in Safari; complete local edge rendering was not rechecked while the user was actively using Agent Studio. Full browser-observation details and API verification are recorded in the viewer artifact.
