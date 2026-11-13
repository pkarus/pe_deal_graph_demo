"""Offline checks for oracle comparison; no live model execution."""
from pathlib import Path
import runpy
import pytest
import ast
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pe_deal_graph import settings as _cfg  # noqa: E402  (database/schema/role/engine names)


runner = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_graphs.py"))


def test_fixed_probe_requires_complete_oracle_distances():
    rows = runner["fixed_probe_oracle_rows"]()
    assert len(rows) == 1720
    runner["validate_fixed_probe_rows"](rows)
    for bad in (rows[:-1], rows + [rows[0]],
                [dict(rows[0], hops=999)] + rows[1:]):
        with pytest.raises(RuntimeError):
            runner["validate_fixed_probe_rows"](bad)


def test_oracle_baseline():
    pairs = runner["prepare_oracle"]()
    assert len(pairs) == 2525
    assert all(a < b for a, b in pairs)
    assert runner["MIN_TIE_STRENGTH"] == 0.0


def test_difference_reports_missing_extra_and_symmetric_duplicates():
    expected = {("P1", "P2"): {"strength": 0.6, "evidence": []},
                ("P2", "P3"): {"strength": 0.7, "evidence": []}}
    rows = [{"p1": "P1", "p2": "P2", "strength": 0.6},
            {"p1": "P2", "p2": "P1", "strength": 0.6},
            {"p1": "P1", "p2": "P4", "strength": 0.8}]
    diff = runner["compare_pairs"](rows, expected)
    assert diff["missing_pairs"] == [["P2", "P3"]]
    assert diff["extra_pairs"] == [["P1", "P4"]]
    assert diff["duplicate_rows"] == 1
    assert diff["noncanonical_pairs"] == [["P2", "P1"]]
    assert diff["missing_pair_oracle_evidence"][0]["oracle"] == expected[("P2", "P3")]


@pytest.fixture(scope="module")
def route_examples():
    return runner["prepare_route_examples"]()


def route_rows(examples):
    source = examples[0]["source"]
    return [{"source": source, "target": source, "hops": 0}] + [
        {"source": source, "target": e["target"], "hops": e["hops"]}
        for e in examples if e["hops"] is not None]


def test_oracle_routes_and_validation(route_examples):
    examples = route_examples
    assert [e["hops"] for e in examples] == [1, 2, 3, None]
    assert {e["source"] for e in examples} == {"P19079"}
    pairs = runner["prepare_oracle"]()
    for e in examples[:3]:
        assert len(e["path"]) - 1 == e["hops"]
        assert all(tuple(sorted(edge)) in pairs for edge in zip(e["path"], e["path"][1:]))
    endpoints = {e["target"] for e in examples} | {examples[0]["source"]}
    runner["validate_route_distances"](examples, endpoints, route_rows(examples))
    edges = [{"p1": a, "p2": b} for e in examples
             for a, b in zip(e["path"], e["path"][1:])]
    runner["validate_route_edges"](examples, edges)
    with pytest.raises(RuntimeError, match="edge missing"):
        runner["validate_route_edges"](examples, [])


@pytest.mark.parametrize("fault", ["empty", "no_self", "missing_endpoint", "wrong_hops", "reachable", "duplicate"])
def test_route_checks_fail_closed(route_examples, fault):
    examples = route_examples
    endpoints = {e["target"] for e in examples} | {examples[0]["source"]}
    rows = route_rows(examples)
    if fault == "empty":
        rows = []
    elif fault == "no_self":
        rows = rows[1:]
    elif fault == "missing_endpoint":
        endpoints.remove(examples[-1]["target"])
    elif fault == "wrong_hops":
        rows[1]["hops"] = 2
    elif fault == "reachable":
        rows.append({"source": examples[0]["source"], "target": examples[-1]["target"], "hops": 4})
    elif fault == "duplicate":
        rows.append(dict(rows[1]))
    with pytest.raises(RuntimeError):
        runner["validate_route_distances"](examples, endpoints, rows)


def load_functions(path, names, namespace):
    """Load production function bodies without importing Snowflake-bound model modules."""
    tree = ast.parse(path.read_text())
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)


@pytest.fixture(scope="module")
def person_oracle():
    import networkx as nx
    oracle = runpy.run_path(str(Path(__file__).resolve().parents[1] / "data/oracle.py"))
    data = oracle["Data"]()
    seeds = set(oracle["our_seeds"](data))
    pairs = oracle["build_knows"](data, seeds)
    graph = oracle["knows_graph"](data, pairs)
    return data, seeds, graph, nx


@pytest.fixture
def offline_path_query(monkeypatch):
    import pandas as pd
    from relationalai.config import Config
    from relationalai.semantics import Model, String, Integer, Float
    from relationalai.semantics.reasoners.graph import Graph
    from snowflake.snowpark import Session

    def block_live(*args, **kwargs):
        raise AssertionError("No live execution is allowed in offline path tests")

    monkeypatch.setattr(Config, "get_session", block_live)
    monkeypatch.setattr(Session, "sql", block_live)
    cfg = Config(connections={"offline": {"type": "duckdb", "path": ":memory:"}},
                 default_connection="offline")
    model = Model("offline_person_paths", config=cfg, is_library=True)
    person = model.Concept("Person", identify_by={"id": String})
    person.name = model.Property(f"{person} has name {String:name}")
    person.knows = model.Relationship(f"{person} knows {person:other}")
    person.tie_strength = model.Property(f"{person} knows {person:other} with strength {Float:strength}")
    graph = Graph(model, directed=False, weighted=False, node_concept=person)
    graph_ns = {"model": model, "Person": person, "knows_graph": graph,
                "_person_distance_queries": {}, "BUILD_PROFILE": "default"}
    root = Path(__file__).resolve().parents[1]
    load_functions(root / "pe_deal_graph/model/graphs.py", ["person_distances"], graph_ns)
    ns = {"model": model, "Person": person, "Integer": Integer, "Float": Float,
          "pd": pd, "GraphOutputMissing": RuntimeError,
          "_graphs": SimpleNamespace(MIN_TIE_STRENGTH=0.0, person_distances=graph_ns["person_distances"])}
    load_functions(root / "pe_deal_graph/queries.py", ["q_person_path", "_assemble_person_path"], ns)
    return ns, pd, graph_ns


