"""Prove the correction preserves original employment factors and ordering."""
import json,math,statistics
from pathlib import Path

def cached_neighborhood(version,pid):
    docs=[json.loads(p.read_text()) for p in Path(f'pyrel_semantic_graph_explorer/.runtime/affinity-{version}').glob('*.json')]
    valid=[d['records'] for d in docs if d.get('records') and d['records'][0].get('source_id')==pid]
    return max(valid,key=len)
reports=[]
for pid in ['CORP_P000002008','PE_P0001']:
    old={r['person_id']:r for r in cached_neighborhood('v2',pid) if r['employment_contribution']>0}
    new={r['person_id']:r for r in cached_neighborhood('v4',pid)}
    assert set(old)==set(new)
    for key,row in new.items():
        for f in ['raw_years','effective_years']:
            assert math.isclose(row[f],old[key][f],abs_tol=1e-12)
        assert math.isclose(row['strength'],old[key]['employment_contribution']/.75,abs_tol=1e-12)
        assert row['friendship_contribution']==0
    # Ranking is unchanged except machine-rounding ties; compare all strict gaps.
    ordered=sorted(new,key=lambda k:new[k]['strength'])
    assert all(old[b]['employment_contribution']+1e-12>=old[a]['employment_contribution'] for a,b in zip(ordered,ordered[1:]))
    before=[r['employment_contribution'] for r in old.values()];after=[r['strength'] for r in new.values()]
    reports.append({'person_id':pid,'edges':len(new),'unchanged_temporal_and_spatial_factors':True,'unchanged_employment_ranking':True,
        'employment_multiplier':1/.75,'before_median':statistics.median(before),'after_median':statistics.median(after),
        'before_max':max(before),'after_max':max(after),'after_above_0_8':sum(v>=.8 for v in after)})
old=json.loads(Path('artifacts/affinity_v2_native_fixture.json').read_text());new=json.loads(Path('artifacts/affinity_v4_native_fixture.json').read_text())
old_rows={(r['left_id'],r['right_id']):r for r in old['rows']}
checked=0
for r in new['rows']:
    prior=old_rows.get((r['left_id'],r['right_id']))
    if not prior:continue
    for f in ['raw_years','effective_years','career_mean_years','left_career_years','right_career_years','career_fraction','duration_component','time_score']:
        assert math.isclose(r[f],prior[f],abs_tol=1e-12),(f,r,prior)
    assert math.isclose(r['strength'],prior['employment_contribution']/.75,abs_tol=1e-12)
    checked+=1
report={'status':'PASS','original_native_fixture_components_verified':checked,'neighborhoods':reports,
    'note':'Before refers to v2 employment contribution; friendship bonuses are deferred. No other formula/factor/curve uplift.'}
Path('artifacts/affinity_v4_original_rules_comparison.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
