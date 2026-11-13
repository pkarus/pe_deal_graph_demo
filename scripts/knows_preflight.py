"""Pre-flight for the tenure-overlap rule: how many role pairs would it have to compare?

The K1 rule (rules.knows_tenure_overlap) joins every pair of roles at the same organization. That is
harmless when employers are small (the scale fixtures cap a workplace at 16 people) and explosive when
one employer has thousands of roles: n roles -> n*(n-1)/2 candidate pairs. Run this on the ROLE_HISTORY
table you are about to model BEFORE deploying; it only runs one aggregate SELECT.

Usage
    python scripts/knows_preflight.py --table MY_DB.MY_SCHEMA.ROLE_HISTORY
    python scripts/knows_preflight.py --fixture connected1m --cap 500

``--cap N`` also reports what PE_K1_MAX_ORG_ROLES=N would skip.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pe_deal_graph import settings as _cfg  # noqa: E402

SOURCES = {"baseline": "DEPLOY_SRC", "connected100k": "CONNECTED_100K_SRC", "connected1m": "CONNECTED_1M_SRC",
           "connected10m": "CONNECTED_10M_SRC"}
WARN_PAIRS = 2_000_000_000  # above this, cap giant employers or expect a very long refresh


def preflight_sql(table: str, cap: int) -> str:
    return f"""WITH org AS (SELECT ORG_ID, COUNT(*) AS N FROM {table} GROUP BY ORG_ID)
SELECT COUNT(*) AS ORGANIZATIONS, SUM(N) AS ROLES, MAX(N) AS LARGEST_ORG_ROLES,
       APPROX_PERCENTILE(N, 0.5) AS MEDIAN_ORG_ROLES, APPROX_PERCENTILE(N, 0.99) AS P99_ORG_ROLES,
       SUM(N * (N - 1) / 2) AS CANDIDATE_PAIRS,
       SUM(IFF(N > {cap}, N * (N - 1) / 2, 0)) AS PAIRS_IN_ORGS_OVER_CAP,
       COUNT_IF(N > {cap}) AS ORGS_OVER_CAP, SUM(IFF(N > {cap}, N, 0)) AS ROLES_IN_ORGS_OVER_CAP
FROM org"""


def summarize(row: dict, cap: int) -> dict:
    pairs = int(row["CANDIDATE_PAIRS"] or 0)
    over = int(row["PAIRS_IN_ORGS_OVER_CAP"] or 0)
    out = {k.lower(): int(v or 0) for k, v in row.items()}
    out["cap"] = cap
    out["candidate_pairs_with_cap"] = pairs - over
    out["share_of_pairs_in_orgs_over_cap"] = round(over / pairs, 4) if pairs else 0.0
    out["verdict"] = ("OK: the tenure rule compares a manageable number of role pairs" if pairs <= WARN_PAIRS else
                      f"RISK: {pairs:,} candidate pairs. Set PE_K1_MAX_ORG_ROLES={cap} "
                      f"({pairs - over:,} pairs remain) or a different cap before deploying.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--table", help="fully qualified ROLE_HISTORY-shaped table (needs an ORG_ID column)")
    where.add_argument("--fixture", choices=sorted(SOURCES))
    ap.add_argument("--cap", type=int, default=500)
    ap.add_argument("--print-sql", action="store_true")
    args = ap.parse_args()
    table = args.table or f"{_cfg.schema(SOURCES[args.fixture])}.ROLE_HISTORY"
    sql = preflight_sql(table, args.cap)
    if args.print_sql:
        print(sql)
        return 0
    import person_path_proc
    con = person_path_proc.connect()
    try:
        cur = con.cursor()
        cur.execute(sql)
        row = dict(zip([d[0] for d in cur.description], cur.fetchone()))
    finally:
        con.close()
    print(json.dumps(dict(table=table, **summarize(row, args.cap)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
