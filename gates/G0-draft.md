# G0 Environment - DRAFT preflight evidence (R01 a1 pre-approval; a2 BLOCKED; a3 bootstrap verified, engine READY, smoke PASS)

Collected 2026-10-21T22:12+02:00 by R01. Bootstrap NOT applied. Engine NOT created. Smoke test NOT run.
The Gatekeeper (R18) re-runs everything and writes gates/G0.md after the bootstrap is approved and applied.

## Checks

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 1 | Python (system) | `python3 --version` | Python 3.9.6 (too old for relationalai, which needs 3.10+) | info |
| 2 | Python (venv) | `.venv/bin/python --version` | Python 3.13.13 (uv-managed) | PASS |
| 3 | uv | `uv --version` | uv 0.11.11 | PASS |
| 4 | relationalai importable | `.venv/bin/python -c "import importlib.metadata as m; print(m.version('relationalai'))"` | 1.27.1 (pinned in pyproject.toml + uv.lock; PyPI latest is 1.36.0) | PASS |
| 5 | raiconfig parses | `.venv/bin/python -c "from relationalai.config import create_config; create_config()"` | OK | PASS |
| 6 | rai CLI from venv | `.venv/bin/rai --version` | rai 1.27.1 | PASS |
| 7 | snow CLI | `snow --version` | Snowflake CLI version: 3.16.0 | PASS |
| 8 | snow connection non-interactive | `snow connection list` (non-secret fields only) | `rai`: account ajb85638, authenticator PROGRAMMATIC_ACCESS_TOKEN, default role ACCOUNTADMIN | PASS |
| 9 | identity | `snow sql -c rai -q "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_ACCOUNT(), CURRENT_REGION()"` | `piotr.kraus@relational.ai`, ACCOUNTADMIN, AJB85638, AWS_US_WEST_2 | PASS |
| 10 | admin roles usable | `SHOW GRANTS TO USER "piotr.kraus@relational.ai"`; `SHOW GRANTS OF ROLE SECURITYADMIN`; `SHOW GRANTS OF ROLE SYSADMIN` | user holds ACCOUNTADMIN; SECURITYADMIN and SYSADMIN are both granted to ACCOUNTADMIN; SYSADMIN has CREATE WAREHOUSE / CREATE DATABASE | PASS |
| 11 | RAI Native App | `SHOW APPLICATIONS LIKE 'RELATIONALAI'` | RELATIONALAI, version V4, label 2026.10.10-d139e47, patch 106, upgrade_state COMPLETE, owner ACCOUNTADMIN | PASS |
| 12 | RAI app roles | `SHOW APPLICATION ROLES IN APPLICATION RELATIONALAI` | 26 roles incl. RAI_USER, APP_USER, ENG_USER, ENG_ADMIN, CDC_ADMIN, ALL_SCHEMA_CDC, OBSERVABILITY_VIEWER | PASS |
| 13 | engine pe_demo_logic | `SELECT ... FROM RELATIONALAI.API.REASONERS WHERE NAME ILIKE '%pe_demo%'` | 0 rows: does not exist yet (85 reasoners in the account in total) | info |
| 14 | target objects absent | `SHOW ROLES LIKE 'RAI_DEMO_PE'; SHOW WAREHOUSES LIKE 'RAI_DEMO_PE_WH'; SHOW DATABASES LIKE 'RAI_DEMO_PE_DEALS'` | all empty | info |
| 15 | rai connect (pre-bootstrap) | `.venv/bin/rai connect` | PAT auth reaches Snowflake; fails only with "Role 'RAI_DEMO_PE' ... does not exist or not authorized" (expected until bootstrap) | expected FAIL |
| 16 | Claude Code RAI skills | `claude -p "List the skills you have whose names start with rai-..."` | 15 skills: rai-build-starter-ontology, rai-cortex-integration, rai-discovery, rai-graph-analysis, rai-health, rai-ontology-design, rai-predictive-modeling, rai-predictive-training, rai-prescriptive-problem-formulation, rai-prescriptive-results-interpretation, rai-prescriptive-solver-management, rai-pyrel-coding, rai-querying, rai-rules-authoring, rai-setup | PASS |
| 17 | Playwright Chromium | `.venv/bin/playwright --version`; `.venv/bin/playwright install chromium`; headless launch + set_content | Playwright 1.64.0; Chromium 156.0.8078.4 launched headless, page title read back | PASS |
| 18 | Makefile skeleton | `make venv`; `make data` | venv target prints relationalai 1.27.1 / rai 1.27.1; placeholders exit 1 with TODO(owner) | PASS |

## Evidence behind the bootstrap edits

