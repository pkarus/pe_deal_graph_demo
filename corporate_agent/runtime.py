"""Snowflake handlers: source lookup, dynamic PyRel execution and correlation audit."""
import ast,hashlib,json,time,uuid
from datetime import datetime,timezone
from .dynamic import EXAMPLE,build_query,validate_code
from .model import IntroductionGraph,SOURCE,validate_person_id
from .scoring import VERSION,RAW_SCORING_VERSION,NORMALIZATION,AS_OF,validate_as_of
from .presentation import records as native_records,breakdowns,agent_payload,FORMULA
try:
    from ._build import RUNTIME_SHA256
except ImportError:
    RUNTIME_SHA256='local-development'

ENGINE='alaa_pe_deal_graph_experiment'


def rows(session,sql,params=None):
    return [{k.lower():v for k,v in r.as_dict().items()} for r in session.sql(sql,params=params or []).collect()]


def ready_engine(session):
    sql='SELECT NAME,ID,SIZE,STATUS,VERSION FROM RELATIONALAI.API.ENGINES WHERE NAME=?'
    engine=rows(session,sql,[ENGINE])
    if not engine:raise RuntimeError('Configured RAI engine does not exist')
    if engine[0]['status']=='SUSPENDED':
        session.sql('CALL RELATIONALAI.API.RESUME_REASONER_ASYNC(?,?)',params=['LOGIC',ENGINE]).collect()
    deadline=time.monotonic()+120
    while engine[0]['status']!='READY':
        if engine[0]['status'] not in ['SUSPENDED','PENDING','PROVISIONING','RESUMING'] or time.monotonic()>=deadline:
            raise RuntimeError('RAI engine did not become READY; no fallback is available')
        time.sleep(3)
        engine=rows(session,sql,[ENGINE])
        if not engine:raise RuntimeError('Configured RAI engine disappeared')
    return engine


def find_people(session,person,company,title,team_only):
    args=[];filters=['R.END_DATE IS NULL']
    for value,expr in [(person,'(P.PERSON_ID ILIKE ? OR P.FULL_NAME ILIKE ?)'),
                       (company,'(C.COMPANY_ID ILIKE ? OR C.NAME ILIKE ?)')]:
        if value:
            filters.append(expr);args.extend(['%'+value+'%']*2)
    if team_only:filters.append('T.PERSON_ID IS NOT NULL')
    if title:
        norm=title.lower().strip()
        if norm in ['head of data','data head','head of data analytics']:
            filters.append('H.PERSON_ID IS NOT NULL')
        else:
            aliases={'ceo':'Chief Executive Officer','cfo':'Chief Financial Officer'}
            filters.append('(R.TITLE ILIKE ? OR R.ROLE_TYPE ILIKE ?)')
            args.extend(['%'+aliases.get(norm,title)+'%','%'+title+'%'])
    result=rows(session,f'''SELECT P.PERSON_ID,P.FULL_NAME NAME,R.TITLE,C.COMPANY_ID,C.NAME COMPANY,
            T.PERSON_ID IS NOT NULL ON_TEAM,H.DESIGNATION,H.BASIS DESIGNATION_BASIS,
            COUNT(*) OVER() TOTAL_MATCHES
        FROM {SOURCE}.PERSON P JOIN {SOURCE}.ROLE_HISTORY R ON R.PERSON_ID=P.PERSON_ID
        JOIN {SOURCE}.COMPANY C ON C.COMPANY_ID=R.ORG_ID
        LEFT JOIN {SOURCE}.TEAM_MEMBER T ON T.PERSON_ID=P.PERSON_ID
        LEFT JOIN {SOURCE}.HEAD_OF_DATA H ON H.PERSON_ID=P.PERSON_ID AND H.COMPANY_ID=C.COMPANY_ID
        WHERE {' AND '.join(filters)} ORDER BY P.PERSON_ID LIMIT 20''',args)
    return {'status':'MATCHES' if result else 'NO_MATCH','rows':result,
            'total_matches':result[0]['total_matches'] if result else 0,
            'synthetic_data':True,'team_firm':'Northwind Equity Partners (Synthetic)',
            'query_reference':EXAMPLE,
            'query_context':'Person, Company, Employment, OurTeamMember, Connection, IntroductionRoute, model, graph, center, Sources, best_route, shortest_route, Integer, Float, String. Create query only; the tool executes it.'}


