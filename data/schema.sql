-- PE deal-graph demo: Snowflake DDL (owner: R05 Data Architect)
-- Target: RAI_DEMO_PE_DEALS.DEAL_GRAPH. All data is synthetic and fictional, as of AS_OF_DATE 2026-10-01.
--
-- Conventions
-- * IDs are opaque strings drawn from shuffled pools; the prefix only names the entity type
--   (C = company, S = sponsor, I = intermediary, F = fund, P = person, SC = sector,
--   R = role, O = ownership, T = transaction, TP = transaction party, L = commercial link,
--   X = CRM interaction, G = signal). Region IDs are natural codes (US, US-SOUTH, US-TX, CA-ON).
-- * Organizations are polymorphic: ROLE_HISTORY.org_id, TRANSACTION_PARTY.org_id and
--   CRM_INTERACTION.counterparty_org_id point to COMPANY, SPONSOR or INTERMEDIARY, and the sibling
--   org_type column ('company' | 'sponsor' | 'intermediary') says which table to join.
--   Snowflake does not enforce FOREIGN KEY constraints; they are declared below where the target is a
--   single table and documented in comments where the target is polymorphic. The R05 self-check
--   (python data/generate.py --check) verifies 100% referential integrity on every one of them.
-- * Open end dates (NULL) mean "still current". Dates are DATE, money is USD millions (NUMBER(10,2)).
-- * No column carries ground truth: there is no planted flag, no story key, no expected answer.
--   data/golden/ is never loaded.

CREATE OR REPLACE TABLE SECTOR (
    sector_id        VARCHAR(16)  NOT NULL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    level            NUMBER(1)    NOT NULL,          -- 1 sector, 2 subsector, 3 niche
    parent_id        VARCHAR(16),                    -- NULL for level 1
    CONSTRAINT fk_sector_parent FOREIGN KEY (parent_id) REFERENCES SECTOR (sector_id)
);

CREATE OR REPLACE TABLE REGION (
    region_id        VARCHAR(16)  NOT NULL PRIMARY KEY, -- 'US', 'US-SOUTH', 'US-TX', 'CA', 'CA-ON'
    name             VARCHAR(80)  NOT NULL,
    level            NUMBER(1)    NOT NULL,          -- 1 country, 2 census region, 3 state or province
    region_type      VARCHAR(20)  NOT NULL,          -- country | census_region | state | province
    parent_id        VARCHAR(16),
    CONSTRAINT fk_region_parent FOREIGN KEY (parent_id) REFERENCES REGION (region_id)
);

CREATE OR REPLACE TABLE SPONSOR (
    sponsor_id       VARCHAR(16)  NOT NULL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    hq_region_id     VARCHAR(16)  NOT NULL,
    aum_musd         NUMBER(10,2),
    strategy         VARCHAR(40),                    -- lower_mid_market_buyout | middle_market_buyout | growth_buyout
    CONSTRAINT fk_sponsor_region FOREIGN KEY (hq_region_id) REFERENCES REGION (region_id)
);

CREATE OR REPLACE TABLE FUND (
    fund_id          VARCHAR(16)  NOT NULL PRIMARY KEY,
    sponsor_id       VARCHAR(16)  NOT NULL,
    name             VARCHAR(120) NOT NULL,
    vintage_year     NUMBER(4)    NOT NULL,
    size_musd        NUMBER(10,2) NOT NULL,
    ebitda_min_musd  NUMBER(10,2),                   -- target EBITDA band
    ebitda_max_musd  NUMBER(10,2),
    geography        VARCHAR(40),
    area_guideline_pct NUMBER(5,2),                  -- IC concentration guideline per thesis area (% of size); NULL if none
    CONSTRAINT fk_fund_sponsor FOREIGN KEY (sponsor_id) REFERENCES SPONSOR (sponsor_id)
);

-- Thesis tree: include / exclude nodes at mixed sector levels, with a margin benchmark per include node.
CREATE OR REPLACE TABLE FUND_FOCUS (
    fund_id               VARCHAR(16) NOT NULL,
    sector_id             VARCHAR(16) NOT NULL,
    mode                  VARCHAR(10) NOT NULL,      -- include | exclude
    margin_benchmark_pct  NUMBER(5,2),               -- EBITDA margin benchmark in percent; NULL for exclude
    PRIMARY KEY (fund_id, sector_id),
    CONSTRAINT fk_focus_fund   FOREIGN KEY (fund_id)   REFERENCES FUND (fund_id),
    CONSTRAINT fk_focus_sector FOREIGN KEY (sector_id) REFERENCES SECTOR (sector_id)
);

