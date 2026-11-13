import json
from pathlib import Path
from scripts.person_path_proc import connect
from corporate_agent.scoring import SOURCE,CORPORATE
with connect() as con:
 c=con.cursor();c.execute(f'SELECT COUNT(*) FROM {CORPORATE}.ROLE_HISTORY');careers=c.fetchone()[0];assert careers==3371598
 expected={'TEAM_MEMBER':100,'TEAM_ROLE_HISTORY':450,'WORKPLACE_V2':3372048,'OFFICE_V2':20898,'FRIENDSHIP_V2':1910282,'LEADERSHIP_COHORT_V2':2100}
 for table,count in expected.items():
  c.execute(f'SELECT COUNT(*) FROM {SOURCE}.{table}');assert c.fetchone()[0]==count
 c.execute("SHOW AGENTS LIKE 'PE_INTRO_1M_TEST' IN SCHEMA ALAA_RELAPP_PERSISTENCE.PE_DEAL_GRAPH_EXPERIMENT_CONNECTED_1M_INTRO_TEST")
 row=dict(zip([d[0].lower() for d in c.description],c.fetchone()))
 prior=json.loads(Path('artifacts/corporate_affinity_v2_preservation.json').read_text());assert str(row['created_on'])==prior['older_agent_created_on']
 c.execute(f'SELECT SCORING_VERSION,COUNT(*) FROM {SOURCE}.NETWORK_RUNS_V2 GROUP BY 1');versions=dict(c.fetchall());assert versions.get('corporate-affinity-v2') and versions.get('corporate-affinity-v4') and versions.get('corporate-affinity-v5')
 report={'status':'PASS','original_career_rows':careers,'preserved_tables':expected,'older_agent':row['name'],'older_agent_created_on':str(row['created_on']),'retained_analytics_versions':versions,'active_version':'corporate-affinity-v5'}
 Path('artifacts/corporate_affinity_v5_preservation.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS: source facts, older agent, and prior native snapshots preserved',flush=True)
