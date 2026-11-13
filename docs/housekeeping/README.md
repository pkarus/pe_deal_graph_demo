# Housekeeping — November 12, 2026

Scope: local changes only in `pe_deal_graph_demo-main-2`; no intentional edits to the separate general-demo `main` folder. Snowflake changes only in `ALAA_RELAPP_PERSISTENCE`, plus explicitly authorized RAI service operations for this workspace's source streams. No graph feature development or new scale run was performed.

## Local result

Removed large generated 100K/1M/10M CSV copies, six bulky exported result dumps, old build traces, browser/tool caches used to generate the field guide, the repository installation cache, and duplicate historical planning files. Approximately 12.54 GB and 34,000 files removed net. Kept the generator and scale manifests instead of keeping the generated datasets.

About 500 files remain outside `.venv/` and `repositories/`. The remaining tens of thousands of files are installed Python dependencies and source/tool checkouts, not tens of thousands of demo experiments. Those installations were not removed. Demo-maker still launches. Source repositories, user configuration, onboarding documents, compact benchmark records, and the latest main-2 debugger trace remain.

Small 10K connected and sparse regression fixtures remain because the local test suite uses them. A test exposed the sparse dependency after deletion; both its small base and derived fixture were regenerated. The two local test files produced 33 passes and one initial failure; the failing test passed after restoration. No claim is made that the whole repository test suite was run.

118 exact duplicate files were removed from the Nov 5 backup; 16 unique historical source/test versions remain. Automatic approval review blocked deletion of the whole backup because unique work had not been established as disposable. No unique backup file was deleted.

## Snowflake result

Removed 15 obsolete graph schemas, 498 tables/views, seven legacy procedures, and the old `PE_GRAPH_ASSISTANT` precomputed-answer agent. The tables reported 3,096,407,919 bytes of active storage before deletion; this is not a claim of immediate billed-storage reduction because retention can outlive a drop. The database now has 383 tables/views, including unrelated applications that were deliberately preserved.

Retired groups:
- All four remaining `CONNECTED_100K` schemas.
- `DEPLOY`, `DEPLOY_META`, `DEPLOY_PATHS`, `DEPLOY_SRC`.
- `COMMUNITY`, `COMMUNITY_META`, `TARGETS`, `TARGETS_META`.
- `INTRO_APP`, `INTRO_APP_META`.
- The unused `CONNECTED_10M_PATHS` SQL graph copy.

All names above are prefixed `PE_DEAL_GRAPH_EXPERIMENT_` in the authorized database. The removal logs include exact identifiers and Snowflake query IDs. Compressed DDL records preserve definitions only, not bulky data backups. Associated RAI data streams were removed before their source schemas.

## What remains and why

- `CONNECTED_1M` and its source/model metadata: current enriched introduction inputs. `CONNECTED_1M_PATHS` remains because the current contact view depends on it.
- `CONNECTED_1M_INTRO_TEST`: current agent, enrichment tables, five serving procedures, and separately dated community output.
- `CONNECTED_2M`: inputs still accepted by the deployed scale procedure.
- `CONNECTED_10M`, source and model metadata: largest validated graph inputs and their regeneration definitions. The duplicate SQL path schema was removed.
- Base PE data, lab/backorder applications, and unrelated model-management schemas: preserved.

Current introduction procedures: `FIND_CONNECTION`, `FIND_CONNECTION_AT_SCALE`, `SEARCH_PEOPLE`, `PERSON_CONTACTS`, `PERSON_COMMUNITY`. Route requests use native RAI on demand. Community output is still a retained analytical table; converting that behavior is future graph work, not a result of this cleanup.

Verification: current person, employment-attribute, and contact-edge views query successfully; `PERSON_COMMUNITY_NATIVE` has 1,000,000 rows; all remaining tasks are suspended. No expensive new RAI route computation was run for housekeeping. Live view/procedure/function definitions and graph agent specifications were checked for dependencies before drops; this does not establish the absence of unknown external callers.

## Resume rules

Do not run the historical README/Makefile deployment commands to recreate retired experiments. Keep the focus on target-specific native RAI queries when graph work resumes. Generated scale CSVs and repeated result dumps should be temporary; retain parameters, compact correctness results, and one useful diagnostic trace.

See `summary.json`, `local_cleanup.json`, `historical_cleanup.json`, `snowflake_cleanup.json`, and `route_cleanup.json` for the measured inventory and exact actions. `stage_cleanup.json`, when present, records removal of obsolete runtime archives after checking Python imports.
