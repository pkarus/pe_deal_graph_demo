"""Rules layer of the Northwind deal graph (owner: R09 Rules Engineer).

Business logic as derived properties on the shared model. Every contract name populated here is
declared in core.py (ONTOLOGY.md section 5, owner R09); this module only adds model.define(...) rules
and a few private helper relations (listed in HELPERS). Graph outputs this module consumes come
from graphs.py (R10) through contract names, never through an import:
Person.nearest_seed_hops (Finale reach), Intermediary.bridge_rank (coverage gap) and
Company.commercial_hops (conflict reach).

Importing the module adds the Act 1-4 rules. The Finale (warm-path points plus the cross-fund
conflict flag and the re-score) is opt-in: call ``enable_finale()`` (queries.finale_rescore does),
or set PE_DEAL_GRAPH_FINALE=1 before import. The Finale writes only its own finale_* names, so
Act-1 scores and tiers never change when it is on.

Verified idioms (research/pyrel_cheatsheet.md, relationalai 1.27.1, legacy compiler):
- defaults use a second rule with model.not_(), never ``X.q | default`` inside define;
- no aggs.string_join: ordered lists are joined by a recursive prefix rule;
- rank keys all ascend (numeric keys negated) and end with a unique key;
- dates are PyRel dates relative to AS_OF.
"""

from __future__ import annotations

import os

from relationalai.semantics import Date, Float, Integer, String
from relationalai.semantics.std import datetime as dt
from relationalai.semantics.std import floats, math, numbers, strings
from relationalai.semantics.std import aggregates as aggs
from relationalai.semantics.std.aggregates import asc, rank

from .core import (
    AS_OF, AS_OF_ISO, OUR_SEED_ROLE_TYPES, OUR_SPONSOR_NAME, model,
    AreaExposure, BuyingFund, Company, ConflictSubject, CoverageGap, DealFlowTransaction, DecisionMaker,
    EligibleTarget, Fund, FundFocus, Interaction, Intermediary, Knows, KnowsEvidence, NorthwindHolding,
    Organization, OurFund, OurSeed, OurSponsor, Ownership, Person, PipelineEntry, PortfolioExposure,
    ProFormaExposure, Region, Role, ScoreComponent, Sector, Signal, Sponsor, ThesisArea, Transaction,
    TransactionParty, bridge_cutoff, coverage_q1,
)

# ============================================================================================
# Constants (exported for queries.py, export.py and the explorer; nothing downstream retypes them)
# ============================================================================================
TIER_A_MIN = 70
TIER_B_MIN = 50
READINESS_CAP = 50
FIT_MAX = 30
ACCESS_MAX = 20          # A_CRM 10 + A_WARM_PATH 10 (Finale)
MAX_SCORE = 100
EBITDA_CORE_MIN = 10.0   # FIT_EBITDA full points inside [10, 30]
EBITDA_CORE_MAX = 30.0
AS_OF_YEAR = int(AS_OF_ISO[:4])
VINTAGE_CUT = AS_OF_YEAR - 8          # exit window: fund vintage <= 2018
EXIT_HOLD_YEARS = 5
ADVISOR_ROLES = ("sell_side_advisor", "buy_side_advisor", "debt_advisor")   # lenders are not advisors
CONFLICT_SUBJECT_STAGES = ("IOI prep",)
TENURE_OVERLAP_MIN_DAYS = 365          # "12 months or more" of shared tenure
EXPOSURE_MAX_HOPS = 2
WARM_PATH_MAX_HOPS = 2
WARM_PATH_POINTS = 10
CONFLICT_FLAG = "Conflict - cross-fund review"          # Finale flag text
EXPOSURE_CONFLICT_KIND = "CONFLICT - cross-fund review"  # PortfolioExposure.kind (ONTOLOGY.md 5.6)
UNSCORED_ACTIVITY_MIN_SIGNALS = 3

# Date windows, all relative to AS_OF (QUESTIONS.md 0.1). Windows are closed on both ends.
T_6M = dt.date.subtract(AS_OF, dt.months(6))
T_12M = dt.date.subtract(AS_OF, dt.months(12))
T_18M = dt.date.subtract(AS_OF, dt.months(18))
T_24M = dt.date.subtract(AS_OF, dt.months(24))
T_5Y = dt.date.subtract(AS_OF, dt.years(5))
T_10Y = dt.date.subtract(AS_OF, dt.years(10))
T_15Y = dt.date.subtract(AS_OF, dt.years(15))
T_20Y = dt.date.subtract(AS_OF, dt.years(20))
T_PLUS_18M = dt.date.add(AS_OF, dt.months(18))

# Score components in explanation order. label/group/max_points feed the explorer and the export.
SCORE_COMPONENTS = {
    "FIT_THESIS": {"label": "Thesis fit", "group": "Fit", "max_points": 15, "order": 1,
                   "doc": "15 points when the company is an eligible Fund IV target: its niche rolls up to a Fund IV "
                          "focus area, EBITDA is in the band, it is US-headquartered, private and not already ours."},
    "FIT_EBITDA": {"label": "EBITDA size", "group": "Fit", "max_points": 10, "order": 2,
                   "doc": "10 points for EBITDA of $10-30M (the sweet spot), 5 points at the edges of the $5-40M band."},
    "FIT_MARGIN": {"label": "Margin vs benchmark", "group": "Fit", "max_points": 5, "order": 3,
                   "doc": "5 points when the EBITDA margin meets the benchmark of the company's Fund IV focus area."},
    "R_CFO_FROM_PE": {"label": "CFO from a PE-backed company", "group": "Readiness", "max_points": 15, "order": 4,
                      "doc": "15 points when the current CFO joined in the last 18 months straight from a company that "
                             "was sponsor-owned while the CFO worked there (a three-way dated join: the CFO role, the "
                             "prior role ending within 12 months before, and the prior employer's ownership during it)."},
    "R_EXIT_WINDOW": {"label": "Sponsor exit window", "group": "Readiness", "max_points": 15, "order": 5,
                      "doc": "15 points when the current owner is a sponsor fund that has held the company 5+ years "
                             "and whose fund is 8+ years past vintage (vintage 2018 or earlier)."},
    "R_BANKER": {"label": "Banker engaged", "group": "Readiness", "max_points": 10, "order": 6,
                 "doc": "10 points when a bank or boutique was reported engaged in the last 6 months."},
    "R_DEBT": {"label": "Debt maturing", "group": "Readiness", "max_points": 10, "order": 7,
               "doc": "10 points when known debt matures within the next 18 months."},
    "R_SUCCESSION": {"label": "Founder succession", "group": "Readiness", "max_points": 10, "order": 8,
                     "doc": "10 points when a founder has been CEO for 15+ years and there is no President or COO "
                            "in place. Tenure, never age."},
    "R_NEW_DIRECTOR": {"label": "New independent director", "group": "Readiness", "max_points": 5, "order": 9,
                       "doc": "5 points when a board member joined in the last 12 months who holds no other role at "
                              "the company and no current role at its owning sponsor."},
    "A_CRM": {"label": "Positive CRM touch", "group": "Access", "max_points": 10, "order": 10,
              "doc": "10 points when we had a positive interaction in the last 24 months with the company or with "
                     "someone who currently works there."},
    "A_WARM_PATH": {"label": "Warm path to the CEO", "group": "Access", "max_points": WARM_PATH_POINTS, "order": 11,
                    "finale_only": True,
                    "doc": "Finale only: 10 points when the current CEO is two Knows hops or fewer from any Northwind "
                           "deal-team or operating-partner seed (graph distance feeding a rule)."},
}
_ACT1_CODES = [c for c, m in SCORE_COMPONENTS.items() if not m.get("finale_only")]
for _c, _m in SCORE_COMPONENTS.items():
    _m["rule_id"] = _c

# ============================================================================================
# Private helper relations (not part of the contract; documented for R11/R13 and the reviewers)
# ============================================================================================
Sector.is_thesis_exclusion = model.Relationship(f"{Sector} is excluded from the Fund IV thesis")
Interaction.touches_org = model.Relationship(f"{Interaction} touches {Organization:touched}")
TenureOverlap = model.Concept("TenureOverlap", identify_by={"role_a": Role, "role_b": Role})
TenureOverlap.days = model.Property(f"{TenureOverlap} lasts {Integer:days}")
TenureOverlap.start = model.Property(f"{TenureOverlap} starts {Date:start}")
TenureOverlap.end = model.Property(f"{TenureOverlap} ends {Date:end}")
TenureOverlap.end_label = model.Property(f"{TenureOverlap} ends as {String:end_label}")
TenureOverlap.kind_label = model.Property(f"{TenureOverlap} reads as {String:kind_label}")
ScoreCandidate = model.Concept("ScoreCandidate", identify_by={"company": Company, "code": String, "key": String})
ScoreCandidate.points = model.Property(f"{ScoreCandidate} is worth {Integer:points}")
ScoreCandidate.evidence = model.Property(f"{ScoreCandidate} is evidenced by {String:evidence}")
ScoreCandidate.sort_key = model.Property(f"{ScoreCandidate} sorts by {Integer:sort_key}")
ScoreComponent.code_order = model.Property(f"{ScoreComponent} has code order {Integer:code_order}")
ScoreComponent.position = model.Property(f"{ScoreComponent} is listed at {Integer:position}")
ScoreComponent.why_text = model.Property(f"{ScoreComponent} reads {String:why_text}")
Company.has_why_item = model.Relationship(f"{Company} has explanation item {Integer:why_item}")
Company.has_signal_type_item = model.Relationship(f"{Company} has signal type item {Integer:type_item}")
Company.has_tie_item = model.Relationship(f"{Company} has tie item {Integer:tie_item} with {Intermediary:tie_via}")
Company.why_upto = model.Property(f"{Company} is explained through item {Integer:why_upto_pos} by {String:why_upto}")
SignalTypeCount = model.Concept("SignalTypeCount", identify_by={"company": Company, "signal_type": String})
SignalTypeCount.n = model.Property(f"{SignalTypeCount} counts {Integer:n}")
SignalTypeCount.label = model.Property(f"{SignalTypeCount} reads {String:label}")
SignalTypeCount.position = model.Property(f"{SignalTypeCount} is listed at {Integer:position}")
Company.signal_types_upto = model.Property(
    f"{Company} lists signal types through {Integer:types_pos} as {String:signal_types_upto}")
