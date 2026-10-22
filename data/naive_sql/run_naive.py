#!/usr/bin/env python
"""Run the naive "SQL screen" baselines in data/naive_sql/*.sql on Snowflake (owner: R11).

Usage:
    .venv/bin/python data/naive_sql/run_naive.py            # run every .sql, print row counts and top rows
    .venv/bin/python data/naive_sql/run_naive.py q_flow      # run one baseline

Connects as RAI_DEMO_PE exactly like data/load.py (PAT from raiconfig.yaml, never printed).
Statement text is prepared the way pe_deal_graph/export.py does (full-line `--` comments removed,
trailing semicolon dropped), so what the tests run is what the exporter runs.
Plain warehouse SQL only: no RAI engine involved.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAIVE_DIR = Path(__file__).resolve().parent
DB, SCHEMA = "RAI_DEMO_PE_DEALS", "DEAL_GRAPH"


def sql_text(name: str) -> str:
    """Executable statement for data/naive_sql/<name>.sql (comment lines stripped, as export.py does)."""
    text = (NAIVE_DIR / f"{name}.sql").read_text(encoding="utf-8")
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("--")).strip().rstrip(";")


def connect():
    import snowflake.connector
    import yaml

    cfg = yaml.safe_load((ROOT / "raiconfig.yaml").read_text())
    c = cfg["connections"][cfg.get("default_connection", "pe_demo")]
    token = Path(c["token_file_path"]).expanduser().read_text().strip()
    return snowflake.connector.connect(
        account=c["account"], user=c["user"], authenticator="programmatic_access_token",
        token=token, role=c["role"], warehouse=c["warehouse"], database=DB, schema=SCHEMA,
    )


def run(name: str, con=None):
    """Run one baseline and return a pandas DataFrame with lower-case column names."""
    import pandas as pd

    own = con is None
    con = con or connect()
    try:
        cur = con.cursor()
        cur.execute(sql_text(name))
        cols = [d[0].lower() for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        if own:
            con.close()


def all_names() -> list[str]:
    return sorted(p.stem for p in NAIVE_DIR.glob("*.sql"))


def main(argv: list[str]) -> int:
    import pandas as pd

    names = argv or all_names()
    con = connect()
    try:
        for n in names:
            df = run(n, con)
            print(f"## {n}.sql: {len(df)} rows")
            with pd.option_context("display.width", 220, "display.max_colwidth", 120):
                print(df.head(12).to_string(index=False))
            print()
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
