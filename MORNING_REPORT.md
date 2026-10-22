# Morning report: Northwind deal-graph demo

Last updated: 13:20 Warsaw (final, P9). If you read this later, check the gate table against STATE.json.

## 1. Verdict

**Verdict: READY WITH CAVEATS.** Gates G0-G6 passed. G7 passed with a note. G8 ran in reduced form (no engine) and passed its scope. G9 was not re-run formally. Tier-2 ad-libs are only partly rehearsed. Every act has an engine-free fallback.

**Live check at 13:18 (P9, through the warm query server):** `ask.py finale_rescore` returned exactly golden's Finale Tier A (Bayside 95, Larkspur 90, Saltmarsh 80, Quarry 75, Ashby Vale 75, Fenwick 70), with Tessmark Clinical Supply at 75 flagged "Conflict - cross-fund review" and off Tier A, in 13.6 s. `ask.py q_score` returned golden's 6 Tier A companies in order, in 10.2 s.

**Engine state:** left running and warm for testing; auto-suspends after 30 idle minutes. Run `make keepalive` during the meeting, and suspend with `.venv/bin/rai reasoners suspend --type Logic --name pe_demo_logic` when done (stop the server first with `.venv/bin/python demo_workspace/ask.py --serve-stop`; see RUNBOOK "After the demo").

**Query server:** running (started by `make warm` at 13:14, 127.0.0.1 only, log demo_workspace/scratch/.ask_server/server.log). `make warm` at 13:13-13:18 took 4 min 9 s: auth OK, engine READY, server started, first pass q_score 42.5 s, q_path 27.8 s, q_flow 19.7 s, q_conflict 24.5 s, finale_rescore 14.9 s; ready pass 10.7 / 27.8 / 17.6 / 24.2 / 14.4 s; every name check OK.

**Demo risk:** live Finale authoring runs a different rule set in a separate process and can cause empty reads on the shared model. Rely on the 3-minute cutoff and the prebuilt `finale_rescore`.

This was a daytime run. The overnight window was lost waiting on the Phase 0 question. The timebox restarted at 07:46, the hard stop moved to 14:00, and your testing starts at 13:35.

## 2. Gates

| Gate | Status | Attempts | Evidence | Commit |
|---|---|---|---|---|
| G0 Preflight and bootstrap | PASS | 2 | gates/G0.md | b3e07e3 |
| G1 Hero questions and critic | PASS | 2 | gates/G1.md | 6330f15 |
| G2 Signal data loaded | PASS | 1 | gates/G2.md | d1de7ec |
| G3 Ontology | PASS | 1 | gates/G3.md | 24a56ce |
| G4 Rules, graphs, queries, tests | PASS | 1 | gates/G4.md | 5daeb91 |
| G5 Noise and decoys | PASS | 1 | gates/G5.md | ed8ecc6 |
| G6 Export, explorer, script | PASS | 1 | gates/G6.md | 917d449 |
| G7 Claude Code surface (transcripts) | PASS WITH NOTE (Tier-1 clean runs 4-6; no `make export` or edits during the demo, warm server up) | 1 | gates/G7.md | c899cde |
| G8 Cold rehearsal | PARTIAL PASS (reduced, no engine: cold worktree setup, all 5 `--from-exports` fallbacks, explorer and script clean; live path covered by G7 and the P9 live check) | 1 | gates/G8.md | 19b40ff |
| G9 Review board | NOT RUN formally; four early reviews ran and their BLOCKER/MAJOR findings were fixed | 0 | handoffs/25, 26, 34, 35 | none |

G9 detail: all four reviewers ran early, before rehearsal, and their BLOCKER and MAJOR findings were fixed. None was re-reviewed afterward.

| Reviewer | Early result | Fixed |
|---|---|---|
| R19a PE managing director | FAIL: 2 BLOCKER, 7 MAJOR, 9 MINOR | Yes: prose (cold open, finale wording, hold semantics) and the Pinewick rename |
| R19c data realism | FAIL: 0 BLOCKER, 3 MAJOR, 13 MINOR | Yes: data fixer (tenures, add-ons, EV/EBITDA) |
| R19b technical | FAIL: 0 BLOCKER, 3 MAJOR, 15 MINOR | M1 and M2 fixed in code. M3 (Finale extension point) was handled only through CLAUDE.md building blocks and the fixed 3-minute cutoff, not new code. |
| R19d demo ops | FAIL: 1 BLOCKER, 6 MAJOR, 6 MINOR | Yes: warm timing, keepalive, warm query server, --from-exports, one Finale cutoff, /clear per act, venue checklist |

