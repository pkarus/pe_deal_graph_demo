"""Independent CSV oracle for testing RAI output, NEVER used by the explorer.

Usage: python scripts/validate_corporate_neighborhood.py PERSON_ID
Compare every returned neighbor, strongest score, and employment-overlap witness.
"""
from pathlib import Path
from datetime import date
import csv
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/corporate_1m_1000_companies'
AS_OF = date(2026, 10, 1)


def oracle(person_id):
    with (DATA/'ROLE_HISTORY.csv').open() as f:
        career = [r for r in csv.DictReader(f) if r['person_id'] == person_id]
    employers = {r['org_id']:r for r in career}
    expected = {}
    candidates = 0
    rejected = 0
    with (DATA/'ROLE_HISTORY.csv').open() as f:
        for row in csv.DictReader(f):
            if row['org_id'] not in employers or row['person_id'] == person_id:
                continue
            candidates += 1
            focal = employers[row['org_id']]
            start = max(date.fromisoformat(row['start_date']),date.fromisoformat(focal['start_date']))
            end = min(date.fromisoformat(row['end_date']) if row['end_date'] else AS_OF,
                      date.fromisoformat(focal['end_date']) if focal['end_date'] else AS_OF)
            days = (end-start).days
            if days < 365:
                rejected += 1
                continue
            factor = 1 if end >= date(2016,10,1) else .7 if end >= date(2006,10,1) else .4
            strength = factor * min(1.,.4+.15*days/365.25)
            item = {'strength':strength,'company_id':row['org_id'],'overlap_start':str(start),
                    'overlap_end':str(end),'overlap_days':days}
            existing = expected.get(row['person_id'],[])
            if not existing or strength > existing[0]['strength']:
                expected[row['person_id']] = [item]
            elif strength == existing[0]['strength']:
                existing.append(item)
    return expected, {'candidate_roles':candidates,'rejected_under_365_days':rejected}


def validate(person_id):
    caches = ROOT/'pyrel_semantic_graph_explorer/.runtime/neighborhoods'
    cache = next(json.loads(p.read_text()) for p in caches.glob('*.json')
                 if json.loads(p.read_text())['center']['id']==person_id)
    actual = {}
    for row in cache['records']:
        assert row['source_id']==person_id and row['distance']==1
        actual.setdefault(row['person_id'],[]).append(row)
    expected, stats = oracle(person_id)
    assert set(actual)==set(expected), (len(actual),len(expected),list(set(actual)^set(expected))[:10])
    for person, rows in expected.items():
        returned = actual[person]
        assert len(returned)==len(rows), person
        for row in rows:
            got = next(x for x in returned if x['company_id']==row['company_id'])
            assert math.isclose(got['strength'],row['strength'],abs_tol=1e-8), (person,got,row)
            assert got['overlap_days']==row['overlap_days'], (person,got,row)
            assert got['overlap_start'][:10]==row['overlap_start'], person
            assert got['overlap_end'][:10]==row['overlap_end'], person
            assert got['total_neighbors']==len(expected), got
    report = {'person_id':person_id,'status':'PASS','neighbors':len(expected),
              'strongest_evidence_rows':sum(map(len,expected.values())),**stats,
              'algorithm':'RAI Graph.distance(from_=center)',
              'independent_validation':'Complete CSV oracle; IDs, strengths, dates, days, evidence multiplicity and native count',
              'calculation_seconds':cache['computation_seconds']}
    path = ROOT/f'artifacts/corporate_neighborhood_validation_{person_id}.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    validate(sys.argv[1] if len(sys.argv)>1 else 'CORP_P000002008')
