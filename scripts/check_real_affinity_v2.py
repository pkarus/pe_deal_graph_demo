"""Independent validation of a real pair's native score and period decomposition."""
from scripts.person_path_proc import connect
from tests.affinity_oracle import score_pair
from corporate_agent.presentation import breakdowns
from corporate_agent.scoring import AS_OF,SOURCE
import json,math
edges=json.load(open('artifacts/affinity_pair_full.json'));periods=json.load(open('artifacts/affinity_pair_period.json'))
r=list(breakdowns(edges,periods,AS_OF).values())[0];ids=[r['left_id'],r['right_id']]
with connect() as con:
 c=con.cursor();c.execute(f'SELECT * FROM {SOURCE}.WORKPLACE_V2 WHERE PERSON_ID IN (%s,%s)',ids)
 work=[dict(zip([d[0] for d in c.description],v)) for v in c.fetchall()]
 c.execute(f'SELECT * FROM {SOURCE}.FRIENDSHIP_V2 WHERE P1=%s AND P2=%s',sorted(ids))
 friends=[dict(zip([d[0] for d in c.description],v)) for v in c.fetchall()]
e=score_pair(*ids,work,friends)
for k,v in e.items():assert math.isclose(r[k],v,abs_tol=1e-8),(k,r[k],v)
assert math.isclose(sum(p['weighted_days'] for p in r['periods'])/365.25,r['effective_years'],abs_tol=1e-8)
open('artifacts/affinity_v2_real_edge_validation.json','w').write(json.dumps({'status':'PASS','pair':ids,'all_components':e,'decomposition':r},indent=2))
print('PASS all real edge components and period totals',flush=True)