## 3. The four hero questions and the Finale

Names are the final fictional ones. SQL-vs-KG numbers are from gates/G5.md section 4.

- **Act 1, Q-SCORE: six names to call Monday.** Tier A is Larkspur Revenue Partners 90, Bayside Pediatric Therapy Group 85, Saltmarsh Home Infusion 80, Quarry Records Retrieval 75, Tessmark Clinical Supply 75, Fenwick Food Safety Labs 70. Saltmarsh and Fenwick have no CRM coverage.
  - SQL: a keyword screen returns 206 candidates. Its top 3 are decoys (Cobalt Urgent Care, Pembrook Veterinary, Linden Hollow Senior Care), the best real name is 6th, and it misses 2 of 6.
  - KG: 6 Tier A with score components, and the near miss (Ashby Vale, 65) shows why it is Tier B.
- **Act 2, Q-PATH: who gets us an edge.** Larkspur in 3 hops (0.700, Priya Raman to Sofia Brandt to Nathan Cole to CEO Ruth Adeyemi). Bayside in 2 hops (0.600, via Marcus Whitfield and Elena Marsh). Saltmarsh is cold.
  - SQL: a date-blind join returns 1 row, a false intro (Tom Harlowe to Victor Hale via Varnell Lab Services, who never overlapped). A CRM search shows one neutral meeting and implies "we know Coppervale".
  - KG: 2 warm paths and 3 cold rows. Tenure overlap rejects the false intro.
- **Act 3, Q-FLOW: who bridges deal flow.** Cedar Row Partners is the top bridge (14 touchpoints). Harbor Lane Advisors is second with only 1 touchpoint in 24 months, the coverage gap.
  - SQL: a deal-count league table puts Brayford Capital Markets first (40 deals) and Harbor Lane 10th.
  - KG: betweenness puts Brayford outside the top 5.
- **Act 4, Q-CONFLICT: before we bid on Tessmark Clinical Supply.** Pinewick Dermatology Partners (Fund III) is a 1-link cross-fund conflict. Ironvale Testing Group is 2 links, informational. Specialty Distribution goes from 32.08% to 36.67% with the $55M check, over the 35% guideline by $20M.
  - SQL: an ownership screen returns Pinewick plus the decoy Cobbleton (sold 2020) and misses Ironvale. A per-niche concentration screen shows all 6 areas under guideline (max 12.5%) and misses the breach.
  - KG: 2 exposures and the only breach.
- **Finale: two sentences of new rules re-score the list.** Bayside moves to first at 95. Ashby Vale rises into Tier A at 75. Tessmark keeps 75 but is flagged "hold until cross-fund clearance" and is off the call list.
  - SQL: no route without rewriting the rules and the path logic.
  - KG: one pass re-scores everything.

## 4. How to run it

From RUNBOOK.md, in the repo root:

```
[ -f raiconfig.yaml ] || cp /Users/piotrkraus/rai-repos/pe_deal_graph_demo/raiconfig.yaml .
uv sync --python 3.13
make warm            # then, in its own terminal: make keepalive
open artifacts/deal_graph_explorer.html artifacts/demo_script.html
cd demo_workspace && claude
```

- T-30: `make warm`. It checks auth, resumes the engine, starts the warm query server and runs every hero query. Look for `make warm: OK`.
- T-10: `make warm` again, then start `make keepalive` in its own terminal and leave it running. Never leave more than 25 minutes without a query or a ping.
- Type `/clear` before each act's first prompt and before the Finale. Never type it between a prompt and its ad-lib. Prompts are in demo_workspace/prompts.md.
- Auto fallback: if a live query hits a lock, an empty graph or a 503, `ask.py` retries once after 20 s and then shows the precomputed rows from exports/.
- Manual fallback: `uv run python ask.py --from-exports <fn>` (no engine, no Snowflake). Then the explorer, which needs no network.
- Finale: one live attempt, at most 3 minutes, then type `use the prebuilt version`.
- You are testing on this laptop. The engine pe_demo_logic and the warm query server are left warm for you. Nothing else should touch the engine while you test: no `make test`, `make export` or `make load`.

