"""Cortex response-limit regression: preserve answers and numeric evidence."""
import copy,json
from corporate_agent.presentation import agent_payload


def result_fixture():
    result={'status':'OK','request_id':'fixture','transaction_ids':['native-fixture'],
            'total_connections':100,'displayed':10,'rows':[]}
    for i in range(10):
        edges=[]
        for j in range(2):
            edge={'left_id':f'CORP_P{i*2+j:09d}','right_id':f'CORP_P{i*2+j+100:09d}',
                  'left_name':'Long synthetic example source name','right_name':'Long synthetic example destination name',
                  'strength':.070000000000001**.25,'raw_strength':.070000000000001,'raw_years':4.,'effective_years':2.,'career_mean_years':20.,
                  'left_career_years':18.,'right_career_years':22.,'career_fraction':.1,'duration_component':.04,
                  'time_score':.070000000000001,'employment_contribution':.070000000000001,
                  'friendship_score':0.,'friendship_contribution':0.,
                  'friendship_status':'Deferred; not used in scoring','friendship_source':'Not used',
                  'evidence':'Representative employment: Example Company: 2010-01-01 to 2014-01-01 (1461 days; Same office); total shared years=4; '+('native evidence '*35),
                  'periods':[{'start_date':'2010-01-01','end_date':'2014-01-01','days':1461,
                      'spatial_factor':1.,'decay_factor':.5,'weighted_days':730.5,
                      'supporting_employment':[{'company':'Example Company','spatial_basis':'Same office'}]}]*5}
            edges.append(edge)
        result['rows'].append({'connection_id':f'PE_P{i:04d}','connection':'Synthetic team member',
            'target_id':'CORP_P000000999','target':'Synthetic CEO','hops':2,'minimum_hops':1,
            'strength':.00490000000000014**.25,'raw_strength':.00490000000000014,'path':f'PE_P{i:04d}|intermediate|target',
            'reason':'Native reason with dated evidence. '*40,'edge_decomposition':edges})
    return result


def test_large_tool_response_preserves_every_answer_and_factor():
    original=result_fixture();before=copy.deepcopy(original)
    result=agent_payload(original)
    assert original==before
    assert len(json.dumps(result,indent=4,ensure_ascii=True).encode())<26000
    assert len(result['rows'])==10
    assert result['transaction_ids']==original['transaction_ids']
    for row,full in zip(result['rows'],original['rows'],strict=True):
        for key in ['connection_id','target_id','hops','minimum_hops','path','strength','raw_strength']:
            assert row[key]==full[key]
        for key,edge in zip(row['edge_ids'],full['edge_decomposition'],strict=True):
            actual=result['edge_details'][key]
            if isinstance(actual,list):actual=dict(zip(result['edge_detail_columns'],actual,strict=True))
            for name,value in edge.items():
                if isinstance(value,(int,float)):assert actual[name]==value


def test_ten_three_hop_routes_fit_and_reconstruct_all_numeric_factors():
    original=result_fixture()
    for i,row in enumerate(original['rows']):
        edge=copy.deepcopy(row['edge_decomposition'][0])
        edge['left_id']=f'CORP_P{i+800:09d}';edge['right_id']=f'CORP_P{i+900:09d}'
        row['edge_decomposition'].append(edge);row['hops']=3
    before=copy.deepcopy(original);result=agent_payload(original)
    assert original==before
    assert len(json.dumps(result,indent=4,ensure_ascii=True).encode())<26000
    assert len(result['rows'])==10 and len(result['edge_details'])==30
    for row,full in zip(result['rows'],original['rows'],strict=True):
        for key,edge in zip(row['edge_ids'],full['edge_decomposition'],strict=True):
            actual=result['edge_details'][key]
            if isinstance(actual,list):actual=dict(zip(result['edge_detail_columns'],actual,strict=True))
            actual={**result.get('edge_detail_constants',{}),**actual}
            for name,value in edge.items():
                if isinstance(value,(int,float)):assert actual[name]==value
