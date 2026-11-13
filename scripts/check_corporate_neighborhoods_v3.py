"""Compare every native explorer neighbor and score with independent Snowflake SQL."""
import json,math,requests
from pathlib import Path
from corporate_agent.validate import oracle_sql
from scripts.person_path_proc import connect

reports=[]
for pid in ['CORP_P000002008','PE_P0001']:
    response=requests.get(f'http://127.0.0.1:8000/api/corporate/neighborhood/{pid}?limit=40',timeout=900)
    response.raise_for_status();display=response.json()
    Path(f'artifacts/corporate_explorer_v3_neighborhood_{pid}.json').write_text(json.dumps(display,indent=2))
    cached=next(json.loads(p.read_text()) for p in Path('pyrel_semantic_graph_explorer/.runtime/affinity-v3').glob('*.json')
                if set(json.loads(p.read_text()).get('transaction_ids',[]))==set(display['transaction_ids']))
    native=cached['records']
    sql=oracle_sql(pid,pid).rsplit('    SELECT *,MIN(HOPS)',1)[0]
    sql+=' SELECT P1,P2,STRENGTH,RAW_YEARS,DURATION_COMPONENT,RECENCY_FACTOR,SPATIAL_FACTOR,DURATION_CONTRIBUTION,RECENCY_CONTRIBUTION,SPATIAL_CONTRIBUTION,CAREER_CONTRIBUTION FROM factors WHERE STRENGTH>0'
    with connect() as con:
        c=con.cursor();c.execute(sql)
        expected=[dict(zip([d[0].lower() for d in c.description],r)) for r in c.fetchall()]
        query_id=c.sfqid
    oracle={r['p2'] if r['p1']==pid else r['p1']:r for r in expected}
    assert set(oracle)=={r['person_id'] for r in native}
    assert len(oracle)==display['total_neighbors']
    max_error=0.
    for row in native:
        assert row['distance']==1
        for key in ['strength','raw_years','duration_component','recency_factor','spatial_factor','duration_contribution','recency_contribution','spatial_contribution','career_contribution']:
            truth=float(oracle[row['person_id']][key]);error=abs(row[key]-truth)
            assert math.isclose(row[key],truth,abs_tol=1e-8),(pid,row['person_id'],key,row[key],truth)
            max_error=max(max_error,error)
    expected_ids=sorted(oracle,key=lambda p:(-float(oracle[p]['strength']),p))[:40]
    assert [e['target'] for e in display['graph']['edges']]==expected_ids
    reports.append({'person_id':pid,'all_neighbors_verified':len(native),'max_absolute_error':max_error,
                    'sql_oracle_query_id':query_id,'native_transaction_ids':display['transaction_ids']})
    print('PASS',pid,len(native),'native neighbors and every score',flush=True)
Path('artifacts/corporate_explorer_v3_neighborhood_validation.json').write_text(json.dumps({'status':'PASS','cases':reports},indent=2))
