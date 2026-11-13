"""Generate explicit synthetic office and friendship FACTS, never graph scores.

Original careers are unchanged. DuckDB is used only to generate/load facts;
all production relationship weights, paths and analytics are computed in RAI.
"""
from pathlib import Path
import argparse,hashlib,json
import duckdb

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/corporate_enrichment_v2'
AS_OF='2026-10-01'


def generate():
    OUT.mkdir(exist_ok=True)
    if (OUT/'MANIFEST.json').exists():raise RuntimeError('Versioned enrichment already exists')
    db=duckdb.connect(str(OUT/'generation.duckdb'))
    db.execute("SET memory_limit='3GB'")
    db.execute("SET threads=4")
    db.execute(f"CREATE TABLE roles AS SELECT * FROM read_csv('{ROOT}/data/corporate_1m_1000_companies/ROLE_HISTORY.csv',all_varchar=true) UNION ALL SELECT * FROM read_csv('{ROOT}/data/pe_team_100/TEAM_ROLE_HISTORY.csv',all_varchar=true)")
    db.execute(f"""CREATE TABLE sites AS SELECT company_id,region_id,
      ROW_NUMBER() OVER(PARTITION BY company_id ORDER BY region_id)-1 AS site
      FROM read_csv('{ROOT}/data/corporate_1m_1000_companies/COMPANY_SITE.csv',all_varchar=true)
      UNION ALL SELECT 'PE_FIRM_NORTHWIND','US-NY',0""")
    db.execute("""CREATE TABLE offices AS SELECT company_id||'_O'||(site*3+i)::VARCHAR OFFICE_ID,
      company_id COMPANY_ID,company_id||'_CITY_'||site::VARCHAR CITY_ID,
      region_id||' / synthetic city '||(site+1)::VARCHAR CITY_NAME,
      'Office '||(i+1)::VARCHAR||' (Synthetic)' OFFICE_NAME,TRUE IS_SYNTHETIC
      FROM sites CROSS JOIN range(3) AS t(i)""")
    db.execute("""CREATE TABLE workplaces AS WITH numbered AS (
      SELECT R.*, (hash(person_id,org_id,'workplace-74130') % C.n)::BIGINT AS office_no,
        hash(role_id,'remote-74130') % 10=0 AS remote
      FROM roles R JOIN (SELECT company_id,COUNT(*)*3 n FROM sites GROUP BY company_id) C
      ON R.org_id=C.company_id)
      SELECT role_id ROLE_ID,person_id PERSON_ID,org_id ORG_ID,
        start_date::DATE START_DATE,NULLIF(end_date,'')::DATE END_DATE,
        CASE WHEN remote THEN NULL ELSE org_id||'_O'||office_no::VARCHAR END OFFICE_ID,
        CASE WHEN remote THEN NULL ELSE org_id||'_CITY_'||(office_no//3)::VARCHAR END CITY_ID,
        CASE WHEN remote THEN 'REMOTE' ELSE 'ONSITE' END WORK_MODE,TRUE IS_SYNTHETIC
      FROM numbered""")
    # These are generated friendship assertions, not employment inference rules.
    db.execute("""CREATE TABLE friend_candidates AS
      WITH current_peers AS (
        SELECT PERSON_ID,START_DATE,
          LAG(PERSON_ID) OVER(PARTITION BY OFFICE_ID ORDER BY hash(PERSON_ID,'current-friend-74130')) PEER,
          LAG(START_DATE) OVER(PARTITION BY OFFICE_ID ORDER BY hash(PERSON_ID,'current-friend-74130')) PEER_START
        FROM workplaces WHERE END_DATE IS NULL AND WORK_MODE='ONSITE'),
      previous_jobs AS (
        SELECT * FROM workplaces WHERE END_DATE IS NOT NULL AND WORK_MODE='ONSITE'
        QUALIFY ROW_NUMBER() OVER(PARTITION BY PERSON_ID ORDER BY END_DATE DESC,ROLE_ID)=1),
      alumni_peers AS (
        SELECT PERSON_ID,END_DATE,
          LAG(PERSON_ID) OVER(PARTITION BY OFFICE_ID,YEAR(END_DATE)//4 ORDER BY hash(PERSON_ID,'alumni-friend-74130')) PEER,
          LAG(END_DATE) OVER(PARTITION BY OFFICE_ID,YEAR(END_DATE)//4 ORDER BY hash(PERSON_ID,'alumni-friend-74130')) PEER_END
        FROM previous_jobs),
      social_peers AS (
        SELECT PERSON_ID,LAG(PERSON_ID) OVER(ORDER BY hash(PERSON_ID,'social-friend-74130')) PEER
        FROM (SELECT DISTINCT PERSON_ID FROM workplaces) WHERE hash(PERSON_ID,'social-selection') % 4=0)
      SELECT PERSON_ID,PEER,GREATEST(START_DATE,PEER_START) CONFIRMED_ON,
        'synthetic current-office friendship' SOURCE FROM current_peers
      UNION ALL SELECT PERSON_ID,PEER,GREATEST(END_DATE,PEER_END),
        'synthetic alumni friendship' FROM alumni_peers
      UNION ALL SELECT PERSON_ID,PEER,DATE '2020-01-01'+(hash(PERSON_ID,PEER,'friend-date') % 2400)::INTEGER,
        'synthetic personal friendship' FROM social_peers""")
    db.execute("""CREATE TABLE friendships AS SELECT LEAST(PERSON_ID,PEER) P1,GREATEST(PERSON_ID,PEER) P2,
      'CONFIRMED' STATUS,CONFIRMED_ON,SOURCE,TRUE IS_SYNTHETIC FROM friend_candidates
      WHERE PEER IS NOT NULL AND PERSON_ID<>PEER
      QUALIFY ROW_NUMBER() OVER(PARTITION BY P1,P2 ORDER BY CONFIRMED_ON,SOURCE)=1""")
    assert db.execute('SELECT COUNT(*) FROM workplaces').fetchone()[0]==3371598+450
    assert db.execute('SELECT COUNT(*) FROM workplaces WHERE START_DATE>COALESCE(END_DATE,DATE \'2026-10-01\')').fetchone()[0]==0
    report={'version':'corporate-affinity-v2','seed':74130,'as_of':AS_OF,'synthetic':True,
      'generation_only':'Office assignments and explicit friendships; no generated connection scores or centrality',
      'duckdb_version':duckdb.__version__,'tables':{}}
    for name,table in [('OFFICE_V2','offices'),('WORKPLACE_V2','workplaces'),('FRIENDSHIP_V2','friendships')]:
        path=OUT/f'{name}.csv.gz'
        db.execute(f"COPY (SELECT * FROM {table} ORDER BY ALL) TO '{path}' (HEADER,COMPRESSION GZIP)")
        report['tables'][name]={'rows':db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],
          'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),'bytes':path.stat().st_size}
        print(name,report['tables'][name],flush=True)
    report['office_assignments_missing'] = db.execute("SELECT COUNT(*) FROM workplaces WHERE WORK_MODE='ONSITE' AND OFFICE_ID IS NULL").fetchone()[0]
    report['remote_roles']=db.execute("SELECT COUNT(*) FROM workplaces WHERE WORK_MODE='REMOTE'").fetchone()[0]
    report['friendships_involving_pe']=db.execute("SELECT COUNT(*) FROM friendships WHERE P1 LIKE 'PE_%' OR P2 LIKE 'PE_%'").fetchone()[0]
    db.close()
    (OUT/'MANIFEST.json').write_text(json.dumps(report,indent=2)+'\n')


