"""Verify normalization leaves every original raw component and ranking intact."""
import json,math,statistics
from pathlib import Path

def read(name):return json.loads(Path('artifacts',name+'.json').read_text())
def neighborhood(version,pid):
 docs=[json.loads(p.read_text()) for p in Path(f'pyrel_semantic_graph_explorer/.runtime/affinity-{version}').glob('*.json')]
 return max([d['records'] for d in docs if d.get('records') and d['records'][0].get('source_id')==pid],key=len)
reports=[]
for pid in ['CORP_P000002008','PE_P0001']:
 old={r['person_id']:r for r in neighborhood('v4',pid)};new={r['person_id']:r for r in neighborhood('v5',pid)}
 assert set(old)==set(new)
 for key,row in new.items():
  assert math.isclose(row['raw_strength'],old[key]['strength'],abs_tol=1e-12)
  assert math.isclose(row['strength'],old[key]['strength']**.25,abs_tol=1e-12)
  for f in ['raw_years','effective_years','employment_contribution','friendship_contribution']:
   assert math.isclose(row[f],old[key][f],abs_tol=1e-12)
 ordered=sorted(new,key=lambda k:new[k]['strength']);assert all(old[b]['strength']+1e-12>=old[a]['strength'] for a,b in zip(ordered,ordered[1:]))
 vals=[r['strength'] for r in new.values()]
 reports.append({'person_id':pid,'edges':len(new),'raw_components_unchanged':True,'ranking_preserved':True,'normalized_median':statistics.median(vals),'normalized_max':max(vals)})
old={(r['left_id'],r['right_id']):r for r in read('affinity_v4_native_fixture')['rows']};new=read('affinity_v5_native_fixture')['rows']
fixture_count=len(new)
for row in new:
 baseline=old[(row['left_id'],row['right_id'])]
 for key,value in baseline.items():
  if isinstance(value,(int,float)) and key!='strength':assert math.isclose(value,row[key],abs_tol=1e-12),(key,value,row[key])
 assert math.isclose(baseline['strength'],row['raw_strength'],abs_tol=1e-12)
 assert math.isclose(row['strength'],row['raw_strength']**.25,abs_tol=1e-12)
old_route=read('affinity_v4_route_fixture');new_route=read('affinity_v5_route_fixture')
for mode in ['strongest','shortest']:
 a,b=old_route[mode][0],new_route[mode][0]
 for key in ['connection_id','target_id','path','hops','minimum_hops']:assert a[key]==b[key]
 assert math.isclose(a['strength'],b['raw_strength'],abs_tol=1e-12)
old=read('corporate_affinity_v4_analytics');new=read('corporate_affinity_v5_analytics')
a={(r['left_id'],r['right_id']):r for r in old['edges']};b={(r['left_id'],r['right_id']):r for r in new['edges']};assert set(a)==set(b)
for k in a:assert math.isclose(a[k]['strength'],b[k]['raw_strength'],abs_tol=1e-12)
a={r['person_id']:r for r in old['nodes']}
for r in new['nodes']:
 assert a[r['person_id']]['degree']==r['degree']
 for k in ['weighted_degree','betweenness']:assert math.isclose(a[r['person_id']][k],r[k],rel_tol=1e-7,abs_tol=5e-4)
report={'status':'PASS','neighborhoods':reports,'raw_fixture_components_unchanged':fixture_count,
 'strongest_and_shortest_raw_routes_preserved':True,'cohort_raw_edges_preserved':len(b),'cohort_degree_and_betweenness_preserved':len(a),
 'normalization':'Fixed fourth root; no question-specific maximum, percentile, or probability claim.'}
Path('artifacts/affinity_v5_normalization_comparison.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
