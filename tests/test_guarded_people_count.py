"""Offline regression checks: no model execution or Snowflake connection."""
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest


guard = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/guarded_people_count.py"))


def test_real_sdk_table_source_name(monkeypatch):
    from relationalai.config import Config
    from relationalai.semantics import Model, String
    from snowflake.snowpark import Session

    def no_connection(*args, **kwargs):
        raise AssertionError("Offline regression must not connect or execute SQL")

    monkeypatch.setattr(Config, "get_session", no_connection)
    monkeypatch.setattr(Session, "sql", no_connection)
    config = Config(
        connections={"offline": {"type": "duckdb", "path": ":memory:"}},
        default_connection="offline",
    )
    model = Model("offline_source_guard", config=config, is_library=True)
    source = guard["SCOPE"] + ".PERSON"
    table = model.Table(source, schema={"PERSON_ID": String, "NAME": String})
    assert table._name == source
    assert not isinstance(table.name, str)
    assert guard["require_table_sources"]([table]) == [source]
    with pytest.raises(RuntimeError, match="must be a string"):
        guard["require_sources"]([table.name])

    outside = model.Table("OTHER_DB.OTHER_SCHEMA.PERSON", schema={"PERSON_ID": String})
    with pytest.raises(RuntimeError, match="Source scope violation"):
        guard["require_table_sources"]([outside])


@pytest.mark.parametrize("value", [None, 123, [], {}])
def test_rejects_non_string_before_allowlist(value):
    with pytest.raises(RuntimeError, match="must be a string"):
        guard["require_table_sources"]([SimpleNamespace(_name=value)])
