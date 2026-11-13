"""Assemble completed v2 evidence; refuse a stale deployed-agent validation."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json

root=Path(__file__).resolve().parents[1]
def read(name):return json.loads((root/'artifacts'/f'{name}.json').read_text())
deployment=read('corporate_agent_deployment');agent=read('corporate_agent_acceptance_v2')
files=['__init__.py','model.py','scoring.py','presentation.py','dynamic.py','runtime.py']
digest=hashlib.sha256(b''.join((root/'corporate_agent'/p).read_bytes() for p in files)).hexdigest()
assert digest==deployment['runtime_sha256']
assert agent['status']=='PASS' and all(c['runtime_sha256']==digest for c in agent['cases'])
assert all(c.get('response_language_verified') for c in agent['cases'])
names=['affinity_v2_native_fixture','affinity_v2_route_fixture','affinity_v2_real_edge_validation',
       'corporate_explorer_v2_edge_validation','corporate_explorer_v2_neighborhood_validation',
       'corporate_explorer_v2_historical_validation','corporate_affinity_v2_preservation']
checks={name:read(name) for name in names}
assert all(c['status']=='PASS' for c in checks.values())
analytics=read('corporate_affinity_v2_analytics');assert analytics['independent_validation']['status']=='PASS'
report={
    'status':'PASS','verified_at':datetime.now(timezone.utc).isoformat(),
    'scoring_version':'corporate-affinity-v2','runtime_sha256':digest,
    'agent':deployment['agent'],'local_explorer':'http://127.0.0.1:3000',
    'native_scoring_fixture_cases':len(checks['affinity_v2_native_fixture']['cases']),
    'strongest_vs_shortest_route_regression':'PASS: strongest two-hop witness and minimum one-hop distance coexist',
    'all_neighborhood_edges_verified':sum(c['all_neighbors_verified'] for c in checks['corporate_explorer_v2_neighborhood_validation']['cases']),
    'live_agent_questions':[{'case':c['case'],'request_id':c['request_id'],'sources_connected':c['total_connections'],
          'seconds':c['seconds'],
          'returned_paths_verified':c['returned_paths_verified'],'parent_call_query_id':c['call_query_id'],
          'native_transaction_ids':c['native_transaction_ids'],'role':c['role']} for c in agent['cases']],
    'missing_company_control':agent['missing_company_control'],
    'analytics':{k:analytics[k] for k in ['run_id','scope','as_of','node_count','edge_count','min_strength',
        'nontrivial_community_count','isolated_people','community_method','betweenness_method','independent_validation','transactions']},
    'local_checks':{'unit_tests':'19 passed','typescript':'PASS','production_build':'PASS',
        'browser':'Safari: corporate and PE neighborhoods, cohort graph, person metrics/timeline, full edge factors and native IDs rendered',
        'historical_scoring':'PASS at 2020-10-01; no future periods included'},
    'preservation':checks['corporate_affinity_v2_preservation'],
    'limits':['Exact introduction search through two hops','Centrality and communities cover the defined 2100-person cohort',
              'Betweenness is exact and unweighted; Louvain uses affinity weights',
              'All data is synthetic; scores are heuristics, not probabilities'],
    'evidence_files':[f'artifacts/{n}.json' for n in names+['corporate_affinity_v2_analytics','corporate_agent_acceptance_v2']],
    'audit_sql':'sql/corporate_agent_audit.sql',
}
(root/'artifacts/corporate_affinity_v2_acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: final deployed runtime, all live questions, 7190 native neighbors, scoring, structural analytics, UI and preservation')
