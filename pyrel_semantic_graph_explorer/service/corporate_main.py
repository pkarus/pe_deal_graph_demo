"""Local viewer for native RAI scores, neighborhoods and cohort analytics."""
from pathlib import Path
import hashlib,json,os,sys,threading,time,uuid
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));os.environ.setdefault('RAI_CONFIG_FILE_PATH',str(ROOT/'raiconfig.yaml'))
from fastapi import FastAPI,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from pe_deal_graph import settings
from corporate_agent.local import local_configuration
from pe_deal_graph.corporate_graph import CorporateNeighborhood
from corporate_agent.scoring import ScoredNetwork,SOURCE,CORPORATE,DEFAULT_PERSON,AS_OF,VERSION,validate_person_id,validate_as_of
from corporate_agent.runtime import ready_engine
from corporate_agent.presentation import records,breakdowns,FORMULA
from scripts.person_path_proc import connect

app=FastAPI(title='Corporate People Graph — RAI',version='5.0')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000','http://127.0.0.1:3000'],allow_methods=['GET'],allow_headers=['*'])
CACHE=ROOT/'pyrel_semantic_graph_explorer/.runtime/affinity-v5';CACHE.mkdir(parents=True,exist_ok=True)
LOCK=threading.Lock()
FINGERPRINT=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in ['corporate_agent/scoring.py','corporate_agent/presentation.py','pe_deal_graph/corporate_graph.py','data/corporate_enrichment_v2/MANIFEST.json'])+SOURCE.encode()).hexdigest()

def read(sql,params=()):
    with connect() as con:
        c=con.cursor();c.execute(sql,params);names=[col[0].lower() for col in c.description]
        return [dict(zip(names,row)) for row in c.fetchall()]

def validate(pid=None,as_of=str(AS_OF)):
    try:
        if pid:validate_person_id(pid)
        return validate_as_of(as_of)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

def snapshot(as_of):
    runs=read(f'''SELECT RUN_ID,METADATA_JSON FROM {SOURCE}.NETWORK_RUNS_V2 WHERE AS_OF=%s::DATE
         AND SCORING_VERSION=%s ORDER BY COMPUTED_AT DESC LIMIT 1''',(str(as_of),VERSION))
    return {**json.loads(runs[0]['metadata_json']),'run_id':runs[0]['run_id']} if runs else None

def metrics(ids,as_of):
    meta=snapshot(as_of)
    if not meta:return {},None
    result=read(f'''SELECT PERSON_ID,COMMUNITY_ID,BETWEENNESS,DEGREE,WEIGHTED_DEGREE FROM {SOURCE}.NETWORK_ANALYTICS_V2
       WHERE RUN_ID=%s AND PERSON_ID IN ({','.join(['%s']*len(ids))})''',(meta['run_id'],*ids)) if ids else []
    return {r['person_id']:r for r in result},meta

def person_profile(pid,as_of=AS_OF):
    found=read(f'SELECT PERSON_ID ID,FULL_NAME NAME FROM {SOURCE}.PERSON WHERE PERSON_ID=%s',(pid,))
    if not found:raise HTTPException(404,'Person not found')
    history=read(f'''SELECT R.ROLE_ID,R.ORG_ID COMPANY_ID,C.NAME COMPANY,R.ROLE_TYPE,R.TITLE,R.START_DATE,R.END_DATE,
       W.OFFICE_ID,W.CITY_ID,W.WORK_MODE,
       DATEDIFF(day,R.START_DATE,LEAST(COALESCE(R.END_DATE,%s::DATE),%s::DATE))/365.25 TENURE_YEARS
       FROM {SOURCE}.ROLE_HISTORY R JOIN {SOURCE}.COMPANY C ON C.COMPANY_ID=R.ORG_ID
       LEFT JOIN {SOURCE}.WORKPLACE_V2 W ON W.ROLE_ID=R.ROLE_ID
       WHERE R.PERSON_ID=%s AND R.START_DATE<%s::DATE ORDER BY R.START_DATE''',(str(as_of),str(as_of),pid,str(as_of)))
    m,meta=metrics([pid],as_of)
    return {**found[0],'history':history,'network':m.get(pid),'network_scope':meta['scope'] if meta else None,'as_of':str(as_of)}

def native_cached(key,calculate,refresh=False):
    path=CACHE/(hashlib.sha256(f'{FINGERPRINT}:{key}'.encode()).hexdigest()+'.json')
    with LOCK:
        if path.exists() and not refresh:return json.loads(path.read_text()),True
        started=time.monotonic();cfg,session=local_configuration(12);ready_engine(session)
        try:
            request_id=uuid.uuid4().hex
            with session.query_history(include_describe=True) as history:result=calculate(cfg,request_id)
            ids=[q.query_id for q in history.queries]
            native=session.sql('SELECT ID,STATE FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:explorer_request_id::STRING=?',params=[request_id]).collect()
            if not native or any(r['STATE']!='COMPLETED' for r in native):raise RuntimeError('Native transaction not verified')
            result.update(transaction_ids=[r['ID'] for r in native],computed_at=datetime.now(timezone.utc).isoformat(),
                          computation_seconds=round(time.monotonic()-started,2),scoring_version=VERSION)
            path.write_text(json.dumps(result,default=str));return result,False
        except HTTPException:
            raise
        except Exception as exc:
            import logging
            logging.exception('Native RAI calculation failed')
            raise HTTPException(502,'RAI calculation failed; see local service log. No fallback was used.') from exc
        finally:
            session.close()

@app.get('/api/corporate/health')
def health():return {'status':'ok','source':SOURCE,'default_person':DEFAULT_PERSON,'as_of':str(AS_OF),'scoring_version':VERSION}

