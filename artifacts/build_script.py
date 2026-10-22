#!/usr/bin/env python3
"""Build the demo run-of-show, artifacts/demo_script.html (owner: R16 Script Writer).

Inputs (read-only):
    artifacts/demo_script_template.html   prose, one block per question ID
    exports/*.json                         every number shown (R13, live RAI)
    data/golden/stories.md                 story cards (R05), appendix
    demo_workspace/prompts.md              exact prompts to type (R14)
    research/domain_brief.md               vocabulary, skeptic Q&A (R02)
    ONTOLOGY.md                            mermaid diagram, optional (R08)

Rules this builder enforces:
    * Every number is injected from exports by key path ({{ expr | fmt }}). The template itself
      may not contain a digit outside its <style> block; the build fails if it does.
    * A missing key, an empty selector or a null where a value is required fails the build.
    * After writing, the output is re-checked: every injected value is re-resolved against
      exports and compared, any other visible digit outside an exempt source block fails,
      and so does any em dash (U+2014).

Usage:
    .venv/bin/python artifacts/build_script.py              # exports/ -> artifacts/demo_script.html
    .venv/bin/python artifacts/build_script.py --fixture    # fixtures -> tests/fixtures/script/out/demo_script_FIXTURE.html
    .venv/bin/python artifacts/build_script.py --check-only [--fixture]   # re-verify an existing output

Expression syntax inside {{ }}:
    file.key.key[0].key                    dict keys and list indexes (negative allowed)
    file.list[field=value]                 filter a list (also !=); value may be true/false/null,
                                           a number, a string, or {another.expression}
    expr | fmt | fmt                       formatters, see FORMATTERS
    @q.  -> the current question's export file    @sql. -> sql_baseline.questions.<QID>.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "artifacts" / "demo_script_template.html"
PROMPTS = ROOT / "demo_workspace" / "prompts.md"
QUESTIONS_MD = ROOT / "QUESTIONS.md"
BRIEF = ROOT / "research" / "domain_brief.md"
ONTOLOGY = ROOT / "ONTOLOGY.md"
REAL_EXPORTS = ROOT / "exports"
REAL_STORIES = ROOT / "data" / "golden" / "stories.md"
REAL_OUT = ROOT / "artifacts" / "demo_script.html"
FIX_EXPORTS = ROOT / "tests" / "fixtures" / "exports"           # R15's fixture set
FIX_DIR = ROOT / "tests" / "fixtures" / "script"
FIX_EXTRA = FIX_DIR / "exports_extra"                           # R16 keys R15's fixture lacks
FIX_STORIES = FIX_DIR / "stories.md"
FIX_OUT = FIX_DIR / "out" / "demo_script_FIXTURE.html"

EM_DASH = "\u2014"

# Per question: export file, ask.py function, explorer view (RUNBOOK.md act table, PROMPT.md 7.4).
QUESTIONS = {
    "Q-SCORE": {"file": "q_score", "fn": "q_score", "view": "Scorecard", "reasoner": "Rules"},
    "Q-PATH": {"file": "q_path", "fn": "q_path", "view": "Warm path", "reasoner": "Graph and rules"},
    "Q-ADDON": {"file": "q_addon", "fn": "q_addon", "view": "Add-on map", "reasoner": "Graph"},
    "Q-CONFLICT": {"file": "q_conflict", "fn": "q_conflict", "view": "Conflict check",
                   "reasoner": "Graph and rules"},
    "Q-FLOW": {"file": "q_flow", "fn": "q_flow", "view": "Deal flow", "reasoner": "Graph and rules"},
    "FINALE": {"file": "q_score", "fn": "finale_rescore", "view": "Scorecard, Finale toggle",
               "reasoner": "Rules composing graph output"},
}
ORDER_ADDON = ["Q-SCORE", "Q-PATH", "Q-ADDON", "Q-FLOW"]          # QUESTIONS.md v1 (PROMPT.md 7.3)
ORDER_CONFLICT = ["Q-SCORE", "Q-PATH", "Q-FLOW", "Q-CONFLICT"]    # QUESTIONS.md v2 (default)
# PROMPT.md 7.5 minutes. Acts are timed by position, so a swap keeps the 15-18 minute arc.
MINUTES = {"COLD_OPEN": 1, "MODEL": 2, "ACT": [3, 3, 3, 2], "FINALE": 3, "CLOSE": 1}
REQUIRED_FILES = ["meta", "q_score", "q_path", "q_flow", "sql_baseline", "graph", "rules"]


class BuildError(Exception):
    pass


def fail(msg: str) -> None:
    raise BuildError(msg)


# --------------------------------------------------------------------------- data loading

def deep_merge(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_exports(exports_dir: Path, extra_dir: Path | None) -> dict:
    if not exports_dir.is_dir():
        fail(f"exports directory not found: {exports_dir} (R13 writes it with `make export`)")
    data = {}
    for p in sorted(exports_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail(f"{p}: invalid JSON: {e}")
    if extra_dir is not None and extra_dir.is_dir():
        for p in sorted(extra_dir.glob("*.json")):
            deep_merge(data.setdefault(p.stem, {}), json.loads(p.read_text(encoding="utf-8")))
    missing = [f for f in REQUIRED_FILES if f not in data]
    if missing:
        fail(f"exports missing required files: {', '.join(m + '.json' for m in missing)} in {exports_dir}")
    return data


def act_order(data: dict, override: str | None) -> list[str]:
    if override:
        order = [q.strip() for q in override.split(",") if q.strip()]
    elif isinstance(data["meta"].get("act_order"), list):
        order = list(data["meta"]["act_order"])
    elif data["meta"].get("act3") == "q_addon":
        order = ORDER_ADDON
    else:
        order = ORDER_CONFLICT
    for q in order:
        if q not in QUESTIONS or q == "FINALE":
            fail(f"unknown act question id in act order: {q}")
        if QUESTIONS[q]["file"] not in data:
            fail(f"act {q} needs exports/{QUESTIONS[q]['file']}.json, which is missing")
    if len(order) != len(MINUTES["ACT"]):
        fail(f"act order must have {len(MINUTES['ACT'])} questions, got {order}")
    return order


# --------------------------------------------------------------------------- expressions

def _split_path(expr: str) -> list[tuple[str, str]]:
    """Split 'a.b[0][x={c.d[1]}].e' into [('key','a'),('key','b'),('sel','0'),('sel','x={...}'),('key','e')]."""
    out, i, n, buf = [], 0, len(expr), ""
    while i < n:
        c = expr[i]
        if c == ".":
            if buf:
                out.append(("key", buf))
                buf = ""
            i += 1
        elif c == "[":
            if buf:
                out.append(("key", buf))
                buf = ""
            depth_b, depth_c, j = 1, 0, i + 1
            while j < n:
                if expr[j] == "{":
                    depth_c += 1
                elif expr[j] == "}":
                    depth_c -= 1
                elif expr[j] == "[" and depth_c == 0:
                    depth_b += 1
                elif expr[j] == "]" and depth_c == 0:
                    depth_b -= 1
                    if depth_b == 0:
                        break
                j += 1
            if j >= n:
                fail(f"unbalanced [ in expression: {expr}")
            out.append(("sel", expr[i + 1:j].strip()))
            i = j + 1
        else:
            buf += c
            i += 1
    if buf:
        out.append(("key", buf))
    return out


def _literal_match(actual, lit: str, data: dict) -> bool:
    lit = lit.strip()
    if lit.startswith("{") and lit.endswith("}"):
        target = resolve(lit[1:-1].strip(), data)
        return actual == target
    low = lit.lower()
    if isinstance(actual, bool) or low in ("true", "false"):
        return isinstance(actual, bool) and actual == (low == "true")
    if low == "null":
        return actual is None
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        try:
            return math.isclose(float(actual), float(lit), abs_tol=1e-9)
        except ValueError:
            return False
    return actual is not None and str(actual) == lit


def resolve(expr: str, data: dict):
    cur, seen = data, ""
    for kind, tok in _split_path(expr):
        if kind == "key":
            if not isinstance(cur, dict):
                fail(f"missing key '{tok}' in {expr}: {seen or '<root>'} is not an object")
            if tok not in cur:
                fail(f"missing key: {seen + '.' if seen else ''}{tok}  (full path: {expr})")
            cur = cur[tok]
            seen = f"{seen}.{tok}" if seen else tok
        else:
            if not isinstance(cur, list):
                fail(f"selector [{tok}] in {expr}: {seen} is not a list")
            if re.fullmatch(r"-?\d+", tok):
                idx = int(tok)
                if not -len(cur) <= idx < len(cur):
                    fail(f"index [{idx}] out of range at {seen} (length {len(cur)}) in {expr}")
                cur = cur[idx]
            else:
                m = re.fullmatch(r"([A-Za-z_][\w]*)\s*(!=|=)\s*(.+)", tok, re.S)
                if not m:
                    fail(f"bad selector [{tok}] in {expr}")
                field, op, lit = m.groups()
                res = []
                for el in cur:
                    if not isinstance(el, dict) or field not in el:
                        fail(f"selector [{tok}] in {expr}: element of {seen} has no key '{field}'")
                    hit = _literal_match(el[field], lit, data)
                    if hit == (op == "="):
                        res.append(el)
                cur = res
            seen = f"{seen}[{tok}]"
    return cur


def _num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(f"formatter '{name}' needs a number, got {v!r}")
    return v


def _need(v, name):
    if v is None:
        fail(f"formatter '{name}' got null")
    return v


def _hops(path, name):
    if not isinstance(path, dict) or not isinstance(path.get("hops"), list) or not path["hops"]:
        fail(f"formatter '{name}' needs a path object with a non-empty 'hops' list")
    return path["hops"]


FORMATTERS = {
    "int": lambda v: f"{int(round(_num(v, 'int'))):,}",
    "f1": lambda v: f"{_num(v, 'f1'):.1f}",
    "f2": lambda v: f"{_num(v, 'f2'):.2f}",
    "f3": lambda v: f"{_num(v, 'f3'):.3f}",
    "f4": lambda v: f"{_num(v, 'f4'):.4f}",
    "pct": lambda v: f"{_num(v, 'pct'):.1f}%",          # value already in percent
    "musd": lambda v: f"${_num(v, 'musd'):,.1f}M",
    "text": lambda v: str(_need(v, "text")),
    "opt": lambda v: "-" if v is None else str(v),
    "year": lambda v: "present" if v is None else str(v)[:4],
    "date": lambda v: "present" if v is None else str(v),
    "yesno": lambda v: "yes" if v else "no",
    "list": lambda v: ", ".join(str(x) for x in v) if v else "none",
    "len": lambda v: len(v),
    "via": lambda p: ", then ".join(h["to_name"] for h in _hops(p, "via")[:-1]) or "a direct tie",
    "chain": lambda p: " > ".join([_hops(p, "chain")[0]["from_name"]] + [h["to_name"] for h in p["hops"]]),
    "seed": lambda p: _hops(p, "seed")[0]["from_name"],
}


def apply_fmt(value, chain: list[str]) -> str:
    for f in chain:
        if f not in FORMATTERS:
            fail(f"unknown formatter '{f}'")
        value = FORMATTERS[f](value)
    if not chain or not isinstance(value, str):
        if value is None:
            fail("value is null and no formatter handles null (use | opt)")
        if isinstance(value, bool):
            value = "yes" if value else "no"
        elif isinstance(value, int):
            value = f"{value:,}"
        elif isinstance(value, float):
            if value.is_integer():
                value = f"{int(value):,}"
            else:
                fail(f"float {value} needs an explicit formatter (f1, f2, f3, pct, musd)")
        elif isinstance(value, (list, dict)):
            fail(f"a list or object cannot be shown directly; add a formatter (got {str(value)[:60]})")
    return str(value)


class Ctx:
    """Rendering context: data plus counters for the build report."""

    def __init__(self, data: dict):
        self.data = data
        self.n_values = 0
        self.keys: set[str] = set()

    def v(self, expr: str, fmt: str = "") -> str:
        chain = [f.strip() for f in fmt.split("|") if f.strip()]
        text = apply_fmt(resolve(expr, self.data), chain)
        self.n_values += 1
        self.keys.add(normalize_key(expr))
        return (f'<span class="v" data-k="{html.escape(expr, quote=True)}" '
                f'data-f="{html.escape("|".join(chain), quote=True)}">{html.escape(text)}</span>')

    def lit(self, value, kind: str) -> str:
        return f'<span class="lit" data-lit="{kind}">{html.escape(str(value))}</span>'


def normalize_key(expr: str) -> str:
    """Key path with list positions and filters collapsed, for the handoff's consumed-key list."""
    expr = re.sub(r"\{[^{}]*\}", "{..}", expr)
    expr = re.sub(r"\[-?\d+\]", "[]", expr)
    expr = re.sub(r"\[([A-Za-z_]\w*)\s*(!=|=)[^\]]*\]", r"[\1\2..]", expr)
    return expr


