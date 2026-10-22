# Text query bank: ad-hoc questions for Claude Code

Owner: R14. Status: v1, designed offline. Expected answers come from `scripts/query_bank_oracle.py` (pandas over data/csv/, the loaded noisy data; its self-check matches exports/q_score.json: 248 scored, 6 Tier A, 15 Tier B, every Tier A and B score equal). **None of these prompts has been rehearsed live yet.** All data is synthetic, as of AS_OF = 2026-10-01.

Purpose: show that the semantic layer answers plain-English questions beyond the four hero prompts, using one short PyRel query over names that already exist (ONTOLOGY.md). No new rules.

## How Claude Code runs them

- **Answerable from hero rows** (marked *hero rows*): run the hero function through `ask.py` (warm server, seconds) and filter or explain its rows. This is the fastest and safest path. Hero rows cover Tier A only.
- **Otherwise**: one script in `scratch/<name>.py`, with the standard start from CLAUDE.md ("Finale building blocks"), then one `model.where(...).select(...).to_df()`. Import names from `pe_deal_graph.model.core` after `import pe_deal_graph.queries` (that import loads the rules and graphs; without it every derived name is empty). Never define a rule.
- **Timing, be honest:** a scratch query runs in-process, not on the warm server. Rehearsal saw 58-147 s for scratch PyRel (handoff 42), most of it compile. Plan on about 60-90 s per scratch question; *hero rows* questions take about 30-60 s end to end.
- Idioms (research/pyrel_cheatsheet.md): `X.ref()` for a second variable of the same concept; `.alias()` every column; sort in pandas after `to_df()` (row order is not guaranteed); `select` is left-outer, so filter with `where` to drop rows; no `desc` mixed with `asc`; dates are `dt.date(2026, 10, 1)` with `from relationalai.semantics.std import datetime as dt`.

Header used by every sketch (not repeated below):

```python
import os, sys; os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")); sys.path.insert(0, ".")
import pe_deal_graph.queries  # loads core, rules and graphs
from pe_deal_graph.model.core import model, Company, Person, Role, Region, Sector, Fund, Ownership, Intermediary, \
    Sponsor, Interaction, ScoreComponent, EligibleTarget, NorthwindHolding, BuyingFund, OurSeed, \
    DealFlowTransaction, TransactionParty
from relationalai.semantics import Float, Integer
from relationalai.semantics.std import datetime as dt
```

## SHOWCASE (the 6 most reliable)

| # | Act | Prompt | Path |
|---|---|---|---|
| T1 | 1 | Why is Fenwick Food Safety Labs Tier A when nobody here covers it? | hero rows (q_score) |
| T2 | 1 | Which of our targets hired a CFO from a PE-backed company in the last 18 months, and from where? | hero rows or one ScoreComponent query |
| T3 | 1 | Which of our scored targets are owned by a sponsor that is in its exit window? | one ScoreComponent query |
| T5 | 1 | Which Fund IV targets headquartered in Texas are Tier A or Tier B? | one query |
| T6 | 2 | Who runs Saltmarsh Home Infusion today, and who sits on its board? | one Role query (source data only) |
| T11 | 4 | What does Fund IV own today, how much equity is in each, and in which thesis area? | one Ownership query |

---

## Act 1. After q_score (rules)

### T1. Why is Fenwick Tier A with no coverage (SHOWCASE)

- **Prompt:** `Why is Fenwick Food Safety Labs Tier A when nobody here covers it?`
- **Business point:** every point is explainable, and the model reaches past the CRM: a Tier A name nobody owns.
- **Reasoner:** rule (explain).
- **Path:** hero rows. `uv run python ask.py q_score`, then read the Fenwick row (`why`, `in_crm`). PyRel only if the row is missing:

```python
c = Company.ref()
df = model.where(EligibleTarget(c), c.name == "Fenwick Food Safety Labs").select(
    c.score.alias("score"), c.tier.alias("tier"), c.fit_points.alias("fit"),
    c.readiness_points.alias("readiness"), c.access_points.alias("access"), c.why.alias("why")).to_df()
crm = model.where(c.name == "Fenwick Food Safety Labs", c.in_crm()).select(c.name.alias("n")).to_df()  # empty = no coverage
```

