"""G7 gatekeeper checker (independent of scripts/rehearsal_check.py).

Per transcript: final assistant text, RAI Skill use, exact-string golden/decoy match, latency from
first to last event timestamp (fallback: result.duration_ms). Reads saved stream-json only.
Usage: python3 scripts/gate_g7_check.py [--json]
"""
import glob, json, os, re, statistics, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REH = os.path.join(ROOT, "artifacts", "rehearsal")
Q = json.load(open(os.path.join(ROOT, "data/golden/expected.json")))["questions"]
QK = {"SCORE": "Q-SCORE", "PATH": "Q-PATH", "FLOW": "Q-FLOW", "CONFLICT": "Q-CONFLICT"}

def names(l):
    return [x["name"] if isinstance(x, dict) else x for x in l]

def spec(pid):
    kind, fam = pid.split("-", 1)
    if kind in ("T1", "PARA", "PILOT"):
        q = Q[QK[fam]]
        must = q["rehearsal"]["must_appear"]
        decoy_reh = q["rehearsal"].get("must_not_appear", [])
        decoy_all = sorted(set(decoy_reh) | set(names(q.get("must_not_contain", []))))
        return must, decoy_reh, decoy_all, None
    # Tier-2: row-based, from prompts.md "Expected"
    if fam == "SCORE":
        return ["Bayside Pediatric Therapy Group", "Quarry Records Retrieval", "Tessmark Clinical Supply"], [], [], None
    if fam == "PATH":
        return ["Tom Harlowe", "Victor Hale"], [], [], r"2011|2013|never overlap|did not overlap|didn't overlap|no overlap"
    if fam == "FLOW":
        return ["Saltmarsh Home Infusion"], [], [], None
    if fam == "CONFLICT":
        return [], ["Cobbleton Dental Group"], [], r"\$\s?35"
    if fam == "FINALE":
        m = [n.replace(" (as flagged)", "") for n in Q["FINALE"]["rehearsal"]["must_appear"]]
        return m, [], [], r"(?i)hold until cross-fund clearance|cross-fund (review|clearance)"
    raise SystemExit("unknown " + pid)

def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

def analyse(path):
    pid = os.path.basename(path).rsplit("_run", 1)[0]
    stamps, final, last_assist, skills, result, errs = [], None, "", [], None, []
    for line in open(path):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("timestamp"):
            stamps.append(ts(e["timestamp"]))
        t = e.get("type")
        if t == "assistant":
            txt = "".join(b.get("text", "") for b in e["message"]["content"] if b.get("type") == "text")
            if txt.strip():
                last_assist = txt
            for b in e["message"]["content"]:
                if b.get("type") == "tool_use" and b.get("name") == "Skill":
                    skills.append((b.get("input") or {}).get("skill", ""))
        elif t == "user":
            c = e.get("message", {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if b.get("type") == "tool_result" and b.get("is_error"):
                        errs.append(str(b.get("content"))[:200])
        elif t == "result":
            result = e
            final = e.get("result")
    final = final if final else last_assist
    must, d_reh, d_all, extra = spec(pid)
    # Tier-2 ad-libs run in a forked Tier-1 session that already loaded the skill
    skill_inherited = pid.startswith('T2-') and pid != 'T2-FINALE'
    missing = [n for n in must if n not in final]
    dec_reh = [n for n in d_reh if n in final]
    dec_all = [n for n in d_all if n in final]
    rai = [s for s in skills if "rai" in s.lower()]
    lat = (max(stamps) - min(stamps)) if len(stamps) > 1 else None
    dur = result.get("duration_ms") / 1000 if result and result.get("duration_ms") else None
    xok = True if not extra else bool(re.search(extra, final))
    ok = (not missing) and (not dec_reh) and xok and (bool(rai) or skill_inherited) and bool(final.strip()) and not (result or {}).get("is_error")
    return dict(file=os.path.basename(path), id=pid, run=int(path.rsplit("_run", 1)[1].split(".")[0]), ok=ok, missing=missing,
                decoy_rehearsal=dec_reh, decoy_strict=dec_all, extra_ok=xok, skills=skills, rai=bool(rai),
                lat_ts=lat, lat_dur=dur, final_len=len(final), errs=errs, is_error=(result or {}).get("is_error"))

def med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None

if __name__ == "__main__":
    rows = [analyse(p) for p in sorted(glob.glob(os.path.join(REH, "*_run*.jsonl")))]
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1)); sys.exit()
    for r in rows:
        print(f"{r['file']:28} ok={int(r['ok'])} rai={int(r['rai'])} lat_ts={r['lat_ts'] and round(r['lat_ts'],1)} dur={r['lat_dur'] and round(r['lat_dur'],1)} "
              f"missing={r['missing']} decoy={r['decoy_rehearsal']} strict_decoy={r['decoy_strict']} extra={r['extra_ok']} nerr={len(r['errs'])}")
    print()
    def grp(pid, runs=None):
        g = [r for r in rows if r["id"] == pid and (runs is None or r["run"] in runs)]
        return g, sum(r["ok"] for r in g), med([r["lat_ts"] for r in g]), med([r["lat_dur"] for r in g])
    print("SUMMARY (prompt, view: n, pass, median lat by timestamps, median by duration_ms)")
    for f in QK:
        for view, runs in (("all6", None), ("1-3", {1,2,3}), ("4-6", {4,5,6})):
            g, p, m, d = grp("T1-" + f, runs)
            print(f"T1-{f:9} {view:5} n={len(g)} pass={p} med_ts={m and round(m,1)} med_dur={d and round(d,1)}")
    for pid in sorted({r["id"] for r in rows if not r["id"].startswith("T1")}):
        g, p, m, d = grp(pid)
        print(f"{pid:14} all   n={len(g)} pass={p} med_ts={m and round(m,1)} med_dur={d and round(d,1)}")