@pytest.mark.parametrize("source,target", [
    ("P10034", "P31852"), ("P10034", "P37083"), ("P10034", "P10451"),
    ("P10451", "P10034"), ("P10034", "P10034"), ("P10034", "P10001"),
    ("P10001", "P10001"), ("P10001", "P10034"),
    ("P10034", "P19694"), ("P10034", "P11562"),
])
def test_arbitrary_paths_against_oracle(offline_path_query, person_oracle, source, target):
    ns, pd, graph_ns = offline_path_query
    data, seeds, graph, nx = person_oracle
    assert source not in seeds
    distances = nx.single_source_shortest_path_length(graph, source)
    endpoints = [{"id": p, "name": data.pname(p)} for p in sorted({source, target})]
    responses = [pd.DataFrame(endpoints)]
    if source != target:
        responses.append(pd.DataFrame([{"id": p, "name": data.pname(p), "hops": h}
                                       for p, h in distances.items()]))
        if target in distances:
            edges = []
            for u, v in graph.edges:
                for a, b in ((u, v), (v, u)):
                    if a in distances and b in distances and distances[b] == distances[a] + 1 and distances[b] <= distances[target]:
                        edges.append({"a": a, "b": b})
            responses.append(pd.DataFrame(edges, columns=["a", "b"]))
    ns["_run"] = lambda query: responses.pop(0)
    result = ns["q_person_path"](source, target)
    assert not responses
    assert result["distance"] == distances.get(target)
    if target not in distances:
        assert result["status"] == "unreachable" and result["route"] == []
    else:
        assert result["status"] == ("self" if source == target else "reachable")
        route = result["route"]
        assert route[0] == source and route[-1] == target
        assert len(route) - 1 == nx.shortest_path_length(graph, source, target)
        assert all(graph.has_edge(a, b) for a, b in zip(route, route[1:]))
    if source != target:
        first = graph_ns["person_distances"](source)
        assert graph_ns["person_distances"](source) is first
        assert graph_ns["person_distances"](target) is not first


def test_person_path_missing_and_invalid_inputs(offline_path_query):
    ns, pd, _ = offline_path_query
    ns["_run"] = lambda query: pd.DataFrame(columns=["id", "name"])
    with pytest.raises(ValueError, match="Unknown person IDs"):
        ns["q_person_path"]("MISSING", "MISSING")
    with pytest.raises(ValueError, match="nonempty"):
        ns["q_person_path"](None, "P10034")
    with pytest.raises(RuntimeError, match="self-distance"):
        ns["_assemble_person_path"]("a", "b", {"a": "A", "b": "B"}, {}, [])
    with pytest.raises(RuntimeError, match="route witness"):
        ns["_assemble_person_path"]("a", "b", {"a": "A", "b": "B"}, {"a": 0, "b": 1}, [])


def test_remaining_batch_exact_cases():
    cases = runner["prepare_person_path_examples"](remaining=True)
    assert [(e["source"], e["target"], e["hops"]) for e in cases] == [
        ("P10034", "P31852", 1), ("P10034", "P37083", 2),
        ("P10034", "P10034", 0), ("P10034", "P10001", None)]
    assert all(not e["source_is_seed"] for e in cases)


def test_long_batch_exact_cases(person_oracle):
    data, seeds, graph, nx = person_oracle
    cases = runner["prepare_person_path_examples"](long_paths=True)
    assert [(e["source"], e["target"], e["hops"]) for e in cases] == [
        ("P10034", "P19694", 4), ("P10034", "P11562", 5)]
    for e in cases:
        assert e["source"] not in seeds and e["target"] not in seeds
        assert nx.shortest_path_length(graph, e["source"], e["target"]) == e["hops"]
        assert len(e["path"]) - 1 == e["hops"]
        assert all(graph.has_edge(a, b) for a, b in zip(e["path"], e["path"][1:]))
    with pytest.raises(ValueError, match="cannot be combined"):
        runner["prepare_person_path_examples"](remaining=True, long_paths=True)


@pytest.mark.parametrize("failure", ["query_error", "wrong_distance", "wrong_edge"])
def test_path_batch_stops_on_failure(monkeypatch, failure):
    import sys
    from types import ModuleType
    calls = []
    examples = [{"source": "A", "target": "B", "hops": 1},
                {"source": "A", "target": "C", "hops": 2},
                {"source": "A", "target": "A", "hops": 0}]

    def query(source, target):
        calls.append((source, target))
        if target == "B":
            return {"distance": 1, "status": "reachable", "route": ["A", "B"]}
        if failure == "query_error":
            raise RuntimeError("Guard blocked query")
        return {"distance": 9 if failure == "wrong_distance" else 2,
                "status": "reachable", "route": ["A", "UNKNOWN", "C"]}

    fake = ModuleType("pe_deal_graph.queries")
    fake.q_person_path = query
    monkeypatch.setitem(sys.modules, "pe_deal_graph.queries", fake)
    execute = runner["run_arbitrary_person_paths"]
    monkeypatch.setitem(execute.__globals__, "prepare_oracle", lambda: {("A", "B"): {}, ("B", "C"): {}})
    with pytest.raises(RuntimeError):
        execute(examples)
    assert calls == [("A", "B"), ("A", "C")]