# --------------------------------------------------------------------------- source documents

def load_prompts() -> tuple[dict, str]:
    """prompts.md (R14) is the source once it is no longer DRAFT v1; until then QUESTIONS.md v2."""
    if PROMPTS.exists() and "DRAFT v1" not in PROMPTS.read_text(encoding="utf-8"):
        p = parse_prompts(PROMPTS, "## ")
        src = "demo_workspace/prompts.md"
        if QUESTIONS_MD.exists():
            q = parse_prompts(QUESTIONS_MD, "### ")
            for qid, e in p.items():
                if qid in q and q[qid].get("tier1") != e.get("tier1"):
                    print(f"build_script: WARNING - Tier-1 prompt for {qid} differs between prompts.md "
                          "and QUESTIONS.md; using prompts.md", file=sys.stderr)
        return p, src
    if not QUESTIONS_MD.exists():
        fail("neither a synced demo_workspace/prompts.md nor QUESTIONS.md is available for prompts")
    q = parse_prompts(QUESTIONS_MD, "### ")
    return q, "QUESTIONS.md"


def parse_prompts(path: Path, heading: str) -> dict:
    if not path.exists():
        fail(f"prompts file not found: {path} (R14)")
    text = path.read_text(encoding="utf-8")
    sections = re.split(rf"(?m)^{re.escape(heading)}", text)[1:]
    out = {}
    for sec in sections:
        head, _, body = sec.partition("\n")
        if head.lower().startswith("finale"):
            qid = "FINALE"
        else:
            m = re.search(r"Q-[A-Z]+", head)
            if not m:
                continue
            qid = m.group(0)
        entry, label = {}, None
        quote: list[str] = []

        def flush():
            if quote and label and label not in entry:
                entry[label] = " ".join(q.strip() for q in quote).strip()

        for line in body.splitlines():
            s = line.strip()
            if s.startswith(">"):
                if label:
                    quote.append(s[1:].strip())
                continue
            if quote:
                flush()
                quote = []
                label = None
            low = s.lstrip("*").lower()
            if (low.startswith("tier-1") or low.startswith("tier-2 rule")
                    or low.startswith("prompt the presenter types")):
                label = "tier1"
            elif low.startswith("paraphrase"):
                label = "para"
            elif low.startswith("tier-2"):
                label = "tier2"
                m = re.search(r'"([^"]+)"', s)               # QUESTIONS.md: suggestion inline in quotes
                if m and "tier2" not in entry:
                    entry["tier2"] = m.group(1)
            elif label == "tier2" and "tier2" not in entry:
                m = re.match(r'^-\s*"([^"]+)"', s)          # QUESTIONS.md: suggestions as bullets
                if m:
                    entry["tier2"] = m.group(1)
            elif s and not s.startswith("-"):
                label = None
        flush()
        if qid not in out and "tier1" in entry:
            out[qid] = entry
    return out