@app.get('/api/corporate/search')
def search(q:str=Query('',max_length=120),limit:int=Query(20,ge=1,le=50)):
    term='%'+q.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
    return read(f'''SELECT P.PERSON_ID ID,P.FULL_NAME NAME,R.TITLE,C.NAME COMPANY FROM {SOURCE}.PERSON P
       JOIN {SOURCE}.ROLE_HISTORY R ON R.PERSON_ID=P.PERSON_ID JOIN {SOURCE}.COMPANY C ON C.COMPANY_ID=R.ORG_ID
       WHERE R.END_DATE IS NULL AND (P.PERSON_ID ILIKE %s ESCAPE '!' OR P.FULL_NAME ILIKE %s ESCAPE '!'
       OR C.NAME ILIKE %s ESCAPE '!') ORDER BY P.PERSON_ID LIMIT %s''',(term,term,term,limit))

@app.get('/api/corporate/person/{person_id}')
def person(person_id:str,as_of:str=str(AS_OF)):return person_profile(person_id,validate(person_id,as_of))

@app.get('/api/corporate/neighborhood/{person_id}')
def neighborhood(person_id:str,min_strength:float=Query(0.,ge=0,le=1),limit:int=Query(40,ge=1,le=150),refresh:bool=False,as_of:str=str(AS_OF)):
    when=validate(person_id,as_of);center=person_profile(person_id,when)
    def calculate(cfg,request_id):return {'records':records(CorporateNeighborhood(person_id,min_strength,config=cfg,as_of=when).run(request_id))}
    result,cached=native_cached(f'neighbors:{person_id}:{min_strength}:{when}',calculate,refresh)
    selected=sorted(result['records'],key=lambda r:(-r['raw_strength'],r['person_id']))[:limit]
    ids=[person_id]+[r['person_id'] for r in selected];metric,meta=metrics(ids,when)
    nodes=[{'id':pid,'concept':'Center' if pid==person_id else 'Person','label':name,
            'attributes':metric.get(pid,{})} for pid,name in [(person_id,center['name'])]+[(r['person_id'],r['name']) for r in selected]]
    edges=[{'id':'--'.join(sorted([person_id,r['person_id']])),'source':person_id,'target':r['person_id'],
      'relationship':f"{r['strength']:.4f}",'label':r['evidence'],'strength':r['strength'],'raw_strength':r['raw_strength'],
      'attributes':{'strength':r['strength']},'summary':r} for r in selected]
    total=int(result['records'][0]['total_neighbors']) if result['records'] else 0
    return {**{k:v for k,v in result.items() if k!='records'},'center':center,'graph':{'nodes':nodes,'edges':edges},
      'total_neighbors':total,'shown_neighbors':len(selected),'has_more':total>len(selected),'cached':cached,
      'source':SOURCE,'engine':settings.ENGINE,'algorithm':'Native RAI Graph.distance + shared PyRel affinity rules',
      'scope':'Exact one-hop incident graph; links between neighbors are outside this view',
      'network_metadata':meta,'as_of':str(when),'min_strength':min_strength,'formula':FORMULA}

@app.get('/api/corporate/edge/{left}/{right}')
def edge(left:str,right:str,as_of:str=str(AS_OF),refresh:bool=False):
    when=validate(left,as_of);validate(right,as_of);a,b=sorted([left,right])
    if a==b:raise HTTPException(422,'Choose two different people')
    def calculate(cfg,request_id):
        n=ScoredNetwork(a,b,mode='pair',as_of=when,config=cfg)
        parts=breakdowns(records(n.edge_query().meta(explorer_request_id=request_id).to_df()),records(n.period_query().meta(explorer_request_id=request_id).to_df()),when)
        if (a,b) not in parts:raise HTTPException(404,'No qualifying connection for this date')
        return parts[(a,b)]
    result,cached=native_cached(f'edge:{a}:{b}:{when}',calculate,refresh)
    return {**result,'cached':cached}

@app.get('/api/corporate/network')
def network(as_of:str=str(AS_OF),community:str='',limit:int=Query(150,ge=1,le=300)):
    when=validate(as_of=as_of);meta=snapshot(when)
    if not meta:raise HTTPException(404,'No validated native RAI cohort snapshot for this date')
    all_nodes=read(f'SELECT * FROM {SOURCE}.NETWORK_ANALYTICS_V2 WHERE RUN_ID=%s ORDER BY BETWEENNESS DESC,PERSON_ID',(meta['run_id'],))
    choices=sorted({r['community_id'] for r in all_nodes})
    chosen=[r for r in all_nodes if not community or r['community_id']==community][:limit]
    ids={r['person_id'] for r in chosen}
    rows=read(f'SELECT P1,P2,STRENGTH,DETAILS_JSON FROM {SOURCE}.NETWORK_EDGES_V2 WHERE RUN_ID=%s ORDER BY STRENGTH DESC',(meta['run_id'],))
    edges=[{'id':r['p1']+'--'+r['p2'],'source':r['p1'],'target':r['p2'],'relationship':f"{r['strength']:.4f}",
      'label':'Native RAI normalized strength','strength':r['strength'],'raw_strength':json.loads(r['details_json'])['raw_strength'],'attributes':{'strength':r['strength']}}
      for r in rows if r['p1'] in ids and r['p2'] in ids]
    return {'metadata':meta,'communities':choices,'shown_nodes':len(chosen),'shown_edges':len(edges),
      'display_scope':'Top cohort nodes by native betweenness; only edges with both endpoints displayed. Metrics use all 2100 cohort nodes.',
      'graph':{'nodes':[{'id':r['person_id'],'concept':'Person','label':r['name'],'attributes':r} for r in chosen],'edges':edges}}
