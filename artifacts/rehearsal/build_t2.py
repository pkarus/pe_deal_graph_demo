# Builds jobs_t2.json: each ad-lib resumes (forks) a passing Tier-1 session of its act; Finale runs fresh.
import json, subprocess, sys
from pathlib import Path
R = Path(__file__).resolve().parent
P = json.loads((R / "prompts.json").read_text())
res = [json.loads(l) for l in subprocess.run([sys.executable, str(R.parents[1] / "scripts/rehearsal_check.py"), "--all"], capture_output=True, text=True).stdout.splitlines()]
n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
jobs = [{"id": f"T2-FINALE_run{k}", "prompt": P["T2-FINALE"]} for k in range(1, n + 1)]
for a in ["SCORE", "PATH", "FLOW", "CONFLICT"]:
    ok = [r for r in res if r["prompt_id"] == f"T1-{a}" and r["pass"]]
    ok.sort(key=lambda r: r["transcript"], reverse=True)  # prefer the latest (clean server) runs
    for k, r in enumerate(ok[:n], 1):
        jobs.append({"id": f"T2-{a}_run{k}", "prompt": P[f"T2-{a}"], "resume": r["session_id"], "from": r["transcript"]})
(R / "jobs_t2.json").write_text(json.dumps(jobs, indent=1))
print([(j["id"], j.get("from")) for j in jobs])