## 5. Decisions to check

1. **Degrade step 1.** Q-ADDON was swapped out for Q-CONFLICT as hero Act 4 (08:27), because R04 found Q-ADDON's reasoning necessity too weak. Q-ADDON and Q-COMPETE are backups.
2. **raiconfig deployment block commented out.** In relationalai 1.27.1 any deployment block turns on deploy mode, and queries then read pre-deployed tables. Interactive engine queries are what the demo needs.
3. **Bootstrap deviations.** You ran the bootstrap in Snowsight. R01 had struck GRANT USAGE ... TO APPLICATION RELATIONALAI and OPERATE on the warehouse as unnecessary. The role RAI_DEMO_PE is owned by ACCOUNTADMIN and has no direct grant to your user. It is reachable through ACCOUNTADMIN and SYSADMIN, and G0 accepted this.
4. **Golden Pinewick rename.** R19a found that the Finale riser (Ashby Vale, a dental DSO) looked like a Fund III dental holding. The holding became Pinewick Dermatology Partners in the Dermatology niche. Six name strings in golden/expected.json changed, with no number or order change. The G5 gatekeeper signed it off.
5. **Concurrency cap raised to 8 agents** (2 on the engine) at your 08:05 request. Concurrent writers locked the engine several times, and rehearsal runs 1-3 degraded for that reason.
6. **Early reviews.** All four reviewers ran before rehearsal and were not re-run (section 2).
7. **Wexley Medical Linen flag semantics.** The oracle flags it as conflicted with a Tier C score of 25. The golden answer only says "take off Tier A". It is kept as a superset flag outside Tier A, and `finale_rescore` shows only conflicted targets that are Tier A.
8. **Deploy mode not adopted.** On 1.27.1 it returned 0 rows or a GraphOutputMissing error, needs EXECUTE TASK on the account, and the live Finale would fail. Its reads took 4.8 s versus 64 s cold when it did work.
9. **relationalai 1.36.0 upgrade deferred.** It passed all checks (67 rules, 48 graph, 44 tests) with identical outputs and no measurable speed-up. It is a one-line pin change, and I did not adopt it mid-run.
10. **Demo surface.** Claude Code in demo_workspace/ on this laptop. There is no Snowsight, and Cowork is out of scope. The warm query server (first query 64 s down to about 11 s) replaced "every act in a new process".

## 6. Degradations applied

- Step 1 only (08:27): Q-ADDON to backup, Q-CONFLICT promoted to Act 4.
- Rehearsal cut short at 13:00 to free the engine for the export. T2-CONFLICT was NOT RUN. T2-PATH, T2-CONFLICT and T2-FLOW are marked optional with fallbacks.
- No Cowork or Snowsight surface.

## 7. Open MINOR findings

- Data: OWNERSHIP has 265 rows against a target of 600. Some signal equity checks are 25-45% of the fund. Acquired add-ons have no OWNERSHIP rows. Tier B and the near-miss lists shifted. Remaining R19c minors cover ownership volume, 2007-09 vintages and m6-m12.
- 20 placeholder-replacement names were not web-checked because of a search quota. Run a collision check before any external use.
- The explorer strikes through conflicted names. It should read "hold until cross-fund clearance".
- A stale "Pinewick Dental Partners" remains in a comment in data/naive_sql/q_conflict.sql and in scripts/audit_realism.py.
- Decoy leakage is possible in Tier-1 and paraphrase transcripts, and the check must cover both.
- Tier-2 ad-libs often write slow scratch PyRel (58-147 s) instead of filtering hero rows. The Finale live script against the server lock is untested.
- A flake was seen once: a run returned zero conflict-reach rows after a stream resync. An invariant check and a 20 s retry now guard it.
- The warm-server fingerprint includes export.py, so editing it makes the server stale. Do not edit it while testing.
- The Makefile lacks check-rules and check-graphs targets. No whitespace regions were built.
- Housekeeping: tests/out is not gitignored (left out of the final commit). scripts/scout/out/dev* folders are stale. Dropped SCOUT_* tables may leave data streams behind.
- Engine resume time from SUSPENDED is not measured.

