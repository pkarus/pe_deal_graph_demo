"""Independent small-data score oracle for validation only; not deployed."""
from datetime import date,timedelta

SNAPSHOT=date(2026,10,1)

def union_days(intervals):
    total=0;end=date(1900,1,1)
    for lo,hi in sorted(intervals):
        total+=max(0,(hi-max(lo,end)).days);end=max(end,hi)
    return total


def score_pair(left,right,work,friends,as_of=SNAPSHOT):
    def d(v):return date.fromisoformat(v[:10]) if isinstance(v,str) else v
    def jobs(person):return [{**r,'lo':d(r['START_DATE']),'hi':min(d(r['END_DATE']) if r['END_DATE'] else as_of,as_of)}
      for r in work if r['PERSON_ID']==person and d(r['START_DATE'])<as_of]
    a,b=jobs(left),jobs(right)
    career_a=union_days([(r['lo'],r['hi']) for r in a])/365.25
    career_b=union_days([(r['lo'],r['hi']) for r in b])/365.25
    overlaps=[]
    for x in a:
        for y in b:
            lo=max(x['lo'],y['lo']);hi=min(x['hi'],y['hi'])
            if x['ORG_ID']!=y['ORG_ID'] or x['ORG_ID']=='PE_FIRM_NORTHWIND' or (hi-lo).days<365:continue
            spatial=.25
            if x['WORK_MODE']==y['WORK_MODE']=='ONSITE':
                spatial=1. if x['OFFICE_ID'] and x['OFFICE_ID']==y['OFFICE_ID'] else .6 if x['CITY_ID'] and x['CITY_ID']==y['CITY_ID'] else .25
            overlaps.append((lo,hi,spatial))
    cutoffs=[date(as_of.year-n,as_of.month,min(as_of.day,28) if as_of.month==2 and as_of.day==29 else as_of.day) for n in [2,5,10,15]]
    points=sorted({p for lo,hi,_ in overlaps for p in [lo,hi]}|set(cutoffs))
    raw=effective=0.
    for lo,hi in zip(points,points[1:]):
        spatial=max([s for start,end,s in overlaps if start<=lo and end>=hi],default=0.)
        if not spatial:continue
        factor=1. if lo>=cutoffs[0] else .8 if lo>=cutoffs[1] else .5 if lo>=cutoffs[2] else .25 if lo>=cutoffs[3] else .1
        raw+=(hi-lo).days;effective+=(hi-lo).days*spatial*factor
    raw/=365.25;effective/=365.25
    career_mean=(career_a+career_b)/2
    fraction=min(1.,effective/career_mean) if career_mean else 0.
    duration=min(effective/10,1)**2
    friend=0. # Deferred: no score and no friendship-created edges.
    temporal=.5*fraction+.5*duration
    return {'left_career_years':career_a,'right_career_years':career_b,'career_mean_years':career_mean,
      'raw_years':raw,'effective_years':effective,'career_fraction':fraction,'duration_component':duration,
      'time_score':temporal,'friendship_score':friend,'employment_contribution':temporal,
      'friendship_contribution':.25*friend,'raw_strength':temporal,'strength':temporal**.25}


def fixture():
    import pandas as pd
    people=[];work=[];friends=[];cases={}
    def pair(name,career_start,shared_start,shared_end=None,location='same',friend=False,concurrent=False):
        base=len(people)+1;ids=[f'CORP_P{i:09d}' for i in [base,base+1]]
        for i,pid in enumerate(ids):
            people.append({'PERSON_ID':pid,'FULL_NAME':name+' '+str(i)})
            periods=[(f'SOLO_{pid}',date(career_start,10,1),date(shared_start,10,1)),
                     ('SHARED_'+name,date(shared_start,10,1),date(shared_end,10,1) if shared_end else None)]
            if shared_end:periods.append((f'AFTER_{pid}',date(shared_end,10,1),None))
            if concurrent:periods.append(('SHARED_'+name,date(shared_start+1,10,1),date(shared_end-1,10,1) if shared_end else None))
            for j,(org,lo,hi) in enumerate(periods):
                if hi==lo:continue
                office=org+'_OFFICE_1';city=org+'_CITY_1';mode='ONSITE'
                if i==1 and location in ['city','different']:office=org+'_OFFICE_2'
                if i==1 and location=='different':city=org+'_CITY_2'
                if location in ['remote','unknown']:office=city=None;mode='REMOTE' if location=='remote' else 'ONSITE'
                work.append({'ROLE_ID':pid+'_'+str(j),'PERSON_ID':pid,'ORG_ID':org,'START_DATE':lo,'END_DATE':hi,
                  'OFFICE_ID':office,'CITY_ID':city,'WORK_MODE':mode})
        if friend:friends.append({'P1':ids[0],'P2':ids[1],'STATUS':'CONFIRMED','CONFIRMED_ON':date(2025,1,1),'SOURCE':'synthetic fixture'})
        cases[name]=ids
    pair('long40',1986,2016)
    pair('short5',2021,2024)
    pair('recent',2006,2021)
    pair('old',2006,2006,2011)
    pair('samecity',2006,2021,location='city')
    pair('differentcity',2006,2021,location='different')
    pair('remote',2006,2021,location='remote')
    pair('friend',2006,2021,friend=True)
    pair('concurrent',2006,2021,concurrent=True)
    pair('future',2006,2027)
    pair('unknown',2006,2021,location='unknown')
    # Explicit friend without a shared employer: zero score; must not create an edge.
    x,y=cases['future'];friends.append({'P1':x,'P2':y,'STATUS':'CONFIRMED','CONFIRMED_ON':date(2025,1,1),'SOURCE':'synthetic personal friendship'})
    companies=[{'COMPANY_ID':o,'NAME':o} for o in sorted({r['ORG_ID'] for r in work})]
    inputs={'work':pd.DataFrame(work),'friends':pd.DataFrame(friends),'people':pd.DataFrame(people),
      'team':pd.DataFrame(people[:2]),'company':pd.DataFrame(companies),'cohort':pd.DataFrame([{'PERSON_ID':p['PERSON_ID']} for p in people])}
    return inputs,cases,work,friends