def _inline_md(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _strip_cites(s: str) -> str:
    return re.sub(r"\s*\[\d+\](\[\d+\])*", "", s)


def parse_brief(path: Path) -> dict:
    if not path.exists():
        fail(f"domain brief not found: {path} (R02)")
    text = path.read_text(encoding="utf-8")

    def section(num: int) -> str:
        m = re.search(rf"(?ms)^## {num}\..*?$(.*?)(?=^## |\Z)", text)
        if not m:
            fail(f"domain brief section {num} not found")
        return m.group(1)

    vocab = []
    for line in section(1).splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line) and not line.startswith("| Say"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2:
                vocab.append(cells + [""] * (3 - len(cells)))
    if not vocab:
        fail("domain brief section 1 has no vocabulary table rows")
    m = re.search(r'\*\*"Affinity already does this\."\*\*\s*(.+)', section(3))
    if not m:
        fail('domain brief section 3 has no **"Affinity already does this."** paragraph')
    affinity = _strip_cites(m.group(1).strip())
    qa = []
    for m in re.finditer(r'(?m)^\d+\.\s+\*\*"?(.+?)"?\*\*\s*(.+)$', section(4)):
        qa.append((m.group(1).strip().strip('"'), _strip_cites(m.group(2).strip())))
    if len(qa) < 3:
        fail(f"domain brief section 4: expected 3 skeptic questions, found {len(qa)}")
    return {"vocab": vocab, "affinity": affinity, "qa": qa}


def md_to_html(text: str) -> str:
    """Small Markdown subset: headings, bullets, numbered lists, pipe tables, paragraphs."""
    out, para, lst, table = [], [], None, []

    def close():
        nonlocal para, lst, table
        if para:
            out.append("<p>" + _inline_md(" ".join(para)) + "</p>")
            para = []
        if lst:
            tag, items = lst
            out.append(f"<{tag}>" + "".join(f"<li>{_inline_md(i)}</li>" for i in items) + f"</{tag}>")
            lst = None
        if table:
            rows = [r for r in table if not re.match(r"^\|\s*:?-", r)]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            if cells:
                h = "".join(f"<th>{_inline_md(c)}</th>" for c in cells[0])
                b = "".join("<tr>" + "".join(f"<td>{_inline_md(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
                out.append(f'<div class="tw"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>')
            table = []

    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip():
            close()
            continue
        if s.startswith("|"):
            if para or lst:
                close()
            table.append(s)
            continue
        if table:
            close()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            close()
            level = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{level}>{_inline_md(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)", s)
        if m:
            if para:
                close()
            if lst and lst[0] != "ul":
                close()
            lst = lst or ("ul", [])
            lst[1].append(m.group(1))
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)", s)
        if m:
            if para:
                close()
            if lst and lst[0] != "ol":
                close()
            lst = lst or ("ol", [])
            lst[1].append(m.group(1))
            continue
        if lst and line.startswith("  "):
            lst[1][-1] += " " + s.strip()
            continue
        if lst:
            close()
        para.append(s.strip())
    close()
    return "\n".join(out)


NUM_TOKEN = re.compile(r"(?<![A-Za-z_\d.])\d[\d,]*(?:\.\d+)?")


def _forms(tok: str) -> set[str]:
    t = tok.replace(",", "")
    if "." in t:
        return {t, t.rstrip("0").rstrip(".")}
    try:
        return {str(int(t))}
    except ValueError:
        return {t}


def export_number_set(data) -> set[str]:
    found: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, bool) or o is None:
            return
        elif isinstance(o, (int, float)):
            for d in range(0, 5):
                found.update(_forms(f"{o:.{d}f}"))
            found.update(_forms(repr(o)))
        elif isinstance(o, str):
            for t in NUM_TOKEN.findall(o):
                found.update(_forms(t))

    walk(data)
    return found


WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"build_script: WARNING - {msg}", file=sys.stderr)


def unverified_numbers(text: str, known: set[str]) -> list[str]:
    return [tok for tok in NUM_TOKEN.findall(text) if not (_forms(tok) & known)]


def load_stories(path: Path, data: dict, want: bool) -> dict:
    """Story cards (R05). Returns {'why': {qid: text}, 'appendix': html}.

    The per-act "why it matters to a partner" line is used when its numbers (usually none) all equal
    exports. The full appendix is included only if every number in the file equals exports; otherwise it
    is left out with a warning, because the page may not show a number that exports do not hold.
    """
    out = {"why": {}, "appendix": ""}
    if not want:
        return out
    if not path.exists():
        fail(f"story cards not found: {path} (R05 writes data/golden/stories.md); "
             "use --no-stories only for a draft build")
    text = path.read_text(encoding="utf-8")
    known = export_number_set(data)
    for sec in re.split(r"(?m)^## ", text)[1:]:
        head = sec.partition("\n")[0]
        m = re.match(r"(Q-[A-Z]+|FINALE)\b", head.strip(), re.I)
        if not m:
            continue
        qid = m.group(1).upper()
        w = re.search(r"\*\*Why it matters to a partner\.\*\*\s*(.+)", sec)
        if not w:
            continue
        line = w.group(1).strip()
        bad = unverified_numbers(line, known)
        if bad:
            warn(f"stories.md {qid} 'why it matters' line has numbers not in exports ({', '.join(bad)}); omitted")
        else:
            out["why"][qid] = line
    bad = []
    for ln, line in enumerate(text.splitlines(), 1):
        bad += [f"line {ln}: {tok}" for tok in unverified_numbers(line, known)]
    if bad:
        warn(f"story-card appendix omitted: {len(bad)} number(s) in {path.name} are not in exports "
             f"(first: {'; '.join(bad[:8])})")
    else:
        out["appendix"] = md_to_html(text)
    return out


def check_prompt_names(prompts: dict, data: dict) -> None:
    """Warn when a proper name in a Tier-1 prompt does not occur anywhere in exports (stale name)."""
    strings: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            strings.append(o)

    walk(data)
    blob = "\n".join(strings)
    for qid, e in prompts.items():
        for name in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", e.get("tier1", "")):
            if name not in blob:
                warn(f"Tier-1 prompt for {qid} names '{name}', which no export contains (stale name?)")


# --------------------------------------------------------------------------- ontology diagram

DEFAULT_ONTOLOGY = {
    "nodes": {
        "Sponsor": (110, 60, False), "Fund": (330, 60, False), "Sector": (590, 60, False),
        "Region": (830, 60, False),
        "Intermediary": (110, 200, False), "Transaction": (330, 200, False), "Company": (590, 200, False),
        "Signal": (830, 170, False), "PipelineEntry": (830, 240, False),
        "Interaction": (110, 460, False), "Person": (330, 340, False), "Role": (590, 340, False),
        "Knows": (330, 460, True), "Score and Tier": (590, 460, True), "CoverageGap": (110, 340, True),
        "Conflict": (830, 460, True), "AddOnFit": (830, 340, True),
    },
    "edges": [
        ("Sponsor", "Fund", "manages", False), ("Fund", "Company", "owns (dated)", False),
        ("Company", "Sector", "in niche", False), ("Sector", "Sector", "parent", False),
        ("Company", "Region", "HQ and sites", False), ("Region", "Region", "parent", False),
        ("Transaction", "Company", "target", False), ("Intermediary", "Transaction", "advises", False),
        ("Sponsor", "Transaction", "buys or sells", False), ("Signal", "Company", "readiness", False),
        ("PipelineEntry", "Company", "CRM stage", False), ("Company", "Company", "sells to", False),
        ("Person", "Role", "holds (dated)", False), ("Role", "Company", "at", False),
        ("Interaction", "Person", "our touch", False),
        ("Person", "Knows", "derived", True), ("Company", "Score and Tier", "derived", True),
        ("Intermediary", "CoverageGap", "derived", True), ("Company", "Conflict", "derived", True),
        ("Company", "AddOnFit", "derived", True),
    ],
}


def parse_mermaid(text: str) -> dict | None:
    m = re.search(r"```mermaid\s*\n(.*?)```", text, re.S)
    if not m:
        return None
    src = m.group(1)
    edges = []
    for line in src.splitlines():
        s = line.strip()
        if not s or s.startswith("%%"):
            continue
        s = re.sub(r'"[^"]*"\s*(?=[-.<|o}{*])', "", s)       # classDiagram cardinalities
        e = re.match(r'^(\w+)\s+[|o}{]{1,2}(?:--|\.\.)[|o}{]{1,2}\s+(\w+)\s*:\s*"?([^"]*)"?', s)
        if e:
            edges.append((e.group(1), e.group(2), e.group(3).strip(), False))
            continue
        e = re.match(r'^(\w+)(?:[\[(][^\])]*[\])])?\s*(-\.->|-->|---|==>|-\.-|<\|--|\*--|o--|\.\.>)\s*'
                     r'(?:\|([^|]*)\|)?\s*(\w+)(?:[\[(][^\])]*[\])])?\s*(?::\s*(.*))?$', s)
        if e:
            edges.append((e.group(1), e.group(4), (e.group(3) or e.group(5) or "").strip(),
                          e.group(2) in ("-.->", "-.-", "..>")))
            continue
        e = re.match(r'^(\w+)(?:[\[(][^\])]*[\])])?\s*--\s*([^->][^>]*?)\s*-->\s*(\w+)', s)
        if e:
            edges.append((e.group(1), e.group(3), e.group(2).strip(), False))
    if not edges:
        return None
    names = []
    for a, b, _, _ in edges:
        for x in (a, b):
            if x not in names:
                names.append(x)
    n = len(names)
    cx, cy, rx, ry = 470, 260, 380, 210
    nodes = {name: (cx + rx * math.cos(2 * math.pi * i / n - math.pi / 2),
                    cy + ry * math.sin(2 * math.pi * i / n - math.pi / 2), False)
             for i, name in enumerate(names)}
    return {"nodes": nodes, "edges": edges, "source": src}


def render_ontology_svg(spec: dict) -> str:
    W, H, bw, bh = 940, 520, 128, 34
    parts = [f'<svg class="onto" viewBox="0 0 {W} {H}" role="img" aria-label="Ontology diagram" '
             'xmlns="http://www.w3.org/2000/svg">',
             '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="onto-arrow"/></marker></defs>']
    nodes = spec["nodes"]

    def border_pt(x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return x1, y1
        t = min((bw / 2) / abs(dx) if dx else 1e9, (bh / 2) / abs(dy) if dy else 1e9)
        return x1 + dx * t, y1 + dy * t

    for a, b, label, derived in spec["edges"]:
        if a not in nodes or b not in nodes:
            continue
        cls = "onto-edge derived" if derived else "onto-edge"
        ax, ay, _ = nodes[a]
        bx, by, _ = nodes[b]
        if a == b:
            x0, y0 = ax + bw / 2 - 18, ay - bh / 2
            parts.append(f'<path class="{cls}" d="M{x0:.0f},{y0:.0f} c 10,-34 46,-30 36,{bh / 2 + 6:.0f}" '
                         'marker-end="url(#arr)"/>')
            parts.append(f'<text class="onto-elabel" x="{x0 - 4:.0f}" y="{y0 - 14:.0f}" text-anchor="end">'
                         f'{html.escape(label)}</text>')
            continue
        sx, sy = border_pt(ax, ay, bx, by)
        tx, ty = border_pt(bx, by, ax, ay)
        parts.append(f'<line class="{cls}" x1="{sx:.0f}" y1="{sy:.0f}" x2="{tx:.0f}" y2="{ty:.0f}" '
                     'marker-end="url(#arr)"/>')
        if label and not derived:
            mx, my = (sx + tx) / 2, (sy + ty) / 2
            parts.append(f'<text class="onto-elabel" x="{mx:.0f}" y="{my - 4:.0f}" text-anchor="middle">'
                         f'{html.escape(label)}</text>')
    for name, (x, y, derived) in nodes.items():
        cls = "onto-node derived" if derived else "onto-node"
        parts.append(f'<rect class="{cls}" x="{x - bw / 2:.0f}" y="{y - bh / 2:.0f}" width="{bw}" '
                     f'height="{bh}" rx="6"/>')
        parts.append(f'<text class="onto-nlabel" x="{x:.0f}" y="{y + 5:.0f}" text-anchor="middle">'
                     f'{html.escape(name)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def ontology_block() -> str:
    spec, note, src_attr = None, "", ""
    if ONTOLOGY.exists():
        spec = parse_mermaid(ONTOLOGY.read_text(encoding="utf-8"))
    if spec:
        svg = render_ontology_svg(spec)
        src = html.escape(spec["source"])
        src_attr = ' data-src="ONTOLOGY.md"'                 # edge labels are source text (may hold digits)
        note = ('<p class="small">Drawn from the mermaid diagram in ONTOLOGY.md. '
                'Concept names match the model code.</p>'
                f'<details class="noprint" data-src="ONTOLOGY.md"><summary>Mermaid source</summary>'
                f'<pre>{src}</pre></details>')
    else:
        svg = render_ontology_svg(DEFAULT_ONTOLOGY)
        note = ('<p class="small">Sketch from the design brief. Dashed boxes are derived by rules or graph '
                'algorithms, never loaded. When ONTOLOGY.md lands with a mermaid block, the build draws it '
                'here instead.</p>')
    return f'<div class="tw"{src_attr}>{svg}</div>{note}'


# --------------------------------------------------------------------------- tables

def table(head: list[str], rows: list[list[str]], cls: str = "") -> str:
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def t_score_tier_a(c: Ctx, qid: str) -> str:
    base = "q_score.rows[tier=A]"
    rows = []
    for i in range(len(resolve(base, c.data))):
        r = f"{base}[{i}]"
        crm = resolve(f"{r}.in_crm", c.data)
        badge = "" if crm else ' <span class="chip warn">not in CRM</span>'
        rows.append([c.v(f"{r}.rank"), "<strong>" + c.v(f"{r}.name") + "</strong>" + badge,
                     c.v(f"{r}.score"), c.v(f"{r}.fit"), c.v(f"{r}.readiness"), c.v(f"{r}.access"),
                     '<span class="small">' + c.v(f"{r}.why") + "</span>"])
    return table(["Rank", "Company", "Score", "Fit", "Readiness", "Access", "Why"], rows, "num")


def t_score_breakdown(c: Ctx, qid: str) -> str:
    r = "q_score.rows[tier=A][0]"
    rows = []
    comps = resolve(f"{r}.components", c.data)
    for i in range(len(comps)):
        cid = comps[i]["id"]
        rows.append([c.v(f"q_score.components[id={cid}][0].label"),
                     c.v(f"q_score.components[id={cid}][0].group"),
                     c.v(f"{r}.components[{i}].points"),
                     '<span class="small">' + c.v(f"{r}.components[{i}].evidence") + "</span>"])
    return table(["Component", "Group", "Points", "Evidence"], rows, "num")


def t_score_ineligible(c: Ctx, qid: str) -> str:
    base = "q_score.ineligible"
    rows = [[c.v(f"{base}[{i}].name"), '<span class="small">' + c.v(f"{base}[{i}].reason") + "</span>"]
            for i in range(len(resolve(base, c.data)))]
    return table(["Company", "Why the rules reject it"], rows)


def t_sql(c: Ctx, qid: str) -> str:
    base = f"sql_baseline.questions.{qid}"
    rows = []
    for i in range(len(resolve(f"{base}.rows", c.data))):
        r = f"{base}.rows[{i}]"
        verdict = resolve(f"{r}.verdict", c.data)
        chip = {"decoy": '<span class="chip bad">decoy</span>', "agrees": '<span class="chip ok">agrees</span>'}
        metric = resolve(f"{r}.metric", c.data)
        mfmt = "f1" if isinstance(metric, float) and not metric.is_integer() else ""
        rows.append([c.v(f"{r}.rank"), c.v(f"{r}.name"), c.v(f"{r}.metric", mfmt),
                     chip.get(verdict, c.v(f"{r}.verdict")),
                     '<span class="small">' + c.v(f"{r}.note", "opt") + "</span>"])
    out = ""
    if rows:
        out += table(["Rank", "SQL screen row", c.v(f"{base}.metric_label"), "Verdict", "Note"], rows, "num")
    missed = resolve(f"{base}.missed", c.data)
    if missed:
        items = "".join(f"<li><strong>{c.v(f'{base}.missed[{i}].name')}</strong>: "
                        f"<span class=\"small\">{c.v(f'{base}.missed[{i}].note', 'opt')}</span></li>"
                        for i in range(len(missed)))
        out += f'<p class="small">Missed by the SQL screen:</p><ul class="tight">{items}</ul>'
    return out


def t_paths(c: Ctx, qid: str) -> str:
    out = []
    targets = resolve("q_path.targets", c.data)
    for i in range(len(targets)):
        t = f"q_path.targets[{i}]"
        owner = resolve(f"{t}.owner_name", c.data)
        own = f", owned by {c.v(f'{t}.owner_name')}" if owner else ", founder-owned"
        status = resolve(f"{t}.status", c.data)
        chip = '<span class="chip ok">warm</span>' if status == "warm" else '<span class="chip bad">cold</span>'
        block = [f'<h4>{c.v(f"{t}.company_name")} <span class="small">score rank {c.v(f"{t}.score_rank")}'
                 f'{own}</span> {chip}</h4><p class="small">{c.v(f"{t}.summary")}</p>']
        dms = resolve(f"{t}.decision_makers", c.data)
        for d in range(len(dms)):
            dm = f"{t}.decision_makers[{d}]"
            who = f'<strong>{c.v(f"{dm}.name")}</strong> ({c.v(f"{dm}.role_label")})'
            if resolve(f"{dm}.status", c.data) != "warm":
                block.append(f'<p>{who}: <span class="chip bad">no path</span> {c.v(f"{dm}.summary")}</p>')
                continue
            block.append(f'<p>{who}: {c.v(f"{dm}.hops")} hops, best path strength '
                         f'{c.v(f"{dm}.best_strength", "f3")}</p>')
            for j in range(len(resolve(f"{dm}.paths", c.data))):
                pth = f"{dm}.paths[{j}]"
                hops = "".join(f'<li>{c.v(f"{pth}.hops[{k}].from_name")} to {c.v(f"{pth}.hops[{k}].to_name")}: '
                               f'<span class="small">{c.v(f"{pth}.hops[{k}].evidence")} '
                               f'(tie strength {c.v(f"{pth}.hops[{k}].strength", "f3")})</span></li>'
                               for k in range(len(resolve(f"{pth}.hops", c.data))))
                tag = '<span class="chip ok">best path</span>' if j == 0 else '<span class="chip">alternate</span>'
                block.append(f'<p class="small">{tag} {c.v(f"{pth}.length")} hops, strength '
                             f'{c.v(f"{pth}.strength", "f3")}</p><ol class="hops">{hops}</ol>')
        ci = resolve(f"{t}.closest_intermediary", c.data)
        if ci:
            block.append(f'<p class="small">Closest intermediary: <strong>{c.v(f"{t}.closest_intermediary.name")}'
                         f'</strong>. {c.v(f"{t}.closest_intermediary.evidence")}</p>')
        out.append("".join(block))
    return '<div class="paths">' + "".join(out) + "</div>"


def t_addon(c: Ctx, qid: str) -> str:
    base = "q_addon.candidates"
    rows = []
    for i in range(len(resolve(base, c.data))):
        r = f"{base}[{i}]"
        rows.append([c.v(f"{r}.rank"), "<strong>" + c.v(f"{r}.name") + "</strong>", c.v(f"{r}.niche"),
                     c.v(f"{r}.similarity", "f4"), c.v(f"{r}.shared_count") + " of " + c.v(f"{r}.union_count"),
                     c.v(f"{r}.whitespace_states", "list"),
                     '<span class="small">' + c.v(f"{r}.evidence") + "</span>"])
    return table(["Rank", "Candidate", "Niche", "Similarity", "Shared / union", "New states", "Evidence"],
                 rows, "num")


def t_flow(c: Ctx, qid: str) -> str:
    base = "q_flow.intermediaries"
    items = resolve(base, c.data)
    order = sorted(range(len(items)), key=lambda i: items[i]["betweenness_rank"])
    show = [i for i in order if items[i]["top_decile"] or items[i]["is_gap"]]
    for i in order:
        if len(show) >= 5:
            break
        if i not in show:
            show.append(i)
    show = sorted(show, key=lambda i: items[i]["betweenness_rank"])
    rows = []
    for i in show:
        r = f"{base}[{i}]"
        gap = '<span class="chip bad">coverage gap</span>' if items[i]["is_gap"] else ""
        rows.append([c.v(f"{r}.betweenness_rank"), "<strong>" + c.v(f"{r}.name") + "</strong> " + gap,
                     c.v(f"{r}.betweenness", "f1"), c.v(f"{r}.deals_in_window"),
                     c.v(f"{r}.deals_5y_all_sectors"), c.v(f"{r}.touchpoints_24m")])
    return table(["Centrality rank", "Intermediary", "Betweenness", "Thesis deals in window",
                  "All deals, five years", "Our touchpoints, two years"], rows, "num")


def t_conflict(c: Ctx, qid: str) -> str:
    base = "q_conflict.exposures"
    rows = []
    for i in range(len(resolve(base, c.data))):
        r = f"{base}[{i}]"
        bad = resolve(f"{r}.kind", c.data) == "conflict"
        label = c.v(f"{r}.kind_label")
        rows.append([c.v(f"{r}.name"), c.v(f"{r}.fund_name") + ' <span class="small">since ' + c.v(f"{r}.since")
                     + "</span>", c.v(f"{r}.distance"),
                     f'<span class="chip {"bad" if bad else "warn"}">{label}</span>',
                     '<span class="small">' + c.v(f"{r}.evidence") + "</span>"])
    out = table(["Current holding", "Fund", "Hops", "Kind", "Evidence"], rows, "num")
    ctx_rows = resolve("q_conflict.context", c.data)
    if ctx_rows:
        items = "".join(f'<li>{c.v(f"q_conflict.context[{i}].name")} (distance {c.v(f"q_conflict.context[{i}].distance")}'
                        f'):{c.v(f"q_conflict.context[{i}].reason")}</li>' for i in range(len(ctx_rows)))
        out += f'<p class="small">Correctly left out (presenter context, not in the live answer):</p><ul class="small">{items}</ul>'
    k = "q_conflict.concentration"
    arows = []
    for i in range(len(resolve(f"{k}.areas", c.data))):
        a = f"{k}.areas[{i}]"
        flag = '<span class="chip bad">over guideline</span>' if resolve(f"{a}.breach", c.data) else ""
        name = c.v(f"{a}.name")
        if resolve(f"{a}.is_subject_area", c.data):
            name = f"<strong>{name}</strong>"
        arows.append([name, c.v(f"{a}.before_musd", "musd") + " (" + c.v(f"{a}.before_pct", "pct") + ")",
                      c.v(f"{a}.after_musd", "musd") + " (" + c.v(f"{a}.after_pct", "pct") + ") " + flag])
    out += (f'<p>Concentration, {c.v(f"{k}.fund_name")} ({c.v(f"{k}.fund_size_musd", "musd")} committed), '
            f'guideline {c.v(f"{k}.guideline_pct", "pct")} per thesis area, with a {c.v(f"{k}.check_musd", "musd")} '
            f'check:</p>')
    out += table(["Thesis area", "Before", "With the deal"], arows, "num")
    return out


def t_finale(c: Ctx, qid: str) -> str:
    base = "q_score.finale.rows"
    rows = []
    for i in range(len(resolve(base, c.data))):
        r = f"{base}[{i}]"
        row = resolve(r, c.data)
        if row.get("prev_tier") != "A" and row.get("tier") != "A" and not row.get("conflict"):
            continue
        if row.get("conflict"):
            change = ('<span class="chip bad">' + c.v(f"{r}.tier") + "</span> "
                      '<span class="small">' + c.v(f"{r}.conflict.reason") + "</span>")
            rank = "-"
        else:
            delta = row.get("delta") or 0
            change = (("+" + c.v(f"{r}.delta") + " " + c.v(f"{r}.added_components[0].evidence"))
                      if delta else "no change")
            if row.get("prev_tier") != "A" and row.get("tier") == "A":
                change += ' <span class="chip ok">new to Tier A</span>'
            rank = c.v(f"{r}.rank")
        rows.append([rank, "<strong>" + c.v(f"{r}.name") + "</strong>",
                     c.v(f"{r}.prev_score") + " (" + c.v(f"{r}.prev_tier") + ")",
                     c.v(f"{r}.score") + " (" + c.v(f"{r}.tier") + ")", change])
    return table(["New rank", "Company", "Before", "After", "Change"], rows, "num")


def t_edge_types(c: Ctx, qid: str) -> str:
    base = "graph.edge_types"
    rows = [[c.v(f"{base}[{i}].label"), c.v(f"{base}[{i}].count"), c.v(f"{base}[{i}].rule_id", "opt")]
            for i in range(len(resolve(base, c.data)))]
    return table(["Relationship in the explorer", "Edges shown", "Rule"], rows, "num")


TABLES = {
    "score_tier_a": t_score_tier_a, "score_breakdown": t_score_breakdown,
    "score_ineligible": t_score_ineligible, "sql": t_sql, "paths": t_paths, "addon": t_addon,
    "flow": t_flow, "conflict": t_conflict, "finale": t_finale, "edge_types": t_edge_types,
}


# --------------------------------------------------------------------------- template rendering

BLOCK_RE = re.compile(r"<!--\s*BLOCK\s+([\w-]+)\s*-->(.*?)<!--\s*/BLOCK\s+\1\s*-->", re.S)
NEXT_RE = re.compile(r"<!--\s*NEXT\s+([\w*-]+)\s*-->(.*?)<!--\s*/NEXT\s*-->", re.S)


def load_template(path: Path) -> dict:
    if not path.exists():
        fail(f"template not found: {path}")
    text = path.read_text(encoding="utf-8")
    blocks = {m.group(1): m.group(2) for m in BLOCK_RE.finditer(text)}
    for need in ["PAGE", "COLD_OPEN", "MODEL", "FINALE", "CLOSE", "ELEVATOR", "SKEPTICS", "STORIES",
                 *[q for q in QUESTIONS if q != "FINALE"]]:
        if need not in blocks:
            fail(f"template block missing: {need}")
    # Nothing numeric typed by hand: no digit in visible template text.
    audit = re.sub(r"<style>.*?</style>", "", text, flags=re.S)
    audit = re.sub(r"<script>.*?</script>", "", audit, flags=re.S)
    audit = re.sub(r"<!--.*?-->", "", audit, flags=re.S)
    audit = re.sub(r"\{\{.*?\}\}", "", audit, flags=re.S)
    audit = re.sub(r"\[\[.*?\]\]", "", audit, flags=re.S)
    audit = re.sub(r"<[^>]+>", "", audit)
    digits = sorted({ln for ln, line in enumerate(audit.splitlines(), 1) if re.search(r"\d", line)})
    if digits:
        fail("template contains hand-typed digits in visible text (inject them from exports): "
             + ", ".join(repr(line.strip()) for ln, line in enumerate(audit.splitlines(), 1) if ln in digits))
    if EM_DASH in text:
        fail("template contains an em dash (U+2014)")
    return blocks


class Renderer:
    def __init__(self, ctx: Ctx, prompts: dict, brief: dict, order: list[str], stories: dict,
                 fixture: bool, prompt_src: str):
        self.c, self.prompts, self.brief, self.order = ctx, prompts, brief, order
        self.prompt_src = prompt_src
        self.stories, self.fixture = stories, fixture

    def render(self, body: str, qid: str | None = None, act_no: int | None = None,
               minutes: int | None = None, next_qid: str | None = None) -> str:
        def pick_next(m):
            want = m.group(1)
            return m.group(2) if want == next_qid else ""

        if NEXT_RE.search(body):
            variants = [m.group(1) for m in NEXT_RE.finditer(body)]
            if next_qid not in variants:
                fail(f"block {qid}: no hand-off variant for next act {next_qid} (have {variants})")
            body = NEXT_RE.sub(pick_next, body)
        if qid:
            spec = QUESTIONS[qid]
            body = body.replace("@q.", spec["file"] + ".").replace("@sql.", f"sql_baseline.questions.{qid}.")

        def directive(m):
            name, _, arg = m.group(1).strip().partition(":")
            if name == "act_no":
                return self.c.lit(act_no, "act number")
            if name == "minutes":
                return self.c.lit(minutes, "minutes, PROMPT.md 7.5")
            if name == "fn":
                return f"<code>{QUESTIONS[qid]['fn']}</code>"
            if name == "fallback":
                fn = QUESTIONS[qid]["fn"]
                return (f'<code class="cmd">uv run python ask.py {fn}</code>')
            if name == "fallback_steps":
                return self.fallback_steps(qid)
            if name == "prompt_src":
                return f"<code>{self.prompt_src}</code>"
            if name == "view":
                return QUESTIONS[qid]["view"]
            if name == "reasoner":
                return QUESTIONS[qid]["reasoner"]
            if name == "prompt":
                return self.prompt(qid if not arg.count("/") else arg.split("/")[0],
                                   arg.split("/")[-1] if arg else "tier1")
            if name == "table":
                if arg not in TABLES:
                    fail(f"unknown table directive: {arg}")
                return TABLES[arg](self.c, qid)
            if name == "ontology":
                return ontology_block()
            if name == "brief":
                return self.brief_html(arg)
            if name == "stories":
                return f'<div data-src="data/golden/stories.md">{self.stories["appendix"]}</div>'
            if name == "story_why":
                line = self.stories["why"].get(qid)
                if not line:
                    return ""
                return (f'<p class="sowhat" data-src="data/golden/stories.md"><strong>So what for a partner.'
                        f'</strong> {_inline_md(line)}</p>')
            fail(f"unknown directive [[{m.group(1)}]]")

        body = re.sub(r"\[\[(.+?)\]\]", directive, body)

        def value(m):
            expr, _, fmt = m.group(1).partition("|")
            return self.c.v(expr.strip(), fmt)

        return re.sub(r"\{\{\s*(.+?)\s*\}\}", value, body, flags=re.S)

    def fallback_steps(self, qid: str) -> str:
        fn, view = QUESTIONS[qid]["fn"], QUESTIONS[qid]["view"]
        return ('<ol class="fallback">'
                f'<li>Say "let me pull the governed version" and type in Claude Code: <code class="cmd">Run uv run '
                f'python ask.py {fn} and show the result as a table with the why for each row.</code></li>'
                f'<li>If Claude Code itself is down, in a second terminal: <code class="cmd">cd demo_workspace '
                f'&amp;&amp; uv run python ask.py {fn}</code> and talk over the printed table.</li>'
                f'<li>If RAI or Snowflake is down, switch to the explorer, <strong>{view}</strong> view. It is '
                'built from the same exports and needs no network.</li></ol>')

    def prompt(self, qid: str, kind: str) -> str:
        p = self.prompts.get(qid)
        if not p:
            fail(f"prompts.md has no section with a Tier-1 prompt for {qid}")
        if kind not in p:
            if kind == "tier1":
                fail(f"prompts.md: no Tier-1 prompt for {qid}")
            return ""
        label = {"tier1": "Type this, verbatim", "para": "Paraphrase, if you prefer your own words",
                 "tier2": "Optional ad-lib follow-up"}[kind]
        cls = "prompt" if kind == "tier1" else "prompt alt"
        return (f'<div class="{cls}" data-src="{self.prompt_src}"><div class="plabel">{label}'
                f'<button type="button" class="copy noprint">Copy</button></div>'
                f'<pre>{html.escape(p[kind])}</pre></div>')

    def brief_html(self, which: str) -> str:
        b = self.brief
        if which == "qa":
            items = "".join(f'<div class="qa"><p class="q">"{_inline_md(q)}"</p><p>{_inline_md(a)}</p></div>'
                            for q, a in b["qa"])
            items += (f'<div class="qa"><p class="q">"Affinity already does this."</p>'
                      f'<p>{_inline_md(b["affinity"])}</p></div>')
            return f'<div data-src="research/domain_brief.md">{items}</div>'
        if which == "qa_rest":
            # The template carries one merged Affinity/DealCloud answer (R19a m6), so skip the brief's
            # Affinity entries and its section-3 paragraph to avoid a duplicate.
            items = "".join(f'<div class="qa"><p class="q">"{_inline_md(q)}"</p><p>{_inline_md(a)}</p></div>'
                            for q, a in b["qa"] if "affinity" not in q.lower())
            return f'<div data-src="research/domain_brief.md">{items}</div>'
        if which == "vocab":
            rows = [[_inline_md(s), _inline_md(n), '<span class="small">' + _inline_md(note) + "</span>"]
                    for s, n, note in b["vocab"]]
            return f'<div data-src="research/domain_brief.md">{table(["Say", "Not", "Note"], rows)}</div>'
        fail(f"unknown brief directive: {which}")


def build(data: dict, order: list[str], prompts: tuple[dict, str], brief: dict, stories: dict,
          fixture: bool) -> tuple[str, Ctx]:
    blocks = load_template(TEMPLATE)
    ctx = Ctx(data)
    r = Renderer(ctx, prompts[0], brief, order, stories, fixture, prompts[1])
    seq = order + ["FINALE"]
    acts_html = []
    for i, qid in enumerate(order):
        acts_html.append(r.render(blocks[qid], qid=qid, act_no=i + 1, minutes=MINUTES["ACT"][i],
                                  next_qid=seq[i + 1]))
    # Run-of-show summary.
    ros = [["Cold open", "-", ctx.lit(MINUTES["COLD_OPEN"], "minutes"), "-", "Overview"],
           ["The model", "-", ctx.lit(MINUTES["MODEL"], "minutes"), "-", "Global"]]
    for i, qid in enumerate(order):
        ros.append([f"Act {ctx.lit(i + 1, 'act number')}", qid, ctx.lit(MINUTES["ACT"][i], "minutes"),
                    f"<code>{QUESTIONS[qid]['fn']}</code>", QUESTIONS[qid]["view"]])
    ros.append(["Finale", "Live rule", ctx.lit(MINUTES["FINALE"], "minutes"), "<code>finale_rescore</code>",
                QUESTIONS["FINALE"]["view"]])
    ros.append(["Close", "-", ctx.lit(MINUTES["CLOSE"], "minutes"), "-", "-"])
    total = MINUTES["COLD_OPEN"] + MINUTES["MODEL"] + sum(MINUTES["ACT"]) + MINUTES["FINALE"] + MINUTES["CLOSE"]
    ros_html = table(["Segment", "Question", "Minutes", "Fallback function", "Explorer view"], ros)
    ros_html += f'<p class="small">Total {ctx.lit(total, "minutes")} minutes.</p>'

    meta = data["meta"]
    source = str(meta.get("source", "")).upper()
    banner = ""
    if fixture or source == "FIXTURE":
        banner = ('<div class="stamp">FIXTURE BUILD. Every name and number on this page is fake test data. '
                  'Do not present from this file.</div>')
    elif source not in ("RAI", "LIVE"):
        banner = (f'<div class="stamp">Built from {html.escape(source or "UNLABELLED")} exports, not live '
                  'RAI output. Check with R13 before presenting.</div>')

    slots = {
        "banner": banner,
        "fixture_class": "fixture" if banner and (fixture or source == "FIXTURE") else "",
        "title_prefix": "FIXTURE - " if (fixture or source == "FIXTURE") else "",
        "run_of_show": ros_html,
        "cold_open": r.render(blocks["COLD_OPEN"], minutes=MINUTES["COLD_OPEN"]),
        "model": r.render(blocks["MODEL"], minutes=MINUTES["MODEL"]),
        "acts": "\n".join(acts_html),
        "finale": r.render(blocks["FINALE"], qid="FINALE", minutes=MINUTES["FINALE"]),
        "close": r.render(blocks["CLOSE"], minutes=MINUTES["CLOSE"]),
        "elevator": r.render(blocks["ELEVATOR"]),
        "skeptics": r.render(blocks["SKEPTICS"]),
        "stories": r.render(blocks["STORIES"]) if stories["appendix"] else "",
    }
    page = blocks["PAGE"]
    for k, v in slots.items():
        page = page.replace(f"[[slot:{k}]]", v)
    if "[[slot:" in page:
        fail("unfilled slot in PAGE: " + re.search(r"\[\[slot:[^\]]+\]\]", page).group(0))
    page = r.render(page)
    return page.strip() + "\n", ctx


# --------------------------------------------------------------------------- verification

class Checker(HTMLParser):
    SKIP = {"style", "script"}
    VOID = {"br", "img", "meta", "link", "input", "hr", "path", "rect", "line"}

    def __init__(self, data: dict):
        super().__init__(convert_charrefs=True)
        self.data = data
        self.stack: list[tuple[str, bool, dict | None]] = []
        self.errors: list[str] = []
        self.verified = 0
        self.span: dict | None = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.VOID:
            return
        exempt = bool(a.get("data-src")) or "lit" in (a.get("class") or "").split()
        val = None
        if "data-k" in a:
            val = {"k": a["data-k"], "f": a.get("data-f", ""), "text": ""}
            self.span = val
        if tag in self.SKIP:
            self.skip += 1
        self.stack.append((tag, exempt, val))

    def handle_endtag(self, tag):
        if tag in self.VOID or not any(t == tag for t, _, _ in self.stack):
            return                                   # self-closing SVG/void tag: nothing was pushed
        while self.stack:
            t, _, val = self.stack.pop()
            if t in self.SKIP:
                self.skip -= 1
            if val is not None:
                self._verify(val)
                self.span = None
            if t == tag:
                break

    def _verify(self, val):
        chain = [f for f in val["f"].split("|") if f]
        try:
            want = apply_fmt(resolve(val["k"], self.data), chain)
        except BuildError as e:
            self.errors.append(f"{val['k']}: {e}")
            return
        if want != val["text"]:
            self.errors.append(f"{val['k']}: page shows {val['text']!r}, exports give {want!r}")
        else:
            self.verified += 1

    def handle_data(self, d):
        if self.span is not None:
            self.span["text"] += d
            return
        if self.skip or any(ex for _, ex, _ in self.stack):
            return
        if re.search(r"\d", d):
            self.errors.append(f"hand-typed digit outside an injected value: {d.strip()[:80]!r}")


def check(path: Path, data: dict) -> tuple[int, list[str]]:
    text = path.read_text(encoding="utf-8")
    errors = []
    if EM_DASH in text:
        errors.append(f"em dash (U+2014) found {text.count(EM_DASH)} time(s)")
    if re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", text, re.I):
        errors.append("external src/href found; the page must be offline")
    size = path.stat().st_size
    if size > 8 * 1024 * 1024:
        errors.append(f"file is {size} bytes, over 8 MB")
    ch = Checker(data)
    ch.feed(text)
    ch.close()
    return ch.verified, errors + ch.errors


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", action="store_true", help="build from test fixtures, stamped FIXTURE")
    ap.add_argument("--exports", type=Path, help="exports directory (default exports/)")
    ap.add_argument("--stories", type=Path, help="story cards (default data/golden/stories.md)")
    ap.add_argument("--out", type=Path, help="output HTML path")
    ap.add_argument("--act-order", help="override act order, e.g. Q-SCORE,Q-PATH,Q-FLOW,Q-CONFLICT")
    ap.add_argument("--no-stories", action="store_true", help="draft build without the story-card appendix")
    ap.add_argument("--check-only", action="store_true", help="only verify an existing output")
    ap.add_argument("--list-keys", action="store_true", help="print every exports key path consumed")
    args = ap.parse_args(argv)

    try:
        if args.fixture:
            exports, extra = args.exports or FIX_EXPORTS, FIX_EXTRA
            stories, out = args.stories or FIX_STORIES, args.out or FIX_OUT
        else:
            exports, extra = args.exports or REAL_EXPORTS, None
            stories, out = args.stories or REAL_STORIES, args.out or REAL_OUT
        data = load_exports(exports, extra)
        is_fixture = args.fixture or str(data["meta"].get("source", "")).upper() == "FIXTURE"
        if is_fixture and out.resolve() == REAL_OUT.resolve():
            fail("refusing to write artifacts/demo_script.html from FIXTURE exports; "
                 "use --fixture (writes tests/fixtures/script/out/)")
        if args.check_only:
            n, errs = check(out, data)
        else:
            order = act_order(data, args.act_order)
            prompts = load_prompts()
            brief = parse_brief(BRIEF)
            stories_d = load_stories(stories, data, not args.no_stories)
            check_prompt_names(prompts[0], data)
            page, ctx = build(data, order, prompts, brief, stories_d, is_fixture)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(page, encoding="utf-8")
            n, errs = check(out, data)
            if args.list_keys:
                print("\n".join(sorted(ctx.keys)))
            print(f"build_script: wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} "
                  f"({out.stat().st_size:,} bytes, acts {' > '.join(order)} > FINALE, "
                  f"{'FIXTURE' if is_fixture else data['meta'].get('source', '?')} exports)")
        if errs:
            print(f"build_script: CHECK FAIL ({len(errs)} problem(s)):", file=sys.stderr)
            for e in errs[:60]:
                print("  " + e, file=sys.stderr)
            return 1
        print(f"build_script: CHECK OK - {n} injected values re-verified against exports, "
              "no hand-typed digits, no em dashes, no external URLs"
              + (f" ({len(WARNINGS)} warning(s) above)" if WARNINGS else ""))
        return 0
    except BuildError as e:
        print(f"build_script: FAIL - {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
