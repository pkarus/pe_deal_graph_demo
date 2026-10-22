"""Automated numbers check for the Deal Graph Explorer (owner: R15; the G6 "every number equals
exports/" diff).

How it works: the explorer renders every exported value through one formatter and tags the element
with data-src="<file stem>:<JSON pointer>|<format>"; canvas labels are logged in
window.__explorer.registry with the same sources. This test drives the page through every view
and every selectable state, then for each rendered value resolves the pointer in exports/*.json,
formats it with build_explorer.format_value (the Python mirror of the JS formatter) and diffs the
text. It also fails on any digit on screen that is not tagged as an export value (data-src) or as
static UI text (data-static), so no number can be typed by hand.

Run:
    .venv/bin/python -m pytest tests/test_explorer_numbers.py -q
    EXPLORER_EXPORTS=tests/fixtures/exports .venv/bin/python -m pytest tests/test_explorer_numbers.py -q
"""

from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from test_explorer_support import (COLLECT_JS, SRC_RE, PageSession, build_into, exports_dir, load_builder,
                                   load_exports_json)

MAX_GLOBAL_SELECTIONS = 60


@pytest.fixture(scope="module")
def harvest(tmp_path_factory):
    """Visit every state and return (values, unattributed digit strings, canvas registry, exports)."""
    exp = load_exports_json(exports_dir())
    html = build_into(tmp_path_factory.mktemp("explorer_numbers"))
    values: dict[str, str] = {}
    conflicts: list[str] = []
    bad: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        s = PageSession(browser, html)
        page = s.open()

        def collect(state):
            got = page.evaluate(COLLECT_JS)
            for src, text in got["vals"]:
                if src in values and values[src] != text:
                    conflicts.append(f"{state}: {src} rendered as {values[src]!r} and {text!r}")
                values[src] = text
            for b in got["bad"]:
                bad.add(f"{state}: {b}")
            return got["reg"]

        collect("overview")
        g = exp["graph"]
        tagged = [n["id"] for n in g["nodes"] if n["tags"]]
        rest = [n["id"] for n in g["nodes"] if not n["tags"]]
        for nid in (tagged + rest)[:MAX_GLOBAL_SELECTIONS]:
            page.evaluate("id => window.__explorer.api.overview(id)", nid)
            collect(f"overview node {nid}")
        for e in g["edges"][:MAX_GLOBAL_SELECTIONS]:
            page.evaluate("id => window.__explorer.api.overviewEdge(id)", e["id"])
            collect(f"overview edge {e['id']}")

        page.evaluate("window.__explorer.show('score')")
        page.evaluate("window.__explorer.api.score({all: true, naive: true, expandAll: true})")
        collect("score act1")
        if exp["q_score"].get("finale"):
            page.evaluate("window.__explorer.api.score({mode: 'finale'})")
            page.evaluate("window.__explorer.api.score({all: true, expandAll: true})")
            collect("score finale")

        page.evaluate("window.__explorer.show('path')")
        for t in exp["q_path"]["targets"]:
            page.evaluate("id => window.__explorer.api.path(id)", t["company_id"])
            collect(f"path {t['company_id']}")

        page.evaluate("window.__explorer.show('flow')")
        page.click("#flow-league")
        for it in exp["q_flow"]["intermediaries"]:
            page.evaluate("id => window.__explorer.api.flow(id)", it["org_id"])
            collect(f"flow {it['org_id']}")

        if "q_conflict" in exp:
            page.evaluate("window.__explorer.show('conflict')")
            collect("conflict")
        if "q_addon" in exp:
            page.evaluate("window.__explorer.show('addon')")
            for c in exp["q_addon"]["candidates"]:
                page.evaluate("id => window.__explorer.api.addon(id)", c["company_id"])
                collect(f"addon {c['company_id']}")

        registry = page.evaluate("window.__explorer.registry")
        errors = list(s.errors)
        s.close()
        browser.close()
    return {"values": values, "conflicts": conflicts, "bad": sorted(bad), "registry": registry, "exports": exp, "errors": errors}