- **Expected:** score 70, Tier A (rank 6). Fit 30 + Readiness 40 + Access 0. Components: thesis fit 15 (Food Safety Testing under Testing, Inspection & Certification); EBITDA $12.0M +10; margin 18.2% vs 17.0% +5; sponsor exit window +15 (Sablewood Equity Fund II, vintage 2015, held since 2020-06-30 = 6.3 years); banker engaged 2026-09-08 (Brackden Partners) +10; debt matures 2027-08-15 +10; new independent director Elise Marchetti since 2026-01-20 +5. No pipeline row and no CRM touch: "no coverage".
- **Decoys (must not appear):** Cobalt Urgent Care Partners, Pembrook Veterinary Pharmaceuticals, Linden Hollow Senior Care, Northgate Behavioral Health.
- **Risk:** low. **Fallback:** `uv run python ask.py --from-exports q_score` and read the Fenwick row.

### T2. CFOs hired from PE-backed companies (SHOWCASE)

- **Prompt:** `Which of our targets hired a CFO from a PE-backed company in the last 18 months, and from where?`
- **Business point:** a temporal join SQL screens get wrong: the old employer had to be sponsor-owned *while the CFO worked there*.
- **Reasoner:** rule (R_CFO_FROM_PE).
- **Path:** hero rows answer it (all four are Tier A); the one-query version covers every scored target:

```python
k, c = ScoreComponent.ref(), Company.ref()
df = model.where(k.company(c), k.code == "R_CFO_FROM_PE").select(
    c.name.alias("name"), c.score.alias("score"), c.tier.alias("tier"), k.evidence.alias("why")).to_df()
df = df.sort_values(["score", "name"], ascending=[False, True])
```

- **Expected (4 rows, all Tier A):** Larkspur Revenue Partners (Rohan Falkner, hired 2025-07-01, from Flintstead Payroll Services, owned by Kestrelmoor Capital Fund II); Bayside Pediatric Therapy Group (Elena Marsh, 2025-06-01, from "a former Northwind portfolio company", owned by Northwind Equity Partners Fund II while she was there); Saltmarsh Home Infusion (Wes Okonkwo, 2025-11-03, from Sorrhall Hospice, Ridgeback Partners Fund III); Quarry Records Retrieval (Leon Galloway, 2025-05-05, from Kestwood Claims Services, Glenhallow Partners Fund IV). Not awarded to Ashby Vale Dental Partners (its CFO came from a founder-owned company) or Tessmark Clinical Supply (CFO in seat since 2016).
- **Decoys:** Cobbleton Dental Group (the governed evidence says "a former Northwind portfolio company"; quote the `why` column, do not rebuild it from Role rows).
- **Risk:** low. **Fallback:** answer from `ask.py q_score` rows (component "CFO from a PE-backed company").

### T3. Sponsors in their exit window (SHOWCASE)

- **Prompt:** `Which of our scored targets are owned by a sponsor that is in its exit window?`
- **Business point:** secondary-buyout supply: held 5+ years by a fund of vintage 2018 or older. A recent sponsor purchase does not count.
- **Reasoner:** rule (R_EXIT_WINDOW).
- **Path:** one query (hero rows would miss the Tier B name):

```python
k, c = ScoreComponent.ref(), Company.ref()
df = model.where(k.company(c), k.code == "R_EXIT_WINDOW").select(
    c.name.alias("name"), c.score.alias("score"), c.tier.alias("tier"), k.evidence.alias("why")).to_df()
df = df.sort_values(["score", "name"], ascending=[False, True])
```

- **Expected (4 rows):** Larkspur Revenue Partners 90 A (Kestrelmoor Capital Fund I, vintage 2016, held since 2019-04-15 = 7.5 years); Saltmarsh Home Infusion 80 A (Coppervale Partners Fund II, vintage 2017, since 2020-09-01 = 6.1 years); Fenwick Food Safety Labs 70 A (Sablewood Equity Fund II, vintage 2015, since 2020-06-30 = 6.3 years); Nettlewell Home Nursing 55 B (Calfield Equity Fund III, vintage 2016, since 2021-06-29 = 5.3 years; a minority stake, which the rule counts).
- **Decoys:** Cobalt Urgent Care Partners (Marmarsh Capital Fund II bought it 2025-04-01; only if the presenter asks).
- **Risk:** low-medium (scratch query time). **Fallback:** `ask.py q_score` rows give the three Tier A names; say "plus one Tier B name" only if the query ran.

### T4. Tier B names one signal from Tier A

