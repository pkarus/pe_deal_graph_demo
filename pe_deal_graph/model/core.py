"""Core layer of the Northwind deal graph (owner: R08 Ontology Engineer).

What lives here
1. Source concepts and their Snowflake bindings: every table in data/schema.sql
   (RAI_DEMO_PE_DEALS.DEAL_GRAPH) maps to one concept or one relationship.
2. Source normalization: open end dates (NULL) mean "still current", evaluated at AS_OF.
3. The DERIVED LAYER CONTRACT: every derived concept, property and relationship that R09
   (rules.py) and R10 (graphs.py) populate is DECLARED here, with its exact name, reading and
   types, and is populated nowhere in this file. rules.py and graphs.py import only this module
   and add model.define(...) rules for the names they own, so neither imports the other
   (graph outputs feed rules and rules feed graphs without an import cycle). ONTOLOGY.md
   section 5 is the human-readable copy of the contract; scripts/validate_ontology.py checks
   that the two agree.

Usage
    from pe_deal_graph.model import model, Company, Person, ...     # or get_model()

Conventions
- Identity: every source concept is identified by its source primary key as ``id`` (String).
  Company, Sponsor and Intermediary share one ``Organization.id`` space (C*, S*, I* prefixes
  never collide), so polymorphic org_id columns resolve with Organization.filter_by(id=...).
- Money is USD millions (``*_musd``, Float). Percentages are 0-100 Floats (``*_pct``).
- BOOLEAN columns are unary flags (``Company.is_public()``, ``Role.is_founder()``).
- Nullable columns are bound in separate define() calls so a NULL never drops the entity.
- No rule calls today(): use AS_OF.
"""

from relationalai.semantics import Date, Float, Integer, Model, String
from relationalai.semantics.std import datetime as dt

# --------------------------------------------------------------------------------------------
# Constants shared by every layer
# --------------------------------------------------------------------------------------------
SOURCE_SCHEMA = "RAI_DEMO_PE_DEALS.DEAL_GRAPH"
AS_OF = dt.date(2026, 10, 1)  # CONFIG AS_OF_DATE as a PyRel date (a python datetime.date literal does not compile)
AS_OF_ISO = "2026-10-01"
OUR_SPONSOR_NAME = "Northwind Equity Partners"  # "us"; Fund IV = our fund with the latest vintage
OUR_SEED_ROLE_TYPES = ("Deal Team", "Operating Partner")  # current roles at our sponsor that make a seed
MAX_PATH_HOPS = 3  # warm paths longer than this are reported as "no path within 3 hops"
BETWEENNESS_PIVOTS = 16000  # >= any possible |V| (row cap), so betweenness is exact Brandes

model = Model("pe_deal_graph")


def get_model() -> Model:
    """Return the single shared Model. Importing this module declares and binds everything in core."""
    return model


def _table(name: str):
    return model.Table(f"{SOURCE_SCHEMA}.{name}")


# ============================================================================================
# 1. SOURCE CONCEPTS
# ============================================================================================

# ---- Organizations (COMPANY, SPONSOR, INTERMEDIARY) ----------------------------------------
Organization = model.Concept("Organization", identify_by={"id": String})
Organization.name = model.Property(f"{Organization} has {String:name}")
Company = model.Concept("Company", extends=[Organization])
Sponsor = model.Concept("Sponsor", extends=[Organization])
Intermediary = model.Concept("Intermediary", extends=[Organization])

# ---- Reference hierarchies ----------------------------------------------------------------
Sector = model.Concept("Sector", identify_by={"id": String})
Region = model.Concept("Region", identify_by={"id": String})

# ---- People and funds ----------------------------------------------------------------------
Person = model.Concept("Person", identify_by={"id": String})
Fund = model.Concept("Fund", identify_by={"id": String})
FundFocus = model.Concept("FundFocus", identify_by={"fund_id": String, "sector_id": String})

# ---- Facts with their own identity ---------------------------------------------------------
Role = model.Concept("Role", identify_by={"id": String})
Ownership = model.Concept("Ownership", identify_by={"id": String})
Transaction = model.Concept("Transaction", identify_by={"id": String})
TransactionParty = model.Concept("TransactionParty", identify_by={"id": String})
CommercialLink = model.Concept("CommercialLink", identify_by={"id": String})
Interaction = model.Concept("Interaction", identify_by={"id": String})
PipelineEntry = model.Concept("PipelineEntry", identify_by={"company_id": String})
Signal = model.Concept("Signal", identify_by={"id": String})

# ---- Properties and relationships ----------------------------------------------------------
Organization.hq_region = model.Property(f"{Organization} is headquartered in {Region:hq_region}")

Sector.name = model.Property(f"{Sector} has {String:name}")
Sector.level = model.Property(f"{Sector} has {Integer:level}")  # 1 sector, 2 subsector, 3 niche
Sector.parent = model.Property(f"{Sector} sits under {Sector:parent}")

Region.name = model.Property(f"{Region} has {String:name}")
Region.level = model.Property(f"{Region} has {Integer:level}")  # 1 country, 2 census region, 3 state/province
Region.region_type = model.Property(f"{Region} has {String:region_type}")
Region.parent = model.Property(f"{Region} sits under {Region:parent}")

