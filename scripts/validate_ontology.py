#!/usr/bin/env python
"""G3 ontology check (owner: R08). Run: make ontology-check   (or .venv/bin/python scripts/validate_ontology.py)

Checks
  A. offline   ONTOLOGY.md concept glossary == concepts declared in pe_deal_graph/model/core.py (exact names);
               ONTOLOGY.md interface contract == core.DERIVED_CONCEPTS + core.DERIVED_RELATIONSHIPS (exact names),
               and every contract signature equals the reading registered in code;
               every table in data/schema.sql is bound in core.py and listed in the ONTOLOGY.md mapping;
               every schema.sql column is bound in core.py unless listed in UNMAPPED_COLUMNS.
  B. engine    entity count per concept == Snowflake source rows (Organization == companies + sponsors + intermediaries);
               every core (source-bound) relationship has > 0 facts AND exactly the number of facts its
               source column implies (non-null values, TRUE flags, distinct pairs).
  C. --derived (after P4) every non-optional derived name in the contract has > 0 facts.

Flags: --offline (A only), --derived (A + B + C), --no-sql (skip Snowflake SQL; B then only checks > 0).
Exit code 0 = PASS, 1 = FAIL. Uses the RAI engine for B/C (one model, a few batched queries).
"""
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AS_OF_SQL = "DATE '2026-10-01'"
# schema.sql columns intentionally not bound (the org subtype already says which table an org_id points to)
UNMAPPED_COLUMNS = {
    ("ROLE_HISTORY", "ORG_TYPE"),
    ("TRANSACTION_PARTY", "ORG_TYPE"),
    ("CRM_INTERACTION", "COUNTERPARTY_ORG_TYPE"),
}