- **Prompt:** `Which Tier B targets are one readiness signal away from Tier A, and which signal would get them there?`
- **Business point:** a watch list with a trigger: you know exactly which event to look for.
- **Reasoner:** rule (score components plus the 70-point threshold and the 50-point readiness cap).
- **Path:** one query for the awarded codes; the "missing" step is pandas over those rows:

```python
c, k = Company.ref(), ScoreComponent.ref()
df = model.where(EligibleTarget(c), c.tier == "B", c.score >= 55, k.company(c)).select(
    c.name.alias("name"), c.score.alias("score"), c.readiness_points.alias("readiness"),
    c.access_points.alias("access"), k.code.alias("code")).to_df()
# missing readiness code worth >= 70 - score (gain = min(50, readiness + pts) - readiness);
# R_EXIT_WINDOW needs a sponsor owner, so founder-owned names can only gain it from a CFO hire
```

- **Expected (6 names, each needs R_CFO_FROM_PE, +15):** Ashby Vale Dental Partners 65 (needs only 5: a PE-backed CFO hire, or a positive CRM touch, A_CRM +10, would also do it; it is the Finale riser); Nettlewell Home Nursing 55; Flintbury Animal Hospitals 55; Nettlehurst Dermatology 55; Salstow Lab Supply 55; Wilhall Health System 55. The eight Tier B names at 50 need 20 and are not one signal away.
- **Decoys:** none in scope.
- **Risk:** medium (Claude must reason over the codes; may also list exit window for founder-owned names). **Fallback:** show the 6 names with `why` and say "each is missing the PE-backed CFO hire".

### T5. Texas Tier A and B (SHOWCASE)

- **Prompt:** `Which Fund IV targets headquartered in Texas are Tier A or Tier B?`
- **Business point:** a simple filter over governed tiers; Texas has 31 scored companies but only two worth a call.
- **Reasoner:** lookup (filter on derived tier).

```python
c, r = Company.ref(), Region.ref()
df = model.where(EligibleTarget(c), c.hq_region(r), r.name == "Texas", c.score >= 50).select(
    c.name.alias("name"), c.score.alias("score"), c.tier.alias("tier"),
    c.ebitda_musd.alias("ebitda_musd"), c.why.alias("why")).to_df()
```

- **Expected (2 rows):** Larkspur Revenue Partners, 90, A, EBITDA $26.0M; Fairhaven Revenue Cycle, 50, B, EBITDA $26.9M (thesis, EBITDA, margin, banker engaged, debt maturing; no CRM touch).
- **Decoys:** Cobalt Urgent Care Partners (Texas, EBITDA $20.0M, Tier C 30); Tullmere Chemical Distribution and Ironvale Testing Group (Texas, already Northwind holdings). Do not ask for a "$10-25M EBITDA in Texas" list: it returns Cobalt.
- **Risk:** low. **Fallback:** say Larkspur from `ask.py q_score` and "one Tier B name, Fairhaven Revenue Cycle" only if the query ran.

## Act 2. After q_path (graph + rules)

### T6. Saltmarsh leadership and board (SHOWCASE)

- **Prompt:** `Who runs Saltmarsh Home Infusion today, and who sits on its board?`
- **Business point:** current roles are dated facts, so "today" is exact; the board seat is the owner's designee.
- **Reasoner:** lookup (source Role, `Role.is_current()`).

```python
c, ro, p = Company.ref(), Role.ref(), Person.ref()
df = model.where(c.name == "Saltmarsh Home Infusion", ro.organization(c), ro.is_current(), ro.person(p)).select(
    p.name.alias("person"), ro.role_type.alias("role"), ro.title.alias("title"), ro.start_date.alias("since")).to_df()
f = Fund.ref()
own = model.where(c.name == "Saltmarsh Home Infusion", c.current_owner_fund(f)).select(f.name.alias("owner")).to_df()
```

- **Expected (3 rows):** Victor Hale, CEO, since 2020-11-02; Wes Okonkwo, CFO, since 2025-11-03; Graham Pike, Board (Director), since 2020-09-01, who also holds a current role at Coppervale Partners (the owner, Coppervale Partners Fund II since 2020-09-01). No path within 3 hops to any of them (Act 2).
- **Decoys:** Tom Harlowe, Varnell Lab Services.
- **Risk:** low. **Fallback:** `ask.py q_path` rows (CEO and designee for Saltmarsh).

### T7. Who on our team is within two hops of Daniel Reyes

