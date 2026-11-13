"""Local synthetic large-company careers, using the existing 17-table source schema.

No Snowflake connections, RAI execution, or materialized person-to-person edges.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import random
from collections import Counter
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path

from data.generate import AS_OF, FIRST, LAST, US_STATES as STATES, STATE_WEIGHT, TABLES

ROOT = Path(__file__).resolve().parent
EMPLOYER_WEIGHTS = (12, 18, 24, 22, 15, 9)
TENURE_MONTHS = (6, 12, 18, 24, 30, 36, 42, 48, 60, 72, 84, 96, 120, 144)
INDUSTRIES = (
    ('Technology', 'Enterprise technology', 'Software and cloud platforms', 'Technologies', .24, .40),
    ('Financial Services', 'Diversified finance', 'Banking and payments', 'Financial Group', .28, .65),
    ('Healthcare', 'Healthcare enterprises', 'Healthcare products and services', 'Health Group', .14, .25),
    ('Industrials', 'Industrial production', 'Industrial equipment and services', 'Industries', .16, .30),
    ('Consumer Goods', 'Consumer products', 'Household and personal products', 'Consumer Brands', .18, .35),
    ('Retail', 'Retail enterprises', 'General merchandise and ecommerce', 'Retail Group', .07, .30),
    ('Energy', 'Energy enterprises', 'Integrated energy and infrastructure', 'Energy', .19, 1.10),
    ('Telecommunications', 'Communications infrastructure', 'Telecommunications services', 'Communications', .30, .50),
    ('Transportation', 'Transportation enterprises', 'Logistics and transportation', 'Logistics', .12, .25),
    ('Materials', 'Materials production', 'Chemicals and advanced materials', 'Materials', .17, .55),
    ('Utilities', 'Utility enterprises', 'Power and water utilities', 'Utilities', .25, .65),
)
NAME_A = ('Alder', 'Amber', 'Ash', 'Aspen', 'Birch', 'Blue', 'Brook', 'Cedar', 'Clear', 'Copper',
          'Crest', 'Elm', 'Ever', 'Fair', 'Field', 'Fox', 'Glen', 'Gold', 'Granite', 'Green',
          'Harbor', 'Haven', 'High', 'Iron', 'Lake', 'Maple', 'Meadow', 'North', 'Oak', 'Pine',
          'Red', 'Ridge', 'River', 'Silver', 'Stone', 'Summit', 'West', 'Willow', 'Wind', 'Wood')
NAME_B = ('bank', 'bay', 'bridge', 'brook', 'crest', 'dale', 'field', 'ford', 'gate', 'grove',
          'haven', 'hill', 'lake', 'land', 'mark', 'mont', 'point', 'ridge', 'rock', 'shore',
          'stead', 'stone', 'vale', 'view', 'well', 'wick', 'wind', 'wood', 'worth', 'water')
FUNCTIONS = ('Engineering', 'Finance', 'Operations', 'Sales', 'Marketing', 'Human Resources',
             'Information Technology', 'Data Analytics', 'Procurement', 'Customer Success', 'Legal')


class Sampler:
    def __init__(self, values, weights):
        self.values = tuple(values)
        self.cumulative = []
        total = 0.0
        for weight in weights:
            total += weight
            self.cumulative.append(total)
        self.total = total

    def draw(self, rng):
        return self.values[bisect.bisect(self.cumulative, rng.random() * self.total)]


def tenure_sampler():
    """An exponentially tilted gamma-like discrete distribution with mean 48 months."""
    base = [m * math.exp(-m / 24) for m in TENURE_MONTHS]
    lo, hi = -.2, .2
    for _ in range(80):
        tilt = (lo + hi) / 2
        weights = [w * math.exp(tilt * m) for m, w in zip(TENURE_MONTHS, base)]
        mean = sum(m * w for m, w in zip(TENURE_MONTHS, weights)) / sum(weights)
        if mean < 48:
            lo = tilt
        else:
            hi = tilt
    return Sampler(TENURE_MONTHS, weights)


def months_before(value, months):
    year, month = divmod(value.year * 12 + value.month - 1 - months, 12)
    return date(year, month + 1, min(value.day, 28))


def person_id(index):
    return f'CORP_P{index:09d}'


def company_id(index):
    return f'CORP_C{index:06d}'


def role_id(index):
    return f'CORP_R{index:010d}'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_output(path):
    path = Path(path).resolve()
    for protected in (ROOT / 'csv', ROOT / 'golden', ROOT / 'scale_10k', ROOT / 'scale_sparse_seed_10k', ROOT / 'scale_connected_10k'):
        if path == protected or protected in path.parents or path in protected.parents:
            raise ValueError('Refusing a protected demo or regression-fixture path')
    if path.exists():
        raise FileExistsError(f'Output already exists: {path}')
    return path


def write_corporate(out, people=1_000_000, companies=1_000, seed=42):
    if type(people) is not int or type(companies) is not int or not 6 <= companies <= 1_000:
        raise ValueError('companies must be an integer between 6 and 1000')
    if not 2 * companies <= people <= 10_000_000:
        raise ValueError('people must be between twice the company count and 10 million')
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    out = check_output(out)
    rng = random.Random(seed)
    names_rng = random.Random(f'corporate-names:{seed}')
    employers = Sampler(range(1, 7), EMPLOYER_WEIGHTS)
    tenure = tenure_sampler()
    gaps = Sampler((0, 30, 60, 90, 180, 270, 365), (60, 12, 10, 8, 5, 3, 2))
    state_codes = tuple(STATES)
    headquarters = Sampler(state_codes, [STATE_WEIGHT[k] for k in state_codes])
    company_rows, weights, sectors = [], [], []
    names = [(a + b) for a in NAME_A for b in NAME_B]
    rng.shuffle(names)
    for index in range(companies):
        sector = index % len(INDUSTRIES)
        sectors.append(sector)
        profile = INDUSTRIES[sector]
        headcount = int(max(5_000, min(500_000, rng.lognormvariate(10.6, .9))))
        weights.append(max(.25, min(6., headcount / 50_000)))
        revenue = headcount * profile[5] * rng.uniform(.65, 1.6)
        company_rows.append({
            'company_id': company_id(index + 1), 'name': f'{names[index]} {profile[3]} (Synthetic)',
            'sector_id': f'CORP_SC{sector + 1:02d}N', 'hq_region_id': 'US-' + headquarters.draw(rng),
            'revenue_musd': f'{revenue:.2f}', 'ebitda_musd': f'{revenue * rng.uniform(profile[4] * .7, profile[4] * 1.3):.2f}',
            'employees': headcount, 'founded_year': 1950 if index < 6 else rng.randint(1900, 2010),
            'is_public': 'true' if rng.random() < .80 else 'false',
        })
    company_sampler = Sampler(range(companies), weights)
    by_sector = {}
    for sector in set(sectors):
        indices = [i for i, value in enumerate(sectors) if value == sector]
        by_sector[sector] = Sampler(indices, [weights[i] for i in indices])
    current_people = Counter()
    counts = Counter()
    out.mkdir(parents=True)
    with ExitStack() as stack:
        writers = {}
        for table, (_, columns) in TABLES.items():
            fh = stack.enter_context((out / f'{table}.csv').open('w', newline='', buffering=1024 * 1024))
            writer = csv.DictWriter(fh, fieldnames=columns, lineterminator='\n')
            writer.writeheader()
            writers[table] = writer

        def emit(table, row):
            writers[table].writerow(row)
            counts[table] += 1

        emit('REGION', dict(region_id='US', name='United States', level=1, region_type='country', parent_id=''))
        for region in ('NORTHEAST', 'MIDWEST', 'SOUTH', 'WEST'):
            emit('REGION', dict(region_id='US-' + region, name=region.title(), level=2, region_type='census_region', parent_id='US'))
        for code, (name, region) in STATES.items():
            emit('REGION', dict(region_id='US-' + code, name=name, level=3, region_type='state', parent_id='US-' + region))
        for index, profile in enumerate(INDUSTRIES, 1):
            for level, suffix, parent in ((1, '', ''), (2, 'S', f'CORP_SC{index:02d}'), (3, 'N', f'CORP_SC{index:02d}S')):
                emit('SECTOR', dict(sector_id=f'CORP_SC{index:02d}' + suffix, name=profile[level - 1], level=level, parent_id=parent))

        next_role = 0
        for index in range(people):
            pid = person_id(index + 1)
            first, last = names_rng.choice(FIRST), names_rng.choice(LAST)
            if names_rng.random() < .12:
                last += '-' + names_rng.choice(LAST)
            full = f'{first} {names_rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}. {last}'
            emit('PERSON', dict(person_id=pid, first_name=first, last_name=last, full_name=full))
            executive = index < 2 * companies
            current_company = index % companies if executive else company_sampler.draw(rng)
            count = rng.choice((3, 4, 5, 6)) if executive else employers.draw(rng)
            # Work backwards from the current job, then write in chronological order.
            while True:
                intervals = []
                end = AS_OF
                for job in range(count):
                    start = months_before(end, tenure.draw(rng)) - timedelta(days=rng.randrange(28))
                    intervals.append((start, end))
                    end = start - timedelta(days=gaps.draw(rng))
                career_days = (AS_OF - intervals[-1][0]).days
                if career_days <= 42 * 365.25 and (not executive or career_days >= 15 * 365.25):
                    break
            used = {current_company}
            assignments = [current_company]
            for start, _ in intervals[1:]:
                same_sector = rng.random() < .70
                preferred = by_sector[sectors[current_company]] if same_sector else company_sampler
                selected = None
                for attempt in range(100):
                    candidate = (preferred if attempt < 15 else company_sampler).draw(rng)
                    if candidate not in used and company_rows[candidate]['founded_year'] <= start.year:
                        selected = candidate
                        break
                if selected is None:
                    eligible = [i for i, row in enumerate(company_rows) if i not in used and row['founded_year'] <= start.year]
                    selected = rng.choice(eligible)
                used.add(selected)
                assignments.append(selected)
            function = rng.choice(FUNCTIONS)
            career_start = intervals[-1][0]
            for job, ((start, end), employer) in enumerate(reversed(list(zip(intervals, assignments)))):
                years = (start - career_start).days / 365.25
                prefix = 'Associate' if years < 3 else 'Senior' if years < 7 else 'Manager,' if years < 12 else 'Director,' if years < 20 else 'Vice President,'
                title = f'{prefix} {function}'
                if executive and job == count - 1:
                    title = 'Chief Executive Officer' if index < companies else 'Chief Financial Officer'
                next_role += 1
                emit('ROLE_HISTORY', dict(
                    role_id=role_id(next_role), person_id=pid, org_id=company_id(employer + 1), org_type='company',
                    role_type='CEO' if title == 'Chief Executive Officer' else 'CFO' if title == 'Chief Financial Officer' else 'Employee',
                    title=title, start_date=start.isoformat(), end_date='' if job == count - 1 else end.isoformat(), is_founder='false',
                ))
            current_people[current_company] += 1
            if (index + 1) % 100_000 == 0:
                print(f'Generated {index + 1:,} people and {next_role:,} employment records', flush=True)
        for index, row in enumerate(company_rows):
            if current_people[index] > row['employees']:
                raise ValueError('Tracked employees exceed simulated enterprise headcount')
            emit('COMPANY', row)
            sites = {row['hq_region_id']}
            for code in rng.sample(state_codes, rng.randint(2, 10)):
                sites.add('US-' + code)
            for region in sorted(sites):
                emit('COMPANY_SITE', dict(company_id=row['company_id'], region_id=region))

    manifest = {
        'mode': 'corporate-careers', 'format_version': 1, 'as_of_date': AS_OF.isoformat(), 'random_seed': seed,
        'people': people, 'companies': companies, 'roles': counts['ROLE_HISTORY'],
        'employer_count_weights': dict(zip(range(1, 7), EMPLOYER_WEIGHTS)), 'target_mean_tenure_years': 4.0,
        'assumptions': [
            'Fictional large US corporations; not actual Fortune companies or an empirically fitted Fortune dataset.',
            'One current employer and 1–6 distinct company employers per person; career length at most 42 years.',
            'Mean tenure is observed employment duration; current jobs are measured through the as-of date, not their eventual end.',
            'Industry-biased career moves, uneven employer sizes, non-overlapping jobs and optional gaps.',
            'Company employee counts are simulated full enterprise headcounts; tracked people are a sample.',
            'Each company has one designated current CEO and CFO, each with at least 15 years of career history.',
            'PE sponsors, funds, deals, CRM, pipeline and commercial-link tables are intentionally empty.',
            'No graph edges are generated. RAI remains responsible for graph calculation.',
        ],
        'tables': {},
    }
    for table in TABLES:
        path = out / f'{table}.csv'
        manifest['tables'][table] = {'rows': counts[table], 'sha256': sha256(path), 'bytes': path.stat().st_size}
    manifest['total_rows'] = sum(counts.values())
    manifest['csv_bytes'] = sum(t['bytes'] for t in manifest['tables'].values())
    (out / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


def check_corporate(out):
    """Validate the actual written CSVs independently of generation-time counters."""
    out = Path(out)
    manifest = json.loads((out / 'MANIFEST.json').read_text())
    if manifest.get('mode') != 'corporate-careers':
        raise ValueError('Not a corporate-careers manifest')
    as_of = date.fromisoformat(manifest['as_of_date'])

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(set(manifest['tables']) == set(TABLES), 'Manifest table inventory differs')
    for table, (_, columns) in TABLES.items():
        path = out / f'{table}.csv'
        require(sha256(path) == manifest['tables'][table]['sha256'], f'{table}: sha256 differs')
        with path.open(newline='') as fh:
            require(next(csv.reader(fh)) == columns, f'{table}: header differs')

    def small_table(name):
        with (out / f'{name}.csv').open(newline='') as fh:
            rows = list(csv.DictReader(fh))
        require(len(rows) == manifest['tables'][name]['rows'], f'{name}: row count differs')
        pk, _ = TABLES[name]
        keys = [tuple(row[k] for k in pk) for row in rows]
        require(all(all(k) for k in keys) and len(keys) == len(set(keys)), f'{name}: invalid primary keys')
        return rows

    sector_rows, region_rows, company_rows = (small_table(t) for t in ('SECTOR', 'REGION', 'COMPANY'))
    sector = {r['sector_id']: r for r in sector_rows}
    region = {r['region_id']: r for r in region_rows}
    companies = {r['company_id']: r for r in company_rows}
    require(len(companies) == manifest['companies'], 'Company population differs')
    require(len({r['name'] for r in company_rows}) == len(companies), 'Company names duplicate')
    for rows, key, lookup in ((sector_rows, 'sector_id', sector), (region_rows, 'region_id', region)):
        for row in rows:
            require(not row['parent_id'] or row['parent_id'] in lookup, f'{key}: invalid parent')
    for row in company_rows:
        require(row['sector_id'] in sector and int(sector[row['sector_id']]['level']) == 3, 'Invalid company sector')
        require(row['hq_region_id'] in region, 'Invalid company headquarters')
        require(0 < float(row['ebitda_musd']) < float(row['revenue_musd']), 'Invalid company financials')
        require(int(row['employees']) >= 5000 and int(row['founded_year']) <= as_of.year, 'Invalid corporate profile')
        require(row['is_public'] in ('true', 'false'), 'Invalid public/private flag')
    sites = small_table('COMPANY_SITE')
    site_pairs = {(r['company_id'], r['region_id']) for r in sites}
    require(all(c in companies and r in region for c, r in site_pairs), 'Invalid company site reference')
    require(all((r['company_id'], r['hq_region_id']) in site_pairs for r in company_rows), 'Missing HQ site')
    for table in TABLES:
        if table not in ('SECTOR', 'REGION', 'COMPANY', 'COMPANY_SITE', 'PERSON', 'ROLE_HISTORY'):
            require(not small_table(table), f'{table}: corporate employment fixture expects empty supporting table')
    people = 0
    with (out / 'PERSON.csv').open(newline='') as fh:
        for people, row in enumerate(csv.DictReader(fh), 1):
            require(row['person_id'] == person_id(people), 'PERSON: invalid/duplicate/order-mismatched ID')
            require(all(row[k].strip() for k in ('first_name', 'last_name', 'full_name')), 'PERSON: blank name')
    require(people == manifest['people'] == manifest['tables']['PERSON']['rows'], 'Person count differs')

    employer_hist, tenure_hist, career_hist = Counter(), Counter(), Counter()
    company_roles, company_current, ceos, cfos = Counter(), Counter(), Counter(), Counter()
    company_first, company_last = {}, {}
    previous_person = 0
    current_jobs = 0
    previous_end = None
    first_start = None
    seen_companies = set()
    total_tenure_days = 0
    completed_days = current_days = completed_count = current_count = 0
    roles = 0
    gap_days = 0
    executive_people = set()

    def finish_person():
        if previous_person:
            require(1 <= len(seen_companies) <= 6, 'Employer count outside 1–6')
            require(current_jobs == 1 and previous_end is None, 'Person must finish with exactly one current job')
            span = (as_of - first_start).days
            require(span <= 42 * 365.25, 'Career exceeds 42 years')
            if previous_person in executive_people:
                require(span >= 15 * 365.25, 'Executive career shorter than 15 years')
            employer_hist[len(seen_companies)] += 1
            career_hist[round(span / 365.25)] += 1

    with (out / 'ROLE_HISTORY.csv').open(newline='') as fh:
        for roles, row in enumerate(csv.DictReader(fh), 1):
            require(row['role_id'] == role_id(roles), 'ROLE_HISTORY: invalid/duplicate/order-mismatched ID')
            pid = row['person_id']
            require(pid.startswith('CORP_P') and pid[6:].isdigit(), 'Invalid person reference')
            index = int(pid[6:])
            require(1 <= index <= people and pid == person_id(index), 'Invalid person reference')
            if index != previous_person:
                finish_person()
                require(index == previous_person + 1, 'Missing person career or noncontiguous role records')
                previous_person = index
                seen_companies = set()
                current_jobs = 0
                previous_end = None
                first_start = None
            cid = row['org_id']
            require(row['org_type'] == 'company' and cid in companies, 'Invalid company reference')
            require(cid not in seen_companies, 'Repeated employer within a career')
            start = date.fromisoformat(row['start_date'])
            end = date.fromisoformat(row['end_date']) if row['end_date'] else as_of
            require(start < end <= as_of, 'Invalid employment date interval')
            require(start.year >= int(companies[cid]['founded_year']), 'Employment predates company founding')
            if seen_companies:
                require(previous_end is not None and start >= previous_end, 'Overlapping jobs or current job before final job')
                gap_days += (start - previous_end).days
            else:
                first_start = start
            require(row['role_type'] in ('Employee', 'CEO', 'CFO') and row['title'], 'Invalid role type/title')
            require(row['is_founder'] == 'false', 'Unexpected founder flag')
            days = (end - start).days
            total_tenure_days += days
            tenure_hist[days] += 1
            company_roles[cid] += 1
            company_first[cid] = min(company_first.get(cid, start), start)
            company_last[cid] = max(company_last.get(cid, end), end)
            seen_companies.add(cid)
            if not row['end_date']:
                current_jobs += 1
                company_current[cid] += 1
                current_count += 1
                current_days += days
                if row['role_type'] in ('CEO', 'CFO'):
                    (ceos if row['role_type'] == 'CEO' else cfos)[cid] += 1
                    executive_people.add(index)
            else:
                completed_days += days
                completed_count += 1
            previous_end = end if row['end_date'] else None
    finish_person()
    require(previous_person == people, 'Some people have no employment records')
    require(roles == manifest['roles'] == manifest['tables']['ROLE_HISTORY']['rows'], 'Role count differs')
    require(set(company_roles) == set(companies), 'Companies without employment records')
    require(all(ceos[c] == cfos[c] == 1 for c in companies), 'Companies must have one current CEO and CFO')
    require(all(0 < company_current[c] <= int(companies[c]['employees']) for c in companies), 'Current employee count outside company capacity')
    mean_tenure = total_tenure_days / roles / 365.25
    tolerance = max(.10, 8 / math.sqrt(roles))
    require(abs(mean_tenure - 4) <= tolerance, f'Mean observed tenure {mean_tenure:.4f} outside four-year tolerance {tolerance:.4f}')

    def quantile(histogram, q):
        rank = max(1, math.ceil(sum(histogram.values()) * q))
        cumulative = 0
        for value, count in sorted(histogram.items()):
            cumulative += count
            if cumulative >= rank:
                return value

    pairs = sum(n * (n - 1) // 2 for n in company_roles.values())
    report = {
        'status': 'PASS', 'validation_scope': 'All 17 CSVs: hashes, headers, counts, identifiers, references, career dates and population constraints.',
        'as_of_date': as_of.isoformat(), 'people': people, 'companies': len(companies), 'roles': roles,
        'employers_per_person': {'min': min(employer_hist), 'max': max(employer_hist), 'mean': round(roles / people, 6), 'distribution': dict(sorted(employer_hist.items()))},
        'tenure_years': {'mean_observed': round(mean_tenure, 6), 'mean_completed': round(completed_days / completed_count / 365.25, 6) if completed_count else None,
                         'mean_current_elapsed': round(current_days / current_count / 365.25, 6),
                         'p10': round(quantile(tenure_hist, .1) / 365.25, 3), 'median': round(quantile(tenure_hist, .5) / 365.25, 3),
                         'p90': round(quantile(tenure_hist, .9) / 365.25, 3), 'acceptance_tolerance': round(tolerance, 6)},
        'career_span_years': {'median_rounded': quantile(career_hist, .5), 'max_rounded': max(career_hist)},
        'current_roles': current_count, 'completed_roles': completed_count, 'current_ceos': sum(ceos.values()), 'current_cfos': sum(cfos.values()),
        'mean_gap_days_between_jobs': round(gap_days / completed_count, 3) if completed_count else 0,
        'company_employment': {'all_companies_have_current_people': True,
            'tracked_current_min': min(company_current.values()), 'tracked_current_max': max(company_current.values()),
            'tracked_current_mean': round(people / len(companies), 2),
            'all_time_roles_min': min(company_roles.values()), 'all_time_roles_max': max(company_roles.values())},
        'industry_groups': len({r['sector_id'] for r in company_rows}), 'hq_states': len({r['hq_region_id'] for r in company_rows}),
        'public_companies': sum(r['is_public'] == 'true' for r in company_rows), 'company_site_rows': len(sites),
        'rai_workload': {'same_employer_candidate_role_pairs': pairs,
            'meaning': 'Sum of n*(n-1)/2 per company, before the existing RAI K1 date-overlap filter. Not a count of unique person edges.',
            'assessment': 'REVIEW_BEFORE_RAI_LOAD: large employers imply dense co-employment ties; consider team/site evidence before treating overlapping employment as acquaintance.'},
        'graph_calculations_run': False, 'snowflake_modified': False,
        'csv_bytes': sum((out / f'{t}.csv').stat().st_size for t in TABLES),
        'tables': {t: manifest['tables'][t]['rows'] for t in TABLES},
    }
    (out / 'VALIDATION.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def corporate_main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--corporate', action='store_true')
    mode.add_argument('--corporate-check', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--people', type=int, default=1_000_000)
    parser.add_argument('--companies', type=int, default=1_000)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args(argv)
    if args.corporate:
        manifest = write_corporate(args.out, args.people, args.companies, args.seed)
        print(json.dumps({k: manifest[k] for k in ('people', 'companies', 'roles', 'csv_bytes')}, indent=2))
    else:
        print(json.dumps(check_corporate(args.out), indent=2))
