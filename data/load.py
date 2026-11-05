#!/usr/bin/env python
"""R07 loader: create tables from data/schema.sql and load data/csv/*.csv into RAI_DEMO_PE_DEALS.DEAL_GRAPH.

Generic: parses schema.sql, loads every table that has a CSV, verifies counts against
data/csv/MANIFEST.json (or CSV line counts). Idempotent (CREATE OR REPLACE, then COPY).
Credentials come from raiconfig.yaml (connection pe_demo); the PAT is read at runtime, never printed.
"""
import csv, json, re, sys
from pathlib import Path

import snowflake.connector
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pe_deal_graph import settings as _cfg  # noqa: E402  (database/schema/role/engine names)
DATA = ROOT / "data"
CSV_DIR = DATA / "csv"
DB, SCHEMA = _cfg.DATABASE, _cfg.BASE_SCHEMA  # from raiconfig.yaml / pe_settings.yaml (default RAI_DEMO_PE_DEALS.DEAL_GRAPH)
PROTECTED = {"SMOKE_TEST"}


def parse_schema(path):
    text = re.sub(r"--[^\n]*", "", path.read_text())
    out = []  # (table, ddl) in file order (FK dependency order)
    for stmt in text.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = re.match(r"CREATE\s+OR\s+REPLACE\s+TABLE\s+([A-Za-z_][\w]*)\s*\(", stmt, re.I)
        if not m:
            raise SystemExit(f"schema.sql: unsupported statement: {stmt[:60]!r}")
        name = m.group(1).upper()
        if name in PROTECTED:
            raise SystemExit(f"schema.sql must not define protected table {name}")
        out.append((name, stmt))
    return out


def schema_cols(ddl):
    body = ddl[ddl.index("(") + 1: ddl.rindex(")")]
    cols, depth, cur = [], 0, ""
    for ch in body:  # split on top-level commas
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            cols.append(cur); cur = ""
        else:
            cur += ch
    cols.append(cur)
    return [c.split()[0].lower() for c in cols
            if c.strip() and c.split()[0].upper() not in ("CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE")]


def csv_header(p):
    with open(p, newline="") as f:
        return [h.strip().lower() for h in next(csv.reader(f))]


def connect():
    cfg = yaml.safe_load((ROOT / "raiconfig.yaml").read_text())
    c = cfg["connections"][cfg.get("default_connection", "pe_demo")]
    token = Path(c["token_file_path"]).expanduser().read_text().strip()
    con = snowflake.connector.connect(
        account=c["account"], user=c["user"], authenticator="programmatic_access_token",
        token=token, role=c["role"], warehouse=c["warehouse"], database=DB, schema=SCHEMA,
    )
    return con


