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

## Local-only synthetic scale fixtures

`data/generate.py --scale` is separate from the signal/noise demo modes. It writes
all 17 existing CSV schemas and a deterministic `MANIFEST.json` into a **new**
directory. It refuses existing directories, paths inside `data/csv` or
`data/golden`, mixed demo/scale flags, and scale-only options without opt-in.
It never loads Snowflake or imports/runs the RAI model. Existing finite demo ID
pools, row caps, source configuration, and golden stories are unchanged.

```bash
# Generate into a NEW directory (data/scale_10k already contains the validated fixture).
env -u DEBUG .venv/bin/python data/generate.py --scale --people 10000 --workplace-size 8 --seed 42 --out data/scale_10k_new
# Read-only local validation of the prepared fixture:
env -u DEBUG .venv/bin/python data/generate.py --scale-check --out data/scale_10k
# Offline regression tests:
env -u DEBUG .venv/bin/python -m pytest tests/test_scale_generator.py -q
```

The generated names use a local seeded RNG; topology is a fixed deterministic
construction independent of the seed. All scale IDs have their own prefix and
nine-digit numeric suffix, avoiding the demo's finite shuffled ID pools.
The fixture uses K1 workplace overlap (Board roles starting 2020-01-01, open
through fixed AS_OF 2026-10-01); K2 deal and K3 CRM inputs are empty. Reference
sponsor/fund rows support the existing oracle, but there are no OurSeed members.
This is a sparse relationship/path fixture, not a replacement for the demo's
business-question stories or a realistic connected-network benchmark.

People `SCALE_P000000000` through `SCALE_P000000005` form an isolated six-person
chain. Each adjacent pair shares its own two-person workplace, so no workplace
can shortcut the chain. From `SCALE_P000000000`, targets ending `001` through
`005` have exact shortest distances 1–5; the route is the ascending prefix of
that chain. Person `SCALE_P000000006` has its own workplace and is unreachable.
All remaining people belong to one bounded workplace each. The default size is
8; `--workplace-size` accepts 2–32. Companies have distinct IDs and are never
collapsed under one common employer. No deal or CRM links join the components.

For N people and workplace cap k, let q,r = divmod(N-7,k). There are N+4 roles,
6+ceil((N-7)/k) companies, and exactly `5 + q*k*(k-1)/2 + r*(r-1)/2`
unordered Knows connections. At k=8:

| People | Roles | Expected connections |
| ---: | ---: | ---: |
| 10,000 | 10,004 | 34,977 |
| 100,000 | 100,004 | 349,977 |
| 1,000,000 | 1,000,004 | 3,499,977 |

These are O(N*k) connections, not O(N²): at fixed k, degree and component size
stay bounded. A chain member has at most two roles; every bulk person has one.
Adding future roles, bridges, deal participants, or CRM edges requires renewed
oracle checks because those can change density and shortest paths.

Generation streams rows and file hashes; it does not allocate all people,
roles, or edges in memory. The same generator accepts 100K and 1M with the
`--people` option and a new output directory. CSV storage is approximately
linear (about 19 MB / 193 MB projected from the 10K run, not measured).
The existing independent oracle materializes pandas data, edge evidence and a
NetworkX graph; validation therefore has substantial O(N+E) memory overhead.
Only 10K has been validated here. Before 1M oracle validation, budget memory or
prepare a separately reviewed streaming/component-wise validator. Do not run
all-pairs distances: planted checks need only one source BFS.

Validated local 10K output in `data/scale_10k`: 1,929,728 CSV bytes;
1,934,372 total bytes including manifest (18 files). The existing oracle confirms
34,977 connections, maximum degree 7, largest component 8, exact distances 1–5,
unreachable handling, and every example route edge at threshold 0.0.
Two generations were byte-identical. SHA-256 checks confirmed demo CSV and
golden files were unchanged. No Snowflake loads or RAI runs were performed.


## Experiment deployment

The custom deployment receipts, SQL scanner, provenance checks, and continuation
flags have been removed. Historical investigation commands are superseded here.
The runner uses the existing `_DEPLOY_SRC` copies, `_DEPLOY` outputs, and
`_DEPLOY_META` metadata under `ALAA_RELAPP_PERSISTENCE`, as `RAI_USER` on `RAI_XS`.
It does not provision schemas, copy source tables, or grant permissions.
The SDK handles its normal deployment metadata and object lifecycle directly.
This remains the fixed-source distance probe, not the full demo deployment.

Print targets without connecting:
```bash
env -u DEBUG .venv/bin/python scripts/check_graphs.py --prepare-copied-distance-probe
```

Deploy and run one manual refresh, then compare all expected distances:
```bash
env -u DEBUG .venv/bin/python scripts/check_graphs.py --run-copied-distance-probe --execute --refresh
```
Omit `--refresh` to install only. There is no recurring refresh schedule.
Do not run concurrently with an older deployment runner.


### Distance recursion compatibility fix (SDK 1.27.1)

