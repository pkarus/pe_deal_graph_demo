# R17 rehearsal summary (2026-10-22, 12:24-13:01 Warsaw)

Command per run, from demo_workspace/: `claude -p "<prompt>" --output-format stream-json --verbose --allowedTools "Bash(uv:*),Bash(python:*),Read,Glob,Grep,Skill"`. Tier-2 ad-libs add `--resume <passing Tier-1 session> --fork-session`, because the presenter does not `/clear` between a Tier-1 prompt and its ad-lib. The Finale runs as a fresh session. At most 3 runs in parallel. Latency is wall-clock per `claude -p` process, from latency.tsv. For T2-PATH_run1 and T2-FLOW_run1 it is taken from the transcript's result.duration_ms instead, because the runner was stopped. Checker: `python3 scripts/rehearsal_check.py --all`, which scans assistant text only. Must-appear and must-not-appear names come from data/golden/expected.json `rehearsal`. Tier-2 checks are row-based, per prompts.md "Expected".

## Results

| prompt | runs | passes | median s | max s | runs via warm server | failure reason |
|---|---|---|---|---|---|---|
| T1-SCORE set B, runs 4-6 (clean warm server) | 3 | 3 | 56.9 | 128.2 | 3/3 | - |
| T1-PATH set B, runs 4-6 (clean warm server) | 3 | 3 | 72.7 | 116.5 | 3/3 | - |
| T1-FLOW set B, runs 4-6 (clean warm server) | 3 | 3 | 58.0 | 76.8 | 3/3 | - |
| T1-CONFLICT set B, runs 4-6 (clean warm server) | 3 | 3 | 73.3 | 76.2 | 3/3 | - |
| T1-SCORE set A, runs 1-3 (server went stale) | 3 | 3 | 62.1 | 68.8 | 2/3 | - |
| T1-PATH set A, runs 1-3 (server went stale) | 3 | 3 | 95.2 | 160.1 | 1/3 | - |
| T1-FLOW set A, runs 1-3 (server went stale) | 3 | 2 | 79.9 | 82.6 | 1/3 | run2: missing: Cedar Row Partners, Harbor Lane Advisors |
| T1-CONFLICT set A, runs 1-3 (server went stale) | 3 | 2 | 85.1 | 147.0 | 1/3 | run2: missing: Pinewick Dermatology Partners, Ironvale Testing Group, Specialty Distribution |
| PARA-SCORE | 3 | 3 | 56.7 | 66.1 | 3/3 | - |
| PARA-PATH | 3 | 3 | 69.2 | 73.6 | 3/3 | - |
| PARA-FLOW | 3 | 3 | 51.4 | 54.1 | 3/3 | - |
| PARA-CONFLICT | 3 | 3 | 65.5 | 67.3 | 3/3 | - |
| T2-SCORE | 2 | 2 | 102.5 | 147.0 | 1/2 | - |
| T2-PATH | 2 | 1 | 93.9 | 121.1 | 0/2 | run2: expected fact not found |
| T2-FLOW | 1 | 1 | 106.7 | 106.7 | 0/1 | - |
| T2-CONFLICT | 0 | - | - | - | - | NOT RUN (orchestrator stop at 13:00) |
| T2-FINALE | 2 | 2 | 191.1 | 222.1 | 1/2 | - |
| PILOT-SCORE (run1 before fix, run2 after) | 2 | 1 | 72.1 | 113.6 | 1/2 | run1: no RAI skill |

## Verdict against section 9.3

- **Tier-1, G7 basis = set B, clean warm server:** all four acts PASS, 3/3 each. Every run loaded `rai-querying`, contained every golden name and no decoy. Medians: SCORE 56.9 s, PATH 72.7 s, FLOW 58.0 s, CONFLICT 73.3 s, all 90 s or less.
  - Set A passed only 10/12. FLOW run2 and CONFLICT run2 failed, and PATH's median was 95.2 s. This was environmental. At 12:37 the export fixer edited pe_deal_graph/export.py. That changed ask.py's server fingerprint, so later calls ran in-process alongside `make export`. Those calls hit `SnowflakeTableObjectsException`, and there was no `exports/` to fall back to. Claude refused to invent rows, which is correct behavior, but the run still fails the check.
- **Paraphrase:** PASS for all four acts, 3/3 each.
- **Tier-2:**
  - SCORE: 2/2 PASS.
  - FINALE: 2/2 PASS. Run1 was fully live. In run2 the live hop-evidence query came back empty, so it fell back to `finale_rescore` as CLAUDE.md says.
  - PATH: 1/2. Run2 hit the engine error "provided data streams do not exist" while `make export` was running.
  - FLOW: 1/1. Not enough runs for a verdict.
  - CONFLICT: NOT RUN.
- **NOT RUN, by orchestrator stop at 13:00:** T2-CONFLICT (0 runs), T2-FLOW run2 (killed 10 s after it started; partial transcript at killed_T2-FLOW_run2.jsonl.partial), and any third Tier-2 runs.

## Observations

- **Pilot:** before the CLAUDE.md fix, no skill was loaded. After it, `rai-querying` loaded in every Tier-1 and paraphrase run. The skill call added only a few seconds.
- **Parallel queuing:** wall time includes queuing on the single warm server when 3 runs execute at once. Example: T1-SCORE_run4 took 128 s, of which the query was 10 s and the API time 22 s. A sequential live demo will be faster than these medians.
- **Tier-2 ad-libs write PyRel:** ad-libs usually wrote a scratch PyRel script, which ran in-process, instead of filtering the hero rows. That is slower (58-147 s) and goes through the in-process engine path, which is where engine errors appeared.
