# RUNBOOK: Northwind deal-graph demo

Owner: R14 Demo Workspace. Status: v3 (R20 demo-ops fixes per R19d: warm timing, keepalive, query server, engine-free fallback, one Finale cutoff, `/clear` per act, venue network), synced to QUESTIONS.md v2 and the final fictional names.

All data is synthetic, as of 2026-10-01. Engine: `pe_demo_logic` (HIGHMEM_X64_S, auto-suspend 30 min). Snowflake role `RAI_DEMO_PE`, database `RAI_DEMO_PE_DEALS.DEAL_GRAPH`.

> **PAT EXPIRES 2026-10-29.** raiconfig.yaml authenticates with a programmatic access token (created 2026-10-22, 7-day life). On or after 2026-10-29 every live act fails. For any demo on or after 2026-10-28, regenerate it the day before: in Snowsight, as the raiconfig user, create a new PAT and write it to the `token_file_path` in raiconfig.yaml (`~/.snowflake/pat_token_pe_demo`), then `chmod 600 ~/.snowflake/pat_token_pe_demo` and run `make warm`. `make warm` checks auth first with `rai connect` and prints the error verbatim.

## The 5 commands (fresh checkout to live demo)

Run from the root of the checkout you will present from: the main checkout, or a fresh `git worktree` (for example `git worktree add ../pe_demo_run HEAD && cd ../pe_demo_run`, or one under `.claude/worktrees/`).

```bash
# 1. Copy the gitignored RAI config into this checkout (a fresh worktree has none; nothing works without it).
#    The first entry of `git worktree list` is always the main checkout. Safe to re-run, and safe in the main checkout.
[ -f raiconfig.yaml ] || cp "$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)/raiconfig.yaml" .
#    Absolute-path equivalent: [ -f raiconfig.yaml ] || cp /Users/piotrkraus/rai-repos/pe_deal_graph_demo/raiconfig.yaml .

# 2. Create the pinned venv (Python 3.13, relationalai 1.27.1) from uv.lock.
uv sync --python 3.13

# 3. At T-30 and again at T-10: check auth, resume the engine, start the warm query server, run every hero query.
make warm
#    Then, in its own terminal, until the Q&A ends (Ctrl-C to stop):
make keepalive

# 4. Open the Deal Graph Explorer and the run-of-show (offline, single files).
open artifacts/deal_graph_explorer.html artifacts/demo_script.html

# 5. Start Claude Code for the live acts (pre-launch it at T-15, see the timeline).
cd demo_workspace && claude
```

Checks after each step:

1. `test -f raiconfig.yaml && echo ok`. The token path in it is `~`-relative (`~/.snowflake/...`), so the copy works for the same user on the same machine. Presenting from another laptop: that laptop needs its own raiconfig.yaml and token file at the same path (and its own PAT if the user differs). Never commit either.
2. `.venv/bin/python -c "import relationalai, importlib.metadata as m; print(m.version('relationalai'))"` prints `1.27.1`.
3. `make warm` prints, in order: `auth OK`, `engine pe_demo_logic READY`, `query server: started` (or `already running`), one `warm <fn>` line and one `ready <fn>` line per hero query with its time and `names OK`, then `make warm: OK - ...`. The `ready` times are what each live act will take. Any `make warm: FAIL - ...` line names the cause and the fix; re-run after fixing. A `NAME CHECK FAILED` line means the live answer no longer matches data/golden/expected.json (for example after a data reload): do not present that act live; use its fallback. `make keepalive` prints one timestamped line per ping (`engine awake, ping took N s`); a `ping FAILED` line means re-run `make warm`.
4. The explorer opens on the overview with no network. Both HTML files and `exports/` must be committed (G7); `make artifacts` rebuilds them from `exports/` only.
5. In Claude Code, type the prompts from `demo_workspace/prompts.md` in order, with `/clear` before each act. Claude Code reads `demo_workspace/CLAUDE.md` and has the RAI skills from the `rai@RelationalAI` plugin (`demo_workspace/.claude/settings.json`, which also raises the Bash timeout to 5 minutes so a slow query is never cut off at 2).