The copied distance probe runner applies a temporary, process-local SQL-lowering
workaround in `deploy_distance_probe`. Only the probe distance relation is affected:
`MIN(D) GROUP BY NODE_U, NODE_V` is applied across accumulated state and new
candidates before computing the next delta. The installed SDK is unchanged.
The unmodified compiler retained longer cyclic walks and did not converge in the
observed run. This workaround is not an upstream SDK fix and should be removed
once that compiler behavior is fixed. Use the runner command above to preserve it
on redeployment; directly deploying the model without the runner bypasses it.

Offline SQL execution verifies cyclic/disconnected examples and all 1,720 baseline
distances against independent breadth-first search. A regression also checks that
unrelated relations are unchanged and the compiler method is restored on failure.

The copied probe also creates `ROLE_HISTORY_NORMALIZED` and
`OWNERSHIP_NORMALIZED` views in the existing `_DEPLOY` output schema. These
read the two corresponding `_DEPLOY_SRC` tables and compute effective end dates
with SQL COALESCE and current status from the raw source dates. This prevents
a missing-property fallback from being retained during recursive entity
materialization. The original source tables and default interactive model are
unchanged. The views are recreated by the existing deployment runner.

Live validation of both fixes passed: 1,720 distance rows and all 2,525 unordered connection pairs match the independent oracle exactly. The distance block took about 54 seconds; the full refresh includes input/rule materialization and takes longer. This validates only the copied fixed-source probe. See the existing investigation report for the task query ID and timings.


## Local connected fixtures up to 10M people

The connected generator uses compact integer role memberships and streams CSV
rows. It counts unique connections one bounded person neighborhood at a time;
it never retains the complete edge set. Memory is O(people + roles), not constant.
Topology, random seed ordering, IDs and dates match the earlier generator.
The sparse generator retains its existing 1M limit.

```bash
.venv/bin/python data/generate.py --scale-connected --people 10000000 --workplace-size 16 --seed 42 --out data/scale_connected_10m
.venv/bin/python data/generate.py --scale-check-streaming --out data/scale_connected_10m
```

Generation refuses an existing output directory. The streamed check verifies
file hashes, table counts, sequential primary IDs, role references, duplicate
memberships, role/workplace bounds, five team seeds, and all 14 protected route
cases including self and unreachable. It does not compute the full distance
oracle or independently verify the largest component or total edge count.
The manifest edge count is calculated by the generator. Keep the full
`--scale-check` oracle for small fixtures; do not run it on 10M.

Generated 10M files are ignored by Git. These commands are local only and do not
connect to Snowflake, load tables, deploy models, or change reasoners.

Local 10M run (2026-11-09): 10,000,000 people, 29,997,801 roles,
129,700,057 generator-counted connections and 4,717,104,170 CSV bytes.
Generation took 211.762 s; streamed validation took 226.051 s. Peak process
RSS was 1,051,131,904 bytes. All 14 planted cases passed. Results are in
`data/scale_connected_10m/VALIDATION.json` and table hashes in `MANIFEST.json`.
Seventeen generator tests passed. Outputs matched the previous generator
byte-for-byte at 20, 300 and 10K, and the preserved 100K manifest and every
CSV hash matched. No live RAI execution or full 10M distance validation occurred.

### 10M deployment tests

`data/load.py --fixture connected10m --execute` creates only fresh 10M
source/output/metadata schemas and stages CSVs without loading all rows into
Python. Its receipt records COPY counts, table counts, primary-ID uniqueness
and role reference checks. It refuses existing targets rather than replacing
them. The existing engine and pools are never managed by the loader.

The distance runner accepts `--fixture connected10m --distance-reasoner sql`
with the existing deploy/refresh flags. Full result comparison uses the compact
oracle in `data/oracle.py`: a sparse person-workplace incidence graph, after
checking every workplace's role windows overlap by at least 365 days and that
there are no CRM or transaction inputs. Person-to-person incidence distance
divided by two is then the exact Knows distance. All five seed vectors are
cached under the ignored fixture directory, and results are compared in batches.

The community runner accepts `--fixture connected10m` with existing flags.
Default scale settings remain one Louvain level, seed 42, and all 10M people
as pivots (exact within-community betweenness). Coverage is checked for every
output ID; independent exact betweenness checks cover up to five largest
communities, each bounded to 1,000 people. This is sampled validation, not an
independent check of all 10M scores. Existing native query/task timeouts remain
in effect. No automatic refresh schedules or engine resizing are introduced.

10M SQL distance run (2026-11-09): one manual refresh succeeded on RAI_XS
in 3,037.164 seconds (50m 37.164s), excluding deployment and client validation.
All 49,999,995 rows from five seeds matched the independent compact oracle.
Selected block durations: input/model materialization 712.748s; tenure-overlap
524.337s; Knows evidence 244.204s; Knows consolidation 389.900s; distance
recursion 1,099.242s; final distance output 15.106s. These are selected block
durations, not an additive breakdown of every statement.

