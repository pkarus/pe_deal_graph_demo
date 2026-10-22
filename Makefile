# PE deal-graph demo - Makefile skeleton (owner: R01 Platform).
# Each role fills in ONLY its own target body; do not edit other roles' targets.
# Placeholders fail loudly (exit 1) until their owner replaces them.

SHELL  := /bin/bash
UV     ?= uv
PY     := .venv/bin/python
RAI    := .venv/bin/rai
ENGINE := pe_demo_logic

.PHONY: help venv smoke data oracle load test export artifacts explorer demo-script warm rehearse

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
	$(PY) data/generate.py
	$(PY) data/generate.py --check

# R06: independent pandas/networkx oracle for every hero answer -> data/oracle_output.json (reads data/csv/ only, never data/golden/).
oracle:
	$(PY) data/oracle.py

# R07: create tables from data/schema.sql in RAI_DEMO_PE_DEALS.DEAL_GRAPH and load data/csv/.
load:
	$(PY) data/load.py

# R11: hero tests (pytest tests/test_hero.py).
test:
	@echo "TODO(R11): make test not implemented yet" >&2; exit 1

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

# R14: resume engine $(ENGINE) and run every hero query once.
# Preconditions are checked before the engine is touched; each failure prints one clear line.
warm:
	@test -x $(PY) || { echo "make warm: FAIL - venv missing. Run: uv sync  (RUNBOOK.md step 2)" >&2; exit 1; }
	@test -f raiconfig.yaml || { echo "make warm: FAIL - raiconfig.yaml missing in $$PWD (gitignored). Copy it from the main checkout (RUNBOOK.md step 1)." >&2; exit 1; }
	@$(PY) demo_workspace/ask.py --check || { echo "make warm: FAIL - hero queries not ready (pe_deal_graph/queries.py, owner R11); engine not touched." >&2; exit 1; }
	@echo "make warm: resuming engine $(ENGINE) and waiting for READY ..."
	@$(RAI) reasoners resume --type Logic --name $(ENGINE) --wait >/dev/null 2>&1 \
	  || $(RAI) reasoners wait --type Logic --name $(ENGINE) \
	  || { echo "make warm: FAIL - engine $(ENGINE) not READY. Check: $(RAI) reasoners get --type Logic --name $(ENGINE)" >&2; exit 1; }
	@$(PY) demo_workspace/ask.py --warm || { echo "make warm: FAIL - a hero query failed (above). Use the per-act fallback in RUNBOOK.md." >&2; exit 1; }
	@echo "make warm: OK - engine $(ENGINE) warm, every hero query ran once."

# R17: cold rehearsal per PROMPT.md section 9.3.
rehearse:
	@echo "TODO(R17): make rehearse not implemented yet" >&2; exit 1

# R08: G3 ontology check - ONTOLOGY.md names == core.py; entity counts == source rows; every core relationship > 0 facts.
# ARGS=--offline (names and mapping only, no engine) | ARGS=--derived (after P4: derived names must have facts too).
.PHONY: ontology-check
ontology-check:
	$(PY) scripts/validate_ontology.py $(ARGS)
