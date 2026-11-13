"""Population invariants and corruption checks; entirely local, no graph execution."""
import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pytest

from data.corporate import check_corporate, sha256, write_corporate
from data.generate import TABLES, main


@pytest.fixture(scope='module')
def corporate_fixture(tmp_path_factory):
    out = tmp_path_factory.mktemp('corporate') / 'fixture'
    write_corporate(out, people=5_000, companies=50)
    return out


def read_rows(path):
    with path.open(newline='') as fh:
        return list(csv.DictReader(fh))


def replace_rows(out, table, rows):
    path = out / f'{table}.csv'
    with path.open('w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLES[table][1], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads((out / 'MANIFEST.json').read_text())
    manifest['tables'][table].update(rows=len(rows), sha256=sha256(path), bytes=path.stat().st_size)
    (out / 'MANIFEST.json').write_text(json.dumps(manifest))


def test_corporate_population_careers_and_context(corporate_fixture):
    report = check_corporate(corporate_fixture)
    assert report['status'] == 'PASS'
    assert report['people'] == report['current_roles'] == 5_000
    assert report['companies'] == report['current_ceos'] == report['current_cfos'] == 50
    assert report['industry_groups'] == 11
    assert report['hq_states'] > 10
    assert report['employers_per_person']['min'] == 1
    assert report['employers_per_person']['max'] == 6
    assert 3.25 < report['employers_per_person']['mean'] < 3.55
    assert abs(report['tenure_years']['mean_observed'] - 4) < .10
    assert report['tenure_years']['p10'] < report['tenure_years']['median'] < report['tenure_years']['p90']
    assert not report['graph_calculations_run'] and not report['snowflake_modified']
    # Independently inspect the CSV rather than relying only on the validator's report.
    careers = defaultdict(list)
    roles = read_rows(corporate_fixture / 'ROLE_HISTORY.csv')
    for role in roles:
        careers[role['person_id']].append(role)
    for career in careers.values():
        assert 1 <= len(career) <= 6
        assert len(career) == len({r['org_id'] for r in career})
        assert sum(not r['end_date'] for r in career) == 1
        for left, right in zip(career, career[1:]):
            assert date.fromisoformat(left['end_date']) <= date.fromisoformat(right['start_date'])
    employer_counts = Counter(r['org_id'] for r in roles)
    assert report['rai_workload']['same_employer_candidate_role_pairs'] == sum(n*(n-1)//2 for n in employer_counts.values())


def test_corporate_reproducible_and_seed_changes_content(tmp_path):
    outputs = [tmp_path / name for name in ('a', 'b', 'c')]
    for out, seed in zip(outputs, (42, 42, 43)):
        write_corporate(out, people=500, companies=12, seed=seed)
    a, b, c = [{p.name: sha256(p) for p in out.iterdir()} for out in outputs]
    assert a == b
    assert a['PERSON.csv'] != c['PERSON.csv']
    assert a['ROLE_HISTORY.csv'] != c['ROLE_HISTORY.csv']


@pytest.mark.parametrize('corruption,match', [
    ('person_reference', 'Invalid person reference'),
    ('company_reference', 'Invalid company reference'),
    ('overlap', 'Overlapping jobs'),
    ('repeated_employer', 'Repeated employer'),
    ('extra_current_job', 'current job before final job'),
    ('founding', 'predates company founding'),
    ('duplicate_role', 'invalid/duplicate/order-mismatched ID'),
])
def test_validator_checks_content_even_when_hashes_are_updated(corporate_fixture, tmp_path, corruption, match):
    out = tmp_path / 'changed'
    shutil.copytree(corporate_fixture, out)
    roles = read_rows(out / 'ROLE_HISTORY.csv')
    # The first designated CEO has multiple successive jobs.
    assert roles[0]['person_id'] == roles[1]['person_id']
    if corruption == 'person_reference':
        roles[0]['person_id'] = 'CORP_P999999999'
    elif corruption == 'company_reference':
        roles[0]['org_id'] = 'CORP_C999999'
    elif corruption == 'overlap':
        roles[1]['start_date'] = roles[0]['start_date']
    elif corruption == 'repeated_employer':
        roles[1]['org_id'] = roles[0]['org_id']
    elif corruption == 'extra_current_job':
        roles[0]['end_date'] = ''
    elif corruption == 'founding':
        roles[0]['start_date'] = '1800-01-01'
    elif corruption == 'duplicate_role':
        roles[1]['role_id'] = roles[0]['role_id']
    replace_rows(out, 'ROLE_HISTORY', roles)
    with pytest.raises(ValueError, match=match):
        check_corporate(out)


def test_hash_changes_and_invalid_options(corporate_fixture, tmp_path):
    out = tmp_path / 'changed'
    shutil.copytree(corporate_fixture, out)
    with (out / 'PERSON.csv').open('a') as fh:
        fh.write('broken\n')
    with pytest.raises(ValueError, match='sha256'):
        check_corporate(out)
    with pytest.raises(FileExistsError):
        write_corporate(out)
    with pytest.raises(ValueError, match='protected'):
        write_corporate(Path(__file__).parents[1] / 'data/csv/new')
    for people, companies in ((100, 5), (100, 1001), (10, 6), (True, 10)):
        with pytest.raises(ValueError):
            write_corporate(tmp_path / 'invalid', people, companies)
    assert not (tmp_path / 'invalid').exists()
    with pytest.raises(ValueError, match='require --corporate'):
        main(['--companies', '1000'])


def test_generator_cli_opt_in(tmp_path, capsys):
    out = tmp_path / 'cli'
    main(['--corporate', '--people', '500', '--companies', '12', '--out', str(out)])
    assert json.loads(capsys.readouterr().out)['people'] == 500
    main(['--corporate-check', '--out', str(out)])
    assert json.loads(capsys.readouterr().out)['status'] == 'PASS'
