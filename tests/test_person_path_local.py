"""On-demand employment paths: no Snowflake, RAI configuration or stored graph."""
import csv
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pe_deal_graph.person_path import PersonPaths


def make_data(tmp_path, roles):
    people = sorted({r[1] for r in roles} | {"ISOLATED"})
    tables = {
        "PERSON": (["person_id", "full_name"], [(p, p) for p in people]),
        "ROLE_HISTORY": (["role_id", "person_id", "org_id", "role_type", "start_date", "end_date"], roles),
        "CRM_INTERACTION": (["interaction_id"], []),
    }
    for table, (fields, rows) in tables.items():
        with (tmp_path / f"{table}.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(rows)
    return PersonPaths(tmp_path)


def edge_roles(a, b, start="2020-01-01", end="", org=None):
    org = org or a + b
    return [(org + a, a, org, "CEO", start, end), (org + b, b, org, "CEO", start, end)]


def test_strongest_shortest_and_multiple_role_evidence(tmp_path):
    roles = edge_roles("A", "B", "2025-01-01") + edge_roles("B", "D")
    roles += edge_roles("A", "C") + edge_roles("C", "D")
    roles += edge_roles("A", "C", "2024-01-01", org="ACsecond")
    graph = make_data(tmp_path, roles)
    result = graph.query("A", "D")
    assert result["route"] == ["A", "C", "D"]
    assert result["shortest_route_count"] == 2  # Multiple jobs do not multiply person routes.
    assert result["route_strength"] == 1
    assert len(result["hops"][0]["evidence"]) == 2
    assert graph.query("D", "A")["route"] == ["D", "C", "A"]


def test_shortest_before_strength_and_threshold_changes_answer(tmp_path):
    graph = make_data(tmp_path, edge_roles("A", "D", "2025-01-01") +
                      edge_roles("A", "B") + edge_roles("B", "D"))
    assert graph.query("A", "D")["route"] == ["A", "D"]
    assert graph.query("A", "D", min_strength=0.9)["route"] == ["A", "B", "D"]
    assert graph.query("A", "D", min_strength=0.9, max_hops=1)["status"] == "beyond_max_hops"


def test_same_employer_requires_365_days_and_applies_recency(tmp_path):
    roles = [("a", "A", "O", "Board", "2000-01-01", "2001-01-01"),
             ("b", "B", "O", "Board", "2000-01-02", "2001-01-01"),
             ("c", "C", "O", "Board", "2000-01-03", "2001-01-01")]
    graph = make_data(tmp_path, roles)
    result = graph.query("A", "B")
    assert result["distance"] == 1
    assert result["route_strength"] == pytest.approx(0.4 * (0.4 + 0.15 * 365 / 365.25))
    assert result["hops"][0]["evidence"][0]["relationship"] == "board co-service"
    assert graph.query("A", "C")["status"] == "unreachable"


def test_missing_self_isolated_and_hop_limit(tmp_path):
    graph = make_data(tmp_path, edge_roles("A", "B"))
    assert graph.query("MISSING", "MISSING")["status"] == "unknown_person"
    assert graph.query("A", "A")["distance"] == 0
    assert graph.query("A", "B", max_hops=0)["status"] == "beyond_max_hops"
    assert graph.query("A", "ISOLATED")["status"] == "unreachable"
    assert graph.query("ISOLATED", "A")["status"] == "unreachable"


def test_equal_scores_have_stable_lexical_route(tmp_path):
    graph = make_data(tmp_path, edge_roles("A", "C") + edge_roles("C", "D") +
                      edge_roles("A", "B") + edge_roles("B", "D"))
    assert graph.query("A", "D")["route"] == ["A", "B", "D"]
    assert graph.query("A", "D")["shortest_route_count"] == 2


def test_no_connections_or_distances_precomputed(tmp_path, monkeypatch):
    graph = make_data(tmp_path, edge_roles("A", "B") + edge_roles("B", "C"))
    calls = []
    original = graph._connections
    def counted(person, stats):
        calls.append(person)
        return original(person, stats)
    monkeypatch.setattr(graph, "_connections", counted)
    assert calls == []
    graph.query("A", "B")
    assert calls == ["A"]
    graph.query("A", "B")
    assert calls == ["A", "A"]  # Derive again rather than return a cached result.


def test_rejects_unimplemented_connection_rules(tmp_path):
    make_data(tmp_path, edge_roles("A", "B"))
    (tmp_path / "CRM_INTERACTION.csv").write_text("interaction_id\nCRM1\n")
    with pytest.raises(ValueError, match="K1 roles only"):
        PersonPaths(tmp_path)


@pytest.mark.parametrize("kwargs", [{"max_hops": -1}, {"max_hops": 1.5},
                                    {"min_strength": float("nan")}, {"min_strength": 1.1}])
def test_invalid_search_parameters(tmp_path, kwargs):
    graph = make_data(tmp_path, edge_roles("A", "B"))
    with pytest.raises(ValueError):
        graph.query("A", "B", **kwargs)


def validate_connected_10k():
    """Repeat the recorded 82-case oracle comparison without contacting any service."""
    import hashlib
    import json
    import math
    import random
    import runpy
    import statistics
    import time
    import networkx as nx
    ROOT = Path(__file__).resolve().parents[1]
    directory = ROOT / 'data/scale_connected_10k'
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.csv')}
    started = time.perf_counter()
    query = PersonPaths(directory)
    load_seconds = time.perf_counter() - started
    manifest = json.loads((directory / 'MANIFEST.json').read_text())
    
    # The full oracle graph exists only in this verification program. The query module
    # does not import it and receives no oracle graph, edge table or distance results.
    oracle = runpy.run_path(str(ROOT / 'data/oracle.py'))
    oracle['load_csv'].__globals__['CSV_DIR'] = directory
    data = oracle['Data']()
    assert not data.manifest_mismatches, data.manifest_mismatches
    pairs = oracle['build_knows'](data, set(oracle['our_seeds'](data)), include_evidence=False)
    full = oracle['knows_graph'](data, pairs)
    assert len(full) == 10000 and full.number_of_edges() == 131904
    
    cases = [(e['source'], e['target'], 12, 0.0) for e in manifest['examples'] + manifest['team_examples']]
    rng = random.Random(42)
    people = sorted(query.people)
    cases += [(*rng.sample(people, 2), 12, 0.0) for _ in range(40)]
    cases += [(b, a, cap, w) for a, b, cap, w in cases[14:18]]
    cases += [(a, b, 12, w) for a, b, _, _ in cases[14:24] for w in (0.75, 1.0)]
    cases += [('P19079', 'SCALE_P000000004', 3, 0.0),
              ('P19079', 'P19079', 0, 0.0),
              ('P19079', 'MISSING', 12, 0.0), ('MISSING', 'MISSING', 12, 0.0)]
    
    results = []
    for source, target, cap, threshold in cases:
        result = query.query(source, target, max_hops=cap, min_strength=threshold)
        graph = nx.subgraph_view(full, filter_edge=lambda a, b: full[a][b]['strength'] >= threshold)
        status = result['status']
        if source not in graph or target not in graph:
            assert status == 'unknown_person', result
        else:
            try:
                want = nx.shortest_path_length(graph, source, target)
            except nx.NetworkXNoPath:
                want = None
            if want is None:
                assert status in ('unreachable', 'beyond_max_hops'), result
            elif want > cap:
                assert status == 'beyond_max_hops', result
            else:
                assert status == ('self' if source == target else 'reachable'), result
                assert result['distance'] == want, result
                paths = list(nx.all_shortest_paths(graph, source, target))
                scored = [(math.prod(full[a][b]['strength'] for a, b in zip(p, p[1:])), p) for p in paths]
                strength, path = min(scored, key=lambda x: (-x[0], x[1]))
                assert result['route'] == path, (result, path)
                assert result['shortest_route_count'] == len(paths), result
                assert math.isclose(result['route_strength'], strength, abs_tol=1e-12), result
                assert result['route_names'] == [query.people[p] for p in path]
                for hop in result['hops']:
                    a, b = hop['from'], hop['to']
                    assert math.isclose(hop['strength'], full[a][b]['strength'], abs_tol=1e-12)
                    assert hop['evidence'] and all(e['overlap_days'] >= 365 for e in hop['evidence'])
        results.append(result)
    
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.csv')}
    times = [r['query_seconds'] for r in results]
    reachable = [r for r in results if r['status'] == 'reachable']
    report = {
        'method': 'Local Python; on-demand K1 relationships from raw CSV roles; no saved graph or distances',
        'scope': 'K1 tenure/board overlap only; nonempty CRM/deal input is rejected',
        'people': len(query.people), 'roles': query.role_count,
        'oracle_connections_validation_only': full.number_of_edges(),
        'csv_load_and_index_seconds': load_seconds,
        'cases_passed': len(results),
        'query_seconds_median_all_cases': statistics.median(times),
        'query_seconds_median_reachable': statistics.median(r['query_seconds'] for r in reachable),
        'query_seconds_max': max(times),
        'people_expanded_median_reachable': statistics.median(r['search']['people_expanded'] for r in reachable),
        'source_csv_unchanged': True, 'source_sha256': before,
        'validation': 'Independent data/oracle.py graph plus NetworkX exhaustive shortest routes. Checks distance, strongest product, tie ordering, route count, each edge and names. Oracle used only by validator.',
        'limitations': ['Local 10K fixture, not a RAI or Snowflake benchmark',
                        'Data indexes loaded once; no result or neighbor cache between requests',
                        'Unreachable searches can inspect the full reachable component',
                        'K2 deals and K3 CRM not implemented in this local prototype'],
        'cases': results,
    }
    return report


def test_connected_10k_against_independent_oracle():
    report = validate_connected_10k()
    assert report['cases_passed'] == 82
    assert report['source_csv_unchanged']


def test_community_scores_only_requested_group_and_reuses_it(tmp_path, monkeypatch):
    import networkx as nx
    from pe_deal_graph.person_path import CommunityConnectors
    records = make_data(tmp_path, edge_roles('A', 'B') + edge_roles('B', 'C') +
                        edge_roles('C', 'D') + edge_roles('D', 'E'))
    monkeypatch.setattr(nx.community, 'louvain_communities',
                        lambda *a, **kw: [{'A', 'B', 'C'}, {'D', 'E'}, {'ISOLATED'}])
    calls = []
    original = nx.betweenness_centrality
    def counted(graph, **kwargs):
        calls.append(set(graph))
        return original(graph, **kwargs)
    monkeypatch.setattr(nx, 'betweenness_centrality', counted)
    analysis = CommunityConnectors(records)
    assert calls == []
    result = analysis.query('A', top=1)
    assert result['leaders'] == [{'person_id': 'B', 'name': 'B', 'betweenness': 1.0}]
    assert not result['cache_hit']
    assert analysis.query('C')['cache_hit']
    assert calls == [{'A', 'B', 'C'}]
    assert analysis.query('D')['communities_scored_so_far'] == 2
    assert calls == [{'A', 'B', 'C'}, {'D', 'E'}]
    # A new snapshot starts without scores, even for the same person.
    assert not CommunityConnectors(records).query('A')['cache_hit']


def test_community_isolate_ties_unknown_and_empty_edges(tmp_path):
    from pe_deal_graph.person_path import CommunityConnectors
    analysis = CommunityConnectors(make_data(tmp_path, []))
    assert analysis.query('ISOLATED')['person_betweenness'] == 0
    assert analysis.query('ISOLATED')['community_size'] == 1
    with pytest.raises(ValueError, match='Unknown person'):
        analysis.query('MISSING')
    with pytest.raises(ValueError, match='positive integer'):
        analysis.query('ISOLATED', top=0)


def validate_requested_community_10k():
    """Verify one requested community using the literal shortest-path definition."""
    from collections import defaultdict
    import hashlib
    from itertools import combinations
    import math
    import networkx as nx
    import runpy
    import time
    from pe_deal_graph.person_path import CommunityConnectors
    root = Path(__file__).resolve().parents[1]
    directory = root / 'data/scale_connected_10k'
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.csv')}
    start = time.perf_counter()
    records = PersonPaths(directory)
    load_seconds = time.perf_counter() - start
    source, target = 'P19079', 'SCALE_P000004200'
    route = records.query(source, target)
    analysis = CommunityConnectors(records, max_levels=5, seed=7)
    assert not analysis._scores
    first = analysis.query(target)
    repeated = analysis.query(target)
    members = analysis._groups[first['community_id']]
    other_member = next(p for p in sorted(members) if p != target)
    another_person = analysis.query(other_member)
    assert not first['cache_hit'] and repeated['cache_hit'] and another_person['cache_hit']
    assert len(analysis._scores) == 1
    assert first['leaders'] == repeated['leaders']

    oracle = runpy.run_path(str(root / 'data/oracle.py'))
    oracle['load_csv'].__globals__['CSV_DIR'] = directory
    data = oracle['Data']()
    assert not data.manifest_mismatches
    pairs = oracle['build_knows'](data, set(oracle['our_seeds'](data)), include_evidence=False)
    reference = oracle['knows_graph'](data, pairs)
    assert len(analysis._membership) == len(reference) == 10000
    assert analysis._graph.number_of_edges() == reference.number_of_edges() == 131904
    for (a, b), edge in pairs.items():
        assert analysis._graph.has_edge(a, b)
        assert analysis._graph[a][b]['strength'] == edge['strength']
    assert route['distance'] == nx.shortest_path_length(reference, source, target)
    route_scores = [math.prod(reference[a][b]['strength'] for a,b in zip(p,p[1:]))
                    for p in nx.all_shortest_paths(reference, source, target)]
    assert route['route_strength'] == max(route_scores)
    assert route['shortest_route_count'] == len(route_scores)

    # Independent scoring procedure: enumerate all shortest paths for each unordered
    # pair in this community, and divide each internal person's contributions by
    # the number of tied shortest paths. No centrality function is used here.
    group = reference.subgraph(members)
    expected = defaultdict(float)
    checked_pairs = 0
    for a, b in combinations(sorted(members), 2):
        try:
            paths = list(nx.all_shortest_paths(group, a, b))
        except nx.NetworkXNoPath:
            continue
        checked_pairs += 1
        for path in paths:
            for p in path[1:-1]:
                expected[p] += 1 / len(paths)
    scores = analysis._scores[first['community_id']]
    worst_error = max(abs(scores[p] - expected[p]) for p in members)
    assert worst_error < 1e-8, worst_error
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.csv')}
    return {'execution': 'local Python / NetworkX, K1-only raw CSV sample',
            'csv_load_and_index_seconds': load_seconds, 'route': route,
            'community_preparation': analysis.preparation, 'first_community_request': first,
            'repeat_community_request': repeated, 'same_community_other_person': another_person,
            'validation': {'all_graph_edges_match_oracle': True, 'route_matches_oracle': True,
                           'community_scores_checked': len(scores), 'unordered_pairs_checked': checked_pairs,
                           'method': 'exhaustive shortest-path contributions on independently derived edges',
                           'max_abs_error': worst_error, 'only_one_community_scored': len(analysis._scores) == 1,
                           'input_csv_unchanged': True},
            'cache_scope': 'This in-memory snapshot only; new process or changed data requires a new instance.'}


def test_requested_community_10k():
    report = validate_requested_community_10k()
    assert report['validation']['only_one_community_scored']


def test_saved_1m_community_query_reuses_membership_and_exact_scores(monkeypatch):
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('path_runner_test', root / 'scripts/person_path_proc.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    class Cursor:
        def __init__(self):
            self.edge_reads = 0
        def execute(self, sql, params=()):
            if 'SELECT COMMUNITY' in sql:
                self.rows = [(7,)]
            elif 'SELECT C.ID' in sql:
                self.rows = [('A', 'Alice', 0.25, 1), ('B', 'Bob', 0.5, 1), ('C', 'Carol', 0.25, 1)]
            elif 'SELECT K.P1' in sql:
                self.edge_reads += 1
                self.rows = [('A', 'B'), ('B', 'C')]
            else:
                raise AssertionError(sql)
            return self
        def fetchone(self):
            return self.rows[0] if self.rows else None
        def fetchall(self):
            return self.rows
    class Connection:
        def __init__(self):
            self.cur = Cursor()
        def cursor(self):
            return self.cur
    con = Connection()
    lookup = runner.SavedCommunity1M(con)
    saved = lookup.query('A')
    assert saved['sampled_people'] == 3 and saved['communities_calculated_locally'] == 0
    assert con.cur.edge_reads == 0
    exact = lookup.query('A', exact=True)
    assert exact['leaders'][0]['id'] == 'B' and exact['leaders'][0]['score'] == 1.0
    assert exact['sampled_people'] == 0 and not exact['cache_hit']
    assert lookup.query('C', exact=True)['cache_hit']
    assert con.cur.edge_reads == 1
    assert runner.SavedCommunity1M(con).query('A', exact=True)['cache_hit'] is False
    assert con.cur.edge_reads == 2