def test_deploy_preview_never_connects(monkeypatch, capsys):
    run = runner["run_copied_distance_probe"]
    def unexpected():
        pytest.fail("Preview opened a connection")
    monkeypatch.setitem(run.__globals__, "build_deployment_probe", unexpected)
    run()
    assert f"{_cfg.BASE_SCHEMA}_DEPLOY_SRC" in capsys.readouterr().out


@pytest.mark.parametrize("fails", [False, True])
def test_direct_deploy_closes_session_and_refreshes_only_on_success(monkeypatch, fails):
    run = runner["run_copied_distance_probe"]
    calls = []
    def deploy(**kwargs):
        calls.append(("deploy", kwargs))
        if fails:
            raise RuntimeError("SDK failure")
    session = SimpleNamespace(close=lambda: calls.append("close"))
    model = SimpleNamespace(deploy=deploy)
    monkeypatch.setitem(run.__globals__, "build_deployment_probe", lambda: (model, session))
    monkeypatch.setitem(run.__globals__, "refresh_distance_probe", lambda s: calls.append("refresh"))
    monkeypatch.setitem(run.__globals__, 'install_community_export_fix', lambda *a: None)
    if fails:
        with pytest.raises(RuntimeError, match="SDK failure"):
            run(execute=True, refresh=True)
        assert calls == [("deploy", {"wait": False, "force": False}), "close"]
    else:
        run(execute=True, refresh=True)
        assert calls == [("deploy", {"wait": False, "force": False}), "refresh", "close"]




@pytest.mark.parametrize("use_demo", [False, True, "seeds"])
def test_distance_merge_converges_on_cycles_and_matches_bfs(use_demo):
    import duckdb
    import networkx as nx
    from relationalai.semantics.backends.sql.sql_ir import (
        SQLSelectQuery, SQLSelectItem, SQLColumnRef, SQLFromItem, SQLTableSource,
    )
    from relationalai.semantics.backends.sql.emitter import SQLEmitter
    from relationalai.semantics.backends.sql.duckdb_backend import DuckDBBackend
    graph = nx.Graph()
    if use_demo:
        graph.add_edges_from(runner["prepare_oracle"]())
        sources = runner["seed_probe_oracle_rows"]()[0] if use_demo == "seeds" else ["P10034", "P10451"]
    else:
        graph.add_edges_from([("A", "B"), ("B", "C"), ("C", "A"),
                              ("C", "D"), ("D", "E"), ("E", "F"), ("F", "G")])
        graph.add_node("isolated")
        sources = ["A", "G", "isolated"]
    conn = duckdb.connect()
    try:
        conn.execute("CREATE TABLE edges (src VARCHAR, dst VARCHAR)")
        edges = list(graph.edges())
        conn.executemany("INSERT INTO edges VALUES (?, ?)", edges + [(b,a) for a,b in edges])
        conn.execute("CREATE TABLE accum (NODE_U VARCHAR, NODE_V VARCHAR, D INTEGER)")
        conn.executemany("INSERT INTO accum VALUES (?, ?, 0)", [(s,s) for s in sources])
        conn.execute("CREATE TABLE delta AS SELECT * FROM accum")
        q = SQLSelectQuery(select=tuple(SQLSelectItem(SQLColumnRef(c), alias=c)
                                      for c in ("NODE_U", "NODE_V", "D")),
                           from_item=SQLFromItem(source=SQLTableSource("candidates"), alias="c"))
        merged = SQLEmitter(DuckDBBackend(None)).emit_query(runner["minimum_distance_merge"](q))
        for iteration in range(len(graph) + 1):
            conn.execute("CREATE OR REPLACE TABLE candidates AS SELECT * FROM accum UNION ALL "
                         "SELECT delta.NODE_U, edges.dst, delta.D + 1 FROM delta JOIN edges ON delta.NODE_V=edges.src")
            conn.execute("CREATE OR REPLACE TABLE next_accum AS " + merged)
            conn.execute("CREATE OR REPLACE TABLE delta AS SELECT * FROM next_accum EXCEPT SELECT * FROM accum")
            conn.execute("CREATE OR REPLACE TABLE accum AS SELECT * FROM next_accum")
            if conn.execute("SELECT COUNT(*) FROM delta").fetchone()[0] == 0:
                break
        else:
            pytest.fail("Distance recursion did not converge")
        actual = conn.execute("SELECT * FROM accum").fetchall()
        expected = {(s,t,d) for s in sources for t,d in nx.single_source_shortest_path_length(graph,s).items()}
        assert set(actual) == expected
        assert len(actual) == len(expected)
        if use_demo == "seeds":
            result = runner["validate_seed_probe_rows"]([dict(source=s,target=t,hops=d) for s,t,d in actual], sources)
            assert result["seed_count"] == len(sources)
            assert len(actual) == 4300
        elif use_demo:
            runner["validate_fixed_probe_rows"]([dict(source=s,target=t,hops=d) for s,t,d in actual])
            assert len(actual) == 1720
    finally:
        conn.close()


