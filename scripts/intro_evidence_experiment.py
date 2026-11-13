"""Small synthetic CRM/deal/role enrichment over the existing 1M RAI graph.

Creates only CONNECTED_1M_INTRO_TEST. Views retain the original million people
and connections; the on-demand path procedure is reused unchanged. This is a
Snowflake SQL/JavaScript experiment, not a new RAI refresh or Cortex agent test.
The isolated names and facts are planted correctness cases, not customer data.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import runpy
import statistics
import time
from types import SimpleNamespace

import person_path_proc as paths

ROOT = paths.ROOT
AS_OF = "2026-10-01"
TARGET, MAYA, JORDAN = "SCALE_P000004200", "SCALE_P000600001", "SCALE_P000600002"
MARCUS, PRIYA, TOM, DANA, GRACE = "P19079", "P25319", "P26028", "P26070", "P95007"
SEEDS = [MARCUS, PRIYA, TOM, DANA, GRACE]
ORG = "INTRO_TEST_HARBOR"
LABELS = [(TARGET, "Alex Morgan"), (MAYA, "Maya Chen"), (JORDAN, "Jordan Ellis")]
ROLES = [
    ("INTRO_R1", TARGET, ORG, "Harbor Analytics (synthetic)", "Employee", "Director of Partnerships", "2024-01-01", None),
    ("INTRO_R2", MAYA, ORG, "Harbor Analytics (synthetic)", "Employee", "Head of Customer Operations", "2024-01-01", None),
]
PARTIES = [
    ("INTRO_D1", "2025-06-01", ORG, "Majority recap", TARGET, "seller", ORG),
    ("INTRO_D1", "2025-06-01", ORG, "Majority recap", JORDAN, "sell_side_advisor", "INTRO_TEST_ADVISOR"),
]
# Only recent positive person-level interactions by a team member qualify.
CRM = [
    ("INTRO_C1", MARCUS, MAYA, ORG, "2025-03-01", "positive"),
    ("INTRO_C2", MARCUS, MAYA, ORG, "2025-10-01", "positive"),
    ("INTRO_C3", MARCUS, MAYA, ORG, "2026-09-01", "positive"),
    ("INTRO_C4", DANA, JORDAN, "INTRO_TEST_ADVISOR", "2025-04-01", "positive"),
    ("INTRO_C5", DANA, JORDAN, "INTRO_TEST_ADVISOR", "2026-08-01", "positive"),
    ("INTRO_C6", PRIYA, TARGET, ORG, "2026-09-15", "positive"),
    ("CONTROL_NEGATIVE", GRACE, TARGET, ORG, "2026-05-01", "negative"),
    ("CONTROL_OLD", GRACE, TARGET, ORG, "2024-09-30", "positive"),
    ("CONTROL_FUTURE", GRACE, TARGET, ORG, "2026-10-02", "positive"),
    ("CONTROL_ORG_ONLY", GRACE, None, ORG, "2026-07-01", "positive"),
    ("CONTROL_NEUTRAL", GRACE, TARGET, ORG, "2026-06-01", "neutral"),
    ("CONTROL_NON_SEED", JORDAN, TARGET, ORG, "2026-05-01", "positive"),
]
TABLES = {
    "PERSON_LABEL": ("ID VARCHAR, NAME VARCHAR", LABELS),
    "ROLE_HISTORY": ("ROLE_ID VARCHAR, PERSON_ID VARCHAR, ORG_ID VARCHAR, ORG_NAME VARCHAR, ROLE_TYPE VARCHAR, TITLE VARCHAR, START_DATE DATE, END_DATE DATE", ROLES),
    "DEAL_PARTY": ("TRANSACTION_ID VARCHAR, CLOSE_DATE DATE, TARGET_ID VARCHAR, STRUCTURE VARCHAR, LEAD_PERSON_ID VARCHAR, PARTY_ROLE VARCHAR, ORG_ID VARCHAR", PARTIES),
    "CRM_INTERACTION": ("INTERACTION_ID VARCHAR, OUR_PERSON_ID VARCHAR, COUNTERPARTY_PERSON_ID VARCHAR, COUNTERPARTY_ORG_ID VARCHAR, INTERACTION_DATE DATE, SENTIMENT VARCHAR", CRM),
}


def original_oracle(fixture=None):
    """Evaluate the raw added facts with the existing independent Python oracle."""
    fixture = fixture or dict(labels=LABELS,roles=ROLES,parties=PARTIES,crm=CRM,seeds=SEEDS)
    oracle = runpy.run_path(str(ROOT / "data/oracle.py"))
    by_org = defaultdict(list)
    for rid, pid, oid, _, kind, _, start, end in fixture['roles']:
        by_org[oid].append(dict(role_id=rid, person_id=pid, org_id=oid, role_type=kind,
                               start_date=date.fromisoformat(start), end_date=date.fromisoformat(end) if end else None))
    txn, parties = {}, defaultdict(list)
    for tid, closed, target, structure, person, role, org in fixture['parties']:
        txn[tid] = dict(close_date=date.fromisoformat(closed), target_id=target, structure=structure)
        parties[tid].append(dict(lead_person_id=person, party_role=role, org_id=org))
    crm = [dict(interaction_id=r[0], our_person_id=r[1], counterparty_person_id=r[2],
                counterparty_org_id=r[3], interaction_date=date.fromisoformat(r[4]), sentiment=r[5]) for r in fixture['crm']]
    names = dict(fixture['labels'])
    data = SimpleNamespace(roles_by_org=by_org, txn=txn, parties_by_txn=parties, crm=crm,
                           org_name=lambda x: "Harbor Analytics (synthetic)" if x == ORG else x,
                           pname=lambda x: names.get(x, x))
    return oracle["build_knows"](data, set(fixture['seeds']))


def views(schema: str, base: str, edge_schema: str):
    """SQL equivalents of the existing K1/K2/K3 rules used by these facts."""
    yield f"""CREATE VIEW {schema}.PERSON AS
        SELECT P.ID, COALESCE(L.NAME,P.NAME) AS NAME FROM {base}.PERSON P
        LEFT JOIN {schema}.PERSON_LABEL L ON L.ID=P.ID"""
    yield f"""CREATE VIEW {schema}.TEAM_SEEDS AS
        SELECT DISTINCT R.PERSON_ID FROM {base}_SRC.ROLE_HISTORY R
        JOIN {base}_SRC.SPONSOR S ON S.SPONSOR_ID=R.ORG_ID
        WHERE S.NAME='Northwind Equity Partners' AND R.ROLE_TYPE IN ('Deal Team','Operating Partner')
          AND R.START_DATE <= '{AS_OF}'::DATE AND (R.END_DATE IS NULL OR R.END_DATE > '{AS_OF}'::DATE)"""
    yield f"""CREATE VIEW {schema}.ADDED_EVIDENCE AS
        WITH overlap AS (
            SELECT A.PERSON_ID P1, B.PERSON_ID P2, A.ORG_NAME,
                GREATEST(A.START_DATE,B.START_DATE) S,
                LEAST(COALESCE(A.END_DATE,'{AS_OF}'::DATE),COALESCE(B.END_DATE,'{AS_OF}'::DATE)) E,
                DATEDIFF('day',S,E) DAYS
            FROM {schema}.ROLE_HISTORY A JOIN {schema}.ROLE_HISTORY B
              ON A.ORG_ID=B.ORG_ID AND A.PERSON_ID < B.PERSON_ID
        ), crm AS (
            SELECT C.OUR_PERSON_ID A, C.COUNTERPARTY_PERSON_ID B, COUNT(*) N,
                MIN(INTERACTION_DATE) S, MAX(INTERACTION_DATE) E
            FROM {schema}.CRM_INTERACTION C JOIN {schema}.TEAM_SEEDS T ON T.PERSON_ID=C.OUR_PERSON_ID
            WHERE C.SENTIMENT='positive' AND C.COUNTERPARTY_PERSON_ID IS NOT NULL
              AND C.OUR_PERSON_ID <> C.COUNTERPARTY_PERSON_ID
              AND C.INTERACTION_DATE BETWEEN DATEADD('month',-24,'{AS_OF}'::DATE) AND '{AS_OF}'::DATE
            GROUP BY A,B
        )
        SELECT P1,P2,
            (CASE WHEN E >= DATEADD('year',-10,'{AS_OF}'::DATE) THEN 1.0
                  WHEN E >= DATEADD('year',-20,'{AS_OF}'::DATE) THEN 0.7 ELSE 0.4 END)
                * LEAST(1.0,0.4+0.15::DOUBLE*DAYS/365.25)::DOUBLE AS STRENGTH,
            'K1' KIND, 'K1 employment overlap at '||ORG_NAME||': '||S::VARCHAR||' to '||E::VARCHAR||
                ' (as-of date); '||DAYS::VARCHAR||' days' AS EVIDENCE
        FROM overlap WHERE DAYS >= 365
        UNION ALL
        SELECT A.LEAD_PERSON_ID, B.LEAD_PERSON_ID,
            0.7 * CASE WHEN A.CLOSE_DATE >= DATEADD('year',-10,'{AS_OF}'::DATE) THEN 1.0
                       WHEN A.CLOSE_DATE >= DATEADD('year',-20,'{AS_OF}'::DATE) THEN 0.7 ELSE 0.4 END,
            'K2', 'K2 both lead persons on '||A.STRUCTURE||' of Harbor Analytics (synthetic), closed '||
                A.CLOSE_DATE::VARCHAR||'; '||A.PARTY_ROLE||' / '||B.PARTY_ROLE
        FROM {schema}.DEAL_PARTY A JOIN {schema}.DEAL_PARTY B
          ON A.TRANSACTION_ID=B.TRANSACTION_ID AND A.LEAD_PERSON_ID < B.LEAD_PERSON_ID
        UNION ALL
        SELECT LEAST(A,B),GREATEST(A,B),CASE WHEN N=1 THEN 0.6 WHEN N=2 THEN 0.8 ELSE 1.0 END,
            'K3','K3 '||N::VARCHAR||' positive person-level CRM interactions: '||S::VARCHAR||' to '||E::VARCHAR
        FROM crm"""
    # The installation checks these five pairs are absent from the base. Therefore UNION ALL
    # introduces no parallel edges. Multiple added evidence items still select their maximum.
    yield f"""CREATE VIEW {schema}.KNOWS_EDGES AS
        WITH added AS (
            SELECT P1,P2,STRENGTH,EVIDENCE FROM {schema}.ADDED_EVIDENCE
            QUALIFY ROW_NUMBER() OVER (PARTITION BY P1,P2 ORDER BY STRENGTH DESC,KIND,EVIDENCE)=1
        )
        SELECT SRC,DST,STRENGTH,EVIDENCE FROM {edge_schema}.KNOWS_EDGES
        UNION ALL SELECT P1,P2,STRENGTH,EVIDENCE FROM added
        UNION ALL SELECT P2,P1,STRENGTH,EVIDENCE FROM added"""


def install(con, schema, base, edge_schema):
    """Create the isolated test once, without replacing any existing object."""
    cur = con.cursor()
    expected = original_oracle()
    if cur.execute(f"SELECT COUNT(*) FROM {base}.PERSON").fetchone()[0] != 1_000_000:
        raise RuntimeError("Expected the existing one-million-person deployment")
    ids = [TARGET, MAYA, JORDAN, *SEEDS]
    if cur.execute(f"SELECT COUNT(*) FROM {base}.PERSON WHERE ID IN ({','.join(['%s']*len(ids))})", ids).fetchone()[0] != len(ids):
        raise RuntimeError("Fixture people missing")
    for a, b in expected:
        if cur.execute(f"SELECT COUNT(*) FROM {edge_schema}.KNOWS_EDGES WHERE SRC=%s AND DST=%s", (a,b)).fetchone()[0]:
            raise RuntimeError(f"Planted pair already exists: {a}, {b}")
    # CREATE (not CREATE OR REPLACE/IF NOT EXISTS) rejects an existing schema.
    cur.execute(f"CREATE SCHEMA {schema} COMMENT='Isolated synthetic introduction evidence test on 1M; base data read-only'")
    for name, (columns, rows) in TABLES.items():
        cur.execute(f"CREATE TABLE {schema}.{name} ({columns})")
        cur.executemany(f"INSERT INTO {schema}.{name} VALUES ({','.join(['%s']*len(rows[0]))})", rows)
    for sql in views(schema,base,edge_schema):
        cur.execute(sql)
    cur.execute(paths.procedure_sql(schema,schema).replace("CREATE OR REPLACE PROCEDURE", "CREATE PROCEDURE",1))


def validate_added(con, schema):
    cur = con.cursor()
    actual = cur.execute(f"SELECT P1,P2,STRENGTH,KIND,EVIDENCE FROM {schema}.ADDED_EVIDENCE ORDER BY P1,P2").fetchall()
    expected = original_oracle()
    assert {(r[0],r[1]) for r in actual} == set(expected)
    assert len(actual) == len(expected) == 5
    for a,b,strength,kind,evidence in actual:
        item = expected[a,b]
        assert math.isclose(float(strength),item['strength'],abs_tol=1e-9)
        assert kind == item['evidence'][0]['type'] and evidence
    assert {r[0] for r in cur.execute(f"SELECT PERSON_ID FROM {schema}.TEAM_SEEDS")} == set(SEEDS)
    return [dict(p1=a,p2=b,strength=float(w),kind=k,evidence=e) for a,b,w,k,e in actual]


def independent_routes(con,schema,threshold):
    """Exhaustive independent oracle for ALL routes <=3 hops from these seeds.

    Any such route uses a seed edge, a target edge, and (for length 3) an
    edge incident to a target neighbor. Read those edges, not the full graph.
    """
    import networkx as nx
    cur = con.cursor()
    near = [r[0] for r in cur.execute(f"SELECT DST FROM {schema}.KNOWS_EDGES WHERE SRC=%s AND STRENGTH >= %s", (TARGET,threshold))]
    sources = sorted(set(SEEDS+[TARGET]+near))
    rows = cur.execute(f"SELECT SRC,DST,STRENGTH FROM {schema}.KNOWS_EDGES WHERE SRC IN ({','.join(['%s']*len(sources))}) AND STRENGTH >= %s", (*sources,threshold)).fetchall()
    g=nx.Graph()
    g.add_weighted_edges_from((a,b,float(w)) for a,b,w in rows)
    out={}
    for source in SEEDS:
        routes=list(nx.all_shortest_paths(g,source,TARGET))
        assert len(routes[0])-1 <= 3, "The bounded independent oracle cannot validate longer routes"
        ranked=sorted(((math.prod(g[a][b]['weight'] for a,b in zip(r,r[1:])),r) for r in routes), key=lambda v:(-v[0],v[1]))
        strength,route=ranked[0]
        out[source]=dict(distance=len(route)-1,route=route,route_strength=strength,shortest_route_count=len(routes))
    return out, len(rows)


def run_questions(con,schema,repeats=3):
    cur=con.cursor()
    questions=[
        ("Who on our team can connect us to Alex Morgan, and why?",SEEDS,0.0,PRIYA),
        ("How can Marcus reach Alex: how many hops, what strength, and what evidence?",[MARCUS],0.0,MARCUS),
        ("Who should connect us if every link must have strength at least 0.75?",SEEDS,0.75,MARCUS),
        ("How can Dana reach Alex, and what supports those links?",[DANA],0.0,DANA),
    ]
    reference={t:independent_routes(con,schema,t) for t in (0.0,0.75)}
    checks=[]
    for question,sources,threshold,winner in questions:
        timings=[]; attempts=[]
        for repeat in range(repeats):
            results=[]; query_ids=[]; started=time.perf_counter()
            for source in sources:
                row=cur.execute(f"CALL {schema}.PERSON_PATH(%s,%s,%s,%s)",(source,TARGET,12,threshold)).fetchone()
                query_ids.append(cur.sfqid)
                result=json.loads(row[0]) if isinstance(row[0],str) else row[0]
                results.append(result)
            elapsed=time.perf_counter()-started
            for result in results:
                exp=reference[threshold][0][result['source_id']]
                assert result['status']=='reachable'
                for key in ('distance','route','shortest_route_count'):
                    assert result[key]==exp[key], (question,key,result[key],exp[key])
                assert abs(result['route_strength']-exp['route_strength']) <= 0.00000051
                assert all(h['evidence'] and h['strength'] >= threshold-0.00000051 for h in result['hops'])
            results.sort(key=lambda r:(r['distance'],-r['route_strength'],r['source_id']))
            assert results[0]['source_id']==winner
            timings.append(elapsed)
            attempts.append(dict(repeat=repeat+1,seconds=elapsed,query_ids=query_ids,results=results))
            print(f"PASS {question} repeat={repeat+1} calls={len(sources)} seconds={elapsed:.3f}",flush=True)
        checks.append(dict(question=question,min_link_strength=threshold,first_seconds=timings[0],
                           repeat_median_seconds=statistics.median(timings[1:]) if len(timings)>1 else None,
                           winner=attempts[-1]['results'][0],attempts=attempts))
    return dict(questions=checks,reference_edges_read={str(t):r[1] for t,r in reference.items()},
                assertions="All procedure results matched exhaustive shortest routes <=3 hops: distance, strongest product, route and count")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--install',action='store_true')
    ap.add_argument('--test',action='store_true')
    ap.add_argument('--repeats',type=int,default=3)
    args=ap.parse_args()
    if not args.install and not args.test:
        print(json.dumps({f'{a}|{b}':v for (a,b),v in original_oracle().items()},indent=2))
        return
    if args.repeats < 1:
        ap.error('--repeats must be positive')
    base,edges=paths.schemas('connected1m'); schema=base+'_INTRO_TEST'
    started=time.perf_counter(); con=paths.connect(); connect_seconds=time.perf_counter()-started
    try:
        cur=con.cursor(); cur.execute('ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=120')
        identity=cur.execute('SELECT CURRENT_ROLE(),CURRENT_WAREHOUSE(),CURRENT_ACCOUNT(),CURRENT_VERSION()').fetchone()
        if args.install:
            started=time.perf_counter(); install(con,schema,base,edges)
            print(f'Installed {schema} in {time.perf_counter()-started:.3f}s',flush=True)
        added=validate_added(con,schema)
        if args.test:
            report=run_questions(con,schema,args.repeats)
            report.update(as_of=AS_OF,people=1_000_000,schema=schema,base=base,warehouse=identity[1],
                role=identity[0],connect_seconds=connect_seconds,added_edges=added,
                raw_rows={k:len(v[1]) for k,v in TABLES.items()},negative_controls=6,
                evidence_roles=[dict(zip(['id','person_id','org_id','org_name','role_type','title','start','end'],r)) for r in ROLES],
                code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                execution='SQL rule views + existing JavaScript path search over RAI-materialized 1M connections; no new RAI computation',
                limitations=['Planted synthetic evidence tests, not real introduction success.',
                    'Direct query tests, not Cortex natural-language evaluation.',
                    'Warm warehouse; validation preceded timing; first run is not assumed cold.',
                    'End-to-end execute/fetch timings; team question makes five sequential calls.',
                    'No community refresh; original partition is not claimed valid for added links.',
                    'No dense-hub or long-route stress test.'])
            dest=ROOT/'artifacts/intro_evidence_1m.json';dest.write_text(json.dumps(report,indent=2)+'\n')
            print(f'Saved {dest}',flush=True)
    finally:
        con.close()



def expanded_fixture():
    """Deterministic synthetic attributes; all IDs reuse existing million-person nodes."""
    labels, roles, parties, crm = list(LABELS), list(ROLES), list(PARTIES), list(CRM)
    seeds = SEEDS + [f"SCALE_P{800000+i:09d}" for i in range(95)]
    first = ['Avery','Blair','Cameron','Devon','Emerson','Finley','Hayden','Jamie','Kendall','Logan']
    last = ['Adler','Bennett','Chen','Diaz','Evans','Foster','Gupta','Hayes','Ibrahim','Jensen']
    companies = ['Cedarbridge Health','Willow Diagnostics','Summit Home Care','Clearwater Infusion',
        'Oakwell Dental','Pinecrest Analytics','Meadow Rehabilitation','Stonehaven Logistics',
        'Brookfield Software','Redwood Revenue Services','Silverlake Imaging','Fairhaven Pediatrics',
        'Westbrook Medical','Ashford Compliance','Elmwood Therapy','Brightwater Labs',
        'Riverton Devices','Lakehaven Pharmacy','Maplewood Services','Northgate Wellness']
    titles = ['Chief Executive Officer','Chief Financial Officer','Chief Operating Officer',
              'Vice President of Business Development','Director of Partnerships']
    for i, pid in enumerate(seeds):
        if i >= 5:
            labels.append((pid, f"{first[(i-5)//10]} {last[(i-5)%10]}"))
        roles.append((f'EXP_TEAM_{i}',pid,'INTRO_TEAM','Northwind Expansion Team (synthetic)',
                      'Deal Team','Investment Associate' if i>=5 else 'Team Partner','2024-01-01',None))
    for i, company in enumerate(companies):
        org=f'INTRO_COMPANY_{i:02d}'
        for j,title in enumerate(titles):
            k=i*5+j; pid=f'SCALE_P{700000+k:09d}'
            labels.append((pid,f"{first[k//10]} {last[k%10]}-Reed"))
            roles.append((f'EXP_ROLE_{k}',pid,org,company+' (synthetic)','Employee',title,'2024-01-01',None))
            # Different team members have different recent CRM histories.
            for n in range(1+k%3):
                crm.append((f'EXP_CRM_{k}_{n}',seeds[k],pid,org,f'2026-0{n+5}-15','positive'))
        # Two executives previously worked together at a different firm.
        for j in (0,1):
            roles.append((f'EXP_FORMER_{i}_{j}',f'SCALE_P{700000+i*5+j:09d}',f'INTRO_ALUMNI_{i}',
                          company+' Advisory (synthetic)','Employee','Senior Consultant','2015-01-01','2020-01-01'))
        parties.extend([(f'EXP_DEAL_{i}','2025-06-01',org,'Majority recap',f'SCALE_P{700000+i*5:09d}','seller',org),
                        (f'EXP_DEAL_{i}','2025-06-01',org,'Majority recap',JORDAN,'sell_side_advisor','INTRO_TEST_ADVISOR')])
    return {'seeds':seeds,'companies':companies,'labels':labels,'roles':roles,'parties':parties,'crm':crm}


def expanded_view_sql(schema,base,edge_schema):
    """Reuse evidence rules, merge duplicate pairs, and resolve each actual deal target."""
    definitions=list(views(schema,base,edge_schema))
    definitions[1]=f"""CREATE VIEW {schema}.TEAM_SEEDS AS
        SELECT DISTINCT PERSON_ID FROM {schema}.ROLE_HISTORY
        WHERE ORG_ID='INTRO_TEAM' AND ROLE_TYPE='Deal Team'
        AND START_DATE <= '{AS_OF}'::DATE AND (END_DATE IS NULL OR END_DATE > '{AS_OF}'::DATE)"""
    definitions[2]=definitions[2].replace("' of Harbor Analytics (synthetic), closed '||",
        f"' of '||COALESCE((SELECT MIN(R.ORG_NAME) FROM {schema}.ROLE_HISTORY R WHERE R.ORG_ID=A.TARGET_ID),A.TARGET_ID)||', closed '||")
    definitions[3]=f"""CREATE VIEW {schema}.KNOWS_EDGES AS
        WITH candidates AS (
          SELECT SRC,DST,STRENGTH,EVIDENCE FROM {edge_schema}.KNOWS_EDGES
          UNION ALL SELECT P1,P2,STRENGTH,EVIDENCE FROM {schema}.ADDED_EVIDENCE
          UNION ALL SELECT P2,P1,STRENGTH,EVIDENCE FROM {schema}.ADDED_EVIDENCE
        ) SELECT SRC,DST,STRENGTH,EVIDENCE FROM candidates
        QUALIFY ROW_NUMBER() OVER (PARTITION BY SRC,DST ORDER BY STRENGTH DESC,EVIDENCE)=1"""
    return [sql.replace('CREATE VIEW','CREATE OR REPLACE VIEW',1) for sql in definitions]


def expand_team(con):
    """Idempotently extend only INTRO_TEST; never modify base source tables."""
    base,edges=paths.schemas('connected1m'); schema=base+'_INTRO_TEST'
    fixture=expanded_fixture(); cur=con.cursor()
    ids=sorted({r[0] for r in fixture['labels']}|set(fixture['seeds']))
    count=cur.execute(f"SELECT COUNT(*) FROM {base}.PERSON WHERE ID IN ({','.join(['%s']*len(ids))})",ids).fetchone()[0]
    if count!=len(ids):raise RuntimeError('Enrichment references missing people')
    additions={'PERSON_LABEL':fixture['labels'],'ROLE_HISTORY':fixture['roles'],
               'DEAL_PARTY':fixture['parties'],'CRM_INTERACTION':fixture['crm']}
    # Insert missing deterministic records; do not delete or reset any table.
    for table,records in additions.items():
        existing=set(cur.execute(f'SELECT * FROM {schema}.{table}').fetchall())
        normalized={tuple(str(v) if isinstance(v,date) else v for v in row) for row in existing}
        missing=[r for r in records if tuple(r) not in normalized]
        if missing:cur.executemany(f"INSERT INTO {schema}.{table} VALUES ({','.join(['%s']*len(records[0]))})",missing)
    for sql in expanded_view_sql(schema,base,edges):cur.execute(sql.replace(' AS',' COPY GRANTS AS',1))
    actual={r[0] for r in cur.execute(f'SELECT PERSON_ID FROM {schema}.TEAM_SEEDS')}
    if actual!=set(fixture['seeds']):raise RuntimeError('Team membership does not match 100-person fixture')
    return fixture


def varied_fixture():
    """More varied synthetic careers and sparse team contacts, not population realism."""
    import random
    rng=random.Random(20261112)
    f=expanded_fixture()
    # IDs in the scale generator encode workplace groups. Consecutive IDs therefore
    # accidentally made enriched executives and employees former coworkers.
    old=sorted({r[0] for r in f['labels']} - {TARGET,MAYA,JORDAN})
    chosen=rng.sample(range(20000,980000),len(old)+5)
    mapping={pid:f'SCALE_P{n:09d}' for pid,n in zip(old,chosen)}
    def pid(x):return mapping.get(x,x)
    f['seeds']=[pid(x) for x in f['seeds']]
    f['labels']=[(pid(x),name) for x,name in f['labels']]
    f['roles']=[];f['crm']=list(CRM);f['parties']=list(PARTIES)
    f['roles'].extend(ROLES)
    f['members']=[(x, ['Healthcare','Software','Services','Operations','Research'][i%5],
                    f'{2016+i%11}-01-01') for i,x in enumerate(f['seeds'])]
    for i,x in enumerate(f['seeds']):
        f['roles'].append((f'EXP_TEAM_{i}',x,'INTRO_TEAM','Northwind Equity Partners (synthetic)',
            'Deal Team','Investment Associate' if i>=5 else 'Team Partner',f'{2016+i%11}-01-01',None))
    titles=['Chief Executive Officer','Chief Financial Officer','Chief Operating Officer',
            'Vice President of Business Development','Director of Partnerships']
    advisors=[f'SCALE_P{n:09d}' for n in chosen[len(old):]]
    advisor_names=['Leila Morgan','Owen Patel','Nadia Brooks','Mateo Silva','Yasmin Walker']
    f['labels'].extend(zip(advisors,advisor_names))
    f['executives']={}
    for i,company in enumerate(f['companies']):
        org=f'INTRO_COMPANY_{i:02d}'
        executives=[pid(f'SCALE_P{700000+i*5+j:09d}') for j in range(5)]
        f['executives'][company]=dict(zip(titles,executives))
        for j,x in enumerate(executives):
            k=i*5+j
            start=['2021-04-01','2023-02-15','2025-03-01','2026-06-01','2024-09-01'][(i+j)%5]
            if j==0:start='2021-04-01' # Seller was already CEO at the 2025 transaction.
            f['roles'].append((f'EXP_ROLE_{k}',x,org,company+' (synthetic)','Employee',titles[j],start,None))
            # Some companies have no direct team CRM; contacts need not be the CEO.
            if i%4!=3 and (j==1 or (j==2 and i%2==0) or (j==4 and i%3==0)):
                member=f['seeds'][(k*13+7)%100]
                for n in range(1+(i+j)%3):
                    f['crm'].append((f'VAR_CRM_{k}_{n}',member,x,org,f'2026-0{n+5}-15','positive'))
        for j in (0,1):
            f['roles'].append((f'EXP_FORMER_{i}_{j}',executives[j],f'INTRO_ALUMNI_{i}',
                company+' Advisory (synthetic)','Employee','Senior Consultant',
                '2014-01-01' if j==0 else '2018-01-01','2020-01-01'))
        # Selected employees have a genuine historical overlap, not universal team links.
        if i%3==0:
            f['roles'].append((f'VAR_ALUMNI_{i}',f['seeds'][(i*7+9)%100],f'INTRO_ALUMNI_{i}',
                company+' Advisory (synthetic)','Employee','Analyst','2016-01-01','2019-01-01'))
        advisor=advisors[i%5]
        f['parties'].extend([(f'EXP_DEAL_{i}','2025-06-01',org,'Majority recap',executives[0],'seller',org),
            (f'EXP_DEAL_{i}','2025-06-01',org,'Majority recap',advisor,'sell_side_advisor',f'INTRO_ADVISOR_{i%5}')])
    for i,x in enumerate(advisors):
        f['roles'].append((f'VAR_ADVISOR_{i}',x,f'INTRO_ADVISOR_{i}',f'Advisory Practice {i+1} (synthetic)',
            'Employee','Managing Director',f'{2017+i}-01-01',None))
    f['evidence_roles']=[r for r in f['roles'] if not r[0].startswith('EXP_TEAM_')]
    f['mapping']=mapping
    return f


def revise_test_data(con):
    """Replace only the previously generated INTRO_TEST facts; base data is read-only."""
    base,edges=paths.schemas('connected1m');schema=base+'_INTRO_TEST'
    f=varied_fixture();cur=con.cursor()
    ids=sorted({r[0] for r in f['labels']}|set(f['seeds']))
    assert cur.execute(f"SELECT COUNT(*) FROM {base}.PERSON WHERE ID IN ({','.join(['%s']*len(ids))})",ids).fetchone()[0]==len(ids)
    cur.execute(f'CREATE TABLE IF NOT EXISTS {schema}.TEAM_MEMBERS (PERSON_ID VARCHAR, TEAM_NAME VARCHAR, JOIN_DATE DATE)')
    records={'PERSON_LABEL':f['labels'],'ROLE_HISTORY':f['roles'],'DEAL_PARTY':f['parties'],
             'CRM_INTERACTION':f['crm'],'TEAM_MEMBERS':f['members']}
    cur.execute('BEGIN')
    try:
        for table,rows in records.items():
            cur.execute(f'DELETE FROM {schema}.{table}')
            cur.executemany(f"INSERT INTO {schema}.{table} VALUES ({','.join(['%s']*len(rows[0]))})",rows)
        cur.execute('COMMIT')
    except Exception:
        cur.execute('ROLLBACK');raise
    definitions=expanded_view_sql(schema,base,edges)
    definitions[1]=f"CREATE OR REPLACE VIEW {schema}.TEAM_SEEDS AS SELECT PERSON_ID FROM {schema}.TEAM_MEMBERS WHERE JOIN_DATE <= '{AS_OF}'::DATE"
    definitions[2]=definitions[2].replace(f'FROM {schema}.ROLE_HISTORY A JOIN {schema}.ROLE_HISTORY B',
        f"FROM (SELECT * FROM {schema}.ROLE_HISTORY WHERE ROLE_ID NOT LIKE 'EXP_TEAM_%') A JOIN (SELECT * FROM {schema}.ROLE_HISTORY WHERE ROLE_ID NOT LIKE 'EXP_TEAM_%') B")
    for sql in definitions:cur.execute(sql.replace(' AS',' COPY GRANTS AS',1))
    return f

if __name__=='__main__':
    main()