def network_context(session,person_ids,as_of=AS_OF):
    runs=rows(session,f'''SELECT RUN_ID,METADATA_JSON FROM {SOURCE}.NETWORK_RUNS_V2
        WHERE AS_OF=?::DATE AND SCORING_VERSION=? ORDER BY COMPUTED_AT DESC LIMIT 1''',[str(as_of),VERSION])
    if not runs:return {'available':False,'reason':'No validated native RAI cohort snapshot for this date/version'}
    run=runs[0];meta=json.loads(run['metadata_json'])
    metrics=rows(session,f'''SELECT PERSON_ID,COMMUNITY_ID,BETWEENNESS,DEGREE,WEIGHTED_DEGREE
       FROM {SOURCE}.NETWORK_ANALYTICS_V2 WHERE RUN_ID=? AND PERSON_ID IN ({','.join(['?']*len(person_ids))})''',
       [run['run_id'],*person_ids]) if person_ids else []
    return {'available':True,'metadata':meta,'people':metrics,
        'missing_people_mean':'Outside the defined cohort, not zero centrality',
        'affects_strength':False}


def execute_pyrel(session,target_id,source_id,pyrel_code,top_n,as_of=str(AS_OF)):
    request_id=str(uuid.uuid4())
    digest=hashlib.sha256(pyrel_code.encode()).hexdigest()
    started=datetime.now(timezone.utc)
    session.sql(f'''INSERT INTO {SOURCE}.QUERY_AUDIT
        (REQUEST_ID,PYREL_CODE,PYREL_SHA256,TARGET_ID,SOURCE_ID,STARTED_AT,STATUS,RUNTIME_SHA256,SNOWFLAKE_SESSION_ID)
        SELECT ?,?,?,?,?,?::TIMESTAMP_TZ,'RUNNING',?,CURRENT_SESSION() ''',
        params=[request_id,pyrel_code,digest,target_id,source_id,started.isoformat(),RUNTIME_SHA256]).collect()
    query_ids=[];transactions=[];engine=[]
    try:
        as_of=validate_as_of(as_of)
        validate_person_id(target_id)
        if source_id:validate_person_id(source_id)
        if not 1<=top_n<=10:raise ValueError('top_n must be 1–10')
        validate_code(pyrel_code)
        requested=[target_id]+([source_id] if source_id else [])
        existing=rows(session,f'SELECT PERSON_ID FROM {SOURCE}.PERSON WHERE PERSON_ID IN ({",".join(["?"]*len(requested))})',requested)
        if set(requested)-{r['person_id'] for r in existing}:raise ValueError('Unknown endpoint; resolve IDs with find_people first')
        engine=ready_engine(session)
        from relationalai.config.config import ConfigFromActiveSession
        elapsed=(datetime.now(timezone.utc)-started).total_seconds()
        native_budget=max(1,min(8,int((540-elapsed)/60)))
        config=ConfigFromActiveSession(reasoners={'logic':{'name':ENGINE}},
            data={'query_timeout_mins':native_budget,'poll_timeout_mins':native_budget+1})
        config.model.path=None;config.oplog.enabled=False;config.deployment=None
        config.execution.retries.enabled=False
        with session.query_history(include_describe=True) as history:
            context=IntroductionGraph(target_id,source_id=source_id,config=config,source=SOURCE,as_of=as_of)
            query=build_query(context,pyrel_code)
            frame=query.meta(agent_request_id=request_id,agent='CORPORATE_INTRODUCTIONS',pyrel_sha256=digest).to_df()
            records=native_records(frame)
            shortest=any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='shortest_route' for n in ast.walk(ast.parse(pyrel_code)))
            records.sort(key=(lambda r:(r['hops'],-r['raw_strength'],r['connection_id'],r['path'])) if shortest else
                         (lambda r:(-r['raw_strength'],r['hops'],r['connection_id'],r['path'])))
            selected=records[:top_n]
            path_people=sorted({pid for r in selected for pid in r['path'].split('|')})
            if path_people:
                parts=breakdowns(native_records(context.edge_query(path_people).meta(agent_request_id=request_id).to_df()),
                    native_records(context.period_query(path_people).meta(agent_request_id=request_id).to_df()),as_of)
                for row in selected:
                    ids=row['path'].split('|')
                    row['edge_decomposition']=[parts[tuple(sorted((a,b)))] for a,b in zip(ids,ids[1:])]
        query_ids=[q.query_id for q in history.queries]
        transactions=rows(session,'''SELECT ID,DATABASE_NAME,STATE,ENGINE_NAME,CREATED_ON,FINISHED_AT,DURATION,ATTRIBUTES
            FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:agent_request_id::STRING=? ORDER BY CREATED_ON''',[request_id])
        if not transactions and query_ids:
            transactions=rows(session,f'''SELECT ID,DATABASE_NAME,STATE,ENGINE_NAME,CREATED_ON,FINISHED_AT,DURATION,ATTRIBUTES
                FROM RELATIONALAI.API.TRANSACTIONS WHERE ID IN ({','.join(['?']*len(query_ids))})''',query_ids)
        required={'connection_id','connection','target_id','target','strength','raw_strength','reason','hops','minimum_hops','path'}
        if not required.issubset(frame.columns):raise ValueError('Return every required column alias: '+', '.join(sorted(required)))
        allowed={source_id} if source_id else {r['person_id'] for r in rows(session,f'SELECT PERSON_ID FROM {SOURCE}.TEAM_MEMBER')}
        for row in records:
            if row['target_id']!=target_id or row['connection_id'] not in allowed or row['hops'] not in [1,2]:
                raise ValueError('Query returned rows outside the requested endpoint/source/hop scope')
            if not 0<=row['strength']<=1 or not 0<=row['raw_strength']<=1 or not row['reason']:raise ValueError('Incomplete relationship evidence')
        if not transactions or not all(r['state']=='COMPLETED' for r in transactions):
            raise RuntimeError('Native RAI execution could not be correlated to a completed transaction')
        result={'status':'OK' if records else 'NO_PATH_WITHIN_2_HOPS','rows':selected,
                'total_connections':len(records),'displayed':min(len(records),top_n),'sources_searched':len(allowed),
                'total_connections_definition':'Number of starting people with a qualifying selected witness; NOT a count of all routes',
                'all_routes_enumerated':False,'direct_connections':sum(r['minimum_hops']==1 for r in records),
                'direct_connections_definition':'Starting people in this result with a direct modeled edge, even if a stronger two-hop witness was selected',
                'request_id':request_id,'transaction_ids':[r['id'] for r in transactions],
                'pyrel_sha256':digest,'algorithm':'native RAI Graph.distance + PyRel employment and strongest-route rules',
                'search_limit_hops':2,'scope':'Exact paths up to two hops; no claim about longer paths or global disconnection',
                'route_formula':'One hop = normalized edge strength; two hops = product of normalized leg strengths = fourth root of raw route product',
                'friendship_policy':'Deferred; preserved facts do not affect scores or create edges',
                'ranking':('Fewest hops, then strongest product' if shortest else 'Strongest product across paths up to two hops, then fewest hops')+'; one deterministic witness per source',
                'scoring_version':VERSION,'raw_scoring_version':RAW_SCORING_VERSION,'normalization':NORMALIZATION,
                'strength_scale':'Normalized 0–1: fourth root of unchanged raw score. Fixed scale, not a probability or percentile.',
                'formula':FORMULA,
                'network_context':network_context(session,path_people,as_of),
                'strength_is_probability':False,'synthetic_data':True,'as_of':str(as_of),
                'seconds':round((datetime.now(timezone.utc)-started).total_seconds(),2)}
        session.sql(f'''UPDATE {SOURCE}.QUERY_AUDIT SET STATUS='COMPLETED',COMPLETED_AT=CURRENT_TIMESTAMP(),
             RAI_TRANSACTION_IDS=PARSE_JSON(?),SNOWFLAKE_QUERY_IDS=PARSE_JSON(?),RESULT=PARSE_JSON(?),ENGINE_STATE=PARSE_JSON(?)
             WHERE REQUEST_ID=?''',params=[json.dumps(result['transaction_ids']),json.dumps(query_ids),
                     json.dumps(result),json.dumps(engine,default=str),request_id]).collect()
        return agent_payload(result)
    except Exception as exc:
        error=f'{type(exc).__name__}: {exc}'[:3000]
        session.sql(f"UPDATE {SOURCE}.QUERY_AUDIT SET STATUS='FAILED',COMPLETED_AT=CURRENT_TIMESTAMP(),ERROR=? WHERE REQUEST_ID=?",params=[error,request_id]).collect()
        return {'status':'ERROR','request_id':request_id,'error':error,'no_fallback_used':True}
