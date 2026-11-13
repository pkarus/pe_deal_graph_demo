"""Native regression: a stronger two-hop path can coexist with a direct edge."""
import json,math,uuid
from pathlib import Path
from datetime import date
from corporate_agent.scoring import SOURCE
from corporate_agent.model import IntroductionGraph
from corporate_agent.dynamic import EXAMPLE,build_query
from corporate_agent.local import local_configuration
from corporate_agent.presentation import records
from scripts.person_path_proc import connect
from tests.affinity_oracle import fixture,score_pair

inputs,cases,work,friends=fixture()
a,t=cases['old'];b=cases['future'][0]
extra=[{'P1':x,'P2':b,'STATUS':'CONFIRMED','CONFIRMED_ON':date(2025,1,1),'SOURCE':'synthetic route fixture'} for x in [a,t]]
friends=friends+extra
inputs={k:SOURCE+'.AFFINITY_FIXTURE_V2_'+k.upper() for k in inputs}
inputs['friends']=SOURCE+'.AFFINITY_ROUTE_FIXTURE_V2_FRIENDS'
with connect() as con:
    c=con.cursor()
    c.execute(f'CREATE TABLE IF NOT EXISTS {inputs["friends"]} (P1 VARCHAR,P2 VARCHAR,STATUS VARCHAR,CONFIRMED_ON DATE,SOURCE VARCHAR) CHANGE_TRACKING=TRUE')
    c.execute(f'SELECT COUNT(*) FROM {inputs["friends"]}')
    if c.fetchone()[0]==0:
        c.executemany(f'INSERT INTO {inputs["friends"]} VALUES (%s,%s,%s,%s,%s)',[tuple(r[k] for k in ['P1','P2','STATUS','CONFIRMED_ON','SOURCE']) for r in friends])
run_id=uuid.uuid4().hex
cfg,session=local_configuration(8)
try:
    n=IntroductionGraph(t,source_id=a,config=cfg,inputs=inputs)
    strongest=records(build_query(n,EXAMPLE).meta(route_fixture_id=run_id).to_df())
    shortest=records(build_query(n,EXAMPLE.replace('best_route(', 'shortest_route(')).meta(route_fixture_id=run_id).to_df())
    assert len(strongest)==len(shortest)==1
    assert strongest[0]['minimum_hops']==shortest[0]['minimum_hops']==1
    assert strongest[0]['hops']==2 and strongest[0]['path']=='|'.join([a,b,t])
    assert math.isclose(strongest[0]['strength'],.25*.25,abs_tol=1e-10)
    assert shortest[0]['hops']==1 and shortest[0]['path']=='|'.join([a,t])
    assert math.isclose(shortest[0]['strength'],score_pair(a,t,work,friends)['strength'],abs_tol=1e-8)
    transactions=session.sql('SELECT ID,STATE FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:route_fixture_id::STRING=?',params=[run_id]).collect()
    assert len(transactions)==2 and all(r['STATE']=='COMPLETED' for r in transactions)
    report={'status':'PASS','strongest':strongest,'shortest':shortest,'transactions':[r.as_dict() for r in transactions]}
    Path('artifacts/affinity_v2_route_fixture.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: strongest route has two hops while native minimum distance and shortest route have one',flush=True)
finally:session.close()