Company.sector = model.Property(f"{Company} operates in niche {Sector:sector}")  # always a level-3 niche
Company.revenue_musd = model.Property(f"{Company} has {Float:revenue_musd}")
Company.ebitda_musd = model.Property(f"{Company} has {Float:ebitda_musd}")  # adjusted LTM EBITDA
Company.employees = model.Property(f"{Company} has {Integer:employees}")
Company.founded_year = model.Property(f"{Company} has {Integer:founded_year}")
Company.is_public = model.Relationship(f"{Company} is publicly listed")
Company.operates_in = model.Relationship(f"{Company} has a site in {Region:region}")  # COMPANY_SITE
Company.supplies = model.Relationship(f"{Company} supplies {Company:customer}")  # COMMERCIAL_LINK, direct

Sponsor.aum_musd = model.Property(f"{Sponsor} has {Float:aum_musd}")
Sponsor.strategy = model.Property(f"{Sponsor} has {String:strategy}")

Intermediary.intermediary_type = model.Property(f"{Intermediary} has {String:intermediary_type}")

Person.first_name = model.Property(f"{Person} has {String:first_name}")
Person.last_name = model.Property(f"{Person} has {String:last_name}")
Person.name = model.Property(f"{Person} has {String:name}")  # full_name

Fund.name = model.Property(f"{Fund} has {String:name}")
Fund.sponsor = model.Property(f"{Fund} is managed by {Sponsor:sponsor}")
Fund.vintage_year = model.Property(f"{Fund} has {Integer:vintage_year}")
Fund.size_musd = model.Property(f"{Fund} has {Float:size_musd}")
Fund.ebitda_min_musd = model.Property(f"{Fund} has {Float:ebitda_min_musd}")
Fund.ebitda_max_musd = model.Property(f"{Fund} has {Float:ebitda_max_musd}")
Fund.geography = model.Property(f"{Fund} has {String:geography}")
Fund.area_guideline_pct = model.Property(f"{Fund} has {Float:area_guideline_pct}")  # IC cap per thesis area

FundFocus.fund = model.Property(f"{FundFocus} belongs to {Fund:fund}")
FundFocus.sector = model.Property(f"{FundFocus} targets {Sector:sector}")
FundFocus.mode = model.Property(f"{FundFocus} has {String:mode}")  # include | exclude
FundFocus.margin_benchmark_pct = model.Property(f"{FundFocus} has {Float:margin_benchmark_pct}")

Role.person = model.Property(f"{Role} is held by {Person:person}")
Role.organization = model.Property(f"{Role} is at {Organization:organization}")
Role.role_type = model.Property(f"{Role} has {String:role_type}")  # CEO, CFO, COO, President, Board, ...
Role.title = model.Property(f"{Role} has {String:title}")
Role.start_date = model.Property(f"{Role} starts on {Date:start_date}")
Role.end_date = model.Property(f"{Role} ends on {Date:end_date}")  # absent = current
Role.is_founder = model.Relationship(f"{Role} is held by a founder")

Ownership.company = model.Property(f"{Ownership} is of {Company:company}")
Ownership.fund = model.Property(f"{Ownership} is held by {Fund:fund}")
Ownership.start_date = model.Property(f"{Ownership} starts on {Date:start_date}")
Ownership.end_date = model.Property(f"{Ownership} ends on {Date:end_date}")  # absent = still held
Ownership.stake_type = model.Property(f"{Ownership} has {String:stake_type}")  # majority | minority
Ownership.equity_invested_musd = model.Property(f"{Ownership} has {Float:equity_invested_musd}")

Transaction.target = model.Property(f"{Transaction} targets {Company:target}")
Transaction.close_date = model.Property(f"{Transaction} closed on {Date:close_date}")
Transaction.deal_role = model.Property(f"{Transaction} has {String:deal_role}")  # platform | add_on
Transaction.seller_type = model.Property(f"{Transaction} has {String:seller_type}")  # founder_family | sponsor | corporate
Transaction.structure = model.Property(f"{Transaction} has {String:structure}")  # control_buyout | majority_recap | minority | dividend_recap
Transaction.ev_musd = model.Property(f"{Transaction} has {Float:ev_musd}")
Transaction.ev_ebitda = model.Property(f"{Transaction} has {Float:ev_ebitda}")

TransactionParty.transaction = model.Property(f"{TransactionParty} takes part in {Transaction:transaction}")
TransactionParty.organization = model.Property(f"{TransactionParty} is {Organization:organization}")
TransactionParty.party_role = model.Property(f"{TransactionParty} has {String:party_role}")  # buyer, seller, owner, *_advisor, lender, co_investor
TransactionParty.fund = model.Property(f"{TransactionParty} acts through {Fund:fund}")
TransactionParty.lead_person = model.Property(f"{TransactionParty} is led by {Person:lead_person}")

CommercialLink.supplier = model.Property(f"{CommercialLink} has supplier {Company:supplier}")
CommercialLink.customer = model.Property(f"{CommercialLink} has customer {Company:customer}")
CommercialLink.value_band = model.Property(f"{CommercialLink} has {String:value_band}")
CommercialLink.since_year = model.Property(f"{CommercialLink} has {Integer:since_year}")

Interaction.our_person = model.Property(f"{Interaction} is logged by {Person:our_person}")
Interaction.counterparty_person = model.Property(f"{Interaction} is with person {Person:counterparty_person}")
Interaction.counterparty_org = model.Property(f"{Interaction} is with {Organization:counterparty_org}")
Interaction.interaction_date = model.Property(f"{Interaction} happened on {Date:interaction_date}")
Interaction.channel = model.Property(f"{Interaction} has {String:channel}")  # meeting | call | email | conference
Interaction.sentiment = model.Property(f"{Interaction} has {String:sentiment}")  # positive | neutral | negative