## Presenter timeline

| When | Do | Pass when |
|---|---|---|
| T-1 day | Check the PAT date (box above). Run the venue-network checklist below. Full rehearsal from this RUNBOOK. Freeze the data: no `make data`, `make load` or `make export` from now on (a reload forces a 1.5-2.5 min stream re-sync and can change names). | `make warm: OK` from the venue network or the hotspot |
| T-30 | `make warm` (surfaces auth, network and data problems while there is time to fix them). Open the explorer (Overview) and this script. Do Not Disturb on, Slack and mail closed, power connected, terminal font 18 pt or larger. | `make warm: OK` |
| T-15 | Pre-launch Claude Code: `cd demo_workspace && claude`, accept the folder-trust prompt and any plugin prompt, and run one throwaway prompt: `Run uv run python ask.py --list`. Keep this session open for the demo. Open a second terminal in `demo_workspace/` for fallbacks. Bookmark the explorer `#addon` view. | the throwaway prompt answers with no permission prompt |
| T-10 | `make warm` again (the engine suspends after 30 idle minutes; this one reuses the running query server, so it is quicker). Then start `make keepalive` in its own terminal and leave it running. In Claude Code, type `/clear`. | `make warm: OK`, first `engine awake` line |
| During | Never let more than 25 minutes pass with neither a query nor a keepalive ping. Type `/clear` before each act's Tier-1 prompt and before the Finale prompt (never between a prompt and its ad-lib). | each act answers within its slot |
| After the Q&A | Ctrl-C the keepalive terminal, stop the query server, suspend the engine (see "After the demo"). | `SUSPENDED` |

## Venue network

Every live act needs two services: the Anthropic API (Claude Code) and Snowflake (`ajb85638.snowflakecomputing.com:443`, for RAI). The explorer and the script need neither.

- [ ] Once, outside the demo path (Snowsight, ACCOUNTADMIN): check which network policy and authentication policy apply to the raiconfig user (`SHOW PARAMETERS LIKE 'NETWORK_POLICY' IN USER <user>;` and `DESCRIBE NETWORK POLICY <name>;`). By default Snowflake accepts a PAT only from a user covered by a network policy. If that policy allowlists office or VPN egress IPs only, the venue Wi-Fi fails auth even with a valid PAT. Note the allowed IP ranges here: ______
- [ ] The day before, or at T-30 at the latest: run `make warm` from the venue network itself. A `network policy` / `IP not allowed` error or a connect timeout in its verbatim output means this network will not work.
- [ ] Hotspot plan: a charged phone with a data plan, tethering tested with `make warm` beforehand (and allowed by the network policy). If the venue Wi-Fi fails, switch to the hotspot and re-run `make warm`.
- [ ] If a VPN is required for Snowflake, connect it before `make warm` and keep it on for the whole meeting.
- [ ] Claude Code: open `claude` once on the venue network (the T-15 pre-launch covers it).
- [ ] If the network drops during the demo: do not retry live. Go to the engine-free fallback for the act (`--from-exports`, then the explorer).

## Latency

