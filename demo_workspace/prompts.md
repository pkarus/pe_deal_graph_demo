# Demo prompts

**Status: FINAL v2.** Tier-1 text is verbatim from QUESTIONS.md v2 (R20 Fixer, accepted by R04 attempt 2) with the final fictional names from data/golden/stories.md substituted. Arc: Q-SCORE, Q-PATH, Q-FLOW, Q-CONFLICT, Finale. Q-ADDON is a backup.

Type each prompt into Claude Code started in `demo_workspace/`. Before each act's Tier-1 prompt (and before the Finale prompt), type `/clear` and press Enter, so every act starts from the same empty context as rehearsal. Never `/clear` between a Tier-1 prompt and its ad-lib. Each act has a prebuilt fallback: `uv run python ask.py <function>`, and with no engine `uv run python ask.py --from-exports <function>` (RUNBOOK.md, "Fallback per act").

Rehearsal (PROMPT.md 9.3): Tier-1 verbatim must pass 3 of 3; Tier-2 and paraphrases must pass 2 of 3. No Tier-1 prompt or paraphrase invites an answer that names a decoy. Tier-2 prompts may name a decoy on purpose, and the check there is row-based.

## Act 1. Q-SCORE (rules), function `q_score`

Tier-1 (verbatim):

> Which companies fit the Fund IV thesis and look ready to transact in the next 12 to 18 months? Show the Tier A list with the score components behind each one, and flag any that are not in our CRM.

Paraphrase:

> Give me the Tier A targets for Fund IV, the ones that fit the thesis and could trade in the next year or so. Break down each score and tell me which ones we don't have in the CRM.

Tier-2 ad-lib:

> Only show the founder-owned names.

Expected: Bayside Pediatric Therapy Group, Quarry Records Retrieval, Tessmark Clinical Supply (the off-market cut; the other three are sponsor-backed).

## Act 2. Q-PATH (graph + rules), function `q_path`

Tier-1 (verbatim):

> For our top three targets, what is our warmest path to each CEO, and through whom? Show every hop with its evidence, check the owner's board designee for sponsor-owned targets, and say plainly if a target is cold.

Paraphrase:

> Who on our team can get us an intro to the CEOs of the top three names? Walk me through each connection hop by hop, look at the owning sponsor's board designee where there is one, and tell me if any of them is a cold call.

**Tier-2 ad-lib status: OPTIONAL - not rehearsed to threshold.** T2-PATH passed 1 of 2 (one engine error). Fallback: If the answer takes over 90 s or wanders, say "let me show the precomputed view" and run `uv run python ask.py --from-exports q_path`, or open the explorer view.

Tier-2 ad-lib:

> Why isn't Tom Harlowe's Varnell Lab Services connection a path to Victor Hale?

Expected: Tom Harlowe left in June 2011, Victor Hale arrived in March 2013, so they never overlapped. Naming both is correct here (row-based check). Second option: "We know Coppervale Partners. Doesn't that get us into Saltmarsh Home Infusion?"

## Act 3. Q-FLOW (graph + rules), function `q_flow`

Tier-1 (verbatim):

> Which intermediaries actually bridge deal flow in our Fund IV sectors, and where is our coverage weakest? Show the five that bridge the most deal flow, our touchpoints with each over the last 24 months, and any coverage gap.

Paraphrase:

> Which bankers and advisors really sit in the middle of deal flow in our Fund IV sectors? Show the top five, how often we have been in touch with each over the last two years, and where we are barely covered.

**Tier-2 ad-lib status: OPTIONAL - 1 run only.** T2-FLOW passed its only run. Fallback: If the answer takes over 90 s or wanders, say "let me show the precomputed view" and run `uv run python ask.py --from-exports q_flow`, or open the explorer view.

Tier-2 ad-lib:

> Which of Harbor Lane Advisors' deals involve companies on our Tier A list?

Expected: Saltmarsh Home Infusion. Second option, if a partner asks for volume: "How does that compare with a simple deal-count league table?" (Brayford Capital Markets tops the count and is not a top bridge; naming it is correct here, row-based check.)

## Act 4. Q-CONFLICT (graph + rules), function `q_conflict`

Tier-1 (verbatim):

> Before we bid on Tessmark Clinical Supply, does it conflict with anything we own, and would the deal push Fund IV over its sector concentration guideline?

Paraphrase:

> We are about to go after Tessmark Clinical Supply. Is there a conflict with our existing portfolio, and would the deal take Fund IV over its sector concentration guideline?

**Tier-2 ad-lib status: OPTIONAL - not rehearsed to threshold.** T2-CONFLICT was not run. Fallback: If the answer takes over 90 s or wanders, say "let me show the precomputed view" and run `uv run python ask.py --from-exports q_conflict`, or open the explorer view.

Tier-2 ad-lib:

> What is the largest check we could write without breaching the guideline?

Expected: $35M of headroom. Second option: "Our old portfolio list says Cobbleton Dental Group is a Tessmark Clinical Supply conflict. Is it?" (No, sold February 2020; row-based check.)

## Finale. Live rule authoring, fallback function `finale_rescore`

Tier-2 rule (verbatim; QUESTIONS.md v2 Finale reworded per R19a M6, same expected rows):

> Add two rules and re-score. One: a target gets 10 access points if one of our deal team or operating partners can reach its CEO in two hops or fewer. Two: any target that is a customer or supplier of a current Fund III portfolio company needs cross-fund clearance, so flag it "hold until cross-fund clearance" and keep it off the Tier A call list until it is cleared.

Paraphrase (2 of 3):

> Add a warm-path rule: 10 access points when someone on our team is within two hops of the target's CEO. Add a conflict rule: a customer or supplier of a current Fund III company gets flagged "hold until cross-fund clearance" and stays off the Tier A call list until it is cleared. Then re-score.

Expected shape: Bayside Pediatric Therapy Group moves to #1 at 95, Ashby Vale Dental Partners rises from Tier B (65) into Tier A at 75, and Tessmark Clinical Supply keeps 75 but is flagged "Conflict - cross-fund review" (hold until cross-fund clearance) and is not in the Tier A rows. The other Tier A names come back clear. Do not describe the hold as dropping the deal: it is a disclosure and clearance step for the conflicts committee. Reach means the current CEO within 2 hops, from any seed. Realistic timing: about 3 minutes (rehearsal runs were about 191 s, one via the prebuilt fallback). Fall back after the first failure or at 3 minutes, whichever comes first. If live authoring fails, the presenter says "here is the same rule, prebuilt" and Claude Code runs `uv run python ask.py finale_rescore`.

## Backup. Q-ADDON (graph), function `q_addon`

Use only as an ad-lib after Act 4 (Ironvale Testing Group came up as a shared customer).

Tier-1 (verbatim):

> Which add-ons best extend our Ironvale Testing Group platform, beyond the obvious same-niche names? Show the shared customers and the new states each one adds.

Expected top candidate: Fernhollow Environmental Labs (Jaccard 0.2727, adds Colorado, Utah and New Mexico).