PipelineEntry.company = model.Property(f"{PipelineEntry} tracks {Company:company}")
PipelineEntry.stage = model.Property(f"{PipelineEntry} has {String:stage}")
PipelineEntry.added_date = model.Property(f"{PipelineEntry} was added on {Date:added_date}")
PipelineEntry.owner = model.Property(f"{PipelineEntry} is owned by {Person:owner}")
PipelineEntry.est_equity_check_musd = model.Property(f"{PipelineEntry} has {Float:est_equity_check_musd}")

Signal.company = model.Property(f"{Signal} is about {Company:company}")
Signal.signal_type = model.Property(f"{Signal} has {String:signal_type}")
Signal.signal_date = model.Property(f"{Signal} was learned on {Date:signal_date}")
Signal.event_date = model.Property(f"{Signal} refers to event on {Date:event_date}")  # e.g. debt maturity
Signal.intermediary = model.Property(f"{Signal} names {Intermediary:intermediary}")  # e.g. the engaged bank
Signal.magnitude_musd = model.Property(f"{Signal} has {Float:magnitude_musd}")

# Source normalization (defined below): open end dates -> AS_OF; current at AS_OF.
Role.effective_end_date = model.Property(f"{Role} effectively ends on {Date:effective_end_date}")
Role.is_current = model.Relationship(f"{Role} is current")
Ownership.effective_end_date = model.Property(f"{Ownership} effectively ends on {Date:effective_end_date}")
Ownership.is_current = model.Relationship(f"{Ownership} is current")


# ============================================================================================
# 2. SNOWFLAKE BINDINGS (one block per table, in schema.sql order)
# ============================================================================================
SOURCE_TABLES = {}  # table name -> model.Table, used by scripts/validate_ontology.py


def _bind(name: str):
    t = _table(name)
    SOURCE_TABLES[name] = t
    return t


# SECTOR
_src = _bind("SECTOR")
model.define(x := Sector.new(id=_src.SECTOR_ID), x.name(_src.NAME), x.level(_src.LEVEL))
# Same-type slots need two independent refs: two Sector.filter_by(...) in one rule unify into ONE variable.
_a, _b = Sector.ref(), Sector.ref()
model.where(_a.id == _src.SECTOR_ID, _b.id == _src.PARENT_ID).define(_a.parent(_b))

# REGION
_src = _bind("REGION")
model.define(x := Region.new(id=_src.REGION_ID), x.name(_src.NAME), x.level(_src.LEVEL),
             x.region_type(_src.REGION_TYPE))
_a, _b = Region.ref(), Region.ref()
model.where(_a.id == _src.REGION_ID, _b.id == _src.PARENT_ID).define(_a.parent(_b))

# SPONSOR
_src = _bind("SPONSOR")
model.define(x := Sponsor.new(id=_src.SPONSOR_ID), x.name(_src.NAME),
             x.hq_region(Region.filter_by(id=_src.HQ_REGION_ID)))
model.define(Sponsor.filter_by(id=_src.SPONSOR_ID).aum_musd(_src.AUM_MUSD))
model.define(Sponsor.filter_by(id=_src.SPONSOR_ID).strategy(_src.STRATEGY))

# FUND
_src = _bind("FUND")
model.define(x := Fund.new(id=_src.FUND_ID), x.name(_src.NAME),
             x.sponsor(Sponsor.filter_by(id=_src.SPONSOR_ID)),
             x.vintage_year(_src.VINTAGE_YEAR), x.size_musd(_src.SIZE_MUSD))
model.define(Fund.filter_by(id=_src.FUND_ID).ebitda_min_musd(_src.EBITDA_MIN_MUSD))
model.define(Fund.filter_by(id=_src.FUND_ID).ebitda_max_musd(_src.EBITDA_MAX_MUSD))
model.define(Fund.filter_by(id=_src.FUND_ID).geography(_src.GEOGRAPHY))
model.define(Fund.filter_by(id=_src.FUND_ID).area_guideline_pct(_src.AREA_GUIDELINE_PCT))

# FUND_FOCUS
_src = _bind("FUND_FOCUS")
model.define(x := FundFocus.new(fund_id=_src.FUND_ID, sector_id=_src.SECTOR_ID),
             x.fund(Fund.filter_by(id=_src.FUND_ID)), x.sector(Sector.filter_by(id=_src.SECTOR_ID)),
             x.mode(_src.MODE))
model.define(FundFocus.filter_by(fund_id=_src.FUND_ID, sector_id=_src.SECTOR_ID)
             .margin_benchmark_pct(_src.MARGIN_BENCHMARK_PCT))

# INTERMEDIARY
_src = _bind("INTERMEDIARY")
model.define(x := Intermediary.new(id=_src.INTERMEDIARY_ID), x.name(_src.NAME),
             x.intermediary_type(_src.INTERMEDIARY_TYPE),
             x.hq_region(Region.filter_by(id=_src.HQ_REGION_ID)))

# COMPANY
_src = _bind("COMPANY")
model.define(x := Company.new(id=_src.COMPANY_ID), x.name(_src.NAME),
             x.sector(Sector.filter_by(id=_src.SECTOR_ID)),
             x.hq_region(Region.filter_by(id=_src.HQ_REGION_ID)))
