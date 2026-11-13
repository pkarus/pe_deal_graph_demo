"""Native regression: stronger two-hop employment route and a weaker direct edge."""
import json,math,uuid
from pathlib import Path
from datetime import date
from corporate_agent.scoring import SOURCE
from corporate_agent.model import IntroductionGraph
from corporate_agent.dynamic import EXAMPLE,build_query
from corporate_agent.local import local_configuration
from corporate_agent.presentation import records
from scripts.person_path_proc import connect
from tests.affinity_oracle import score_pair

a,b,t=['CORP_P000900001','CORP_P000900002','CORP_P000900003']
work=[]
for pid in [a,b,t]:
    work.append(dict(ROLE_ID=pid+'_career',PERSON_ID=pid,ORG_ID='SOLO_'+pid,START_DATE=date(2006,10,1),END_DATE=date(2022,10,1),OFFICE_ID=pid,CITY_ID=pid,WORK_MODE='ONSITE'))
for org,ids,start,end in [('AB',[a,b],2022,None),('BT',[b,t],2022,None),('AT',[a,t],2006,2007)]:
    for pid in ids:
        work.append(dict(ROLE_ID=pid+'_'+org,PERSON_ID=pid,ORG_ID=org,START_DATE=date(start,10,1),END_DATE=date(end,10,1) if end else None,OFFICE_ID=org if org!='AT' else pid,CITY_ID=org if org!='AT' else pid,WORK_MODE='ONSITE'))
people=[{'PERSON_ID':pid,'FULL_NAME':name} for pid,name in zip([a,b,t],['Source','Intermediary','Target'])]
data={'work':work,'people':people,'team':people[:1],'company':[{'COMPANY_ID':org,'NAME':org} for org in sorted({r['ORG_ID'] for r in work})]}
inputs={}
with connect() as con:
    c=con.cursor()
    for name,rows in data.items():
        table=SOURCE+'.AFFINITY_ROUTE_FIXTURE_V4_'+name.upper();cols=list(rows[0])
        ddl=','.join(k+(' DATE' if k.endswith('_DATE') else ' VARCHAR') for k in cols)
        c.execute(f'CREATE TABLE IF NOT EXISTS {table} ({ddl}) CHANGE_TRACKING=TRUE')
        c.execute(f'SELECT COUNT(*) FROM {table}')
        if c.fetchone()[0]==0:c.executemany(f"INSERT INTO {table} VALUES ({','.join(['%s']*len(cols))})",[tuple(r[k] for k in cols) for r in rows])
        inputs[name]=table
run_id=uuid.uuid4().hex
cfg,session=local_configuration(8)
try:
    n=IntroductionGraph(t,source_id=a,config=cfg,inputs=inputs)
    strongest=records(build_query(n,EXAMPLE).meta(route_fixture_id=run_id).to_df())
    shortest=records(build_query(n,EXAMPLE.replace('best_route(', 'shortest_route(')).meta(route_fixture_id=run_id).to_df())
    assert len(strongest)==len(shortest)==1
    assert strongest[0]['minimum_hops']==shortest[0]['minimum_hops']==1
    assert strongest[0]['hops']==2 and strongest[0]['path']=='|'.join([a,b,t])
    legs=[score_pair(x,y,work,[])['strength'] for x,y in [(a,b),(b,t)]]
    assert math.isclose(strongest[0]['strength'],math.prod(legs),abs_tol=1e-8)
    assert strongest[0]['strength']<min(legs)
    assert shortest[0]['hops']==1 and shortest[0]['path']=='|'.join([a,t])
    assert math.isclose(shortest[0]['strength'],score_pair(a,t,work,[])['strength'],abs_tol=1e-8)
    transactions=session.sql('SELECT ID,STATE FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:route_fixture_id::STRING=?',params=[run_id]).collect()
    assert len(transactions)==2 and all(r['STATE']=='COMPLETED' for r in transactions)
    report={'status':'PASS','strongest':strongest,'shortest':shortest,'transactions':[r.as_dict() for r in transactions]}
    Path('artifacts/affinity_v4_route_fixture.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: strongest route has two hops while native minimum distance and shortest route have one',flush=True)
finally:session.close()