# Core relationship -> SQL that returns the number of facts the source implies.
# ("T", None) = COUNT(*) of T; ("T", "COL") = non-null COL; ("T", "COL=TRUE") = TRUE flags; str = raw SQL.
ORGS = "(SELECT COUNT(*) FROM SPONSOR) + (SELECT COUNT(*) FROM INTERMEDIARY) + (SELECT COUNT(*) FROM COMPANY)"
EXPECTED_FACTS = {
    "Organization.name": ORGS,
    "Organization.hq_region": ORGS,
    "Sector.name": ("SECTOR", None), "Sector.level": ("SECTOR", None), "Sector.parent": ("SECTOR", "PARENT_ID"),
    "Region.name": ("REGION", None), "Region.level": ("REGION", None), "Region.region_type": ("REGION", None),
    "Region.parent": ("REGION", "PARENT_ID"),
    "Company.sector": ("COMPANY", None), "Company.revenue_musd": ("COMPANY", "REVENUE_MUSD"),
    "Company.ebitda_musd": ("COMPANY", "EBITDA_MUSD"), "Company.employees": ("COMPANY", "EMPLOYEES"),
    "Company.founded_year": ("COMPANY", "FOUNDED_YEAR"), "Company.is_public": ("COMPANY", "IS_PUBLIC=TRUE"),
    "Company.operates_in": "SELECT COUNT(*) FROM (SELECT DISTINCT COMPANY_ID, REGION_ID FROM COMPANY_SITE)",
    "Company.supplies": "SELECT COUNT(*) FROM (SELECT DISTINCT SUPPLIER_ID, CUSTOMER_ID FROM COMMERCIAL_LINK)",
    "Sponsor.aum_musd": ("SPONSOR", "AUM_MUSD"), "Sponsor.strategy": ("SPONSOR", "STRATEGY"),
    "Intermediary.intermediary_type": ("INTERMEDIARY", None),
    "Person.first_name": ("PERSON", None), "Person.last_name": ("PERSON", None), "Person.name": ("PERSON", None),
    "Fund.name": ("FUND", None), "Fund.sponsor": ("FUND", None), "Fund.vintage_year": ("FUND", None),
    "Fund.size_musd": ("FUND", None), "Fund.ebitda_min_musd": ("FUND", "EBITDA_MIN_MUSD"),
    "Fund.ebitda_max_musd": ("FUND", "EBITDA_MAX_MUSD"), "Fund.geography": ("FUND", "GEOGRAPHY"),
    "Fund.area_guideline_pct": ("FUND", "AREA_GUIDELINE_PCT"),
    "FundFocus.fund": ("FUND_FOCUS", None), "FundFocus.sector": ("FUND_FOCUS", None),
    "FundFocus.mode": ("FUND_FOCUS", None), "FundFocus.margin_benchmark_pct": ("FUND_FOCUS", "MARGIN_BENCHMARK_PCT"),
    "Role.person": ("ROLE_HISTORY", None), "Role.organization": ("ROLE_HISTORY", None),
    "Role.role_type": ("ROLE_HISTORY", None), "Role.title": ("ROLE_HISTORY", "TITLE"),
    "Role.start_date": ("ROLE_HISTORY", None), "Role.end_date": ("ROLE_HISTORY", "END_DATE"),
    "Role.is_founder": ("ROLE_HISTORY", "IS_FOUNDER=TRUE"),
    "Role.effective_end_date": ("ROLE_HISTORY", None),
    "Role.is_current": f"SELECT COUNT(*) FROM ROLE_HISTORY WHERE START_DATE <= {AS_OF_SQL} "
                       f"AND (END_DATE IS NULL OR END_DATE > {AS_OF_SQL})",
    "Ownership.company": ("OWNERSHIP", None), "Ownership.fund": ("OWNERSHIP", None),
    "Ownership.start_date": ("OWNERSHIP", None), "Ownership.end_date": ("OWNERSHIP", "END_DATE"),
    "Ownership.stake_type": ("OWNERSHIP", None), "Ownership.equity_invested_musd": ("OWNERSHIP", "EQUITY_INVESTED_MUSD"),
    "Ownership.effective_end_date": ("OWNERSHIP", None),
    "Ownership.is_current": f"SELECT COUNT(*) FROM OWNERSHIP WHERE START_DATE <= {AS_OF_SQL} "
                            f"AND (END_DATE IS NULL OR END_DATE > {AS_OF_SQL})",
    "Transaction.target": ("TRANSACTION", None), "Transaction.close_date": ("TRANSACTION", None),
    "Transaction.deal_role": ("TRANSACTION", None), "Transaction.seller_type": ("TRANSACTION", None),
    "Transaction.structure": ("TRANSACTION", None), "Transaction.ev_musd": ("TRANSACTION", "EV_MUSD"),
    "Transaction.ev_ebitda": ("TRANSACTION", "EV_EBITDA"),
    "TransactionParty.transaction": ("TRANSACTION_PARTY", None),
    "TransactionParty.organization": ("TRANSACTION_PARTY", None),
    "TransactionParty.party_role": ("TRANSACTION_PARTY", None),
    "TransactionParty.fund": ("TRANSACTION_PARTY", "FUND_ID"),
    "TransactionParty.lead_person": ("TRANSACTION_PARTY", "LEAD_PERSON_ID"),
    "CommercialLink.supplier": ("COMMERCIAL_LINK", None), "CommercialLink.customer": ("COMMERCIAL_LINK", None),
    "CommercialLink.value_band": ("COMMERCIAL_LINK", None), "CommercialLink.since_year": ("COMMERCIAL_LINK", "SINCE_YEAR"),
    "Interaction.our_person": ("CRM_INTERACTION", None),
    "Interaction.counterparty_person": ("CRM_INTERACTION", "COUNTERPARTY_PERSON_ID"),
    "Interaction.counterparty_org": ("CRM_INTERACTION", "COUNTERPARTY_ORG_ID"),
    "Interaction.interaction_date": ("CRM_INTERACTION", None), "Interaction.channel": ("CRM_INTERACTION", None),
    "Interaction.sentiment": ("CRM_INTERACTION", None),
    "PipelineEntry.company": ("PIPELINE", None), "PipelineEntry.stage": ("PIPELINE", None),
    "PipelineEntry.added_date": ("PIPELINE", None), "PipelineEntry.owner": ("PIPELINE", None),
    "PipelineEntry.est_equity_check_musd": ("PIPELINE", "EST_EQUITY_CHECK_MUSD"),
    "Signal.company": ("COMPANY_SIGNAL", None), "Signal.signal_type": ("COMPANY_SIGNAL", None),
    "Signal.signal_date": ("COMPANY_SIGNAL", None), "Signal.event_date": ("COMPANY_SIGNAL", "EVENT_DATE"),
    "Signal.intermediary": ("COMPANY_SIGNAL", "INTERMEDIARY_ID"),
    "Signal.magnitude_musd": ("COMPANY_SIGNAL", "MAGNITUDE_MUSD"),
}

