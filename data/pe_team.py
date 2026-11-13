"""Separate deterministic synthetic PE employees and dated corporate careers."""
import csv
import json
import random
from datetime import date,timedelta
from pathlib import Path
from data.generate import FIRST,LAST

ROOT=Path(__file__).resolve().parents[1]
AS_OF=date(2026,10,1)
FIRM='PE_FIRM_NORTHWIND'


def generate():
    out=ROOT/'data/pe_team_100'
    out.mkdir(exist_ok=False)
    rng=random.Random(74129)
    companies=list(csv.DictReader((ROOT/'data/corporate_1m_1000_companies/COMPANY.csv').open()))
    people=[];roles=[];tenures=[]
    for i in range(1,101):
        person_id=f'PE_P{i:04d}'
        previous=3+(i%2)
        # Calibrated around four years, with actual dates and small employment gaps.
        durations=[int(rng.choices([2,3,4,5,6],[1,2,4,2,1])[0]*365.25)+rng.randint(-35,35)
                   for _ in range(previous+1)]
        end=AS_OF
        intervals=[]
        for j,days in enumerate(reversed(durations)):
            start=end-timedelta(days=days)
            intervals.append((start,end,days))
            end=start-timedelta(days=rng.randint(14,75))
        intervals.reverse()
        current_start=intervals[-1][0]
        title=['Investment Associate','Vice President','Principal','Operating Partner','Partner'][(i-1)%5]
        people.append({'PERSON_ID':person_id,'FULL_NAME':f'{FIRST[(i*7)%len(FIRST)]} {chr(65+(i%26))}. {LAST[(i*11)%len(LAST)]}',
                       'FIRM_ID':FIRM,'TITLE':title,'JOIN_DATE':str(current_start),'IS_SYNTHETIC':True})
        eligible=[c for c in companies if int(c['founded_year'])<=intervals[0][0].year]
        chosen=rng.sample(eligible,previous)
        for j,(start,end,days) in enumerate(intervals):
            current=j==previous
            roles.append({'ROLE_ID':f'PE_R{i:04d}_{j+1}','PERSON_ID':person_id,
                          'ORG_ID':FIRM if current else chosen[j]['company_id'],
                          'ORG_TYPE':'sponsor' if current else 'company','ROLE_TYPE':'Deal Team' if current else 'Employee',
                          'TITLE':title if current else ['Analyst, Finance','Senior Finance','Manager, Strategy','Director, Strategy'][j],
                          'START_DATE':str(start),'END_DATE':None if current else str(end),'IS_FOUNDER':False})
            tenures.append(days/365.25)
    mean=sum(tenures)/len(tenures)
    assert len(people)==100 and abs(mean-4)<.2,mean
    for name,rows in [('TEAM_MEMBER',people),('TEAM_ROLE_HISTORY',roles)]:
        with (out/f'{name}.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    report={'employees':100,'previous_employers_min':3,'previous_employers_max':4,
            'roles_including_current_pe':len(roles),'mean_tenure_years':mean,
            'prior_corporate_employers':len({r['ORG_ID'] for r in roles if r['ORG_ID']!=FIRM}),
            'as_of':str(AS_OF),'seed':74129,'current_firm':'Northwind Equity Partners (Synthetic)',
            'interpretation':'3–4 prior corporate employers plus current PE employment; separate from original corporate records'}
    (out/'MANIFEST.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':generate()