def csv_rows(p):
    with open(p, newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def main():
    tables = parse_schema(DATA / "schema.sql")
    files = {t: CSV_DIR / f"{t}.csv" for t, _ in tables}
    for p in list(files.values()) + [CSV_DIR]:
        assert "golden" not in p.resolve().parts, f"refusing to load from golden: {p}"
    assert CSV_DIR.resolve() == (DATA / "csv").resolve()
    missing = [t for t, p in files.items() if not p.exists()]
    extra = sorted(p.stem for p in CSV_DIR.glob("*.csv") if p.stem.upper() not in dict(tables))
    if extra:
        print(f"WARNING: CSVs without a table in schema.sql (skipped): {extra}")
    if missing:
        print(f"WARNING: tables without a CSV (created empty, not verified): {missing}")
    # consistency pre-check: a CSV whose header differs from schema.sql is skipped (R05 mid-write)
    incons = [t for t, ddl in tables if files[t].exists() and csv_header(files[t]) != schema_cols(ddl)]
    for t in incons:
        print(f"INCONSISTENT (skipped, existing table untouched): {t} csv={csv_header(files[t])} "
              f"schema={schema_cols(dict(tables)[t])}")
    tables = [(t, d) for t, d in tables if t not in incons]
    mf = CSV_DIR / "MANIFEST.json"
    manifest = json.loads(mf.read_text())["tables"] if mf.exists() else None
    expected = {}
    for t, p in files.items():
        if not p.exists():
            continue
        expected[t] = manifest[t]["rows"] if manifest and t in manifest else csv_rows(p)

    con = connect()
    cur = con.cursor()
    try:
        ident = cur.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_ROLE()").fetchone()
        assert ident[:2] == (DB, SCHEMA), ident
        print(f"connected: db={ident[0]} schema={ident[1]} role={ident[2]}")
        cur.execute("CREATE TEMPORARY STAGE IF NOT EXISTS LOAD_STAGE")
        cur.execute("CREATE OR REPLACE FILE FORMAT LOAD_CSV_FMT TYPE=CSV PARSE_HEADER=TRUE "
                    "FIELD_OPTIONALLY_ENCLOSED_BY='\"' NULL_IF=('') EMPTY_FIELD_AS_NULL=TRUE "
                    "ERROR_ON_COLUMN_COUNT_MISMATCH=TRUE")
        for t, ddl in tables:
            cur.execute(ddl)
            if t in files and files[t].exists():
                cur.execute(f"PUT 'file://{files[t]}' @LOAD_STAGE/{t}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
                cur.execute(f"COPY INTO {t} FROM @LOAD_STAGE/{t}/ FILE_FORMAT=(FORMAT_NAME=LOAD_CSV_FMT) "
                            "MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE ON_ERROR=ABORT_STATEMENT FORCE=TRUE")
            cur.execute(f"ALTER TABLE {t} SET CHANGE_TRACKING = TRUE")
        rows, ok = [], True
        for t, _ in tables:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            ct = cur.execute(f"SHOW TABLES LIKE '{t}' IN SCHEMA {DB}.{SCHEMA}").fetchall()[0]
            cols = [d[0] for d in cur.description]
            tracking = ct[cols.index("change_tracking")]
            exp = expected.get(t)
            good = exp is not None and n == exp and tracking == "ON"
            ok &= good
            rows.append((t, exp, n, tracking, "OK" if good else "MISMATCH"))
        print(f"{'TABLE':18}{'EXPECTED':>9}{'LOADED':>8}  TRACKING  RESULT")
        for r in rows:
            print(f"{r[0]:18}{str(r[1]):>9}{r[2]:>8}  {r[3]:8}  {r[4]}")
        print(f"TOTAL expected={sum(v for v in expected.values())} loaded={sum(r[2] for r in rows)}")
        ok &= not incons
        print("LOAD PASS" if ok else f"LOAD FAIL (inconsistent={incons})")
        return 0 if ok else 1
    finally:
        con.close()



FIXTURES = {'baseline': ('DEPLOY', 'csv'),  # demo CSVs -> <schema>_DEPLOY_SRC, used by the deployments
            'sparse': ('SPARSE_10K', 'scale_sparse_seed_10k'),
            'connected': ('CONNECTED_10K', 'scale_connected_10k'),
            'connected100k': ('CONNECTED_100K', 'scale_connected_100k'),
            'connected1m': ('CONNECTED_1M', 'scale_connected_1m')}


def fixture_spec(fixture):
    suffix, directory = FIXTURES[fixture]
    output = f'{_cfg.DATABASE}.{_cfg.BASE_SCHEMA}_' + suffix
    return DATA / directory, output + '_SRC', output, output + '_META'


def canonical_rows(rows, ddl):
    from decimal import Decimal
    columns = schema_cols(ddl)
    types = [re.search(r'\b'+c+r'\s+(VARCHAR|NUMBER|DATE|BOOLEAN)', ddl, re.I).group(1).upper() for c in columns]
    def value(v, kind):
        if v is None or v == '': return None
        if kind == 'NUMBER': return Decimal(str(v))
        if kind == 'BOOLEAN': return str(v).lower() == 'true'
        return str(v)
    return sorted([tuple(value(v,k) for v,k in zip(row,types)) for row in rows], key=repr)


def fixture_data(fixture):
    import hashlib
    directory, *_ = fixture_spec(fixture)
    manifest = json.loads((directory/'MANIFEST.json').read_text())
    result = []
    for name, ddl in parse_schema(DATA/'schema.sql'):
        path = directory/f'{name}.csv'
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['tables'][name]['sha256']:
            raise RuntimeError('Fixture hash mismatch: '+name)
        with path.open() as fh:
            reader = csv.reader(fh); header = next(reader); rows = list(reader)
        if header != schema_cols(ddl) or len(rows) != manifest['tables'][name]['rows']:
            raise RuntimeError('Fixture layout/count mismatch: '+name)
        result.append((name,ddl,rows))
    return result


def verify_fixture_session(session, fixture):
    _, source, _, _ = fixture_spec(fixture)
    for name,ddl,expected in fixture_data(fixture):
        actual = session.sql(f"SELECT {','.join(schema_cols(ddl))} FROM {source}.{name}").collect()
        if canonical_rows(actual,ddl) != canonical_rows(expected,ddl):
            raise RuntimeError('Source contents differ: '+name)


def load_fixture(fixture, *, execute=False):
    """Fresh isolated targets only; never resume, replace, or repair on failure."""
    directory, source, output, meta = fixture_spec(fixture)
    data = fixture_data(fixture)
    if not execute:
        print(json.dumps(dict(fixture=fixture, directory=str(directory), schemas=[source,output,meta], tables=len(data))))
        return
    cfg = yaml.safe_load((ROOT/'raiconfig.yaml').read_text()); c = cfg['connections'][cfg['default_connection']]
    auth = {k: v for k, v in c.items() if k not in ('type', 'role', 'warehouse', 'database', 'schema')}  # any login method
    con = snowflake.connector.connect(**auth,
        role=f'{_cfg.ADMIN_ROLE}', warehouse=f'{_cfg.WAREHOUSE}', database=f'{_cfg.DATABASE}', schema=f'{_cfg.BASE_SCHEMA}')
    completed = []
    try:
        cur = con.cursor()
        if cur.execute('SELECT CURRENT_ROLE(),CURRENT_WAREHOUSE()').fetchone() != (f'{_cfg.ADMIN_ROLE}',f'{_cfg.WAREHOUSE}'):
            raise RuntimeError('Wrong provisioning context')
        cur.execute(f'SHOW SCHEMAS IN DATABASE {_cfg.DATABASE}')
        names = [d[0] for d in cur.description]
        existing = {dict(zip(names,r))['name'] for r in cur.fetchall()}
        if existing & {s.split('.')[1] for s in (source,output,meta)}:
            raise RuntimeError('Unexpected existing fixture target; stop')
        for schema in (source,output,meta):
            cur.execute(f'CREATE SCHEMA {schema}')
            completed.append(dict(action='create_schema',schema=schema,query_id=cur.sfqid))
            cur.execute(f'GRANT USAGE ON SCHEMA {schema} TO ROLE {_cfg.DEPLOY_ROLE}')
        for schema in (output,meta):
            for privilege in (('CREATE TABLE','CREATE VIEW') if schema == output else
                              ('CREATE TABLE','CREATE VIEW','CREATE PROCEDURE','CREATE TASK','CREATE TAG')):
                cur.execute(f'GRANT {privilege} ON SCHEMA {schema} TO ROLE {_cfg.DEPLOY_ROLE}')
        cur.execute(f'USE SCHEMA {source}')
        for name,ddl,rows in data:
            cur.execute(re.sub(r'^CREATE OR REPLACE TABLE '+name, 'CREATE TABLE '+source+'.'+name, ddl))
            columns = schema_cols(ddl)
            if fixture=='connected1m' and rows:
                import pandas as pd
                from snowflake.connector.pandas_tools import write_pandas
                frame=pd.DataFrame(rows,columns=[c.upper() for c in columns]).replace({'':None})
                success, _, loaded, _ = write_pandas(con,frame,name,database=source.split('.')[0],
                    schema=source.split('.')[1],chunk_size=100000,auto_create_table=False,
                    overwrite=False,on_error='abort_statement',use_logical_type=True)
                if not success or loaded!=len(rows):raise RuntimeError('Bulk load incomplete: '+name)
                del frame
            else:
                for offset in range(0,len(rows),5000 if fixture=='connected100k' else 250):
                    batch = rows[offset:offset+(5000 if fixture=='connected100k' else 250)]
                    placeholders = '('+','.join(['%s']*len(columns))+')'
                    cur.execute(f"INSERT INTO {source}.{name} ({','.join(columns)}) VALUES "+','.join([placeholders]*len(batch)),
                                tuple(v if v != '' else None for row in batch for v in row))
            actual = cur.execute(f"SELECT {','.join(columns)} FROM {source}.{name}").fetchall()
            if canonical_rows(actual,ddl) != canonical_rows(rows,ddl): raise RuntimeError('Loaded values differ: '+name)
            cur.execute(f'GRANT SELECT ON TABLE {source}.{name} TO ROLE {_cfg.DEPLOY_ROLE}')
            completed.append(dict(action='verified_table',table=name,rows=len(rows)))
            print(json.dumps(completed[-1]),flush=True)
        print(json.dumps(dict(result='LOAD PASS',fixture=fixture,completed=completed)),flush=True)
    except BaseException:
        print(json.dumps(dict(result='STOPPED',fixture=fixture,completed=completed)),flush=True)
        raise
    finally:
        con.close()


if __name__ == "__main__":
    if '--fixture' in sys.argv:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--fixture', choices=tuple(FIXTURES), required=True)
        parser.add_argument('--execute', action='store_true')
        args = parser.parse_args()
        load_fixture(args.fixture, execute=args.execute)
    else:
        sys.exit(main())