- App grants not needed: `SHOW GRANTS TO APPLICATION RELATIONALAI` shows no grant of any kind on PK_REGULATORY, CARS_DEMO or PK_NESTLE_DIET, yet `RELATIONALAI.API.DATA_STREAMS` holds 10 + 15 + 11 streams on those databases, all STATUS CREATED, bound through app reference DATA_STREAM_TABLE. Docs (create_data_stream) require only SELECT + change tracking + cdc_admin on the caller side.
- Pattern of existing demo roles (RAI_DEMO_CARS, RAI_DEMO_REGULATORY): `USAGE APPLICATION_ROLE RELATIONALAI.RAI_USER` granted by ACCOUNTADMIN plus OWNERSHIP of their own database. The draft follows the same pattern.
- User name is lowercase with '@': `SHOW GRANTS TO USER "PIOTR.KRAUS@RELATIONAL.AI"` fails with "does not exist"; the quoted lowercase form works.

## Not yet done (needs approved bootstrap)

- Apply data/00_bootstrap.sql.
- `rai connect` as RAI_DEMO_PE.
- Create or resume engine pe_demo_logic (HIGHMEM_X64_S, auto-suspend 30 min), confirm READY.
- Smoke test: 3-row table in RAI_DEMO_PE_DEALS.DEAL_GRAPH with CHANGE_TRACKING = TRUE, read through a tiny PyRel model, count = 3.

## Could not check

- PAT role restriction / expiry: `SHOW USER PROGRAMMATIC ACCESS TOKENS` was blocked by the harness. If the PAT is restricted to a role, RAI_DEMO_PE must be in that role's hierarchy (it will be, via SYSADMIN -> ACCOUNTADMIN, if the restriction is ACCOUNTADMIN).
- `RELATIONALAI.API.CDC_STATUS` (named in the rai-health skill) is not accessible as ACCOUNTADMIN or RAI_DEVELOPER on app V4; CDC is evidently working (streams in CREATED state).

## Attempt 2 (R01 a2, 2026-10-22, post-approval) - BLOCKED

The user approved data/00_bootstrap.sql as drafted at 07:46. R01 a2 applied it unchanged (sha256 933dbef9429b85f9996a59067a8963ff3f33ca2d210187ca065874bd3072a15d).

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 19 | Apply bootstrap | `snow sql -c rai -f data/00_bootstrap.sql` | Failed on the first statement `USE ROLE SECURITYADMIN;` with `003107 (42501): 01c7e4dc-030c-6988-0005-5ee310e72f22: SQL execution error: Current session is restricted. USE ROLE not allowed.` snow stops on the first error, so no later statement ran. | BLOCKED |
| 20 | Nothing partially applied | `SHOW ROLES LIKE 'RAI_DEMO_PE'; SHOW WAREHOUSES LIKE 'RAI_DEMO_PE_WH'; SHOW DATABASES LIKE 'RAI_DEMO_PE_DEALS'` | all `No data` | clean |
| 21 | Session role | `SELECT CURRENT_ROLE(), CURRENT_AVAILABLE_ROLES()` | ACCOUNTADMIN; SECURITYADMIN and SYSADMIN are listed as available, but the session cannot switch to them | info |
| 22 | Credential in use | `snow connection list` (non-secret fields) | `rai` uses PROGRAMMATIC_ACCESS_TOKEN from token_file_path ~/.snowflake/pat_token. raiconfig.yaml uses the same file. | info |

Root cause: the PAT in ~/.snowflake/pat_token was evidently created with a ROLE_RESTRICTION (very likely ACCOUNTADMIN). A role-restricted PAT session cannot run USE ROLE. The bootstrap needs USE ROLE SECURITYADMIN, SYSADMIN, RAI_DEMO_PE and ACCOUNTADMIN.

Knock-on risk: raiconfig.yaml connects with role RAI_DEMO_PE using the same PAT. A token restricted to ACCOUNTADMIN will probably not open a RAI_DEMO_PE session even after the bootstrap. So steps 2-5 (rai connect, engine, smoke test) are expected to fail until the credential changes too.

Not run in attempt 2, because they depend on the bootstrap: rai connect as RAI_DEMO_PE; engine pe_demo_logic create/resume (still does not exist); smoke test. Rows 1-18 above (versions, auth type, app reachable, claude -p skills, Playwright) are unchanged from attempt 1.

