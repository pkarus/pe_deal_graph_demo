"""R17 rehearsal runner: runs claude -p jobs from demo_workspace/, at most N in parallel.

Job file: JSON list of {"id": "<prompt_id>_run<k>", "prompt": "...", "resume": "<session id>"|null}.
Saves artifacts/rehearsal/<id>.jsonl and appends "<id>\t<wall seconds>\t<rc>" to latency.tsv.
A "resume" job continues that Tier-1 session with --fork-session (same context as the presenter,
who never /clears between a Tier-1 prompt and its ad-lib); the original transcript stays untouched.
Usage: python scripts/rehearsal_run.py jobs.json [--par 3] [--deadline HH:MM]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "demo_workspace"
REH = ROOT / "artifacts" / "rehearsal"
TOOLS = "Bash(uv:*),Bash(python:*),Read,Glob,Grep,Skill"


def run(job, deadline):
    if deadline and datetime.now().strftime("%H:%M") >= deadline:
        print(f"SKIP {job['id']} (past deadline {deadline})", flush=True)
        return
    cmd = ["claude", "-p", job["prompt"], "--output-format", "stream-json", "--verbose", "--allowedTools", TOOLS]
    if job.get("resume"):
        cmd += ["--resume", job["resume"], "--fork-session"]
    out = REH / f"{job['id']}.jsonl"
    t0 = time.monotonic()
    with out.open("w") as fh:
        try:
            rc = subprocess.run(cmd, cwd=WS, stdout=fh, stderr=subprocess.STDOUT, timeout=600).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    dt = time.monotonic() - t0
    with (REH / "latency.tsv").open("a") as fh:
        fh.write(f"{job['id']}\t{dt:.1f}\t{rc}\t{datetime.now().isoformat(timespec='seconds')}\n")
    print(f"DONE {job['id']} {dt:.1f}s rc={rc}", flush=True)


def main():
    args = sys.argv[1:]
    jobs = json.loads(Path(args[0]).read_text())
    par = int(args[args.index("--par") + 1]) if "--par" in args else 3
    deadline = args[args.index("--deadline") + 1] if "--deadline" in args else None
    REH.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=min(par, 3)) as ex:
        list(ex.map(lambda j: run(j, deadline), jobs))


if __name__ == "__main__":
    main()