Company.signals_12m = model.Property(f"{Company} has {Integer:signals_12m} signals in 12 months")
Company.why_not_activity = model.Property(f"{Company} shows unscored activity {String:why_not_activity}")
Company.why_not_exit = model.Property(f"{Company} misses the exit window {String:why_not_exit}")
IntermediaryTie = model.Concept("IntermediaryTie", identify_by={"company": Company, "intermediary": Intermediary,
                                                                "key": String})
IntermediaryTie.days_ago = model.Property(f"{IntermediaryTie} is {Integer:days_ago} days old")
IntermediaryTie.label = model.Property(f"{IntermediaryTie} reads {String:label}")
IntermediaryTie.position = model.Property(f"{IntermediaryTie} is listed at {Integer:position}")
Company.intermediary_ties_upto = model.Property(
    f"{Company} ties to {Intermediary:via} through {Integer:ties_pos} as {String:intermediary_ties_upto}")
Intermediary.touch_position = model.Property(f"{Intermediary} sits at {Integer:touch_position} by touchpoints")
Company.link_phrase = model.Property(f"{Company:company_a} relates to {Company:company_b} as {String:link_phrase}")
ExposureRoute = model.Concept("ExposureRoute", identify_by={"subject": Company, "company": Company,
                                                            "middle": Company})
ExposureRoute.text = model.Property(f"{ExposureRoute} reads {String:text}")
Company.warm_path_text = model.Property(f"{Company} has warm-path note {String:warm_path_text}")
Company.conflict_text = model.Property(f"{Company} has conflict note {String:conflict_text}")
ConflictLink = model.Concept("ConflictLink", identify_by={"company": Company, "held": Company})
ConflictLink.text = model.Property(f"{ConflictLink} reads {String:text}")
Organization.is_former_holding = model.Relationship(f"{Organization} is a former Northwind portfolio company")
Organization.evidence_name = model.Property(f"{Organization} is cited in evidence as {String:evidence_name}")
Person.northwind_label = model.Property(f"{Person} is cited in evidence as {String:northwind_label}")
FORMER_HOLDING_LABEL = "a former Northwind portfolio company"
NORTHWIND_ROLE_LABELS = (("Operating Partner", "a Northwind operating partner"),
                         ("Deal Team", "a Northwind deal-team member"))

HELPERS = (
    "Sector.is_thesis_exclusion", "Interaction.touches_org", "TenureOverlap", "ScoreCandidate",
    "ScoreComponent.code_order", "ScoreComponent.position", "ScoreComponent.why_text", "Company.why_upto",
    "SignalTypeCount", "Company.signal_types_upto", "Company.signals_12m", "Company.why_not_activity",
    "Company.why_not_exit", "IntermediaryTie", "Company.intermediary_ties_upto", "Intermediary.touch_position",
    "Company.link_phrase", "Company.has_why_item", "Company.has_signal_type_item", "Company.has_tie_item", "ExposureRoute",
    "Company.warm_path_text", "Company.conflict_text", "ConflictLink", "Organization.is_former_holding",
    "Organization.evidence_name", "Person.northwind_label",
)

pd_ = dt.date.period_days   # Integer days, end - start


def _s(x):
    """String form of a value inside a rule (dates print ISO, floats unpadded)."""
    return strings.string(x)


def _money(x):
    return strings.concat("$", strings.string(math.round(x, 1)), "M")


def _words(x):
    """snake_case source code value -> plain words (sell_side_advisor -> sell-side advisor)."""
    return strings.replace(strings.replace(x, "_side_", "-side "), "_", " ")


def _years(days, digits):
    return strings.string(math.round(floats.float(days) / 365.25, digits))


def _recency(d):
    """QUESTIONS.md Q-PATH recency(d): 1.0 within 10 years of AS_OF, 0.7 within 20 years, else 0.4."""
    return [((d >= T_10Y,), 1.0), ((d < T_10Y, d >= T_20Y), 0.7), ((d < T_20Y,), 0.4)]


def _overlap_days(s1, e1, s2, e2):
    """min(e1, e2) - max(s1, s2) in days, as the minimum of the four end-minus-start differences."""
    return math.minimum(math.minimum(pd_(s1, e1), pd_(s2, e2)), math.minimum(pd_(s2, e1), pd_(s1, e2)))


# ============================================================================================
# 1. Hierarchies and "us"
# ============================================================================================
def sector_closure():
    """Sector hierarchy closure. A niche is within itself, its subsector and its sector, at any depth.

    This recursive rule lets the Fund IV thesis name focus nodes at mixed levels (a whole sector,
    a subsector, or a single excluded niche) and still classify every company on its niche.
    Region closure works the same way: a state is within its census region and the country.
    Used by Q-SCORE (thesis fit, US gate), Q-FLOW (deal-flow scope) and Q-CONFLICT (thesis areas)."""
    s, a, b = Sector.ref(), Sector.ref(), Sector.ref()
    model.define(Sector.ancestor_or_self(Sector))
    model.where(s.ancestor_or_self(a), a.parent(b)).define(s.ancestor_or_self(b))
    r, ra, rb = Region.ref(), Region.ref(), Region.ref()
    model.define(Region.ancestor_or_self(Region))
    model.where(r.ancestor_or_self(ra), ra.parent(rb)).define(r.ancestor_or_self(rb))


def who_we_are():
    """Who "we" are. Northwind Equity Partners is our sponsor; its funds are ours; the buying fund is
    our fund with the latest vintage (Fund IV). Our seeds are the people who can make an introduction
    today: current Deal Team members and Operating Partners at Northwind (former partners are not).
    A Northwind holding is a company one of our funds owns today; sold companies do not count.
    Thesis areas are the Fund IV include nodes. Each company's current majority owner fund and
    current CEO are also derived here."""
    model.where(Sponsor.name == OUR_SPONSOR_NAME).define(OurSponsor(Sponsor))
    sp = Sponsor.ref()
    model.where(Fund.sponsor(sp), OurSponsor(sp)).define(OurFund(Fund))
    # Latest vintage over our sponsor's funds, read from Fund.sponsor (not from OurFund: BuyingFund is a
    # subtype of OurFund, so aggregating over OurFund would be recursion through an aggregate).
    f2, sp2, sp3 = Fund.ref(), Sponsor.ref(), Sponsor.ref()
    latest = aggs.max(f2.vintage_year).where(f2.sponsor(sp2), sp2.name == OUR_SPONSOR_NAME)
    model.where(Fund.sponsor(sp3), sp3.name == OUR_SPONSOR_NAME, Fund.vintage_year == latest).define(BuyingFund(Fund))
    r, org = Role.ref(), Organization.ref()
    model.where(r.person(Person), r.organization(org), OurSponsor(org), r.is_current(),
                r.role_type.in_(list(OUR_SEED_ROLE_TYPES))).define(OurSeed(Person))
    f3 = Fund.ref()
    model.where(Ownership.is_current(), Ownership.fund(f3), OurFund(f3)).define(NorthwindHolding(Ownership))
    bf = Fund.ref()
    model.where(FundFocus.fund(bf), BuyingFund(bf), FundFocus.mode == "include",
                FundFocus.sector(Sector)).define(ThesisArea(Sector))
    bf2, ff2 = Fund.ref(), FundFocus.ref()
    model.where(ff2.fund(bf2), BuyingFund(bf2), ff2.mode == "exclude",
                ff2.sector(Sector)).define(Sector.is_thesis_exclusion())
    ow, fo = Ownership.ref(), Fund.ref()
    model.where(ow.company(Company), ow.is_current(), ow.stake_type == "majority",
                ow.fund(fo)).define(Company.current_owner_fund(fo))
    rc, pc = Role.ref(), Person.ref()
    model.where(rc.organization(Company), rc.role_type == "CEO", rc.is_current(),
                rc.person(pc)).define(Company.current_ceo(pc))


