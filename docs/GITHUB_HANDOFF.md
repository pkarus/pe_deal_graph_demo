# GitHub handoff

Prepared locally on November 13, 2026. This snapshot is a file tree, not a Git checkout. No branch, commit, remote, push or deployment was created for this preparation. The source working folder and running services were left intact.

## Branch preparation

Suggested branch name: `feat/corporate-rai-introductions`.

When a push is authorized, start from a normal clone of the intended existing GitHub repository so its history is preserved. Create the branch there and merge the contents of this prepared folder into that checkout. Review the diff before staging. Do not copy the surrounding preparation reports or use a destructive directory synchronization. The repository URL and base branch have not been assumed.

## Deployment scope

The active package supports one- and two-hop introductions. The three-hop package is preserved under `experiments/three_hop_agent/` and remains unvalidated for full-team performance. Its paid-compute benchmark requires separate explicit authorization and was not run during preparation.

Account-specific resource names remain in `corporate_agent/scoring.py`, `corporate_agent/runtime.py`, validation scripts and audit SQL. `corporate_agent/setup.py` and deployment code derive additional resources from these settings. The example connection file uses placeholders; replacing it alone does not retarget every corporate resource. Review these names before a deployment to another account. Historical validation records intentionally retain their transaction IDs, engine names and original account object identifiers for traceability.

This preparation does not redeploy the agent, regenerate analytics or change the score formula. Current presentation evidence is `artifacts/corporate_presentation_acceptance.json`; older v5 evidence predates the presentation-only change and retains its own runtime hash.

## Data regeneration

Large generated corporate and enrichment CSVs are omitted. Their Python generators, original manifests and small PE/regression fixtures are included.

1. Generate and check `data/corporate_1m_1000_companies/` using the commands in the root README. The destination must not already exist.
2. Keep the included `data/pe_team_100/` fixture unless intentionally regenerating the PE team.
3. To regenerate enrichment, first move the manifest-only `data/corporate_enrichment_v2/` folder outside the checkout. Read `data/corporate_enrichment.py` and run its generation path after the corporate and PE inputs exist. This is a separate operation from loading Snowflake.
4. Compare the new manifest with the retained one before loading or using it for a cache fingerprint. Generation and loading were not performed for this handoff.

The existing Snowflake-backed explorer can use the included enrichment manifest without local large CSVs, provided its configured account has the matching tables.

## Included evidence

The artifacts directory contains an explicit subset of existing validation JSON, native transaction references, small native fixtures and the baseline offline explorer assets needed by tests. Logs, debugger archives, deployment zip files, screenshots, runtime caches and most obsolete run records are omitted. Missing historical evidence paths in old documents refer to the original working folder; the handoff does not claim to contain every historical artifact.

`LEGACY_README.md`, historical runbooks and cleanup reports are preserved as history. The root README and `corporate_agent/README.md` describe the active implementation. Generic upstream explorer documentation is retained in `pyrel_semantic_graph_explorer/UPSTREAM_README.md`.
