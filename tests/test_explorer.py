"""Playwright click-through for the Deal Graph Explorer (owner: R15; G6 evidence).

Run:
    .venv/bin/python -m pytest tests/test_explorer.py -q                                   # exports/
    EXPLORER_EXPORTS=tests/fixtures/exports .venv/bin/python -m pytest tests/test_explorer.py -q

Checks: offline in headless Chromium with zero console errors and zero network requests, no
localStorage, default view ready in under 2 s, every view reachable, the warm-path click-through
(select a target, the path highlights, hop evidence shows), plus file-level checks (single file,
under 8 MB, no em dash) and the build guards.
"""

from __future__ import annotations

import subprocess

import pytest
from playwright.sync_api import sync_playwright

from test_explorer_support import (DEFAULT_EXPORTS, DELIVERABLE, FIXTURE_EXPORTS, ROOT, PageSession, build_into,
                                   exports_dir, load_builder, load_exports_json, using_default_exports)

READY_BUDGET_MS = 2000


@pytest.fixture(scope="module")
def exports():
    return load_exports_json(exports_dir())


@pytest.fixture(scope="module")
def html(tmp_path_factory):
    return build_into(tmp_path_factory.mktemp("explorer"))


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def session(browser, html):
    s = PageSession(browser, html)
    yield s
    s.close()


def _assert_clean(s: PageSession):
    assert s.errors == [], f"console errors: {s.errors}"
    assert s.network == [], f"network requests attempted: {s.network}"


# ----------------------------------------------------------------------------- file-level checks
def test_single_file_size_and_style(html):
    raw = html.read_bytes()
    assert len(raw) < 8 * 1024 * 1024, f"{len(raw)} bytes is over 8 MB"
    text = raw.decode("utf-8")
    assert "\u2014" not in text, "em dash (U+2014) found in the HTML"
    assert "<script src" not in text and "<link " not in text, "external script or stylesheet reference"
    builder = load_builder()
    for name in ("APP_JS", "CSS", "BODY"):
        src = getattr(builder, name)
        for banned in ("localStorage", "sessionStorage", "fetch(", "XMLHttpRequest", "WebSocket", "http://", "https://"):
            assert banned not in src, f"{banned!r} appears in the explorer's own {name}"


def test_builder_has_no_em_dash():
    assert "\u2014" not in (ROOT / "artifacts" / "build_explorer.py").read_text(encoding="utf-8")


def test_build_guards(tmp_path):
    builder = load_builder()
    with pytest.raises(builder.ContractError, match="exports directory not found"):
        builder.build(tmp_path / "nope", tmp_path / "x.html")
    with pytest.raises(builder.ContractError, match="refusing to write FIXTURE"):
        builder.build(FIXTURE_EXPORTS, builder.DEFAULT_OUT)


