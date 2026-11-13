"""Execute the shared score model on the real RAI engine against controlled facts."""
import json,math
import pandas as pd
from pathlib import Path
from corporate_agent.scoring import ScoredNetwork,SOURCE
from pe_deal_graph.intro_rai import configuration
from tests.affinity_oracle import fixture,score_pair

inputs,cases,work,friends=fixture()
# Physical fixtures use exactly the production CDC path. This SDK's inline
# m.data loader drops whole rows containing NULL, including current jobs.
from scripts.person_path_proc import connect
with connect() as con:
    c=con.cursor()
    for name,df in list(inputs.items()):
        table=SOURCE+'.AFFINITY_FIXTURE_V4_'+name.upper()
        columns=list(df.columns)
        ddl=','.join(col+(' DATE' if col.endswith('_DATE') or col=='CONFIRMED_ON' else ' VARCHAR') for col in columns)
        c.execute(f'CREATE TABLE IF NOT EXISTS {table} ({ddl}) CHANGE_TRACKING=TRUE')
        c.execute(f'SELECT COUNT(*) FROM {table}')
        if c.fetchone()[0]==0:
            values=[tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False,name=None)]
            c.executemany(f"INSERT INTO {table} VALUES ({','.join(['%s']*len(columns))})",values)
        c.execute(f'GRANT SELECT ON TABLE {table} TO ROLE RAI_USER')
        inputs[name]=table
network=ScoredNetwork(mode='cohort',config=configuration(),inputs=inputs)
frame=network.edge_query().to_df()
records=json.loads(frame.to_json(orient='records',double_precision=15))
Path('artifacts/affinity_v4_fixture_actual.json').write_text(json.dumps(records,indent=2)+'\n')
print('Native fixture rows:',len(records),flush=True)
by_pair={(r['left_id'],r['right_id']):r for r in records}
for name,(a,b) in cases.items():
    expected=score_pair(a,b,work,friends)
    if expected['strength']==0:assert (a,b) not in by_pair;continue
    actual=by_pair[(a,b)]
    for key,val in expected.items():assert math.isclose(actual[key],val,abs_tol=1e-8),(name,key,actual[key],val)
    assert 0<=actual['strength']<=1
    assert math.isclose(actual['strength'],actual['employment_contribution']+actual['friendship_contribution'],abs_tol=1e-10)
def score(name):return by_pair[tuple(cases[name])]['strength']
assert score('long40')>score('short5')
assert score('recent')>score('old')
assert score('recent')>score('samecity')>score('differentcity')
assert math.isclose(score('friend'),score('recent'),abs_tol=1e-8)
assert math.isclose(score('concurrent'),score('recent'),abs_tol=1e-8)
assert tuple(cases['future']) not in by_pair
assert math.isclose(score('unknown'),score('differentcity'),abs_tol=1e-8)
sample=cases['friend']
filtered=json.loads(network.edge_query(sample).to_df().to_json(orient='records',double_precision=15))
assert len(filtered)==1 and filtered[0]['left_id']==sample[0],filtered
from corporate_agent.presentation import breakdowns,records as native_records
parts=breakdowns(records,native_records(network.period_query().to_df()),network.as_of)
for key,row in parts.items():
    assert math.isclose(sum(p['weighted_days'] for p in row['periods'])/365.25,row['effective_years'],abs_tol=1e-8),(key,row)
Path('artifacts/affinity_v4_native_fixture.json').write_text(json.dumps({'status':'PASS','rows':records,'cases':cases},indent=2)+'\n')
print('PASS',len(cases),'native RAI scoring scenarios',flush=True)
print({name:score(name) for name in cases if tuple(cases[name]) in by_pair},flush=True)
