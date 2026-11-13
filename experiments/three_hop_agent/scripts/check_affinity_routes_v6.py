"""Native regression: the sole path needs two intermediaries and three edges."""
import argparse,json,math,uuid
from pathlib import Path
from datetime import date
from corporate_agent.scoring import SOURCE
from corporate_agent.model import IntroductionGraph
from corporate_agent.dynamic import EXAMPLE,build_query
from corporate_agent.local import local_configuration
from corporate_agent.presentation import records
from corporate_agent.runtime import ready_engine
from scripts.person_path_proc import connect
from tests.affinity_oracle import score_pair

parser=argparse.ArgumentParser();parser.add_argument('--direct',choices=['none','weak','strong'],default='none');args=parser.parse_args()
a,b,c,t=['CORP_P000900001','CORP_P000900002','CORP_P000900003','CORP_P000900004']
work=[]
for pid in [a,b,c,t]:
    work.append(dict(ROLE_ID=pid+'_career',PERSON_ID=pid,ORG_ID='SOLO_'+pid,START_DATE=date(2006,10,1),END_DATE=date(2022,10,1),OFFICE_ID=pid,CITY_ID=pid,WORK_MODE='ONSITE'))
jobs=[('AB',[a,b],2022,None),('BC',[b,c],2022,None),('CT',[c,t],2022,None)]
if args.direct!='none':jobs.append(('AT',[a,t],2006 if args.direct=='weak' else 2022,2007 if args.direct=='weak' else None))
for org,ids,start,end in jobs:
    for pid in ids:
        work.append(dict(ROLE_ID=pid+'_'+org,PERSON_ID=pid,ORG_ID=org,START_DATE=date(start,10,1),END_DATE=date(end,10,1) if end else None,OFFICE_ID=org if org!='AT' or args.direct=='strong' else pid,CITY_ID=org if org!='AT' or args.direct=='strong' else pid,WORK_MODE='ONSITE'))
people=[{'PERSON_ID':pid,'FULL_NAME':name} for pid,name in zip([a,b,c,t],['Source','First intermediary','Second intermediary','Target'])]
data={'work':work,'people':people,'team':people[:1],'company':[{'COMPANY_ID':org,'NAME':org} for org in sorted({r['ORG_ID'] for r in work})]}
inputs={}
with connect() as con:
    cur=con.cursor()
    for name,rows in data.items():
        table=SOURCE+'.AFFINITY_ROUTE_FIXTURE_V6_'+args.direct.upper()+'_'+name.upper();cols=list(rows[0])
        ddl=','.join(k+(' DATE' if k.endswith('_DATE') else ' VARCHAR') for k in cols)
        cur.execute(f'CREATE TABLE IF NOT EXISTS {table} ({ddl}) CHANGE_TRACKING=TRUE')
        cur.execute(f'SELECT COUNT(*) FROM {table}')
        if cur.fetchone()[0]==0:cur.executemany(f"INSERT INTO {table} VALUES ({','.join(['%s']*len(cols))})",[tuple(r[k] for k in cols) for r in rows])
        inputs[name]=table
run_id=uuid.uuid4().hex
cfg,session=local_configuration(8)
ready_engine(session)
try:
    n=IntroductionGraph(t,source_id=a,config=cfg,inputs=inputs)
    strongest=records(build_query(n,EXAMPLE).meta(route_fixture_id=run_id).to_df())
    shortest=records(build_query(n,EXAMPLE.replace('best_route(', 'shortest_route(')).meta(route_fixture_id=run_id).to_df())
    assert len(strongest)==len(shortest)==1
    minimum=3 if args.direct=='none' else 1
    assert strongest[0]['minimum_hops']==shortest[0]['minimum_hops']==minimum
    chain_legs=[score_pair(x,y,work,[])['strength'] for x,y in [(a,b),(b,c),(c,t)]]
    expected_path=[a,t] if args.direct=='strong' else [a,b,c,t]
    expected=score_pair(a,t,work,[])['strength'] if args.direct=='strong' else math.prod(chain_legs)
    assert strongest[0]['hops']==len(expected_path)-1 and strongest[0]['path']=='|'.join(expected_path)
    assert math.isclose(strongest[0]['strength'],expected,abs_tol=1e-8)
    assert math.isclose(strongest[0]['raw_strength'],strongest[0]['strength']**4,abs_tol=1e-10)
    shortest_path=[a,b,c,t] if args.direct=='none' else [a,t]
    assert shortest[0]['hops']==minimum and shortest[0]['path']=='|'.join(shortest_path)
    shortest_score=math.prod(chain_legs) if args.direct=='none' else score_pair(a,t,work,[])['strength']
    assert math.isclose(shortest[0]['strength'],shortest_score,abs_tol=1e-8)
    transactions=session.sql('SELECT ID,STATE FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:route_fixture_id::STRING=?',params=[run_id]).collect()
    assert len(transactions)==2 and all(r['STATE']=='COMPLETED' for r in transactions)
    report={'status':'PASS','strongest':strongest,'shortest':shortest,'transactions':[r.as_dict() for r in transactions]}
    Path('artifacts/affinity_v6_route_fixture'+('' if args.direct=='none' else '_'+args.direct)+'.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: exact native route, independent score, shortest distance; direct edge:',args.direct,flush=True)
finally:session.close()