def test_make_explorer_fails_clearly_without_exports():
    r = subprocess.run(["make", "-s", "explorer", "EXPLORER_EXPORTS=/nonexistent/exports"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "exports" in (r.stderr + r.stdout) and "not found" in (r.stderr + r.stdout)


def test_deliverable_is_fresh_build(html):
    if not using_default_exports():
        pytest.skip("freshness of artifacts/deal_graph_explorer.html is only checked against exports/")
    assert DELIVERABLE.exists(), "artifacts/deal_graph_explorer.html missing; run 'make explorer'"
    assert DELIVERABLE.read_bytes() == html.read_bytes(), "artifacts/deal_graph_explorer.html is stale; run 'make explorer'"


def test_default_exports_are_not_fixture(exports):
    if not using_default_exports():
        pytest.skip("only meaningful for exports/")
    assert exports["meta"]["source"] != "FIXTURE"


# ----------------------------------------------------------------------------- browser checks
def test_offline_zero_errors_and_fast_default_view(session):
    page = session.open()
    ready_ms = page.evaluate("window.__explorer.readyMs")
    assert ready_ms is not None and ready_ms < READY_BUDGET_MS, f"default view ready at {ready_ms} ms (budget {READY_BUDGET_MS})"
    assert page.evaluate("document.querySelector('#view-overview canvas') !== null"), "default view has no graph canvas"
    page.wait_for_timeout(300)
    _assert_clean(session)


def test_all_views_reachable(session, exports):
    page = session.open()
    views = page.evaluate("window.__explorer.views")
    hidden = page.evaluate("window.__explorer.hiddenViews")
    expected = {"overview", "score", "path", "flow"} | ({"conflict"} if "q_conflict" in exports else set())
    assert expected <= set(views), f"nav views {views} miss {expected - set(views)}"
    for v in views:
        page.click(f"#tab-{v}")
        page.wait_for_selector(f"#view-{v}:not([hidden]) .panel", timeout=5000)
        assert page.is_visible(f"#view-{v}")
        assert page.evaluate(f"document.querySelector('#view-{v}').textContent.length") > 50
    for v in hidden:
        page.evaluate(f"window.__explorer.show('{v}')")
        page.wait_for_selector(f"#view-{v}:not([hidden]) .panel", timeout=5000)
    for v in views + hidden:  # deep links work too
        session.open(v)
        assert page.is_visible(f"#view-{v}")
    _assert_clean(session)


def test_warm_path_click_through(session, exports):
    """Select a target -> its paths highlight -> the hop evidence shows."""
    page = session.open()
    page.click("#tab-path")
    q = exports["q_path"]
    for t in q["targets"]:
        page.click(f"[data-target='{t['company_id']}']")
        page.wait_for_timeout(150)
        best = [dm["paths"][0] for dm in t["decision_makers"] if dm["status"] == "warm" and dm["paths"]]
        hl = page.evaluate("window.__explorer.cys.path.edges('.path-best').map(e => e.id())")
        assert sorted(hl) == sorted({hp["edge_id"] for p in best for hp in p["hops"]}), f"{t['company_id']}: highlighted {hl}"
        ev = page.inner_text("#path-evidence")
        assert t["company_name"] in ev
        for p in best:
            card = page.locator(f"#path-evidence [data-path='{p['path_id']}']")
            assert card.count() == 1
            assert card.locator(".hop").count() == len(p["hops"])
            for hp in p["hops"]:
                assert hp["evidence"] in card.inner_text(), f"missing hop evidence: {hp['evidence']}"
        for dm in t["decision_makers"]:
            assert page.locator(f"#path-evidence [data-person='{dm['person_id']}']").count() == 1
            if dm["status"] == "cold":
                assert page.locator(f"#path-evidence [data-person='{dm['person_id']}'] [data-cold]").count() == 1
        assert page.locator("#path-evidence [data-claim]").count() == len(t["rejected_claims"])
        for rc in t["rejected_claims"]:
            if rc.get("edge_id"):
                assert page.evaluate(f"window.__explorer.cys.path.getElementById('{rc['edge_id']}').hasClass('rejected-on')")
        if t.get("next_step"):
            page.click("#path-next")
            page.wait_for_selector("#view-flow:not([hidden])")
            assert page.evaluate("window.__explorer.state.flow") == t["next_step"]["node_id"]
            page.click("#tab-path")
    _assert_clean(session)


def test_scorecard(session, exports):
    page = session.open("score")
    q = exports["q_score"]
    tier_a = [r for r in q["rows"] if r["tier"] == "A"]
    assert page.locator("#score-list .sc-row").count() == len(tier_a)
    assert page.locator("#score-list [data-badge='not-in-crm']").count() == sum(not r["in_crm"] for r in tier_a)
    first = tier_a[0]["company_id"]
    page.click(f"#score-list .sc-row[data-company='{first}']")
    assert page.locator(f"#score-list .sc-detail[data-company='{first}'] .comp").count() == len(q["components"])
    page.click(f"#score-list .sc-detail[data-company='{first}'] .comp .lbl >> nth=0")
    assert page.locator("#sc-rule .rule-card").count() == 1
    page.click("#score-naive")
    assert page.is_visible("#score-naive-panel")
    if q.get("finale"):
        page.click("#score-finale")
        assert page.locator("#score-list .sc-row").count() >= 1
        for r in q["finale"]["rows"]:
            if r["conflict"]:
                assert page.locator(f"#score-list .sc-row[data-company='{r['company_id']}'] .tier-Conflict").count() == 1
    _assert_clean(session)


def test_global_search_expand_and_toggles(session, exports):
    page = session.open()
    g = exports["graph"]
    node = next((n for n in g["nodes"] if "tier_a" in n["tags"]), g["nodes"][0])
    page.fill("#search", node["label"][:30])
    page.click(f"#search-results button[data-node='{node['id']}']")
    assert page.evaluate("window.__explorer.state.ovSel") == node["id"]
    assert node["label"] in page.inner_text("#ov-sel")
    page.click("#hop1")
    n_hl = page.evaluate("window.__explorer.cys.overview.nodes('.hl').length")
    deg = len({e["source"] for e in g["edges"] if e["target"] == node["id"]} | {e["target"] for e in g["edges"] if e["source"] == node["id"]})
    assert n_hl == deg + 1
    page.click("#hop2")
    assert page.evaluate("window.__explorer.cys.overview.nodes('.hl').length") >= n_hl
    page.uncheck("[data-edge-type='tenure'] input")
    assert page.evaluate("window.__explorer.cys.overview.edges('[type = \"tenure\"]').every(e => e.hasClass('off'))")
    if g["edges"]:
        e = g["edges"][0]
        etype = next(t for t in g["edge_types"] if t["id"] == e["type"])
        page.evaluate(f"window.__explorer.api.overviewEdge('{e['id']}')")
        assert page.locator("#ov-rule .rule-card").count() == (1 if (e.get("rule_id") or etype.get("rule_id")) else 0)
        assert e["evidence"] in page.inner_text("#ov-sel")
    page.click("#reset")
    _assert_clean(session)


def test_deal_flow(session, exports):
    page = session.open("flow")
    q = exports["q_flow"]
    for it in q["intermediaries"]:
        page.click(f"#flow-table tr[data-org='{it['org_id']}']")
        assert it["name"] in page.inner_text("#flow-detail")
        assert page.locator("#flow-deals li").count() == len(it["deal_ids"])
    gaps = [it for it in q["intermediaries"] if it["is_gap"]]
    assert page.locator("#flow-table [data-badge='gap']").count() == len(gaps)
    page.click("#flow-league")
    assert page.is_visible("#flow-sql")
    _assert_clean(session)


def test_conflict_check(session, exports):
    if "q_conflict" not in exports:
        pytest.skip("q_conflict.json not exported")
    page = session.open("conflict")
    q = exports["q_conflict"]
    assert page.locator("#cf-hits [data-exposure]").count() == len(q["exposures"])
    assert page.locator("#cf-ctx [data-context]").count() == len(q["context"])
    assert page.locator("#cf-gauge .area-row").count() == len(q["concentration"]["areas"])
    for x in q["exposures"]:
        cls = "conflict" if x["kind"] == "conflict" else "info"
        for eid in x["edge_ids"]:
            assert page.evaluate(f"window.__explorer.cys.conflict.getElementById('{eid}').hasClass('{cls}')")
    _assert_clean(session)


def test_addon_backup_view(session, exports):
    if "q_addon" not in exports:
        pytest.skip("q_addon.json not exported")
    page = session.open("addon")
    for c in exports["q_addon"]["candidates"]:
        page.click(f"#addon-table tr[data-candidate='{c['company_id']}']")
        assert page.locator("#addon-shared li").count() == len(c["shared_neighbors"])
    _assert_clean(session)