model.define(Company.filter_by(id=_src.COMPANY_ID).revenue_musd(_src.REVENUE_MUSD))
model.define(Company.filter_by(id=_src.COMPANY_ID).ebitda_musd(_src.EBITDA_MUSD))
model.define(Company.filter_by(id=_src.COMPANY_ID).employees(_src.EMPLOYEES))
model.define(Company.filter_by(id=_src.COMPANY_ID).founded_year(_src.FOUNDED_YEAR))
model.where(_src.IS_PUBLIC == True).define(Company.filter_by(id=_src.COMPANY_ID).is_public())  # noqa: E712

# COMPANY_SITE (pure many-to-many: a relationship, not a concept)
_src = _bind("COMPANY_SITE")
model.define(Company.filter_by(id=_src.COMPANY_ID).operates_in(Region.filter_by(id=_src.REGION_ID)))

# PERSON
_src = _bind("PERSON")
model.define(x := Person.new(id=_src.PERSON_ID), x.first_name(_src.FIRST_NAME),
             x.last_name(_src.LAST_NAME), x.name(_src.FULL_NAME))

# ROLE_HISTORY (org_id is polymorphic: resolved through Organization.id)
_src = _bind("ROLE_HISTORY")
model.define(x := Role.new(id=_src.ROLE_ID), x.person(Person.filter_by(id=_src.PERSON_ID)),
             x.organization(Organization.filter_by(id=_src.ORG_ID)),
             x.role_type(_src.ROLE_TYPE), x.start_date(_src.START_DATE))
model.define(Role.filter_by(id=_src.ROLE_ID).title(_src.TITLE))
model.define(Role.filter_by(id=_src.ROLE_ID).end_date(_src.END_DATE))
model.where(_src.IS_FOUNDER == True).define(Role.filter_by(id=_src.ROLE_ID).is_founder())  # noqa: E712

# OWNERSHIP
_src = _bind("OWNERSHIP")
model.define(x := Ownership.new(id=_src.OWNERSHIP_ID), x.company(Company.filter_by(id=_src.COMPANY_ID)),
             x.fund(Fund.filter_by(id=_src.FUND_ID)), x.start_date(_src.START_DATE),
             x.stake_type(_src.STAKE_TYPE))
model.define(Ownership.filter_by(id=_src.OWNERSHIP_ID).end_date(_src.END_DATE))
model.define(Ownership.filter_by(id=_src.OWNERSHIP_ID).equity_invested_musd(_src.EQUITY_INVESTED_MUSD))

# TRANSACTION
_src = _bind("TRANSACTION")
model.define(x := Transaction.new(id=_src.TXN_ID), x.target(Company.filter_by(id=_src.TARGET_ID)),
             x.close_date(_src.CLOSE_DATE), x.deal_role(_src.DEAL_ROLE),
             x.seller_type(_src.SELLER_TYPE), x.structure(_src.STRUCTURE))
model.define(Transaction.filter_by(id=_src.TXN_ID).ev_musd(_src.EV_MUSD))
model.define(Transaction.filter_by(id=_src.TXN_ID).ev_ebitda(_src.EV_EBITDA))

# TRANSACTION_PARTY (org_id is polymorphic)
_src = _bind("TRANSACTION_PARTY")
model.define(x := TransactionParty.new(id=_src.PARTY_ID),
             x.transaction(Transaction.filter_by(id=_src.TXN_ID)),
             x.organization(Organization.filter_by(id=_src.ORG_ID)), x.party_role(_src.PARTY_ROLE))
model.define(TransactionParty.filter_by(id=_src.PARTY_ID).fund(Fund.filter_by(id=_src.FUND_ID)))
model.define(TransactionParty.filter_by(id=_src.PARTY_ID).lead_person(Person.filter_by(id=_src.LEAD_PERSON_ID)))

# COMMERCIAL_LINK (also projected onto the direct Company.supplies relationship)
_src = _bind("COMMERCIAL_LINK")
_a, _b = Company.ref(), Company.ref()
model.where(_a.id == _src.SUPPLIER_ID, _b.id == _src.CUSTOMER_ID).define(
    x := CommercialLink.new(id=_src.LINK_ID), x.supplier(_a), x.customer(_b), x.value_band(_src.VALUE_BAND))
model.define(CommercialLink.filter_by(id=_src.LINK_ID).since_year(_src.SINCE_YEAR))
model.where(_a.id == _src.SUPPLIER_ID, _b.id == _src.CUSTOMER_ID).define(_a.supplies(_b))

# CRM_INTERACTION (counterparty_org_id is polymorphic)
_src = _bind("CRM_INTERACTION")
model.define(x := Interaction.new(id=_src.INTERACTION_ID),
             x.our_person(Person.filter_by(id=_src.OUR_PERSON_ID)),
             x.interaction_date(_src.INTERACTION_DATE), x.channel(_src.CHANNEL),
             x.sentiment(_src.SENTIMENT))
model.define(Interaction.filter_by(id=_src.INTERACTION_ID)
             .counterparty_person(Person.filter_by(id=_src.COUNTERPARTY_PERSON_ID)))
model.define(Interaction.filter_by(id=_src.INTERACTION_ID)
             .counterparty_org(Organization.filter_by(id=_src.COUNTERPARTY_ORG_ID)))

# PIPELINE
_src = _bind("PIPELINE")
model.define(x := PipelineEntry.new(company_id=_src.COMPANY_ID),
             x.company(Company.filter_by(id=_src.COMPANY_ID)), x.stage(_src.STAGE),
             x.added_date(_src.ADDED_DATE), x.owner(Person.filter_by(id=_src.OWNER_PERSON_ID)))