def test_distance_fix_hooks_only_probe_relation_and_restores_sdk(monkeypatch):
    monkeypatch.setitem(runner['deploy_distance_probe'].__globals__, 'PROBE_REASONER', 'sql')
    from relationalai.semantics.backends.sql.lowerer import Lowerer
    from relationalai.semantics.backends.sql.artifacts import Target
    from relationalai.semantics.backends.sql.sql_ir import SQLSelectQuery
    original = Lowerer._coalesce_target_query
    lowerer = object.__new__(Lowerer)
    def deploy(**kwargs):
        for matches in (True, False):
            name = runner["PROBE_OUTPUT"] + ".PERSON_PERSON_NODE_U_AND_PERSON_NODE_V_HAVE_A_DISTANCE_OF_NUMBER_38_0_D" if matches else "OTHER.RELATION"
            target = Target(kind="relation", object_name=name, column_names=("NODE_U", "NODE_V", "D"), key_columns=(), anchor_id=1, relation_ids=(1,))
            query = lowerer._coalesce_target_query(target, [SQLSelectQuery()], has_prior=False, requires_coalesce=True)
            assert bool(query.group_by) == matches
        raise RuntimeError("simulated deployment failure")
    with pytest.raises(RuntimeError, match="simulated"):
        runner["deploy_distance_probe"](SimpleNamespace(deploy=deploy))
    assert Lowerer._coalesce_target_query is original


@pytest.mark.parametrize("source,id_column", [("ROLE_HISTORY", "ROLE_ID"), ("OWNERSHIP", "OWNERSHIP_ID")])
def test_source_date_normalization_in_real_sql_model(monkeypatch, tmp_path, source, id_column):
    from relationalai.config import Config
    from relationalai.semantics import Model, String, Date, Boolean
    monkeypatch.chdir(tmp_path)
    cfg = Config(connections={"local": {"type": "duckdb", "path": ":memory:"}},
                 default_connection="local", deployment={"schema": "outputs", "meta_schema": "meta",
                 "auto_deploy": True, "schedules": {"manual": {"interval_s": 0}},
                 "outputs": {"type": "table", "schedule": "manual"}})
    session = cfg.get_session()
    try:
        session.execute(f"CREATE TABLE {source} ({id_column} VARCHAR, START_DATE DATE, END_DATE DATE)")
        session.executemany(f"INSERT INTO {source} VALUES (?, ?, ?)", [
            ("ended", "2020-01-01", "2022-01-01"), ("open", "2020-01-01", None),
            ("future", "2027-01-01", None), ("today", "2020-01-01", "2026-10-01"),
            ("later", "2020-01-01", "2027-01-01")])
        sql = next(sql for sql in runner["probe_date_views_sql"]() if f".{source}_NORMALIZED" in sql)
        session.execute(sql.replace(runner["PROBE_SOURCE"], "main").replace(runner["PROBE_OUTPUT"], "main"))
        model = Model("dates", config=cfg)
        table = model.Table(source + "_NORMALIZED", schema={id_column: String,
            "START_DATE": Date, "END_DATE": Date, "EFFECTIVE_END_DATE": Date, "IS_CURRENT": Boolean})
        entity = model.Concept("TestRole", identify_by={"id": String})
        entity.effective_end_date = model.Property(f"{entity} ends on {Date:end}")
        entity.is_current = model.Relationship(f"{entity} is current")
        model.define(entity.new(id=getattr(table, id_column)))
        namespace = {"model": model}
        path = Path(__file__).resolve().parents[1] / "pe_deal_graph/model/core.py"
        load_functions(path, {"define_source_dates"}, namespace)
        namespace["define_source_dates"](entity, table, id_column)
        rows = model.select(entity.id.alias("id"), entity.effective_end_date.alias("end")).to_df()
        assert {row["id"]: str(row["end"]) for row in rows.to_dict("records")} == {
            "ended": "2022-01-01", "open": "2026-10-01", "future": "2026-10-01",
            "today": "2026-10-01", "later": "2027-01-01"}
        current = model.where(entity.is_current()).select(entity.id.alias("id")).to_df()
        assert set(current["id"]) == {"open", "later"}
    finally:
        session.close()


def test_lookup_cases_cover_both_materialized_sources():
    cases = runner['distance_lookup_cases']()
    expected = {(r['source'], r['target']): r['hops'] for r in runner['fixed_probe_oracle_rows']()}
    assert len(cases) == 14
    for source in ('P10034', 'P10451'):
        subset = [c for c in cases if c['source'] == source]
        assert {c['expected'] for c in subset} == {0,1,2,3,4,5,None}
        for case in subset:
            assert expected.get((source,case['target'])) == case['expected']
            if case['expected'] == 0: assert case['target'] == source


def test_team_probe_oracle_and_exact_validation():
    seeds, expected = runner['seed_probe_oracle_rows']()
    assert seeds == ['P19079', 'P25319', 'P26028', 'P26070', 'P95007']
    result = runner['validate_seed_probe_rows'](expected, seeds)
    assert result['seed_count'] == len(seeds)
    assert result['reachable_distance_rows'] == 4300
    assert result['nonself_rows'] == 4295
    for invalid in (expected[:-1], expected+[expected[0]], [dict(expected[0],hops=999)]+expected[1:],
                    [dict(expected[0],source='P10034')]+expected[1:]):
        with pytest.raises(RuntimeError): runner['validate_seed_probe_rows'](invalid, seeds)
    with pytest.raises(RuntimeError): runner['validate_seed_probe_rows'](expected,seeds[:-1])


def test_team_probe_keeps_source_bound_and_date_fixes():
    source = (Path(__file__).resolve().parents[1] / 'pe_deal_graph/model/graphs.py').read_text()
    assert 'model.where(OurSeed(Person)).define(probe_sources(Person))' in source
    assert 'probe_distance = knows_graph.distance(from_=probe_sources)' in source
    assert 'Person.id.in_(["P10034", "P10451"])' not in source
    sql = runner['probe_date_views_sql']()
    assert len(sql) == 2
    assert all('EFFECTIVE_END_DATE' in q and 'IS_CURRENT' in q for q in sql)


