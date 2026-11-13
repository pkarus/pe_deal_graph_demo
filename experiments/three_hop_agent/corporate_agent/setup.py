"""Create isolated PE team sources, lookup views and execution audit tables."""
from pathlib import Path
import csv,json
from scripts.person_path_proc import connect
from pe_deal_graph import settings

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=settings.schema('CORPORATE_AGENT')
CORPORATE=settings.schema('CORPORATE_1M_SRC')


def main():
    report={'schema':SCHEMA,'corporate_source':CORPORATE,'checks':{}}
    with connect() as con:
        c=con.cursor()
        c.execute(f"CREATE SCHEMA {SCHEMA} COMMENT='Corporate PE introductions: separate team facts, dynamic PyRel and agent audit'")
        c.execute(f'CREATE TABLE {SCHEMA}.TEAM_MEMBER (PERSON_ID VARCHAR PRIMARY KEY,FULL_NAME VARCHAR,FIRM_ID VARCHAR,TITLE VARCHAR,JOIN_DATE DATE,IS_SYNTHETIC BOOLEAN)')
        c.execute(f'CREATE TABLE {SCHEMA}.TEAM_ROLE_HISTORY (ROLE_ID VARCHAR PRIMARY KEY,PERSON_ID VARCHAR,ORG_ID VARCHAR,ORG_TYPE VARCHAR,ROLE_TYPE VARCHAR,TITLE VARCHAR,START_DATE DATE,END_DATE DATE,IS_FOUNDER BOOLEAN)')
        for name in ['TEAM_MEMBER','TEAM_ROLE_HISTORY']:
            with (ROOT/f'data/pe_team_100/{name}.csv').open() as f:
                rows=list(csv.DictReader(f))
            cols=list(rows[0]);values=[tuple(None if row[k]=='' else row[k] for k in cols) for row in rows]
            c.executemany(f'INSERT INTO {SCHEMA}.{name} ({",".join(cols)}) VALUES ({",".join(["%s"]*len(cols))})',values)
            c.execute(f'ALTER TABLE {SCHEMA}.{name} SET CHANGE_TRACKING=TRUE')
        c.execute(f'''CREATE VIEW {SCHEMA}.PERSON AS SELECT PERSON_ID,FULL_NAME FROM {CORPORATE}.PERSON
                      UNION ALL SELECT PERSON_ID,FULL_NAME FROM {SCHEMA}.TEAM_MEMBER''')
        c.execute(f'CREATE TABLE {SCHEMA}.PE_FIRM (COMPANY_ID VARCHAR,NAME VARCHAR)')
        c.execute(f"INSERT INTO {SCHEMA}.PE_FIRM VALUES ('PE_FIRM_NORTHWIND','Northwind Equity Partners (Synthetic)')")
        c.execute(f'ALTER TABLE {SCHEMA}.PE_FIRM SET CHANGE_TRACKING=TRUE')
        c.execute(f'''CREATE VIEW {SCHEMA}.COMPANY AS SELECT COMPANY_ID,NAME FROM {CORPORATE}.COMPANY
                      UNION ALL SELECT COMPANY_ID,NAME FROM {SCHEMA}.PE_FIRM''')
        c.execute(f'''CREATE VIEW {SCHEMA}.ROLE_HISTORY AS SELECT * FROM {CORPORATE}.ROLE_HISTORY
                      UNION ALL SELECT * FROM {SCHEMA}.TEAM_ROLE_HISTORY''')
        for name in ['PERSON','ROLE_HISTORY','COMPANY']:
            c.execute(f'ALTER VIEW {SCHEMA}.{name} SET CHANGE_TRACKING=TRUE')
        c.execute(f'''CREATE TABLE {SCHEMA}.HEAD_OF_DATA AS
          SELECT ORG_ID COMPANY_ID,PERSON_ID,'Head of Data' DESIGNATION,TITLE SOURCE_TITLE,
          'Synthetic designation: highest current Data Analytics title; longest current tenure, then person ID breaks ties' BASIS,
          TRUE IS_SYNTHETIC
          FROM {CORPORATE}.ROLE_HISTORY WHERE END_DATE IS NULL AND TITLE ILIKE '%Data Analytics%'
          QUALIFY ROW_NUMBER() OVER(PARTITION BY ORG_ID ORDER BY
            CASE WHEN TITLE ILIKE 'Vice President%' THEN 1 WHEN TITLE ILIKE 'Director%' THEN 2
                 WHEN TITLE ILIKE 'Manager%' THEN 3 WHEN TITLE ILIKE 'Senior%' THEN 4 ELSE 5 END,
            START_DATE,PERSON_ID)=1''')
        c.execute(f'''CREATE TABLE {SCHEMA}.QUERY_AUDIT(
          REQUEST_ID VARCHAR,PYREL_CODE VARCHAR,PYREL_SHA256 VARCHAR,TARGET_ID VARCHAR,SOURCE_ID VARCHAR,
          STARTED_AT TIMESTAMP_TZ,COMPLETED_AT TIMESTAMP_TZ,STATUS VARCHAR,
          RAI_TRANSACTION_IDS VARIANT,SNOWFLAKE_QUERY_IDS VARIANT,RESULT VARIANT,ENGINE_STATE VARIANT,ERROR VARCHAR)''')
        c.execute(f'CREATE STAGE {SCHEMA}.RUNTIME')
        checks={
          'team_count':f'SELECT COUNT(*) FROM {SCHEMA}.TEAM_MEMBER',
          'team_roles':f'SELECT COUNT(*) FROM {SCHEMA}.TEAM_ROLE_HISTORY',
          'head_designations':f'SELECT COUNT(*) FROM {SCHEMA}.HEAD_OF_DATA',
          'orphan_employers':f"SELECT COUNT(*) FROM {SCHEMA}.TEAM_ROLE_HISTORY R LEFT JOIN {SCHEMA}.COMPANY C ON C.COMPANY_ID=R.ORG_ID WHERE C.COMPANY_ID IS NULL",
          'mean_tenure_years':f"SELECT AVG(DATEDIFF(day,START_DATE,COALESCE(END_DATE,'2026-10-01'::DATE)))/365.25 FROM {SCHEMA}.TEAM_ROLE_HISTORY",
          'team_with_external_overlap':f'''SELECT COUNT(DISTINCT T.PERSON_ID) FROM {SCHEMA}.TEAM_ROLE_HISTORY T
            JOIN {CORPORATE}.ROLE_HISTORY C ON C.ORG_ID=T.ORG_ID
            WHERE DATEDIFF(day,GREATEST(T.START_DATE,C.START_DATE),LEAST(COALESCE(T.END_DATE,'2026-10-01'::DATE),COALESCE(C.END_DATE,'2026-10-01'::DATE)))>=365''',
          'career_overlaps':f'''SELECT COUNT(*) FROM {SCHEMA}.TEAM_ROLE_HISTORY A JOIN {SCHEMA}.TEAM_ROLE_HISTORY B
            ON A.PERSON_ID=B.PERSON_ID AND A.START_DATE<B.START_DATE WHERE A.END_DATE>B.START_DATE'''
        }
        for key,sql in checks.items():
            c.execute(sql);report['checks'][key]=float(c.fetchone()[0]);print(key,report['checks'][key],flush=True)
        assert report['checks']['team_count']==100 and report['checks']['team_with_external_overlap']==100
        assert report['checks']['career_overlaps']==0 and report['checks']['orphan_employers']==0
        assert abs(report['checks']['mean_tenure_years']-4)<.2
    (ROOT/'artifacts/corporate_pe_team_validation.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
