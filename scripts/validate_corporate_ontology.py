"""Read-only native regression for the business ontology against prior v5 evidence."""
import argparse
import gzip
import json
import math
import time
import uuid
from pathlib import Path
from datetime import date
from corporate_agent.scoring import ScoredNetwork, SOURCE, AS_OF
from corporate_agent.local import local_configuration
from corporate_agent.runtime import ready_engine
from corporate_agent.model import IntroductionGraph
from corporate_agent.dynamic import EXAMPLE, build_query
from corporate_agent.presentation import records
from pe_deal_graph.corporate_graph import CorporateNeighborhood
from relationalai.semantics import Integer, Float, inspect
from relationalai.semantics.std import math as rai_math, datetime as rai_datetime

ROOT = Path(__file__).resolve().parents[1]


def compare(actual, expected, keys, ignore=()):
    def index(rows):
        result = {tuple(row[k] for k in keys): row for row in rows}
        assert len(result) == len(rows), 'Duplicate result identity'
        return result
    left, right = index(actual), index(expected)
    assert left.keys() == right.keys(), ('Different result identities', len(left), len(right))
    for key, old in right.items():
        new = left[key]
        for field, value in old.items():
            if field in ignore:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                assert math.isclose(new[field], value, rel_tol=1e-8, abs_tol=1e-8), (key, field, new[field], value)
            else:
                assert new[field] == value, (key, field, new[field], value)