def evidence_names():
    """How evidence text names organizations and our own people. A company that a Northwind fund
    owned in the past but not today is cited as "a former Northwind portfolio company"; every other
    organization by its name. A person with a current Northwind role is cited by that role ("a
    Northwind operating partner" or "a Northwind deal-team member") when they logged a CRM touch:
    the score is about the target, not about which of us made the call."""
    c, o, f, nh = Company.ref(), Ownership.ref(), Fund.ref(), Ownership.ref()
    model.where(o.company(c), o.fund(f), OurFund(f), o.start_date <= AS_OF, model.not_(o.is_current()),
                model.not_(nh.company(c), NorthwindHolding(nh))).define(c.is_former_holding())
    model.where(Organization.is_former_holding()).define(Organization.evidence_name(FORMER_HOLDING_LABEL))
    model.where(Organization.name, model.not_(Organization.is_former_holding())).define(
        Organization.evidence_name(Organization.name))
    r, sp, r2, sp2 = Role.ref(), Organization.ref(), Role.ref(), Organization.ref()
    (op_type, op_label), (dt_type, dt_label) = NORTHWIND_ROLE_LABELS
    model.where(r.person(Person), r.organization(sp), OurSponsor(sp), r.is_current(), r.role_type == op_type).define(
        Person.northwind_label(op_label))
    model.where(r.person(Person), r.organization(sp), OurSponsor(sp), r.is_current(), r.role_type == dt_type,
                model.not_(r2.person(Person), r2.organization(sp2), OurSponsor(sp2), r2.is_current(),
                           r2.role_type == op_type)).define(Person.northwind_label(dt_label))


# ============================================================================================
# 2. Thesis fit and eligibility (Q-SCORE)
# ============================================================================================
def thesis_fit():
    """Thesis fit. A company is in the Fund IV thesis when its niche sits under a Fund IV include
    node (at any level) and under no Fund IV exclude node: Skilled Nursing Facilities is excluded
    inside Healthcare Services, and a veterinary drug maker never reaches a focus node at all.
    Its thesis area is the deepest include node above the niche; the area's margin benchmark is
    the bar for the margin point. A company is US-based when its HQ region rolls up to the
    fund's geography. Eligible targets are in thesis, inside the fund's EBITDA band, US, private
    and not already owned by a Northwind fund; only they are scored. Every other company gets the
    first reason it fails, in the order thesis, band, US, public, ours."""
    n, inc, exc, a2 = Sector.ref(), Sector.ref(), Sector.ref(), Sector.ref()
    model.where(Company.sector(n), n.ancestor_or_self(inc), ThesisArea(inc),
                model.not_(n.ancestor_or_self(exc), exc.is_thesis_exclusion())).define(Company.in_thesis())
    model.where(Company.in_thesis(), Company.sector(n), n.ancestor_or_self(inc), ThesisArea(inc),
                model.not_(n.ancestor_or_self(a2), ThesisArea(a2), a2 != inc, a2.ancestor_or_self(inc))
                ).define(Company.thesis_area(inc))
    a, ff, bf = Sector.ref(), FundFocus.ref(), Fund.ref()
    model.where(Company.thesis_area(a), ff.sector(a), ff.fund(bf), BuyingFund(bf), ff.mode == "include"
                ).define(Company.margin_benchmark_pct(ff.margin_benchmark_pct))
    model.where(Company.revenue_musd > 0.0).define(
        Company.ebitda_margin_pct(100.0 * Company.ebitda_musd / Company.revenue_musd))
    rg, us, bfu = Region.ref(), Region.ref(), Fund.ref()
    model.where(Company.hq_region(rg), rg.ancestor_or_self(us), BuyingFund(bfu), us.id == bfu.geography
                ).define(Company.is_us())

    b, nh = Fund.ref(), Ownership.ref()
    model.where(Company.in_thesis(), BuyingFund(b), Company.ebitda_musd >= b.ebitda_min_musd,
                Company.ebitda_musd <= b.ebitda_max_musd, Company.is_us(), model.not_(Company.is_public()),
                model.not_(nh.company(Company), NorthwindHolding(nh))).define(EligibleTarget(Company))

    # Why not eligible: first failing condition (each branch excludes the earlier ones).
    x = Sector.ref()
    model.where(Company.sector(n), n.ancestor_or_self(x), x.is_thesis_exclusion(), x == n).define(
        Company.ineligible_reason(strings.concat("niche ", n.name, " is excluded from the Fund IV thesis")))
    model.where(Company.sector(n), n.ancestor_or_self(x), x.is_thesis_exclusion(), x != n).define(
        Company.ineligible_reason(strings.concat("niche ", n.name, " is excluded from the Fund IV thesis (under ",
                                                 x.name, ")")))
    x2, i2 = Sector.ref(), Sector.ref()
    model.where(Company.sector(n), model.not_(n.ancestor_or_self(i2), ThesisArea(i2)),
                model.not_(n.ancestor_or_self(x2), x2.is_thesis_exclusion())).define(
        Company.ineligible_reason(strings.concat("niche ", n.name, " is outside the Fund IV thesis tree")))
    model.where(Company.in_thesis(), BuyingFund(b), Company.ebitda_musd > b.ebitda_max_musd).define(
        Company.ineligible_reason(strings.concat("EBITDA ", _money(Company.ebitda_musd), " is above the ",
                                                 _money(b.ebitda_max_musd), " band")))
    model.where(Company.in_thesis(), BuyingFund(b), Company.ebitda_musd < b.ebitda_min_musd).define(
        Company.ineligible_reason(strings.concat("EBITDA ", _money(Company.ebitda_musd), " is below the ",
                                                 _money(b.ebitda_min_musd), " band")))
    model.where(Company.in_thesis(), model.not_(Company.ebitda_musd)).define(
        Company.ineligible_reason("EBITDA is not reported"))
    in_band = (Company.in_thesis(), BuyingFund(b), Company.ebitda_musd >= b.ebitda_min_musd,
               Company.ebitda_musd <= b.ebitda_max_musd)
    hq = Region.ref()
    model.where(*in_band, model.not_(Company.is_us()), Company.hq_region(hq)).define(
        Company.ineligible_reason(strings.concat("headquartered in ", hq.name, ", outside the US")))
    model.where(*in_band, Company.is_us(), Company.is_public()).define(
        Company.ineligible_reason("publicly listed"))
    hf = Fund.ref()
    model.where(*in_band, Company.is_us(), model.not_(Company.is_public()), nh.company(Company),
                NorthwindHolding(nh), nh.fund(hf)).define(
        Company.ineligible_reason(strings.concat("already owned by ", hf.name, " since ", _s(nh.start_date))))


def known_to_crm():
    """Known to our CRM. A company is known when it has a pipeline row, or when any CRM interaction
    touched the company itself or a person who currently works there. "Not in CRM" is the
    opposite: Tier A names with no coverage, meaning no pipeline row and no CRM touch on the
    company or its people."""
    r, p, org = Role.ref(), Person.ref(), Organization.ref()
    model.where(Interaction.counterparty_org(org)).define(Interaction.touches_org(org))
    model.where(Interaction.counterparty_person(p), r.person(p), r.organization(org), r.is_current()
                ).define(Interaction.touches_org(org))
    model.where(PipelineEntry.company(Company)).define(Company.in_crm())
    ix = Interaction.ref()
    model.where(ix.touches_org(Company)).define(Company.in_crm())


# ============================================================================================
# 3. Score components, score, tier, explanation (Q-SCORE)
# ============================================================================================
def _candidate(conds, code, key, points, evidence, sort_key, company=Company):
    model.where(*conds).define(
        k := ScoreCandidate.new(company=company, code=code, key=key), k.points(points), k.evidence(evidence),
        k.sort_key(sort_key))


def fit_components():
    """Fit components (max 30). FIT_THESIS 15 for every eligible target; FIT_EBITDA 10 for EBITDA
    of $10-30M, 5 at the edges of the band; FIT_MARGIN 5 when the EBITDA margin meets the focus
    area's benchmark. Each awarded point carries its evidence in plain words."""
    n, a = Sector.ref(), Sector.ref()
    _candidate((EligibleTarget(Company), Company.sector(n), Company.thesis_area(a)), "FIT_THESIS", "thesis", 15,
               strings.concat("niche ", n.name, " under Fund IV focus ", a.name), 0)
    e = Company.ebitda_musd
    _candidate((EligibleTarget(Company), e >= EBITDA_CORE_MIN, e <= EBITDA_CORE_MAX), "FIT_EBITDA", "core", 10,
               strings.concat("EBITDA ", _money(e), " in the $10-30M sweet spot"), 0)
    for cond in (e < EBITDA_CORE_MIN, e > EBITDA_CORE_MAX):
        _candidate((EligibleTarget(Company), cond), "FIT_EBITDA", "edge", 5,
                   strings.concat("EBITDA ", _money(e), " at the edge of the $5-40M band"), 0)
    a2 = Sector.ref()
    _candidate((EligibleTarget(Company), Company.thesis_area(a2),
                Company.ebitda_margin_pct >= Company.margin_benchmark_pct), "FIT_MARGIN", "margin", 5,
               strings.concat("margin ", _s(math.round(Company.ebitda_margin_pct, 1)), "% vs ",
                              _s(Company.margin_benchmark_pct), "% benchmark for ", a2.name), 0)