CREATE OR REPLACE TABLE INTERMEDIARY (
    intermediary_id    VARCHAR(16)  NOT NULL PRIMARY KEY,
    name               VARCHAR(120) NOT NULL,
    intermediary_type  VARCHAR(30)  NOT NULL,        -- boutique | regional_bank | large_bank | business_broker
    hq_region_id       VARCHAR(16)  NOT NULL,
    CONSTRAINT fk_intermediary_region FOREIGN KEY (hq_region_id) REFERENCES REGION (region_id)
);

CREATE OR REPLACE TABLE COMPANY (
    company_id       VARCHAR(16)  NOT NULL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    sector_id        VARCHAR(16)  NOT NULL,          -- always a level-3 niche
    hq_region_id     VARCHAR(16)  NOT NULL,          -- a state or province
    revenue_musd     NUMBER(10,2),
    ebitda_musd      NUMBER(10,2),                   -- adjusted EBITDA, last twelve months
    employees        NUMBER(8),
    founded_year     NUMBER(4),
    is_public        BOOLEAN      NOT NULL,
    CONSTRAINT fk_company_sector FOREIGN KEY (sector_id)    REFERENCES SECTOR (sector_id),
    CONSTRAINT fk_company_region FOREIGN KEY (hq_region_id) REFERENCES REGION (region_id)
);

-- States a company operates in (HQ state included).
CREATE OR REPLACE TABLE COMPANY_SITE (
    company_id       VARCHAR(16)  NOT NULL,
    region_id        VARCHAR(16)  NOT NULL,
    PRIMARY KEY (company_id, region_id),
    CONSTRAINT fk_site_company FOREIGN KEY (company_id) REFERENCES COMPANY (company_id),
    CONSTRAINT fk_site_region  FOREIGN KEY (region_id)  REFERENCES REGION (region_id)
);

CREATE OR REPLACE TABLE PERSON (
    person_id        VARCHAR(16)  NOT NULL PRIMARY KEY,
    first_name       VARCHAR(60)  NOT NULL,
    last_name        VARCHAR(60)  NOT NULL,
    full_name        VARCHAR(120) NOT NULL
);

-- Dated senior tenures. role_type in {CEO, CFO, COO, President, Board, Operating Partner, Deal Team, Banker}.
-- title is display text (e.g. 'Managing Partner', 'Principal', 'Managing Director').
CREATE OR REPLACE TABLE ROLE_HISTORY (
    role_id          VARCHAR(16)  NOT NULL PRIMARY KEY,
    person_id        VARCHAR(16)  NOT NULL,
    org_id           VARCHAR(16)  NOT NULL,          -- polymorphic: COMPANY | SPONSOR | INTERMEDIARY (see org_type)
    org_type         VARCHAR(16)  NOT NULL,          -- company | sponsor | intermediary
    role_type        VARCHAR(30)  NOT NULL,
    title            VARCHAR(80),
    start_date       DATE         NOT NULL,
    end_date         DATE,                           -- NULL = current
    is_founder       BOOLEAN      NOT NULL,
    CONSTRAINT fk_role_person FOREIGN KEY (person_id) REFERENCES PERSON (person_id)
);

CREATE OR REPLACE TABLE OWNERSHIP (
    ownership_id          VARCHAR(16)  NOT NULL PRIMARY KEY,
    company_id            VARCHAR(16)  NOT NULL,
    fund_id               VARCHAR(16)  NOT NULL,
    start_date            DATE         NOT NULL,
    end_date              DATE,                      -- NULL = still held
    stake_type            VARCHAR(16)  NOT NULL,     -- majority | minority
    equity_invested_musd  NUMBER(10,2),
    CONSTRAINT fk_own_company FOREIGN KEY (company_id) REFERENCES COMPANY (company_id),
    CONSTRAINT fk_own_fund    FOREIGN KEY (fund_id)    REFERENCES FUND (fund_id)
);

-- Transaction type is three dimensions (R02 correction): deal_role, seller_type, structure.
-- NOTE for R07: TRANSACTION is not a Snowflake reserved word; quote it ("TRANSACTION") only if a client complains.
CREATE OR REPLACE TABLE TRANSACTION (
    txn_id           VARCHAR(16)  NOT NULL PRIMARY KEY,
    target_id        VARCHAR(16)  NOT NULL,
    close_date       DATE         NOT NULL,
    deal_role        VARCHAR(16)  NOT NULL,          -- platform | add_on
    seller_type      VARCHAR(20)  NOT NULL,          -- founder_family | sponsor | corporate (owner type for recaps)
    structure        VARCHAR(20)  NOT NULL,          -- control_buyout | majority_recap | minority | dividend_recap
    ev_musd          NUMBER(10,2),
    ev_ebitda        NUMBER(6,2),
    CONSTRAINT fk_txn_target FOREIGN KEY (target_id) REFERENCES COMPANY (company_id)
);

