"""Scout probe: (a) do model.data() rows with "" / None in one column vanish from rules that do not
use that column? (b) does string_join / mixed-order rank work? Run on the default compiler, then
with RAI_LQP_COMPILER=direct to compare.

Run: .venv/bin/python scripts/scout/probe_inline.py
     RAI_LQP_COMPILER=direct .venv/bin/python scripts/scout/probe_inline.py
"""
import os
import traceback

import pandas as pd
from relationalai.semantics import Integer, Model, String
from relationalai.semantics.std import aggregates as aggs
from relationalai.semantics.std.aggregates import asc, desc, rank

print("compiler:", os.environ.get("RAI_LQP_COMPILER", "legacy (default)"))
model = Model("pe_scout_probe")
rows = model.data(pd.DataFrame({"deal_id": ["D1", "D2", "D3"], "advisor": ["I1", "I3", "I3"],
                                "buyer": ["S1", "", None]}))
Deal = model.Concept("Deal", identify_by={"deal_id": String})
Deal.advisor = model.Property(f"{Deal} advised by {String:advisor}")
Deal.score = model.Property(f"{Deal} has {Integer:score}")
model.define(d := Deal.new(deal_id=rows.deal_id), d.advisor(rows.advisor))
model.where(Deal.deal_id == "D1").define(Deal.score(10))
model.where(Deal.deal_id == "D2").define(Deal.score(10))
model.where(Deal.deal_id == "D3").define(Deal.score(5))

print(model.select(Deal.deal_id.alias("deal"), Deal.advisor.alias("advisor")).to_df().sort_values("deal"))
print(model.select(rows.deal_id.alias("deal"), rows.buyer.alias("buyer")).to_df().sort_values("deal"))
for label, fn in [
    ("string_join", lambda: model.select(aggs.string_join(Deal.deal_id, sep=",").alias("joined")).to_df()),
    ("mixed rank", lambda: model.select(Deal.deal_id.alias("deal"),
                                        rank(desc(Deal.score), asc(Deal.deal_id)).alias("r")).to_df()),
]:
    try:
        print(label, "OK\n", fn())
    except Exception as e:  # noqa: BLE001
        print(label, "FAIL", repr(e)[:200])
