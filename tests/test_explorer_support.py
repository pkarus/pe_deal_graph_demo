"""Shared helpers for the Deal Graph Explorer tests (owner: R15). Holds no tests itself.

Input selection (the fixture is never the default):
- EXPLORER_EXPORTS: exports directory to build from. Default: <repo>/exports. If it is missing the
  tests fail with a clear message. For development before R13 runs, use
  EXPLORER_EXPORTS=tests/fixtures/exports.
- EXPLORER_HTML: test this prebuilt HTML instead of building a fresh copy into a temp dir.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILDER_PATH = ROOT / "artifacts" / "build_explorer.py"
DEFAULT_EXPORTS = ROOT / "exports"
FIXTURE_EXPORTS = ROOT / "tests" / "fixtures" / "exports"
DELIVERABLE = ROOT / "artifacts" / "deal_graph_explorer.html"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_explorer", BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def exports_dir() -> Path:
    raw = os.environ.get("EXPLORER_EXPORTS")
    d = Path(raw) if raw else DEFAULT_EXPORTS
    if not d.is_absolute():
        d = ROOT / d
    if not d.is_dir():
        pytest.fail(f"exports directory not found: {d}. Run 'make export' (R13) first, or set "
                    f"EXPLORER_EXPORTS=tests/fixtures/exports to test against the FIXTURE set.", pytrace=False)
    return d


def using_default_exports() -> bool:
    return exports_dir().resolve() == DEFAULT_EXPORTS.resolve()


def load_exports_json(d: Path) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))}


def build_into(tmp_dir: Path) -> Path:
    raw = os.environ.get("EXPLORER_HTML")
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else ROOT / p
    builder = load_builder()
    out = tmp_dir / "deal_graph_explorer.html"
    builder.build(exports_dir(), out)
    return out


LOCALSTORAGE_TRAP = """
(() => {
  const trap = { get() { throw new Error('localStorage is not allowed in the explorer'); } };
  try { Object.defineProperty(window, 'localStorage', trap); } catch (e) {}
  try { Object.defineProperty(window, 'sessionStorage', trap); } catch (e) {}
})();
"""


class PageSession:
    """Opens the explorer offline: every non-file request is aborted and recorded,
    localStorage access throws, console errors and page errors are collected."""

    def __init__(self, browser, html: Path, viewport=(1440, 900)):
        self.context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, service_workers="block")
        self.context.add_init_script(LOCALSTORAGE_TRAP)
        self.network: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

        def route(r):
            url = r.request.url
            if url.startswith("file://") or url.startswith("data:") or url.startswith("about:"):
                r.continue_()
            else:
                self.network.append(url)
                r.abort()

        self.context.route("**/*", route)
        self.page = self.context.new_page()
        self.page.on("console", self._console)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.url = html.resolve().as_uri()

    def _console(self, msg):
        if msg.type == "error":
            self.errors.append(f"console.error: {msg.text}")
        elif msg.type == "warning":
            self.warnings.append(msg.text)

    def open(self, fragment: str = ""):
        self.page.goto(self.url + (("#" + fragment) if fragment else ""))
        self.page.wait_for_function("window.__explorer && window.__explorer.ready === true", timeout=15000)
        return self.page

    def close(self):
        self.context.close()


COLLECT_JS = r"""
() => {
  const vals = [];
  document.querySelectorAll('[data-src]').forEach(el => vals.push([el.getAttribute('data-src'), el.textContent]));
  const bad = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!/[0-9]/.test(n.nodeValue)) continue;
    const p = n.parentElement;
    if (!p || p.closest('script,style')) continue;
    if (p.closest('[data-src],[data-static]')) continue;
    bad.push(n.nodeValue.trim().slice(0, 120));
  }
  return { vals: vals, bad: bad, reg: window.__explorer.registry };
}
"""

SRC_RE = re.compile(r"^(?P<file>[a-z_]+):(?P<ptr>[^|]*)\|(?P<fmt>[a-z0-9]+)$")