@pytest.mark.parametrize('fixture,count', [('sparse',200),('connected',49995)])
def test_scale_probe_complete_distance_comparison(fixture,count):
    isolated = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/check_graphs.py'))
    try:
        isolated['select_probe_fixture'](fixture)
        seeds, rows = isolated['seed_probe_oracle_rows']()
        assert len(seeds) == 5 and len(rows) == count
        assert isolated['validate_seed_probe_rows'](rows,seeds)['correctness'] == 'PASS'
        for bad in (rows[:-1], rows+[rows[0]], [dict(rows[0],hops=999)]+rows[1:]):
            with pytest.raises(RuntimeError): isolated['validate_seed_probe_rows'](bad,seeds)
        plan = isolated['prepare_copied_distance_probe']()
        assert not plan['deployment']['auto_deploy']
        assert plan['deployment']['schedules']['path_probe'] == dict(interval_s=0,run_on_deploy=False)
        with pytest.raises(KeyError): isolated['select_probe_fixture']('unrelated')
    finally:
        isolated['select_probe_fixture']('baseline')


def test_community_report_checks_internal_scores_and_isolates():
    import networkx as nx
    from types import SimpleNamespace
    graph = nx.path_graph(['a','b','c','d'])
    graph.add_node('isolated')
    data = SimpleNamespace(person={p:dict(full_name=p) for p in graph})
    # Community 1 is a-b-c; d and the isolate are singleton communities.
    rows = [dict(person_id=p,name=p,community=label,betweenness=score)
            for p,label,score in [('a',1,0),('b',1,1),('c',1,0),('d',2,0),('isolated',3,0)]]
    report = runner['summarize_people_communities'](rows,data,graph)
    assert [c['size'] for c in report['communities']] == [3,1,1]
    assert report['communities'][0]['top_connectors'][0]['person_id'] == 'b'
    assert all(c['all_zero'] for c in report['communities'][1:])
    # Whole-graph score for b is 2, which must be rejected as an internal score.
    for bad in (rows[:-1],rows+[rows[0]],[dict(r,betweenness=2) if r['person_id']=='b' else r for r in rows]):
        with pytest.raises(RuntimeError): runner['summarize_people_communities'](bad,data,graph)


def test_community_definitions_use_actual_sdk_without_execution():
    from relationalai.config import Config
    from relationalai.semantics import Model,String,Integer
    from relationalai.semantics.reasoners.graph import Graph
    cfg = Config(connections={'offline':{'type':'duckdb','path':':memory:'}},default_connection='offline')
    model = Model('community_definition_test',config=cfg)
    person = model.Concept('Person',identify_by={'id':String})
    graph = Graph(model,directed=False,weighted=False,node_concept=person)
    namespace = dict(model=model,Person=person,Graph=Graph,Integer=Integer,
                     LOUVAIN_SEED=42,BETWEENNESS_PIVOTS=16000,knows_graph=graph)
    load_functions(Path(__file__).resolve().parents[1]/'pe_deal_graph/model/graphs.py',
                   {'people_community_relations'},namespace)
    labels, scores = namespace['people_community_relations']()
    assert labels is graph.louvain(max_levels=1, randomization_seed=42)
    assert scores is not None
    for level in (1, 5):
        for seed in (42, 7, 99):
            labels, scores = namespace['people_community_relations'](
                max_levels=level, randomization_seed=seed)
            assert labels is graph.louvain(max_levels=level, randomization_seed=seed)
            assert scores is not None
    for pivots in (100000, 1000000):
        namespace['BETWEENNESS_PIVOTS'] = pivots
        assert namespace['people_community_relations']()[1] is not None
    for options in ({'max_levels': 0}, {'max_levels': 1.5}, {'randomization_seed': -1}):
        with pytest.raises(ValueError):
            namespace['people_community_relations'](**options)


def test_community_score_roundoff_requires_oracle_zero():
    import networkx as nx
    from types import SimpleNamespace
    graph = nx.path_graph(['a','b','c'])
    data = SimpleNamespace(person={p:dict(full_name=p) for p in graph})
    rows = [dict(person_id=p,name=p,community=1,betweenness=v)
            for p,v in [('a',-2e-7),('b',1.0),('c',1e-7)]]
    report = runner['summarize_people_communities'](rows,data,graph)
    assert report['rounded_zero_scores'] == 2
    connectors = report['communities'][0]['top_connectors']
    assert connectors[0]['person_id'] == 'b'
    assert connectors[1]['betweenness'] == 0.0
    assert connectors[1]['raw_betweenness'] == -2e-7
    for invalid in (-0.001, float('nan'), float('inf')):
        with pytest.raises(RuntimeError):
            runner['summarize_people_communities']([dict(rows[0],betweenness=invalid)]+rows[1:],data,graph)


@pytest.fixture(scope='module')
def saved_communities():
    import json
    return json.loads((Path(__file__).resolve().parents[1]/'artifacts/people_communities.json').read_text())


