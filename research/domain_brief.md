# Domain brief: US lower-mid-market buy-and-build (R02, as of 2026-10-21)

[n] = source. EST = unsourced estimate: a generator setting only, never quoted on stage.

## 1. Vocabulary: say this, not that

| Say | Not | Note |
|---|---|---|
| platform; add-on (tuck-in, bolt-on) | "parent", "subsidiary deal" | Platform = first investment; add-ons are bought by it. |
| off-market, limited process; banked auction | "proprietary" as a boast | Partners know most "proprietary" deals still have a banker somewhere. |
| fits the Fund IV thesis | "matches our filters" | Sector, size, geography, value-creation plan. |
| sponsor-backed vs. founder- or family-owned | "PE investor", "VC" | |
| secondary buyout (SBO), sponsor-to-sponsor | "resale" | Both buyer and seller are PE firms [14]. |
| majority recap or dividend recap | bare "recap" | Recap = capital-structure change [15]; in LMM (lower-mid-market) usage often a founder selling control and rolling equity. |
| coverage; coverage gap | "banker CRM" | The managed list of banks, boutiques, brokers. |
| sell-side advisor (ran the sale); banker (generic) | "broker" for an M&A bank | Business brokers do sub-scale deals. |
| likely to transact in 12-18 months | "for sale" | |
| TEV/EBITDA, "turns", adjusted EBITDA | "P/E" | |
| warm path, with evidence | "they know each other" | Every hop has a reason. |
| hold period; exit window; vintage; harvesting | "investment age" | |

## 2. Realism ranges for the generator

**Hold periods (verified).** Private Equity Info median hold at exit, 2025, ranges from 5.6 years (Technology, Financial Services) to 6.6 (Healthcare Services) across nine industries, based on 13,757 exits over 2021-2026 YTD [1]. The median rose from 5.0 to 6.0 years in four years [2]; 2026 exits so far: 6.2 [3]. Bain's *average* hold at exit is about 7 years, and almost 40% of companies are held over 5 years [4].

**EV/EBITDA, US LMM platforms (GF Data, first 9 months of 2025, 211 deals with TEV $10-500M)** [6]: $10-25M 5.9x; $25-50M 6.6x; $50-100M 8.7x; $100-250M 10.0x; $100-500M 9.8x. Full-year 2025 average 7.2x, flat on 2024 [7]. Through Q3 2025, business services rose about 0.3x year over year and manufacturing fell about 0.3x [8]. US public comparables in related industries: 11-17x (January 2026) [10].

| Parameter (generator setting) | Healthcare services | Tech-enabled bus. services | Industrial TIC | Specialty distribution |
|---|---|---|---|---|
| Adj. EBITDA margin, range (median) EST | 10-20% (14%) | 15-25% (18%) | 14-22% (17%) | 6-13% (9%) |
| Public anchor | Hospitals 15.8% EBITDA/sales [9] | Business and consumer services 15.7%, information services 17.3% [9] | Intertek FY2025 adj. operating margin 18.1% [11]; environmental and waste services 21.0% [9] | Retail (distributors) 11.4% [9] |
| TEV/EBITDA, EV $50-100M EST | 8-10x | 8.5-10.5x | 8.5-10.5x | 7-9x |
| TEV/EBITDA, EV $100-400M EST | 9.5-12x | 10-12.5x | 10-12.5x | 8.5-10.5x |
| Median hold at exit, 2025 [1] | 6.6 yrs | 5.7 yrs | 6.0 yrs (industrials) | no category (use 6.0) |

Sector spreads around the GF Data bands are EST. Damodaran's "Healthcare Support Services" (3.9%) mixes in low-margin distribution and managed-care businesses, so it is not used as an anchor [9].

**Other settings**

- Hold length draws: lognormal, median about 6 years [1][2]; 5th-95th percentile 3-10 years (EST).
- Add-on share of US buyout deal count: **not verified** (PitchBook returned HTTP 403). EST 65-75% for the generator; on stage say "most deals are add-ons".
- Fund life: 10 years, often plus one or two one-year extensions [13]. Exit window from about year 8; overdue at 10+.
- LMM fund size: EST $250M-1.5B (no source found); Northwind's $1.2B Fund IV is at the top.
- Tenure: sitting CEO average 7.1 years, CFO 4.5 (Fortune 500 and S&P 500, mid-2026) [12]. LMM EST: founder CEOs 12-30 years, PE-appointed CEOs 3-6, CFOs 2-5, board seats 3-7.
- EBITDA $5-40M at these margins implies revenue of about $25-400M.

## 3. Competitive landscape