- **Prompt:** `Who on our team is within two hops of Daniel Reyes, and through whom?`
- **Business point:** relationship reach is computed over dated evidence, and a stale tie is shown for what it is.
- **Reasoner:** graph (materialized `Person.seed_hops`, plus `Person.knows` and `Person.tie_strength`).

```python
s, m, p, h = Person.ref(), Person.ref(), Person.ref(), Integer.ref()
w1, w2 = Float.ref(), Float.ref()
df = model.where(OurSeed(s), Person.seed_hops(s, p, h), p.name == "Daniel Reyes", h == 2,
                 s.knows(m), m.knows(p), Person.tie_strength(s, m, w1), Person.tie_strength(m, p, w2)).select(
    s.name.alias("our_person"), m.name.alias("via"), w1.alias("hop1"), w2.alias("hop2")).to_df()
# keep only rows where m is itself 1 hop from s and p (true by the joins); strength = hop1 * hop2
```

- **Expected (2 rows):** Marcus Whitfield via Elena Marsh (1.0 x 0.6 = 0.600; board and CFO at a former Northwind portfolio company 2015-2019, then Elena Marsh with Daniel Reyes at Bayside since 2025-06-01); Dana Okafor via Walter Kim (0.3 x 0.956 = 0.287; a 1998-2000 overlap at Oldmere Health System, stale). Nobody is 1 hop away.
- **Decoys:** Tom Harlowe (3 hops; out of scope at 2), Cobbleton Dental Group (cite it as "a former Northwind portfolio company", or quote `Knows.evidence`).
- **Risk:** medium (graph output in a fresh process; the join may also return the 3-hop seeds if `h == 2` is dropped). **Fallback:** `ask.py q_path` rows for Bayside (best path and alternate) or the explorer Warm path view.

### T8. Why was Tom Harlowe's intro rejected (not showcase)

- **Prompt:** `Why isn't Tom Harlowe's Varnell Lab Services connection a path to Victor Hale?`
- **Business point:** a shared-employer join invents introductions; the rule needs 12 months of real overlap.
- **Reasoner:** rule (explain K1 tenure overlap).

```python
o, ro, p = Company.ref(), Role.ref(), Person.ref()
df = model.where(o.name == "Varnell Lab Services", ro.organization(o), ro.person(p),
                 p.name.in_(["Tom Harlowe", "Victor Hale"])).select(
    p.name.alias("person"), ro.role_type.alias("role"), ro.start_date.alias("start"), ro.end_date.alias("end")).to_df()
```

- **Expected:** Tom Harlowe, CFO, 2008-01-07 to 2011-06-30; Victor Hale, COO, 2013-03-04 to 2020-08-31. A gap of about 20 months, no overlap, so no Knows edge (the rule needs 365 days); Victor Hale stays cold. Naming both is correct here (the presenter named them).
- **Decoys:** none (row-based check).
- **Risk:** high (rehearsal T2-PATH passed 1 of 2, slow, one engine error). **Fallback:** say it from this page, or open the explorer Warm path view for Saltmarsh (rejected claims panel).

## Act 3. After q_flow (graph + rules)

### T9. Our touchpoints with Harbor Lane

- **Prompt:** `Show every CRM touchpoint we have had with Harbor Lane Advisors in the last 24 months: who, when, channel and tone.`
- **Business point:** the coverage gap is a fact you can drill into, not a score.
- **Reasoner:** lookup (Interaction, plus `Intermediary.touchpoints_24m`).

```python
i, x, us = Intermediary.ref(), Interaction.ref(), Person.ref()
df = model.where(i.name == "Harbor Lane Advisors", x.counterparty_org(i), x.our_person(us),
                 x.interaction_date >= dt.date(2024, 10, 1), x.interaction_date <= dt.date(2026, 10, 1)).select(
    x.interaction_date.alias("date"), us.name.alias("our_person"), x.channel.alias("channel"),
    x.sentiment.alias("sentiment")).to_df()
n = model.where(i.name == "Harbor Lane Advisors").select(i.touchpoints_24m.alias("touchpoints_24m")).to_df()
```

- **Expected:** 1 touchpoint: 2025-11-20, Priya Raman, conference, neutral (touchpoints_24m = 1; Cedar Row Partners has 14). No touch with Celia Navarro or anyone else at Harbor Lane.
- **Decoys:** Brayford Capital Markets.
- **Risk:** low-medium. **Fallback:** `ask.py q_flow` rows (touchpoints column).