def run(phase):
    with gzip.open(ROOT/'artifacts/corporate_ontology_baseline.json.gz', 'rt') as f:
        baseline = json.load(f)
    run_id = uuid.uuid4().hex
    report = {'phase': phase, 'run_id': run_id, 'status': 'RUNNING', 'scoring_version': 'corporate-affinity-v5'}
    print('START', phase, run_id, flush=True)
    cfg, session = local_configuration(8)
    target = 'CORP_P000000373'
    def query(q):
        return records(q.meta(ontology_validation_id=run_id).to_df())
    def sql(statement):
        return [{k.lower(): v for k, v in row.as_dict().items()} for row in session.sql(statement).collect()]
    started = time.monotonic()
    try:
        ready_engine(session)
        if phase == 'domain':
            n = ScoredNetwork(target, config=cfg)
            m, p, c, e = n.model, n.person, n.company, n.employment
            schema = inspect.schema(m)
            assert schema['OurTeamMember'].extends == ('Person',)
            assert 'CareerRole' not in {x.name for x in schema.concepts}
            report['business_schema'] = {name: {'extends': schema[name].extends,
                'properties': [v.name for v in schema[name].properties]}
                for name in ['Person', 'Company', 'Employment', 'OurTeamMember', 'Connection', 'IntroductionRoute']}
            members = query(m.where(n.our_team_member(p)).select(p.id.alias('person_id'), p.name.alias('name')))
            expected = sql(f'SELECT PERSON_ID, FULL_NAME NAME FROM {SOURCE}.TEAM_MEMBER')
            compare(members, expected, ['person_id'])
            assert len(members) == 100
            # Both inverse links must identify the same job, person and company.
            jobs = query(m.where(n.our_team_member(p), p.employment(e), c.employment(e),
                                 e.person(p), e.company(c)).select(
                e.id.alias('role_id'), p.id.alias('person_id'), c.id.alias('company_id'),
                c.name.alias('company'), e.title.alias('title'),
                e.start_date.alias('start_date'),
                (e.end_date | rai_datetime.date.fromordinal(AS_OF.toordinal())).alias('end_date')))
            expected_jobs = sql(f'''SELECT R.ROLE_ID, R.PERSON_ID, R.ORG_ID COMPANY_ID,
                C.NAME COMPANY, R.TITLE, R.START_DATE, COALESCE(R.END_DATE, '2026-10-01'::DATE) END_DATE
                FROM {SOURCE}.TEAM_ROLE_HISTORY R JOIN {SOURCE}.COMPANY C ON C.COMPANY_ID=R.ORG_ID''')
            # JSON/SDK date representations are normalized only for comparison.
            for rows in [jobs, expected_jobs]:
                for row in rows:
                    for field in ['start_date', 'end_date']: row[field] = str(row[field])[:10]
            compare(jobs, expected_jobs, ['role_id'])
            assert len(jobs) == 450 and sum(r['company_id']=='PE_FIRM_NORTHWIND' for r in jobs)==100
            report.update(team_members_verified=len(members), employment_links_verified=len(jobs),
                          membership_source='TEAM_MEMBER', sample_jobs=jobs[:3])
        elif phase == 'fixtures':
            inputs = {k: SOURCE+'.AFFINITY_FIXTURE_V4_'+k.upper() for k in ['work','people','team','company','cohort']}
            n = ScoredNetwork(mode='cohort', config=cfg, inputs=inputs)
            edges = query(n.edge_query())
            compare(edges, baseline['fixture']['rows'], ['left_id','right_id'], ignore=['evidence'])
            periods = query(n.period_query())
            for edge in edges:
                # A period may have several supporting role pairs; deduplicate its temporal slice.
                slices = {(r['start_date'],r['end_date'],r['bucket']): r['weighted_days']
                    for r in periods if r['left_id']==edge['left_id'] and r['right_id']==edge['right_id']}
                assert math.isclose(sum(slices.values())/365.25, edge['effective_years'], abs_tol=1e-8)
            inputs = {k: SOURCE+'.AFFINITY_ROUTE_FIXTURE_V4_'+k.upper() for k in ['work','people','team','company']}
            a, t = 'CORP_P000900001', 'CORP_P000900003'
            n = IntroductionGraph(t, source_id=a, config=cfg, inputs=inputs)
            r = n.introduction_route
            routes = query(n.model.select(r.path.alias('path'), r.source.id.alias('connection_id'),
                r.target.id.alias('target_id'), r.hops.alias('hops'),
                r.strength.alias('strength'), r.raw_strength.alias('raw_strength')))
            for expected in baseline['routes']['strongest'] + baseline['routes']['shortest']:
                actual = [row for row in routes if row['path'] == expected['path']]
                compare(actual, [{k: expected[k] for k in actual[0]}], ['path'])
            via = n.person.ref()
            intermediates = query(n.model.where(r.via(via)).select(r.path.alias('path'), via.id.alias('person_id')))
            assert {(row['path'], row['person_id']) for row in intermediates} == {
                (row['path'], row['path'].split('|')[1]) for row in routes if row['hops'] == 2}
            for key, code in [('strongest', EXAMPLE), ('shortest', EXAMPLE.replace('best_route(', 'shortest_route('))]:
                result = query(build_query(n, code))
                compare(result, baseline['routes'][key], ['connection_id'], ignore=['reason'])
            n = IntroductionGraph(t, config=cfg, inputs=inputs)
            result = query(build_query(n, EXAMPLE))
            compare(result, baseline['routes']['strongest'], ['connection_id'], ignore=['reason'])
            report.update(scoring_cases_verified=len(baseline['fixture']['cases']),
                          scoring_edges_verified=len(edges), strongest_and_shortest_routes_unchanged=True,
                          default_team_and_named_source_agree=True)
            report['introduction_route_objects_verified'] = len(routes)
        elif phase == 'neighborhoods':
            report['neighborhoods'] = []
            for old in baseline['neighborhoods']:
                pid = old['records'][0]['source_id']; start = time.monotonic()
                n = CorporateNeighborhood(pid, config=cfg)
                actual = query(n.query())
                compare(actual, old['records'], ['person_id'], ignore=['evidence'])
                report['neighborhoods'].append({'person_id': pid, 'edges_verified': len(actual),
                    'seconds': round(time.monotonic()-start,2), 'previous_seconds': old['computation_seconds']})
                print('PASS neighborhood', report['neighborhoods'][-1], flush=True)
        elif phase == 'cohort':
            threshold = (.02/.75)**.25
            n = ScoredNetwork(mode='cohort', min_strength=threshold, config=cfg)
            old = baseline['cohort']
            edges = query(n.edge_query(min_strength=threshold))
            compare(edges, old['edges'], ['left_id','right_id'], ignore=['evidence'])
            m,p = n.model,n.person
            labels = n.affinity_graph.louvain(max_levels=5,randomization_seed=42)
            between = n.graph.betweenness_centrality(num_pivots=2100)
            degree, weighted = n.graph.degree(), n.affinity_graph.weighted_degree()
            who, group, score, d, w = p.ref(),Integer.ref(),Float.ref(),Integer.ref(),Float.ref()
            nodes = query(m.where(labels(who,group),between(who,score),degree(who,d),weighted(who,w)).select(
                who.id.alias('person_id'),who.name.alias('name'),group.alias('community_id'),
                rai_math.maximum(0.,score).alias('betweenness'),d.alias('degree'),w.alias('weighted_degree')))
            compare(nodes, old['nodes'], ['person_id'], ignore=['community_id'])
            def partition(rows):
                groups={}
                for r in rows: groups.setdefault(r['community_id'],set()).add(r['person_id'])
                return {frozenset(ids) for ids in groups.values()}
            assert partition(nodes)==partition(old['nodes']), 'Community membership changed'
            report.update(edges_verified=len(edges), nodes_verified=len(nodes),
                          betweenness_and_degrees_unchanged=True, community_partition_unchanged=True)
        report['transactions'] = sql(f"SELECT ID,STATE,DURATION FROM RELATIONALAI.API.TRANSACTIONS WHERE ATTRIBUTES:ontology_validation_id::STRING='{run_id}'")
        assert report['transactions'] and all(t['state']=='COMPLETED' for t in report['transactions'])
        report['status'] = 'PASS'
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        report['seconds']=round(time.monotonic()-started,2)
        (ROOT/f'artifacts/corporate_ontology_{phase}.json').write_text(json.dumps(report,default=str,indent=2)+'\n')
        session.close()
    print(json.dumps(report,default=str,indent=2),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['domain','fixtures','neighborhoods','cohort'])
    run(parser.parse_args().phase)
