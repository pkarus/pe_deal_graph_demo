"""Scout: create or drop the tiny SCOUT_* tables in RAI_DEMO_PE_DEALS.DEAL_GRAPH.

Column types mirror data/schema.sql (VARCHAR ids, NUMBER(10,2) money, NUMBER(1) level,
BOOLEAN flag, nullable DATE end dates), so the idioms verified here transfer to the real model.

Run: .venv/bin/python scripts/scout/scout_tables.py create | drop
"""
import sys

from relationalai.config import create_config

S = "RAI_DEMO_PE_DEALS.DEAL_GRAPH"

TABLES = {
    "SCOUT_SECTOR": (
        "sector_id VARCHAR(16) NOT NULL, name VARCHAR(120) NOT NULL, level NUMBER(1) NOT NULL, parent_id VARCHAR(16)",
        [("SC1", "Healthcare", 1, None), ("SC2", "Healthcare Services", 2, "SC1"),
         ("SC3", "Dental Services", 3, "SC2"), ("SC4", "Veterinary Clinics", 3, "SC2"),
         ("SC5", "Industrials", 1, None), ("SC6", "Testing, Inspection, Certification", 2, "SC5"),
         ("SC7", "Environmental Testing", 3, "SC6"), ("SC8", "Materials Testing", 3, "SC6"),
         ("SC9", "Life Sciences", 1, None), ("SC11", "Pharma Manufacturing", 2, "SC9"),
         ("SC10", "Veterinary Pharma", 3, "SC11")],
    ),
    "SCOUT_COMPANY": (
        "company_id VARCHAR(16) NOT NULL, name VARCHAR(120) NOT NULL, sector_id VARCHAR(16) NOT NULL, "
        "ebitda_musd NUMBER(10,2), revenue_musd NUMBER(10,2), is_founder_owned BOOLEAN NOT NULL",
        [("C1", "Brightwater Dental", "SC3", 12.50, 80.00, False),
         ("C2", "Walnut Dental", "SC3", 18.00, 115.00, True),
         ("C3", "Meridian Lab Services", "SC7", 9.00, 60.00, False),
         ("C4", "Granite TIC", "SC8", 30.00, 200.00, False),
         ("C5", "Envirolab", "SC7", 11.00, 70.00, True),
         ("C6", "VetPharma Co", "SC10", 15.00, 90.00, True),
         ("C7", "Samesite Testing", "SC8", 8.00, 50.00, True),
         ("C8", "Cust A", "SC8", 44.00, 300.00, False),
         ("C9", "Cust B", "SC8", 6.00, 40.00, True),
         ("C10", "Cust C", "SC8", None, None, False),
         ("C11", "Cust D", "SC4", 7.00, 45.00, True),
         ("C12", "Cust E", "SC4", 7.00, 45.00, False),
         ("C13", "Cust F", "SC4", 5.00, 30.00, False)],
    ),
    "SCOUT_SPONSOR": (
        "sponsor_id VARCHAR(16) NOT NULL, name VARCHAR(120) NOT NULL, aum_musd NUMBER(10,2)",
        [("S1", "Northwind Equity Partners", 2500.00), ("S2", "Ironbridge Capital", 900.00)],
    ),
    "SCOUT_INTERMEDIARY": (
        "intermediary_id VARCHAR(16) NOT NULL, name VARCHAR(120) NOT NULL, intermediary_type VARCHAR(30) NOT NULL",
        [("I1", "Harbor Lane Advisors", "boutique"), ("I2", "Cedar Row Partners", "boutique"),
         ("I3", "Big Bank", "large_bank")],
    ),
    "SCOUT_PERSON": (
        "person_id VARCHAR(16) NOT NULL, name VARCHAR(120) NOT NULL",
        [("P1", "Dana Okafor"), ("P2", "Elena Marsh"), ("P3", "Walter Kim"), ("P4", "Tom Brennan"),
         ("P5", "Victor Hale"), ("P6", "Sam Short"), ("P7", "Grace Liu"), ("P8", "Hal Harbor"),
         ("P9", "Ivy Iron")],
    ),
    "SCOUT_ROLE": (
        "role_id VARCHAR(16) NOT NULL, person_id VARCHAR(16) NOT NULL, org_id VARCHAR(16) NOT NULL, "
        "org_type VARCHAR(20) NOT NULL, role_type VARCHAR(30) NOT NULL, start_date DATE NOT NULL, end_date DATE",
        [("R1", "P1", "S1", "sponsor", "Operating Partner", "2020-01-06", None),
         ("R2", "P1", "C1", "company", "COO", "2015-03-01", "2019-06-30"),
         ("R3", "P2", "C1", "company", "CFO", "2014-01-01", "2019-12-31"),
         ("R4", "P2", "C2", "company", "CFO", "2025-06-01", None),
         ("R5", "P3", "C2", "company", "CEO", "2008-01-01", None),
         ("R6", "P4", "S1", "sponsor", "Deal Team", "2012-01-09", None),
         ("R7", "P4", "C3", "company", "VP", "2008-01-07", "2011-06-30"),
         ("R8", "P5", "C3", "company", "CEO", "2013-03-04", "2020-08-31"),
         ("R9", "P6", "C3", "company", "Analyst", "2011-01-01", "2011-08-31"),
         ("R10", "P7", "C2", "company", "Board", "2022-04-01", None),
         ("R11", "P8", "I1", "intermediary", "Managing Director", "2010-01-01", None),
         ("R12", "P9", "S2", "sponsor", "Partner", "2015-01-01", None),
         ("R13", "P7", "S2", "sponsor", "Operating Partner", "2018-01-01", "2021-12-31")],
    ),
}


def lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def main(action: str) -> None:
    session = create_config().get_session()
    role = session.sql("SELECT CURRENT_ROLE()").collect()[0][0]
    assert role == "RAI_DEMO_PE", role
    for name, (cols, rows) in TABLES.items():
        fq = f"{S}.{name}"
        if action == "drop":
            session.sql(f"DROP TABLE IF EXISTS {fq}").collect()
            print(f"dropped {fq}")
            continue
        session.sql(f"CREATE TABLE IF NOT EXISTS {fq} ({cols}) CHANGE_TRACKING = TRUE "
                    f"COMMENT = 'Scout toy table. Safe to drop.'").collect()
        session.sql(f"DELETE FROM {fq}").collect()
        values = ", ".join("(" + ", ".join(lit(v) for v in r) + ")" for r in rows)
        session.sql(f"INSERT INTO {fq} VALUES {values}").collect()
        n = session.sql(f"SELECT COUNT(*) FROM {fq}").collect()[0][0]
        print(f"{fq}: {n} rows")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "create")
