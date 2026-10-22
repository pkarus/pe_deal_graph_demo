"""R17 rehearsal checker: golden / decoy / RAI-skill check over claude -p stream-json transcripts.

Scans only the assistant text (text blocks of assistant messages plus the final result text),
never tool results, so a decoy name inside raw query output does not count against the answer.

Usage:
  python scripts/rehearsal_check.py artifacts/rehearsal/<prompt_id>_run<k>.jsonl [...]
  python scripts/rehearsal_check.py --all            # every transcript in artifacts/rehearsal, JSON lines out
Latency is read from artifacts/rehearsal/latency.tsv (written by scripts/rehearsal_run.py).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REH = ROOT / "artifacts" / "rehearsal"
GOLD = json.loads((ROOT / "data" / "golden" / "expected.json").read_text())["questions"]


def _r(q):
    return GOLD[q]["rehearsal"]


# Per prompt family: (must_appear, must_not_appear, extra regex that must match, or None).
# Tier-1 and paraphrase use the golden rehearsal lists verbatim.
# Tier-2 checks are row-based per prompts.md "Expected" lines.
SPECS = {
    "SCORE": (_r("Q-SCORE")["must_appear"], _r("Q-SCORE")["must_not_appear"], None),
    "PATH": (_r("Q-PATH")["must_appear"], _r("Q-PATH")["must_not_appear"], None),
    "FLOW": (_r("Q-FLOW")["must_appear"], _r("Q-FLOW")["must_not_appear"], None),
    "CONFLICT": (_r("Q-CONFLICT")["must_appear"], _r("Q-CONFLICT")["must_not_appear"], None),
    # Tier-2 ad-libs
    "T2-SCORE": (["Bayside Pediatric Therapy Group", "Quarry Records Retrieval", "Tessmark Clinical Supply"],
                 _r("Q-SCORE")["must_not_appear"], None),
    "T2-PATH": (["Tom Harlowe", "Victor Hale"], [], r"(2011|2013|never overlap|did not overlap|didn't overlap|no overlap)"),
    "T2-FLOW": (["Saltmarsh Home Infusion"], [], None),
    "T2-CONFLICT": ([], ["Cobbleton Dental Group", "Redfern Imaging Centers"], r"\$\s?35(\.0)?\s?(M|million|m\b)"),
    # Finale: golden list minus the "(as flagged)" annotation, plus a hold/conflict flag mention
    "FINALE": ([n.replace(" (as flagged)", "") for n in _r("FINALE")["must_appear"]], [],
               r"(?i)(hold until cross-fund clearance|cross-fund (review|clearance)|conflict)"),
}


def family(prompt_id: str) -> str:
    # ids: T1-SCORE, PARA-PATH, T2-FLOW, T2-FINALE, PILOT-SCORE
    kind, fam = prompt_id.split("-", 1)
    if fam == "FINALE":
        return "FINALE"
    return f"T2-{fam}" if kind == "T2" else fam


def parse(path: Path):
    texts, skills, tools, result, is_error, sid = [], [], [], None, False, None
    server = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = sid or ev.get("session_id")
        if ev.get("type") == "assistant":
            for b in ev.get("message", {}).get("content", []) or []:
                if b.get("type") == "text":
                    texts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    inp = b.get("input", {}) or {}
                    if b.get("name") == "Skill":
                        skills.append(str(inp.get("skill") or inp.get("command") or inp))
                    tools.append(b.get("name") + ":" + str(inp.get("command") or inp.get("skill") or inp.get("file_path") or "")[:120])
        elif ev.get("type") == "user":
            for b in ev.get("message", {}).get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    c = c if isinstance(c, str) else json.dumps(c)
                    for m in re.finditer(r"\(ran in ([0-9.]+)s( on the warm query server)?\)", c):
                        server.append(("server " if m.group(2) else "in-process ") + m.group(1) + "s")
                    if "SnowflakeTableObjectsException" in c or "locked by active write" in c:
                        server.append("ENGINE-ERROR")
        elif ev.get("type") == "result":
            result = ev.get("result")
            is_error = bool(ev.get("is_error"))
    text = "\n".join(texts + ([result] if result else []))
    parse.server = server
    return text, skills, tools, is_error, sid


def latencies():
    out = {}
    f = REH / "latency.tsv"
    if f.exists():
        for ln in f.read_text().splitlines():
            p = ln.split("\t")
            if len(p) >= 3:
                out[p[0]] = (float(p[1]), int(p[2]))
    return out


def check(path: Path, lat=None):
    stem = path.stem  # <prompt_id>_run<k>
    prompt_id = stem.rsplit("_run", 1)[0]
    must, must_not, rx = SPECS[family(prompt_id)]
    text, skills, tools, is_error, sid = parse(path)
    norm = text.replace("‑", "-").replace(" ", " ")
    missing = [n for n in must if n not in norm]
    decoys = [n for n in must_not if n in norm]
    rai_skill = any("rai" in s.lower() for s in skills)
    # Tier-2 ad-libs fork a passing Tier-1 session (which loaded the skill); the forked
    # transcript holds only the new turn, so the skill counts as inherited from that session.
    skill_inherited = (not rai_skill) and prompt_id.startswith("T2-") and prompt_id != "T2-FINALE"
    rai_skill = rai_skill or skill_inherited
    rx_ok = True if rx is None else bool(re.search(rx, norm))
    reasons = []
    if is_error or not text.strip():
        reasons.append("error/empty result")
    if missing:
        reasons.append("missing: " + ", ".join(missing))
    if decoys:
        reasons.append("decoy: " + ", ".join(decoys))
    if not rai_skill:
        reasons.append("no RAI skill")
    if not rx_ok:
        reasons.append("expected fact not found")
    l = (lat or {}).get(stem)
    return {
        "transcript": str(path.relative_to(ROOT)), "prompt_id": prompt_id, "session_id": sid,
        "latency_s": l[0] if l else None, "rc": l[1] if l else None,
        "skills": skills + (["(inherited from Tier-1 session)"] if skill_inherited else []), "pass": not reasons, "reasons": reasons,
        "used_fallback": "from-exports" in " ".join(tools) or "precomputed" in norm.lower(),
        "tools": tools, "query_path": parse.server,
    }


def summary(results):
    import statistics
    groups = {}
    for r in results:
        groups.setdefault(r["prompt_id"], []).append(r)
    lines = ["| prompt | runs | passes | median s | max s | warm-server runs | failure reasons |", "|---|---|---|---|---|---|---|"]
    for pid in sorted(groups):
        g = groups[pid]
        ls = [r["latency_s"] for r in g if r["latency_s"] is not None]
        srv = sum(1 for r in g if any(x.startswith("server") for x in r["query_path"]))
        reasons = "; ".join(f"{Path(r['transcript']).stem.rsplit('_', 1)[1]}: {', '.join(r['reasons'])}" for r in g if r["reasons"]) or "-"
        lines.append(f"| {pid} | {len(g)} | {sum(r['pass'] for r in g)} | {statistics.median(ls):.1f} | {max(ls):.1f} | {srv}/{len(g)} | {reasons} |")
    return "\n".join(lines)


def main(argv):
    lat = latencies()
    if argv[:1] == ["--summary"]:
        res = [check(p, lat) for p in sorted(REH.glob("*_run*.jsonl"))]
        print(summary(res))
        return 0
    paths = sorted(REH.glob("*_run*.jsonl")) if argv[:1] == ["--all"] else [Path(a).resolve() for a in argv]
    for p in paths:
        r = check(p, lat)
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