- The first query in a new Python process costs 45-75 s (model compile and engine setup), even on a warm engine. Every live act used to run in a new process, so each act paid it.
- `make warm` therefore starts a **warm query server**: one long-lived local process (`ask.py serve`, 127.0.0.1 only, token-protected, state and log in `demo_workspace/scratch/.ask_server/`) that keeps the model compiled. `uv run python ask.py <fn>` sends the request to it and prints the same table, ending with `(ran in N s on the warm query server)`. If the server is not running, belongs to another checkout, or the model code changed since it started, `ask.py` runs in-process exactly as before.
- Measured 2026-10-22 11:05 (engine shared with other build agents, so treat as upper bounds): first pass in the server q_score 64.2 s, q_path 46.5 s, q_flow 20.8 s, q_conflict 27.0 s, finale_rescore 67.7 s; second ("ready") pass q_score 10.8 s, q_path 38.8 s, q_flow 24.6 s, q_conflict 28.8 s, finale_rescore 13.5 s; `uv run python ask.py q_score` from the presenter folder 11.7 s wall clock on the warm server; keepalive ping 3.5 s. The server removes the first-query cost; the remaining time is the 5-12 engine round trips (about 3 s each) inside q_path, q_flow and q_conflict.
- Expected per act with the server: the `ready` time printed by `make warm`, plus Claude's own turn time. Without the server: 45-75 s per act plus Claude's turn time. Claude Code's Bash timeout is raised to 5 minutes in `demo_workspace/.claude/settings.json`, so a slow act is never killed at 2 minutes and retried on stage.
- Not covered by the server: the Finale's live-authored scratch script runs in its own process, so it pays the first-query cost (about 1 minute) plus Claude's authoring time. That is why the Finale has a hard cutoff.
- Concurrent model writers lock the engine ("model is currently locked by active write transaction(s)"). On demo day nothing else may use the engine: no `make test`, `make export` or scratch scripts from other terminals. Whether the Finale's live scratch script briefly locks the server's queries has not been tested; R17 should run the Finale and then an act through the server.
- Server commands: `.venv/bin/python demo_workspace/ask.py --serve-status`, `--serve-stop`, `--serve-start`.
- Engine resume from SUSPENDED: not yet measured (R19d m6). Time `rai reasoners resume --type Logic --name pe_demo_logic --wait` once at a rehearsal and write it here: ______. If a mid-demo suspend happens anyway, go to the engine-free fallback for the current act and re-run `make warm` in the second terminal.

## Show order (PROMPT.md 7.5)

Cold open, model overview in the explorer, Act 1 Q-SCORE, Act 2 Q-PATH, Act 3 Q-FLOW, Act 4 Q-CONFLICT, Finale, close (QUESTIONS.md v2). Q-ADDON is a backup ad-lib only. `HERO_QUERIES` in `pe_deal_graph/queries.py` is the authoritative order. Type `/clear` in Claude Code before each act's Tier-1 prompt and before the Finale prompt.

## Fallback per act

If Claude Code stalls (no answer after about 90 s), wanders, or answers wrong, do this, in order:

1. Say "let me pull the governed version" and type in Claude Code: `Run uv run python ask.py <function> and show the result as a table with the why for each row.`
2. If RAI, Snowflake or the network is down (step 1 fails with an engine, auth or network error), type in Claude Code: `Run uv run python ask.py --from-exports <function> and show the result as a table with the why for each row.` It prints the same rows from `exports/` with no engine and no Snowflake, labelled "PRECOMPUTED". Claude stays the interface. Say "this is the governed export from this morning".
3. If Claude Code itself is down: in the second terminal, `cd demo_workspace && uv run python ask.py --from-exports <function>` (or without `--from-exports` if the engine is up) and talk over the printed table.
4. If everything else fails: switch to the explorer view for the act. It is built from `exports/`, the same numbers, and needs no network.

| Act | Function | Explorer view |
|---|---|---|
| 1 Q-SCORE | `q_score` | Scorecard |
| 2 Q-PATH | `q_path` | Warm path |
| 3 Q-FLOW | `q_flow` | Deal flow |
| 4 Q-CONFLICT | `q_conflict` | Conflict check (centered on Tessmark Clinical Supply) |
| Finale | `finale_rescore` | Scorecard, Finale toggle |
| Backup Q-ADDON | `q_addon` | Add-on map (hidden tab, `#addon`); `--from-exports q_addon` works only if `exports/q_addon.json` exists |

**Finale cutoff (one rule, same in CLAUDE.md and the script):** the live rule gets one attempt and at most 4 minutes (the rehearsal median was 191 s). Fall back after the first failure (an error, an empty or partial table, a ranking that looks wrong) or at 4 minutes on the clock, whichever comes first. At 4:00, press Esc and type `use the prebuilt version`. Claude then runs `finale_rescore` (step 1; with no engine, step 2 with `--from-exports finale_rescore`). Say "here is the same rule, prebuilt". Its answer is identical by construction. The flagged row is "hold until cross-fund clearance": it keeps its score and stays off the Tier A call list until the conflicts committee clears it. Never call it a dropped deal.

