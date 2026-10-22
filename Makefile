# PE deal-graph demo - Makefile skeleton (owner: R01 Platform).
# Each role fills in ONLY its own target body; do not edit other roles' targets.
# Placeholders fail loudly (exit 1) until their owner replaces them.

SHELL  := /bin/bash
UV     ?= uv
PY     := .venv/bin/python
RAI    := .venv/bin/rai
ENGINE := pe_demo_logic

.PHONY: help venv smoke data oracle load test naive-sql export artifacts explorer demo-script warm rehearse

help:
	@echo "Targets: venv smoke data load test export artifacts warm rehearse"

# R01: create/refresh the pinned venv from pyproject.toml + uv.lock (relationalai==1.27.1, Python 3.13).
venv:
	$(UV) sync --python 3.13
	$(PY) -c "import importlib.metadata as m; print('relationalai', m.version('relationalai'))"
	$(RAI) --version

# R01: G0 smoke test - 3-row SMOKE_TEST table (CHANGE_TRACKING) read through a tiny PyRel model as RAI_DEMO_PE.
smoke:
	$(PY) scripts/smoke_test.py

# R05: deterministic generation into data/csv/ (and data/golden/) with RANDOM_SEED.
data:
	$(PY) data/generate.py --noise --out data/csv
	$(PY) data/generate.py --check

# R06: independent pandas/networkx oracle for every hero answer -> data/oracle_output.json (reads data/csv/ only, never data/golden/).
oracle:
	$(PY) data/oracle.py

# R07: create tables from data/schema.sql in RAI_DEMO_PE_DEALS.DEAL_GRAPH and load data/csv/.
load:
	$(PY) data/load.py

# R11: hero tests (pytest tests/test_hero.py): golden IDs/order, decoys absent, evidence, two-run determinism,
# naive SQL baselines. 'make test ARGS="-m warehouse"' runs only the SQL baselines (no engine).
# 'make naive-sql' prints every data/naive_sql/*.sql result (warehouse only).
test:
	$(PY) -m pytest tests/test_hero.py -v -p no:cacheprovider $(ARGS)

naive-sql:
	$(PY) data/naive_sql/run_naive.py

# R13: live RAI queries -> exports/*.json.
# Determinism: two runs differ only in meta.generated_at ('make export-compare A=dir B=dir' ignores it).
# 'make export-check' validates exports/ (or EXPORT_DIR=...) against the R15 contract without the engine.
EXPORT_DIR ?= exports
export:
	@test -f pe_deal_graph/queries.py || { echo "export: pe_deal_graph/queries.py missing (owner R11)" >&2; exit 2; }
	$(PY) -m pe_deal_graph.export --out "$(EXPORT_DIR)"
	$(PY) -m pe_deal_graph.export --check-contract "$(EXPORT_DIR)"

export-check:
	$(PY) -m pe_deal_graph.export --check-contract "$(EXPORT_DIR)"

export-compare:
	$(PY) -m pe_deal_graph.export --compare "$(A)" "$(B)"

# R15/R16: build artifacts/*.html from exports/. "artifacts" runs both steps; each role owns its own step.
artifacts: explorer demo-script

# R15: Deal Graph Explorer from exports/ (never from the FIXTURE set). Fails clearly if exports/ is missing.
EXPLORER_EXPORTS ?= exports
explorer:
	@test -d "$(EXPLORER_EXPORTS)" || { echo "ERROR: $(EXPLORER_EXPORTS)/ not found. Run 'make export' (R13) first; the explorer is built only from live exports." >&2; exit 1; }
	$(PY) artifacts/build_explorer.py --exports "$(EXPLORER_EXPORTS)" --out artifacts/deal_graph_explorer.html

# R16: demo script from exports/ and golden/stories.md.
# Fails loudly on a missing exports key; re-verifies every injected number; refuses FIXTURE exports.
demo-script:
	$(PY) artifacts/build_script.py

# R16: FIXTURE build for development only -> tests/fixtures/script/out/demo_script_FIXTURE.html (stamped FIXTURE).
demo-script-fixture:
	$(PY) artifacts/build_script.py --fixture

