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
DATA = ROOT / "data"
CSV_DIR = DATA / "csv"
DB, SCHEMA = "RAI_DEMO_PE_DEALS", "DEAL_GRAPH"
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


if __name__ == "__main__":
    sys.exit(main())