def readiness_components():
    """Readiness components, dated against AS_OF 2026-10-01 (sum capped at 50).
    R_CFO_FROM_PE 15: a CFO hired in the last 18 months whose previous job, ending within 12 months
    before, was at a company a sponsor fund owned during that job (the employer was PE-backed while
    the person was there; a founder-owned prior employer does not count).
    R_EXIT_WINDOW 15: owned by a sponsor fund for 5+ years and the fund is vintage 2018 or older.
    R_BANKER 10: a banker engaged in the last 6 months. R_DEBT 10: debt maturing in the next 18
    months. R_SUCCESSION 10: founder CEO for 15+ years with no President or COO (tenure, never
    age). R_NEW_DIRECTOR 5: a board member added in the last 12 months who is not an executive
    and not from the owning sponsor."""
    # R_CFO_FROM_PE: three-way temporal join.
    cr, pr, ow = Role.ref(), Role.ref(), Ownership.ref()
    p, pc, f = Person.ref(), Company.ref(), Fund.ref()
    _candidate((cr.organization(Company), cr.role_type == "CFO", cr.is_current(), cr.person(p),
                cr.start_date >= T_18M, cr.start_date <= AS_OF,
                pr.person(p), pr.organization(pc), pc != Company,
                pr.effective_end_date >= dt.date.subtract(cr.start_date, dt.months(12)),
                pr.effective_end_date <= cr.start_date,
                ow.company(pc), ow.fund(f),
                _overlap_days(pr.start_date, pr.effective_end_date, ow.start_date, ow.effective_end_date) >= 1),
               "R_CFO_FROM_PE", strings.concat(cr.id, "|", pr.id, "|", ow.id), 15,
               strings.concat("CFO ", p.name, " hired ", _s(cr.start_date), " from ", pc.evidence_name, ", owned by ",
                              f.name, " while the CFO worked there (", _s(pr.start_date), " to ",
                              _s(pr.effective_end_date), ")"),
               0 - pd_(ow.start_date, AS_OF))   # several owners overlapping: cite the earliest
    # R_EXIT_WINDOW: ownership joined to fund vintage.
    o2, f2 = Ownership.ref(), Fund.ref()
    _candidate((o2.company(Company), o2.is_current(), o2.fund(f2), o2.start_date <= T_5Y,
                f2.vintage_year <= VINTAGE_CUT),
               "R_EXIT_WINDOW", o2.id, 15,
               strings.concat(f2.name, ", vintage ", _s(f2.vintage_year), ", held since ", _s(o2.start_date),
                              " = ", _years(pd_(o2.start_date, AS_OF), 1), " years"),
               0 - pd_(o2.start_date, AS_OF))
    # R_BANKER: newest engagement in the last 6 months.
    sg, im = Signal.ref(), Intermediary.ref()
    banker = (sg.company(Company), sg.signal_type == "BANKER_ENGAGED", sg.signal_date >= T_6M,
              sg.signal_date <= AS_OF)
    _candidate((*banker, sg.intermediary(im)), "R_BANKER", sg.id, 10,
               strings.concat("banker engaged ", _s(sg.signal_date), " (", im.name, ")"), pd_(sg.signal_date, AS_OF))
    _candidate((*banker, model.not_(sg.intermediary)), "R_BANKER", sg.id, 10,
               strings.concat("banker engaged ", _s(sg.signal_date)), pd_(sg.signal_date, AS_OF))
    # R_DEBT: earliest maturity inside (T, T+18m], learned on or before T.
    sd = Signal.ref()
    _candidate((sd.company(Company), sd.signal_type == "DEBT_MATURITY", sd.signal_date <= AS_OF,
                sd.event_date > AS_OF, sd.event_date <= T_PLUS_18M),
               "R_DEBT", sd.id, 10,
               strings.concat("debt matures ", _s(sd.event_date), " (flagged ", _s(sd.signal_date), ")"),
               pd_(AS_OF, sd.event_date))
    # R_SUCCESSION: long-tenured founder CEO, no President or COO in place.
    ce, pce, r2 = Role.ref(), Person.ref(), Role.ref()
    _candidate((ce.organization(Company), ce.role_type == "CEO", ce.is_current(), ce.is_founder(),
                ce.start_date <= T_15Y, ce.person(pce),
                model.not_(r2.organization(Company), r2.is_current(), r2.role_type.in_(["President", "COO"]))),
               "R_SUCCESSION", ce.id, 10,
               strings.concat("founder CEO ", pce.name, " since ", _s(ce.start_date), " (",
                              _years(pd_(ce.start_date, AS_OF), 2), " years), no President or COO"),
               0 - pd_(ce.start_date, AS_OF))
    # R_NEW_DIRECTOR: a new board seat held by someone independent of management and the owner.
    bd, pb, r3, r4, o3, f3, sp3 = Role.ref(), Person.ref(), Role.ref(), Role.ref(), Ownership.ref(), Fund.ref(), \
        Sponsor.ref()
    _candidate((bd.organization(Company), bd.role_type == "Board", bd.start_date >= T_12M, bd.start_date <= AS_OF,
                bd.person(pb),
                model.not_(r3.organization(Company), r3.person(pb), r3.is_current(), r3.role_type != "Board"),
                model.not_(o3.company(Company), o3.is_current(), o3.fund(f3), f3.sponsor(sp3), r4.person(pb),
                           r4.organization(sp3), r4.is_current())),
               "R_NEW_DIRECTOR", bd.id, 5,
               strings.concat("new board member ", pb.name, " since ", _s(bd.start_date)),
               0 - pd_(bd.start_date, AS_OF))


def access_components():
    """Access component for Act 1 (max 10). A_CRM 10: at least one positive CRM interaction in the
    last 24 months with the company itself or with a person who currently holds a role there.
    A neutral touch, or one older than 24 months, is a visible near miss, not a point."""
    ix, op, nl = Interaction.ref(), Person.ref(), String.ref()
    win = (ix.sentiment == "positive", ix.interaction_date >= T_24M, ix.interaction_date <= AS_OF, ix.our_person(op))
    # Our own people are cited by role (evidence_names); anyone without a current Northwind role, by name.
    for by_conds, by_text in (((op.northwind_label(nl),), nl), ((model.not_(op.northwind_label),), op.name)):
        _candidate((*win, *by_conds, ix.counterparty_org(Company)), "A_CRM", strings.concat(ix.id, ":org"), 10,
                   strings.concat("positive ", ix.channel, " with the company ", _s(ix.interaction_date), " by ",
                                  by_text), pd_(ix.interaction_date, AS_OF))
        q, r = Person.ref(), Role.ref()
        _candidate((*win, *by_conds, ix.counterparty_person(q), r.person(q), r.organization(Company), r.is_current()),
                   "A_CRM", strings.concat(ix.id, ":person"), 10,
                   strings.concat("positive ", ix.channel, " with ", q.name, " ", _s(ix.interaction_date), " by ",
                                  by_text), pd_(ix.interaction_date, AS_OF))


def composite_score():
    """Composite score. Score = Fit (max 30) + Readiness (sum of readiness points, capped at 50) +
    Access (Act 1: A_CRM only). Tier A at 70 or more, B at 50-69, C below 50. Rank: score, then
    readiness, then fit (all high first), then name. The explanation lists every awarded component
    with its points and evidence, in a fixed order, so every point is traceable."""
    k = ScoreCandidate.ref()
    model.where(EligibleTarget(Company), k.company(Company),
                rank(asc(k.sort_key), asc(k.key)).per(Company, k.code) == 1).define(
        sc := ScoreComponent.new(company=Company, code=k.code), sc.points(k.points), sc.evidence(k.evidence))
    for code in _ACT1_CODES:
        m = SCORE_COMPONENTS[code]
        model.where(ScoreComponent.code == code).define(
            ScoreComponent.pillar(m["group"]), ScoreComponent.code_order(m["order"]),
            ScoreComponent.why_text(strings.concat(m["label"], " +", _s(ScoreComponent.points), " (",
                                                   ScoreComponent.evidence, ")")))
    sums = {}
    for pillar in ("Fit", "Readiness", "Access"):
        sc_ = ScoreComponent.ref()
        sums[pillar] = aggs.sum(sc_.points).per(Company).where(sc_.company(Company), sc_.pillar == pillar) | 0
    model.where(EligibleTarget(Company)).define(
        Company.fit_points(sums["Fit"]),
        Company.readiness_points(math.minimum(READINESS_CAP, sums["Readiness"])),
        Company.access_points(sums["Access"]))
    model.where(EligibleTarget(Company)).define(
        Company.score(Company.fit_points + Company.readiness_points + Company.access_points))
    model.where(Company.score >= TIER_A_MIN).define(Company.tier("A"))
    model.where(Company.score >= TIER_B_MIN, Company.score < TIER_A_MIN).define(Company.tier("B"))
    model.where(Company.score < TIER_B_MIN).define(Company.tier("C"))
    model.where(EligibleTarget(Company)).define(Company.score_rank(
        rank(asc(0 - Company.score), asc(0 - Company.readiness_points), asc(0 - Company.fit_points),
             asc(Company.name), asc(Company.id))))
    # Explanation: recursive ordered join of the awarded components (no string_join on legacy).
    s1, s2, s3 = ScoreComponent.ref(), ScoreComponent.ref(), ScoreComponent.ref()
    model.where(s1.company(Company)).define(s1.position(rank(asc(s1.code_order)).per(Company)))
    model.where(s1.company(Company), s1.position == 1).define(Company.why_upto(1, s1.why_text))
    i, t = Integer.ref(), String.ref()
    model.where(Company.why_upto(i, t), s2.company(Company), s2.position == i + 1).define(
        Company.why_upto(s2.position, strings.concat(t, "; ", s2.why_text)))
    # the last item is the one with no successor
    model.where(s3.company(Company)).define(Company.has_why_item(s3.position))
    model.where(EligibleTarget(Company), Company.why_upto(i, t),
                model.not_(Company.has_why_item(i + 1))).define(Company.why(t))


