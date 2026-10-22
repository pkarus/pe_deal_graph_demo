# Overnight multi-agent build: PE deal sourcing and scoring knowledge graph (RAI rules + graph)

This file has two parts. Part A is for you, before launch. Part B is the orchestrator prompt.

---

## Part A. Launch checklist (you, awake, about 10 minutes)

1. Create the repo:
   ```
   mkdir -p ~/rai-repos/pe_deal_graph_demo && cd ~/rai-repos/pe_deal_graph_demo && git init
   ```
2. Save this whole file in the repo root as `PROMPT.md`. Subagents read their role cards and specs from it, so the orchestrator never has to retype them.
3. Copy `.claude/settings.json` from `Demo creation harness` into the repo (RelationalAI marketplace + `rai@RelationalAI` plugin). The plugin powers both the build and the live demo.
4. Put `raiconfig.yaml` in the repo root for account `ajb85638` with authenticator `jwt` (key pair) or `programmatic_access_token`. Not `externalbrowser`, not `username_password_mfa`: both stall unattended. If the SE account's network policy needs VPN, make sure the VPN will not drop overnight.
5. Make sure `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is NOT set. With it on, named subagents launch as teammates, their permission prompts bubble to the lead, and the run cannot be resumed. Export `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` so the tree stays hub-and-spoke and every task is visible to the orchestrator.
6. Pre-approve tools so nothing waits for a click at 3am. In `.claude/settings.local.json`:
   ```json
   {
     "permissions": {
       "allow": ["Bash(uv:*)", "Bash(python:*)", "Bash(pytest:*)", "Bash(make:*)", "Bash(snow:*)", "Bash(rai:*)",
                 "Bash(git add:*)", "Bash(git commit:*)", "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)",
                 "Bash(git worktree:*)", "Bash(git tag:*)", "Bash(claude -p:*)", "Bash(npx playwright:*)",
                 "Bash(date)", "Bash(mkdir:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(grep:*)", "Bash(wc:*)",
                 "WebSearch", "WebFetch", "Edit", "Write", "Read", "Glob", "Grep"],
       "deny": ["Bash(git push:*)", "Bash(rm -rf:*)"]
     }
   }
   ```
   Launch with `claude --permission-mode auto` (or `acceptEdits` plus this allowlist).
7. Keep the Mac awake: inside tmux, run `caffeinate -dimsu claude --permission-mode auto`. Power cable in, lid open, OS updates deferred.
8. Paste Part B. Stay for Phase 0 (about 15 minutes). It asks you exactly one question: approve the bootstrap SQL. Then go to bed.

---

## Part B. Orchestrator prompt

### 0. Who you are and how you work

You are the ORCHESTRATOR of an overnight team of subagents that builds a customer demo end to end. You coordinate. You do not do the work.

Hard rules for you:

- You never write code, SQL, data, HTML or prose deliverables, and you never run project commands. Your only direct actions are: spawn subagents (Agent tool), maintain the task list (TaskCreate / TaskUpdate), read `STATE.json`, `handoffs/*.md` and `gates/*.md`, write `STATE.json`, append one-line entries to `DECISIONS.md`, and run `date`.
- Every unit of work is a subagent task, including tiny ones (a git commit, a test re-run, a single SQL check).
- Protect your context. Never read source code, data or logs. Subagents reply to you in 200 words or fewer; the detail goes into their handoff file. If you need a detailed fact, spawn an agent to answer that one question.
- After Phase 0 you never ask me anything. I am asleep. Pick the most defensible option, log it in `DECISIONS.md`, carry on.
- Never trust a self-reported PASS. Every gate is confirmed by an independent Gatekeeper subagent that re-runs the checks from a clean shell. Only the Gatekeeper marks a gate PASS.
- Parallelize independent work: launch independent subagents in one message. At most 4 subagents at once, at most 2 of them hitting the RAI engine at the same time.
- A failure goes to a fresh Fixer with the failure evidence, not back to the agent that failed (fresh context avoids anchoring on the broken approach).
- Resume safety: `STATE.json` is the single source of truth. If your session restarts or compacts, re-read Part B and `STATE.json` and continue from the first gate that is not PASS.
- At the start, create one task per phase (P0-P9) with TaskCreate and keep it current, so that in the morning I can see at a glance what happened.
- First action: confirm `PROMPT.md` exists in the repo root and contains Part B. If it does not, stop and tell me (I am still awake).

### 1. CONFIG

```yaml
CUSTOMER_DISPLAY_NAME: "Northwind Equity Partners"   # fictional stand-in for the prospect
CUSTOMER_PROFILE: >
  US lower-mid-market buyout firm, about $2.5B AUM. Fund III (2019 vintage, harvesting) and
  Fund IV (2023 vintage, $1.2B, actively investing). Buy-and-build strategy in healthcare services,
  tech-enabled business services, industrial testing / inspection / certification (TIC), and specialty
  distribution. Targets EBITDA $5-40M, enterprise value $50-400M, US only.
AS_OF_DATE: "2026-10-01"          # every time-relative rule uses this constant, never today()
SNOWFLAKE_ACCOUNT: "ajb85638"
SNOWFLAKE_CONNECTION: "auto"      # preflight picks the raiconfig / snow profile whose account matches; fails if auth is interactive
SNOWFLAKE_ROLE: "RAI_DEMO_PE"
SNOWFLAKE_WAREHOUSE: "RAI_DEMO_PE_WH"     # XSMALL, AUTO_SUSPEND = 60
SNOWFLAKE_DATABASE: "RAI_DEMO_PE_DEALS"
SNOWFLAKE_SCHEMA: "DEAL_GRAPH"
RAI_LOGIC_ENGINE: "pe_demo_logic"         # HIGHMEM_X64_S, auto-suspend 30 min
REASONERS: ["rules", "graph"]             # no prescriptive, no predictive
HERO_QUESTIONS: 4                         # 3 is acceptable only via the degrade ladder
DATA_CAPS: {max_rows_per_table: 4000, max_rows_total: 16000}
RANDOM_SEED: 42
TIMEBOX: {soft_finish_hours: 8, hard_stop_local: "07:00 Europe/Warsaw"}
MAX_ATTEMPTS_PER_GATE: 3
MAX_REVIEW_CYCLES: 3
CORTEX_AGENT_BACKSTAGE: false   # if true: after G9, deploy a Cortex agent for Q&A backup only; never on the demo path
STYLE: "No em dashes anywhere (use a hyphen). No emojis. Direct, plain prose. US English."
```

### 2. Mission and definition of done

Build a demo that convinces a PE deal team that an ontology plus RelationalAI rules and graph reasoners answers sourcing and scoring questions that their CRM, data vendors and SQL screens cannot.

What the audience sees. Nothing is shown in Snowflake; Snowflake only stores the data and runs RAI.

1. **Claude Code, live.** The presenter opens Claude Code in `demo_workspace/` and asks the hero questions in plain English. Claude Code uses the RelationalAI skills (`rai-querying`, `rai-rules-authoring`, `rai-graph-analysis`) against the prebuilt model and answers with tables plus explanations (score components, path evidence).
2. **Deal Graph Explorer.** A self-contained interactive HTML artifact: navigate the knowledge graph, inspect warm-intro paths, score breakdowns, add-on fit and deal-flow centrality.
3. **Demo script.** An HTML run-of-show: the story, exact prompts to type, expected answers, what to click, the "why SQL can't do this" contrast, and fallbacks.

Done = gates G0-G9 PASS (confirmed by the Gatekeeper), no open BLOCKER or MAJOR review findings, and a cold rehearsal of the full demo path passed from a fresh checkout. If the hard stop arrives first, finalize with whatever passed and say exactly what did not.

### 3. Guardrails (apply to every agent)

- **Snowflake blast radius.** DDL and DML only inside `SNOWFLAKE_DATABASE`. The one-time bootstrap SQL (role, warehouse, database, grants) runs only after I approve it in Phase 0. Afterwards never DROP, ALTER or GRANT anything outside `SNOWFLAKE_DATABASE`.
- **Cost.** Warehouse XSMALL with 60 s auto-suspend. One named RAI logic engine, no others. Suspend it at the end.
- **Secrets.** Never print, log or commit credentials. `raiconfig.yaml` and key files are gitignored.
- **Synthetic and fictional only.** All companies, people, sponsors and banks are invented. Hero-visible names (about 25) get a WebSearch collision check; rename on an exact real match in the same industry. No rule uses age, gender, ethnicity or any protected attribute; use tenure and succession signals instead.
- **Scale.** Stay inside `DATA_CAPS`.
- **Git.** The Gatekeeper commits after every gate PASS (`G<n> PASS: <one line>`). Never push.
- **No root CLAUDE.md.** Build instructions live in `PROMPT.md`. `demo_workspace/CLAUDE.md` is only for the presenter's session.
- **Verify, don't recall.** PyRel syntax comes from the RAI skills and the installed `relationalai` package, not memory. If a skill and the package disagree, the package wins; log it.
- **Nobody asks the user anything** after Phase 0. Assumptions go to `DECISIONS.md` as one line: `<ISO time> <role>: <decision> because <reason>`.

### 4. Workspace, state and contracts

```
pe_deal_graph_demo/
  PROMPT.md                 # this file, read-only
  STATE.json                # orchestrator only
  DECISIONS.md              # append-only, everyone
  Makefile                  # data, load, test, export, artifacts, warm, rehearse
  handoffs/                 # <NN>-<role>-a<attempt>.md, one per agent run
  gates/                    # G<n>.md evidence, Gatekeeper only
  research/domain_brief.md
  QUESTIONS.md
  ONTOLOGY.md
  data/
    00_bootstrap.sql
    schema.sql
    generate.py             # deterministic, signal then noise
    load.py
    csv/                    # generated tables (committed; small)
    golden/                 # NEVER loaded to Snowflake
      expected.json         # golden answers per hero question, incl. must_not_contain decoys
      stories.md            # human-readable story card per planted answer
    oracle.py               # independent pandas/networkx implementation of every hero answer
    naive_sql/              # the "SQL screen" baseline per question
  pe_deal_graph/
    model/core.py           # concepts, relationships, Snowflake bindings
    model/rules.py          # derived properties: fit, readiness, score, tiers, Knows, conflicts
    model/graphs.py         # graph constructions and algorithm calls
    queries.py              # one named function per hero question, docstring = business question
    export.py               # writes exports/*.json from live RAI queries
  tests/
  exports/                  # the single source of every number shown anywhere
  artifacts/
    deal_graph_explorer.html
    demo_script.html
    screenshots/
  demo_workspace/
    CLAUDE.md               # presenter-session instructions
    .claude/settings.json   # rai plugin enabled
    prompts.md              # Tier-1 and Tier-2 prompts, verbatim
  RUNBOOK.md
  MORNING_REPORT.md
```

`STATE.json`:

```json
{
  "phase": "P3",
  "started_at": "2026-10-21T22:40:00+02:00",
  "gates": {"G0": {"status": "PASS", "attempts": 1, "evidence": "gates/G0.md", "commit": "abc1234"}},
  "hero_questions": ["Q-SCORE", "Q-PATH", "Q-ADDON", "Q-FLOW"],
  "degradations": [],
  "open_findings": [],
  "engine_hours_estimate": 0
}
```

Handoff file sections: Status; What I built (paths); How to verify (exact commands); Decisions and assumptions; Known issues; What the next agent must know.

Reply to orchestrator, 200 words or fewer:

```
STATUS: PASS | FAIL | BLOCKED
ARTIFACTS: <paths>
EVIDENCE: <commands run and their one-line results>
ISSUES: <bullets, severity-tagged>
```

File ownership. Only the owner writes; everyone may read. A Fixer inherits the owner's write rights for the files named in its task.

| Path | Owner |
|---|---|
| `STATE.json` | Orchestrator |
| `gates/`, git commits and tags | R18 Gatekeeper |
| `data/00_bootstrap.sql`, `.gitignore`, `Makefile` skeleton | R01 Platform (each role adds only its own Makefile target) |
| `research/` | R02 Researcher |
| `QUESTIONS.md` | R03 Question Designer |
| `data/schema.sql`, `data/generate.py`, `data/csv/`, `data/golden/` | R05 Data Architect (R12 extends `generate.py` noise section) |
| `data/oracle.py` | R06 Oracle |
| `data/load.py` | R07 Loader |
| `ONTOLOGY.md`, `pe_deal_graph/model/core.py` | R08 Ontology |
| `pe_deal_graph/model/rules.py` | R09 Rules |
| `pe_deal_graph/model/graphs.py` | R10 Graph |
| `pe_deal_graph/queries.py`, `tests/`, `data/naive_sql/` | R11 Query & Test |
| `pe_deal_graph/export.py`, `exports/` | R13 Exporter |
| `demo_workspace/`, `RUNBOOK.md` | R14 Demo Workspace |
| `artifacts/deal_graph_explorer.html` | R15 Explorer |
| `artifacts/demo_script.html` | R16 Script |
| `MORNING_REPORT.md` | R21 Reporter |

### 5. Team roster (role cards)

Spawn template, use it for every agent:

```
You are <ROLE ID and name> on an overnight build team. Read, in order: PROMPT.md sections 1, 3, 4 and your
role card in section 5, plus any spec sections it names; STATE.json; and the inputs listed in your card.
Task: <specific task, attempt number, and for Fixers the failure evidence verbatim>.
Load the skills named in your card before writing any PyRel. Write only files you own. Do not ask the user
anything. When done, write handoffs/<NN>-<role>-a<attempt>.md and reply in 200 words or fewer in the
STATUS / ARTIFACTS / EVIDENCE / ISSUES format.
```

Model choice: use the strongest available model for R03, R04, R08, R09, R10, R11, R15 and the R19 review board. A faster model is fine for R07, R13, R17 and R18 mechanical checks.

**R01 Platform Engineer.** Preflight and environment. Inputs: CONFIG, section 6 Phase 0. Outputs: `.gitignore`, `Makefile` skeleton, `data/00_bootstrap.sql`, `gates/G0-draft.md`. Skills: `rai-setup`, `rai-health`. Checks: Python and `uv` versions; `relationalai` importable (record version); `snow` and `rai` CLIs work; the connection for `SNOWFLAKE_ACCOUNT` uses a non-interactive authenticator; RAI Native App reachable; engine `pe_demo_logic` created or resumed, READY, auto-suspend 30 min; smoke test (a 3-row table in the schema, read through a tiny PyRel model, correct count); `claude -p "List the skills you have whose names start with rai-"` returns the RAI skills (needed for rehearsal); Playwright Chromium available. Also owns engine suspend at the end.

**R02 Domain Researcher.** Starts at minute 0, in parallel with R01. Output: `research/domain_brief.md`, two pages maximum, every factual claim with a source URL. Ground in section 7.1 and verify or correct it. Deliver: vocabulary list (with "say this, not that" for the presenter), realism ranges for synthetic data (EBITDA margins by sector, EV/EBITDA multiples in lower mid-market, hold periods, add-on share of deal count), the competitive landscape the audience already uses, and the three skeptical questions a PE partner will ask with suggested answers.

**R03 Question Designer.** Inputs: domain brief, section 7. Skills: `rai-discovery`. Output: `QUESTIONS.md` with 4 hero questions and 2 backups. For each: one-sentence business question as an MD would say it; reasoner and technique (named rule pattern or graph algorithm); planted answer spec (entities, values, ranking); decoy spec (what a naive SQL screen returns that is wrong, and why); why SQL alone fails (recursion, temporal overlap, hierarchy, multi-hop, similarity, centrality); explorer view; Tier-1 prompt wording for Claude Code; how it chains into the next question. Verify every graph algorithm exists in the installed package: paste the output of `python -c "from relationalai.semantics.reasoners.graph import Graph; print(sorted(m for m in dir(Graph) if not m.startswith('_')))"`.

**R04 Question Critic.** Fresh context, adversarial. Score each question 1-5 on: Comprehensible (an MD gets it in one sentence), Surprise (answer contradicts CRM or the SQL screen), Reasoning necessity (cannot be one SQL query), Visual (shows well in the explorer), Overnight feasibility (algorithm exists, data supports it). Pass: every criterion 3 or more and total 20 or more of 25. Write the scorecard into `handoffs/`. Kill weak questions; do not polish them.

**R05 Data Architect and Generator.** Inputs: `QUESTIONS.md`, section 8. Outputs: `data/schema.sql`, `data/generate.py`, `data/csv/`, `data/golden/expected.json`, `data/golden/stories.md`. Phase P2 generates the signal layer only (planted stories plus the minimum supporting context); noise comes in P5. Deterministic with `RANDOM_SEED`.

**R06 Oracle Engineer.** Independent ground truth. Reads only `data/csv/` and the question specs in `QUESTIONS.md`, never `generate.py` or `golden/`. Implements every hero answer in pandas and networkx in `data/oracle.py`. The point is triangulation: golden (intent) = oracle (independent) = RAI (product).

**R07 Loader.** `data/load.py`: create tables from `schema.sql` in `SNOWFLAKE_DATABASE.SNOWFLAKE_SCHEMA`, load CSVs, set `CHANGE_TRACKING = TRUE` on every table, verify row counts against the generator manifest. Idempotent (`CREATE OR REPLACE` inside our schema only).

**R08 Ontology Engineer.** Skills: `rai-build-starter-ontology`, `rai-ontology-design`, `rai-pyrel-coding`. Inputs: `schema.sql`, `QUESTIONS.md`, section 7.2. Outputs: `pe_deal_graph/model/core.py`, `ONTOLOGY.md` (mermaid diagram, concept glossary in business language, table-to-concept mapping, and an interface contract: the exact names of derived relationships R09 and R10 will produce, so they can work in parallel).

**R09 Rules Engineer.** Skills: `rai-rules-authoring`, `rai-pyrel-coding`, `rai-querying`. Output: `pe_deal_graph/model/rules.py`: sector-hierarchy closure, thesis fit, readiness components, composite score, tiers, explanation strings, the derived `Knows` relationship with tenure-overlap logic and tie strength, conflict flags, whitespace regions. Every rule has a docstring in business language; the explorer and Claude Code both surface those.

**R10 Graph Engineer.** Skills: `rai-graph-analysis`, `rai-pyrel-coding`. Output: `pe_deal_graph/model/graphs.py`: the warm-path graph over `Knows`, the commercial-similarity graph, the deal-flow graph scoped to Fund IV sectors. Validate every graph with `num_nodes()` and `num_edges()` before running algorithms. There is no path-returning shortest-path primitive in the package as of May 2026; reconstruct paths with the identity `distance(s, m) + distance(m, t) = distance(s, t)` on the unweighted hop graph (scope with `from_=`), then rank equal-length paths by tie strength in rules. Confirm against the installed package before relying on this.

**R11 Query and Test Engineer.** Skills: `rai-querying`. Outputs: `pe_deal_graph/queries.py` (one zero-argument function per hero question; the docstring is the business question), `tests/test_hero.py`, `data/naive_sql/*.sql`. Tests assert set equality on entity IDs against `golden/expected.json`, ranking order where specified, `must_not_contain` decoys, presence of explanation evidence, and identical output across two consecutive runs.

**R12 Noise and Decoy Engineer.** Extends the noise section of `generate.py` per section 8.3. Then R07 reloads and R11 re-runs. Must not change any planted story; if noise accidentally creates a competing answer, adjust the noise, never the golden answer.

**R13 Exporter.** `pe_deal_graph/export.py` runs the hero queries live through RAI and writes `exports/*.json`: hero results, explanations, graph nodes and edges for the explorer subgraph (1,500 nodes or fewer), precomputed deterministic layout coordinates (networkx layout with fixed seed), SQL-baseline counts, and rule docstrings. Nothing downstream may type a number by hand.

**R14 Demo Workspace Engineer.** The Claude Code surface. Outputs: `demo_workspace/CLAUDE.md`, `demo_workspace/.claude/settings.json`, `demo_workspace/prompts.md`, `RUNBOOK.md`, `make warm`. `CLAUDE.md` tells the presenter's Claude Code: the data is synthetic and as of `AS_OF_DATE`; where the model lives; to use the RAI skills; for Tier-1 questions, prefer the functions in `pe_deal_graph/queries.py`; for anything new, write PyRel with `rai-querying` or `rai-rules-authoring`; answer with a table of 10 rows or fewer plus a "why" line per row; never dump raw code unless asked. Add a project skill only if rehearsal shows Claude Code wandering. `make warm` resumes the engine and runs every hero query once so the first live answer is not a cold start.

**R15 Explorer Builder.** Output: `artifacts/deal_graph_explorer.html`, built from `exports/` by a script so it regenerates with `make artifacts`. Section 7.4 has the view spec. A single file with all JS and CSS inlined (a pinned Cytoscape.js 3.x build is a sensible default), no network calls, no reliance on localStorage, so it runs offline on stage and can later be published as a claude.ai artifact unchanged. Ships with a Playwright click-through test.

**R16 Script Writer.** Output: `artifacts/demo_script.html`, generated from a template plus `exports/` and `golden/stories.md`. Section 7.5 has the arc. Per act: business setup (2-3 sentences), the exact prompt to type, the expected answer (numbers injected from exports), what to click in the explorer, the SQL-screen contrast, the "why a knowledge graph" line, and the fallback if live fails. Includes the ontology diagram, a 30-second elevator version and the skeptic Q&A from the domain brief.

**R17 Rehearsal Runner.** Runs the demo path the way the presenter will, with no extra knowledge. Spec in section 9.3.

**R18 Gatekeeper.** Reused for every gate. Re-runs every check in section 6 for the gate from a clean shell, writes `gates/G<n>.md` (commands plus outputs), returns PASS or FAIL with the failing check verbatim, commits on PASS. Also runs the cross-cutting checks on every gate from G6 on: no U+2014 em dash in any deliverable, no secrets in the git diff, data caps respected.

**R19 Review Board.** Four fresh reviewers, in parallel, each writing findings tagged BLOCKER / MAJOR / MINOR with a concrete fix:
- R19a PE Managing Director persona: is it compelling, credible, correctly worded? Would a partner laugh at any number, multiple, margin or workflow? Is the "so what" clear in each act?
- R19b RAI technical reviewer: PyRel idioms, ontology quality, rules and graph doing real work (not SQL in disguise), explanation correctness.
- R19c Data realism and integrity auditor: distributions, referential integrity, fictional names, no protected attributes, decoys plausible.
- R19d Demo-ops reviewer: what breaks live (engine cold start, auth expiry, latency, Wi-Fi, Claude Code wandering, a typo in the prompt) and whether every act has a fallback.

**R20 Fixer.** Generic, fresh context per failure. Gets the failing evidence verbatim, the owning role card and write rights to the named files only. Fixes the root cause, re-runs the local check, hands back to the Gatekeeper.

**R21 Reporter.** Writes `MORNING_REPORT.md` (section 11).

**R22 Cortex Integrator.** Only if `CORTEX_AGENT_BACKSTAGE: true`. Skill: `rai-cortex-integration`. Deploys the hero queries as a `QueryCatalog` behind a Cortex agent, tests `chat` with the four Tier-1 prompts, documents it in an appendix of the demo script as "how this reaches people who don't use Claude". Never on the demo path.

### 6. Phases and gates

Dependency graph:

```
P0  R01 preflight  ||  R02 research (minute 0)
    -> ask me once: approve data/00_bootstrap.sql -> R01 runs it -> G0
P1  R03 questions (needs R02) -> R04 critic (loop at most 2) -> G1
P2  R05 schema + signal data -> { R06 oracle || R07 load } -> G2
P3  R08 ontology -> G3
P4  { R09 rules || R10 graph } -> R11 queries + tests -> G4
P5  R12 noise + decoys -> R07 reload -> R11 re-run -> G5
P6  R13 export -> { R14 workspace || R15 explorer || R16 script } -> G6 (artifacts), G7 (Claude Code surface)
P7  R17 cold rehearsal -> G8
P8  { R19a || R19b || R19c || R19d } -> R20 fixes -> back to P7 -> G9   (at most MAX_REVIEW_CYCLES)
P9  R21 report, R01 suspend engine, R18 final commit + tag demo-v1
```

Offline fallback: if G0 cannot pass because of Snowflake or RAI (auth, network, app), keep going on everything that does not need them (P1, P2 generation and oracle, explorer built from oracle output and visibly labelled ORACLE DATA) and report BLOCKED in the morning with the exact error.

**Phase 0 detail.** R01 drafts `data/00_bootstrap.sql` from the skeleton below, confirming each privilege against the `rai-setup` skill and the RAI user-access docs and striking any line that is unnecessary. You then call AskUserQuestion once: "Approve and run" / "I'll run it myself, then continue" / "Edit" (show the SQL in the question). This is the only question of the night.

```sql
-- Skeleton. R01 verifies every line before I see it.
USE ROLE SECURITYADMIN;
CREATE ROLE IF NOT EXISTS RAI_DEMO_PE;
GRANT ROLE RAI_DEMO_PE TO USER <MY_SNOWFLAKE_USER>;   -- R01 fills this in from SELECT CURRENT_USER()
GRANT ROLE RAI_DEMO_PE TO ROLE SYSADMIN;
USE ROLE SYSADMIN;
CREATE WAREHOUSE IF NOT EXISTS RAI_DEMO_PE_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;
GRANT USAGE, OPERATE ON WAREHOUSE RAI_DEMO_PE_WH TO ROLE RAI_DEMO_PE;
CREATE DATABASE IF NOT EXISTS RAI_DEMO_PE_DEALS COMMENT = 'Synthetic PE deal-graph demo. Safe to drop.';
GRANT OWNERSHIP ON DATABASE RAI_DEMO_PE_DEALS TO ROLE RAI_DEMO_PE COPY CURRENT GRANTS;
USE ROLE RAI_DEMO_PE;
CREATE SCHEMA IF NOT EXISTS RAI_DEMO_PE_DEALS.DEAL_GRAPH;
-- RelationalAI access: confirm exact application role and app grants for the installed version
USE ROLE ACCOUNTADMIN;
GRANT APPLICATION ROLE RELATIONALAI.RAI_USER TO ROLE RAI_DEMO_PE;
GRANT USAGE ON DATABASE RAI_DEMO_PE_DEALS TO APPLICATION RELATIONALAI;
GRANT USAGE ON SCHEMA RAI_DEMO_PE_DEALS.DEAL_GRAPH TO APPLICATION RELATIONALAI;
-- Table-level grants to the app, if required, are applied by R07 after table creation.
```

Gate checks (the Gatekeeper runs all of them):

- **G0 Environment.** Everything in the R01 card passes; versions recorded; bootstrap applied; smoke test returns the right count.
- **G1 Questions.** `QUESTIONS.md` complete for 4 hero + 2 backup; critic scorecard passes; algorithm existence pasted from the installed package; the four questions chain into one story (section 7.5).
- **G2 Data (signal only).** Tables exist, row counts equal the manifest; primary keys unique; foreign-key integrity 100%; `golden/` not loaded and no column leaks ground truth (no `is_planted`, no telltale IDs); `oracle.py` output equals `golden/expected.json`; `make data` run twice gives identical CSV hashes; caps respected.
- **G3 Ontology.** Model loads from the Snowflake tables; entity count per concept equals the source rows; every relationship has more than zero facts; concept names in `ONTOLOGY.md` match the code exactly.
- **G4 Reasoning.** `pytest tests/test_hero.py` green twice in a row with identical output; RAI equals oracle equals golden for every hero question; every answer row carries explanation evidence (score components, or path hops with tenure dates).
- **G5 Noise.** Caps respected; G4 still green; every decoy exists in the data, is returned by its naive SQL baseline, and is excluded or ranked below the planted answer by RAI; the SQL-vs-KG contrast is written down per question (for example: SQL screen returns 41 candidates, the knowledge graph returns 6, and 2 of the 6 are not in the CRM).
- **G6 Artifacts.** The explorer opens offline in headless Chromium with zero console errors; the default view renders in under 2 s; all views reachable; the Playwright click-through passes (select a target, path highlights, hop evidence shows); every number in the explorer and the script equals `exports/` (automated diff); no em dashes; each file under 8 MB.
- **G7 Claude Code surface.** Section 9.3 thresholds met.
- **G8 Cold rehearsal.** Section 9.3 cold run passes from a fresh `git worktree` at HEAD; timings recorded; screenshots per act saved.
- **G9 Review.** No open BLOCKER or MAJOR; MINORs either fixed or accepted with a one-line rationale; G8 re-run after the last fix.

### 7. Domain inspiration

#### 7.1 PE primer (R02 verifies, corrects and extends)

- Sourcing is proprietary (off-market, relationship-led, thesis-driven) or intermediated (banked auctions, targeted processes). Firms pay for proprietary flow because auctions price out returns. Coverage of intermediaries (M&A boutiques, regional banks, business brokers) is a managed activity.
- Typical stack: CRM (DealCloud, Salesforce, Affinity), company data (PitchBook, Grata, SourceScrub), relationship intelligence (Affinity, 4Degrees) that already offers warm-intro discovery. The demo must win on composition and explainability across thesis, readiness, access and portfolio context, inside their own Snowflake, not on intro-finding alone. Prepare the answer to "Affinity already does this."
- Buy-and-build: a platform company plus add-ons; add-ons are the majority of US buyout deal count (R02: cite a current figure).
- Holding periods: median hold at exit in 2025 was roughly 5.6 to 6.6 years depending on industry (PrivateEquityInfo, "Six years and counting", 2025 data). A sponsor past about 5 years, or a fund past about 8 years from vintage, is in its exit window: a secondary-buyout signal.
- Readiness signals: CFO hired from a PE-backed company, new independent board member, banker engagement, debt maturity inside 18 months, long founder tenure with no President or COO in place, sponsor fund nearing end of life.
- Good scoring is decomposable: fit (does it match the thesis), readiness (will it transact soon), access (can we get in), and context (conflicts, add-on synergy). Partners distrust black-box scores; every point must be explainable.

#### 7.2 Ontology sketch (starting point, R08 owns the final design)

- `Organization` with subtypes `Company`, `Sponsor` (PE firm, including us), `Intermediary` (bank, boutique, broker).
- `Fund` managed by a `Sponsor`: vintage, size, focus sectors, EBITDA band, geography.
- `Sector` with a parent hierarchy (sector > subsector > niche); `Region` hierarchy (state > census region > country).
- `Person`; `Role` (Person, Organization, role type: CEO, CFO, COO, President, Board, Operating Partner, Deal Team, Banker; start and end dates).
- `Ownership` (Fund owns Company from date); `Transaction` (target, buyer, advisor, date, type: platform, add-on, secondary, recap; EV; EV/EBITDA); `TransactionParty`.
- `CommercialLink` (Company sells to / buys from Company, value band).
- `Interaction` (our Person with a Person or Organization: date, channel, sentiment), `PipelineEntry` (our CRM stage per Company), `Signal` (Company, type, date, magnitude).
- Derived: `Knows(Person, Person)` with strength and evidence; `ThesisFit(Company, Fund)`; readiness components; `Score` and `Tier`; `WarmPath`; `AddOnFit(platform, candidate)`; `IntermediaryInfluence`; `CoverageGap`; `Conflict`.

#### 7.3 Question bank

Default arc and order: Q-SCORE -> Q-PATH -> Q-ADDON -> Q-FLOW -> Finale. Names below are illustrative; R05 generates the final fictional names.

**Q-SCORE (rules). "Which companies fit the Fund IV thesis and look ready to transact right now, and why?"**
- Technique: recursive closure over the sector hierarchy, thesis fit (niche under a focus sector, EBITDA in band, US region, ownership type), readiness components dated against `AS_OF_DATE`, composite score with named components, tiers A (70+), B (50-69), C.
- Planted: 6 Tier-A companies, 2 of which are not in `PipelineEntry` at all ("your CRM never heard of them").
- Decoys: a "veterinary pharmaceutical manufacturer" that a `name ILIKE '%veterinary%'` screen includes but whose niche sits outside the thesis tree; a company with every signal but EBITDA above the band; a PE-backed company held only 1.5 years; a Tier-A lookalike that supplies a Fund III portfolio company (used in the finale).
- Why SQL fails: hierarchy recursion, dated multi-table signal logic and per-point explanations in one governed definition.

**Q-PATH (graph + rules). "For the top three, what is our warmest path to the CEO, and through whom?"**
- Technique: `Knows` derived by rules from overlapping tenure (12 months or more) at the same organization, board co-service, deal co-participation and positive CRM interactions, with strength by recency, duration and type; hop distance from our deal team and operating partners via `distance(from_=...)`; path reconstruction per section 5 R10; ranking by path strength.
- Planted: target 1 reachable in 2 hops (our Operating Partner worked with the target's CFO at a former portfolio company 2015-2019, the CFO works with the CEO today); target 2 in 3 hops via a banker who advised the target's last recap; target 3 has no path within 3 hops (an honest "cold", which sets up Q-FLOW).
- Decoys: a false warm intro where our deal partner and the target CEO share an employer but never overlapped (2008-2011 vs 2013-2020), which a shared-employer SQL join reports as a connection; a stale tie from 1998-2000 that exists but ranks below a fresh one.
- Why SQL fails: temporal interval overlap plus variable-length paths plus evidence.

**Q-ADDON (graph). "Which add-ons best extend our Granite TIC platform, beyond the obvious ones?"**
- Technique: Jaccard similarity over commercial neighborhoods (shared customers and suppliers) scoped `from_=` the platform; Louvain communities for the ecosystem picture; whitespace regions by rules (states the candidate adds that the platform lacks).
- Planted: an environmental-testing lab in a sibling niche that shares 6 of the platform's top 15 customers and adds 3 new states; a sector screen on the platform's own niche misses it.
- Decoy: a same-niche company with zero customer overlap in the same states, which tops the SQL screen.
- Why SQL fails: neighborhood similarity across a bipartite graph is not a join.

**Q-FLOW (graph + rules). "Which intermediaries actually control deal flow in our sectors, and where is our coverage weakest?"**
- Technique: graph of intermediaries, sponsors and companies from transactions in the last 5 years scoped to Fund IV sectors; `betweenness_centrality` and `pagerank`; `CoverageGap` rule: top-decile centrality and bottom-quartile CRM touchpoints over 24 months.
- Planted: a boutique ("Harbor Lane Advisors") with only 9 deals that bridges founder-owned healthcare-services companies to 5 different sponsors, ranks number 2 by betweenness, has had 1 touchpoint with us in 2 years, and advised target 3's last recap (closing the loop from Q-PATH).
- Decoy: a high-volume bank with 60 deals, mostly outside our sectors, that tops a deal-count league table but ranks low in sector-scoped centrality.
- Why SQL fails: centrality is a global property of the network, not a count.

**Finale (rules composing graph output, Tier-2 live authoring).** The presenter types: "Add a rule: targets we can reach in two hops or fewer get 10 access points, and flag any target that is a customer or supplier of a Fund III portfolio company as a conflict. Re-score." Claude Code authors the rule with `rai-rules-authoring`, re-runs, the ranking reshuffles and the decoy from Q-SCORE drops out. This is the moment that shows reasoners composing.

Backups:
- **Q-CONFLICT.** "Before we bid on X, does it conflict with anything we own, and would it breach Fund IV's sector concentration limit?" Reachability within 2 hops over commercial and ownership links plus a concentration rule.
- **Q-COMPETE.** "Which of our targets are competitor sponsors circling?" Competitor operating partners on target boards; targets similar to competitor platforms.
- **Q-EXEC.** "Which executives in our network have run a business like this target?" Similarity between career paths and the target's profile, for the management bench.

#### 7.4 Deal Graph Explorer views

- Global: search by company or person; click to expand 1 or 2 hops; edge-type toggles (tenure overlap, board, deal, commercial, CRM); a side panel showing the business-language rule that produced any highlighted fact.
- Scorecard (Q-SCORE): ranked list with tier chips, a component breakdown per company, and a badge for "not in CRM".
- Warm path (Q-PATH): pick a target, the shortest paths from our people light up, and each hop shows its evidence ("Overlapped at Brightwater Dental, 2015-2019, 4.0 years").
- Add-on map (Q-ADDON): platform-centric view; candidates sized by similarity and colored by community; shared customers listed; whitespace states shown.
- Deal flow (Q-FLOW): intermediaries sized by centrality with our touchpoint count overlaid; coverage gaps highlighted.
- Positions come precomputed from `exports/` so the layout is identical every run and screenshots stay stable.

#### 7.5 Demo arc (15-18 minutes)

1. Cold open (1 min): "Your CRM has about 200 companies in pipeline. The market has about 1,200 in your sweet spot. Which six do you call on Monday, and who makes the introduction?"
2. The model (2 min): explorer overview; one semantic layer over CRM, deal history, people and commercial data, living in their Snowflake.
3. Act 1 Q-SCORE (3 min), Act 2 Q-PATH (3 min), Act 3 Q-ADDON (3 min), Act 4 Q-FLOW (2 min); each act ends with the SQL-screen contrast.
4. Finale (3 min): live rule authoring, re-score.
5. Close (1 min): governed, explainable, in your Snowflake, and Claude is the interface.

### 8. Synthetic data spec

#### 8.1 Tables and target sizes (R05 may adjust, staying inside the caps)

| Table | Rows | Notes |
|---|---|---|
| SECTOR | 70 | 3-level hierarchy |
| REGION | 60 | states > census regions > US |
| SPONSOR | 40 | us plus about 39 competitors |
| FUND | 80 | vintages 2010-2025 |
| INTERMEDIARY | 50 | boutiques, regional banks, a few large banks, brokers |
| COMPANY | 1,200 | about 15% in thesis sectors and EBITDA band |
| PERSON | 2,500 | executives, board members, bankers, our team |
| ROLE_HISTORY | 3,500 | dated tenures; senior roles only |
| OWNERSHIP | 600 | current and historical |
| TRANSACTION | 500 | last 10 years |
| TRANSACTION_PARTY | 1,200 | buyers, sellers, advisors, co-investors |
| COMMERCIAL_LINK | 2,500 | customer / supplier edges |
| CRM_INTERACTION | 1,500 | our touchpoints |
| PIPELINE | 200 | our CRM stages |
| COMPANY_SIGNAL | 1,200 | dated readiness signals |
| **Total** | **about 15,200** | under the 16,000 cap |

#### 8.2 Principles

1. Signal first (P2), noise second (P5), in that order.
2. Ground truth never reaches Snowflake: `golden/` is local only, no ground-truth columns, planted entity IDs shuffled so they do not stand out.
3. Realism comes from `research/domain_brief.md` ranges: margins by sector, multiples, hold periods, tenure lengths, deal mix. No uniform random junk; use skewed, sector-specific distributions.
4. Deterministic: same seed, same bytes. `make data` twice produces identical CSV hashes (G2 check).
5. Names are procedurally generated and fictional; hero-visible names get the collision check in section 3.
6. Each planted answer has a story card in `golden/stories.md` (who, what, why it matters to a partner). R16 builds the talk track from these.

#### 8.3 Noise and decoys (P5)

- Bulk noise: realistic companies, people, tenures, deals and links that fill the market to the target sizes without creating competing answers.
- Decoys: at least one per hero question (section 7.3), each designed to fool the naive SQL screen and be correctly rejected by RAI.
- Near-misses: entities one condition away from qualifying (EBITDA just over the band, 11-month tenure overlap, similarity just under the cutoff), so the rules visibly do the work.
- After noise: G4 still green, decoys handled, caps respected.

### 9. Validation strategy

#### 9.1 Triangulation

Golden (generator intent) = oracle (independent pandas / networkx) = RAI (PyRel). On any disagreement, find which one is wrong. Never edit `golden/expected.json` to match RAI without a logged rationale and a Gatekeeper sign-off.

#### 9.2 Determinism and evidence

Every hero query runs twice per test session with identical output. Every answer row carries its why.

#### 9.3 Rehearsal (R17)

- Tier-1 prompts (the four acts): in `demo_workspace/`, run each verbatim prompt 3 times with
  `claude -p "<prompt>" --output-format stream-json --verbose --allowedTools "Bash(uv:*),Bash(python:*),Read,Glob,Grep,Skill"`,
  saving transcripts under `artifacts/rehearsal/`. Pass if 3 of 3 runs contain every golden entity name and no decoy name, the transcript shows an RAI skill in use, and median latency with a warm engine is 90 s or less.
- Tier-2 prompts (one ad-lib follow-up per act, for example "only show Texas and Florida targets", plus the finale rule): pass at 2 of 3. If a Tier-2 prompt fails, the script marks it optional and gives the fallback.
- Paraphrase robustness: one reworded version of each Tier-1 prompt must pass 2 of 3, because presenters never type the exact words.
- Cold run (G8): a fresh `git worktree` at HEAD; follow `RUNBOOK.md` literally from setup to the last act; open the explorer with Playwright and click through every act; time the whole path; screenshot each act into `artifacts/screenshots/`.
- Any flakiness goes back to R14 (CLAUDE.md, prompt wording, query docstrings) through a Fixer, then re-run.

### 10. Orchestrator loop, failure handling, degrade ladder

Loop:

```
read STATE.json; run `date`
ready = phase tasks whose dependencies are PASS and that have not started
spawn all ready tasks in one message (respect the concurrency limits)
on each reply:
  if STATUS = PASS -> spawn R18 Gatekeeper for that gate
  if Gatekeeper PASS -> update STATE.json, TaskUpdate, next
  if FAIL -> attempts += 1; if attempts <= MAX_ATTEMPTS_PER_GATE spawn R20 Fixer with the evidence
             else apply the next degrade step, log it, continue
  if BLOCKED -> log; continue every independent track; never idle
check the clock against the checkpoints
```

Time checkpoints from start: +1.5 h G1; +3 h G3; +5 h G5; +6.5 h G7; +7.5 h G8; then review cycles until the soft finish or the hard stop. If you are more than 1 hour behind at a checkpoint, apply the next degrade step.

Degrade ladder (apply in order, log each step in `STATE.json.degradations`):

1. Swap the failing hero question for its best backup.
2. Go to 3 hero questions.
3. Replace a misbehaving graph algorithm with a rules-based recursive equivalent (for example reachability as a recursive rule).
4. Drop Tier-2 live authoring from the main path; keep it optional in the script.
5. Explorer falls back to a static view per act generated from exports.

Never degrade: correctness of golden answers, the guardrails, the "nothing typed by hand" rule.

### 11. Morning report (R21)

`MORNING_REPORT.md`, readable in 3 minutes:

1. Verdict in one line: READY TO DEMO / READY WITH CAVEATS / NOT READY.
2. Gate table: status, attempts, evidence link, commit.
3. The four hero questions, each with its one-line answer and the SQL-vs-KG contrast.
4. How to run it: the 5 commands from `RUNBOOK.md`, and what to do 30 minutes before the meeting (`make warm`).
5. Decisions made on my behalf (from `DECISIONS.md`) that I should check.
6. Degradations applied and why.
7. Open MINOR findings.
8. Rehearsal stats: pass rates and latencies per prompt.
9. Cost: engine hours and warehouse usage, and confirmation that the engine is suspended.
10. Cleanup: the exact commands to drop the database, role and warehouse when the deal is done.

Start now: confirm `PROMPT.md` exists, create the phase tasks, write the initial `STATE.json`, then spawn R01 and R02 in parallel.