# R14: check Snowflake auth, resume engine $(ENGINE), start the warm query server, run every hero query.
# Preconditions are checked before the engine is touched; each failure prints one clear line.
# Run at T-30 (surfaces problems) and again at T-10 (the engine auto-suspends after 30 idle minutes).
# Auth errors from `rai connect` are printed verbatim (the PAT expires $(PAT_EXPIRES)).
# The query server keeps the model compiled in one process so live acts skip the 45-75 s first-query cost;
# if it cannot start, warm still warms the engine in-process and says so. Stop it: $(PY) demo_workspace/ask.py --serve-stop
PAT_EXPIRES := 2026-10-29
warm:
	@test -x $(PY) || { echo "make warm: FAIL - venv missing. Run: uv sync  (RUNBOOK.md step 2)" >&2; exit 1; }
	@test -f raiconfig.yaml || { echo "make warm: FAIL - raiconfig.yaml missing in $$PWD (gitignored). Copy it from the main checkout (RUNBOOK.md step 1)." >&2; exit 1; }
	@$(PY) demo_workspace/ask.py --check || { echo "make warm: FAIL - hero queries not ready (pe_deal_graph/queries.py, owner R11); engine not touched." >&2; exit 1; }
	@if [ ! "$$(date +%F)" \< "$(PAT_EXPIRES)" ]; then echo "make warm: WARNING - today is on or after $(PAT_EXPIRES), the PAT expiry date in RUNBOOK.md. Expect an auth failure below." >&2; fi
	@echo "make warm: checking Snowflake auth (rai connect) ..."
	@out=$$($(RAI) connect 2>&1); rc=$$?; if [ $$rc -ne 0 ]; then \
	  echo "$$out" | grep -v -E "^\s*$$" >&2; \
	  echo "make warm: FAIL - Snowflake auth/connection failed (rai connect output above, verbatim; ignore its generic 'could not reach' hint and read the Error line)." >&2; \
	  echo "  'Programmatic access token is invalid' or 'expired': the PAT (created 2026-10-22, expires $(PAT_EXPIRES)) must be regenerated in Snowsight for the raiconfig user and written to the token_file_path in raiconfig.yaml." >&2; \
	  echo "  'network policy' or 'IP ... not allowed', or a timeout: this network is not allowed for the PAT user. Switch to the hotspot or VPN (RUNBOOK.md, 'Venue network')." >&2; \
	  exit 1; fi; echo "make warm: auth OK"
	@echo "make warm: resuming engine $(ENGINE) and waiting for READY ..."
	@out=$$($(RAI) reasoners resume --type Logic --name $(ENGINE) --wait 2>&1) \
	  || out=$$($(RAI) reasoners wait --type Logic --name $(ENGINE) 2>&1) \
	  || { echo "$$out" | tail -20 >&2; echo "make warm: FAIL - engine $(ENGINE) not READY (output above). Check: $(RAI) reasoners get --type Logic --name $(ENGINE)" >&2; exit 1; }
	@echo "make warm: engine $(ENGINE) READY"
	@$(PY) demo_workspace/ask.py --serve-start \
	  || echo "make warm: WARNING - warm query server did not start; live acts run in-process (45-75 s first query each)." >&2
	@$(PY) demo_workspace/ask.py --warm || { echo "make warm: FAIL - a hero query failed or its names do not match golden (above). Use the per-act fallback in RUNBOOK.md." >&2; exit 1; }
	@echo "make warm: OK - engine $(ENGINE) warm, every hero query ran. Now run 'make keepalive' in its own terminal until the Q&A ends."

# R14: keep engine $(ENGINE) awake during the meeting: one cheap query every KEEPALIVE_MIN minutes until Ctrl-C.
# Uses the warm query server when it is up (each ping takes seconds); prints one timestamped line per ping.
KEEPALIVE_MIN ?= 10
.PHONY: keepalive
keepalive:
	@test -x $(PY) || { echo "make keepalive: FAIL - venv missing. Run: uv sync" >&2; exit 1; }
	@$(PY) demo_workspace/ask.py --keepalive $(KEEPALIVE_MIN)

# R17: cold rehearsal per PROMPT.md section 9.3.
rehearse:
	@echo "TODO(R17): make rehearse not implemented yet" >&2; exit 1

# R08: G3 ontology check - ONTOLOGY.md names == core.py; entity counts == source rows; every core relationship > 0 facts.
# ARGS=--offline (names and mapping only, no engine) | ARGS=--derived (after P4: derived names must have facts too).
.PHONY: ontology-check
ontology-check:
	$(PY) scripts/validate_ontology.py $(ARGS)

# R12: signal + P5 noise into data/csv_noise/ (opt-in; data/csv/ stays signal-only until the orchestrator flips
# the default after G4), then the R05 self-check and the R12 noise check on that directory. Golden is unchanged.
.PHONY: data-noise
NOISE_DIR ?= data/csv_noise
data-noise:
	$(PY) data/generate.py --noise --out $(NOISE_DIR)
	$(PY) data/generate.py --check --out $(NOISE_DIR)
	$(PY) data/generate.py --noise-check --out $(NOISE_DIR)