def why_not_templates():
    """Why-not explanations for scored companies. (a) Unscored activity: three or more signals in the
    last 12 months but none of a scored readiness type, listed by type with counts. (b) Exit window
    not met: sponsor-owned, but not long enough or the fund is too young. A busy news feed is not
    readiness, and a recent buyout is not an exit."""
    # The type is grounded by an actual signal row in the outer where (an aggregate alone does not ground a
    # String group key), then counted per company and type.
    sg0, sg, ty = Signal.ref(), Signal.ref(), String.ref()
    cnt = aggs.count(sg).per(Company, ty).where(sg.company(Company), sg.signal_type(ty), sg.signal_date >= T_12M,
                                                sg.signal_date <= AS_OF)
    model.where(EligibleTarget(Company), sg0.company(Company), sg0.signal_type(ty), sg0.signal_date >= T_12M,
                sg0.signal_date <= AS_OF).define(
        x := SignalTypeCount.new(company=Company, signal_type=ty), x.n(cnt))
    model.where(SignalTypeCount.n == 1).define(SignalTypeCount.label(SignalTypeCount.signal_type))
    model.where(SignalTypeCount.n > 1).define(SignalTypeCount.label(
        strings.concat(SignalTypeCount.signal_type, " x", _s(SignalTypeCount.n))))
    a, b, c = SignalTypeCount.ref(), SignalTypeCount.ref(), SignalTypeCount.ref()
    model.where(a.company(Company)).define(a.position(rank(asc(a.signal_type)).per(Company)))
    model.where(a.company(Company), a.position == 1).define(Company.signal_types_upto(1, a.label))
    i, t = Integer.ref(), String.ref()
    model.where(Company.signal_types_upto(i, t), b.company(Company), b.position == i + 1).define(
        Company.signal_types_upto(b.position, strings.concat(t, ", ", b.label)))
    model.where(EligibleTarget(Company)).define(Company.signals_12m(
        aggs.sum(c.n).per(Company).where(c.company(Company)) | 0))
    d = SignalTypeCount.ref()
    model.where(d.company(Company)).define(Company.has_signal_type_item(d.position))
    k1, k2 = ScoreComponent.ref(), ScoreComponent.ref()
    model.where(EligibleTarget(Company), Company.signals_12m >= UNSCORED_ACTIVITY_MIN_SIGNALS,
                Company.signal_types_upto(i, t), model.not_(Company.has_signal_type_item(i + 1)),
                model.not_(k1.company(Company), k1.code == "R_BANKER"),
                model.not_(k2.company(Company), k2.code == "R_DEBT")).define(
        Company.why_not_activity(strings.concat(_s(Company.signals_12m),
                                                " signals in the last 12 months, none a scored readiness type (",
                                                t, ")")))
    ow, k3 = Ownership.ref(), ScoreComponent.ref()
    model.where(EligibleTarget(Company), ow.company(Company), ow.is_current(), ow.stake_type == "majority",
                model.not_(k3.company(Company), k3.code == "R_EXIT_WINDOW")).define(
        Company.why_not_exit(strings.concat("sponsor-owned since ", _s(ow.start_date), " (",
                                            _years(pd_(ow.start_date, AS_OF), 1), " years)")))
    exit_rule = f"exit window needs {EXIT_HOLD_YEARS}+ years held and fund vintage <= {VINTAGE_CUT}"
    model.where(Company.why_not_activity, Company.why_not_exit).define(
        Company.why_not(strings.concat(Company.why_not_activity, "; ", Company.why_not_exit)))
    model.where(Company.why_not_activity, model.not_(Company.why_not_exit)).define(
        Company.why_not(Company.why_not_activity))
    model.where(Company.why_not_exit, model.not_(Company.why_not_activity)).define(
        Company.why_not(strings.concat(Company.why_not_exit, "; ", exit_rule)))


# ============================================================================================
# 4. Who knows whom (Q-PATH)
# ============================================================================================
def knows_tenure_overlap():
    """K1 tenure overlap. Two people know each other when they held roles at the same organization
    at the same time for 12 months or more (an open role runs to AS_OF). Strength rises with the
    length of the overlap (0.4 + 0.15 per year, capped at 1.0) and fades with age: full weight if
    the overlap ended within 10 years, 0.7 within 20 years, 0.4 before that. It reads "board
    co-service" when both roles are board seats, otherwise "tenure overlap". A shared employer
    without overlapping dates is rejected: two people who worked at the same company years apart
    (for example, one left 613 days before the other arrived) are not a warm intro, which is the
    false lead a shared-employer join reports."""
    ra, rb, pa, pb, org = Role.ref(), Role.ref(), Person.ref(), Person.ref(), Organization.ref()
    ov = _overlap_days(ra.start_date, ra.effective_end_date, rb.start_date, rb.effective_end_date)
    model.where(ra.organization(org), rb.organization(org), ra.person(pa), rb.person(pb), pa.id < pb.id,
                d := ov, d >= TENURE_OVERLAP_MIN_DAYS).define(
        o := TenureOverlap.new(role_a=ra, role_b=rb), o.days(d))
    o = TenureOverlap.ref()
    model.where(o.role_a(ra), o.role_b(rb), ra.start_date >= rb.start_date).define(o.start(ra.start_date))
    model.where(o.role_a(ra), o.role_b(rb), ra.start_date < rb.start_date).define(o.start(rb.start_date))
    model.where(o.role_a(ra), o.role_b(rb), ra.effective_end_date <= rb.effective_end_date).define(
        o.end(ra.effective_end_date))
    model.where(o.role_a(ra), o.role_b(rb), ra.effective_end_date > rb.effective_end_date).define(
        o.end(rb.effective_end_date))
    model.where(o.role_a(ra), o.role_b(rb), model.not_(ra.end_date), model.not_(rb.end_date)).define(
        o.end_label("present"))
    model.where(o.role_a(ra), o.role_b(rb), ra.end_date).define(o.end_label(_s(o.end)))
    model.where(o.role_a(ra), o.role_b(rb), model.not_(ra.end_date), rb.end_date).define(o.end_label(_s(o.end)))
    model.where(o.role_a(ra), o.role_b(rb), ra.role_type == "Board", rb.role_type == "Board").define(
        o.kind_label("board co-service"))
    model.where(o.role_a(ra), o.role_b(rb), model.not_(ra.role_type == "Board", rb.role_type == "Board")).define(
        o.kind_label("tenure overlap"))
    for conds, factor in _recency(o.end):
        model.where(o.role_a(ra), o.role_b(rb), ra.person(pa), rb.person(pb), ra.organization(org), *conds).define(
            e := KnowsEvidence.new(p1=pa, p2=pb, kind="K1", key=strings.concat(ra.id, "-", rb.id)),
            e.strength(factor * math.minimum(1.0, 0.4 + 0.15 * floats.float(o.days) / 365.25)),
            e.organization(org), e.from_date(o.start), e.to_date(o.end),
            e.label(strings.concat(o.kind_label, " at ", org.evidence_name, ", ", _s(o.start), " to ", o.end_label, ", ",
                                   _years(o.days, 2), " years")))


def knows_deal_coparticipation():
    """K2 deal co-participation. Two people know each other when both led a side of the same deal,
    or when one led a side and the other was the target's CEO or CFO on the closing date (the banker
    who ran a recap knows the founder who sold). Strength 0.7, faded by the age of the deal like K1."""
    tp1, tp2, t, tgt = TransactionParty.ref(), TransactionParty.ref(), Transaction.ref(), Company.ref()
    pa, pb = Person.ref(), Person.ref()
    for conds, factor in _recency(t.close_date):
        model.where(tp1.transaction(t), tp2.transaction(t), tp1.lead_person(pa), tp2.lead_person(pb),
                    pa.id < pb.id, t.target(tgt), *conds).define(
            e := KnowsEvidence.new(p1=pa, p2=pb, kind="K2", key=t.id), e.strength(0.7 * factor), e.transaction(t),
            e.from_date(t.close_date), e.to_date(t.close_date),
            e.label(strings.concat("both led sides of the ", _words(t.structure), " of ", tgt.name, " closed ",
                                   _s(t.close_date))))
    tp, xr, tpx, lp, ex = TransactionParty.ref(), Role.ref(), TransactionParty.ref(), Person.ref(), Person.ref()
    base = (tp.transaction(t), tp.lead_person(lp), t.target(tgt), xr.organization(tgt), xr.person(ex),
            xr.role_type.in_(["CEO", "CFO"]), xr.start_date <= t.close_date, xr.effective_end_date >= t.close_date,
            ex != lp, model.not_(tpx.transaction(t), tpx.lead_person(ex)))
    label = strings.concat("lead ", _words(tp.party_role), " on the ", tgt.name, " ", _words(t.structure),
                           " closed ", _s(t.close_date), " while ", ex.name, " was ", xr.role_type)
    for first, second in ((lp, ex), (ex, lp)):
        for conds, factor in _recency(t.close_date):
            model.where(*base, first.id < second.id, *conds).define(
                e := KnowsEvidence.new(p1=first, p2=second, kind="K2", key=strings.concat(t.id, ":", tp.id, ":", xr.id)),
                e.strength(0.7 * factor), e.transaction(t), e.from_date(t.close_date), e.to_date(t.close_date),
                e.label(label))