RESULTS = []  # (status, check, detail)


def record(ok, check, detail="", warn=False):
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    RESULTS.append((status, check, detail))
    print(f"{status:4}  {check}{('  ' + detail) if detail else ''}", flush=True)


# ------------------------------------------------------------------------------------------ A. offline
def md_section(text, heading_prefix):
    m = re.search(rf"^## {re.escape(heading_prefix)}.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def md_first_cells(section):
    """Backticked names in the first cell of markdown table rows -> {name: [other cells]}."""
    out = {}
    for line in section.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|(.*)\|\s*$", line)
        if m:
            out[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return out


def reading_of(core, name):
    """Registered reading of a derived relationship (or concept signature) from the code."""
    from relationalai.semantics import inspect

    schema = inspect.schema(core.model)
    if "." not in name and name in {c.name for c in schema.concepts}:
        c = schema[name]
        if c.extends:
            return "extends " + ", ".join(c.extends)
        return "identify_by " + ", ".join(f"{f.name}: {f.type_name}" for f in c.identify_by)
    if "." not in name:  # standalone value
        rel = getattr(core, name)
        return rel._readings[0] if hasattr(rel, "_readings") else str(rel)
    cname, attr = name.split(".", 1)
    c = schema[cname]
    for r in tuple(c.properties) + tuple(c.relationships):
        if r.name == attr:
            return r.reading
    return None


def standalone_reading(core, name):
    from relationalai.semantics import inspect

    schema = inspect.schema(core.model)
    rel = getattr(core, name)
    target = f"Integer:{name}"
    for r in tuple(schema.bare_properties) + tuple(schema.bare_relationships):
        if r.reading.endswith(target):
            return r.reading
    return str(rel)


def parse_schema_sql():
    text = re.sub(r"--[^\n]*", "", (ROOT / "data" / "schema.sql").read_text())
    tables = {}
    for stmt in text.split(";"):
        m = re.match(r"\s*CREATE\s+OR\s+REPLACE\s+TABLE\s+(\w+)\s*\((.*)\)\s*$", stmt, re.S | re.I)
        if not m:
            continue
        cols = []
        for line in m.group(2).splitlines():
            line = line.strip()
            if not line or re.match(r"(PRIMARY|CONSTRAINT|FOREIGN|UNIQUE)\b", line, re.I):
                continue
            cols.append(line.split()[0].upper())
        tables[m.group(1).upper()] = cols
    return tables


def bound_columns_from_core():
    """Columns used as _src.<COL> inside each _bind("<TABLE>") block of core.py."""
    text = (ROOT / "pe_deal_graph" / "model" / "core.py").read_text()
    out, current = {}, None
    for line in text.splitlines():
        m = re.search(r'_src = _bind\("(\w+)"\)', line)
        if m:
            current = m.group(1)
            out[current] = set()
            continue
        if line.startswith("del _src"):
            current = None
        if current:
            out[current].update(re.findall(r"_src\.([A-Z_][A-Z0-9_]*)", line))
    return out


def check_offline(core):
    from relationalai.semantics import inspect

    doc_path = ROOT / "ONTOLOGY.md"
    if not doc_path.exists():
        record(False, "ONTOLOGY.md exists")
        return
    doc = doc_path.read_text()
    schema = inspect.schema(core.model)
    code_concepts = {c.name for c in schema.concepts}

    glossary = set(md_first_cells(md_section(doc, "2. Concept glossary")))
    record(glossary == code_concepts, "concept names: ONTOLOGY.md glossary == core.py",
           f"{len(code_concepts)} concepts" if glossary == code_concepts else
           f"only in doc={sorted(glossary - code_concepts)} only in code={sorted(code_concepts - glossary)}")

    contract_rows = md_first_cells(md_section(doc, "5. Interface contract"))
    declared = set(core.DERIVED_CONCEPTS) | set(core.DERIVED_RELATIONSHIPS)
    doc_names = set(contract_rows)
    record(doc_names == declared, "interface contract names: ONTOLOGY.md == core.DERIVED_*",
           f"{len(declared)} names" if doc_names == declared else
           f"only in doc={sorted(doc_names - declared)} only in code={sorted(declared - doc_names)}")

    missing = []
    for n in declared:
        obj = core
        for part in n.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                break
        if obj is None:
            missing.append(n)
    record(not missing, "every contract name resolves in core.py", f"missing={missing}" if missing else "")

    bad_sig = []
    for n in sorted(declared & doc_names):
        cells = contract_rows[n]
        doc_sig = cells[0].strip("` ") if cells else ""
        code_sig = standalone_reading(core, n) if "." not in n and n not in code_concepts else reading_of(core, n)
        if doc_sig != code_sig:
            bad_sig.append(f"{n}: doc='{doc_sig}' code='{code_sig}'")
    record(not bad_sig, "contract signatures in ONTOLOGY.md == readings registered in code",
           "; ".join(bad_sig[:6]) + (f" (+{len(bad_sig) - 6} more)" if len(bad_sig) > 6 else ""))

    sql_tables = parse_schema_sql()
    mapping = md_section(doc, "4. Table-to-concept mapping")
    doc_tables = set(re.findall(r"^\|\s*`([A-Z_]+)`", mapping, re.M))
    bound = bound_columns_from_core()
    record(set(sql_tables) == set(core.SOURCE_TABLES), "every schema.sql table is bound in core.py",
           f"{len(sql_tables)} tables" if set(sql_tables) == set(core.SOURCE_TABLES) else
           f"unbound={sorted(set(sql_tables) - set(core.SOURCE_TABLES))} "
           f"stale={sorted(set(core.SOURCE_TABLES) - set(sql_tables))}")
    record(set(sql_tables) == doc_tables, "every schema.sql table is in the ONTOLOGY.md mapping",
           "" if set(sql_tables) == doc_tables else
           f"missing={sorted(set(sql_tables) - doc_tables)} stale={sorted(doc_tables - set(sql_tables))}")
    unmapped = []
    for t, cols in sql_tables.items():
        for col in cols:
            if (t, col) not in UNMAPPED_COLUMNS and col not in bound.get(t, set()):
                unmapped.append(f"{t}.{col}")
    record(not unmapped, "every schema.sql column is bound (except documented org_type columns)",
           f"unbound={unmapped}" if unmapped else "", warn=True)


# ------------------------------------------------------------------------------------------ B/C. engine
def resolve(core, name):
    if "." not in name:
        rel = getattr(core, name)
        return rel._next if hasattr(rel, "_next") and rel._next is not None else rel
    cname, attr = name.split(".", 1)
    chain = getattr(getattr(core, cname), attr)
    return chain._next if hasattr(chain, "_next") else chain


def fact_count_expr(rel):
    from relationalai.semantics.std import aggregates as aggs

    refs = [f.type.ref() for f in rel._fields]
    return aggs.count(*refs).where(rel(*refs))


def run_counts(core, named_exprs, batch=20):
    """Evaluate {label: aggregate expr} in batched selects; missing (empty) aggregates become 0."""
    out = {}
    items = list(named_exprs.items())
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        cols = [(expr | 0).alias(f"c{j}") for j, (_, expr) in enumerate(chunk)]
        df = core.model.select(*cols).to_df()
        if len(df) == 1:
            for j, (label, _) in enumerate(chunk):
                out[label] = int(df[f"c{j}"].iloc[0])
            continue
        # An empty aggregate without a working default empties the whole row: fall back to one query each.
        for label, expr in chunk:
            one = core.model.select(expr.alias("n")).to_df()
            out[label] = int(one["n"].iloc[0]) if len(one) else 0
    return out


def sql_counts(core):
    from relationalai.config import create_config

    session = create_config().get_session()
    session.sql(f"USE SCHEMA {core.SOURCE_SCHEMA}").collect()
    exprs = {}
    for t in core.SOURCE_TABLES:
        exprs[f"rows:{t}"] = f"SELECT COUNT(*) FROM {t}"
    for name, spec in EXPECTED_FACTS.items():
        if isinstance(spec, str):
            exprs[name] = spec if spec.lstrip().upper().startswith("SELECT") else f"SELECT {spec}"
        else:
            t, col = spec
            if col is None:
                exprs[name] = f"SELECT COUNT(*) FROM {t}"
            elif col.endswith("=TRUE"):
                exprs[name] = f"SELECT COUNT(*) FROM {t} WHERE {col[:-5]} = TRUE"
            else:
                exprs[name] = f"SELECT COUNT({col}) FROM {t}"
    labels = list(exprs)
    sql = "SELECT " + ", ".join(f"({exprs[l]}) AS c{i}" for i, l in enumerate(labels))
    row = session.sql(sql).collect()[0]
    return {l: int(row[i]) for i, l in enumerate(labels)}


def core_relationship_names(core):
    from relationalai.semantics import inspect

    schema = inspect.schema(core.model)
    derived = set(core.DERIVED_RELATIONSHIPS)
    names = []
    for c in schema.concepts:
        if c.name in core.DERIVED_CONCEPTS or getattr(core, c.name, None) is None:
            continue  # contract concepts, and helper concepts declared outside core.py
        for r in tuple(c.properties) + tuple(c.relationships):
            if r.is_identity or r.reading.split()[0].split(":")[0] != c.name:
                continue  # identity fields and properties inherited from a parent concept
            n = f"{c.name}.{r.name}"
            if n not in derived:
                names.append(n)
    return names


def check_engine(core, use_sql=True, derived=False):
    from relationalai.semantics.std import aggregates as aggs

    # Source-layer names are read from the schema BEFORE rules.py and graphs.py are imported: those
    # modules add private helpers (TenureOverlap, ScoreCandidate, Company.why_upto, WarmPathCandidate, ...)
    # that are not in core.py and not in the contract, and must not be checked as core relationships.
    rel_names = core_relationship_names(core)
    if derived:
        import pe_deal_graph.model.rules as rules  # (R09)
        import pe_deal_graph.model.graphs  # noqa: F401  (R10)
        rules.enable_finale()  # the finale_* contract names are opt-in; the contract check covers them too

    expected = {}
    if use_sql:
        t0 = time.time()
        expected = sql_counts(core)
        print(f"INFO  Snowflake source counts read in {time.time() - t0:.1f}s", flush=True)

    missing_spec = sorted(set(rel_names) - set(EXPECTED_FACTS))
    record(not missing_spec, "every core relationship has an expected-fact spec in validate_ontology.py",
           f"missing={missing_spec}" if missing_spec else f"{len(rel_names)} core relationships", warn=True)

    exprs = {f"concept:{n}": aggs.count(c) for n, (_, c) in core.CONCEPT_SOURCES.items()}
    exprs["concept:Organization"] = aggs.count(core.Organization)
    for n in rel_names:
        exprs[f"rel:{n}"] = fact_count_expr(resolve(core, n))
    # Same-type slots must bind two different entities (a self-pair means the slots collapsed).
    a = core.Company.ref()
    sa, ra = core.Sector.ref(), core.Region.ref()
    self_pairs = {
        "CommercialLink supplier != customer": aggs.count(core.CommercialLink).where(
            core.CommercialLink.supplier == core.CommercialLink.customer),
        "Company.supplies has no self-pairs": aggs.count(a).where(a.supplies(a)),
        "Sector.parent has no self-pairs": aggs.count(sa).where(sa.parent(sa)),
        "Region.parent has no self-pairs": aggs.count(ra).where(ra.parent(ra)),
    }
    for k, v in self_pairs.items():
        exprs[f"self:{k}"] = v
    if derived:
        for n in core.DERIVED_CONCEPTS:
            exprs[f"derived:{n}"] = aggs.count(getattr(core, n))
        for n in core.DERIVED_RELATIONSHIPS:
            exprs[f"derived:{n}"] = fact_count_expr(resolve(core, n))
    t0 = time.time()
    got = run_counts(core, exprs)
    print(f"INFO  RAI counts ({len(exprs)} aggregates) in {time.time() - t0:.1f}s", flush=True)

    for n, (table, _) in core.CONCEPT_SOURCES.items():
        g = got[f"concept:{n}"]
        if use_sql:
            e = expected[f"rows:{table}"]
            record(g == e and (e > 0 or g == 0), f"entity count {n} == {table} rows", f"rai={g} source={e}",
                   warn=(e == 0))
        else:
            record(g > 0, f"entity count {n} > 0", f"rai={g}")
    g = got["concept:Organization"]
    if use_sql:
        e = sum(expected[f"rows:{t}"] for t in core.UNION_CONCEPTS["Organization"])
        record(g == e, "entity count Organization == SPONSOR + INTERMEDIARY + COMPANY rows", f"rai={g} source={e}")
    else:
        record(g > 0, "entity count Organization > 0", f"rai={g}")

    for k in self_pairs:
        g = got[f"self:{k}"]
        record(g == 0, f"same-type slots: {k}", f"self-pairs={g}")

    for n in rel_names:
        g = got[f"rel:{n}"]
        e = expected.get(n) if use_sql else None
        if e is None:
            record(g > 0, f"facts {n} > 0", f"rai={g}")
        elif e == 0:
            record(g == 0, f"facts {n} > 0", f"rai={g} source=0 (no source values; data gap, not a binding error)",
                   warn=True)
        else:
            record(g == e, f"facts {n} > 0 and == source", f"rai={g} source={e}")

    if derived:
        optional = set(core.OPTIONAL_DERIVED)
        for n in tuple(core.DERIVED_CONCEPTS) + tuple(core.DERIVED_RELATIONSHIPS):
            g = got[f"derived:{n}"]
            record(g > 0, f"derived facts {n} > 0", f"rai={g}" + (" (optional)" if n in optional else ""),
                   warn=n in optional)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="name/mapping checks only, no Snowflake or engine")
    ap.add_argument("--derived", action="store_true", help="also require derived names to have facts (after P4)")
    ap.add_argument("--no-sql", action="store_true", help="skip Snowflake source counts")
    args = ap.parse_args()

    t0 = time.time()
    import pe_deal_graph.model.core as core

    print(f"INFO  model={core.model.name} schema={core.SOURCE_SCHEMA}", flush=True)
    check_offline(core)
    if not args.offline:
        try:
            check_engine(core, use_sql=not args.no_sql, derived=args.derived)
        except Exception as e:  # noqa: BLE001
            record(False, "engine checks ran", f"{type(e).__name__}: {str(e)[:500]}")
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    warns = [r for r in RESULTS if r[0] == "WARN"]
    verdict = "PASS" if not fails else "FAIL"
    print(f"\nONTOLOGY CHECK {verdict}: {len(RESULTS) - len(fails) - len(warns)} pass, {len(warns)} warn, "
          f"{len(fails)} fail ({time.time() - t0:.0f}s){' [offline]' if args.offline else ''}")
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