model.define(PipelineEntry.filter_by(company_id=_src.COMPANY_ID)
             .est_equity_check_musd(_src.EST_EQUITY_CHECK_MUSD))

# COMPANY_SIGNAL
_src = _bind("COMPANY_SIGNAL")
model.define(x := Signal.new(id=_src.SIGNAL_ID), x.company(Company.filter_by(id=_src.COMPANY_ID)),
             x.signal_type(_src.SIGNAL_TYPE), x.signal_date(_src.SIGNAL_DATE))
model.define(Signal.filter_by(id=_src.SIGNAL_ID).event_date(_src.EVENT_DATE))
model.define(Signal.filter_by(id=_src.SIGNAL_ID).intermediary(Intermediary.filter_by(id=_src.INTERMEDIARY_ID)))
model.define(Signal.filter_by(id=_src.SIGNAL_ID).magnitude_musd(_src.MAGNITUDE_MUSD))
del _src, _a, _b

# Source normalization: a NULL end date means "still current" and is evaluated as AS_OF.
model.define(Role.effective_end_date(Role.end_date))
model.where(model.not_(Role.end_date)).define(Role.effective_end_date(AS_OF))
model.where(Role.start_date <= AS_OF, model.not_(Role.end_date)).define(Role.is_current())
model.where(Role.start_date <= AS_OF, Role.end_date > AS_OF).define(Role.is_current())
model.define(Ownership.effective_end_date(Ownership.end_date))
model.where(model.not_(Ownership.end_date)).define(Ownership.effective_end_date(AS_OF))
model.where(Ownership.start_date <= AS_OF, model.not_(Ownership.end_date)).define(Ownership.is_current())
model.where(Ownership.start_date <= AS_OF, Ownership.end_date > AS_OF).define(Ownership.is_current())

# Concept name -> (source table, concept) for entity-count checks (count(concept) == table rows).
CONCEPT_SOURCES = {
    "Sector": ("SECTOR", Sector),
    "Region": ("REGION", Region),
    "Sponsor": ("SPONSOR", Sponsor),
    "Fund": ("FUND", Fund),
    "FundFocus": ("FUND_FOCUS", FundFocus),
    "Intermediary": ("INTERMEDIARY", Intermediary),
    "Company": ("COMPANY", Company),
    "Person": ("PERSON", Person),
    "Role": ("ROLE_HISTORY", Role),
    "Ownership": ("OWNERSHIP", Ownership),
    "Transaction": ("TRANSACTION", Transaction),
    "TransactionParty": ("TRANSACTION_PARTY", TransactionParty),
    "CommercialLink": ("COMMERCIAL_LINK", CommercialLink),
    "Interaction": ("CRM_INTERACTION", Interaction),
    "PipelineEntry": ("PIPELINE", PipelineEntry),
    "Signal": ("COMPANY_SIGNAL", Signal),
}
# Organization = SPONSOR + INTERMEDIARY + COMPANY rows (checked as a sum).
UNION_CONCEPTS = {"Organization": ("SPONSOR", "INTERMEDIARY", "COMPANY")}


# ============================================================================================
# 3. DERIVED LAYER CONTRACT (declared here, populated by R09 rules.py and R10 graphs.py)
#    Do not add model.define() rules for these names in core.py. Owner tag on each line.
#    ONTOLOGY.md section 5 documents semantics; validate_ontology.py checks names agree.
# ============================================================================================

# ---- 3.1 Hierarchy closures and "us" (R09) -------------------------------------------------
Sector.ancestor_or_self = model.Relationship(f"{Sector} is within {Sector:ancestor}")  # R09 reflexive-transitive
Region.ancestor_or_self = model.Relationship(f"{Region} is within {Region:ancestor}")  # R09 reflexive-transitive
OurSponsor = model.Concept("OurSponsor", extends=[Sponsor])  # R09 Northwind Equity Partners
OurFund = model.Concept("OurFund", extends=[Fund])  # R09 every fund of OurSponsor
BuyingFund = model.Concept("BuyingFund", extends=[OurFund])  # R09 Fund IV: OurFund with the latest vintage
OurSeed = model.Concept("OurSeed", extends=[Person])  # R09 current Deal Team / Operating Partner at OurSponsor
NorthwindHolding = model.Concept("NorthwindHolding", extends=[Ownership])  # R09 current Ownership by an OurFund
ThesisArea = model.Concept("ThesisArea", extends=[Sector])  # R09 BuyingFund 'include' focus nodes
Company.current_owner_fund = model.Property(f"{Company} is currently owned by {Fund:current_owner_fund}")  # R09 current majority owner
Company.current_ceo = model.Property(f"{Company} is currently led by {Person:current_ceo}")  # R09

