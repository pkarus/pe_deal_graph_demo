"""Validate real and historical inspector decompositions against independent facts."""
import json,math,requests
from pathlib import Path
from corporate_agent.scoring import SOURCE
from scripts.person_path_proc import connect
from tests.affinity_oracle import score_pair
from datetime import date

left,right='PE_P0001','CORP_P000264831'
with connect() as con:
    c=con.cursor();c.execute(f'SELECT * FROM {SOURCE}.WORKPLACE_V2 WHERE PERSON_ID IN (%s,%s)',(left,right))
    work=[dict(zip([d[0] for d in c.description],r)) for r in c.fetchall()]
report=[]
for asof in ['2026-10-01','2020-10-01']:
    response=requests.get(f'http://127.0.0.1:8000/api/corporate/edge/{left}/{right}?as_of={asof}',timeout=900)
    response.raise_for_status();edge=response.json()
    Path(f'artifacts/corporate_explorer_v3_edge_{asof}.json').write_text(json.dumps(edge,indent=2)+'\n')
    truth=score_pair(right,left,work,[],date.fromisoformat(asof))
    for k,v in truth.items():assert math.isclose(edge[k],v,abs_tol=1e-8),(asof,k,edge[k],v)
    assert all(p['end_date'][:10]<=asof for p in edge['periods'])
    total=sum(p['days'] for p in edge['periods'])
    assert math.isclose(total/365.25,edge['raw_years'],abs_tol=1e-8)
    for k in ['recency','spatial']:
        assert math.isclose(sum(p[k+'_days'] for p in edge['periods'])/total,edge[k+'_factor'],abs_tol=1e-8)
    assert math.isclose(sum(edge[k+'_contribution'] for k in ['duration','recency','spatial','career']),edge['strength'],abs_tol=1e-10)
    assert edge['scoring_version']=='corporate-affinity-v3'
    assert edge['transaction_ids']
    report.append({'as_of':asof,'strength':edge['strength'],'raw_years':edge['raw_years'],'transaction_ids':edge['transaction_ids'],'all_components_verified':True})
    print('PASS inspector',asof,edge['strength'],flush=True)
Path('artifacts/corporate_explorer_v3_edge_validation.json').write_text(json.dumps({'status':'PASS','cases':report},indent=2)+'\n')
