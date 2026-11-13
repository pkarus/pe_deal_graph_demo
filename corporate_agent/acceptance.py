"""Validate saved real agent conversations, authored code, SQL calls and RAI logs."""
from pathlib import Path
import hashlib,json,math,re
from scripts.person_path_proc import connect
from .setup import SCHEMA
from .validate import validate

ROOT=Path(__file__).resolve().parents[1]

def same_value(left,right):
    # Snowflake's VARIANT JSON serialization may change the final binary-float
    # digit. This checks presentation round-tripping, not score correctness.
    if isinstance(left,(int,float)) and isinstance(right,(int,float)):
        return math.isclose(left,right,abs_tol=1e-12,rel_tol=0.)
    return left==right


def main():
    cases=[]
    for name in ['ceo','pair','head']:
        document=json.loads((ROOT/f'artifacts/corporate_agent_chat_{name}.json').read_text())
        blocks=document['response']['content']
        uses=[b['tool_use'] for b in blocks if b['type']=='tool_use' and b['tool_use']['name']=='execute_pyrel']
        results=[b['tool_result'] for b in blocks if b['type']=='tool_result' and b['tool_result']['name']=='execute_pyrel']
        assert len(uses)==len(results)==1,(name,'expected one successful dynamic query')
        envelope=results[0]['content'][0]['json']
        result=json.loads(envelope['result'])
        code=uses[0]['input']['pyrel_code']
        assert result['status']=='OK'
        assert result['scoring_version']=='corporate-affinity-v5' and result['normalization']=='fourth-root-v1'
        assert hashlib.sha256(code.encode()).hexdigest()==result['pyrel_sha256']
        verified=validate(result['request_id'])
        assert code==verified['pyrel_code']
        audited=verified['result']
        assert result['total_connections']==audited['total_connections']
        assert result['direct_connections']==audited['direct_connections']
        for compact,full in zip(result['rows'],audited['rows'],strict=True):
            for key in ['connection_id','target_id','path','hops','minimum_hops','strength','raw_strength']:
                assert same_value(compact[key],full[key]),(name,key)
            if 'edge_detail_columns' not in result:assert compact['reason']==full['reason']
            assert len(compact['edge_ids'])==len(full['edge_decomposition'])
            for edge_id,edge in zip(compact['edge_ids'],full['edge_decomposition'],strict=True):
                assert edge_id==edge['left_id']+'|'+edge['right_id']
                detail=result['edge_details'][edge_id]
                if isinstance(detail,list):detail=dict(zip(result['edge_detail_columns'],detail,strict=True))
                for key,value in detail.items():
                    if key=='representative_employment':assert edge['evidence'].startswith(value)
                    elif key!='periods':assert same_value(value,edge[key]),(name,edge_id,key,value,edge[key])
        if name=='pair':assert 'strength >= 0.1' in code and result['rows'][0]['hops']==2
        prior=next(c for c in json.loads((ROOT/'artifacts/corporate_agent_acceptance_v4.json').read_text())['cases'] if c['case']==name)
        assert result['total_connections']==prior['total_connections']
        for current,old in zip(result['rows'],prior['rows'],strict=True):
            for field in ['connection_id','target_id','path','hops','minimum_hops']:assert current[field]==old[field],(name,field)
            assert math.isclose(current['raw_strength'],old['strength'],abs_tol=1e-12)
            assert math.isclose(current['strength'],old['strength']**.25,abs_tol=1e-12)

        answer=[b['text'] for b in blocks if b['type']=='text'][-1]
        assert not re.search(r"(?:couldn['’]t|could not|cannot|can['’]t|unable to) introduce",answer,re.I),(name,'unsupported assertion of real-world inability')
        assert result['request_id'] in answer and result['transaction_ids'][0] in answer
        assert 'normaliz' in answer.lower(),(name,'normalized scale must be labeled')
        for row in result['rows']:
            table_line=next(line for line in answer.splitlines() if line.startswith('|') and row['connection_id'] in line)
            numbers=[float(x) for x in re.findall(r'(?<![A-Za-z0-9_.])(?:0|1)\.\d+',table_line)]
            assert any(math.isclose(x,row['strength'],abs_tol=5.01e-5) for x in numbers),(name,'normalized score missing from table',table_line)
        assert all(col in answer for col in ['Connection','Target','Strength','Reason'])
        cases.append({'case':name,'question':document['question'],'role':document['role'],
          'seconds':document['seconds'],'request_id':result['request_id'],
          'call_query_id':envelope['query_id'],'native_transaction_ids':result['transaction_ids'],
          'total_connections':result['total_connections'],'returned_paths_verified':len(result['rows']),
          'response_language_verified':True,'raw_v4_paths_and_scores_preserved':True,'normalized_table_values_verified':True,
          'agent_authored_pyrel':code,'response':answer,'rows':result['rows']})
    with connect() as con:
        c=con.cursor()
        ids=[case['call_query_id'] for case in cases]
        c.execute(f'''SELECT QUERY_ID,SESSION_ID,QUERY_TYPE,EXECUTION_STATUS,ROLE_NAME,START_TIME,END_TIME,
            TOTAL_ELAPSED_TIME,QUERY_TEXT
            FROM TABLE(ALAA_RELAPP_PERSISTENCE.INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER(
              END_TIME_RANGE_START=>DATEADD(hour,-4,CURRENT_TIMESTAMP()),RESULT_LIMIT=>10000,
              INCLUDE_CLIENT_GENERATED_STATEMENT=>TRUE))
            WHERE QUERY_ID IN ({','.join(['%s']*len(ids))})''',ids)
        history=[dict(zip([x[0].lower() for x in c.description],row)) for row in c.fetchall()]
        assert len(history)==3,history
        for case in cases:
            parent=next(row for row in history if row['query_id']==case['call_query_id'])
            assert parent['execution_status']=='SUCCESS' and parent['role_name']=='RAI_USER',parent
            c.execute(f'SELECT RUNTIME_SHA256,SNOWFLAKE_SESSION_ID,STARTED_AT,COMPLETED_AT FROM {SCHEMA}.QUERY_AUDIT WHERE REQUEST_ID=%s',(case['request_id'],))
            build,session,start,end=c.fetchone()
            assert len(build)==64
            if session is not None:
                assert session==parent['session_id'] and parent['start_time']<=start and parent['end_time']>=end
            case.update(runtime_sha256=build,parent_call_verified=True,session_correlation_verified=session is not None)
    missing=json.loads((ROOT/'artifacts/corporate_agent_chat_missing.json').read_text())
    assert not any(b['type']=='tool_use' and b['tool_use']['name']=='execute_pyrel' for b in missing['response']['content'])
    lookup=next(b['tool_result'] for b in missing['response']['content'] if b['type']=='tool_result')
    assert json.loads(lookup['content'][0]['json']['result'])['total_matches']==0
    report={'status':'PASS','agent':SCHEMA+'.CORPORATE_INTRODUCTIONS','cases':cases,
      'snowflake_parent_query_history':history,'missing_company_control':'PASS: no invented target, no graph invocation',
      'team':json.loads((ROOT/'data/pe_team_100/MANIFEST.json').read_text()),
      'search_limit_hops':2,'native_engine':'alaa_pe_deal_graph_experiment',
      'native_log_views':['RELATIONALAI.API.TRANSACTIONS','RELATIONALAI.API.ENGINES'],
      'native_child_visibility':'Native child transactions verified in RAI API; public information-schema history exposes parent CALLs',
      'data_is_synthetic':True}
    (ROOT/'artifacts/corporate_agent_acceptance_v5.json').write_text(json.dumps(report,default=str,indent=2)+'\n')
    print('PASS: all three real agent questions, authored PyRel, independent path oracle, native transactions, parent CALL history and missing-company control',flush=True)


if __name__=='__main__':main()
