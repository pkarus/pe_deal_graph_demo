"""Load the validated corporate fixture into a NEW isolated Snowflake schema.

Refuses an existing schema. Never replaces any source, deployment, or agent.
"""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.load import connect, parse_schema, csv_header, schema_cols
from pe_deal_graph import settings

SOURCE = settings.schema("CORPORATE_1M_SRC")
DATA = ROOT / "data/corporate_1m_1000_companies"


def main():
    manifest = json.loads((DATA / "MANIFEST.json").read_text())
    tables = parse_schema(ROOT / "data/schema.sql")
    for name, ddl in tables:
        path = DATA / f"{name}.csv"
        assert csv_header(path) == schema_cols(ddl), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["tables"][name]["sha256"], name
    report = {"source_schema": SOURCE, "tables": {}, "existing_data_changed": False}
    with connect() as con:
        cur = con.cursor()
        cur.execute(f"CREATE SCHEMA {SOURCE} COMMENT='Isolated synthetic corporate careers for local RAI graph explorer'")
        cur.execute(f"USE SCHEMA {SOURCE}")
        cur.execute("CREATE TEMPORARY STAGE CORPORATE_LOAD_STAGE")
        cur.execute("CREATE TEMPORARY FILE FORMAT CORPORATE_LOAD_CSV TYPE=CSV PARSE_HEADER=TRUE "
                    "FIELD_OPTIONALLY_ENCLOSED_BY='\"' NULL_IF=('') EMPTY_FIELD_AS_NULL=TRUE "
                    "ERROR_ON_COLUMN_COUNT_MISMATCH=TRUE")
        for name, ddl in tables:
            cur.execute(ddl.replace("CREATE OR REPLACE TABLE", "CREATE TABLE", 1))
            expected = manifest["tables"][name]["rows"]
            copy_rows = 0
            if expected:
                cur.execute(f"PUT 'file://{DATA / (name + '.csv')}' @CORPORATE_LOAD_STAGE/{name}/ AUTO_COMPRESS=TRUE")
                cur.execute(f"COPY INTO {name} FROM @CORPORATE_LOAD_STAGE/{name}/ "
                            "FILE_FORMAT=(FORMAT_NAME=CORPORATE_LOAD_CSV) "
                            "MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE ON_ERROR=ABORT_STATEMENT")
                copied = [dict(zip([x[0].lower() for x in cur.description], row)) for row in cur.fetchall()]
                assert all(row['status'] == 'LOADED' and row['errors_seen'] == 0 for row in copied), copied
                copy_rows = sum(row['rows_loaded'] for row in copied)
                assert copy_rows == expected, (name, copy_rows, expected)
            actual = cur.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            assert actual == expected, (name, actual, expected)
            cur.execute(f"ALTER TABLE {name} SET CHANGE_TRACKING=TRUE")
            report['tables'][name] = {"expected": expected, "actual": actual,
                                     "sha256": manifest['tables'][name]['sha256'], "copy_rows": copy_rows}
            print(name, actual, "PASS", flush=True)
        sql = """SELECT COUNT(*) PEOPLE,MIN(EMPLOYERS) MIN_EMPLOYERS,MAX(EMPLOYERS) MAX_EMPLOYERS,
                    AVG(EMPLOYERS) AVG_EMPLOYERS,SUM(CURRENT_JOBS) CURRENT_JOBS
                 FROM (SELECT PERSON_ID,COUNT(DISTINCT ORG_ID) EMPLOYERS,
                       COUNT_IF(END_DATE IS NULL) CURRENT_JOBS FROM ROLE_HISTORY GROUP BY PERSON_ID)"""
        cur.execute(sql)
        report['career_statistics'] = dict(zip([x[0] for x in cur.description], map(str,cur.fetchone())))
        report['mean_tenure_years'] = float(cur.execute(
            "SELECT AVG(DATEDIFF(day,START_DATE,COALESCE(END_DATE,'2026-10-01'::DATE)))/365.25 FROM ROLE_HISTORY"
        ).fetchone()[0])
    out = ROOT / "artifacts/corporate_explorer_snowflake_load_20261112.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print('Validated:', out, flush=True)


if __name__ == '__main__':
    main()
