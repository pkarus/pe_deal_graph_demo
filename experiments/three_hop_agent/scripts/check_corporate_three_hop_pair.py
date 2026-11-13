"""Check actual three-hop search against an independent SQL oracle before deployment."""
import argparse,json,math,time,uuid
from pathlib import Path
from corporate_agent.local import local_configuration
from corporate_agent.model import IntroductionGraph
from corporate_agent.dynamic import EXAMPLE,build_query
from corporate_agent.presentation import records
from corporate_agent.runtime import ready_engine
from corporate_agent.validate import oracle_sql
from scripts.person_path_proc import connect

parser=argparse.ArgumentParser();parser.add_argument('--team',action='store_true');args=parser.parse_args()
source_id='' if args.team else 'PE_P0001'
started=time.monotonic();run_id=uuid.uuid4().hex
cfg,session=local_configuration(8)
try:
 ready_engine(session)
 model=IntroductionGraph('CORP_P000000373',source_id=source_id,config=cfg)
 actual=records(build_query(model,EXAMPLE).meta(three_hop_check=run_id).to_df())
 print('Native rows:',len(actual),'hops:',[r['hops'] for r in actual],'seconds:',time.monotonic()-started,flush=True)
 with connect() as con:
  c=con.cursor();c.execute(oracle_sql('CORP_P000000373',source_id))
  expected=[dict(zip([d[0].lower() for d in c.description],r)) for r in c.fetchall()]
  query_id=c.sfqid
 assert len(actual)==len(expected)>0
 actual.sort(key=lambda r:r['connection_id']);expected.sort(key=lambda r:r['connection_id'])
 for a,e in zip(actual,expected):
  for key in ['connection_id','hops','minimum_hops','path']:assert a[key]==e[key],(key,a,e)
  for key in ['strength','raw_strength']:assert math.isclose(a[key],float(e[key]),abs_tol=1e-10),(key,a,e)
 tx=session.sql('SELECT ID,STATE FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:three_hop_check::STRING=?',params=[run_id]).collect()
 assert tx and all(r['STATE']=='COMPLETED' for r in tx)
 Path('artifacts/corporate_three_hop_'+('team' if args.team else 'pair')+'.json').write_text(json.dumps({'status':'PASS','actual':actual,'expected':expected,'transactions':[r.as_dict() for r in tx],'oracle_query_id':query_id,'seconds':time.monotonic()-started},indent=2,default=str)+'\n')
 print('PASS real pair three-hop search and independent SQL oracle',flush=True)
finally:session.close()
