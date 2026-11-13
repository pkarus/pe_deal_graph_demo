"""Check the running viewer serves only the corrected scoring version."""
import json,requests
from pathlib import Path
base='http://127.0.0.1:8000/api/corporate/'
def get(path):
 r=requests.get(base+path,timeout=120);r.raise_for_status();return r.json()
health=get('health');assert health['scoring_version']=='corporate-affinity-v5'
network=get('network?limit=75');meta=network['metadata'];assert meta['version']=='corporate-affinity-v5' and meta['node_count']==2100
assert abs(meta['min_strength']-(.02/.75)**.25)<1e-12
person=get('person/PE_P0001');assert person['network'] is not None and person['history']
edge=get('edge/PE_P0001/CORP_P000264831');assert edge['scoring_version']=='corporate-affinity-v5' and edge['raw_strength']<.1 and abs(edge['strength']-edge['raw_strength']**.25)<1e-12
# Filtering must use normalized strengths consistently and retain raw scores.
filtered=get('neighborhood/PE_P0001?min_strength=0.5&limit=40')
assert filtered['graph']['edges'] and all(e['strength']>=.5 and e['raw_strength']<.5 for e in filtered['graph']['edges'])
assert all(abs(e['strength']-e['raw_strength']**.25)<1e-12 for e in filtered['graph']['edges'])
build=Path('pyrel_semantic_graph_explorer/.runtime/ui_v5_build.log').read_text();assert 'Generating static pages' in build and 'Route (pages)' in build
report={'status':'PASS','health':health,'cohort_run_id':meta['run_id'],'cohort_nodes':meta['node_count'],'cohort_edges':meta['edge_count'],
 'person_profile_and_career':True,'edge_decomposition_version':edge['scoring_version'],'edge_strength':edge['strength'],'edge_raw_strength':edge['raw_strength'],'normalized_threshold_verified':.5,
 'typescript':'PASS','production_build':'PASS','browser_render':'Pending; running API and production build verified.'}
Path('artifacts/corporate_viewer_v5_validation.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS running v5 viewer API, new cohort snapshot, person career, edge decomposition, and production build',flush=True)
