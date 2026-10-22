# Test plan: hands-on demo test (Claude Code, demo_workspace/)

Values are copied from exports/*.json (AS_OF 2026-10-01). Latencies are rehearsal medians on a warm server (artifacts/rehearsal/SUMMARY.md); a sequential live run is usually faster. Fail the act if over 90 s.

## 0. Pre-flight
- [ ] Engine is already warm and the query server is running. Start Claude Code with `cd demo_workspace && claude`.
- [ ] Check: `cd demo_workspace && uv run python ask.py --check`
- [ ] Do not edit code and do not run `make export` while testing (it breaks the warm server and the live answers).

## 1. The five acts (type `/clear` + Enter before each Tier-1 prompt; never between a prompt and its ad-lib)

### Act 1 Q-SCORE (median 57 s)
- [ ] Paste: `Which companies fit the Fund IV thesis and look ready to transact in the next 12 to 18 months? Show the Tier A list with the score components behind each one, and flag any that are not in our CRM.`
- [ ] Must contain 6 Tier A, in order: Larkspur Revenue Partners 90, Bayside Pediatric Therapy Group 85, Saltmarsh Home Infusion 80, Quarry Records Retrieval 75, Tessmark Clinical Supply 75, Fenwick Food Safety Labs 70
- [ ] Components shown (fit, readiness, access; e.g. Larkspur 30/50/10); not in CRM: Saltmarsh Home Infusion, Fenwick Food Safety Labs
- [ ] Must NOT appear: Cobalt Urgent Care Partners, Pembrook Veterinary Pharmaceuticals, Linden Hollow Senior Care, Northgate Behavioral Health
- [ ] Explorer: Scorecard view; click Larkspur Revenue Partners row for its components
- [ ] Fallback: `uv run python ask.py --from-exports q_score`

### Act 2 Q-PATH (median 73 s)
- [ ] Paste: `For our top three targets, what is our warmest path to each CEO, and through whom? Show every hop with its evidence, check the owner's board designee for sponsor-owned targets, and say plainly if a target is cold.`
- [ ] Larkspur Revenue Partners: warm, 3 hops, strength 0.7, to CEO Ruth Adeyemi (owner Kestrelmoor Capital, designee Owen Lacey cold)
- [ ] Bayside Pediatric Therapy Group: warm, 2 hops, strength 0.6, to CEO Daniel Reyes (via Marcus Whitfield, Elena Marsh)
- [ ] Saltmarsh Home Infusion: COLD, CEO Victor Hale, owner Coppervale Partners, designee Graham Pike cold; closest door Harbor Lane Advisors
- [ ] Must NOT appear as a path: Tom Harlowe, Varnell Lab Services (false intro), "we know Coppervale"
- [ ] Explorer: Warm path view; click Saltmarsh Home Infusion (cold), then Bayside
- [ ] Fallback: `uv run python ask.py --from-exports q_path`

### Act 3 Q-FLOW (median 58 s)
- [ ] Paste: `Which intermediaries actually bridge deal flow in our Fund IV sectors, and where is our coverage weakest? Show the five that bridge the most deal flow, our touchpoints with each over the last 24 months, and any coverage gap.`
- [ ] Top 5 (touchpoints in 24m): Cedar Row Partners 14, Harbor Lane Advisors 1, Wilby Securities 5, Umberby & Co. 7, Wexhall Bank Capital 4
- [ ] Gap: Harbor Lane Advisors (rank 2, betweenness 1667.4, 1 touchpoint). Cedar Row is rank 1 (7507.4)
- [ ] Must NOT appear in the top 5: Brayford Capital Markets
- [ ] Explorer: Deal flow view; click Harbor Lane Advisors
- [ ] Fallback: `uv run python ask.py --from-exports q_flow`

### Act 4 Q-CONFLICT (median 73 s)
- [ ] Paste: `Before we bid on Tessmark Clinical Supply, does it conflict with anything we own, and would the deal push Fund IV over its sector concentration guideline?`
- [ ] Conflict: Pinewick Dermatology Partners (Fund III, 1 link, "Conflict - cross-fund review"); informational: Ironvale Testing Group (Fund IV, 2 links)
- [ ] Concentration: Specialty Distribution 32.08% to 36.67% after a $55M check, guideline 35%, breach, over by $20M, headroom $35M
- [ ] Must NOT appear: Cobbleton Dental Group, Redfern Imaging Centers
- [ ] Explorer: Conflict check view (centered on Tessmark Clinical Supply)
- [ ] Fallback: `uv run python ask.py --from-exports q_conflict`

### Finale: see section 3 (median 191 s, one run via prebuilt)
- [ ] Explorer: Scorecard, Finale toggle. Fallback: `uv run python ask.py finale_rescore` (or `--from-exports finale_rescore`)

If an act stalls: ask `Run uv run python ask.py <function> and show the result as a table with the why for each row.` If it errors, use `--from-exports`, then the explorer (open artifacts/deal_graph_explorer.html).

## 2. Paraphrases (rehearsed 3 of 3; same must-contain and must-not lists as above) and Tier-2
- [ ] Q-SCORE: `Give me the Tier A targets for Fund IV, the ones that fit the thesis and could trade in the next year or so. Break down each score and tell me which ones we don't have in the CRM.`
- [ ] Q-PATH: `Who on our team can get us an intro to the CEOs of the top three names? Walk me through each connection hop by hop, look at the owning sponsor's board designee where there is one, and tell me if any of them is a cold call.`
- [ ] Q-FLOW: `Which bankers and advisors really sit in the middle of deal flow in our Fund IV sectors? Show the top five, how often we have been in touch with each over the last two years, and where we are barely covered.`
- [ ] Q-CONFLICT: `We are about to go after Tessmark Clinical Supply. Is there a conflict with our existing portfolio, and would the deal take Fund IV over its sector concentration guideline?`
- [ ] Tier-2 SCORE (rehearsed 2/2): `Only show the founder-owned names.` Expect Bayside Pediatric Therapy Group, Quarry Records Retrieval, Tessmark Clinical Supply
- [ ] OPTIONAL Tier-2 PATH (1 of 2, slow): `Why isn't Tom Harlowe's Varnell Lab Services connection a path to Victor Hale?` Expect left June 2011, Hale arrived March 2013, no overlap
- [ ] OPTIONAL Tier-2 FLOW (1 run): `Which of Harbor Lane Advisors' deals involve companies on our Tier A list?` Expect Saltmarsh Home Infusion
- [ ] OPTIONAL Tier-2 CONFLICT (never run): `What is the largest check we could write without breaching the guideline?` Expect $35M
- [ ] OPTIONAL backup Q-ADDON: `Which add-ons best extend our Ironvale Testing Group platform, beyond the obvious same-niche names? Show the shared customers and the new states each one adds.` Expect Fernhollow Environmental Labs (Jaccard 0.2727; Colorado, Utah, New Mexico)

## 3. Finale live authoring (`/clear` first, fresh session)
- [ ] Paste: `Add two rules and re-score. One: a target gets 10 access points if one of our deal team or operating partners can reach its CEO in two hops or fewer. Two: any target that is a customer or supplier of a current Fund III portfolio company needs cross-fund clearance, so flag it "hold until cross-fund clearance" and keep it off the Tier A call list until it is cleared.`
- [ ] Expected: Bayside Pediatric Therapy Group moves to #1 at 95; Larkspur Revenue Partners 90, Saltmarsh Home Infusion 80, Quarry Records Retrieval 75, Ashby Vale Dental Partners 75 (up from Tier B, 65), Fenwick Food Safety Labs 70
- [ ] Tessmark Clinical Supply keeps 75, flagged "Conflict - cross-fund review" (hold until cross-fund clearance), NOT in the Tier A rows; described as on hold, not dropped
- [ ] Cutoff: one live attempt. After the first error, empty table, or 3 minutes, type `use the prebuilt version`; it runs `ask.py finale_rescore` (about 14 s)
- [ ] Time the run: ______ s; live or prebuilt: ______

## 3b. Text queries (ad-hoc, not rehearsed yet; full bank in demo_workspace/query_bank.md)
Ask each after the act shown, in the same session as that act. Expected values come from the offline pandas oracle (`scripts/query_bank_oracle.py`). Scratch-query questions run in-process: expect about 60-90 s; fail if over 120 s or if it defines a rule.
- [ ] T1 (Act 1, hero rows): `Why is Fenwick Food Safety Labs Tier A when nobody here covers it?` Expect 70 = Fit 30 + Readiness 40 + Access 0; exit window (Sablewood Equity Fund II, 2015, held since 2020-06-30), banker engaged 2026-09-08 (Brackden Partners), debt 2027-08-15, new director Elise Marchetti 2026-01-20; no pipeline row, no CRM touch ("no coverage")
- [ ] T2 (Act 1): `Which of our targets hired a CFO from a PE-backed company in the last 18 months, and from where?` Expect 4: Larkspur Revenue Partners (Rohan Falkner, Flintstead Payroll Services), Bayside Pediatric Therapy Group (Elena Marsh, "a former Northwind portfolio company"), Saltmarsh Home Infusion (Wes Okonkwo, Sorrhall Hospice), Quarry Records Retrieval (Leon Galloway, Kestwood Claims Services). Must NOT appear: Cobbleton Dental Group
- [ ] T3 (Act 1): `Which of our scored targets are owned by a sponsor that is in its exit window?` Expect 4: Larkspur Revenue Partners (Kestrelmoor Capital Fund I, 7.5 years), Saltmarsh Home Infusion (Coppervale Partners Fund II, 6.1), Fenwick Food Safety Labs (Sablewood Equity Fund II, 6.3), Nettlewell Home Nursing (Tier B 55, Calfield Equity Fund III minority, 5.3). Must NOT appear: Cobalt Urgent Care Partners
- [ ] T5 (Act 1): `Which Fund IV targets headquartered in Texas are Tier A or Tier B?` Expect 2: Larkspur Revenue Partners 90 A ($26.0M EBITDA), Fairhaven Revenue Cycle 50 B ($26.9M). Must NOT appear: Cobalt Urgent Care Partners
- [ ] T6 (Act 2): `Who runs Saltmarsh Home Infusion today, and who sits on its board?` Expect Victor Hale CEO (since 2020-11-02), Wes Okonkwo CFO (2025-11-03), Graham Pike Board (2020-09-01, also at Coppervale Partners, the owner). Must NOT appear: Tom Harlowe, Varnell Lab Services
- [ ] T11 (Act 4): `What does Fund IV own today, how much equity is in each, and in which thesis area?` Expect 5: Ironvale Testing Group $150M, Tullmere Chemical Distribution $140M, Flintmoor Industrial Supply $125M, Primdale Ingredients Co $120M, Quillmont Physical Therapy $110M; Specialty Distribution $385M = 32.1%. Must NOT appear: Cobbleton Dental Group, Redfern Imaging Centers
- [ ] Time each: T1 ___ s, T2 ___ s, T3 ___ s, T5 ___ s, T6 ___ s, T11 ___ s

## 4. Report back (send to the build team)
- [ ] Which act and which prompt (paste the exact text, note paraphrase or ad-lib)
- [ ] Wall-clock time, and whether it said "ran in N s on the warm query server" or ran in-process
- [ ] What appeared: wrong or missing golden name, any decoy name, wrong number, invented rows, wording such as "removed" or "disqualified"
- [ ] Any error text (exit 3, engine, auth, SnowflakeTableObjectsException) and whether `ask.py --check` was still OK afterwards
- [ ] Whether the fallback command and the explorer view matched the numbers above
- [ ] Anything that felt slow, wandering, or confusing for a PE audience