def knows_positive_crm():
    """K3 positive CRM. A Northwind seed knows a person after positive person-level interactions
    (meetings, calls, emails or conferences) in the last 24 months: 0.6 for one, 0.8 for two, 1.0 for
    three or more. Org-level touches (a meeting with a firm, no named person) create no personal tie.
    Each seed's log is its own piece of evidence, so two seeds who logged each other never collide."""
    s, q = Person.ref(), Person.ref()

    def window(ix):
        return (ix.our_person(s), ix.counterparty_person(q), ix.sentiment == "positive", ix.interaction_date >= T_24M,
                ix.interaction_date <= AS_OF)

    i0, i1, i2, i3 = Interaction.ref(), Interaction.ref(), Interaction.ref(), Interaction.ref()
    cnt = aggs.count(i1).per(s, q).where(*window(i1))
    first = aggs.min(i2.interaction_date).per(s, q).where(*window(i2))
    last = aggs.max(i3.interaction_date).per(s, q).where(*window(i3))
    for lo, hi in ((s, q), (q, s)):
        for cond, strength in ((lambda n: n == 1, 0.6), (lambda n: n == 2, 0.8), (lambda n: n >= 3, 1.0)):
            model.where(OurSeed(s), *window(i0), n := cnt, f := first, la := last, cond(n), lo.id < hi.id).define(
                e := KnowsEvidence.new(p1=lo, p2=hi, kind="K3", key=strings.concat("crm:", s.id)),
                e.strength(strength), e.from_date(f), e.to_date(la),
                e.label(strings.concat(_s(n), " positive interactions ", _s(f), " to ", _s(la))))


def knows_relationship():
    """Knows. Two people know each other when at least one piece of evidence links them (tenure
    overlap, a shared deal, or positive CRM contact). One row per pair; the tie strength is the
    strongest evidence, and the evidence shown is that strongest item. The symmetric view feeds the
    warm-path graph and the hop-by-hop path strengths."""
    model.define(Knows.new(p1=KnowsEvidence.p1, p2=KnowsEvidence.p2))
    e1, e2, e3 = KnowsEvidence.ref(), KnowsEvidence.ref(), KnowsEvidence.ref()
    model.where(e1.p1 == Knows.p1, e1.p2 == Knows.p2).define(
        Knows.strength(aggs.max(e1.strength).per(Knows)))
    model.where(e2.p1 == Knows.p1, e2.p2 == Knows.p2).define(
        Knows.evidence_count(aggs.count(e2).per(Knows)))
    model.where(e3.p1 == Knows.p1, e3.p2 == Knows.p2,
                rank(asc(0.0 - e3.strength), asc(e3.kind), asc(e3.key)).per(Knows) == 1).define(
        Knows.evidence(e3.label))
    pa, pb = Person.ref(), Person.ref()
    model.where(Knows.p1(pa), Knows.p2(pb)).define(
        pa.knows(pb), pb.knows(pa), pa.tie_strength(pb, Knows.strength), pb.tie_strength(pa, Knows.strength))


# ============================================================================================
# 5. Access: decision-makers and the closest intermediary (Q-PATH)
# ============================================================================================
def decision_makers():
    """Decision-makers. For every eligible target: its current CEO, and, when a sponsor fund owns
    it, each person who sits on its board today and is on the owning sponsor's deal team today
    (the owner's board designee). CFOs, COOs and independent directors are routes, not outcomes."""
    p = Person.ref()
    model.where(EligibleTarget(Company), Company.current_ceo(p)).define(
        dm := DecisionMaker.new(target=Company, person=p), dm.kind("CEO"))
    f, sp, rb, rd, q = Fund.ref(), Sponsor.ref(), Role.ref(), Role.ref(), Person.ref()
    model.where(EligibleTarget(Company), Company.current_owner_fund(f), f.sponsor(sp),
                rb.organization(Company), rb.role_type == "Board", rb.is_current(), rb.person(q),
                rd.organization(sp), rd.role_type == "Deal Team", rd.is_current(), rd.person(q),
                model.not_(Company.current_ceo(q))).define(
        dm := DecisionMaker.new(target=Company, person=q), dm.kind("OWNER_DESIGNEE"))


def closest_intermediary():
    """Closest intermediary. For a company, the bank or boutique with the most recent dated tie in
    the last 5 years: an engagement signal, or an advisor seat (sell-side, buy-side or debt advisor)
    on a deal for the company. Ties go to the name first alphabetically. It is the route into a cold
    target: Harbor Lane Advisors for Saltmarsh."""
    sg, im = Signal.ref(), Intermediary.ref()
    model.where(sg.company(Company), sg.signal_type == "BANKER_ENGAGED", sg.intermediary(im),
                sg.signal_date >= T_5Y, sg.signal_date <= AS_OF).define(
        x := IntermediaryTie.new(company=Company, intermediary=im, key=sg.id),
        x.days_ago(pd_(sg.signal_date, AS_OF)), x.label(strings.concat("engaged ", _s(sg.signal_date))))
    tp, t, im2 = TransactionParty.ref(), Transaction.ref(), Intermediary.ref()
    model.where(tp.transaction(t), t.target(Company), tp.organization(im2), tp.party_role.in_(list(ADVISOR_ROLES)),
                t.close_date >= T_5Y, t.close_date <= AS_OF).define(
        x := IntermediaryTie.new(company=Company, intermediary=im2, key=tp.id),
        x.days_ago(pd_(t.close_date, AS_OF)),
        x.label(strings.concat(_words(tp.party_role), " on the ", _s(t.close_date), " ", _words(t.structure))))
    a, b, c, iv = IntermediaryTie.ref(), IntermediaryTie.ref(), IntermediaryTie.ref(), Intermediary.ref()
    model.where(a.company(Company), a.intermediary(iv),
                rank(asc(a.days_ago), asc(iv.name), asc(iv.id), asc(a.key)).per(Company) == 1).define(
        Company.closest_intermediary(iv))
    model.where(a.company(Company), a.intermediary(iv)).define(
        a.position(rank(asc(a.days_ago), asc(a.key)).per(Company, iv)))
    model.where(a.company(Company), a.intermediary(iv), a.position == 1).define(
        Company.intermediary_ties_upto(iv, 1, a.label))
    i, t2 = Integer.ref(), String.ref()
    model.where(Company.intermediary_ties_upto(iv, i, t2), b.company(Company), b.intermediary(iv),
                b.position == i + 1).define(
        Company.intermediary_ties_upto(iv, b.position, strings.concat(t2, "; ", b.label)))
    model.where(c.company(Company), c.intermediary(iv)).define(Company.has_tie_item(c.position, iv))
    model.where(Company.closest_intermediary(iv), Company.intermediary_ties_upto(iv, i, t2),
                model.not_(Company.has_tie_item(i + 1, iv))).define(
        Company.closest_intermediary_evidence(t2))


# ============================================================================================
# 6. Deal flow and coverage (Q-FLOW)
# ============================================================================================
def deal_flow_scope():
    """Deal-flow scope. A deal counts when it closed in the last 5 years and its target is in the
    Fund IV thesis (the same hierarchy rule as Q-SCORE). For each intermediary: thesis deals advised
    (sell-side, buy-side or debt advisor; lenders are not advisors) and all deals advised in 5 years
    (the league-table count, shown only as a contrast)."""
    tgt = Company.ref()
    model.where(Transaction.close_date >= T_5Y, Transaction.close_date <= AS_OF, Transaction.target(tgt),
                tgt.in_thesis()).define(DealFlowTransaction(Transaction))
    tp, t, tp2, t2 = TransactionParty.ref(), Transaction.ref(), TransactionParty.ref(), Transaction.ref()
    model.define(Intermediary.thesis_deals_5y(
        aggs.count(t).per(Intermediary).where(tp.transaction(t), tp.organization(Intermediary),
                                              tp.party_role.in_(list(ADVISOR_ROLES)), DealFlowTransaction(t)) | 0))
    model.define(Intermediary.all_deals_5y(
        aggs.count(t2).per(Intermediary).where(tp2.transaction(t2), tp2.organization(Intermediary),
                                               tp2.party_role.in_(list(ADVISOR_ROLES)), t2.close_date >= T_5Y,
                                               t2.close_date <= AS_OF) | 0))