### T10. Who Harbor Lane connects in our sectors

- **Prompt:** `Which sponsors has Harbor Lane Advisors brought deals to in our Fund IV sectors over the last five years?`
- **Business point:** why a 9-deal boutique is the number 2 bridge: it feeds five different sponsors.
- **Reasoner:** graph (deal-flow edge set; same facts as `Organization.deal_flow_partner` advisor-buyer and advisor-owner edges).

```python
t, adv, side = DealFlowTransaction.ref(), TransactionParty.ref(), TransactionParty.ref()
i, sp, c = Intermediary.ref(), Sponsor.ref(), Company.ref()
df = model.where(adv.transaction(t), adv.organization(i), i.name == "Harbor Lane Advisors",
                 adv.party_role.in_(["sell_side_advisor", "buy_side_advisor", "debt_advisor"]),
                 side.transaction(t), side.organization(sp), t.target(c)).select(
    sp.name.alias("sponsor"), c.name.alias("target"), t.close_date.alias("closed"), side.party_role.alias("as")).to_df()
```

- **Expected:** 9 thesis deals (`thesis_deals_5y` = 9), 5 sponsors: Coppervale Partners (Langport Dermatology 2022-06-20, Millwood Home Health 2024-02-11, and owner on the Saltmarsh Home Infusion recap 2023-05-18); Tullbrook Capital (Foxmont Dermatology 2022-08-24, Holmere Dermatology 2024-01-03); Claywell Capital Partners (Winbrook Home Health 2024-02-19, Cinderford Veterinary Group 2026-07-24); Brammoor Capital (Tidbrook Urgent Care 2023-01-02); Ostwood Capital Partners (Northorpe Animal Hospitals 2025-12-14). Eight are founder-owned sell-side mandates.
- **Decoys:** Brayford Capital Markets.
- **Risk:** medium (two-party join on a derived subtype). **Fallback:** `ask.py q_flow` row for Harbor Lane, or the explorer Deal flow view (click Harbor Lane Advisors).

## Act 4. Before or after q_conflict

### T11. What Fund IV owns today (SHOWCASE)

- **Prompt:** `What does Fund IV own today, how much equity is in each, and in which thesis area?`
- **Business point:** "current" is a rule (time-bounded ownership), so a company sold years ago never shows up as ours.
- **Reasoner:** lookup (NorthwindHolding, BuyingFund, `Company.thesis_area`).

```python
o, c, f, a = Ownership.ref(), Company.ref(), Fund.ref(), Sector.ref()
df = model.where(NorthwindHolding(o), o.fund(f), BuyingFund(f), o.company(c), c.thesis_area(a)).select(
    c.name.alias("company"), o.equity_invested_musd.alias("equity_musd"), o.start_date.alias("since"),
    a.name.alias("thesis_area")).to_df()
df = df.sort_values(["equity_musd", "company"], ascending=[False, True])
```

- **Expected (5 rows, $645M of $1,200M):** Ironvale Testing Group $150M (since 2024-03-15, Testing, Inspection & Certification); Tullmere Chemical Distribution $140M (2023-11-01, Specialty Distribution); Flintmoor Industrial Supply $125M (2024-08-20, Specialty Distribution); Primdale Ingredients Co $120M (2025-06-02, Specialty Distribution); Quillmont Physical Therapy $110M (2023-09-12, Healthcare Services). Specialty Distribution = $385M = 32.1%, against the 35% guideline (sets up Act 4).
- **Decoys:** Cobbleton Dental Group (Fund II, sold 2020-02-14), Redfern Imaging Centers (Fund III).
- **Risk:** low. **Fallback:** `ask.py q_conflict` concentration rows (Specialty Distribution holdings).

## Not used (and why)

- "Our CRM touchpoints with Tessmark Clinical Supply in the last 12 months": the only touch (2026-06-10, positive meeting) and the pipeline owner are Tom Harlowe, a decoy name in rehearsal.
- "Fund IV targets in Texas with EBITDA of $10-25M": the top rows are Tier C and include the Cobalt Urgent Care Partners decoy (replaced by T5).
- "Who on our team is closest to Harbor Lane's Celia Navarro?": no seed within 3 hops, so the honest answer is an empty table.
- "Why is Northgate Behavioral Health not a target?": answerable (EBITDA $44.0M is above the $40M band, `Company.ineligible_reason`), but the prompt names a decoy; keep it for a partner who asks.
