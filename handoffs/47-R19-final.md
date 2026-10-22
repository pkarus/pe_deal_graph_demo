# Handoff 47 - R19 final review of the built demo (PE MD lens + demo-ops lens)

## Status
FAIL. 1 BLOCKER, 6 MAJOR, 9 MINOR. Read-only review; no deliverable edited, nothing touched the engine.

Read: PROMPT.md 2, 5 (R19 card), 7.5; MORNING_REPORT.md; artifacts/demo_script.html (rendered text); artifacts/screenshots/*.png; demo_workspace/prompts.md and CLAUDE.md; exports/q_score, q_path, q_flow, q_conflict, sql_baseline.json; artifacts/rehearsal/SUMMARY.md; final answers of T1-SCORE_run5, T1-PATH_run4-6, T1-FLOW_run4, T1-CONFLICT_run6, PARA-PATH_run1-3, T2-FINALE_run1-2. Prior findings in handoffs/25 and 35 checked as fixed.

## What works (keep it)
- Act 1 numbers agree everywhere: script, explorer, export and Claude (90/85/80/75/75/70, components sum correctly, 2 with no coverage). Claude uses "no coverage" correctly.
- Act 4 is the strongest act on screen. Claude's answer (T1-CONFLICT_run6) leads with "Yes to both", says "on hold until cross-fund clearance", gives $385M to $440M, 32.1% to 36.7%, over by $20M, headroom $35M. Script, explorer gauge and export agree to the dollar.
- Act 3 numbers agree (Cedar Row 7507.4 / 14 touchpoints, Harbor Lane 1667.4 / 1 touchpoint). The Harbor Lane to Saltmarsh chain into Act 2 is the right partner-grade so-what.
- Live Finale answers (T2-FINALE_run1 and run2) are correct and well worded: Tessmark on hold, Ashby Vale new to Tier A, Bayside #1 at 95.
- Cold open without a market size works: "Your pipeline has 200 names. PitchBook, Grata and your bankers will hand you thousands more."
- Fallbacks are layered and copy-pastable per act (live, `--from-exports`, second terminal, explorer).

## Findings

### B1. BLOCKER. The script's Finale, Close and Elevator name the wrong company on hold (Fairmarsh Health System, a Tier C score of 30)
- **Where:** artifacts/demo_script_template.html lines 607-610, 614, 622, 663, 677 (selector `q_score.finale.rows[conflict!=null][0]`). Rendered in artifacts/demo_script.html Finale "Expected answer" bullets, both `say` lines, "Click in the explorer", "Leave them with" and the Elevator.
- **Problem:** exports/q_score.json `finale.rows` now carries all 8 conflicted eligible targets (the Wexley superset change), sorted by name, so `[0]` is Fairmarsh. The presenter is told to say "Fairmarsh Health System keeps its score of 30 but ... comes off the Tier A call list" (it was never on it), "the others come back clean" (7 others are flagged), and in the Close and Elevator "with only Fairmarsh Health System on hold" (8 are). Claude's live and prebuilt answers say Tessmark. At the climax the presenter contradicts the screen, and the Act 4 to Finale payoff ("the check we ran by hand for one name now runs on every target") is lost.
- **Fix:** change the selector at all six places to the Tier A conflict, e.g. `q_score.finale.rows[conflict!=null][prev_tier=A][0]` (or `[company_id=C8200]` if the builder lacks chained filters). Reword line 614 "and the others come back clean" to "and the other Tier A names come back clean; 7 smaller names are flagged too". Reword lines 663 and 677 "with only X on hold" to "with Tessmark Clinical Supply, our Act 4 target, on hold until cleared". Then `make artifacts` (template-only; does not touch the engine or export.py, so the warm server stays valid).

### M1. MAJOR. In Act 2, Claude sometimes calls the Larkspur path a "stretch" and says only Bayside is warm
- **Where:** demo_workspace/CLAUDE.md line 10 (Facts: "Warm-path reach is measured to the target's current CEO, within 2 hops"). Seen in artifacts/rehearsal/T1-PATH_run5 ("our warm-path standard counts only paths of 2 hops or fewer. So only Bayside has a real warm path. Larkspur is a stretch") and PARA-PATH_run2. 2 of 7 Act 2 answers.
- **Problem:** the script hand-off says "2 of the top 3 have a warm route in", and the presenter's Larkspur line ("Priya calls Sofia this week") depends on that path being real. Claude undercutting it on screen makes the presenter look unprepared. The 2-hop rule is the Finale access-point rule, not the Act 2 definition.
- **Fix:** in CLAUDE.md line 10 replace the second sentence with: "In Act 2 (q_path) any path the query returns, up to 3 hops, is a warm path; do not call it a stretch or apply a 2-hop standard. The 2-hop limit applies only to the Finale access-points rule." Note: CLAUDE.md is not in the warm-server fingerprint per MORNING_REPORT 7, but confirm before editing during the test window.

### M2. MAJOR. Explorer and script say "3 Warm targets" for Act 2; the answer is 2 warm, 1 cold. The false intro is labelled "agrees"
- **Where:** exports/sql_baseline.json `questions.Q-PATH.kg_count = 3`, `rows[0].verdict = "agrees"`; produced by pe_deal_graph/export.py around line 1777 (`verdict = "agrees" if entity in kgset`). Visible in artifacts/screenshots/act2_path.png ("KNOWLEDGE GRAPH 3 Warm targets") and demo_script.html Act 2 SQL contrast ("The model keeps 3 (Warm targets)", table row "Saltmarsh Home Infusion | 1 | agrees | claims Tom Harlowe knows Victor Hale").
- **Problem:** the KPI tile contradicts Claude ("Saltmarsh: cold") and the hand-off. "agrees" next to the exact claim the demo debunks is a laugh line if the toggle is opened.
- **Fix (after the test window; export.py edit invalidates the warm server):** for Q-PATH set `kg_count` to the number of targets with `status == "warm"` and set `verdict = "decoy"` with the tenure-gap note on the false-intro row. Until then, presenter tip: do not point at the Warm path KPI tile.

### M3. MAJOR. Act 1 SQL contrast shows the decoys without saying why they are wrong
- **Where:** demo_script_template.html line 264 (`{{ @sql.rows[0].note | opt }}` renders "The screen's top name is Cobalt Urgent Care Partners: -"); exports/sql_baseline.json Q-SCORE rows all `verdict: "other"`, `note: null`; script line "Toggle the naive SQL list: decoys struck through with the reason" (nothing is struck through, because export.py never emits `decoy`).
- **Problem:** the contrast's punchline is "the screen's top 3 are wrong". The presenter has no reason on the page, and the explorer cannot strike them.
- **Fix:** quickest, template only: replace line 264 with static reasons from data/golden/expected.json: "Cobalt Urgent Care Partners: 5 signals, none a readiness signal, and its sponsor bought it 18 months ago. Pembrook Veterinary Pharmaceuticals: veterinary pharma is outside the thesis tree. Linden Hollow Senior Care: skilled nursing is excluded from the thesis." Proper fix later: export.py marks golden decoys `verdict="decoy"` with these notes.

### M4. MAJOR. The Finale cutoff (3:00) is below the rehearsal median (191 s), so the plan expects the live attempt to be aborted
- **Where:** demo_script_template.html lines 631-633; demo_workspace/prompts.md line 89; run of show "Finale 3 min".
- **Problem:** T2-FINALE_run1 succeeded fully live at about 191 s. Under the current rule the presenter presses Esc at 3:00 on a run that would have finished at 3:11, then waits another 15-30 s for the prebuilt. Ops-wise this converts the best moment of the demo into a visible abort most of the time.
- **Fix:** set the cutoff to 4:00 (keep "first failure" as the other trigger), budget the Finale at 4 min, and take the minute from "The model" (2 to 1 min). Add a talk track for the wait: "While it writes the rules, here is what they will do" and walk the explorer Scorecard Finale toggle. Update both files with the same numbers.

### M5. MAJOR. "Near misses" are 12 alphabetical "Amber..." companies, starting with a car wash
- **Where:** exports/q_score.json `ineligible` (pe_deal_graph/export.py line 1002, first 12 by name); rendered in demo_script.html Act 1 "Near misses the rules reject" and in the explorer Scorecard sidebar "NEAR MISSES (INELIGIBLE)" (visible in artifacts/screenshots/act1_score.png on the default view).
- **Problem:** a partner reads "near miss: Amberbury Auto Spa, car wash outside the thesis" and "Amberby / Ambercombe / Amberdale / Amberdale..." and concludes the data is generated. The real near miss (Ashby Vale, 65, Tier B, why it misses Tier A) is not shown.
- **Fix:** after the test window, export the near misses as the top Tier B rows by score (Ashby Vale 65 first) with their missing components, plus in-thesis names just under the EBITDA band sorted by EBITDA descending. Now: presenter tip, collapse or scroll past the sidebar; in the script, replace the table header with "Ineligible examples (not near misses)".

### M6. MAJOR (verify on the presenter's screen). Explorer graph canvases render as a collapsed clump in the screenshots
- **Where:** artifacts/screenshots/overview.png (600 nodes in a small cluster at centre right, outliers stretch the frame), act2_path.png (Ruth Adeyemi, Nathan Cole, Sofia Brandt, Priya Raman and their edge labels stacked on top of each other), act3_flow.png (Harbor Lane, Tullbrook, Ostwood, Coppervale labels overlapping). Code: artifacts/build_explorer.py layout / fit step.
- **Problem:** "The model" segment and the explorer fallbacks for Acts 2 and 3 open on these views. If the live render matches the screenshots, the path is unreadable and the fallback does not save the act.
- **Fix:** open the explorer now and check each view. If it matches: fit-to-view on the selected subgraph after layout settles and spread the warm-path nodes on a fixed left-to-right layout (seed to CEO). If it is only a screenshot timing artifact, retake the screenshots after the layout settles.

### m1. MINOR. Act 4 spoken line is missing a full stop
- **Where:** demo_script.html Act 4 `say`: "Tessmark Clinical Supply supplies Pinewick Dermatology Partners That needs cross-fund review."
- **Fix:** add "." after the evidence placeholder in the Act 4 `say` in the template.

### m2. MINOR. Templating artifacts read as machine output
- **Where:** demo_script.html and explorer: "has 3 hop(s)", "touched it 1 time(s)", "2 conflict row(s)", "1 touchpoint(s)", "the gap was 1 days", "1 \"connections\"", deal hop "0.0 years".
- **Fix:** add a plural filter in artifacts/build_script.py and build_explorer.py; hide the duration on single-date deal hops.

### m3. MINOR. Act 3 intermediary count disagrees: script "ranks 50 intermediaries", Claude "1st of 34"
- **Where:** demo_script.html Act 3 expected answer (`graph_stats.num_intermediaries = 50`) versus exports/q_flow.json `intermediaries` (34 rows) used by Claude (T1-FLOW_run4).
- **Fix:** script text "ranks the 34 intermediaries active in our sectors" or have the export emit both counts with labels.

### m4. MINOR. The Finale prompt asks for the flag "hold until cross-fund clearance"; the prebuilt label is "Conflict - cross-fund review"
- **Where:** prompts.md Finale; demo_script.html Finale table "75 (Conflict)"; explorer conflict badge.
- **Fix:** label the finale tier "On hold: cross-fund clearance" in the script table and explorer (Claude already renders it that way). Keep "Conflict - cross-fund review" as the Act 4 exposure kind.

### m5. MINOR. Finale "Change" column dumps the whole score explanation
- **Where:** demo_script.html Finale expected table, Bayside and Ashby Vale rows.
- **Fix:** render only the added component: "+10 Warm path to the CEO (CEO at 2 hops)".

### m6. MINOR. Act 1 Claude closer overstates the CRM gap
- **Where:** T1-SCORE_run5 last line: "A CRM screen would miss Saltmarsh and Fenwick entirely ... none of that is logged in the CRM." Sponsor-backed names are in DealCloud via PitchBook (R19a M1).
- **Fix:** CLAUDE.md "Answer format", add: "For Act 1, say the CRM has no coverage of them (no pipeline entry, no touch), not that the CRM would miss them."

### m7. MINOR. A one-day handover is shown as a rejected relationship on Larkspur's default panel
- **Where:** artifacts/screenshots/act2_path.png: "Both worked at Larkspur Revenue Partners. Rejected ... the gap was 1 days" (Martin Greer 2019-04-15 to 2021-05-31, Owen Lacey from 2021-06-01).
- **Problem:** a partner sees a board-seat handover between two Kestrelmoor designees and says "of course they know each other".
- **Fix:** in build_explorer.py, show rejected claims only when the gap is over 90 days, or relabel "no overlap; possible handover, not scored".

### m8. MINOR. Explorer Act 1 header says "next 12 months"; the prompt says "12 to 18 months"
- **Where:** exports/q_score.json `business_question`; act1_score.png header.
- **Fix:** align the export string to "12 to 18 months" at the next export.

### m9. MINOR. Act timings are tight against Claude latency
- **Where:** run of show: Act 4 is 2 min; Claude median 73 s, max 76 s (set B), plus talk.
- **Fix:** make Act 4 3 min and the Close 30 s, or accept running long; talk through the business setup while Claude runs (already in the script).

## Presenter tips
- Practice the Finale wait: talk over the explorer Finale toggle while Claude writes the rules, and practise the exact Esc plus "use the prebuilt version" move at the cutoff.
- Prepare the Larkspur answer: "warm at 3 hops through Sofia at Cedar Row, the banker running the sale, so it earns no Finale access points; the play is an early look". This covers both M1 and a partner asking why Larkspur gets no +10.
- Until B1 is rebuilt, say Tessmark Clinical Supply, never Fairmarsh, in the Finale, Close and Elevator.
- In the explorer, avoid the Warm path KPI tile ("3 Warm targets") and the near-miss sidebar; open the views you will use once before the meeting.
- In Act 1, give the decoy reasons from memory: Cobalt (no readiness signal, bought 18 months ago), Pembrook (vet pharma, off thesis), Linden Hollow (skilled nursing, excluded).