def coverage_gap():
    """Coverage gap. Touchpoints are our CRM interactions in the last 24 months with the intermediary
    or with anyone who works there today (0 when none). The bottom-quartile line is the touchpoint
    count at position ceil(25% of N) over all intermediaries; the top decile of bridges is
    ceil(10% of the intermediaries in the deal-flow graph), by betweenness rank from the graph. A
    gap is a top-decile bridge we touch no more than the bottom quartile: it moves deals in our
    sectors and we barely call it. Volume is not control: the league-table leader is not a bridge."""
    ix = Interaction.ref()
    model.define(Intermediary.touchpoints_24m(
        aggs.count(ix).per(Intermediary).where(ix.touches_org(Intermediary), ix.interaction_date >= T_24M,
                                               ix.interaction_date <= AS_OF) | 0))
    model.define(Intermediary.touch_position(
        rank(asc(Intermediary.touchpoints_24m), asc(Intermediary.name), asc(Intermediary.id))))
    i_all, i_graph = Intermediary.ref(), Intermediary.ref()
    q1_pos = numbers.integer(math.ceil(0.25 * floats.float(aggs.count(i_all))))
    model.where(Intermediary.touch_position == q1_pos).define(coverage_q1(Intermediary.touchpoints_24m))
    model.define(bridge_cutoff(numbers.integer(math.ceil(
        0.10 * floats.float(aggs.count(i_graph).where(i_graph.bridge_rank))))))
    c, q = Integer.ref(), Integer.ref()
    model.where(bridge_cutoff(c), coverage_q1(q), Intermediary.bridge_rank <= c,
                Intermediary.touchpoints_24m <= q).define(CoverageGap(Intermediary))


# ============================================================================================
# 7. Conflicts and concentration (Q-CONFLICT)
# ============================================================================================
def northwind_holding_and_subject():
    """Northwind holdings and the bid subject. A holding is current ownership by a Northwind fund
    (time-bounded: a company we sold in 2020 is not ours). The conflict check runs on the company
    we are preparing an IOI for (pipeline stage "IOI prep")."""
    model.where(PipelineEntry.company(Company), PipelineEntry.stage.in_(list(CONFLICT_SUBJECT_STAGES))).define(
        ConflictSubject(Company))


def portfolio_exposure():
    """Portfolio exposure. For the bid subject, every current Northwind holding within two commercial
    links (supplier or customer, either direction; the distance comes from the commercial graph).
    One link to a company held by another Northwind fund is a conflict for cross-fund review; one
    link to a Fund IV company is a same-fund link; two links is a shared counterparty, shown for
    information. The evidence states the link directions through the middle company. A holding
    three links out, or a former holding, never appears."""
    a, b = Company.ref(), Company.ref()
    model.where(a.supplies(b)).define(
        a.link_phrase(b, strings.concat(a.name, " supplies ", b.name)))
    model.where(b.supplies(a), model.not_(a.supplies(b))).define(
        a.link_phrase(b, strings.concat(a.name, " buys from ", b.name)))
    s, c, nh, f, h = Company.ref(), Company.ref(), Ownership.ref(), Fund.ref(), Integer.ref()
    model.where(ConflictSubject(s), Company.commercial_hops(s, c, h), h >= 1, h <= EXPOSURE_MAX_HOPS,
                nh.company(c), NorthwindHolding(nh), nh.fund(f)).define(
        x := PortfolioExposure.new(subject=s, company=c), x.fund(f), x.hops(h))
    pe, bf = PortfolioExposure.ref(), Fund.ref()
    model.where(pe.hops == 1, pe.fund(bf), model.not_(BuyingFund(bf))).define(pe.kind(EXPOSURE_CONFLICT_KIND))
    model.where(pe.hops == 1, pe.fund(bf), BuyingFund(bf)).define(pe.kind("SAME-FUND LINK"))
    model.where(pe.hops == 2).define(pe.kind("SHARED COUNTERPARTY (informational)"))
    s2, c2, t = Company.ref(), Company.ref(), String.ref()
    model.where(pe.hops == 1, pe.subject(s2), pe.company(c2), s2.link_phrase(c2, t)).define(pe.evidence(t))
    m, t1, t2 = Company.ref(), String.ref(), String.ref()
    model.where(pe.hops == 2, pe.subject(s2), pe.company(c2), s2.link_phrase(m, t1), m.link_phrase(c2, t2)).define(
        r := ExposureRoute.new(subject=s2, company=c2, middle=m), r.text(strings.concat(t1, "; ", t2)))
    er, mm = ExposureRoute.ref(), Company.ref()
    model.where(pe.subject(s2), pe.company(c2), er.subject(s2), er.company(c2), er.middle(mm),
                rank(asc(mm.name), asc(mm.id)).per(s2, c2) == 1).define(pe.evidence(er.text))


def concentration():
    """Concentration guideline. Fund IV's current equity per thesis area (the hierarchy rollup from
    Act 1, not the company's own niche) as a share of fund size, against the IC guideline (35%).
    Pro forma adds the bid subject's estimated equity check to its own thesis area. Headroom is the
    largest check that stays within the guideline; over-by is how far the deal would breach it."""
    bf = Fund.ref()
    model.where(ThesisArea(Sector)).define(AreaExposure.new(area=Sector))
    ae, a, nh, c, f = AreaExposure.ref(), Sector.ref(), Ownership.ref(), Company.ref(), Fund.ref()
    cur = aggs.sum(nh.equity_invested_musd).per(a).where(NorthwindHolding(nh), nh.fund(f), BuyingFund(f),
                                                          nh.company(c), c.thesis_area(a)) | 0.0
    model.where(ae.area(a)).define(ae.current_musd(cur))
    model.where(BuyingFund(bf)).define(
        AreaExposure.current_pct(100.0 * AreaExposure.current_musd / bf.size_musd),
        AreaExposure.guideline_pct(bf.area_guideline_pct))
    s, area, pe_ = Company.ref(), Sector.ref(), PipelineEntry.ref()
    model.where(ConflictSubject(s), ThesisArea(area)).define(ProFormaExposure.new(subject=s, area=area))
    pf, ae2 = ProFormaExposure.ref(), AreaExposure.ref()
    model.where(pf.subject(s), pf.area(area), ae2.area(area), s.thesis_area(area), pe_.company(s)).define(
        pf.musd(ae2.current_musd + pe_.est_equity_check_musd))
    model.where(pf.subject(s), pf.area(area), ae2.area(area), model.not_(s.thesis_area(area))).define(
        pf.musd(ae2.current_musd))
    model.where(pf.area(area), ae2.area(area), BuyingFund(bf)).define(
        pf.pct(100.0 * pf.musd / bf.size_musd),
        pf.headroom_musd(bf.area_guideline_pct / 100.0 * bf.size_musd - ae2.current_musd),
        pf.over_by_musd(math.maximum(0.0, pf.musd - bf.area_guideline_pct / 100.0 * bf.size_musd)))
    model.where(BuyingFund(bf), pf.pct > bf.area_guideline_pct).define(pf.is_breach())


# ============================================================================================
# 8. Finale (opt-in): warm-path points, cross-fund conflict flag, re-score
# ============================================================================================
FINALE_ENABLED = False


def finale_warm_path_points():
    """Warm-path points (Finale). A target earns 10 access points when its current CEO is two Knows
    hops or fewer from any current Northwind deal-team member or operating partner; otherwise 0. The
    distance is the graph output from Act 2 (Person.nearest_seed_hops), so a graph result feeds a
    governed rule."""
    p = Person.ref()
    model.where(EligibleTarget(Company), Company.current_ceo(p), p.nearest_seed_hops <= WARM_PATH_MAX_HOPS).define(
        Company.warm_path_points(WARM_PATH_POINTS),
        Company.warm_path_text(strings.concat("; ", SCORE_COMPONENTS["A_WARM_PATH"]["label"], " +",
                                              _s(WARM_PATH_POINTS), " (CEO at ", _s(p.nearest_seed_hops),
                                              " hops from our nearest seed)")))
    p2 = Person.ref()
    model.where(EligibleTarget(Company), model.not_(Company.current_ceo(p2),
                                                    p2.nearest_seed_hops <= WARM_PATH_MAX_HOPS)).define(
        Company.warm_path_points(0), Company.warm_path_text(""))


def finale_conflict():
    """Cross-fund conflict (Finale). A target that supplies or buys from a company held today by a
    Northwind fund other than Fund IV (today: Fund III) needs cross-fund clearance: it keeps its score,
    is flagged 'Conflict - cross-fund review' and is held off the Tier A call list until cleared. This
    is the Q-CONFLICT one-link exposure, applied to every target at once."""
    held, nh, f = Company.ref(), Ownership.ref(), Fund.ref()
    base = (EligibleTarget(Company), nh.company(held), NorthwindHolding(nh), nh.fund(f), model.not_(BuyingFund(f)),
            held != Company)
    for cond, verb in ((Company.supplies(held), " supplies "), (held.supplies(Company), " buys from ")):
        extra = () if verb == " supplies " else (model.not_(Company.supplies(held)),)
        model.where(*base, cond, *extra).define(
            Company.has_conflict(),
            x := ConflictLink.new(company=Company, held=held),
            x.text(strings.concat(verb.strip(), " ", held.name, " (", f.name, " since ", _s(nh.start_date), ")")))
    cl, hh = ConflictLink.ref(), Company.ref()
    model.where(cl.company(Company), cl.held(hh), rank(asc(hh.name), asc(hh.id)).per(Company) == 1).define(
        Company.conflict_evidence(cl.text),
        Company.conflict_text(strings.concat("; ", CONFLICT_FLAG, ": ", cl.text)))
    model.where(EligibleTarget(Company), model.not_(Company.has_conflict())).define(Company.conflict_text(""))