def load():
    from scripts.person_path_proc import connect
    from corporate_agent.setup import SCHEMA,CORPORATE
    report=json.loads((OUT/'MANIFEST.json').read_text())
    definitions={
      'OFFICE_V2':'OFFICE_ID VARCHAR,COMPANY_ID VARCHAR,CITY_ID VARCHAR,CITY_NAME VARCHAR,OFFICE_NAME VARCHAR,IS_SYNTHETIC BOOLEAN',
      'WORKPLACE_V2':'ROLE_ID VARCHAR,PERSON_ID VARCHAR,ORG_ID VARCHAR,START_DATE DATE,END_DATE DATE,OFFICE_ID VARCHAR,CITY_ID VARCHAR,WORK_MODE VARCHAR,IS_SYNTHETIC BOOLEAN',
      'FRIENDSHIP_V2':'P1 VARCHAR,P2 VARCHAR,STATUS VARCHAR,CONFIRMED_ON DATE,SOURCE VARCHAR,IS_SYNTHETIC BOOLEAN'}
    with connect() as con:
        c=con.cursor()
        c.execute(f'CREATE STAGE IF NOT EXISTS {SCHEMA}.ENRICHMENT_V2_STAGE')
        for name,ddl in definitions.items():
            path=OUT/f'{name}.csv.gz'
            assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==report['tables'][name]['sha256']
            c.execute(f'CREATE TABLE {SCHEMA}.{name} ({ddl})')
            c.execute(f"PUT 'file://{path}' @{SCHEMA}.ENRICHMENT_V2_STAGE AUTO_COMPRESS=FALSE OVERWRITE=FALSE")
            c.execute(f'''COPY INTO {SCHEMA}.{name} FROM @{SCHEMA}.ENRICHMENT_V2_STAGE/{path.name}
              FILE_FORMAT=(TYPE=CSV COMPRESSION=GZIP PARSE_HEADER=TRUE FIELD_OPTIONALLY_ENCLOSED_BY='"' NULL_IF=(''))
              MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE ON_ERROR=ABORT_STATEMENT''')
            c.execute(f'SELECT COUNT(*) FROM {SCHEMA}.{name}');actual=c.fetchone()[0]
            assert actual==report['tables'][name]['rows'],(name,actual)
            c.execute(f'ALTER TABLE {SCHEMA}.{name} SET CHANGE_TRACKING=TRUE')
            c.execute(f'GRANT SELECT ON TABLE {SCHEMA}.{name} TO ROLE RAI_USER')
            print('Loaded',name,actual,flush=True)
        c.execute(f'''CREATE TABLE {SCHEMA}.LEADERSHIP_COHORT_V2 AS
          SELECT PERSON_ID,LISTAGG(DISTINCT KIND,', ') WITHIN GROUP(ORDER BY KIND) COHORT_ROLE FROM (
            SELECT PERSON_ID,'PE employee' KIND FROM {SCHEMA}.TEAM_MEMBER UNION ALL
            SELECT PERSON_ID,'CEO' FROM {CORPORATE}.ROLE_HISTORY WHERE END_DATE IS NULL AND ROLE_TYPE='CEO' UNION ALL
            SELECT PERSON_ID,'Synthetic Head of Data' FROM {SCHEMA}.HEAD_OF_DATA) GROUP BY PERSON_ID''')
        c.execute(f'ALTER TABLE {SCHEMA}.LEADERSHIP_COHORT_V2 SET CHANGE_TRACKING=TRUE')
        c.execute(f'GRANT SELECT ON TABLE {SCHEMA}.LEADERSHIP_COHORT_V2 TO ROLE RAI_USER')
        c.execute(f'SELECT COUNT(*) FROM {SCHEMA}.LEADERSHIP_COHORT_V2');report['leadership_cohort']=c.fetchone()[0]
        assert report['leadership_cohort']==2100,report['leadership_cohort']
        # Verify every employment field matches the original career record.
        c.execute(f'''SELECT COUNT(*) FROM {SCHEMA}.WORKPLACE_V2 W FULL OUTER JOIN {SCHEMA}.ROLE_HISTORY R
          ON W.ROLE_ID=R.ROLE_ID WHERE W.ROLE_ID IS NULL OR R.ROLE_ID IS NULL OR W.PERSON_ID<>R.PERSON_ID
          OR W.ORG_ID<>R.ORG_ID OR W.START_DATE<>R.START_DATE OR NOT EQUAL_NULL(W.END_DATE,R.END_DATE)''')
        assert c.fetchone()[0]==0
        report['career_fields_match_original']=True
    (ROOT/'artifacts/corporate_enrichment_v2_load.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['generate','load']);args=parser.parse_args()
    generate() if args.command=='generate' else load()
