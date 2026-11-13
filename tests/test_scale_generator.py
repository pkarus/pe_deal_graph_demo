"""Local generator tests: no model imports, Snowflake sessions, or RAI execution."""
import csv
import hashlib
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
generator = runpy.run_path(str(ROOT / "data/generate.py"))


def hashes(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("people,size", [(7, 2), (31, 8), (100, 4)])
def test_scale_oracle_and_determinism(tmp_path, people, size):
    before = {d: hashes(ROOT / "data" / d) for d in ("csv", "golden")}
    a, b = tmp_path / "a", tmp_path / "b"
    m = generator["write_scale"](a, people, size)
    generator["write_scale"](b, people, size)
    assert hashes(a) == hashes(b)
    checked = generator["check_scale"](a)
    assert checked["people"] == people
    assert checked["roles"] == people + 4
    assert checked["connections"] == m["expected_connections"]
    assert checked["examples_verified"] == 6
    assert checked["largest_component"] <= max(6, size)
    assert checked["max_degree"] <= max(2, size - 1)
    assert before == {d: hashes(ROOT / "data" / d) for d in before}
    for table, (pk, _) in generator["TABLES"].items():
        with (a / f"{table}.csv").open() as f:
            rows = list(csv.DictReader(f))
        assert len({tuple(r[k] for k in pk) for r in rows}) == len(rows)


def test_scale_refuses_overwrites_and_demo_paths(tmp_path):
    with pytest.raises(FileExistsError):
        generator["write_scale"](tmp_path)
    for directory in (ROOT / "data/csv", ROOT / "data/golden", ROOT / "data/csv/scale"):
        with pytest.raises(ValueError, match="demo"):
            generator["write_scale"](directory)
    for people, size in [(6, 8), (1_000_001, 8), (100, 1), (100, 33)]:
        with pytest.raises(ValueError):
            generator["write_scale"](tmp_path / "invalid", people, size)
    assert not (tmp_path / "invalid").exists()


def test_scale_detects_modified_data(tmp_path):
    out = tmp_path / "fixture"
    generator["write_scale"](out, 20)
    p = out / "ROLE_HISTORY.csv"
    p.write_text(p.read_text().replace("2020-01-01", "2026-09-01"))
    with pytest.raises(ValueError, match="sha256"):
        generator["check_scale"](out)


def test_scale_options_require_opt_in():
    for args in (["--people", "10000"], ["--workplace-size=8"], ["--seed", "42"]):
        with pytest.raises(ValueError, match="require --scale"):
            generator["main"](args)


@pytest.mark.parametrize('people,size', [(20,6), (100,8), (300,16)])
def test_connected_fixture_paths_team_density_and_determinism(tmp_path, people, size):
    before = {d: hashes(ROOT / 'data' / d) for d in ('csv','golden','scale_10k')}
    a,b = tmp_path/'connected_a',tmp_path/'connected_b'
    manifest = generator['write_scale'](a, people, size, connected=True)
    generator['write_scale'](b, people, size, connected=True)
    assert hashes(a) == hashes(b)
    result = generator['check_scale'](a)
    assert result['people'] == people
    assert 2*people <= result['roles'] <= 4*people
    assert result['seed_ids'] == ['P19079','P25319','P26028','P26070','P95007']
    assert result['seed_count'] == 5
    assert result['largest_component'] == people-1
    assert result['component_count'] == 2 and result['isolated_people'] == 1
    assert result['examples_verified'] == 7
    assert result['team_examples_verified'] == 7
    assert {e['hops'] for e in result['team_examples']} == {0,1,2,3,4,5,None}
    assert {e['hops'] for e in result['examples']} == {0,1,2,3,4,5,None}
    assert set(result['roles_per_person']) <= {2,3,4}
    assert max(result['workplace_sizes']) <= size
    assert result['max_degree'] <= 4*(size-1)
    assert result['overlapping_movers'] == people
    assert result['connections'] == manifest['expected_connections']
    assert before == {d: hashes(ROOT/'data'/d) for d in before}
    # Root removal isolates the planted path from all career-move densification.
    import networkx as nx
    oracle = runpy.run_path(str(ROOT/'data/oracle.py'))
    oracle['load_csv'].__globals__['CSV_DIR'] = a
    data = oracle['Data']()
    graph = oracle['knows_graph'](data,oracle['build_knows'](data,set(oracle['our_seeds'](data))))
    protected = manifest['protected_path']
    graph.remove_node(protected[0])
    assert nx.node_connected_component(graph,protected[1]) == set(protected[1:])
    for table,(pk,_) in generator['TABLES'].items():
        with (a/f'{table}.csv').open() as fh: rows=list(csv.DictReader(fh))
        assert len({tuple(r[k] for k in pk) for r in rows}) == len(rows)


def test_connected_mode_rejects_invalid_before_writing(tmp_path):
    for people,size in [(19,8),(100,5)]:
        out=tmp_path/f'invalid_{people}_{size}'
        with pytest.raises(ValueError): generator['write_scale'](out,people,size,connected=True)
        assert not out.exists()


def test_connected_oracle_rejects_a_shortcut_even_with_updated_manifest(tmp_path):
    import json
    out=tmp_path/'shortcut'
    manifest=generator['write_scale'](out,100,8,connected=True)
    path=out/'ROLE_HISTORY.csv'
    with path.open() as fh:
        reader=csv.DictReader(fh);columns=reader.fieldnames;rows=list(reader)
    # Move the chain terminal's private second role into the source workplace.
    role=next(r for r in rows if r['person_id']=='SCALE_P000000005' and r['org_id']=='SCALE_C000000005')
    role['org_id']='SCALE_C000000000'
    with path.open('w',newline='') as fh:
        writer=csv.DictWriter(fh,fieldnames=columns,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    manifest['tables']['ROLE_HISTORY'].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
    manifest['expected_connections'] += 2
    (out/'MANIFEST.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='shortest distance differs'):
        generator['check_scale'](out)


def test_sparse_seed_variant_preserves_source(tmp_path):
    source = tmp_path/'sparse'
    generator['write_scale'](source,100,8)
    before = hashes(source)
    result = generator['write_sparse_seed_variant'](tmp_path/'variant',source)
    assert hashes(source) == before
    assert result['people'] == 100 and result['roles'] == 109
    assert result['largest_component'] == 40
    assert result['examples_verified'] == 6


def test_fixture_load_rejects_unreviewed_targets_and_detects_changed_data():
    loader = runpy.run_path(str(ROOT/'data/load.py'))
    with pytest.raises(KeyError): loader['fixture_spec']('unknown')
    # The demo CSVs load into <schema>_DEPLOY_SRC on a new account; existing schemas are never reused.
    directory, source, output, meta = loader['fixture_spec']('baseline')
    assert directory == ROOT/'data/csv' and source.endswith('_DEPLOY_SRC') and output + '_SRC' == source
    assert len(loader['fixture_data']('baseline')) == 17
    for fixture in ('sparse','connected'):
        directory,source,output,meta = loader['fixture_spec'](fixture)
        assert source == output+'_SRC' and meta == output+'_META'
        assert 'DEPLOY' not in source
        data = loader['fixture_data'](fixture)
        assert len(data) == 17
        for _,ddl,rows in data:
            assert loader['canonical_rows'](rows,ddl) == loader['canonical_rows'](list(reversed(rows)),ddl)


def test_compact_oracle_preserves_all_baseline_strengths():
    import runpy
    from pathlib import Path
    oracle=runpy.run_path(str(Path(__file__).parents[1]/'data/oracle.py'))
    data=oracle['Data']();seeds=set(oracle['our_seeds'](data))
    full=oracle['build_knows'](data,seeds)
    compact=oracle['build_knows'](data,seeds,include_evidence=False)
    assert {k:v['strength'] for k,v in full.items()}=={k:v['strength'] for k,v in compact.items()}
    assert all(set(v)=={'strength'} for v in compact.values())


@pytest.mark.parametrize("people", [20, 300])
def test_connected_streaming_validation(tmp_path, people):
    out = tmp_path / 'streamed'
    generator['write_scale'](out, people, 16, 42, connected=True)
    report = generator['check_connected_streaming'](out)
    assert report['people'] == people
    assert report['planted_cases_verified'] == 14
    assert report['full_distance_oracle_run'] is False
    assert generator['check_scale'](out)['connections'] == report['connections_from_generator']


def test_streamed_validator_rejects_bad_reference_even_with_updated_hash(tmp_path):
    import json
    out = tmp_path / 'bad_reference'
    generator['write_scale'](out, 100, 16, 42, connected=True)
    path = out / 'ROLE_HISTORY.csv'
    path.write_text(path.read_text().replace('SCALE_P000000000', 'SCALE_P999999999', 1))
    m = json.loads((out/'MANIFEST.json').read_text())
    m['tables']['ROLE_HISTORY']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'MANIFEST.json').write_text(json.dumps(m))
    with pytest.raises(ValueError, match='Invalid person reference'):
        generator['check_connected_streaming'](out)


def test_compact_seed_oracle_matches_general_graph_and_rejects_nonoverlap(tmp_path):
    import numpy as np
    import networkx as nx
    out = tmp_path/'compact'
    generator['write_scale'](out,300,16,42,connected=True)
    oracle=runpy.run_path(str(ROOT/'data/oracle.py'))
    report=oracle['compact_connected_seed_distances'](out,tmp_path/'oracle')
    oracle['load_csv'].__globals__['CSV_DIR']=out
    data=oracle['Data']();seeds=oracle['our_seeds'](data)
    graph=oracle['knows_graph'](data,oracle['build_knows'](data,set(seeds)))
    for source in seeds:
        expected=nx.single_source_shortest_path_length(graph,source)
        values=np.load(tmp_path/'oracle'/f'{source}.npy')
        assert values.tolist()==[expected.get(seeds[i-7] if 7<=i<12 else f'SCALE_P{i:09d}',-1) for i in range(300)]
    assert report['reachable_rows']==5*299
    path=out/'ROLE_HISTORY.csv'
    path.write_text(path.read_text().replace('2014-01-01','2026-09-01',1))
    with pytest.raises(ValueError,match='do not all overlap'):
        oracle['compact_connected_seed_distances'](out,tmp_path/'bad_oracle')