## 8. Rehearsal stats

R17, 12:24-13:01, via `claude -p`. Set B (clean warm server) is the G7 basis. Set A hit a stale server after the 12:37 export.py edit.

| Prompt | Runs | Pass | Median s | Max s |
|---|---|---|---|---|
| T1 SCORE (set B) | 3 | 3 | 56.9 | 128.2 |
| T1 PATH (set B) | 3 | 3 | 72.7 | 116.5 |
| T1 FLOW (set B) | 3 | 3 | 58.0 | 76.8 |
| T1 CONFLICT (set B) | 3 | 3 | 73.3 | 76.2 |
| T1 SCORE / PATH / FLOW / CONFLICT (set A) | 3 each | 3 / 3 / 2 / 2 | 62.1 / 95.2 / 79.9 / 85.1 | 68.8 / 160.1 / 82.6 / 147.0 |
| Paraphrase SCORE / PATH / FLOW / CONFLICT | 3 each | 3 each | 56.7 / 69.2 / 51.4 / 65.5 | 66.1 / 73.6 / 54.1 / 67.3 |
| T2 SCORE | 2 | 2 | 102.5 | 147.0 |
| T2 PATH | 2 | 1 | 93.9 | 121.1 |
| T2 FLOW | 1 | 1 | 106.7 | 106.7 |
| T2 CONFLICT | 0 | NOT RUN | none | none |
| T2 FINALE | 2 | 2 | 191.1 | 222.1 |

The set A failures were environmental: Claude refused to invent rows, which is correct. Wall times include queuing when 3 runs shared the one server, so a sequential live demo should be faster.

## 9. Cost

- Engine pe_demo_logic (HIGHMEM_X64_S) has run since about 08:20 with a 30-minute auto-suspend. It is NOT suspended: it is intentionally left running and warm for your testing, with the warm query server up. Suspend it when you finish:

```
.venv/bin/python demo_workspace/ask.py --serve-stop
.venv/bin/rai reasoners suspend --type Logic --name pe_demo_logic
.venv/bin/rai reasoners get --type Logic --name pe_demo_logic     # expect SUSPENDED
```

- Warehouse RAI_DEMO_PE_WH is X-Small with 60 s auto-suspend. Usage is small (loads and counts). STATE.json engine_hours_estimate was never filled in, so check the account usage views for exact credits.
- Stray objects to clean up:
  - RAI models `pe_deal_graph_perf_a` and any `*_deploy` model (for example `pe_deal_graph_deploy`) in pe_demo_logic.
  - Schema RAI_DEMO_PE_DEALS.DEAL_GRAPH_DEPLOY, if PerfB created it.
  - Table `SMOKE_TEST` in RAI_DEMO_PE_DEALS.DEAL_GRAPH. It is outside the dataset, and the G5 gatekeeper listed it as a stray.

## 10. Your to-dos

- `chmod 600 ~/.snowflake/pat_token_pe_demo`
- Check the Snowflake network policy for the venue (RUNBOOK "Venue network"). A PAT is usually accepted only from allowed IPs.
- The PAT expires 2026-10-29. Regenerate it the day before any later demo.
- After the demo, upgrade relationalai to 1.36.0 (pin change, then `uv lock && uv sync`) and re-test deploy mode.
- Optional: add the direct grant `GRANT ROLE RAI_DEMO_PE TO USER <your_user>;`.

## 11. Cleanup when the deal is done (text only, not run)

Delete the RAI engine first, from the repo root:

```
.venv/bin/rai reasoners delete --type Logic --name pe_demo_logic
```

Then, as ACCOUNTADMIN in Snowsight:

```sql
DROP DATABASE IF EXISTS RAI_DEMO_PE_DEALS;
DROP WAREHOUSE IF EXISTS RAI_DEMO_PE_WH;
DROP ROLE IF EXISTS RAI_DEMO_PE;
```

Also remove the PAT file (`rm ~/.snowflake/pat_token_pe_demo`) and revoke the PAT in Snowsight.