def test_saved_rai_baseline_and_decision_maker_scope(saved_communities, person_oracle):
    data, seeds, graph, nx = person_oracle
    run = saved_communities['saved_rai_runs'][0]
    assert saved_communities['graph_sha256'] == runner['community_graph_fingerprint'](data, graph)
    assert run['parameters'] == runner['community_parameters'](1, 42)
    report = runner['summarize_people_communities'](run['rows'], data, graph)
    assert (report['people'], report['connections'], report['community_count']) == (2506, 2525, 1214)
    assert report['singletons'] == report['graph_isolates'] == 603
    assert report['largest_community'] == 16
    assert report['rounded_zero_scores'] == 36
    assert report['modularity'] == pytest.approx(0.7831627683560435)
    assert sum(size * count for size, count in report['size_distribution'].items()) == 2506
    assert sum(not c['all_zero'] for c in report['communities']) == 235
    oracle = runpy.run_path(str(Path(__file__).resolve().parents[1]/'data/oracle.py'))
    focus = runner['community_focus'](oracle, data, report['communities'])
    assert {s['person_id'] for s in focus['team_seeds']} == seeds
    assert {s['community'] for s in focus['team_seeds']} == {3}
    targets = oracle['q_score'](data, oracle['Thesis'](data))['answer']['tier_a_ids']
    assert {p['target_id'] for p in focus['decision_makers']} == set(targets)
    assert len(focus['decision_makers']) == 9
    assert sum(p['kind'] == 'OWNER_DESIGNEE' for p in focus['decision_makers']) == 3
    assert {p['community'] for p in focus['decision_makers'] if p['target_id'] == 'C3225'} == {9}
    assert focus['communities'][0]['top_connectors'][0]['person_id'] == 'P26070'


def test_partition_agreement_ignores_labels_and_adjusts_for_chance():
    ari = runner['adjusted_rand_index']
    left = dict(zip('abcd', [1, 1, 2, 2]))
    relabeled = dict(zip('abcd', [8, 8, 9, 9]))
    crossed = dict(zip('abcd', [8, 9, 8, 9]))
    assert ari(left, relabeled, left) == 1
    assert ari(left, crossed, left) == pytest.approx(-0.5)
    assert ari(left, crossed, ['a']) == 1
    assert ari(dict(zip('abcd', range(4))), dict(zip('abcd', range(4))), left) == 1


def test_decision_maker_scope_excludes_minority_owner_and_duplicate_ceo():
    data = SimpleNamespace(
        pname=lambda p: p,
        fund={'major': {'name': 'Major fund', 'sponsor_id': 'A'},
              'minor': {'name': 'Minor fund', 'sponsor_id': 'B'}},
        current_ownerships=lambda c: [dict(fund_id='major', stake_type='majority'),
                                      dict(fund_id='minor', stake_type='minority')],
        current_roles_at=lambda sponsor, roles: [dict(person_id=p) for p in
                                                 (['ceo', 'owner'] if sponsor == 'A' else ['minor'])],
        org_name=lambda s: s)
    oracle = dict(T='2026-10-01', our_seeds=lambda d: [], Thesis=lambda d: None,
                  q_score=lambda d, t: {'answer': {'tier_a': [dict(company_id='target', name='Target', score=70)]}},
                  decision_makers=lambda d, c: [dict(person_id=p, kind=k) for p, k in
                      [('ceo', 'CEO'), ('ceo', 'OWNER_DESIGNEE'), ('owner', 'OWNER_DESIGNEE'),
                       ('minor', 'OWNER_DESIGNEE')]])
    summary = [dict(community=1, person_ids=['ceo', 'owner', 'minor'])]
    focus = runner['community_focus'](oracle, data, summary)
    assert [(p['person_id'], p['kind']) for p in focus['decision_makers']] == [
        ('ceo', 'CEO'), ('owner', 'OWNER_DESIGNEE')]
    assert focus['decision_makers'][1]['via'] == 'Major fund (A)'


def test_community_exact_settings_and_tolerance():
    import networkx as nx
    graph = nx.path_graph(['a', 'b', 'c'])
    data = SimpleNamespace(person={p: dict(full_name=p) for p in graph})
    rows = [dict(person_id=p, name=p, community=1, betweenness=v)
            for p, v in [('a', -1e-5), ('b', 1), ('c', 0)]]
    report = runner['summarize_people_communities'](rows, data, graph)
    assert report['centrality'] == dict(mode='exact', normalized=False, weight=None,
                                       endpoints=False, rai_num_pivots=16000, networkx_k=None)
    assert report['max_absolute_score_error'] == 1e-5
    with pytest.raises(RuntimeError, match='differs from oracle'):
        runner['summarize_people_communities']([dict(rows[0], betweenness=-1.1e-5)]+rows[1:], data, graph)
    with pytest.raises(RuntimeError, match='Sampled centrality'):
        runner['summarize_people_communities'](rows, data, graph, parameters={'num_pivots': 2})
    # For large scores the relative tolerance is material; this path's center has score 100.
    graph = nx.path_graph([str(i) for i in range(21)])
    data = SimpleNamespace(person={p: dict(full_name=p) for p in graph})
    scores = nx.betweenness_centrality(graph, normalized=False)
    rows = [dict(person_id=p, name=p, community=1, betweenness=v) for p, v in scores.items()]
    rows[10]['betweenness'] += 0.00019
    runner['summarize_people_communities'](rows, data, graph)
    rows[10]['betweenness'] += 0.00002
    with pytest.raises(RuntimeError, match='differs from oracle'):
        runner['summarize_people_communities'](rows, data, graph)