def finale_rescore():
    """Finale re-score. Finale score = Act-1 score + warm-path points; the tier uses the Act-1
    thresholds. The finale Tier-A list ranks eligible targets without a conflict flag by finale score,
    then readiness, then fit, then name. Conflicted targets keep their score and their explanation
    says why they are off the list: the score did not change; the eligibility to be on Monday's
    call list did."""
    model.where(EligibleTarget(Company)).define(Company.finale_score(Company.score + Company.warm_path_points))
    model.where(Company.finale_score >= TIER_A_MIN).define(Company.finale_tier("A"))
    model.where(Company.finale_score >= TIER_B_MIN, Company.finale_score < TIER_A_MIN).define(Company.finale_tier("B"))
    model.where(Company.finale_score < TIER_B_MIN).define(Company.finale_tier("C"))
    model.where(EligibleTarget(Company), model.not_(Company.has_conflict())).define(Company.finale_rank(
        rank(asc(0 - Company.finale_score), asc(0 - Company.readiness_points), asc(0 - Company.fit_points),
             asc(Company.name), asc(Company.id))))
    model.where(EligibleTarget(Company)).define(Company.finale_why(
        strings.concat(Company.why, Company.warm_path_text, Company.conflict_text)))


def enable_finale() -> bool:
    """Opt in to the Finale rules (idempotent). Returns True when this call added them.

    queries.finale_rescore() calls this before querying finale_score / finale_rank / has_conflict.
    The rules only add finale_* names, so the Act-1 answers in the same process are unchanged."""
    global FINALE_ENABLED
    if FINALE_ENABLED:
        return False
    finale_warm_path_points()
    finale_conflict()
    finale_rescore()
    FINALE_ENABLED = True
    return True


# ============================================================================================
# Build the Act 1-4 rules at import
# ============================================================================================
for _fn in (sector_closure, who_we_are, evidence_names, thesis_fit, known_to_crm, fit_components, readiness_components,
            access_components, composite_score, why_not_templates, knows_tenure_overlap, knows_deal_coparticipation,
            knows_positive_crm, knows_relationship, decision_makers, closest_intermediary, deal_flow_scope,
            coverage_gap, northwind_holding_and_subject, portfolio_exposure, concentration):
    _fn()

if os.environ.get("PE_DEAL_GRAPH_FINALE", "").strip().lower() in ("1", "true", "yes", "on"):
    enable_finale()


# ============================================================================================
# Rule catalog for the exporter (R13), the explorer's rule panel and Claude Code
# ============================================================================================
def _doc(fn) -> str:
    import inspect as _inspect
    return _inspect.cleandoc(fn.__doc__ or "")


def _entry(name, questions, fn, doc=None):
    return {"name": name, "kind": "rule", "questions": list(questions), "function": fn.__name__,
            "docstring": doc if doc is not None else _doc(fn)}


RULES = {
    "SECTOR_CLOSURE": _entry("Sector and region hierarchy closure", ["Q-SCORE", "Q-FLOW", "Q-CONFLICT"],
                             sector_closure),
    "WHO_WE_ARE": _entry("Northwind, its funds, seeds and holdings", ["Q-SCORE", "Q-PATH", "Q-CONFLICT"], who_we_are),
    "EVIDENCE_NAMES": _entry("How evidence names companies and our people", ["Q-SCORE", "Q-PATH"], evidence_names),
    "FIT_THESIS": _entry("Thesis fit and eligibility", ["Q-SCORE"], thesis_fit),
    "IN_CRM": _entry("Known to our CRM", ["Q-SCORE"], known_to_crm),
    "SCORE": _entry("Composite score, tier and explanation", ["Q-SCORE", "FINALE"], composite_score),
    "WHY_NOT": _entry("Why-not explanations", ["Q-SCORE"], why_not_templates),
    "K1_TENURE": _entry("Tenure overlap (12 months or more)", ["Q-PATH"], knows_tenure_overlap),
    "K1_BOARD": _entry("Board co-service", ["Q-PATH"], knows_tenure_overlap,
                       "Board co-service. The K1 tenure-overlap rule labels a tie board co-service when both "
                       "people held board seats at the same organization for 12 months or more at the same time; "
                       "strength and recency are as for any tenure overlap."),
    "SHARED_EMPLOYER_REJECT": _entry("Shared employer without overlap is not a tie", ["Q-PATH"],
                                     knows_tenure_overlap,
                                     "Shared employer is not a relationship. The tenure-overlap rule requires the "
                                     "two roles to overlap in time by 12 months or more. Working at the same company "
                                     "years apart creates no Knows edge, so the shared-employer intro a SQL self-join "
                                     "reports (two people at the same lab-services company, 613 days apart) is "
                                     "rejected."),
    "K2_DEAL": _entry("Deal co-participation", ["Q-PATH"], knows_deal_coparticipation),
    "K3_CRM": _entry("Positive CRM contact", ["Q-PATH"], knows_positive_crm),
    "KNOWS": _entry("Who knows whom", ["Q-PATH", "FINALE"], knows_relationship),
    "DECISION_MAKER": _entry("Decision-makers", ["Q-PATH"], decision_makers),
    "CLOSEST_INTERMEDIARY": _entry("Closest intermediary", ["Q-PATH", "Q-FLOW"], closest_intermediary),
    "DEAL_FLOW_SCOPE": _entry("Deal-flow scope", ["Q-FLOW"], deal_flow_scope),
    "COVERAGE_GAP": _entry("Coverage gap", ["Q-FLOW"], coverage_gap),
    "NORTHWIND_HOLDING": _entry("Northwind holding (current only)", ["Q-CONFLICT", "FINALE"],
                                northwind_holding_and_subject,
                                "Northwind holding. A company counts as ours only while a Northwind fund owns it "
                                "today (ownership started on or before AS_OF and has not ended). Time-bounded: "
                                "a company a Northwind fund sold in 2020 is not a holding. The bid subject of "
                                "the conflict check is the pipeline company at stage IOI prep."),
    "PORTFOLIO_EXPOSURE": _entry("Portfolio exposure within two links", ["Q-CONFLICT"], portfolio_exposure),
    "CONCENTRATION": _entry("Thesis-area concentration guideline", ["Q-CONFLICT"], concentration),
    "CONFLICT": _entry("Cross-fund conflict flag", ["Q-CONFLICT", "FINALE"], finale_conflict),
    "WARM_PATH_POINTS": _entry("Warm-path access points", ["FINALE"], finale_warm_path_points),
    "FINALE_RESCORE": _entry("Finale re-score", ["FINALE"], finale_rescore),
    "OWNERSHIP": {"name": "Ownership", "kind": "rule", "questions": ["Q-SCORE", "Q-CONFLICT"], "function": "who_we_are",
                  "docstring": "Ownership. A fund owns a company from its start date to its end date (open means "
                               "still owned at AS_OF). Ownership drives the exit window, the owner's board designee, "
                               "Northwind holdings and the concentration guideline."},
    "EMPLOYMENT": {"name": "Current role", "kind": "rule", "questions": ["Q-SCORE", "Q-PATH"], "function": "who_we_are",
                   "docstring": "Current role. A person holds a role at an organization from its start date to its "
                                "end date (open means current at AS_OF). Roles drive CEOs and decision-makers, "
                                "readiness signals (CFO hire, succession, new director), our seeds and tenure overlap."},
}
for _code in _ACT1_CODES:
    _m = SCORE_COMPONENTS[_code]
    if _code == "FIT_THESIS":
        continue  # the FIT_THESIS id documents the thesis rule itself
    _fn_name = {"Fit": fit_components, "Readiness": readiness_components, "Access": access_components}[_m["group"]]
    RULES[_code] = _entry(f"{_m['label']} ({_m['max_points']} points)", ["Q-SCORE"], _fn_name, _m["doc"])
RULES["A_WARM_PATH"] = _entry("Warm path to the CEO (Finale, 10 points)", ["FINALE"], finale_warm_path_points,
                              SCORE_COMPONENTS["A_WARM_PATH"]["doc"])

__all__ = [
    "RULES", "SCORE_COMPONENTS", "TIER_A_MIN", "TIER_B_MIN", "READINESS_CAP", "MAX_SCORE", "FIT_MAX", "ACCESS_MAX",
    "VINTAGE_CUT", "ADVISOR_ROLES", "CONFLICT_FLAG", "EXPOSURE_CONFLICT_KIND", "WARM_PATH_MAX_HOPS", "WARM_PATH_POINTS", "EXPOSURE_MAX_HOPS",
    "HELPERS", "enable_finale", "FINALE_ENABLED",
]
