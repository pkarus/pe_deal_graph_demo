"""Independent Snowflake SQL score/path oracle; never deployed or used for answers."""
import argparse,hashlib,json,math
from pathlib import Path
from scripts.person_path_proc import connect
from .setup import SCHEMA
from .dynamic import validate_code


def oracle_sql(target,source,shortest=False):
    from .scoring import validate_person_id
    validate_person_id(target)
    if source:validate_person_id(source)
    sources=f"SELECT '{source}' PERSON_ID" if source else f'SELECT PERSON_ID FROM {SCHEMA}.TEAM_MEMBER'
    order='HOPS,RAW_STRENGTH DESC,PATH' if shortest else 'RAW_STRENGTH DESC,HOPS,PATH'
    return f"""WITH sources AS ({sources}), anchors AS (SELECT PERSON_ID FROM sources UNION SELECT '{target}'),
    jobs AS (SELECT *,LEAST(COALESCE(END_DATE,'2026-10-01'::DATE),'2026-10-01'::DATE) HI,
      MAX(LEAST(COALESCE(END_DATE,'2026-10-01'::DATE),'2026-10-01'::DATE)) OVER(
        PARTITION BY PERSON_ID ORDER BY START_DATE,ROLE_ID ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) PRIOR_END
      FROM {SCHEMA}.WORKPLACE_V2 WHERE START_DATE<'2026-10-01'::DATE),
    career AS (SELECT PERSON_ID,SUM(GREATEST(0,DATEDIFF(day,GREATEST(START_DATE,COALESCE(PRIOR_END,START_DATE)),HI)))::DOUBLE/365.25 YEARS
      FROM jobs GROUP BY PERSON_ID),
    overlaps AS (SELECT DISTINCT LEAST(A.PERSON_ID,B.PERSON_ID) P1,GREATEST(A.PERSON_ID,B.PERSON_ID) P2,
      GREATEST(A.START_DATE,B.START_DATE) LO,LEAST(A.HI,B.HI) HI,
      CASE WHEN A.WORK_MODE='ONSITE' AND B.WORK_MODE='ONSITE' AND A.OFFICE_ID<>'' AND A.OFFICE_ID=B.OFFICE_ID THEN 1.
        WHEN A.WORK_MODE='ONSITE' AND B.WORK_MODE='ONSITE' AND A.CITY_ID<>'' AND A.CITY_ID=B.CITY_ID THEN .6 ELSE .25 END SPATIAL
      FROM jobs A JOIN anchors F ON A.PERSON_ID=F.PERSON_ID JOIN jobs B ON A.ORG_ID=B.ORG_ID AND A.PERSON_ID<>B.PERSON_ID
      WHERE A.ORG_ID<>'PE_FIRM_NORTHWIND' AND DATEDIFF(day,GREATEST(A.START_DATE,B.START_DATE),LEAST(A.HI,B.HI))>=365),
    boundaries AS (SELECT P1,P2,LO D FROM overlaps UNION SELECT P1,P2,HI FROM overlaps),
    segments AS (SELECT P1,P2,D LO,LEAD(D) OVER(PARTITION BY P1,P2 ORDER BY D) HI FROM boundaries),
    covered AS (SELECT S.P1,S.P2,S.LO,S.HI,MAX(O.SPATIAL) SPATIAL FROM segments S JOIN overlaps O
      ON S.P1=O.P1 AND S.P2=O.P2 AND O.LO<=S.LO AND O.HI>=S.HI WHERE S.HI>S.LO GROUP BY 1,2,3,4),
    bands AS (SELECT TO_DATE(column1) LO,TO_DATE(column2) HI,column3 FACTOR FROM VALUES
      ('2024-10-01','2026-10-01',1.0),('2021-10-01','2024-10-01',0.8),('2016-10-01','2021-10-01',0.5),
      ('2011-10-01','2016-10-01',0.25),('1900-01-01','2011-10-01',0.1)),
    raw_time AS (SELECT P1,P2,SUM(DATEDIFF(day,LO,HI))::DOUBLE/365.25 RAW_YEARS FROM covered GROUP BY 1,2),
    effective AS (SELECT C.P1,C.P2,SUM(DATEDIFF(day,GREATEST(C.LO,B.LO),LEAST(C.HI,B.HI))*C.SPATIAL*B.FACTOR)::DOUBLE/365.25 EFFECTIVE_YEARS
      FROM covered C JOIN bands B ON C.HI>B.LO AND C.LO<B.HI GROUP BY 1,2),
    friends AS (SELECT DISTINCT P1,P2 FROM {SCHEMA}.FRIENDSHIP_V2 WHERE 1=0 AND STATUS='CONFIRMED' AND CONFIRMED_ON<='2026-10-01'::DATE
      AND (P1 IN (SELECT PERSON_ID FROM anchors) OR P2 IN (SELECT PERSON_ID FROM anchors))),
    pairs AS (SELECT P1,P2 FROM overlaps UNION SELECT P1,P2 FROM friends),
    factor_inputs AS (SELECT P.P1,P.P2,COALESCE(R.RAW_YEARS,0) RAW_YEARS,COALESCE(E.EFFECTIVE_YEARS,0) EFFECTIVE_YEARS,
      COALESCE(L.YEARS,0) LEFT_CAREER_YEARS,COALESCE(RC.YEARS,0) RIGHT_CAREER_YEARS,
      IFF(F.P1 IS NOT NULL,1,0) FRIENDSHIP_SCORE
      FROM pairs P LEFT JOIN raw_time R ON P.P1=R.P1 AND P.P2=R.P2 LEFT JOIN effective E ON P.P1=E.P1 AND P.P2=E.P2
      LEFT JOIN friends F ON P.P1=F.P1 AND P.P2=F.P2 LEFT JOIN career L ON P.P1=L.PERSON_ID LEFT JOIN career RC ON P.P2=RC.PERSON_ID),
    factors AS (SELECT *,
      (LEFT_CAREER_YEARS+RIGHT_CAREER_YEARS)/2 CAREER_MEAN_YEARS,
      CASE WHEN CAREER_MEAN_YEARS>0 THEN LEAST(1,EFFECTIVE_YEARS/CAREER_MEAN_YEARS) ELSE 0 END CAREER_FRACTION,
      POWER(LEAST(EFFECTIVE_YEARS/10,1),2) DURATION_COMPONENT,
      .5*CAREER_FRACTION+.5*DURATION_COMPONENT TIME_SCORE,TIME_SCORE EMPLOYMENT_CONTRIBUTION,
      .25*FRIENDSHIP_SCORE FRIENDSHIP_CONTRIBUTION,EMPLOYMENT_CONTRIBUTION+FRIENDSHIP_CONTRIBUTION RAW_STRENGTH,
      SQRT(SQRT(RAW_STRENGTH)) STRENGTH
      FROM factor_inputs),
    ties AS (SELECT P1 A,P2 B,STRENGTH,RAW_STRENGTH FROM factors WHERE STRENGTH>0 UNION ALL SELECT P2,P1,STRENGTH,RAW_STRENGTH FROM factors WHERE STRENGTH>0),
    candidates AS (SELECT A CONNECTION_ID,1 HOPS,STRENGTH,RAW_STRENGTH,A||'|'||B PATH FROM ties WHERE A IN (SELECT PERSON_ID FROM sources) AND B='{target}'
      UNION ALL SELECT L.A,2,L.STRENGTH*R.STRENGTH,L.RAW_STRENGTH*R.RAW_STRENGTH,L.A||'|'||L.B||'|'||R.B FROM ties L JOIN ties R ON L.B=R.A
      WHERE L.A IN (SELECT PERSON_ID FROM sources) AND R.B='{target}' AND L.A<>R.B AND L.A<>L.B AND L.B<>R.B)
    SELECT *,MIN(HOPS) OVER(PARTITION BY CONNECTION_ID) MINIMUM_HOPS
    FROM candidates QUALIFY ROW_NUMBER() OVER(PARTITION BY CONNECTION_ID ORDER BY {order})=1
    ORDER BY {order.replace('PATH','CONNECTION_ID,PATH')}"""


