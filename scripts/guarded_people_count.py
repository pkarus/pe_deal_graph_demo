"""Default: offline preparation checks. --execute requires separate user approval.

Guards are process-local; no installed SDK file is edited.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import inspect
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pe_deal_graph import settings as _cfg  # noqa: E402  (database/schema/role/engine names)
SCOPE = f"{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}"
ENGINE = f"{_cfg.ENGINE}"
TABLES = frozenset(
    "SECTOR REGION SPONSOR FUND FUND_FOCUS INTERMEDIARY COMPANY COMPANY_SITE "
    "PERSON ROLE_HISTORY OWNERSHIP TRANSACTION TRANSACTION_PARTY COMMERCIAL_LINK "
    "CRM_INTERACTION PIPELINE COMPANY_SIGNAL".split()
)
ALLOWED = frozenset(f"{SCOPE}.{name}" for name in TABLES)


def require_sources(sources):
    sources = list(sources)
    for index, source in enumerate(sources):
        if not isinstance(source, str):
            raise RuntimeError(
                f"Source name at index {index} must be a string; got {type(source).__name__}"
            )
    outside = set(sources) - ALLOWED
    if outside:
        raise RuntimeError(f"Source scope violation: {sorted(outside)}")
    return sources


def require_table_sources(tables):
    # SDK Table.name is a DSL expression; _name holds the source identifier.
    return require_sources(table._name for table in tables)


def reject_stale(poller, progress):
    require_sources(poller.source_info)
    stale = [name for name, info in poller.source_info.items()
             if info.get("state") != "CURRENT"]
    if stale:
        raise RuntimeError(f"Sources need review; automatic deletion is blocked: {stale}")


def check_sql(sql):
    # Defense in depth for explicit SDK stream/engine/settings mutations.
    if re.search(r"\b(?:delete_data_streams?|reset\w*|create_reasoner\w*|"
                 r"delete_reasoner\w*|alter_reasoner\w*|suspend_reasoner\w*|"
                 r"resume_reasoner\w*|alter_cdc\w*|delete_engine|resume_cdc|"
                 r"activate|enable_warm_reasoner|set_warm_reasoners)\s*\(", sql, re.I):
        raise RuntimeError("Blocked SDK stream/engine/settings mutation")
    if re.search(r"\b(?:ALTER|DROP|TRUNCATE|GRANT|REVOKE|CREATE|INSERT|UPDATE|DELETE|MERGE|COPY|PUT)\b", sql, re.I):
        raise RuntimeError("Blocked SDK DDL or data-writing SQL")


def main(query_kind="people"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--communities", action="store_true", help="Baseline Louvain and internal betweenness")
    parser.add_argument("--louvain-max-levels", type=int, nargs='+', help="Level caps to compare (default: 1)")
    parser.add_argument("--louvain-seeds", type=int, nargs='+', help="Non-negative seeds (default: 42)")
    parser.add_argument("--community-results", type=Path, help="Saved RAI artifact (default: artifacts/people_communities.json)")
    parser.add_argument("--community-output", type=Path, help="New JSON artifact; required for live comparisons")
    parser.add_argument("--routes", action="store_true", help="Knows entry point: validate oracle-selected routes")
    parser.add_argument("--person-paths", action="store_true", help="Validate non-seed paths, self, and unreachable")
    parser.add_argument("--remaining-person-paths", action="store_true",
                        help="Validate only the remaining 1-hop, 2-hop, self and unreachable examples")
    parser.add_argument("--long-person-paths", action="store_true",
                        help="Validate reviewed non-seed 4-hop and 5-hop examples")
    parser.add_argument("--source-id")
    parser.add_argument("--target-id")
    args = parser.parse_args()
    if not args.communities and any(value is not None for value in (
            args.louvain_max_levels, args.louvain_seeds, args.community_results, args.community_output)):
        parser.error('Community options require --communities')
    if args.long_person_paths and (args.remaining_person_paths or args.person_paths
                                  or args.source_id is not None or args.target_id is not None):
        raise RuntimeError("The long-path batch cannot be combined with other person-path selections")
    if args.remaining_person_paths and (args.person_paths or args.source_id is not None or args.target_id is not None):
        raise RuntimeError("The remaining-path batch cannot be combined with other person-path selections")
    if args.person_paths or args.remaining_person_paths or args.long_person_paths or args.source_id is not None or args.target_id is not None:
        if query_kind != "knows" or args.routes:
            raise RuntimeError("Use the Knows entry point without --routes for arbitrary-person paths")
        if (args.source_id is None) != (args.target_id is None):
            raise RuntimeError("Provide both --source-id and --target-id")
        query_kind = "person_paths"
    if args.routes:
        if query_kind != "knows":
            raise RuntimeError("Use guarded_knows_count.py for route checks")
        query_kind = "routes"
    if args.communities:
        if query_kind != 'knows' or args.routes or args.person_paths or args.remaining_person_paths or args.long_person_paths or args.source_id or args.target_id:
            raise RuntimeError('Community analysis must be selected alone from the Knows entry point')
        query_kind = 'communities'
        from check_graphs import community_parameters, analyze_people_communities, prepare_oracle
        levels, seeds = args.louvain_max_levels or [1], args.louvain_seeds or [42]
        for level in levels:
            for seed in seeds:
                community_parameters(level, seed)
        saved_path = args.community_results or ROOT/'artifacts/people_communities.json'
        if args.community_output and args.community_output.exists():
            parser.error('--community-output must be a new file; saved evidence is never overwritten')
        if args.execute and args.community_output is None:
            parser.error('--execute --communities requires --community-output to save completed RAI queries')
        if not args.execute:
            print('OFFLINE COMMUNITY ANALYSIS: saved RAI rows and local NetworkX; no connection or model import')
            analyze_people_communities(prepare_oracle(), levels, seeds, saved_path,
                                       output_path=args.community_output)
            return
    os.environ.pop("DEBUG", None)
    os.environ["RAI_CONFIG_FILE_PATH"] = str(ROOT / "raiconfig.yaml")
    sys.path.insert(0, str(ROOT))
    from relationalai.config import create_config
    from v0.relationalai.clients.resources.snowflake.use_index_poller import UseIndexPoller
    from v0.relationalai.clients.resources.snowflake.snowflake import Resources

    if importlib.metadata.version("relationalai") != "1.27.1":
        raise RuntimeError("SDK version changed; review guard compatibility first")
    cfg = create_config()
    conn = cfg.get_default_connection()
    if (conn.database, conn.schema_) != tuple(SCOPE.split(".")):
        raise RuntimeError("Configured database/schema is outside the experiment")
    if cfg.reasoners.logic.name != ENGINE:
        raise RuntimeError("Configured Logic engine does not match the approved engine")
    if cfg.data.ensure_change_tracking:
        raise RuntimeError("Automatic change-tracking changes must remain disabled")
    if cfg.deployment.schema_ is not None or cfg.deployment.auto_deploy:
        raise RuntimeError("Deployment mode is not permitted for this count")

    # Inspect source bindings without importing or executing the model.
    tree = ast.parse((ROOT / "pe_deal_graph/model/core.py").read_text())
    node = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "SOURCE_SCHEMA" for t in n.targets))
    # core.py takes the default source schema from pe_deal_graph.settings (the same value as SCOPE).
    schema = (_cfg.SOURCE_SCHEMA if ast.unparse(node) == "_cfg.SOURCE_SCHEMA" else ast.literal_eval(node))
    names = {ast.literal_eval(n.args[0]) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_bind"}
    if schema != SCOPE or names != TABLES:
        raise RuntimeError("Core source bindings changed; review before running")

    if query_kind in {"knows", "communities"}:
        from check_graphs import prepare_oracle, run_knows_count
        oracle_pairs = prepare_oracle()
    elif query_kind == "routes":
        from check_graphs import prepare_route_examples, run_person_routes
        route_examples = prepare_route_examples()
    elif query_kind == "person_paths":
        from check_graphs import prepare_person_path_examples, run_arbitrary_person_paths
        path_examples = prepare_person_path_examples(
            args.source_id, args.target_id, remaining=args.remaining_person_paths,
            long_paths=args.long_person_paths)
    elif query_kind != "people":
        raise RuntimeError("Unknown guarded query")

    sdk_files = [Path(inspect.getfile(UseIndexPoller)), Path(inspect.getfile(Resources))]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sdk_files}
    print(f"Verified engine: {ENGINE}; source scope: {SCOPE}; 17 allowed tables")
    if not args.execute:
        print("OFFLINE CHECK ONLY: no connection, model import, or query execution")
        return

    # Read-only preflight; no provisioning or repair if anything is missing.
    session = cfg.get_session()
    rows = session.sql(
        "SELECT NAME, STATUS FROM RELATIONALAI.API.REASONERS WHERE NAME = ?",
        params=[ENGINE],
    ).collect()
    if len(rows) != 1 or rows[0]["STATUS"] != "READY":
        raise RuntimeError("Approved engine is not READY; no resume/create attempted")
    streams = session.sql(
        "SELECT FQ_OBJECT_NAME, STATUS FROM RELATIONALAI.API.DATA_STREAMS "
        "WHERE SPLIT_PART(FQ_OBJECT_NAME,'.',1)=? AND SPLIT_PART(FQ_OBJECT_NAME,'.',2)=?",
        params=SCOPE.split("."),
    ).collect()
    found = {r["FQ_OBJECT_NAME"] for r in streams if r["STATUS"] == "CREATED"}
    if not ALLOWED <= found:
        raise RuntimeError(f"Existing experiment streams missing: {sorted(ALLOWED - found)}")

    original_init = UseIndexPoller.__init__
    signature = inspect.signature(original_init)
    original_exec = Resources._exec

    def guarded_init(self, *a, **kw):
        bound = signature.bind(self, *a, **kw)
        if bound.arguments["engine_name"] != ENGINE:
            raise RuntimeError("Runtime engine mismatch")
        bound.arguments["sources"] = require_sources(bound.arguments["sources"])
        require_sources(bound.arguments.get("requested_columns") or {})
        original_init(*bound.args, **bound.kwargs)
        require_sources(self.source_info)
        self.init_engine_async = False  # Existing READY engine only.

    def guarded_exec(self, code, *a, **kw):
        check_sql(code)
        return original_exec(self, code, *a, **kw)

    from snowflake.snowpark import Session
    original_sql = Session.sql

    def guarded_sql(self, query, *a, **kw):
        check_sql(query)
        return original_sql(self, query, *a, **kw)

    try:
        with patch.object(UseIndexPoller, "__init__", guarded_init), \
             patch.object(UseIndexPoller, "_maybe_delete_stale", reject_stale), \
             patch.object(Resources, "_exec", guarded_exec), \
             patch.object(Session, "sql", guarded_sql):
            from pe_deal_graph.model.core import model, Person, SOURCE_TABLES
            require_table_sources(SOURCE_TABLES.values())
            if query_kind == "communities":
                analyze_people_communities(oracle_pairs, levels, seeds, saved_path,
                                           execute=True, output_path=args.community_output)
                return
            if query_kind == "knows":
                run_knows_count(oracle_pairs)
                return
            if query_kind == "routes":
                run_person_routes(route_examples)
                return
            if query_kind == "person_paths":
                run_arbitrary_person_paths(path_examples)
                return
            from relationalai.semantics.std import aggregates as aggs
            result = model.select(aggs.count(Person).alias("people")).to_df()
            print(result.to_string(index=False))
            if len(result) != 1 or int(result["people"].iloc[0]) != 2506:
                raise RuntimeError("People count differs from verified source count 2506")
    finally:
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != before[p] for p in sdk_files):
            raise RuntimeError("SDK files changed during the run")


if __name__ == "__main__":
    main()