# ---- 3.2 Thesis fit, eligibility, readiness, score, tier (R09) -----------------------------
Company.in_thesis = model.Relationship(f"{Company} is in the Fund IV thesis")  # R09 include above, no exclude above
Company.thesis_area = model.Property(f"{Company} falls in thesis area {Sector:thesis_area}")  # R09 deepest include node
Company.margin_benchmark_pct = model.Property(f"{Company} is benchmarked at {Float:margin_benchmark_pct}")  # R09
Company.ebitda_margin_pct = model.Property(f"{Company} has margin {Float:ebitda_margin_pct}")  # R09 100*ebitda/revenue
Company.is_us = model.Relationship(f"{Company} is headquartered in the US")  # R09 region closure reaches US
EligibleTarget = model.Concept("EligibleTarget", extends=[Company])  # R09 scored universe
Company.ineligible_reason = model.Property(f"{Company} is ineligible because {String:ineligible_reason}")  # R09
ScoreComponent = model.Concept("ScoreComponent", identify_by={"company": Company, "code": String})  # R09
ScoreComponent.points = model.Property(f"{ScoreComponent} is worth {Integer:points}")  # R09
ScoreComponent.pillar = model.Property(f"{ScoreComponent} belongs to {String:pillar}")  # R09 Fit | Readiness | Access
ScoreComponent.evidence = model.Property(f"{ScoreComponent} is evidenced by {String:evidence}")  # R09
Company.fit_points = model.Property(f"{Company} has fit {Integer:fit_points}")  # R09 max 30
Company.readiness_points = model.Property(f"{Company} has readiness {Integer:readiness_points}")  # R09 capped 50
Company.access_points = model.Property(f"{Company} has access {Integer:access_points}")  # R09 Act 1: A_CRM only
Company.score = model.Property(f"{Company} has score {Integer:score}")  # R09 fit + readiness + access
Company.tier = model.Property(f"{Company} has tier {String:tier}")  # R09 A >= 70, B 50-69, C < 50
Company.score_rank = model.Property(f"{Company} has score rank {Integer:score_rank}")  # R09 1 = best, tie-broken
Company.why = model.Property(f"{Company} is explained by {String:why}")  # R09 awarded components + evidence
Company.why_not = model.Property(f"{Company} is held back by {String:why_not}")  # R09 'why not' templates (a)+(b)
Company.in_crm = model.Relationship(f"{Company} is known to our CRM")  # R09 pipeline row or touch on it/its people

# ---- 3.3 Relationships between people (R09) ------------------------------------------------
KnowsEvidence = model.Concept("KnowsEvidence", identify_by={"p1": Person, "p2": Person, "kind": String, "key": String})  # R09
KnowsEvidence.strength = model.Property(f"{KnowsEvidence} has {Float:strength}")  # R09 in [0, 1]
KnowsEvidence.label = model.Property(f"{KnowsEvidence} reads {String:label}")  # R09 business-language evidence
KnowsEvidence.organization = model.Property(f"{KnowsEvidence} happened at {Organization:organization}")  # R09 K1 org
KnowsEvidence.transaction = model.Property(f"{KnowsEvidence} came from {Transaction:transaction}")  # R09 K2 deal
KnowsEvidence.from_date = model.Property(f"{KnowsEvidence} starts on {Date:from_date}")  # R09
KnowsEvidence.to_date = model.Property(f"{KnowsEvidence} ends on {Date:to_date}")  # R09
Knows = model.Concept("Knows", identify_by={"p1": Person, "p2": Person})  # R09 one per unordered pair, p1.id < p2.id
Knows.strength = model.Property(f"{Knows} has {Float:strength}")  # R09 max over evidence
Knows.evidence = model.Property(f"{Knows} is evidenced by {String:evidence}")  # R09 label of the strongest evidence
Knows.evidence_count = model.Property(f"{Knows} has {Integer:evidence_count}")  # R09
Person.knows = model.Relationship(f"{Person} knows {Person:other}")  # R09 symmetric (both directions)
Person.tie_strength = model.Property(f"{Person} knows {Person:other} with strength {Float:tie_strength}")  # R09 symmetric

# ---- 3.4 Access: decision-makers, closest intermediary (R09); paths (R10) ------------------
DecisionMaker = model.Concept("DecisionMaker", identify_by={"target": Company, "person": Person})  # R09 per EligibleTarget
DecisionMaker.kind = model.Property(f"{DecisionMaker} decides as {String:kind}")  # R09 CEO | OWNER_DESIGNEE
Company.closest_intermediary = model.Property(f"{Company} is closest to {Intermediary:closest_intermediary}")  # R09
Company.closest_intermediary_evidence = model.Property(f"{Company} links to its intermediary by {String:closest_intermediary_evidence}")  # R09
Person.seed_hops = model.Property(f"{Person:seed} reaches {Person:person} in {Integer:hops} hops")  # R10 distance(from_=OurSeed)
Person.nearest_seed_hops = model.Property(f"{Person} is {Integer:nearest_seed_hops} hops from our nearest seed")  # R10 min over seeds
Person.dm_hops = model.Property(f"{Person:decision_maker} is {Integer:hops} hops from {Person:person}")  # R10 distance(from_=decision-makers)
DecisionMaker.hops = model.Property(f"{DecisionMaker} is {Integer:hops} hops from our nearest seed")  # R10 absent if unreachable
DecisionMaker.is_cold = model.Relationship(f"{DecisionMaker} has no path within 3 hops")  # R10
WarmPath = model.Concept("WarmPath", identify_by={"target": Company, "decision_maker": Person, "route": String})  # R10 route = person ids joined by '>'
WarmPath.seed = model.Property(f"{WarmPath} starts at {Person:seed}")  # R10
WarmPath.hops = model.Property(f"{WarmPath} has {Integer:hops} hops")  # R10 equals DecisionMaker.hops
WarmPath.strength = model.Property(f"{WarmPath} has {Float:strength}")  # R10 product of hop tie strengths
WarmPath.path_rank = model.Property(f"{WarmPath} ranks {Integer:path_rank}")  # R10 1 = best; keep ranks 1-3
WarmPath.evidence = model.Property(f"{WarmPath} is evidenced by {String:evidence}")  # R10 hop-by-hop text
WarmPathHop = model.Concept("WarmPathHop", identify_by={"path": WarmPath, "step": Integer})  # R10 step 1..hops
WarmPathHop.from_person = model.Property(f"{WarmPathHop} goes from {Person:from_person}")  # R10
WarmPathHop.to_person = model.Property(f"{WarmPathHop} goes to {Person:to_person}")  # R10
WarmPathHop.strength = model.Property(f"{WarmPathHop} has {Float:strength}")  # R10 = Person.tie_strength
WarmPathHop.evidence = model.Property(f"{WarmPathHop} is evidenced by {String:evidence}")  # R10 = Knows.evidence