The first local monitor stopped at 30 minutes; the existing Snowflake task
continued and was monitored to completion without resubmission. The SDK task
had USER_TASK_TIMEOUT_MS=0; it was not changed during this run. A 90-minute
manual cap was stated but not reached. Evidence:
`artifacts/seed_distances_connected_10m_sql.json`; query
`01c84c7d-020d-10ee-0005-5ee313e416e6`.

The local independent oracle took 89.945s and 3,378,921,472 peak RSS bytes.
It is a fixture-specific validation implementation, not a replacement for the
RAI model or an equivalent end-to-end performance comparison.

10M Logic community run (2026-11-09): deployment installed, but the single
manual refresh FAILED after 1,731.959 seconds (28m 51.959s). Its Logic
transaction ran for 1,501.684 seconds and aborted with `transaction timeout`
at the configured 25-minute limit. Settings were one Louvain level, seed 42,
and 10M pivots for exact within-community betweenness, using the unchanged
HIGHMEM_X64_S reasoner. PERSONCOMMUNITYPROBE has zero rows; no community
correctness or timing claim is supported by this failed refresh.

Progress snapshots showed substantial time in role/person, role/date,
role/organization and intermediate relations, and later tenure-overlap work.
These snapshots do not establish Louvain or betweenness as the bottleneck.
The final transaction progress and timings are saved in
`artifacts/people_communities_connected_10m.json`; a debugger-readable bundle
is `artifacts/people_communities_connected_10m.debug.zip`.

Original/copy input fingerprints and the existing baseline distance deployment
matched before/after. The new refresh task remains suspended with no schedule.
No retry, engine resize or pool-setting change was performed. The reasoner
was resumed at the user's explicit authorization and retains 30-minute auto
suspend. The successful 10M SQL distance result is unaffected.

10M graph-only Logic experiment (2026-11-09): reused the existing
CONNECTED_10M.PERSON and KNOWS outputs in a fresh
CONNECTED_10M_COMMUNITY_GRAPH_ONLY / _META deployment. Input checks verified
10M unique people, 129,700,057 unique canonical pairs, nonnegative strengths,
and all edge endpoints. Before/after graph fingerprints matched.

The model uses native RAI Louvain (one level, seed 42) and exact unweighted
within-community betweenness (10M pivots), threshold 0.0. It omits employment
and tenure-overlap rules. The single refresh FAILED after 1,630.735s; the Logic
transaction aborted after 1,504.680s at its configured 25-minute limit.
Louvain's community-label relation completed, but the within-community
shortest-distance recursion was still active at timeout. Final
PERSONCOMMUNITYPROBE row count is zero; no community correctness claim is made.
RAI reported HIGH_COST_X_JOIN in the pivot-selection relation; this is a
warning to investigate, not evidence by itself of an incorrect model.

This is a graph-only experiment, excluding the prior SQL graph construction
cost, not an end-to-end speedup measurement. No retry or resize occurred;
HIGHMEM_X64_S and its 30-minute auto-suspend remain unchanged. The task is
suspended with no schedule. Original/baseline preservation checks passed.
Evidence: artifacts/people_communities_connected_10m_graph_only.json and its
.debug.zip. Relevant offline compiler/scope/guard regressions: 95 passed.

Command used (do not repeat against these existing schemas):
  env -u DEBUG .venv/bin/python scripts/check_graphs.py --run-community-probe \
    --fixture connected10m --materialized-community-graph --execute --refresh \
    --json artifacts/people_communities_connected_10m_graph_only.json

40-minute graph-only rerun (2026-11-09): reused the existing deployment and
Person/Knows inputs; no redeploy, CSV load or new schemas. Verified the stored
plan against the prior SHA-256, then changed only its Logic timeout argument
from 25 to 40 minutes. Changed only the existing experiment task timeout from
30 to 50 minutes to allow startup/export overhead. The computation payload,
algorithms and size-S reasoner were unchanged. 35 offline tests passed.

The explicitly requested single rerun FAILED with transaction timeout:
2,524.842 seconds total refresh; 2,404.932 seconds in Logic. Final score output
has zero rows, so no 10M community/betweenness correctness claim is made.
Community-label work completed; within-community distance recursion and
export preparation remained active before abort. The extra 15 minutes did
not establish a successful pipeline. Original/baseline and materialized graph
fingerprints passed preservation checks. No further retry or resize occurred.

Evidence: artifacts/people_communities_connected_10m_graph_only_40m.json and
its .debug.zip. The old 25-minute evidence remains intact. The experiment
retains the 40-minute Logic/50-minute task limits. The task remains suspended
without a schedule, and engine auto-suspend remains 30 minutes.

Command used:
  env -u DEBUG .venv/bin/python scripts/check_graphs.py \
    --refresh-materialized-community-40m --execute \
    --json artifacts/people_communities_connected_10m_graph_only_40m.json
This guarded timeout transition expects the prior 25-minute plan; it is not
an automatic retry command against the now-modified plan.