def _check(src: str, text: str, exp: dict, fmt_value) -> str | None:
    m = SRC_RE.match(src)
    if not m:
        return f"malformed data-src {src!r}"
    if m["file"] not in exp:
        return f"{src}: no {m['file']}.json in exports"
    builder = load_builder()
    try:
        raw = builder.resolve_pointer(exp[m["file"]], m["ptr"])
    except (KeyError, IndexError, ValueError, TypeError):
        return f"{src}: pointer does not resolve in exports"
    want = fmt_value(raw, m["fmt"])
    if want != text:
        return f"{src}: page shows {text!r}, exports give {want!r}"
    return None


def test_every_rendered_value_equals_exports(harvest):
    fmt_value = load_builder().format_value
    exp = harvest["exports"]
    assert len(harvest["values"]) > 100, "too few tagged values were rendered; is the page empty?"
    problems = [p for src, text in harvest["values"].items() if (p := _check(src, text, exp, fmt_value))]
    problems += harvest["conflicts"]
    assert not problems, f"{len(problems)} value(s) differ from exports/:\n" + "\n".join(problems[:50])


def test_every_canvas_label_equals_exports(harvest):
    fmt_value = load_builder().format_value
    exp = harvest["exports"]
    problems = []
    for entry in harvest["registry"]:
        for part in entry["parts"]:
            if (p := _check(part["src"], part["text"], exp, fmt_value)):
                problems.append(p)
    assert harvest["registry"], "no canvas labels were registered"
    assert not problems, f"{len(problems)} canvas label part(s) differ from exports/:\n" + "\n".join(problems[:50])


def test_no_untagged_numbers_on_screen(harvest):
    assert not harvest["bad"], ("digits rendered without an export source (data-src) or a static tag:\n"
                                + "\n".join(harvest["bad"][:50]))


def test_hero_numbers_are_on_screen(harvest):
    """Coverage: the hero answers themselves are rendered, not just checked when present."""
    v, exp = harvest["values"], harvest["exports"]
    need = []
    for i, r in enumerate(exp["q_score"]["rows"]):
        if r["tier"] == "A":
            need += [f"q_score:/rows/{i}/score|int", f"q_score:/rows/{i}/rank|int"]
    for i, t in enumerate(exp["q_path"]["targets"]):
        for d, dm in enumerate(t["decision_makers"]):
            for j, _ in enumerate(dm["paths"]):
                need.append(f"q_path:/targets/{i}/decision_makers/{d}/paths/{j}/strength|f3")
    for i, _ in enumerate(exp["q_flow"]["intermediaries"]):
        need += [f"q_flow:/intermediaries/{i}/betweenness|f1", f"q_flow:/intermediaries/{i}/touchpoints_24m|int"]
    for q in ("Q-SCORE", "Q-PATH", "Q-FLOW", "Q-CONFLICT"):
        if q in exp["sql_baseline"]["questions"] and (q != "Q-CONFLICT" or "q_conflict" in exp):
            need.append(f"sql_baseline:/questions/{q}/row_count|int")
    if "q_conflict" in exp:
        for i, a in enumerate(exp["q_conflict"]["concentration"]["areas"]):
            need.append(f"q_conflict:/concentration/areas/{i}/before_pct|pct1")
            if a["after_pct"] != a["before_pct"]:
                need.append(f"q_conflict:/concentration/areas/{i}/after_pct|pct1")
        need += ["q_conflict:/concentration/guideline_pct|pct1", "q_conflict:/concentration/headroom_musd|musd1"]
    missing = [n for n in need if n not in v]
    assert not missing, "hero numbers not rendered:\n" + "\n".join(missing)


def test_no_console_errors_during_traversal(harvest):
    assert harvest["errors"] == []
