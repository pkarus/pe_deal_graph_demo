"""Format native RAI score outputs. No scores, paths or analytics calculated here."""
import json
from .scoring import VERSION

RAW_FORMULA='0.50 × min(effective_years / mean_career_years, 1) + 0.50 × min(effective_years / 10, 1)²; effective_years = unioned shared days × location × original recency bands / 365.25; friendship deferred'

FORMULA='Normalized strength = sqrt(sqrt(raw_strength)); raw_strength = '+RAW_FORMULA


def records(frame):
    return json.loads(frame.to_json(orient='records',date_format='iso',double_precision=15))


def breakdowns(edge_rows,period_rows,as_of):
    result={}
    for e in edge_rows:
        key=(e['left_id'],e['right_id'])
        result[key]={**e,'scoring_version':VERSION,'as_of':str(as_of),'formula':FORMULA,'periods':[],'synthetic':True}
    periods={}
    for row in period_rows:
        pair=(row['left_id'],row['right_id'])
        if pair not in result:continue
        key=(*pair,row['start_date'],row['end_date'],row['bucket'])
        if key not in periods:
            period={k:row[k] for k in ['start_date','end_date','days','bucket','recency_band','decay_factor','spatial_factor','weighted_days']}
            period['supporting_employment']=[]
            periods[key]=period;result[pair]['periods'].append(period)
        evidence={k:row[k] for k in ['role_a','role_b','company','office_a','office_b','city_a','city_b','spatial_basis','evidence_spatial_factor']}
        if evidence not in periods[key]['supporting_employment']:periods[key]['supporting_employment'].append(evidence)
    for row in result.values():row['periods'].sort(key=lambda r:(r['start_date'],r['end_date']))
    return result


def agent_payload(result):
    """Deduplicate presentation evidence to fit Cortex's 32KB tool envelope.

    The audit retains the full native result. No scores are recalculated here.
    """
    payload={k:v for k,v in result.items() if k!='rows'}
    payload['rows']=[];details={}
    for row in result['rows']:
        item={k:v for k,v in row.items() if k!='edge_decomposition'}
        item['edge_ids']=[]
        for edge in row['edge_decomposition']:
            key=edge['left_id']+'|'+edge['right_id'];item['edge_ids'].append(key)
            if key in details:continue
            detail={k:v for k,v in edge.items() if k not in
                    {'as_of','scoring_version','synthetic','formula','evidence','periods'}}
            detail['representative_employment']=edge['evidence'].split('; total shared years=')[0]
            detail['periods']=[
                f"{p['start_date'][:10]} to {p['end_date'][:10]}: {p['days']} days × "
                f"{p['spatial_factor']} location × {p['decay_factor']} decay = {p['weighted_days']} effective days; "
                +'; '.join(dict.fromkeys(e['company']+' — '+e['spatial_basis'] for e in p['supporting_employment']))
                for p in edge['periods']]
            details[key]=detail
        payload['rows'].append(item)
    payload['edge_details']=details
    payload['full_decomposition']='Every native period and workplace witness is retained in QUERY_AUDIT.RESULT for this request_id and is available in the local edge inspector.'
    if len(json.dumps(payload,indent=4,ensure_ascii=True).encode())>26000:
        for detail in details.values():detail.pop('periods',None)
        payload['period_delivery']='Detailed periods omitted from this tool response to stay within its size limit; all scores, factors and route evidence are included.'
    if len(json.dumps(payload,indent=4,ensure_ascii=True).encode())>26000:
        # Ten distinct three-hop routes can still exceed the envelope after
        # removing periods. A columnar presentation preserves every factor
        # without repeating field names and composite evidence on each row.
        fields=[k for k in next(iter(details.values())) if k not in {'left_id','right_id','periods'}]
        if 'representative_employment' not in fields:fields.append('representative_employment')
        native_edges={e['left_id']+'|'+e['right_id']:e for row in result['rows'] for e in row['edge_decomposition']}
        payload['edge_detail_columns']=fields
        payload['edge_details']={key:[edge.get(k) if k!='representative_employment' else
            edge['evidence'].split('; total shared years=')[0] for k in fields] for key,edge in native_edges.items()}
        for row in payload['rows']:row['reason']='Native evidence for each leg is in edge_details, referenced by edge_ids; the full composite reason is retained in QUERY_AUDIT.RESULT.'
        payload['edge_detail_format']='Columnar: each edge_details array follows edge_detail_columns in order; no numerical values have been changed.'
    if len(json.dumps(payload,indent=4,ensure_ascii=True).encode())>26000 and 'edge_detail_columns' in payload:
        fields=payload['edge_detail_columns'];values=list(payload['edge_details'].values())
        # Factor out repeated constants without dropping a single score/factor.
        common={name:values[0][i] for i,name in enumerate(fields)
                if all(row[i]==values[0][i] for row in values)}
        indices=[i for i,name in enumerate(fields) if name not in common]
        payload['edge_detail_constants']=common
        payload['edge_detail_columns']=[fields[i] for i in indices]
        payload['edge_details']={key:[row[i] for i in indices] for key,row in payload['edge_details'].items()}
        payload['edge_detail_format']+=' Merge edge_detail_constants into each decoded edge; these exact values apply to every edge.'
    return payload