If asked about data boundaries: the data, the model and the reasoning run inside the customer's Snowflake account; Claude sees only the result rows of the queries it runs. Do not say "no data leaves".

## Repo hygiene

`demo_workspace/scratch/` holds live PyRel scripts written during the demo and must be gitignored (line for `.gitignore`: `demo_workspace/scratch/`). R01 owns `.gitignore`; the orchestrator adds it.

## After the demo

Stop the keepalive (Ctrl-C in its terminal), stop the warm query server, and suspend the engine (it would otherwise idle for 30 minutes before auto-suspend):

```bash
.venv/bin/python demo_workspace/ask.py --serve-stop
.venv/bin/rai reasoners suspend --type Logic --name pe_demo_logic
.venv/bin/rai reasoners get --type Logic --name pe_demo_logic     # expect SUSPENDED
```

A presenter worktree can be removed with `git worktree remove ../pe_demo_run` (delete its `raiconfig.yaml` first or pass `--force`; the file is gitignored).

## Query interface contract

R11 implements exactly these names in `pe_deal_graph/queries.py`. `demo_workspace/CLAUDE.md`, `demo_workspace/ask.py`, `make warm`, R13 export and R17 rehearsal call them by name. Names are per question, not per act number, so a question swap or reorder never renames a function.

| Function | Status | Question (QUESTIONS.md) | Returns (one row per answer entity, ranked) |
|---|---|---|---|
| `q_score()` | required | Q-SCORE: Fund IV Tier A list | Tier-A companies: name, score, fit, readiness, access, tier, in_crm, why |
| `q_path()` | required | Q-PATH: warmest path to each top-three CEO and the owner's board designee | one row per target and decision maker (or per hop): target, decision_maker, role, hops, strength, path, why; a cold target has an explicit cold row |
| `q_addon()` | optional backup | Q-ADDON: Ironvale Testing Group add-ons | candidates: name, similarity, shared_links, new_states, why |
| `q_conflict()` | required (Act 4) | Q-CONFLICT: Tessmark Clinical Supply conflict and concentration | conflicts and the concentration result: entity, distance, fund, verdict, why |
| `q_flow()` | required | Q-FLOW: deal-flow control and coverage gap | betweenness top 5 only: name, betweenness, thesis_deals, our_touchpoints, coverage_gap, why |
| `finale_rescore()` | required | Finale: warm-path points plus conflict flag, re-score | Tier-A list after the finale rules, plus the conflicted target flagged: name, score, change, flag, why |
| `q_compete()` | optional | Q-COMPETE backup | targets: name, sponsor, evidence, why |

Rules for every function:

1. Zero arguments, module-level, importable with `import pe_deal_graph.queries`. The first docstring line is the business question in MD voice (Claude Code and `ask.py --list` show it).
2. Returns a pandas DataFrame, or a dict of label to DataFrame for a multi-part answer. Column names above are guidance; a `name` (or `target`) display-name column and a `why` column are mandatory. `why` holds the evidence in business language (components with dates, hops with tenure overlaps, shared customers, deal counts).
3. Answer rows only, 10 or fewer per frame where the spec allows, deterministically ordered (tie-breaks per QUESTIONS.md). Rehearsal fails a run whose transcript contains a decoy name, so decoys appear only where the answer is about them (the finale's conflicted row, carried with its flag).
4. Idempotent and side-effect free across calls: `finale_rescore()` must not change what `q_score()` returns afterwards.
5. `HERO_QUERIES`: a module-level tuple of the hero function names in demo order, for example `("q_score", "q_path", "q_flow", "q_conflict", "finale_rescore")`. `make warm` runs exactly this tuple.

Check the contract without the engine: `.venv/bin/python demo_workspace/ask.py --check`.

Automatic fallback: if a live hero query hits a missing graph output, an empty frame, an engine lock or a 503, `ask.py` retries once after 20 s, then prints "Live query unavailable, showing precomputed result from exports" and shows the `--from-exports` rows for the same function (or a clear message if `exports/` is missing).
