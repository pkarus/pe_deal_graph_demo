"""Native weighted Louvain and exact unweighted cohort betweenness snapshots."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,time,uuid
from collections import Counter
import pandas as pd
from relationalai.semantics import Integer,Float
from relationalai.semantics.std import aggregates as aggs,math as rai_math
from .scoring import ScoredNetwork,SOURCE,VERSION,AS_OF
from .presentation import records

ROOT=Path(__file__).resolve().parents[1]
RAW_THRESHOLD=.02/.75
# Only a configuration threshold; production normalization is evaluated in RAI.
THRESHOLD=RAW_THRESHOLD**.25


def calculate(as_of=AS_OF,threshold=THRESHOLD):
    from .local import local_configuration
    from .runtime import ready_engine
    config,session=local_configuration(20);ready_engine(session)
    n=int(session.sql(f'SELECT COUNT(*) FROM {SOURCE}.LEADERSHIP_COHORT_V2').collect()[0][0])
    run_id=str(uuid.uuid4());start=time.monotonic()
    graph=ScoredNetwork(mode='cohort',min_strength=threshold,as_of=as_of,config=config)
    m,p=graph.model,graph.person
    labels=graph.affinity_graph.louvain(max_levels=5,randomization_seed=42)
    between=graph.graph.betweenness_centrality(num_pivots=n)
    degree=graph.graph.degree();weighted_degree=graph.affinity_graph.weighted_degree()
    who,group,score,d,w=p.ref(),Integer.ref(),Float.ref(),Integer.ref(),Float.ref()
    query=m.where(labels(who,group),between(who,score),degree(who,d),weighted_degree(who,w)).select(
      who.id.alias('person_id'),who.name.alias('name'),group.alias('community_id'),
      rai_math.maximum(0.,score).alias('betweenness'),d.alias('degree'),w.alias('weighted_degree'))
    with session.query_history(include_describe=True) as history:
        nodes=records(query.meta(analytics_run_id=run_id).to_df())
        edges=records(graph.edge_query(min_strength=threshold).meta(analytics_run_id=run_id).to_df())
    query_ids=[q.query_id for q in history.queries]
    (ROOT/'artifacts/corporate_affinity_v5_analytics_raw.json').write_text(json.dumps({'nodes':nodes,'edges':edges,'query_ids':query_ids},default=str))
    tx=session.sql("SELECT ID,STATE,ENGINE_NAME FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:analytics_run_id::STRING=?",params=[run_id]).collect()
    native=[r.as_dict() for r in tx]
    assert native and all(r['STATE']=='COMPLETED' for r in native),(query_ids,native)
    assert len(nodes)==n,(len(nodes),n)
    assert len({r['person_id'] for r in nodes})==n
    report={'run_id':run_id,'as_of':str(as_of),'version':VERSION,'min_strength':threshold,'min_raw_strength':RAW_THRESHOLD,
      'weight_scale':'Native analytics use unchanged raw weights; displayed edge strengths use fourth-root normalization',
      'scope':'Leadership cohort: all 100 PE employees, 1000 current CEOs, 1000 synthetic Heads of Data',
      'node_count':len(nodes),'edge_count':len(edges),'community_count':len({r['community_id'] for r in nodes}),
      'isolated_people':sum(r['degree']==0 for r in nodes),
      'nontrivial_community_count':sum(count>1 for count in Counter(r['community_id'] for r in nodes).values()),
      'community_method':'Native RAI weighted Louvain, seed 42, max_levels 5',
      'betweenness_method':'Native RAI exact UNWEIGHTED betweenness on the score-thresholded cohort topology',
      'betweenness_pivots':n,'betweenness_is_global':False,'transactions':native,
      'computed_at':datetime.now(timezone.utc).isoformat(),'seconds':round(time.monotonic()-start,2),
      'nodes':nodes,'edges':edges}
    path=ROOT/'artifacts/corporate_affinity_v5_analytics.json';path.write_text(json.dumps(report,default=str,indent=2)+'\n')
    print('Native analytics:',{k:v for k,v in report.items() if k not in ['nodes','edges','transactions']},flush=True)
    return report


def validate(report):
    # Independent test oracle, never used to produce the published analytics.
    import networkx as nx
    graph=nx.Graph();graph.add_nodes_from(r['person_id'] for r in report['nodes'])
    graph.add_weighted_edges_from((r['left_id'],r['right_id'],r['raw_strength']) for r in report['edges'])
    expected=nx.betweenness_centrality(graph,normalized=False,weight=None)
    import math
    pairs=[(r['betweenness'],expected[r['person_id']]) for r in report['nodes'] if expected[r['person_id']]>0]
    # RAI versions may count ordered pairs on undirected graphs. Determine the
    # convention once, then verify every value; do not silently normalize it.
    factor=1. if all(math.isclose(a,b,rel_tol=1e-7,abs_tol=5e-4) for a,b in pairs) else 2.
    for row in report['nodes']:
        assert math.isclose(row['betweenness'],factor*expected[row['person_id']],rel_tol=1e-7,abs_tol=5e-4),row
        assert row['degree']==graph.degree(row['person_id'])
        assert math.isclose(row['weighted_degree'],graph.degree(row['person_id'],weight='weight'),abs_tol=1e-7)
    groups={}
    for row in report['nodes']:groups.setdefault(str(row['community_id']),set()).add(row['person_id'])
    modularity=nx.community.modularity(graph,groups.values(),weight='weight')
    assert modularity>0,modularity
    validation={'status':'PASS','all_node_betweenness_verified':len(expected),'native_raw_pair_count_factor':factor,
      'weighted_modularity':modularity,'betweenness_absolute_tolerance':5e-4,
      'max_betweenness_absolute_error':max(abs(r['betweenness']-factor*expected[r['person_id']]) for r in report['nodes']),'degree_and_weighted_degree_verified':True,
      'note':'Louvain partitions can vary; verify coverage and weighted modularity, not identical labels'}
    report['independent_validation']=validation
    (ROOT/'artifacts/corporate_affinity_v5_analytics.json').write_text(json.dumps(report,default=str,indent=2)+'\n')
    print('Analytics validation',validation,flush=True)


def publish(report):
    from scripts.person_path_proc import connect
    from snowflake.connector.pandas_tools import write_pandas
    db,schema=SOURCE.split('.')
    assert report.get('independent_validation',{}).get('status')=='PASS'
    with connect() as con:
        c=con.cursor()
        c.execute(f'''CREATE TABLE IF NOT EXISTS {SOURCE}.NETWORK_RUNS_V2 (
          RUN_ID VARCHAR,AS_OF DATE,SCORING_VERSION VARCHAR,MIN_STRENGTH FLOAT,COMPUTED_AT TIMESTAMP_TZ,METADATA_JSON VARCHAR)''')
        c.execute(f'''CREATE TABLE IF NOT EXISTS {SOURCE}.NETWORK_ANALYTICS_V2 (
          RUN_ID VARCHAR,PERSON_ID VARCHAR,NAME VARCHAR,COMMUNITY_ID VARCHAR,BETWEENNESS FLOAT,DEGREE NUMBER,WEIGHTED_DEGREE FLOAT)''')
        c.execute(f'''CREATE TABLE IF NOT EXISTS {SOURCE}.NETWORK_EDGES_V2 (
          RUN_ID VARCHAR,P1 VARCHAR,P2 VARCHAR,STRENGTH FLOAT,DETAILS_JSON VARCHAR)''')
        nodes=pd.DataFrame([{**{k.upper():str(v) if k=='community_id' else v for k,v in row.items()},'RUN_ID':report['run_id']} for row in report['nodes']])
        edges=pd.DataFrame([{'RUN_ID':report['run_id'],'P1':r['left_id'],'P2':r['right_id'],'STRENGTH':r['strength'],'DETAILS_JSON':json.dumps(r)} for r in report['edges']])
        for table,frame in [('NETWORK_ANALYTICS_V2',nodes),('NETWORK_EDGES_V2',edges)]:
            ok,_,count,_=write_pandas(con,frame,table,database=db,schema=schema,auto_create_table=False)
            assert ok and count==len(frame)
        meta={k:v for k,v in report.items() if k not in ['nodes','edges']}
        # Publishing the run manifest is the visibility boundary: incomplete
        # output rows are never selected by the agent/UI without this record.
        c.execute(f'INSERT INTO {SOURCE}.NETWORK_RUNS_V2 VALUES (%s,%s,%s,%s,%s,%s)',
          (report['run_id'],report['as_of'],VERSION,report['min_strength'],report['computed_at'],json.dumps(meta)))
        for table in ['NETWORK_RUNS_V2','NETWORK_ANALYTICS_V2','NETWORK_EDGES_V2']:
            c.execute(f'GRANT SELECT ON TABLE {SOURCE}.{table} TO ROLE RAI_USER')
    print('Published validated RAI cohort analytics',report['run_id'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reuse',action='store_true');args=p.parse_args()
    result=json.loads((ROOT/'artifacts/corporate_affinity_v5_analytics.json').read_text()) if args.reuse else calculate()
    validate(result);publish(result)
