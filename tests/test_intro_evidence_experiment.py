"""The planted raw facts must imply the expected links, not just expected stories."""
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import intro_evidence_experiment as exp


def pair(a,b):
    return tuple(sorted((a,b)))


def test_raw_facts_and_strengths():
    actual=exp.original_oracle()
    expected={pair(exp.MARCUS,exp.MAYA):1.0,
              pair(exp.MAYA,exp.TARGET):0.4+0.15*1004/365.25,
              pair(exp.DANA,exp.JORDAN):0.8,
              pair(exp.JORDAN,exp.TARGET):0.7,
              pair(exp.PRIYA,exp.TARGET):0.6}
    assert set(actual)==set(expected)
    for edge,weight in expected.items():
        assert math.isclose(actual[edge]['strength'],weight,abs_tol=1e-12)
        assert actual[edge]['evidence'][0]['text']


@pytest.mark.parametrize('control',[r for r in exp.CRM if r[0].startswith('CONTROL_')],ids=lambda r:r[0])
def test_nonqualifying_crm_does_not_create_personal_connection(monkeypatch,control):
    monkeypatch.setattr(exp,'CRM',[control])
    result=exp.original_oracle()
    assert len(result)==2  # Employment and deal evidence only.
    assert all(item['type']!='K3' for row in result.values() for item in row['evidence'])


def test_threshold_and_route_ranking_have_distinct_effects():
    weights={edge:value['strength'] for edge,value in exp.original_oracle().items()}
    marcus=weights[pair(exp.MARCUS,exp.MAYA)]*weights[pair(exp.MAYA,exp.TARGET)]
    dana=weights[pair(exp.DANA,exp.JORDAN)]*weights[pair(exp.JORDAN,exp.TARGET)]
    priya=weights[pair(exp.PRIYA,exp.TARGET)]
    assert marcus>priya>dana
    # Hop-first ranking still puts the direct connection first.
    assert min([(2,-marcus,'Marcus'),(2,-dana,'Dana'),(1,-priya,'Priya')])[2]=='Priya'
    assert weights[pair(exp.MAYA,exp.TARGET)]>=0.75
    assert weights[pair(exp.PRIYA,exp.TARGET)]<0.75
    assert weights[pair(exp.JORDAN,exp.TARGET)]<0.75


def test_expanded_fixture_has_100_distinct_recorded_seeds_and_resolvable_roles():
    f=exp.expanded_fixture()
    assert f==exp.expanded_fixture()
    assert len(set(f['seeds']))==100
    assert len({pid for _,pid,org,*_ in f['roles'] if org=='INTRO_TEAM'})==100
    assert len(f['companies'])==20
    assert sum(r[5]=='Chief Executive Officer' for r in f['roles'])==20
    assert sum(r[7] is not None for r in f['roles'])==40
    assert len({r[0] for r in f['labels']})==len(f['labels'])
    assert not any(f'SCALE_P{i:09d}' in f['seeds'] for i in range(7))


def test_expanded_evidence_uses_original_rules_and_rejects_negative_controls():
    f=exp.expanded_fixture(); edges=exp.original_oracle(f)
    # 100 employees share a recorded workplace; every unordered team pair exists.
    assert all(pair(a,b) in edges for i,a in enumerate(f['seeds']) for b in f['seeds'][i+1:])
    assert math.isclose(edges[pair(f['seeds'][0],'SCALE_P000700000')]['strength'],0.6)
    assert math.isclose(edges[pair(f['seeds'][1],'SCALE_P000700001')]['strength'],0.8)
    assert math.isclose(edges[pair(f['seeds'][2],'SCALE_P000700002')]['strength'],1)
    assert pair(exp.GRACE,exp.TARGET) not in edges
    assert pair(exp.JORDAN,'SCALE_P000700000') in edges


def test_varied_fixture_membership_does_not_create_clique():
    f=exp.varied_fixture()
    assert f==exp.varied_fixture()
    assert len(set(f['seeds']))==100
    assert len({r[0] for r in f['labels']})==len(f['labels'])
    assert len({r[6] for r in f['roles'] if r[0].startswith('EXP_TEAM_')})>5
    evidence=dict(f,roles=f['evidence_roles'])
    edges=exp.original_oracle(evidence)
    assert not any(a in f['seeds'] and b in f['seeds'] for a,b in edges)
    ceos={v['Chief Executive Officer'] for v in f['executives'].values()}
    assert not any(r[2] in ceos for r in f['crm'])
    assert len(edges)<1000
    assert not set(f['mapping'].values()) & set(f['mapping'])


def test_attribute_and_contact_tools_are_paginated_and_separate():
    import intro_contacts
    sql=intro_contacts.attribute_sql('DB.TEST')
    assert "employment==='former'" in sql and 'END_DATE<=' in sql
    assert 'total_people' in sql and 'next_page' in sql
    contacts=intro_contacts.contacts_sql('DB.TEST')
    assert 'all direct contacts, including outside our team' in contacts
    assert 'score_basis' in contacts and 'total_contacts' in contacts
    assert "ORDER BY E.STRENGTH DESC,E.DST LIMIT '+size+' OFFSET '" in contacts
    assert 'Number.isInteger(page)' in contacts


def test_contact_deal_roles_are_explicit_not_inferred_from_titles():
    import intro_contacts
    sql=intro_contacts.contacts_sql('DB.TEST')
    assert 'A.PARTY_ROLE TARGET_ROLE' in sql and 'B.PARTY_ROLE CONTACT_ROLE' in sql
    assert 'participants:' in sql and 'role:d.target_role' in sql
    search=intro_contacts.attribute_sql('DB.TEST')
    assert 'title,expanded,title,expanded' in search # CTO must not match Director.
