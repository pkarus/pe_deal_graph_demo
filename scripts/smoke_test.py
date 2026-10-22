"""G0 smoke test (owner: R01 Platform).

Checks the full path Snowflake -> CDC data stream -> RAI logic engine -> PyRel query:
1. As RAI_DEMO_PE (raiconfig.yaml), make sure RAI_DEMO_PE_DEALS.DEAL_GRAPH.SMOKE_TEST
   exists with CHANGE_TRACKING = TRUE and exactly 3 known rows. Idempotent: the table
   is never replaced, so the RAI data stream bound to it stays valid across runs.
2. Read it through a one-concept PyRel model and assert the entity count is 3.

Run: make smoke   (or .venv/bin/python scripts/smoke_test.py)
"""

from relationalai.config import create_config
from relationalai.semantics import Integer, Model, String
from relationalai.semantics.std import aggregates as aggs

TABLE = "RAI_DEMO_PE_DEALS.DEAL_GRAPH.SMOKE_TEST"
EXPECTED = 3

SETUP_SQL = [
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
          ID INTEGER NOT NULL,
          LABEL VARCHAR NOT NULL
        )
        CHANGE_TRACKING = TRUE
        COMMENT = 'G0 smoke test (R01). Safe to drop.'""",
    f"ALTER TABLE {TABLE} SET CHANGE_TRACKING = TRUE",
    f"""MERGE INTO {TABLE} t
        USING (SELECT column1 AS ID, column2 AS LABEL
               FROM VALUES (1, 'alpha'), (2, 'bravo'), (3, 'charlie')) s
        ON t.ID = s.ID
        WHEN MATCHED AND t.LABEL <> s.LABEL THEN UPDATE SET LABEL = s.LABEL
        WHEN NOT MATCHED THEN INSERT (ID, LABEL) VALUES (s.ID, s.LABEL)""",
    f"DELETE FROM {TABLE} WHERE ID NOT IN (1, 2, 3)",
]


def setup_table() -> int:
    session = create_config().get_session()
    ident = session.sql("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_SCHEMA()").collect()[0]
    print(f"session: role={ident[0]} database={ident[1]} schema={ident[2]}")
    assert ident[0] == "RAI_DEMO_PE", f"expected role RAI_DEMO_PE, got {ident[0]}"
    for stmt in SETUP_SQL:
        session.sql(stmt).collect()
    sf_count = session.sql(f"SELECT COUNT(*) FROM {TABLE}").collect()[0][0]
    ct = session.sql(f"SHOW TABLES LIKE 'SMOKE_TEST' IN SCHEMA RAI_DEMO_PE_DEALS.DEAL_GRAPH").collect()
    change_tracking = ct[0]["change_tracking"] if ct else None
    print(f"snowflake: {TABLE} rows={sf_count} change_tracking={change_tracking}")
    assert change_tracking == "ON", f"CHANGE_TRACKING is {change_tracking}, expected ON"
    return sf_count


# Tiny PyRel model, defined at module level.
model = Model("pe_demo_smoke_test")
SmokeRow = model.Concept("SmokeRow", identify_by={"id": Integer})
SmokeRow.label = model.Property(f"{SmokeRow} has {String:label}")


def define_model() -> None:
    src = model.Table(TABLE)
    model.define(r := SmokeRow.new(id=src.ID), r.label(src.LABEL))


def main() -> None:
    sf_count = setup_table()
    assert sf_count == EXPECTED, f"Snowflake row count {sf_count} != {EXPECTED}"

    define_model()
    rows = model.select(SmokeRow.id.alias("id"), SmokeRow.label.alias("label")).to_df()
    print(rows.sort_values("id").to_string(index=False))
    rai_count = int(model.select(aggs.count(SmokeRow).alias("n")).to_df()["n"].iloc[0])
    print(f"rai: SmokeRow count={rai_count}")
    assert rai_count == EXPECTED, f"RAI count {rai_count} != {EXPECTED}"
    print("SMOKE TEST PASS")


if __name__ == "__main__":
    main()
