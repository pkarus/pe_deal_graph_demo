# PE deal-graph demo - Makefile skeleton (owner: R01 Platform).
# Each role fills in ONLY its own target body; do not edit other roles' targets.
# Placeholders fail loudly (exit 1) until their owner replaces them.

SHELL  := /bin/bash
UV     ?= uv
PY     := .venv/bin/python
RAI    := .venv/bin/rai
ENGINE := pe_demo_logic

.PHONY: help venv smoke data load test export artifacts warm rehearse

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
	@echo "TODO(R05): make data not implemented yet" >&2; exit 1

# R07: create tables from data/schema.sql in RAI_DEMO_PE_DEALS.DEAL_GRAPH and load data/csv/.
load:
	@echo "TODO(R07): make load not implemented yet" >&2; exit 1

# R11: hero tests (pytest tests/test_hero.py).
test:
	@echo "TODO(R11): make test not implemented yet" >&2; exit 1

# R13: live RAI queries -> exports/*.json.
export:
	@echo "TODO(R13): make export not implemented yet" >&2; exit 1

# R15/R16: build artifacts/*.html from exports/.
artifacts:
	@echo "TODO(R15/R16): make artifacts not implemented yet" >&2; exit 1

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