# ---- 3.5 Deal flow and coverage (R09 rules, R10 graph) -------------------------------------
DealFlowTransaction = model.Concept("DealFlowTransaction", extends=[Transaction])  # R09 last 5y, target in thesis
Intermediary.thesis_deals_5y = model.Property(f"{Intermediary} advised {Integer:thesis_deals_5y} thesis deals in 5 years")  # R09
Intermediary.all_deals_5y = model.Property(f"{Intermediary} advised {Integer:all_deals_5y} deals in 5 years")  # R09 league-table count
Organization.deal_flow_partner = model.Relationship(f"{Organization} shares deal flow with {Organization:other}")  # R10 edge set, one fact per pair (id <)
Organization.betweenness = model.Property(f"{Organization} has betweenness {Float:betweenness}")  # R10 exact Brandes
Organization.pagerank = model.Property(f"{Organization} has pagerank {Float:pagerank}")  # R10 display only
Organization.flow_community = model.Property(f"{Organization} is in deal-flow community {Integer:flow_community}")  # R10 optional, Louvain, explorer only
Intermediary.bridge_rank = model.Property(f"{Intermediary} ranks {Integer:bridge_rank} as a bridge")  # R10 among intermediaries
Intermediary.touchpoints_24m = model.Property(f"{Intermediary} has {Integer:touchpoints_24m} touchpoints in 24 months")  # R09 0 when none
coverage_q1 = model.Property(f"intermediary coverage bottom quartile is {Integer:coverage_q1}")  # R09 standalone value
bridge_cutoff = model.Property(f"top decile of bridges ends at rank {Integer:bridge_cutoff}")  # R09 ceil(0.10 * N in graph)
CoverageGap = model.Concept("CoverageGap", extends=[Intermediary])  # R09 top-decile bridge with touchpoints <= Q1

# ---- 3.6 Conflict and concentration (R09 rules, R10 graph) ---------------------------------
ConflictSubject = model.Concept("ConflictSubject", extends=[Company])  # R09 pipeline stage 'IOI prep' or 'IOI Submitted'
Company.commercial_hops = model.Property(f"{Company:subject} is {Integer:hops} commercial links from {Company:company}")  # R10 distance(from_=ConflictSubject)
PortfolioExposure = model.Concept("PortfolioExposure", identify_by={"subject": Company, "company": Company})  # R09 holdings within 2 links
PortfolioExposure.fund = model.Property(f"{PortfolioExposure} is held by {Fund:fund}")  # R09
PortfolioExposure.hops = model.Property(f"{PortfolioExposure} is {Integer:hops} links away")  # R09 1 or 2
PortfolioExposure.kind = model.Property(f"{PortfolioExposure} is classified {String:kind}")  # R09 see ONTOLOGY.md 5.6
PortfolioExposure.evidence = model.Property(f"{PortfolioExposure} is evidenced by {String:evidence}")  # R09 link directions
AreaExposure = model.Concept("AreaExposure", identify_by={"area": Sector})  # R09 one per ThesisArea of BuyingFund
AreaExposure.current_musd = model.Property(f"{AreaExposure} has current {Float:current_musd}")  # R09 0.0 when none
AreaExposure.current_pct = model.Property(f"{AreaExposure} has current share {Float:current_pct}")  # R09 0-100
AreaExposure.guideline_pct = model.Property(f"{AreaExposure} has guideline {Float:guideline_pct}")  # R09 BuyingFund.area_guideline_pct
ProFormaExposure = model.Concept("ProFormaExposure", identify_by={"subject": Company, "area": Sector})  # R09 every subject x area
ProFormaExposure.musd = model.Property(f"{ProFormaExposure} has pro forma {Float:musd}")  # R09
ProFormaExposure.pct = model.Property(f"{ProFormaExposure} has pro forma share {Float:pct}")  # R09 0-100
ProFormaExposure.headroom_musd = model.Property(f"{ProFormaExposure} leaves headroom {Float:headroom_musd}")  # R09 guideline - current
ProFormaExposure.over_by_musd = model.Property(f"{ProFormaExposure} exceeds by {Float:over_by_musd}")  # R09 0.0 if no breach
ProFormaExposure.is_breach = model.Relationship(f"{ProFormaExposure} breaches the guideline")  # R09 pct > guideline

