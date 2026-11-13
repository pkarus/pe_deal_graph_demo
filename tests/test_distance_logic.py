"""Logic routing, schema isolation, and actual compilation without live access."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(monkeypatch):
    # Fixture selection changes process-local model environment variables.
    monkeypatch.setenv('PE_DEAL_GRAPH_PROBE_FIXTURE', 'baseline')
    return runpy.run_path(str(ROOT / 'scripts/check_graphs.py'))


def test_logic_default_keeps_existing_inputs_and_sql_opt_in(runner):
    runner['select_probe_fixture']('connected1m')
    p = runner['prepare_copied_distance_probe']()
    cfg = runner['_cfg']
    assert p['source'] == cfg.schema('CONNECTED_1M_SRC')
    assert p['output'] == cfg.schema('CONNECTED_1M_LOGIC')
    assert p['metadata'] == cfg.schema('CONNECTED_1M_LOGIC_META')
    assert p['deployment']['outputs']['reasoner'] == 'logic'
    assert p['compiler'] == {'safe_recursion': False}
    assert p['deployment']['schedules']['path_probe'] == {'interval_s': 0, 'run_on_deploy': False}
    runner['select_probe_fixture']('connected1m', 'sql')
    sql = runner['prepare_copied_distance_probe']()
    assert sql['source'] == p['source']
    assert sql['output'] == cfg.schema('CONNECTED_1M')
    assert sql['deployment']['outputs']['reasoner'] == 'sql'
    runner['select_community_fixture']('connected1m')
    assert runner['prepare_copied_distance_probe']()['output'] == cfg.schema('CONNECTED_1M')
    assert runner['prepare_community_probe']()['schema'] == cfg.schema('CONNECTED_1M_COMMUNITY')


@pytest.mark.parametrize('fault', [None, 'sql', 'engine', 'schedule', 'source', 'meta', 'empty'])
def test_logic_plan_rejects_fallback_and_scope_changes(runner, fault):
    runner['select_probe_fixture']('connected1m')
    p = runner['prepare_copied_distance_probe']()
    entry = SimpleNamespace(reasoner='logic', schedule_name='path_probe', parameters={
        'engine_name': runner['_cfg'].ENGINE,
        'source_table_names': [p['source'] + '.PERSON', p['metadata'] + '.ENCODED_INPUT',
                               p['source'].removesuffix('_SRC') + '.ROLE_HISTORY_NORMALIZED']})
    meta = p['metadata']
    if fault == 'sql': entry.reasoner = 'sql'
    if fault == 'engine': entry.parameters['engine_name'] = 'other_engine'
    if fault == 'schedule': entry.schedule_name = 'other_schedule'
    if fault == 'source': entry.parameters['source_table_names'] = ['OTHER.SCHEMA.PERSON']
    if fault == 'meta': meta = 'OTHER.META'
    entries = [] if fault == 'empty' else [entry]
    if fault:
        with pytest.raises(RuntimeError): runner['validate_distance_plan'](meta, entries)
    else:
        runner['validate_distance_plan'](meta, entries)


@pytest.mark.parametrize('existing', [None, 'output', 'metadata'])
@pytest.mark.parametrize('fixture,reduced', [('connected1m', False), ('connected100k', True), ('connected1m', True)])
def test_new_schema_guard_never_replaces_existing_targets(runner, existing, fixture, reduced):
    runner['select_probe_fixture'](fixture, reduced_exports=reduced)
    p = runner['prepare_copied_distance_probe']()
    calls = []
    def sql(statement):
        calls.append(statement)
        rows = [{'name': p[existing].split('.')[1]}] if existing and statement.startswith('SHOW SCHEMAS') else []
        return SimpleNamespace(collect=lambda: rows)
    if existing:
        with pytest.raises(RuntimeError, match='already exist'):
            runner['provision_logic_distance_schemas'](SimpleNamespace(sql=sql))
        assert not any(q.startswith(('CREATE', 'GRANT')) for q in calls)
    else:
        runner['provision_logic_distance_schemas'](SimpleNamespace(sql=sql))
        assert [q for q in calls if q.startswith('CREATE')] == [
            'CREATE SCHEMA ' + p['output'], 'CREATE SCHEMA ' + p['metadata']]
    assert calls[-1] == 'USE ROLE ' + runner['_cfg'].DEPLOY_ROLE


def test_logic_path_does_not_install_sql_recursion_workaround(runner):
    from relationalai.semantics.backends.sql.lowerer import Lowerer
    original = Lowerer._coalesce_target_query
    def deploy(**kwargs):
        assert Lowerer._coalesce_target_query is original
        assert kwargs == {'wait': False, 'force': False}
    runner['deploy_distance_probe'](SimpleNamespace(deploy=deploy))


@pytest.mark.parametrize('reduced', [False, True])
def test_actual_1m_model_compiles_to_logic_offline(tmp_path, reduced):
    env = dict(os.environ)
    env.pop('DEBUG', None)
    report = tmp_path / 'plan.json'
    result = subprocess.run([
        sys.executable, '-B', str(ROOT / 'scripts/check_graphs.py'),
        '--compile-copied-distance-probe', '--fixture', 'connected1m', '--json', str(report),
        *(['--reduced-distance-exports'] if reduced else []),
    ], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    p = json.loads(report.read_text())
    assert p['offline']
    assert len(p['blocks']) == 1
    assert {b['reasoner'] for b in p['blocks']} == {'logic'}
    assert all(b['engine'] == p['engine'] and b['lqp_bytes'] > 0 for b in p['blocks'])
    assert p['output'].endswith('_CONNECTED_1M_LOGIC' + ('_LEAN' if reduced else ''))
    assert p['persisted_outputs'] == (['PERSONDISTANCEPROBE'] if reduced else None)


@pytest.mark.parametrize('selected,suffix', [('connected100k', 'CONNECTED_100K'), ('connected1m', 'CONNECTED_1M')])
def test_reduced_distance_scope_and_reset(runner, selected, suffix):
    for fixture, reasoner in [('baseline', 'logic'), ('connected', 'logic'), ('connected100k', 'sql'), ('connected1m', 'sql')]:
        with pytest.raises(ValueError):
            runner['select_probe_fixture'](fixture, reasoner, reduced_exports=True)
    runner['select_probe_fixture'](selected, reduced_exports=True)
    p = runner['prepare_copied_distance_probe']()
    assert p['output'] == runner['_cfg'].schema(suffix + '_LOGIC_LEAN')
    assert p['source'] == runner['_cfg'].schema(suffix + '_SRC')
    assert p['persisted_outputs'] == ['PERSONDISTANCEPROBE']
    runner['select_probe_fixture'](selected)
    assert not runner['prepare_copied_distance_probe']()['reduced_exports']


@pytest.mark.parametrize('suffix', ['CONNECTED_100K_LOGIC_LEAN', 'CONNECTED_1M_LOGIC_LEAN'])
def test_reduced_distance_filter_preserves_real_sdk_logic_body(runner, suffix):
    from relationalai.semantics.backends.sql.orchestrator import _load_js_procedure
    schema = runner['_cfg'].schema(suffix)
    body = _load_js_procedure('run_lqp_block', schema=schema + '_META', app_name='RELATIONALAI',
                              secret_fn_fqn='', max_parallel_exports='8', user_agent='offline-test').split('$$')[1]
    marker = 'tracer.startActiveSpan("export_results", function (span) {'
    prefix, suffix = body.split(marker)
    changed = runner['reduced_distance_export_body'](body, schema)
    assert changed.startswith(prefix)
    assert changed.endswith(marker + suffix)
    inserted = changed[len(prefix):changed.index(marker)]
    assert schema + '.PERSONDISTANCEPROBE' in inserted
    assert '.OURSEED' not in inserted and '.KNOWS' not in inserted
    assert 'exportSpecs.length !== 1' in inserted
    with pytest.raises(ValueError):
        runner['reduced_distance_export_body'](body, schema.removesuffix('_LEAN'))
    with pytest.raises(RuntimeError):
        runner['reduced_distance_export_body'](changed, schema)


@pytest.mark.parametrize('fault', [None, 'missing_self', 'duplicate_self', 'wrong_hops', 'missing_pair', 'extra_seed'])
def test_reduced_distance_validation_never_reads_unexported_ourseed(runner, monkeypatch, fault):
    runner['select_probe_fixture']('connected100k', reduced_exports=True)
    expected = [dict(source='a', target='a', hops=0), dict(source='b', target='b', hops=0),
                dict(source='a', target='x', hops=1), dict(source='b', target='x', hops=2)]
    monkeypatch.setitem(runner['validate_seed_probe_rows'].__globals__, 'seed_probe_oracle_rows', lambda: (['a', 'b'], expected))
    rows = [dict(row) for row in expected]
    if fault == 'missing_self': rows.pop(0)
    if fault == 'duplicate_self': rows.append(dict(rows[0]))
    if fault == 'wrong_hops': rows[-1]['hops'] = 99
    if fault == 'missing_pair': rows.pop()
    if fault == 'extra_seed': rows.append(dict(source='c', target='c', hops=0))
    def unexpected(*a, **kw): pytest.fail('Reduced validation read an unexported table')
    session = SimpleNamespace(sql=unexpected)
    if fault:
        with pytest.raises(RuntimeError): runner['validate_persisted_seed_distances'](session, rows)
    else:
        assert runner['validate_persisted_seed_distances'](session, rows)['correctness'] == 'PASS'


def test_ten_million_targets_and_exact_community_pivots(runner):
    cfg=runner['_cfg']
    runner['select_probe_fixture']('connected10m','sql')
    plan=runner['prepare_copied_distance_probe']()
    assert plan['source']==cfg.schema('CONNECTED_10M_SRC')
    assert plan['output']==cfg.schema('CONNECTED_10M')
    assert plan['deployment']['schedules']['path_probe']['run_on_deploy'] is False
    runner['select_community_fixture']('connected10m')
    assert runner['prepare_community_probe']()['schema']==cfg.schema('CONNECTED_10M_COMMUNITY')
    assert runner['deployed_community_parameters']()['num_pivots']==10_000_000
    runner['select_probe_fixture']('connected1m','sql')
    assert runner['prepare_copied_distance_probe']()['output']==cfg.schema('CONNECTED_1M')


def test_materialized_10m_compiles_native_algorithms_without_role_rules(runner, monkeypatch):
    from unittest.mock import patch
    from relationalai.config import Config, create_config, DeploymentConfig
    from relationalai.config.config import ambient_model_config
    from relationalai.config.connections.snowflake import SnowflakeConnection
    from relationalai.semantics.backends.multi_reasoner_executor import MultiReasonerExecutor
    from relationalai.util import schema as schema_cache
    runner['select_community_fixture']('connected10m')
    g = runner['build_materialized_community_model'].__globals__
    g['COMMUNITY_OUTPUT'] += '_GRAPH_ONLY'
    g['COMMUNITY_META'] = g['COMMUNITY_OUTPUT'] + '_META'
    monkeypatch.setenv('RAI_CONFIG_FILE_PATH', str(ROOT/'raiconfig.yaml'))
    cfg = create_config();cfg.compiler.safe_recursion=False;cfg.compiler.dry_run=True
    cfg.deployment = DeploymentConfig(**runner['prepare_community_probe']())
    cache = {g['PROBE_OUTPUT']+'.PERSON': {'ID':'String'},
             g['PROBE_OUTPUT']+'.KNOWS': {'P1':'String','P2':'String','STRENGTH':'Float'}}
    def blocked(*a, **kw):raise AssertionError('Unexpected live access')
    with patch('socket.socket.connect', blocked), patch.object(Config,'get_session',return_value=SimpleNamespace(sql=blocked)), \
         patch.object(SnowflakeConnection,'_create_new_session',blocked), \
         patch.object(schema_cache,'CACHE',cache), patch.object(schema_cache,'_save_cache',blocked), ambient_model_config(cfg):
        model = runner['build_materialized_community_model']()
        executor = MultiReasonerExecutor(cfg)
        mm=model.to_metamodel()
        normalizer, plan=executor._create_model_plan(mm)
        assert len(plan.blocks)==1
        block=plan.blocks[0];assert block.reasoner_type=='logic'
        logic=executor._logic_executor.plan_block(block,mm,plan.catalog,plan.version_state,normalizer,plan.ingest_sources_by_block.get(block.index))
        sql,sources,lqp,params=executor._logic_executor.plan_refresh_sql(g['COMMUNITY_META'],block.index,logic,mm,plan.catalog)
        assert params['engine_name']==g['COMMUNITY_ENGINE']
        assert all(s in cache or s.startswith(g['COMMUNITY_META']+'.') for s in sources)
        assert not any('ROLE_HISTORY' in s for s in sources)
        assert lqp
    assert not any(k.startswith('pe_deal_graph.model') for k in sys.modules)


@pytest.mark.parametrize('fixture', ['baseline','connected1m'])
def test_materialized_graph_rejects_other_fixtures(runner, fixture):
    runner['select_community_fixture'](fixture)
    with pytest.raises(ValueError, match='Materialized graph'):
        runner['run_community_probe'](materialized_graph=True)



def test_graph_only_timeout_change_preserves_payload(runner):
    cfg=runner['_cfg']
    call=(f"CALL {cfg.schema('CONNECTED_10M_COMMUNITY_GRAPH_ONLY_META')}._INTERNAL_RUN_LQP_BLOCK(79, 'block', "
          f"'{cfg.ENGINE}', 'HIGHMEM_X64_S', 25, TRUE, 0, 'payload25', 'exports');")
    result=runner['extend_graph_only_timeout'](call)
    assert result==call.replace("'HIGHMEM_X64_S', 25,", "'HIGHMEM_X64_S', 40,")
    for bad in (result,call.replace('_GRAPH_ONLY_META','_META'),call.replace('HIGHMEM_X64_S','HIGHMEM_X64_M'),call.replace('(79,','(80,')):
        with pytest.raises(ValueError):runner['extend_graph_only_timeout'](bad)