Unblock options (the user must act; the agent does not change credentials or the approved SQL):
1. Run data/00_bootstrap.sql unchanged in a Snowsight worksheet as ACCOUNTADMIN, where USE ROLE works.
2. Then provide a PAT that can open a RAI_DEMO_PE session. Either use `ALTER USER "piotr.kraus@relational.ai" ADD PROGRAMMATIC ACCESS TOKEN pe_demo ROLE_RESTRICTION = 'RAI_DEMO_PE' DAYS_TO_EXPIRY = 7;` saved to a new file such as ~/.snowflake/pat_token_pe_demo with raiconfig.yaml token_file_path pointing at it, or use an unrestricted PAT. Then re-spawn R01 a3 to run steps 2-5.

## Attempt 3 (R01 a3, 2026-10-22 08:03-08:13 Warsaw) - all R01-card checks PASS

The user ran the bootstrap in Snowsight and saved a PAT restricted to RAI_DEMO_PE at ~/.snowflake/pat_token_pe_demo. The token was never read, printed or logged. Only its existence and size were checked.

### Credential and config

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 23 | New PAT file present | `test -s ~/.snowflake/pat_token_pe_demo; ls -l ~/.snowflake/` | exists, 225 bytes, mode 0644 (old pat_token is 0600) | PASS (see issue I1) |
| 24 | raiconfig token path | `grep token_file_path raiconfig.yaml` | `token_file_path: ~/.snowflake/pat_token_pe_demo`; role RAI_DEMO_PE, warehouse RAI_DEMO_PE_WH, database RAI_DEMO_PE_DEALS, schema DEAL_GRAPH unchanged | PASS |
| 25 | raiconfig still gitignored | `git check-ignore -v raiconfig.yaml` | `.gitignore:38:raiconfig.yaml` | PASS |
| 26 | Deploy mode off | `.venv/bin/python -c "from relationalai.config import create_config; print(create_config().deployment_enabled)"` | `False` (the `deployment:` section is commented out, see row 37) | PASS |

### Bootstrap objects (read-only, via `snow sql -c rai`, ACCOUNTADMIN)

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 27 | Role | `SHOW ROLES LIKE 'RAI_DEMO_PE'` | RAI_DEMO_PE, owner ACCOUNTADMIN, created 2026-10-21 23:00:28 PDT, comment matches the file | PASS |
| 28 | Warehouse | `SHOW WAREHOUSES LIKE 'RAI_DEMO_PE_WH'` | X-Small, auto_suspend 60, auto_resume true, owner SYSADMIN, SUSPENDED at check time | PASS |
| 29 | Database | `SHOW DATABASES LIKE 'RAI_DEMO_PE_DEALS'` | owner RAI_DEMO_PE, comment 'Synthetic PE deal-graph demo. Safe to drop.' | PASS |
| 30 | Schema | `SHOW SCHEMAS IN DATABASE RAI_DEMO_PE_DEALS` | DEAL_GRAPH (owner RAI_DEMO_PE), INFORMATION_SCHEMA, PUBLIC (owner SYSADMIN) | PASS |
| 31 | Grants to role | `SHOW GRANTS TO ROLE RAI_DEMO_PE` | exactly 4: USAGE on WAREHOUSE RAI_DEMO_PE_WH (by SYSADMIN); OWNERSHIP on DATABASE RAI_DEMO_PE_DEALS; OWNERSHIP on SCHEMA RAI_DEMO_PE_DEALS.DEAL_GRAPH; USAGE on APPLICATION_ROLE RELATIONALAI.RAI_USER (by ACCOUNTADMIN). Matches the approved file. | PASS |
| 32 | Role hierarchy | `SHOW GRANTS OF ROLE RAI_DEMO_PE`; `SHOW GRANTS TO USER "piotr.kraus@relational.ai"` | granted to ROLE SYSADMIN only. The approved `GRANT ROLE RAI_DEMO_PE TO USER` is NOT present; the user reaches the role through ACCOUNTADMIN > SYSADMIN > RAI_DEMO_PE. | deviation (issue I2), non-blocking |

### Connection as RAI_DEMO_PE (new PAT, through raiconfig.yaml)

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 33 | rai connect | `.venv/bin/rai connect` | `Connected successfully`; account ajb85638, warehouse RAI_DEMO_PE_WH, database RAI_DEMO_PE_DEALS, schema DEAL_GRAPH, role RAI_DEMO_PE | PASS |
| 34 | Session identity | `create_config().get_session().sql("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()")` | piotr.kraus@relational.ai, RAI_DEMO_PE, RAI_DEMO_PE_WH, RAI_DEMO_PE_DEALS, DEAL_GRAPH | PASS |

A read-only probe of `USE ROLE ACCOUNTADMIN` on this session (to prove the role restriction) was denied by the harness. It was not retried.