# ---- 3.7 Finale (R09, behind the FINALE flag) and backups (R10, optional) ------------------
Company.warm_path_points = model.Property(f"{Company} earns warm-path {Integer:warm_path_points}")  # R09 10 or 0
Company.has_conflict = model.Relationship(f"{Company} has a cross-fund conflict")  # R09
Company.conflict_evidence = model.Property(f"{Company} conflicts because {String:conflict_evidence}")  # R09
Company.finale_score = model.Property(f"{Company} has finale score {Integer:finale_score}")  # R09 score + warm_path_points
Company.finale_tier = model.Property(f"{Company} has finale tier {String:finale_tier}")  # R09 by finale_score; conflict does not change it
Company.finale_rank = model.Property(f"{Company} has finale rank {Integer:finale_rank}")  # R09 over non-conflicted scored companies
Company.finale_why = model.Property(f"{Company} is explained in the finale by {String:finale_why}")  # R09
Company.commercial_community = model.Property(f"{Company} is in commercial community {Integer:commercial_community}")  # R10 optional, Louvain
Company.addon_similarity = model.Property(f"{Company:platform} and {Company:candidate} have jaccard {Float:addon_similarity}")  # R10 optional, Q-ADDON backup

# Names of everything in section 3 (validate_ontology.py excludes them from the G3 fact checks and
# checks them against ONTOLOGY.md). OPTIONAL_DERIVED may legitimately stay empty after P4.
DERIVED_CONCEPTS = (
    "OurSponsor", "OurFund", "BuyingFund", "OurSeed", "NorthwindHolding", "ThesisArea", "EligibleTarget",
    "ScoreComponent", "KnowsEvidence", "Knows", "DecisionMaker", "WarmPath", "WarmPathHop",
    "DealFlowTransaction", "CoverageGap", "ConflictSubject", "PortfolioExposure", "AreaExposure",
    "ProFormaExposure",
)
DERIVED_RELATIONSHIPS = (
    "Sector.ancestor_or_self", "Region.ancestor_or_self", "Company.current_owner_fund", "Company.current_ceo",
    "Company.in_thesis", "Company.thesis_area", "Company.margin_benchmark_pct", "Company.ebitda_margin_pct",
    "Company.is_us", "Company.ineligible_reason", "ScoreComponent.points", "ScoreComponent.pillar",
    "ScoreComponent.evidence", "Company.fit_points", "Company.readiness_points", "Company.access_points",
    "Company.score", "Company.tier", "Company.score_rank", "Company.why", "Company.why_not", "Company.in_crm",
    "KnowsEvidence.strength", "KnowsEvidence.label", "KnowsEvidence.organization", "KnowsEvidence.transaction",
    "KnowsEvidence.from_date", "KnowsEvidence.to_date", "Knows.strength", "Knows.evidence", "Knows.evidence_count",
    "Person.knows", "Person.tie_strength", "DecisionMaker.kind", "Company.closest_intermediary",
    "Company.closest_intermediary_evidence", "Person.seed_hops", "Person.nearest_seed_hops", "Person.dm_hops",
    "DecisionMaker.hops", "DecisionMaker.is_cold", "WarmPath.seed", "WarmPath.hops", "WarmPath.strength",
    "WarmPath.path_rank", "WarmPath.evidence", "WarmPathHop.from_person", "WarmPathHop.to_person",
    "WarmPathHop.strength", "WarmPathHop.evidence", "Intermediary.thesis_deals_5y", "Intermediary.all_deals_5y",
    "Organization.deal_flow_partner", "Organization.betweenness", "Organization.pagerank",
    "Organization.flow_community", "Intermediary.bridge_rank", "Intermediary.touchpoints_24m", "coverage_q1",
    "bridge_cutoff", "Company.commercial_hops", "PortfolioExposure.fund", "PortfolioExposure.hops",
    "PortfolioExposure.kind", "PortfolioExposure.evidence", "AreaExposure.current_musd", "AreaExposure.current_pct",
    "AreaExposure.guideline_pct", "ProFormaExposure.musd", "ProFormaExposure.pct", "ProFormaExposure.headroom_musd",
    "ProFormaExposure.over_by_musd", "ProFormaExposure.is_breach", "Company.warm_path_points", "Company.has_conflict",
    "Company.conflict_evidence", "Company.finale_score", "Company.finale_tier", "Company.finale_rank",
    "Company.finale_why", "Company.commercial_community", "Company.addon_similarity",
)
OPTIONAL_DERIVED = (
    "Organization.flow_community", "Company.commercial_community", "Company.addon_similarity",
    "KnowsEvidence.organization", "KnowsEvidence.transaction", "KnowsEvidence.from_date", "KnowsEvidence.to_date",
    "DecisionMaker.is_cold", "CoverageGap", "Company.why_not", "Company.ineligible_reason",
    "ProFormaExposure.is_breach", "Company.has_conflict", "Company.conflict_evidence",
)

__all__ = [
    "model", "get_model", "AS_OF", "AS_OF_ISO", "SOURCE_SCHEMA", "OUR_SPONSOR_NAME", "OUR_SEED_ROLE_TYPES",
    "MAX_PATH_HOPS", "BETWEENNESS_PIVOTS", "SOURCE_TABLES", "CONCEPT_SOURCES", "UNION_CONCEPTS",
    "DERIVED_CONCEPTS", "DERIVED_RELATIONSHIPS", "OPTIONAL_DERIVED",
    # source concepts
    "Organization", "Company", "Sponsor", "Intermediary", "Sector", "Region", "Person", "Fund", "FundFocus",
    "Role", "Ownership", "Transaction", "TransactionParty", "CommercialLink", "Interaction", "PipelineEntry",
    "Signal",
    # derived concepts and standalone values
    *DERIVED_CONCEPTS, "coverage_q1", "bridge_cutoff",
]