def test_offline_community_entrypoint_never_imports_live_clients(monkeypatch, tmp_path, capsys):
    import builtins
    import json
    import sys
    root = Path(__file__).resolve().parents[1]
    entry = runpy.run_path(str(root/'scripts/guarded_people_count.py'))
    original_import = builtins.__import__
    def local_import(name, *args, **kwargs):
        if name.startswith(('relationalai', 'v0.relationalai', 'snowflake', 'pe_deal_graph.model')):
            raise AssertionError('Offline analysis tried to import a live client/model: '+name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', local_import)
    monkeypatch.syspath_prepend(str(root/'scripts'))
    output = tmp_path/'comparison.json'
    monkeypatch.setattr(sys, 'argv', ['guarded_knows_count.py', '--communities',
        '--louvain-max-levels', '1', '5', '--louvain-seeds', '42', '7', '99',
        '--community-output', str(output)])
    entry['main'](query_kind='knows')
    result = json.loads(output.read_text())['analysis']
    assert len(result['runs']) == 7
    assert len(result['pending_rai_runs']) == 5
    assert all(r['status'] == 'requires live execution' for r in result['pending_rai_runs'])
    assert len([s for s in result['stability'] if s['kind'] == 'seed stability']) == 6
    assert all(r['singletons'] == 603 for r in result['runs'])
    assert 'OFFLINE COMMUNITY ANALYSIS' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        entry['main'](query_kind='knows')  # Refuse to overwrite saved evidence.


def test_saved_community_fingerprint_and_score_corruption_fail(saved_communities, tmp_path, monkeypatch):
    import copy
    import json
    analyze = runner['analyze_people_communities']
    def forbidden(*a, **kw):
        raise AssertionError('Live execution is forbidden')
    monkeypatch.setitem(analyze.__globals__, 'run_people_communities', forbidden)
    pairs = runner['prepare_oracle']()
    source = tmp_path/'saved.json'
    for corruption in ('graph', 'score', 'parameters'):
        saved = copy.deepcopy(saved_communities)
        if corruption == 'graph':
            saved['graph_sha256'] = 'stale'
        elif corruption == 'score':
            saved['saved_rai_runs'][0]['rows'][0]['betweenness'] = 999
        else:
            saved['saved_rai_runs'][0]['parameters']['max_sweeps'] = 21
        source.write_text(json.dumps(saved))
        with pytest.raises(RuntimeError):
            analyze(pairs, [1], [42], source)


def test_mocked_live_comparison_reuses_saved_run_and_checkpoints_before_validation(
        saved_communities, tmp_path, monkeypatch, capsys):
    import copy
    import json
    root = Path(__file__).resolve().parents[1]
    analyze = runner['analyze_people_communities']
    calls = []
    def fake_run(pairs, *, max_levels, randomization_seed):
        calls.append((max_levels, randomization_seed))
        run = copy.deepcopy(saved_communities['saved_rai_runs'][0])
        run['parameters'] = runner['community_parameters'](max_levels, randomization_seed)
        return run
    monkeypatch.setitem(analyze.__globals__, 'run_people_communities', fake_run)
    output = tmp_path/'live_mock.json'
    result = analyze(runner['prepare_oracle'](), [1, 5], [42], root/'artifacts/people_communities.json',
                     execute=True, output_path=output)
    assert calls == [(5, 42)]
    assert len(result['saved_rai_runs']) == 2
    assert not result['analysis']['pending_rai_runs']
    assert len(json.loads(output.read_text())['saved_rai_runs']) == 2
    def corrupt_run(*a, **kw):
        run = fake_run(*a, **kw)
        run['rows'][0]['betweenness'] = 999
        return run
    monkeypatch.setitem(analyze.__globals__, 'run_people_communities', corrupt_run)
    output = tmp_path/'failed_mock.json'
    with pytest.raises(RuntimeError, match='differs from oracle'):
        analyze(runner['prepare_oracle'](), [5], [42], root/'artifacts/people_communities.json',
                execute=True, output_path=output)
    assert json.loads(output.read_text())['saved_rai_runs'][-1]['rows'][0]['betweenness'] == 999
    capsys.readouterr()


def test_community_deployment_is_isolated_manual_logic():
    config = runner['prepare_community_probe']()
    distance = runner['prepare_copied_distance_probe']()['deployment']
    assert config['schema'] != distance['schema']
    assert config['meta_schema'] != distance['meta_schema']
    assert config['outputs']['reasoner'] == 'logic'
    assert config['schedules'] == {'community_baseline': {'interval_s': 0, 'run_on_deploy': False}}
    assert config['auto_deploy'] is False


def test_deployment_validation_requires_fresh_complete_graph(saved_communities):
    run = saved_communities['saved_rai_runs'][0]
    edges = [dict(p1=a, p2=b) for a, b in runner['prepare_oracle']()]
    report = runner['validate_community_deployment_rows'](run['rows'], edges)
    assert (report['people'], report['community_count']) == (2506, 1214)
    with pytest.raises(RuntimeError, match='Knows graph differs'):
        runner['validate_community_deployment_rows'](run['rows'], edges[:-1])
    with pytest.raises(RuntimeError, match='Incomplete community membership'):
        runner['validate_community_deployment_rows'](run['rows'][:-1], edges)


@pytest.mark.parametrize('column,quoted', [
    ('id', '"ID"'),
    ('Person_node__has_non-rescaled_betweenness_centrality_value__Float_centrality',
     '"Person_node__has_non-rescaled_betweenness_centrality_value__Float_centrality"'),
    ('a"b', '"a""b"'),
    ('"MixedCase"', '"MixedCase"'),
])
def test_export_fix_quotes_stage_and_projection_without_changing_values(tmp_path, column, quoted):
    """Execute the real helper JS against a mock Snowflake transport, including cleanup."""
    import json
    import shutil
    import subprocess
    engine = shutil.which('node') or '/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc'
    if not Path(engine).exists(): pytest.skip('JavaScript runtime unavailable')
    original, fixed = runner['community_export_procedure_sql']()
    assert original.count('JSON.stringify(columnFields)') == 1
    spec = dict(destination_fqn='OUT.RESULT', export_filename='export_test',
                column_fields=[[column, 'DOUBLE']], actual_cols=[column], declared_cols=[column, 'absent'])
    harness = '''var calls = [];
var snowflake = {execute: function (opts) {
    calls.push(opts.sqlText);
    return {next: function () {return true;}, getColumnValue: function () {return 1;}};
}};
'''
    harness += 'var EXPORT_SPEC_JSON = ' + json.dumps(json.dumps(spec)) + ';\n'
    harness += 'var BLOCK_INDEX=1, TXN_ID="existing_txn";\n'
    harness += '(function () {\n' + fixed.split('$$')[1] + '\n})();\n'
    harness += ('console.log' if Path(engine).name == 'node' else 'print') + '(JSON.stringify(calls));\n'
    script = tmp_path / 'export.js'; script.write_text(harness)
    result = subprocess.run([engine, str(script)], check=True, capture_output=True, text=True)
    calls = json.loads(result.stdout.strip())
    assert len(calls) == 4
    # SQL string-literal escaping happens after identifier quoting.
    escaped_fields = json.dumps([[quoted, 'DOUBLE']], separators=(',', ':')).replace('\\', '\\\\').replace("'", "''")
    assert escaped_fields in calls[0]
    assert quoted + ' as ' + quoted in calls[2]
    assert 'NULL as "ABSENT"' in calls[2]
    assert calls[3] == "CALL RELATIONALAI.api.drop_result_table('export_test_table')"


def test_scale_targets_preserve_baseline_and_separate_community_outputs():
    isolated=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/check_graphs.py'))
    isolated['select_probe_fixture']('connected1m')
    assert isolated['prepare_copied_distance_probe']()['output'].endswith('CONNECTED_1M_LOGIC')
    isolated['select_probe_fixture']('connected100k')
    p=isolated['prepare_copied_distance_probe']()
    assert p['source'].endswith('CONNECTED_100K_SRC')
    assert p['output'].endswith('CONNECTED_100K_LOGIC')
    isolated['select_community_fixture']('connected')
    c=isolated['prepare_community_probe']()
    assert c['schema'].endswith('CONNECTED_10K_COMMUNITY')
    assert c['outputs']['reasoner']=='logic'
    assert c['schedules']['community_baseline']==dict(interval_s=0,run_on_deploy=False)
    isolated['select_community_fixture']('connected100k')
    assert isolated['prepare_community_probe']()['schema'].endswith('CONNECTED_100K_COMMUNITY')
    assert isolated['deployed_community_parameters']()['num_pivots'] == 100000
    isolated['select_community_fixture']('connected1m')
    assert isolated['prepare_community_probe']()['schema'].endswith('CONNECTED_1M_COMMUNITY')
    assert isolated['deployed_community_parameters']()['num_pivots'] == 1000000
    with pytest.raises(ValueError):isolated['select_community_fixture']('sparse')
    isolated['select_community_fixture']('baseline')
    assert isolated['prepare_community_probe']()['schema'] == _cfg.schema('COMMUNITY')
    assert isolated['deployed_community_parameters']()['num_pivots'] == 16000


def test_seed_lookup_benchmark_cases_include_each_source_and_unreachable():
    seeds=['a','b'];rows=[dict(source=s,target=s,hops=0) for s in seeds]
    rows += [dict(source=s,target=f'{s}{h}',hops=h) for s in seeds for h in range(1,6)]
    cases=runner['seed_lookup_cases'](seeds,rows,{r['target'] for r in rows}|{'isolated'})
    assert len(cases)==14
    expected={(r['source'],r['target']):r['hops'] for r in rows}
    for s in seeds:
        assert {c['expected'] for c in cases if c['source']==s}=={0,1,2,3,4,5,None}
    for c in cases:
        assert expected.get((c['source'],c['target']))==c['expected']
    with pytest.raises(RuntimeError):runner['seed_lookup_cases'](seeds,rows[:-1],set())


def test_community_deployment_parameters_keep_scale_and_demo_separate():
    isolated=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/check_graphs.py'))
    ns=isolated['deployed_community_parameters'].__globals__
    ns['COMMUNITY_LEVELS'],ns['COMMUNITY_SEED']=5,7
    assert isolated['deployed_community_parameters']()==isolated['community_parameters'](5,7)
    isolated['select_community_fixture']('connected1m')
    p=isolated['deployed_community_parameters']()
    assert (p['max_levels'],p['randomization_seed'],p['num_pivots'])==(5,7,1000000)
    with pytest.raises(ValueError):isolated['run_community_probe'](redeploy=True)


def test_reduced_exports_leave_logic_body_unchanged():
    schema = f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_CONNECTED_100K_COMMUNITY_LEAN'
    body = 'unchanged Logic payload and transaction;\ntracer.startActiveSpan("export_results", function (span) {\nexport();\n});'
    changed = runner['reduced_community_export_body'](body, schema)
    assert changed.startswith('unchanged Logic payload and transaction;\n')
    assert changed.endswith('tracer.startActiveSpan("export_results", function (span) {\nexport();\n});')
    assert schema + '.KNOWS' in changed and schema + '.PERSONCOMMUNITYPROBE' in changed
    with pytest.raises(ValueError):
        runner['reduced_community_export_body'](body, schema.replace('_LEAN', ''))
    with pytest.raises(RuntimeError):
        runner['reduced_community_export_body'](changed, schema)


def test_scale_community_settings_have_separate_targets():
    isolated = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_graphs.py"))
    select = isolated['select_community_fixture']
    g = select.__globals__
    select('connected100k')
    original = g['COMMUNITY_OUTPUT']
    source = g['PROBE_SOURCE']
    g['COMMUNITY_LEVELS'], g['COMMUNITY_SEED'] = 5, 7
    select('connected100k')
    assert g['COMMUNITY_OUTPUT'] == original + '_L5_S7'
    assert g['COMMUNITY_META'] == g['COMMUNITY_OUTPUT'] + '_META'
    assert g['PROBE_SOURCE'] == source
    assert isolated['deployed_community_parameters']()['num_pivots'] == 100000