### Engine

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 35 | Engine absent before | `.venv/bin/rai reasoners get --type Logic --name pe_demo_logic` | `Reasoner not found.` | info |
| 36 | Create to READY | `.venv/bin/rai reasoners create --type Logic --name pe_demo_logic --size HIGHMEM_X64_S --auto-suspend-mins 30 --wait --timeout-s 900` | READY after 4 min 21 s (created 08:05:05 Warsaw by piotr.kraus@relational.ai) | PASS |
| 36b | Engine settings | `CALL RELATIONALAI.API.GET_REASONER('logic','pe_demo_logic')` as RAI_DEMO_PE | TYPE LOGIC, SIZE HIGHMEM_X64_S, STATUS READY, AUTO_SUSPEND_MINS 30, compute_pool RELATIONAL_AI_HIGHMEM_X64_S | PASS |
| 36c | One engine only | `SELECT NAME, TYPE, STATUS FROM RELATIONALAI.API.REASONERS WHERE NAME ILIKE 'pe_demo%'` | 1 row: pe_demo_logic, logic, READY | PASS |

### Smoke test

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 37 | First run (deploy mode on) | `make smoke` | FAIL: `Object 'RAI_DEMO_PE_DEALS.DEAL_GRAPH.SMOKEROW' does not exist`. Cause: raiconfig `deployment: schema: DEAL_GRAPH` enables early-access deploy mode in 1.27.1 (`Config.deployment_enabled`); with `auto_deploy` unset, `executor.execute_query` calls `prepare_query` and compiles against pre-deployed tables. Fix: commented out the `deployment:` section. | fixed |
| 38 | Smoke test | `make smoke` (= `.venv/bin/python scripts/smoke_test.py`) | session role RAI_DEMO_PE; `SMOKE_TEST rows=3 change_tracking=ON`; parallel init 49.9 s (indexing 31.3 s); 2 queries COMPLETED (3.7 s, 3.0 s); rows 1 alpha / 2 bravo / 3 charlie; `rai: SmokeRow count=3`; `SMOKE TEST PASS`; 70 s wall | PASS |
| 39 | Idempotent re-run | `make smoke` | rows=3, count=3, PASS | PASS |
| 40 | Nothing stray | `SHOW SCHEMAS IN DATABASE RAI_DEMO_PE_DEALS`; `SHOW OBJECTS IN SCHEMA RAI_DEMO_PE_DEALS.DEAL_GRAPH`; `RELATIONALAI.API.DATA_STREAMS` | schemas DEAL_GRAPH only (as RAI_DEMO_PE); objects: SMOKE_TEST (TABLE) only; 1 data stream on RAI_DEMO_PE_DEALS | PASS |

Rows 1-18 (Python 3.13.13, uv 0.11.11, relationalai 1.27.1, rai and snow CLIs, non-interactive PAT auth, RAI app V4 reachable, `claude -p` lists the rai- skills, Playwright 1.64.0 + Chromium 156) are unchanged from attempt 1. The Gatekeeper should re-run them.

### R01-card summary

| R01 check | Evidence | Status |
|---|---|---|
| Python and uv versions | rows 2-3 | PASS |
| relationalai importable, version recorded | row 4 (1.27.1) | PASS |
| snow and rai CLIs work | rows 6-7, 33 | PASS |
| Non-interactive authenticator for ajb85638 | rows 8, 24, 33 (PAT, no prompt) | PASS |
| RAI Native App reachable | rows 11-12, 36b | PASS |
| Bootstrap applied | rows 27-32 | PASS (with deviation I2) |
| Engine pe_demo_logic READY, auto-suspend 30 | rows 36-36c | PASS |
| Smoke test, 3 rows, correct count | rows 38-39 | PASS |
| claude -p lists rai- skills | row 16 | PASS |
| Playwright Chromium | row 17 | PASS |

### Issues

- I1 MINOR: ~/.snowflake/pat_token_pe_demo is mode 0644 (world-readable). Recommend `chmod 600 ~/.snowflake/pat_token_pe_demo`. Not changed by R01, because the agent does not modify credential files.
- I2 MINOR: the approved `GRANT ROLE RAI_DEMO_PE TO USER "piotr.kraus@relational.ai"` was not applied, and the role is owned by ACCOUNTADMIN rather than SECURITYADMIN. This has no functional effect today, because access goes through the ACCOUNTADMIN > SYSADMIN chain. If that chain changes, the session breaks. The user can run the single grant in Snowsight to match the file.
- I3 INFO: the raiconfig `deployment:` section is disabled. Any later role that wants `rai models deploy` must re-enable it deliberately.
- I4 INFO: the first query on a fresh engine and stream took about 50 s of init. R14 `make warm` should cover this before the demo.