def validate(request_id):
    report={'request_id':request_id}
    with connect() as con:
        c=con.cursor();c.execute(f'SELECT * FROM {SCHEMA}.QUERY_AUDIT WHERE REQUEST_ID=%s',(request_id,))
        audit=dict(zip([d[0].lower() for d in c.description],c.fetchone()))
        assert audit['status']=='COMPLETED',audit.get('error')
        result=json.loads(audit['result']);validate_code(audit['pyrel_code'])
        assert hashlib.sha256(audit['pyrel_code'].encode()).hexdigest()==audit['pyrel_sha256']
        c.execute(oracle_sql(audit['target_id'],audit['source_id'],'shortest_route(' in audit['pyrel_code']))
        expected=[dict(zip([d[0].lower() for d in c.description],r)) for r in c.fetchall()];oracle_query_id=c.sfqid
        by_id={r['connection_id']:r for r in expected}
        for row in result['rows']:
            exp=by_id[row['connection_id']]
            assert row['hops']==exp['hops'] and row['path']==exp['path'],(row,exp)
            assert row['minimum_hops']==exp['minimum_hops'],(row,exp)
            assert math.isclose(row['strength'],float(exp['strength']),abs_tol=1e-8),(row,exp)
            assert math.isclose(row['raw_strength'],float(exp['raw_strength']),abs_tol=1e-10),(row,exp)
            ids=row['path'].split('|')
            c.execute(f'SELECT PERSON_ID,FULL_NAME FROM {SCHEMA}.PERSON WHERE PERSON_ID IN ({",".join(["%s"]*len(ids))})',ids)
            names=dict(c.fetchall());assert names[ids[0]]==row['connection'] and names[ids[-1]]==row['target']
            assert all(names[p] in row['reason'] for p in ids)
            # Independent Python oracle checks every leg and all numeric decomposition fields.
            from tests.affinity_oracle import score_pair
            c.execute(f'SELECT * FROM {SCHEMA}.WORKPLACE_V2 WHERE PERSON_ID IN ({",".join(["%s"]*len(ids))})',ids)
            work=[dict(zip([d[0] for d in c.description],r)) for r in c.fetchall()]
            c.execute(f'SELECT * FROM {SCHEMA}.FRIENDSHIP_V2 WHERE P1 IN ({",".join(["%s"]*len(ids))}) AND P2 IN ({",".join(["%s"]*len(ids))})',ids+ids)
            friends=[dict(zip([d[0] for d in c.description],r)) for r in c.fetchall()]
            product=1.;raw_product=1.
            for edge in row['edge_decomposition']:
                truth=score_pair(edge['left_id'],edge['right_id'],work,friends)
                for k,v in truth.items():assert math.isclose(edge[k],v,abs_tol=1e-8),(k,edge[k],v)
                assert math.isclose(sum(p['weighted_days'] for p in edge['periods'])/365.25,edge['effective_years'],abs_tol=1e-8)
                product*=edge['strength'];raw_product*=edge['raw_strength']
            assert math.isclose(product,row['strength'],abs_tol=1e-8)
            assert math.isclose(raw_product,row['raw_strength'],abs_tol=1e-10)
            assert math.isclose(row['strength'],row['raw_strength']**.25,abs_tol=1e-8)
        if 'strength >' not in audit['pyrel_code']:
            assert result['total_connections']==len(expected)
            assert result['direct_connections']==sum(r['minimum_hops']==1 for r in expected)
            assert [r['connection_id'] for r in result['rows']]==[r['connection_id'] for r in expected[:result['displayed']]]
        ids=json.loads(audit['rai_transaction_ids'])
        c.execute(f'''SELECT T.ID,T.STATE,T.ENGINE_NAME,T.DURATION,T.CREATED_ON,E.STATUS ENGINE_STATUS,E.SIZE
          FROM RELATIONALAI.API.TRANSACTIONS T JOIN RELATIONALAI.API.ENGINES E ON E.NAME=T.ENGINE_NAME
          WHERE T.ID IN ({','.join(['%s']*len(ids))})''',ids)
        transactions=[dict(zip([d[0].lower() for d in c.description],r)) for r in c.fetchall()]
        assert len(transactions)==len(ids) and all(t['state']=='COMPLETED' for t in transactions)
        assert all(t['engine_name']=='alaa_pe_deal_graph_experiment' for t in transactions)
        report.update(status='PASS',returned_paths_verified=len(result['rows']),total_connections=result['total_connections'],
          unfiltered_oracle_connections=len(expected),oracle_query_id=oracle_query_id,transactions=transactions,
          pyrel_code=audit['pyrel_code'],pyrel_sha256=audit['pyrel_sha256'],result=result)
    Path(f'artifacts/corporate_agent_validation_{request_id}.json').write_text(json.dumps(report,default=str,indent=2)+'\n')
    print('PASS independent SQL path oracle and every score component',request_id,flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('request_id');validate(p.parse_args().request_id)
