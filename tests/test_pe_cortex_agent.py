"""Coverage and tie semantics for the persisted-result lookup, entirely offline."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('pe_agent', Path(__file__).parents[1] / 'scripts/pe_cortex_agent.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


@pytest.fixture
def lookup():
    people = [dict(person_id=p, name=n, community=c, internal_betweenness=b) for p, n, c, b in [
        ('P1', 'Seed One', 10, -5e-13), ('P2', 'Reachable Two', 10, 1e-13),
        ('P3', 'Unreachable Three', 20, 0.0), ('P4', 'Reachable Four', 10, 0.0)]]
    distances = [dict(source_id='P1', target_id=p, hops=h) for p, h in [('P1', 0), ('P2', 2), ('P4', 4)]]
    targets = [dict(person_id='P2', name='Reachable Two', target_id='C1', target_name='Target One', kind='CEO')]
    companies = [dict(target_id='C1', target_name='Target One'), dict(target_id='C2', target_name='Outside Two')]
    return lambda operation, **kw: agent.answer_lookup(people, distances, ['P1'], targets, companies, operation, **kw)


def test_unreachable_differs_from_unsupported_source(lookup):
    assert lookup('distance', person='P3')['distances'][0]['status'] == 'UNREACHABLE'
    response = lookup('distance', person='P1', source_person='P2')
    assert response['status'] == 'SOURCE_NOT_PRECOMPUTED'
    assert 'distances' not in response  # No reversed-pair inference, even though P1->P2 exists.


def test_self_and_longer_than_three_hops(lookup):
    assert lookup('distance', person='P1')['distances'][0]['hops'] == 0
    assert lookup('distance', person='P1')['distances'][0]['status'] == 'SELF'
    assert lookup('distance', person='P4')['distances'][0]['hops'] == 4


def test_unknown_ambiguous_and_out_of_scope_are_not_unreachable(lookup):
    assert lookup('distance', person='P999')['status'] == 'NOT_FOUND'
    assert lookup('community', person='Reachable')['status'] == 'AMBIGUOUS'
    assert lookup('distance', target_company='C2')['status'] == 'OUTSIDE_TARGET_SCOPE'
    assert lookup('distance', person="x'; DROP TABLE PERSON;--")['status'] == 'NOT_FOUND'


def test_ties_zero_residuals_and_truncation(lookup):
    group = lookup('connectors', community_id='10', top_n=1)['communities'][0]
    assert group['all_scores_zero_at_display_precision']
    assert group['same_score_members_omitted_at_cutoff'] == 2
    assert group['top_connectors'][0]['rank'] == 1
    group = lookup('connectors', person='P3')['communities'][0]
    assert group['size'] == 1 and group['top_connectors'][0]['displayed_betweenness'] == 0


def test_only_requested_company_and_raw_community(lookup):
    rows = lookup('distance', target_company='Target One')['distances']
    assert len(rows) == 1 and rows[0]['target_id'] == 'P2'
    assert lookup('community', person='P2')['communities'][0]['community'] == 10


@pytest.mark.parametrize('kwargs', [{'top_n': 0}, {'top_n': 11}, {'top_n': True},
                                    {'person': 'P1', 'community_id': '10'}, {'source_person': 'P1'}])
def test_invalid_options_are_rejected(lookup, kwargs):
    assert lookup('connectors', **kwargs)['status'].startswith('INVALID')


def test_no_algorithm_or_sql_execution_surface(lookup):
    assert lookup('refresh')['status'] == 'UNSUPPORTED_OPERATION'
    sql = agent.procedure_sql([])
    assert 'EXECUTE AS CALLER' in sql
    assert 'import relationalai' not in sql
    assert 'import networkx' not in sql
    compile(sql.split('AS $$\n', 1)[1].rsplit('\n$$', 1)[0], '<handler>', 'exec')
    assert len(agent.agent_specification()['tools']) == 1


def test_changed_baseline_stops_before_answering():
    body = agent.procedure_sql([]).split('AS $$\n', 1)[1].rsplit('\n$$', 1)[0]
    scope = {}
    exec(compile(body, '<handler>', 'exec'), scope)

    class ChangedRow:
        def as_dict(self):
            return {'NAME': 'changed', 'N': 1, 'H': 2}

    class Session:
        def sql(self, query, params=None):
            assert query == agent.fingerprint_sql()  # No result lookup after mismatch.
            return self

        def collect(self):
            return [ChangedRow()]

    result = scope['lookup_handler'](Session(), 'distance', 'P1', '', '', '', 3)
    assert result['status'] == 'BASELINE_CHANGED'
    assert result['data_label'] == 'SYNTHETIC PE DEMO DATA'
    assert 'distances' not in result


def test_preservation_survives_json_round_trip_and_detects_other_agent_change(monkeypatch):
    created = datetime(2026, 11, 4, tzinfo=timezone.utc)
    before = dict(database_name='DB', schema_name='SCHEMA', name='EXISTING', owner='OWNER', created_on=str(created))
    live = dict(before, created_on=created)
    report = {'baseline_before': {'hash': 42}, 'agents_before': [before]}
    monkeypatch.setattr(agent, 'preservation', lambda _: {'hash': 42})
    monkeypatch.setattr(agent, 'read_rows', lambda *_: [live])
    monkeypatch.setattr(agent, 'save_report', lambda _: None)
    agent.verify_preservation(None, report)
    assert report['other_agents_unchanged']
    live['owner'] = 'DIFFERENT'
    with pytest.raises(AssertionError):
        agent.verify_preservation(None, report)


@pytest.fixture(scope='module')
def target_runner():
    import runpy
    return runpy.run_path(str(Path(__file__).parents[1] / 'scripts/check_rules.py'))


def test_target_oracle_checks_all_rules_and_records_scope_difference(target_runner):
    expected = target_runner['target_oracle_rows']()
    result = target_runner['validate_target_rows'](expected['companies'],
        [{'id':r['id']} for r in expected['companies']], expected['mappings'], expected['components'])
    assert (result['eligible_targets'],result['decision_makers'],result['tier_a_targets'],result['tier_a_decision_makers']) == (248,256,6,9)
    assert result['raw_oracle_mapping_count']==257
    assert result['explicit_model_scope_exclusions']==[
        {'target':'C9820','person':'P38163','kind':'OWNER_DESIGNEE','reason':'not a majority owner'}]


@pytest.mark.parametrize('fault',['missing','duplicate','wrong_person','nonmajority','wrong_score','wrong_tier'])
def test_target_validation_rejects_incorrect_persisted_rows(target_runner,fault):
    e=target_runner['target_oracle_rows']()
    if fault=='missing':e['mappings'].pop()
    if fault=='duplicate':e['mappings'].append(e['mappings'][0])
    if fault=='wrong_person':e['mappings'][0]['person']='unknown'
    if fault=='nonmajority':e['mappings'].append({'target':'C9820','person':'P38163','kind':'OWNER_DESIGNEE'})
    if fault=='wrong_score':e['companies'][0]['score']+=1
    if fault=='wrong_tier':e['companies'][0]['tier']='A' if e['companies'][0]['tier']!='A' else 'B'
    with pytest.raises(RuntimeError):
        target_runner['validate_target_rows'](e['companies'],[{'id':r['id']} for r in e['companies']],e['mappings'],e['components'])


def test_agent_uses_persisted_targets_without_snapshot_fallback():
    sql=agent.procedure_sql([])
    assert 'P67052' not in sql and 'Ruth Adeyemi' not in sql
    assert 'TARGETS = ' not in sql
    body=sql.split('AS $$\n',1)[1].rsplit('\n$$',1)[0]
    scope={}
    exec(compile(body,'<handler>','exec'),scope)
    seen=[]
    persisted=[{'person_id':'P_NEW','name':'Persisted person','target_id':'C_NEW',
                'target_name':'Persisted company','kind':'CEO','target_score':70,'via':None}]
    def read(_,query,params=None):
        seen.append(query)
        return persisted if 'SELECT dm.PERSON' in query else []
    scope['read_rows']=read
    answer=scope['lookup_handler'](None,'catalog','','','','',3)
    assert answer['tier_a_decision_makers']==persisted
    assert any(agent.TARGET_OUTPUT+'.DECISIONMAKER' in q and "c.TIER='A'" in q for q in seen)
    persisted.clear()
    assert scope['lookup_handler'](None,'catalog','','','','',3)['tier_a_decision_makers']==[]


@pytest.fixture
def route_data():
    people = [dict(person_id=n, name=n, community=1, internal_betweenness=0)
              for n in ('S', 'A', 'B', 'T', 'U', 'I')]
    distances = [dict(source_id='S', target_id=n, hops=d)
                 for n,d in [('S',0),('A',1),('B',1),('T',2),('U',3)]]
    edges = [dict(p1=a,p2=b,strength=0.6) for a,b in
             [('S','A'),('S','B'),('A','T'),('B','T'),('A','B'),('T','U')]]
    return people, distances, edges


def test_all_two_hop_intermediaries_and_explicit_route_limit(route_data):
    people, distances, edges = route_data
    r = agent.reconstruct_paths(people,distances,edges,'S','T',limit=1)
    assert r['shortest_route_count']==2 and r['routes_truncated']
    assert {p['person_id'] for p in r['all_two_hop_intermediaries']}=={'A','B'}
    assert [p['person_id'] for p in r['routes'][0]['people']]==['S','A','T']
    assert len(r['routes'][0]['edges'])==2


def test_routes_self_unreachable_and_nonseed_coverage(route_data):
    people, distances, edges = route_data
    for target,status,count in [('S','SELF',1),('I','UNREACHABLE',0)]:
        r=agent.answer_lookup(people,distances,['S'],[],[],'paths',person=target,edges=edges)
        assert r['paths'][0]['status']==status
        assert r['paths'][0]['shortest_route_count']==count
    r=agent.answer_lookup(people,distances,['S'],[],[],'paths',person='T',source_person='A',edges=edges)
    assert r['status']=='SOURCE_NOT_PRECOMPUTED'
    assert agent.answer_lookup(people,distances,['S'],[],[],'paths',person='T')['status']=='PATH_DATA_UNAVAILABLE'
    r=agent.answer_lookup(people,distances,['S'],[],[],'paths',person='T',edges=[])
    assert r['status']=='INCONSISTENT_PATH_DATA'


def test_cyclic_routes_match_independent_enumeration(route_data):
    import networkx as nx
    people, distances, edges = route_data
    graph=nx.Graph();graph.add_edges_from((r['p1'],r['p2']) for r in edges)
    for target in ('A','T','U'):
        result=agent.reconstruct_paths(people,distances,edges,'S',target,limit=10)
        actual={tuple(p['person_id'] for p in r['people']) for r in result['routes']}
        assert actual==set(map(tuple,nx.all_shortest_paths(graph,'S',target)))
        assert result['shortest_route_count']==len(actual)
        assert not result['routes_truncated']


def test_bayside_routes_match_local_oracle():
    import runpy
    import networkx as nx
    root=Path(__file__).parents[1]
    oracle=runpy.run_path(str(root/'data/oracle.py')); data=oracle['Data']()
    pairs=oracle['build_knows'](data,set(oracle['our_seeds'](data)))
    graph=oracle['knows_graph'](data,pairs)
    people=[dict(person_id=n,name=n) for n in graph]
    edges=[dict(p1=a,p2=b,strength=r['strength']) for (a,b),r in pairs.items()]
    for source in ('P19079','P26070'):
        distances=[dict(source_id=source,target_id=t,hops=d) for t,d in nx.single_source_shortest_path_length(graph,source).items()]
        result=agent.reconstruct_paths(people,distances,edges,source,'P37955',limit=10)
        expected=set(map(tuple,nx.all_shortest_paths(graph,source,'P37955')))
        assert result['shortest_route_count']==len(expected)
        assert {tuple(p['person_id'] for p in r['people']) for r in result['routes']}==expected
        assert {p['person_id'] for p in result['all_two_hop_intermediaries']}=={p[1] for p in expected}


def test_community_settings_are_explicit_and_no_best_partition_claim():
    _,metadata=agent.saved_configuration()
    assert metadata['community_configuration']['max_levels']==5
    assert metadata['community_configuration']['randomization_seed']==7
    spec=agent.agent_specification()
    assert 'For EVERY community or connector answer' in spec['instructions']['response']
    assert 'paths' in spec['tools'][0]['tool_spec']['input_schema']['properties']['operation']['enum']
    assert agent.DISTANCE+'.KNOWS' in agent.fingerprint_sql()
    body=agent.procedure_sql([]).split('AS $$\n',1)[1].rsplit('\n$$',1)[0]
    compile(body,'<updated handler>','exec')


def test_strongest_route_selected_before_truncation_and_evidence_retained(route_data):
    people, distances, edges = route_data
    for edge in edges:
        edge['strength'] = 0.9 if 'B' in (edge['p1'],edge['p2']) else 0.2
        edge['evidence'] = 'persisted evidence for ' + edge['p1'] + edge['p2']
        edge['evidence_count'] = 2
    people[2]['current_roles'] = [{'title':'CFO','org_id':'C1'}]
    r = agent.reconstruct_paths(people,distances,edges,'S','T',limit=1)
    route = r['routes'][0]
    assert [p['person_id'] for p in route['people']] == ['S','B','T']
    assert route['route_strength'] == pytest.approx(0.81)
    assert route['people'][1]['current_roles'][0]['title']=='CFO'
    assert all(e['evidence'].startswith('persisted evidence') and e['evidence_count']==2 for e in route['edges'])
    assert r['routes_truncated'] and r['shortest_route_count']==2


def test_weighted_top_k_matches_exhaustive_with_zero_edges():
    import itertools
    import math
    import networkx as nx
    for zero in (False,True):
        graph=nx.Graph()
        layers=[['S'],['A','B','C'],['D','E','F'],['T']]
        for i,(left,right) in enumerate(zip(layers,layers[1:])):
            for j,(a,b) in enumerate(itertools.product(left,right)):
                graph.add_edge(a,b,strength=0.0 if zero and b=='T' else [0.2,0.7,1.0][(i+j)%3])
        people=[dict(person_id=n,name=n) for n in graph]
        distances=[dict(source_id='S',target_id=n,hops=d) for n,d in nx.single_source_shortest_path_length(graph,'S').items()]
        edges=[dict(p1=a,p2=b,**v) for a,b,v in graph.edges(data=True)]
        expected=sorted([(math.prod(graph[a][b]['strength'] for a,b in zip(p,p[1:])),tuple(p))
                         for p in nx.all_shortest_paths(graph,'S','T')],key=lambda r:(-r[0],r[1]))
        for k in (1,3,10):
            r=agent.reconstruct_paths(people,distances,edges,'S','T',k)
            assert [(p['route_strength'],tuple(n['person_id'] for n in p['people'])) for p in r['routes']]==expected[:k]
            assert r['shortest_route_count']==len(expected)


def test_recommendation_orders_hops_before_product_and_preserves_ties():
    people=[dict(person_id=n,name=n) for n in ('A','B','T','X')]
    edges=[dict(p1='A',p2='T',strength=.2),dict(p1='B',p2='X',strength=1.),dict(p1='X',p2='T',strength=1.)]
    distances=[dict(source_id=s,target_id=n,hops=d) for s,ns in [('A',[('A',0),('T',1)]),('B',[('B',0),('X',1),('T',2)])] for n,d in ns]
    r=agent.answer_lookup(people,distances,['B','A'],[],[],'paths',person='T',edges=edges)
    assert [x['source_id'] for x in r['ranked_routes']]==['A','B']
    assert [x['route_strength'] for x in r['ranked_routes']]==[.2,1.]


def test_compact_team_result_keeps_all_sources_and_ranks_shorter_alternative():
    import json
    people=[dict(person_id=n,name=n) for n in ('S','D','P','A','B','T')]
    edges=[dict(p1=a,p2=b,strength=w,evidence='stored evidence') for a,b,w in [('S','A',1),('A','T',.6),('D','B',.3),('B','T',.96),('P','S',1)]]
    import networkx as nx
    g=nx.Graph();g.add_edges_from((e['p1'],e['p2']) for e in edges)
    distances=[dict(source_id=s,target_id=n,hops=h) for s in ('S','D','P') for n,h in nx.single_source_shortest_path_length(g,s).items()]
    full=agent.answer_lookup(people,distances,['S','P','D'],[],[],'paths',person='T',edges=edges)
    result=agent.compact_path_result(full,all_sources=True)
    assert result['coverage_complete'] and result['sources_returned']==3
    assert {r['source_id']:r['hops'] for r in result['source_summary']}=={'S':2,'D':2,'P':3}
    assert [r['source_id'] for r in result['ranked_routes']]==['S','D']
    assert all('person_ids' in r and 'people' not in r for r in result['ranked_routes'])
    assert len(json.dumps(result))<5000
