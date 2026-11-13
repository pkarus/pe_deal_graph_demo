"""Run only after explicit approval: one temporary medium-engine benchmark."""
import argparse,json,math,sys,threading,time,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
from scripts.person_path_proc import connect
from corporate_agent.local import local_configuration
from corporate_agent.model import IntroductionGraph
from corporate_agent.dynamic import EXAMPLE,build_query
from corporate_agent.presentation import records
from corporate_agent.validate import oracle_sql


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--approved-30-minute-test',action='store_true');args=parser.parse_args()
    if not args.approved_30_minute_test:parser.error('Explicit user approval is required before creating additional paid compute.')
    started=time.monotonic();deadline=started+1800;run_id=uuid.uuid4().hex
    name='pe_threehop_m_bench_'+run_id[:8];created=False;removed=False;lock=threading.Lock();session=None
    report={'engine':name,'size':'HIGHMEM_X64_M','benchmark_id':run_id,'status':'STARTED'}
    def cleanup():
        nonlocal removed
        with lock:
            if created and not removed:
                with connect() as con:con.cursor().execute('CALL RELATIONALAI.API.DELETE_REASONER(%s,%s)',('logic',name))
                removed=True
    timer=threading.Timer(1800,cleanup);timer.daemon=True
    try:
        with connect() as con:
            c=con.cursor();c.execute('SELECT COUNT(*) FROM RELATIONALAI.API.ENGINES WHERE NAME=%s',(name,));assert c.fetchone()[0]==0
            c.execute('CALL RELATIONALAI.API.CREATE_REASONER_ASYNC(%s,%s,%s,PARSE_JSON(%s))',('logic',name,'HIGHMEM_X64_M',json.dumps({'auto_suspend_mins':10})))
            created=True;timer.start()
            while time.monotonic()<min(deadline,started+600):
                c.execute('SELECT STATUS FROM RELATIONALAI.API.ENGINES WHERE NAME=%s',(name,));state=c.fetchone()[0]
                if state=='READY':break
                if state in ['FAILED','ERROR']:raise RuntimeError('Temporary engine '+state)
                time.sleep(10)
            else:raise TimeoutError('Temporary engine did not become ready within ten minutes')
        cfg,session=local_configuration(8);cfg.reasoners.logic.name=name;cfg.reasoners.logic.size='HIGHMEM_X64_M'
        model=IntroductionGraph('CORP_P000000373',config=cfg)
        query_start=time.monotonic();actual=records(build_query(model,EXAMPLE).meta(benchmark_id=run_id).to_df())
        report.update(native_seconds=time.monotonic()-query_start,rows=actual)
        actual.sort(key=lambda r:(-r['raw_strength'],r['hops'],r['connection_id'],r['path']))
        checks=[]
        with connect() as con:
            c=con.cursor()
            for row in actual[:5]:
                remaining=int(deadline-time.monotonic())-10
                if remaining<1:raise TimeoutError('Benchmark deadline reached')
                c.execute(f'ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS={min(120,remaining)}')
                c.execute(oracle_sql('CORP_P000000373',row['connection_id']))
                expected=dict(zip([d[0].lower() for d in c.description],c.fetchone()))
                assert row['path']==expected['path'] and row['hops']==expected['hops']
                assert math.isclose(row['raw_strength'],float(expected['raw_strength']),abs_tol=1e-10)
                checks.append(c.sfqid)
        report.update(status='PASS',displayed_path_oracle_queries=checks)
    except Exception as exc:
        report.update(status='FAILED',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        try:cleanup()
        finally:
            timer.cancel()
            if session is not None:session.close()
            report.update(engine_deleted=removed,seconds=time.monotonic()-started)
            (ROOT/'artifacts/three_hop_medium_benchmark.json').write_text(json.dumps(report,indent=2,default=str)+'\n')

if __name__=='__main__':main()
