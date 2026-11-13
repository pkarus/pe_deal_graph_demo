"""Environment settings: which Snowflake database, schemas, roles, warehouse and engine to use.

Nothing account-specific is hard-coded in the code. Values are resolved in this order:

1. Environment variables (``PE_DATABASE``, ``PE_BASE_SCHEMA``, ``PE_ENGINE``, ``PE_ADMIN_ROLE``,
   ``PE_DEPLOY_ROLE``, ``PE_WAREHOUSE``).
2. ``pe_settings.yaml`` in the repo root (optional, gitignored; see ``pe_settings.example.yaml``).
3. Your ``raiconfig.yaml`` (default connection's database/schema/role/warehouse, logic reasoner name).
4. The original demo defaults (``RAI_DEMO_PE_DEALS.DEAL_GRAPH`` on engine ``pe_demo_logic``).

Experiment outputs live in sibling schemas named ``<BASE_SCHEMA>_<SUFFIX>`` in ``DATABASE``,
e.g. ``schema("DEPLOY")`` -> ``MY_DB.DEAL_GRAPH_DEPLOY``.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    import yaml
    return yaml.safe_load(path.read_text()) or {}


def _raiconfig() -> dict:
    cfg = _load_yaml(Path(os.environ.get("RAI_CONFIG_FILE_PATH", ROOT / "raiconfig.yaml")))
    connections = cfg.get("connections") or {}
    conn = connections.get(cfg.get("default_connection")) or next(iter(connections.values()), {}) or {}
    logic = (cfg.get("reasoners") or {}).get("logic") or {}
    return {"database": conn.get("database"), "base_schema": conn.get("schema"),
            "admin_role": conn.get("role"), "warehouse": conn.get("warehouse"), "engine": logic.get("name")}


_DEFAULTS = {"database": "RAI_DEMO_PE_DEALS", "base_schema": "DEAL_GRAPH", "engine": "pe_demo_logic",
             "admin_role": "RAI_USER", "warehouse": "RAI_XS"}
_local = _load_yaml(ROOT / "pe_settings.yaml")
_rai = _raiconfig()


def _get(key: str):
    return os.environ.get("PE_" + key.upper()) or _local.get(key) or _rai.get(key) or _DEFAULTS.get(key)


DATABASE = _get("database").upper()
BASE_SCHEMA = _get("base_schema").upper()
ENGINE = _get("engine")                      # RAI engine names are case-sensitive
WAREHOUSE = _get("warehouse").upper()
ADMIN_ROLE = _get("admin_role").upper()      # creates experiment schemas and grants
DEPLOY_ROLE = (_get("deploy_role") or ADMIN_ROLE).upper()  # owns deployments, runs refresh tasks
SOURCE_SCHEMA = f"{DATABASE}.{BASE_SCHEMA}"  # the demo's 17 source tables
# Validated community run the Cortex agent serves (the --json output of a community deployment).
AGENT_COMMUNITY_EVIDENCE = _get("agent_community_evidence") or "artifacts/people_communities_baseline_5_7.json"


def schema(suffix: str) -> str:
    """Fully qualified experiment schema, e.g. schema('DEPLOY') -> '<DB>.<BASE>_DEPLOY'."""
    return f"{DATABASE}.{BASE_SCHEMA}_{suffix}"


def describe() -> str:
    return (f"database={DATABASE} base_schema={BASE_SCHEMA} engine={ENGINE} warehouse={WAREHOUSE} "
            f"admin_role={ADMIN_ROLE} deploy_role={DEPLOY_ROLE}")