-- party_role in {buyer, seller, owner, sell_side_advisor, buy_side_advisor, debt_advisor, lender, co_investor}.
-- owner = the sponsor fund holding the target in a recap with no change of control.
-- A sponsor buyer, seller or owner carries fund_id; an add-on buyer is the platform COMPANY (fund_id NULL).
CREATE OR REPLACE TABLE TRANSACTION_PARTY (
    party_id         VARCHAR(16)  NOT NULL PRIMARY KEY,
    txn_id           VARCHAR(16)  NOT NULL,
    org_id           VARCHAR(16)  NOT NULL,          -- polymorphic: COMPANY | SPONSOR | INTERMEDIARY (see org_type)
    org_type         VARCHAR(16)  NOT NULL,
    party_role       VARCHAR(24)  NOT NULL,
    fund_id          VARCHAR(16),
    lead_person_id   VARCHAR(16),                    -- the lead deal partner or banker on this side
    CONSTRAINT fk_party_txn    FOREIGN KEY (txn_id)         REFERENCES TRANSACTION (txn_id),
    CONSTRAINT fk_party_fund   FOREIGN KEY (fund_id)        REFERENCES FUND (fund_id),
    CONSTRAINT fk_party_person FOREIGN KEY (lead_person_id) REFERENCES PERSON (person_id)
);

-- Directed supplier -> customer edge. Every row is a current relationship.
CREATE OR REPLACE TABLE COMMERCIAL_LINK (
    link_id          VARCHAR(16)  NOT NULL PRIMARY KEY,
    supplier_id      VARCHAR(16)  NOT NULL,
    customer_id      VARCHAR(16)  NOT NULL,
    value_band       VARCHAR(12)  NOT NULL,          -- '<1M' | '1-5M' | '5-20M' | '20M+' annual spend
    since_year       NUMBER(4),
    CONSTRAINT fk_link_supplier FOREIGN KEY (supplier_id) REFERENCES COMPANY (company_id),
    CONSTRAINT fk_link_customer FOREIGN KEY (customer_id) REFERENCES COMPANY (company_id)
);

-- Northwind touchpoints. Person-level when counterparty_person_id is set; org-level otherwise.
CREATE OR REPLACE TABLE CRM_INTERACTION (
    interaction_id          VARCHAR(16) NOT NULL PRIMARY KEY,
    our_person_id           VARCHAR(16) NOT NULL,
    counterparty_person_id  VARCHAR(16),
    counterparty_org_id     VARCHAR(16),             -- polymorphic: COMPANY | SPONSOR | INTERMEDIARY
    counterparty_org_type   VARCHAR(16),
    interaction_date        DATE        NOT NULL,
    channel                 VARCHAR(16) NOT NULL,    -- meeting | call | email | conference
    sentiment               VARCHAR(10) NOT NULL,    -- positive | neutral | negative
    CONSTRAINT fk_crm_our   FOREIGN KEY (our_person_id)          REFERENCES PERSON (person_id),
    CONSTRAINT fk_crm_cpty  FOREIGN KEY (counterparty_person_id) REFERENCES PERSON (person_id)
);

-- Northwind CRM pipeline: one row per company being tracked.
CREATE OR REPLACE TABLE PIPELINE (
    company_id             VARCHAR(16)  NOT NULL PRIMARY KEY,
    stage                  VARCHAR(20)  NOT NULL,    -- Tracking | Contacted | Engaged | IOI prep | IOI Submitted | Passed
    added_date             DATE         NOT NULL,
    owner_person_id        VARCHAR(16)  NOT NULL,
    est_equity_check_musd  NUMBER(10,2),
    CONSTRAINT fk_pipe_company FOREIGN KEY (company_id)      REFERENCES COMPANY (company_id),
    CONSTRAINT fk_pipe_owner   FOREIGN KEY (owner_person_id) REFERENCES PERSON (person_id)
);

-- Dated company events. Scored types: BANKER_ENGAGED, DEBT_MATURITY (event_date = maturity date).
-- Unscored types: ADDON_ANNOUNCED, PRESS_RELEASE, HIRING_SURGE, AWARD, DEBT_REFINANCED.
CREATE OR REPLACE TABLE COMPANY_SIGNAL (
    signal_id        VARCHAR(16)  NOT NULL PRIMARY KEY,
    company_id       VARCHAR(16)  NOT NULL,
    signal_type      VARCHAR(30)  NOT NULL,
    signal_date      DATE         NOT NULL,          -- when we learned of it
    event_date       DATE,                           -- e.g. debt maturity date
    intermediary_id  VARCHAR(16),                    -- e.g. the engaged bank
    magnitude_musd   NUMBER(10,2),                   -- e.g. facility size
    CONSTRAINT fk_signal_company FOREIGN KEY (company_id)      REFERENCES COMPANY (company_id),
    CONSTRAINT fk_signal_interm  FOREIGN KEY (intermediary_id) REFERENCES INTERMEDIARY (intermediary_id)
);