- **Affinity**: AI CRM; scores relationship strength from email and calendar data and "surfaces warm paths to target company decision-makers"; enriched from 40+ sources incl. PitchBook and Grata; MCP connection to Snowflake, Claude, ChatGPT [16].
- **DealCloud (Intapp)**: lifecycle CRM and system of record; also advertises warm paths and relationship strength; PitchBook, Preqin, FactSet feeds [17].
- **4Degrees**: private-markets CRM with relationship-strength scoring for "your best intro" [18].
- **Salesforce Financial Services Cloud**: general CRM unifying client data; not PE-specific [22].
- **PitchBook**: private-market company, deal and investor data; feeds the CRMs above [16][17].
- **Grata, Sourcescrub**: discovery of founder-owned LMM companies (22M+ [19]; 17M from 290,000 sources [20]); both Datasite, being combined [19][21].

**"Affinity already does this."** Affinity answers "who do we know there?" from our inbox. The demo answers "which companies, why now, who gets us in, and what does it do to the portfolio?" in one governed model: thesis fit over a sector hierarchy, readiness from dated signals, access via tenure-overlap paths, portfolio context (add-on fit, conflicts). Every point traces to a named rule and its evidence, running inside the firm's own Snowflake without data movement [23]. Affinity and PitchBook become inputs, not rivals. Do not claim others cannot reach Snowflake [16].

## 4. Three skeptical partner questions

1. **"Affinity or DealCloud already shows me warm intros."** Keep them; a path is one signal. Here it is weighted by tenure overlap and recency, false ties are rejected (Act 2 decoy), and it is combined with fit, readiness and conflicts under weights you control (finale).
2. **"Our CRM data is a mess. Garbage in, garbage out."** Each score shows its components and evidence, so missing data appears as a missing component, not a silent zero. Start with three sources already in Snowflake: CRM, deal history, a vendor feed.
3. **"Would I bet a deal on a score?"** No. It ranks who to call Monday and why; the rules are business language in your Snowflake, editable in a sentence. The opposite of a black box.

## 5. Corrections to section 7.1

1. Hold periods: **verified.** The page is now titled "PE Hold Periods by Industry" (2026-09-07) [1]. Business Services 5.7, Industrials 6.0, no distribution category. These are medians; Bain's about 7 years is an average [4]; do not mix them.
2. "Past about 5 years = exit window" is early: 83% of the 2021 vintage was still held at year 5 [2]. Use held 5+ years *and* fund 8+ years from vintage [13].
3. Add-on share: not verified; keep "majority", no number on screen.
4. "Auctions price out returns" is unsourced. Say "firms invest in off-market flow to avoid fully competitive auctions."
5. DealCloud also offers warm paths [17]; Grata and Sourcescrub share an owner, Datasite [19][21].
6. Section 7.2 transaction type mixes dimensions. Use `deal_role` (platform, add-on), `seller_type` (founder or family, sponsor = SBO, corporate carve-out) and `structure` (control buyout, majority recap, minority, dividend recap).
7. Keep multiples at 6-12.5x; Bain's 14.0x 2025 entry example is large-cap [5][6].

## Sources

1. https://privateequityinfo.com/blog/six-years-and-counting-the-new-reality-of-pe-holding-periods
2. https://privateequityinfo.com/blog/private-equity-median-hold-period-set-to-increase
3. https://privateequityinfo.com/blog/exits-rebound-in-2026-pulling-the-investment-to-exit-ratio-to-a-decade-low
4. https://www.bain.com/insights/outlook-gaining-traction-global-private-equity-report-2026/
5. https://www.bain.com/insights/welcome-to-a-new-era-global-private-equity-report-2026/
6. https://gfdata.com/size-premium-esop-competitive-advantage/
7. https://gfdata.com/year-end-ma-volume-hits-multi-year-low-as-market-navigates-choppy-conditions/
8. https://gfdata.com/private-equitys-five-year-rollercoaster/
9. https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/margin.html (January 2026 data)
10. https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html (January 2026 data)
11. https://www.intertek.com/siteassets/investors/2026/intertek-2025-full-year-results-announcement.pdf
12. https://www.cristkolder.com/s/2026-CKA-Volatility-Report-Americas-Leading-Companies.pdf (pp. 17, 21)
13. https://en.wikipedia.org/wiki/Private_equity_fund
14. https://en.wikipedia.org/wiki/Secondary_buyout
15. https://en.wikipedia.org/wiki/Leveraged_recapitalization
16. https://www.affinity.co/
17. https://www.intapp.com/dealcloud/
18. https://www.4degrees.ai/
19. https://grata.com/
20. https://www.sourcescrub.com/
21. https://grata.com/newsletter/how-its-made-quality-private-market-data
22. https://www.salesforce.com/financial-services/
23. https://www.relational.ai/post/relationalai-launches-genai-powered-decision-intelligence-system-on-the-snowflake-ai-data-cloud
