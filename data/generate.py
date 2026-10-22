#!/usr/bin/env python3
"""Deterministic synthetic data generator for the Northwind PE deal-graph demo (owner: R05).

Usage
    python data/generate.py            # writes data/csv/*.csv, data/csv/MANIFEST.json,
                                       # data/golden/expected.json, data/golden/stories.md
    python data/generate.py --check    # R05 self-check of the written CSVs against golden intent
    python data/generate.py --noise --out data/csv_noise   # R12: signal + noise into DIR (golden unchanged)
    python data/generate.py --check --out data/csv_noise   # R05 self-check on DIR
    python data/generate.py --noise-check --out data/csv_noise   # R12 extra checks on DIR

Layout of this file
    1. CONSTANTS and helpers (seeded RNG, shuffled ID pools, name generator)
    2. REFERENCE data (sector tree, regions)
    3. SIGNAL section: shared cast, then one planting function per question ID
       (STORIES registry). Swapping a question means replacing one function.
    4. NOISE section (R12): opt-in via --noise --out DIR; default output is signal-only
    5. Writers (CSV, manifest, golden, stories)
    6. Self-check (pandas/networkx; NOT the oracle - R06 builds that independently)

Determinism: every random draw comes from random.Random seeded with RANDOM_SEED (or a
string derived from it), rows are written sorted by primary key, floats are rounded, and
no wall-clock time is read. Same seed, same bytes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

# =====================================================================================
# 1. CONSTANTS AND HELPERS
# =====================================================================================

RANDOM_SEED = 42
AS_OF = date(2026, 10, 1)
ROOT = Path(__file__).resolve().parent
CSV_DIR = ROOT / "csv"
GOLDEN_DIR = ROOT / "golden"
DATA_CAPS = {"max_rows_per_table": 4000, "max_rows_total": 16000}

TABLES = {  # table -> (primary key columns, column order)
    "SECTOR": (["sector_id"], ["sector_id", "name", "level", "parent_id"]),
    "REGION": (["region_id"], ["region_id", "name", "level", "region_type", "parent_id"]),
    "SPONSOR": (["sponsor_id"], ["sponsor_id", "name", "hq_region_id", "aum_musd", "strategy"]),
    "FUND": (["fund_id"], ["fund_id", "sponsor_id", "name", "vintage_year", "size_musd",
                           "ebitda_min_musd", "ebitda_max_musd", "geography", "area_guideline_pct"]),
    "FUND_FOCUS": (["fund_id", "sector_id"], ["fund_id", "sector_id", "mode", "margin_benchmark_pct"]),
    "INTERMEDIARY": (["intermediary_id"], ["intermediary_id", "name", "intermediary_type", "hq_region_id"]),
    "COMPANY": (["company_id"], ["company_id", "name", "sector_id", "hq_region_id", "revenue_musd",
                                 "ebitda_musd", "employees", "founded_year", "is_public"]),
    "COMPANY_SITE": (["company_id", "region_id"], ["company_id", "region_id"]),
    "PERSON": (["person_id"], ["person_id", "first_name", "last_name", "full_name"]),
    "ROLE_HISTORY": (["role_id"], ["role_id", "person_id", "org_id", "org_type", "role_type", "title",
                                   "start_date", "end_date", "is_founder"]),
    "OWNERSHIP": (["ownership_id"], ["ownership_id", "company_id", "fund_id", "start_date", "end_date",
                                     "stake_type", "equity_invested_musd"]),
    "TRANSACTION": (["txn_id"], ["txn_id", "target_id", "close_date", "deal_role", "seller_type",
                                 "structure", "ev_musd", "ev_ebitda"]),
    "TRANSACTION_PARTY": (["party_id"], ["party_id", "txn_id", "org_id", "org_type", "party_role",
                                         "fund_id", "lead_person_id"]),
    "COMMERCIAL_LINK": (["link_id"], ["link_id", "supplier_id", "customer_id", "value_band", "since_year"]),
    "CRM_INTERACTION": (["interaction_id"], ["interaction_id", "our_person_id", "counterparty_person_id",
                                             "counterparty_org_id", "counterparty_org_type",
                                             "interaction_date", "channel", "sentiment"]),
    "PIPELINE": (["company_id"], ["company_id", "stage", "added_date", "owner_person_id",
                                  "est_equity_check_musd"]),
    "COMPANY_SIGNAL": (["signal_id"], ["signal_id", "company_id", "signal_type", "signal_date",
                                       "event_date", "intermediary_id", "magnitude_musd"]),
}

# ID pools: prefix -> (low, high, width). IDs are drawn from a shuffled pool, so planted
# entities get scattered IDs and R12 noise drawn later never shifts a planted ID.
ID_POOLS = {
    "C": (1000, 9999), "S": (100, 999), "I": (100, 999), "F": (100, 999), "P": (10000, 99999),
    "SC": (100, 999), "R": (10000, 99999), "O": (1000, 9999), "T": (1000, 9999),
    "TP": (10000, 99999), "L": (10000, 99999), "X": (10000, 99999), "G": (10000, 99999),
}
ORG_TYPE = {"C": "company", "S": "sponsor", "I": "intermediary"}


def d(s: str) -> date:
    return date.fromisoformat(s)


def months_before(dt: date, months: int) -> date:
    y, m = divmod(dt.month - 1 - months, 12)
    return date(dt.year + y, m + 1, min(dt.day, 28))


class IdPools:
    def __init__(self, seed: int):
        self.pools = {}
        for prefix, (lo, hi) in ID_POOLS.items():
            pool = list(range(lo, hi + 1))
            random.Random(f"{seed}-ids-{prefix}").shuffle(pool)
            self.pools[prefix] = pool

    def next(self, prefix: str) -> str:
        return f"{prefix}{self.pools[prefix].pop()}"


# ---- Procedural fictional names ---------------------------------------------------------
NAME_A = ["Amber", "Ash", "Bel", "Birch", "Brack", "Bram", "Bris", "Cal", "Car", "Cinder", "Clay",
          "Cole", "Dun", "Elder", "Elm", "Fair", "Fen", "Fox", "Gal", "Glen", "Gold", "Hal", "Hart",
          "Hazel", "Heath", "Hol", "Kel", "Lang", "Lark", "Lin", "Mar", "Mill", "Moss", "Nor", "Oak",
          "Orr", "Pell", "Quill", "Raven", "Rook", "Rush", "Sal", "Sedge", "Shel", "Stan", "Tam",
          "Thorn", "Tid", "Wal", "Wex", "Wil", "Win", "Yar", "Ember", "Flint", "Gant", "Hob", "Ivo",
          "Jun", "Kest", "Loam", "Merr", "Nettle", "Ost", "Prim", "Rad", "Sorr", "Tull", "Umber", "Vell"]
NAME_B = ["bury", "brook", "combe", "crest", "dale", "field", "ford", "gate", "hall", "haven", "holt",
          "hurst", "ley", "marsh", "mere", "mont", "moor", "port", "ridge", "stead", "ton", "vale",
          "wick", "wood", "worth", "stow", "thorpe", "by", "well", "den"]
SPONSOR_SUFFIX = ["Capital", "Capital Partners", "Equity Partners", "Partners", "Equity", "Investment Partners"]
INTERMEDIARY_SUFFIX = {"boutique": ["Advisors", "Partners", "Capital Advisors", "& Co."],
                       "regional_bank": ["Securities", "Capital Markets", "Bank Capital"],
                       "large_bank": ["Capital Markets", "Securities"],
                       "business_broker": ["Business Brokers", "Business Advisors"]}
FIRST = ["Aaron", "Abigail", "Adrian", "Alana", "Alicia", "Amara", "Andre", "Anika", "Arjun", "Beatrice",
         "Benedict", "Bianca", "Bram", "Caleb", "Camila", "Carmen", "Cecil", "Chiara", "Colin", "Dalia",
         "Damon", "Darius", "Delia", "Desmond", "Eamon", "Edith", "Elias", "Elise", "Emeka", "Esme",
         "Ezra", "Farah", "Felix", "Fiona", "Gareth", "Gemma", "Gideon", "Greta", "Hamid", "Hana",
         "Hector", "Helena", "Idris", "Ines", "Ivan", "Jada", "Jasper", "Joelle", "Jonah", "Kamal",
         "Keira", "Kenji", "Lena", "Leon", "Lionel", "Lucia", "Malik", "Mara", "Mateo", "Maya",
         "Miles", "Nadia", "Naomi", "Nikhil", "Nora", "Omar", "Orla", "Oscar", "Paloma", "Quentin",
         "Rhea", "Rohan", "Rosa", "Silas", "Simone", "Soren", "Tamsin", "Teodor", "Thea", "Tobias",
         "Uma", "Vera", "Vikram", "Wes", "Yara", "Yusuf", "Zara", "Zeke"]
LAST = ["Abbott", "Achterberg", "Adair", "Albrecht", "Ambrose", "Ardent", "Ashdown", "Balogun", "Barrow",
        "Beaumont", "Bellamy", "Bergstrom", "Blackwood", "Bracken", "Calloway", "Carrow", "Castellan",
        "Chen-Morrow", "Corwin", "Dalby", "Delacroix", "Draycott", "Eastlake", "Ellery", "Escobar",
        "Falkner", "Farrow", "Fenimore", "Galloway", "Garrick", "Haddad", "Halloran", "Hargreave",
        "Holbrook", "Ilves", "Iwata", "Jarrell", "Kavanagh", "Kessler", "Kowalczyk", "Lindqvist",
        "Lockhart", "Maddox", "Marchetti", "Mbeki-Shaw", "Merriman", "Nakashima", "Northcott", "Oduya",
        "Ostrowski", "Pemberton", "Quillon", "Radcliffe", "Rasmussen", "Rourke", "Sandoval", "Sato",
        "Selwyn", "Szabo", "Thackeray", "Trevino", "Underhill", "Vasquez-Lowe", "Vance", "Wakefield",
        "Whitcombe", "Yadav", "Yilmaz", "Zielinski", "Okonkwo", "Varga", "Lindgren", "Moravec", "Tanaka"]

# Naive Q-SCORE keywords (QUESTIONS.md v2). Procedural names never contain them; hero names are
# chosen deliberately.
NAIVE_KEYWORDS = ["health", "medical", "clinic", "dental", "veterinar", "care", "testing", "inspection", "distribution"]

# ---- Sector descriptors used to build procedural company names ---------------------
NICHE_WORDS = {
    "Pediatric Therapy Clinics": ["Pediatric Therapy", "Kids Therapy Group"],
    "Physical Therapy Clinics": ["Physical Therapy", "Rehab Partners"],
    "Dental Service Organizations": ["Dental Partners", "Dental Group"],
    "Urgent Care Clinics": ["Urgent Care", "Walk-In Clinics"],
    "Behavioral Health Clinics": ["Behavioral Health", "Counseling Centers"],
    "Dermatology Practices": ["Dermatology", "Skin Specialists"],
    "Home Infusion Services": ["Home Infusion", "Infusion Partners"],
    "Home Health Agencies": ["Home Health", "Home Nursing"],
    "Hospice Providers": ["Hospice", "Hospice Partners"],
    "Skilled Nursing Facilities": ["Skilled Nursing", "Nursing Centers"],
    "Veterinary Clinics": ["Animal Hospitals", "Veterinary Group"],
    "Veterinary Diagnostics Labs": ["Animal Diagnostics", "Vet Labs"],
    "Healthcare Staffing": ["Clinical Staffing", "Nurse Staffing"],
    "Medical Courier Services": ["Medical Courier", "Specimen Logistics"],
    "Community Hospitals": ["Health System", "Regional Medical Center"],
    "Healthcare Revenue Cycle Services": ["Revenue Cycle", "Claims Partners"],
    "Records Retrieval & Litigation Support": ["Records Retrieval", "Litigation Support"],
    "Payroll & HR Outsourcing": ["Payroll Services", "HR Solutions"],
    "Insurance Claims Processing": ["Claims Services", "Adjusting Services"],
    "Compliance & Training Services": ["Compliance Services", "Training Systems"],
    "Commercial Janitorial Services": ["Facility Services", "Building Services"],
    "Security Guard Services": ["Security Services", "Protective Services"],
    "Pest Control Services": ["Pest Control", "Pest Solutions"],
    "Promotional Products": ["Promotions", "Branded Products"],
    "Digital Marketing Agencies": ["Digital", "Media Group"],
    "Materials Testing": ["Materials Testing", "Geotechnical Labs"],
    "Environmental Testing": ["Environmental Labs", "Analytical Labs"],
    "Non-Destructive Testing": ["NDT Services", "Inspection Services"],
    "Calibration Services": ["Calibration", "Metrology"],
    "Food Safety Testing": ["Food Safety Labs", "Food Labs"],
    "Precision Machining": ["Precision", "Machine Works"],
    "Packaging Manufacturing": ["Packaging", "Container Co"],
    "Industrial Coatings": ["Coatings", "Finishing"],
    "Civil Engineering Services": ["Engineering", "Civil Group"],
    "Commercial HVAC Contractors": ["Mechanical", "Climate Systems"],
    "General Contractors": ["Builders", "Construction"],
    "Aerospace Components": ["Aerostructures", "Aero Components"],
    "Medical & Lab Supply Distribution": ["Clinical Supply", "Lab Supply"],
    "Specialty Chemicals Distribution": ["Chemical Supply", "Chemicals"],
    "Electrical Components Distribution": ["Electrical Supply", "Electric Supply"],
    "Specialty Food Ingredients Distribution": ["Ingredients", "Food Ingredients"],
    "Foodservice Distribution": ["Foodservice", "Food Supply"],
    "Industrial MRO Distribution": ["Industrial Supply", "MRO Supply"],
    "Packaging Supply Distribution": ["Packaging Supply", "Container Supply"],
    "Diagnostic Imaging Centers": ["Imaging", "Radiology Partners"],
    "Healthcare Linen Services": ["Linen Services", "Textile Services"],
    "Veterinary Pharmaceuticals": ["Animal Pharma", "Veterinary Pharmaceuticals"],
    "Generic Pharmaceuticals": ["Pharma", "Generics"],
    "Contract Research Organizations": ["Clinical Research", "Research Partners"],
    "Clinical Laboratory Services": ["Lab Services", "Diagnostics"],
    "Vertical SaaS": ["Software", "Systems"],
    "Cybersecurity Software": ["Cyber", "Security Software"],
    "Managed IT Services": ["IT Services", "Technology Partners"],
    "Data Center Services": ["Data Centers", "Colocation"],
    "Fitness Clubs": ["Fitness", "Athletic Clubs"],
    "Car Wash Chains": ["Car Wash", "Auto Spa"],
    "Specialty Foods": ["Foods", "Provisions"],
    "Craft Beverages": ["Beverage Co", "Brewing"],
}

# ---- Sector economics (domain brief, R02): margin range/median, EV/EBITDA bands ------------
SECTOR_ECON = {  # level-1 or level-2 name -> (margin lo, mode, hi, multiple lo (EV<100), hi (EV>=100))
    "Healthcare Services": (0.10, 0.14, 0.20, (8.0, 10.0), (9.5, 12.0)),
    "Tech-Enabled Business Services": (0.15, 0.18, 0.25, (8.5, 10.5), (10.0, 12.5)),
    "Testing, Inspection & Certification": (0.14, 0.17, 0.22, (8.5, 10.5), (10.0, 12.5)),
    "Specialty Distribution": (0.06, 0.09, 0.13, (7.0, 9.0), (8.5, 10.5)),
    "default": (0.08, 0.13, 0.20, (6.0, 8.5), (8.0, 11.0)),
}

# =====================================================================================
# 2. REFERENCE DATA
# =====================================================================================

SECTOR_TREE = {
    "Healthcare Services": {
        "Outpatient Clinical Services": ["Pediatric Therapy Clinics", "Physical Therapy Clinics",
                                         "Dental Service Organizations", "Urgent Care Clinics",
                                         "Behavioral Health Clinics", "Dermatology Practices", "Diagnostic Imaging Centers"],
        "Post-Acute Care": ["Home Infusion Services", "Home Health Agencies", "Hospice Providers",
                                   "Skilled Nursing Facilities"],
        "Animal Health Services": ["Veterinary Clinics", "Veterinary Diagnostics Labs"],
        "Healthcare Support Services": ["Healthcare Staffing", "Medical Courier Services", "Healthcare Linen Services"],
        "Acute Care": ["Community Hospitals"],
    },
    "Business Services": {
        "Tech-Enabled Business Services": ["Healthcare Revenue Cycle Services",
                                           "Records Retrieval & Litigation Support",
                                           "Payroll & HR Outsourcing", "Insurance Claims Processing",
                                           "Compliance & Training Services"],
        "Facilities Services": ["Commercial Janitorial Services", "Security Guard Services",
                                "Pest Control Services"],
        "Marketing Services": ["Promotional Products", "Digital Marketing Agencies"],
    },
    "Industrials": {
        "Testing, Inspection & Certification": ["Materials Testing", "Environmental Testing",
                                                "Non-Destructive Testing", "Calibration Services",
                                                "Food Safety Testing"],
        "Industrial Manufacturing": ["Precision Machining", "Packaging Manufacturing", "Industrial Coatings"],
        "Engineering & Construction": ["Civil Engineering Services", "Commercial HVAC Contractors",
                                       "General Contractors"],
        "Aerospace & Defense": ["Aerospace Components"],
    },
    "Distribution": {
        "Specialty Distribution": ["Medical & Lab Supply Distribution", "Specialty Chemicals Distribution",
                                   "Electrical Components Distribution",
                                   "Specialty Food Ingredients Distribution", "Industrial MRO Distribution"],
        "Broadline Distribution": ["Foodservice Distribution", "Packaging Supply Distribution"],
    },
    "Life Sciences": {
        "Pharmaceutical Manufacturing": ["Veterinary Pharmaceuticals", "Generic Pharmaceuticals"],
        "Research & Lab Services": ["Contract Research Organizations", "Clinical Laboratory Services"],
    },
    "Technology": {
        "Software": ["Vertical SaaS", "Cybersecurity Software"],
        "IT Services": ["Managed IT Services", "Data Center Services"],
    },
    "Consumer": {
        "Consumer Services": ["Fitness Clubs", "Car Wash Chains"],
        "Food & Beverage": ["Specialty Foods", "Craft Beverages"],
    },
}

US_STATES = {  # code -> (name, census region)
    "AL": ("Alabama", "SOUTH"), "AK": ("Alaska", "WEST"), "AZ": ("Arizona", "WEST"),
    "AR": ("Arkansas", "SOUTH"), "CA": ("California", "WEST"), "CO": ("Colorado", "WEST"),
    "CT": ("Connecticut", "NORTHEAST"), "DE": ("Delaware", "SOUTH"), "DC": ("District of Columbia", "SOUTH"),
    "FL": ("Florida", "SOUTH"), "GA": ("Georgia", "SOUTH"), "HI": ("Hawaii", "WEST"),
    "ID": ("Idaho", "WEST"), "IL": ("Illinois", "MIDWEST"), "IN": ("Indiana", "MIDWEST"),
    "IA": ("Iowa", "MIDWEST"), "KS": ("Kansas", "MIDWEST"), "KY": ("Kentucky", "SOUTH"),
    "LA": ("Louisiana", "SOUTH"), "ME": ("Maine", "NORTHEAST"), "MD": ("Maryland", "SOUTH"),
    "MA": ("Massachusetts", "NORTHEAST"), "MI": ("Michigan", "MIDWEST"), "MN": ("Minnesota", "MIDWEST"),
    "MS": ("Mississippi", "SOUTH"), "MO": ("Missouri", "MIDWEST"), "MT": ("Montana", "WEST"),
    "NE": ("Nebraska", "MIDWEST"), "NV": ("Nevada", "WEST"), "NH": ("New Hampshire", "NORTHEAST"),
    "NJ": ("New Jersey", "NORTHEAST"), "NM": ("New Mexico", "WEST"), "NY": ("New York", "NORTHEAST"),
    "NC": ("North Carolina", "SOUTH"), "ND": ("North Dakota", "MIDWEST"), "OH": ("Ohio", "MIDWEST"),
    "OK": ("Oklahoma", "SOUTH"), "OR": ("Oregon", "WEST"), "PA": ("Pennsylvania", "NORTHEAST"),
    "RI": ("Rhode Island", "NORTHEAST"), "SC": ("South Carolina", "SOUTH"), "SD": ("South Dakota", "MIDWEST"),
    "TN": ("Tennessee", "SOUTH"), "TX": ("Texas", "SOUTH"), "UT": ("Utah", "WEST"),
    "VT": ("Vermont", "NORTHEAST"), "VA": ("Virginia", "SOUTH"), "WA": ("Washington", "WEST"),
    "WV": ("West Virginia", "SOUTH"), "WI": ("Wisconsin", "MIDWEST"), "WY": ("Wyoming", "WEST"),
}
# Population-skewed weights for HQ draws (big business states heavier).
STATE_WEIGHT = defaultdict(lambda: 1.0, {"TX": 9, "CA": 8, "FL": 7, "NY": 6, "IL": 5, "PA": 4, "OH": 4,
                                         "GA": 4, "NC": 4, "NJ": 3, "MA": 3, "VA": 3, "TN": 3, "MI": 3,
                                         "AZ": 3, "CO": 3, "MN": 2.5, "MO": 2.5, "WA": 2.5, "IN": 2})


# =====================================================================================
# World: tables plus helpers that keep cross-table facts consistent
# =====================================================================================

class World:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.ids = IdPools(seed)
        self.t = {name: [] for name in TABLES}
        self.key = {}          # role key -> entity id (golden only, never written to CSV)
        self.name_of = {}      # entity id -> display name
        self.sector_id = {}    # sector name -> id
        self.sector_parent = {}  # sector id -> parent id
        self.sector_name = {}
        self.used_names = set()
        self.company_row = {}
        self.fund_sponsor = {}
        self.fund_vintage = {}
        self.golden = {}       # question id -> golden dict
        self.stories = {}      # question id -> list of story-card markdown strings

    # ---- registry -------------------------------------------------------------------
    def reg(self, key, eid, name=None):
        if key:
            assert key not in self.key, f"duplicate role key {key}"
            self.key[key] = eid
        if name is not None:
            self.name_of[eid] = name
        return eid

    def k(self, key):
        return self.key[key]

    def claim_name(self, name):
        assert name not in self.used_names, f"duplicate name {name}"
        self.used_names.add(name)
        return name

    # ---- procedural names -------------------------------------------------------------
    @staticmethod
    def tidy(word):
        """R20 (R19c m4): collapse a letter tripled at the stem/suffix join ("Millley" -> "Milley").
        Pure string post-processing: consumes no random number, and no stem pair collides after it."""
        out = []
        for ch in word:
            if len(out) >= 2 and out[-1].lower() == ch.lower() and out[-2].lower() == ch.lower():
                continue
            out.append(ch)
        return "".join(out)

    def coined(self, rng=None):
        rng = rng or self.rng
        for _ in range(1000):
            w = self.tidy(rng.choice(NAME_A) + rng.choice(NAME_B))
            if not any(kw in w.lower() for kw in NAIVE_KEYWORDS):
                return w
        raise RuntimeError("name space exhausted")

    def company_name(self, niche, rng=None):
        rng = rng or self.rng
        for _ in range(1000):
            n = f"{self.coined(rng)} {rng.choice(NICHE_WORDS[niche])}"
            if n not in self.used_names:
                return n
        raise RuntimeError("company name space exhausted")

    def person_name(self, rng=None):
        rng = rng or self.rng
        for _ in range(5000):
            f, l = rng.choice(FIRST), rng.choice(LAST)
            n = f"{f} {l}"
            if n not in self.used_names:
                return f, l
        raise RuntimeError("person name space exhausted")

    # ---- entity helpers ---------------------------------------------------------------
    def sponsor(self, key, name, state, aum, strategy="lower_mid_market_buyout"):
        sid = self.ids.next("S")
        self.t["SPONSOR"].append({"sponsor_id": sid, "name": self.claim_name(name), "hq_region_id": f"US-{state}",
                                  "aum_musd": round(aum, 2), "strategy": strategy})
        return self.reg(key, sid, name)

    def fund(self, key, sponsor_id, name, vintage, size, band=(5.0, 40.0), geography="US", guideline=None):
        fid = self.ids.next("F")
        self.t["FUND"].append({"fund_id": fid, "sponsor_id": sponsor_id, "name": self.claim_name(name),
                               "vintage_year": vintage, "size_musd": round(size, 2),
                               "ebitda_min_musd": band[0], "ebitda_max_musd": band[1], "geography": geography,
                               "area_guideline_pct": guideline})
        self.fund_sponsor[fid] = sponsor_id
        self.fund_vintage[fid] = vintage
        return self.reg(key, fid, name)

    def intermediary(self, key, name, itype, state):
        iid = self.ids.next("I")
        self.t["INTERMEDIARY"].append({"intermediary_id": iid, "name": self.claim_name(name),
                                       "intermediary_type": itype, "hq_region_id": f"US-{state}"})
        return self.reg(key, iid, name)

    def company(self, key, name, niche, state, revenue, ebitda, founded=None, employees=None,
                is_public=False, sites=None, rng=None):
        rng = rng or self.rng
        cid = self.ids.next("C")
        if founded is None:
            founded = rng.randint(1965, 2014)
        if employees is None:
            employees = int(round(revenue * rng.uniform(4.0, 9.0)))
        row = {"company_id": cid, "name": self.claim_name(name), "sector_id": self.sector_id[niche],
               "hq_region_id": f"US-{state}" if len(state) == 2 else state,
               "revenue_musd": round(revenue, 2), "ebitda_musd": round(ebitda, 2), "employees": employees,
               "founded_year": founded, "is_public": is_public}
        self.t["COMPANY"].append(row)
        self.company_row[cid] = row
        site_states = sorted(set([state] + list(sites or [])))
        for s in site_states:
            self.t["COMPANY_SITE"].append({"company_id": cid, "region_id": f"US-{s}"})
        return self.reg(key, cid, name)

    def filler_company(self, niche, rng=None, ebitda=None, state=None, key=None, sites=None):
        """A realistic company in `niche` with sector-specific margin and skewed size."""
        rng = rng or self.rng
        econ = self.econ_for(niche)
        if ebitda is None:
            ebitda = round(min(90.0, max(1.5, rng.lognormvariate(math.log(12.0), 0.7))), 1)
        margin = rng.triangular(econ[0], econ[2], econ[1])
        revenue = round(ebitda / margin, 1)
        if state is None:
            states = list(US_STATES)
            state = rng.choices(states, weights=[STATE_WEIGHT[s] for s in states])[0]
        return self.company(key, self.company_name(niche, rng), niche, state, revenue, ebitda, rng=rng,
                            sites=sites)

    def econ_for(self, niche):
        sid = self.sector_id[niche]
        chain = []
        while sid:
            chain.append(self.sector_name[sid])
            sid = self.sector_parent[sid]
        for n in chain:
            if n in SECTOR_ECON:
                return SECTOR_ECON[n]
        return SECTOR_ECON["default"]

    def multiple(self, niche, ebitda, rng=None):
        rng = rng or self.rng
        econ = self.econ_for(niche)
        lo, hi = econ[3] if ebitda * 9 < 100 else econ[4]
        return round(rng.uniform(lo, hi), 1)

    def person(self, key, full_name=None, rng=None):
        pid = self.ids.next("P")
        if full_name is None:
            first, last = self.person_name(rng)
            full_name = f"{first} {last}"
        else:
            first, last = full_name.split(" ", 1)
        self.t["PERSON"].append({"person_id": pid, "first_name": first, "last_name": last,
                                 "full_name": self.claim_name(full_name)})
        return self.reg(key, pid, full_name)

    def role(self, person_id, org_id, role_type, start, end=None, title=None, founder=False):
        prefix = org_id.rstrip("0123456789")
        start_d = d(start) if isinstance(start, str) else start
        if prefix == "C":  # R20 guard: nobody holds a role at a company before the company was founded
            fy = self.company_row[org_id]["founded_year"]
            assert start_d >= date(fy, 1, 1), f"role at {org_id} starts {start_d}, before its founding year {fy}"
        rid = self.ids.next("R")
        self.t["ROLE_HISTORY"].append({"role_id": rid, "person_id": person_id, "org_id": org_id,
                                       "org_type": ORG_TYPE[prefix], "role_type": role_type,
                                       "title": title or role_type, "start_date": d(start) if isinstance(start, str) else start,
                                       "end_date": (d(end) if isinstance(end, str) else end),
                                       "is_founder": founder})
        return rid

    def own(self, company_id, fund_id, start, end=None, equity=None, stake="majority"):
        oid = self.ids.next("O")
        start = d(start) if isinstance(start, str) else start
        end = d(end) if isinstance(end, str) else end
        if equity is None:
            row = self.company_row[company_id]
            equity = round(row["ebitda_musd"] * 9.0 * 0.45, 1)
        self.t["OWNERSHIP"].append({"ownership_id": oid, "company_id": company_id, "fund_id": fund_id,
                                    "start_date": start, "end_date": end, "stake_type": stake,
                                    "equity_invested_musd": round(equity, 2)})
        return oid

    def txn(self, target_id, close, deal_role, seller_type, structure, parties, multiple=None, rng=None):
        """parties: list of (org_id, party_role, fund_id or None, lead_person_id or None)."""
        rng = rng or self.rng
        close = d(close) if isinstance(close, str) else close
        row = self.company_row[target_id]
        niche = self.sector_name[row["sector_id"]]
        ebitda_then = round(row["ebitda_musd"] * rng.uniform(0.70, 0.95), 2)
        mult = multiple if multiple is not None else self.multiple(niche, ebitda_then, rng)
        tid = self.ids.next("T")
        ev = None if structure == "dividend_recap" else round(ebitda_then * mult, 1)
        self.t["TRANSACTION"].append({"txn_id": tid, "target_id": target_id, "close_date": close,
                                      "deal_role": deal_role, "seller_type": seller_type, "structure": structure,
                                      "ev_musd": ev, "ev_ebitda": None if ev is None else mult})
        for org_id, prole, fund_id, lead in parties:
            prefix = org_id.rstrip("0123456789")
            self.t["TRANSACTION_PARTY"].append({"party_id": self.ids.next("TP"), "txn_id": tid, "org_id": org_id,
                                                "org_type": ORG_TYPE[prefix], "party_role": prole,
                                                "fund_id": fund_id, "lead_person_id": lead})
        return tid

    def buyout(self, target_id, close, buyer_fund, advisors=(), seller_fund=None, seller_type="founder_family",
               structure="control_buyout", deal_role="platform", buyer_lead=None, seller_lead=None,
               equity=None, platform_id=None, rng=None):
        """Platform buyout (fund buys target) or add-on (platform company buys target).
        Writes TRANSACTION + parties + OWNERSHIP changes consistently."""
        parties = []
        if deal_role == "add_on":
            parties.append((platform_id, "buyer", None, buyer_lead))
        else:
            parties.append((self.fund_sponsor[buyer_fund], "buyer", buyer_fund, buyer_lead))
        if seller_fund is not None:
            parties.append((self.fund_sponsor[seller_fund], "seller", seller_fund, seller_lead))
            seller_type = "sponsor"
            for o in self.t["OWNERSHIP"]:
                if o["company_id"] == target_id and o["fund_id"] == seller_fund and o["end_date"] is None:
                    o["end_date"] = d(close) if isinstance(close, str) else close
        for adv in advisors:
            org, prole, lead = (adv + (None,))[:3] if len(adv) == 2 else adv
            parties.append((org, prole, None, lead))
        tid = self.txn(target_id, close, deal_role, seller_type, structure, parties, rng=rng)
        if deal_role == "platform" and structure in ("control_buyout", "majority_recap"):
            self.own(target_id, buyer_fund, close, equity=equity,
                     stake="majority")
        elif deal_role == "platform" and structure == "minority":
            self.own(target_id, buyer_fund, close, equity=equity, stake="minority")
        return tid

    def link(self, supplier, customer, band="1-5M", since=None, rng=None):
        rng = rng or self.rng
        lid = self.ids.next("L")
        self.t["COMMERCIAL_LINK"].append({"link_id": lid, "supplier_id": supplier, "customer_id": customer,
                                          "value_band": band, "since_year": since or rng.randint(2012, 2024)})
        return lid

    def crm(self, our, when, channel, sentiment, person=None, org=None):
        xid = self.ids.next("X")
        org_type = ORG_TYPE[org.rstrip("0123456789")] if org else None
        self.t["CRM_INTERACTION"].append({"interaction_id": xid, "our_person_id": our,
                                          "counterparty_person_id": person, "counterparty_org_id": org,
                                          "counterparty_org_type": org_type,
                                          "interaction_date": d(when) if isinstance(when, str) else when,
                                          "channel": channel, "sentiment": sentiment})
        return xid

    def pipe(self, company_id, stage, added, owner, check):
        self.t["PIPELINE"].append({"company_id": company_id, "stage": stage, "added_date": d(added),
                                   "owner_person_id": owner, "est_equity_check_musd": check})

    def signal(self, company_id, stype, when, event=None, interm=None, magnitude=None):
        gid = self.ids.next("G")
        self.t["COMPANY_SIGNAL"].append({"signal_id": gid, "company_id": company_id, "signal_type": stype,
                                         "signal_date": d(when), "event_date": d(event) if event else None,
                                         "intermediary_id": interm, "magnitude_musd": magnitude})
        return gid


def build_reference(w: World):
    """Sector tree (3 levels) and region tree (country > census region > state/province)."""
    for l1, subs in SECTOR_TREE.items():
        s1 = w.ids.next("SC")
        w.t["SECTOR"].append({"sector_id": s1, "name": l1, "level": 1, "parent_id": None})
        w.sector_id[l1], w.sector_parent[s1], w.sector_name[s1] = s1, None, l1
        for l2, niches in subs.items():
            s2 = w.ids.next("SC")
            w.t["SECTOR"].append({"sector_id": s2, "name": l2, "level": 2, "parent_id": s1})
            w.sector_id[l2], w.sector_parent[s2], w.sector_name[s2] = s2, s1, l2
            for l3 in niches:
                s3 = w.ids.next("SC")
                w.t["SECTOR"].append({"sector_id": s3, "name": l3, "level": 3, "parent_id": s2})
                w.sector_id[l3], w.sector_parent[s3], w.sector_name[s3] = s3, s2, l3
    reg = w.t["REGION"]
    reg.append({"region_id": "US", "name": "United States", "level": 1, "region_type": "country", "parent_id": None})
    for code, name in [("NORTHEAST", "Northeast"), ("MIDWEST", "Midwest"), ("SOUTH", "South"), ("WEST", "West")]:
        reg.append({"region_id": f"US-{code}", "name": name, "level": 2, "region_type": "census_region",
                    "parent_id": "US"})
    for code, (name, cr) in US_STATES.items():
        reg.append({"region_id": f"US-{code}", "name": name, "level": 3, "region_type": "state",
                    "parent_id": f"US-{cr}"})
    reg.append({"region_id": "CA", "name": "Canada", "level": 1, "region_type": "country", "parent_id": None})
    reg.append({"region_id": "CA-CENTRAL", "name": "Central Canada", "level": 2, "region_type": "census_region",
                "parent_id": "CA"})
    reg.append({"region_id": "CA-ON", "name": "Ontario", "level": 3, "region_type": "province", "parent_id": "CA-CENTRAL"})
    reg.append({"region_id": "CA-QC", "name": "Quebec", "level": 3, "region_type": "province", "parent_id": "CA-CENTRAL"})


# =====================================================================================
# 3. SIGNAL SECTION (QUESTIONS.md v2)
#    Shared cast first, then one planting function per question ID (STORIES registry).
#    Every hero-visible name below was collision-checked (see handoffs/07-R05-a1.md).
# =====================================================================================

HERO_NAMES = {
    # Q-SCORE cast
    "T_BANKER": "Larkspur Revenue Partners",
    "T_WARM": "Bayside Pediatric Therapy Group",
    "T_COLD": "Saltmarsh Home Infusion",
    "CONF": "Tessmark Clinical Supply",            # replaces R03 placeholder "Keystone Clinical Supply"
    "T_5": "Quarry Records Retrieval",
    "T_6": "Fenwick Food Safety Labs",
    "NM_B": "Ashby Vale Dental Partners",          # replaces "Alder Creek Dental Partners" (real practice)
    "D_VET": "Pembrook Veterinary Pharmaceuticals",
    "D_BIG": "Northgate Behavioral Health",
    "D_SHORT": "Cobalt Urgent Care Partners",
    "D_SNF": "Linden Hollow Senior Care",
    # Portfolio, conflict and path context
    "BRIGHT": "Cobbleton Dental Group",            # replaces "Brightwater Dental" (real practice)
    "PINE": "Pinewick Dermatology Partners",       # replaces "Pinecrest Dental Partners" (close real match); R20: not dental, so no DSO lookalike of NM_B (R19a B2)
    "REDFERN": "Redfern Imaging Centers",
    "GRANITE": "Ironvale Testing Group",           # replaces "Granite Testing Group"
    "MEADOW": "Quillmont Physical Therapy",        # replaces "Meadowbrook Physical Therapy" (generic, likely real)
    "DIST1": "Tullmere Chemical Distribution",     # replaces "Tidewater Chemical Distribution"
    "DIST2": "Flintmoor Industrial Supply",        # replaces "Juniper Industrial Supply"
    "DIST3": "Primdale Ingredients Co",            # replaces "Sable Ingredients Co" (clashed with Sablewood)
    "C07": "Ravenholt Engineering Group",          # replaces "Bluestem Engineering Group"
    "H1": "Carrowmere Community Hospital",         # replaces "Ashby Community Hospital" (clashed with NM_B)
    "H2": "Wexley Medical Linen",                  # replaces "Fairmont Medical Linen"
    "A1": "Fernhollow Environmental Labs",         # replaces "Clearwater Environmental Labs" (close real match)
    "A2": "Tollbridge NDT Services",               # replaces "Ridgeline NDT Services"
    "A3": "Merrow Calibration",                    # replaces "Summit Calibration Co"
    "D_SAME": "Shalecrest Materials Testing",      # replaces "Bedrock Materials Testing"
    "MERIDIAN": "Varnell Lab Services",            # replaces "Meridian Lab Services"
    "OLDHARBOR": "Oldmere Health System",          # replaces "Old Harbor Health"
    "LAKEMONT": "Lakeholm Orthodontics",           # replaces "Lakemont Orthodontics"
    # Sponsors
    "NW": "Northwind Equity Partners",             # CONFIG CUSTOMER_DISPLAY_NAME
    "IRONBRIDGE": "Kestrelmoor Capital",           # replaces "Ironbridge Capital" (real PE firm)
    "COPPERLINE": "Coppervale Partners",           # replaces "Copperline Partners" (real investment firm)
    "TAMARACK": "Sablewood Equity",                # replaces "Tamarack Equity" (real fund family name)
    "RIDGEBACK": "Ridgeback Partners",
    "ASHGROVE": "Glenhallow Partners",             # replaces "Ashgrove Partners"
    # Intermediaries
    "HL": "Harbor Lane Advisors",
    "CEDAR": "Cedar Row Partners",
    "BIGBANK": "Brayford Capital Markets",         # replaces "Continental Capital Markets"
    "LAKESHORE": "Kellbrook Securities",           # replaces "Lakeshore Securities"
    # People
    "OP": "Marcus Whitfield", "MP": "Dana Okafor", "VP": "Priya Raman",
    "MD_MER": "Tom Harlowe",                       # replaces "Tom Brennan" (real PE executive)
    "OP2": "Grace Liu", "EX_NW": "Harold Becker",
    "CFO_W": "Elena Marsh", "CEO_W": "Daniel Reyes", "X_STALE": "Walter Kim",
    "Y_BANK": "Sofia Brandt", "B_BANK": "Nathan Cole", "CEO_B": "Ruth Adeyemi",
    "OWN_B": "Owen Lacey", "IB_LEAD": "Martin Greer", "CEO_C": "Victor Hale", "OWN_C": "Graham Pike",
    "HL_MD": "Celia Navarro", "RAFAEL": "Rafael Ortiz",
    "Z": "Lucas Ferreira", "CEO_NMB": "Lydia Okoro",
    "DIR_CONF": "Helen Voss", "DIR_NMB": "Iris Calloway",
}


def plant_shared_cast(w: World):
    """Northwind, its funds and people (OUR_SEEDS), the competitor sponsors and banks that recur
    across questions, and the seven Q-SCORE cast companies with their senior teams and owners.
    Facts used by more than one question live here so a single question can be swapped."""
    H = HERO_NAMES
    rng = random.Random(f"{w.seed}-cast")
    nw = w.sponsor("NW", H["NW"], "IL", 2500.0)
    w.fund("NW_F2", nw, "Northwind Equity Partners Fund II", 2014, 650.0)
    w.fund("NW_F3", nw, "Northwind Equity Partners Fund III", 2019, 900.0)
    w.fund("NW_F4", nw, "Northwind Equity Partners Fund IV", 2023, 1200.0, guideline=35.0)

    # OUR_SEEDS: current Northwind Deal Team / Operating Partner roles.
    for key, rtype, title, start in [("MP", "Deal Team", "Managing Partner", "2009-01-05"),
                                     ("MD_MER", "Deal Team", "Managing Director", "2012-09-04"),
                                     ("VP", "Deal Team", "Partner", "2017-02-01"),
                                     ("OP", "Operating Partner", "Operating Partner", "2014-09-02"),
                                     ("OP2", "Operating Partner", "Operating Partner", "2020-09-14")]:
        p = w.person(key, H[key])
        w.role(p, nw, rtype, start, title=title)
    ex = w.person("EX_NW", H["EX_NW"])  # former partner: not a seed
    w.role(ex, nw, "Deal Team", "2006-01-09", "2021-03-31", title="Partner")

    # Competitor sponsors that own cast companies.
    kb = w.sponsor("IRONBRIDGE", H["IRONBRIDGE"], "MA", 1100.0)
    w.fund("KB_F1", kb, "Kestrelmoor Capital Fund I", 2016, 420.0)
    w.fund("KB_F2", kb, "Kestrelmoor Capital Fund II", 2021, 610.0)
    cv = w.sponsor("COPPERLINE", H["COPPERLINE"], "TN", 950.0)
    w.fund("CV_F2", cv, "Coppervale Partners Fund II", 2017, 380.0)
    w.fund("CV_F3", cv, "Coppervale Partners Fund III", 2022, 540.0)
    sw = w.sponsor("TAMARACK", H["TAMARACK"], "MN", 800.0)
    w.fund("SW_F2", sw, "Sablewood Equity Fund II", 2015, 310.0)
    w.fund("SW_F3", sw, "Sablewood Equity Fund III", 2021, 450.0)
    rb = w.sponsor("RIDGEBACK", H["RIDGEBACK"], "NY", 1600.0, "middle_market_buyout")
    w.fund("RB_F3", rb, "Ridgeback Partners Fund III", 2019, 780.0)
    gh = w.sponsor("ASHGROVE", H["ASHGROVE"], "GA", 1300.0)
    w.fund("GH_F4", gh, "Glenhallow Partners Fund IV", 2022, 700.0)

    # Recurring intermediaries and their bankers.
    w.intermediary("CEDAR", H["CEDAR"], "boutique", "IL")
    w.intermediary("HL", H["HL"], "boutique", "TN")
    w.intermediary("BIGBANK", H["BIGBANK"], "large_bank", "NY")
    w.intermediary("LAKESHORE", H["LAKESHORE"], "regional_bank", "OH")
    adv_old = w.intermediary("ADV_OLD", f"{w.coined(rng)} Advisors", "boutique", "MO")
    hl_md = w.person("HL_MD", H["HL_MD"]); w.role(hl_md, w.k("HL"), "Banker", "2012-04-02", title="Managing Director")
    b_bank = w.person("B_BANK", H["B_BANK"])
    w.role(b_bank, w.k("CEDAR"), "Banker", "2014-05-01", title="Managing Director")
    yb = w.person("Y_BANK", H["Y_BANK"])
    w.role(yb, w.k("LAKESHORE"), "Banker", "2012-06-04", "2016-12-16", title="Vice President")
    w.role(yb, w.k("CEDAR"), "Banker", "2017-01-09", title="Director")

    # ---- Q-SCORE cast companies (section 2 of QUESTIONS.md) ----
    w.company("T_BANKER", H["T_BANKER"], "Healthcare Revenue Cycle Services", "TX", 130.0, 26.0, founded=2005,
              sites=["OK", "LA"])
    w.company("T_WARM", H["T_WARM"], "Pediatric Therapy Clinics", "FL", 140.0, 22.0, founded=2008,
              sites=["GA", "AL"])
    w.company("T_COLD", H["T_COLD"], "Home Infusion Services", "NC", 115.0, 18.0, founded=2002,
              sites=["SC", "VA"])
    w.company("CONF", H["CONF"], "Medical & Lab Supply Distribution", "OH", 140.0, 14.0, founded=1999,
              sites=["IN", "KY", "MI"])
    w.company("T_5", H["T_5"], "Records Retrieval & Litigation Support", "PA", 42.0, 8.5, founded=2009,
              sites=["NJ"])
    w.company("T_6", H["T_6"], "Food Safety Testing", "WI", 66.0, 12.0, founded=1996, sites=["IL", "MN"])
    w.company("NM_B", H["NM_B"], "Dental Service Organizations", "AZ", 100.0, 16.0, founded=2006, sites=["NV"])

    # Senior teams of the cast (tenure and succession facts, never age).
    k = w.k
    p = w.person("CEO_B", H["CEO_B"]); w.role(p, k("T_BANKER"), "CEO", "2005-03-01", title="Founder and CEO", founder=True)
    p = w.person("COO_B"); w.role(p, k("T_BANKER"), "COO", "2020-02-03", title="Chief Operating Officer")
    w.role(p, k("ASHGROVE"), "Operating Partner", "2014-03-03", "2019-11-29", title="Operating Partner")
    p = w.person("CEO_W", H["CEO_W"]); w.role(p, k("T_WARM"), "CEO", "2008-01-01", title="Founder and CEO", founder=True)
    p = w.person("CEO_C", H["CEO_C"]); w.role(p, k("T_COLD"), "CEO", "2020-11-02", title="Chief Executive Officer")
    p = w.person("CEO_CONF"); w.role(p, k("CONF"), "CEO", "1999-05-01", title="Founder and CEO", founder=True)
    p = w.person("CFO_CONF"); w.role(p, k("CONF"), "CFO", "2016-04-04", title="Chief Financial Officer")
    p = w.person("CEO_T5"); w.role(p, k("T_5"), "CEO", "2009-09-01", title="Founder and CEO", founder=True)
    p = w.person("CEO_T6"); w.role(p, k("T_6"), "CEO", "2021-01-04", title="Chief Executive Officer")
    p = w.person("CEO_NMB", H["CEO_NMB"]); w.role(p, k("NM_B"), "CEO", "2006-03-01", title="Founder and CEO", founder=True)

    # CFO hires. T_BANKER, T_COLD and T_5 hired from sponsor-backed companies (R_CFO_FROM_PE);
    # NM_B hired from a founder-owned company (no ownership rows): the temporal join rejects it.
    cfo_specs = [  # key, company, cfo start, prior niche, prior start, prior end, owner fund key, own start, own end
        ("CFO_B", "T_BANKER", "2025-07-01", "Payroll & HR Outsourcing", "2019-03-04", "2025-05-30", "KB_F2", "2021-08-16", None),
        ("CFO_C", "T_COLD", "2025-11-03", "Hospice Providers", "2021-01-11", "2025-09-26", "RB_F3", "2020-05-11", None),
        ("CFO_T5", "T_5", "2025-05-05", "Insurance Claims Processing", "2018-09-04", "2025-04-11", "GH_F4", "2022-07-01", None),
        ("CFO_NMB", "NM_B", "2025-05-12", "Physical Therapy Clinics", "2021-02-01", "2025-04-25", None, None, None),
    ]
    for key, ckey, start, niche, pstart, pend, fkey, ostart, oend in cfo_specs:
        prior = w.filler_company(niche, rng, ebitda=round(rng.uniform(9, 30), 1))
        if fkey:
            w.own(prior, k(fkey), ostart, oend)
        p = w.person(key)
        w.role(p, prior, "CFO", pstart, pend, title="Chief Financial Officer")
        w.role(p, k(ckey), "CFO", start, title="Chief Financial Officer")

    # T_WARM's CFO came from Cobbleton Dental Group (BRIGHT), a former Northwind Fund II company.
    bright = w.company("BRIGHT", H["BRIGHT"], "Dental Service Organizations", "MO", 300.0, 45.0,
                       founded=1994, sites=["KS", "IL", "IA"])
    p = w.person("CFO_W", H["CFO_W"])
    w.role(p, bright, "CFO", "2015-03-01", "2025-04-30", title="Chief Financial Officer")
    w.role(p, k("T_WARM"), "CFO", "2025-06-01", title="Chief Financial Officer")
    p = w.person("CEO_BRIGHT"); w.role(p, bright, "CEO", "2011-04-04", title="Chief Executive Officer")
    rb_lead = w.person("RB_LEAD"); w.role(rb_lead, k("RIDGEBACK"), "Deal Team", "2011-06-06", title="Partner")
    w.role(rb_lead, bright, "Board", "2020-02-14", title="Director")
    # Northwind's lead on both Brightwater deals is the former partner EX_NW (no seed K2 edge to CFO_W).
    w.buyout(bright, "2014-06-30", k("NW_F2"), advisors=[(adv_old, "sell_side_advisor")], buyer_lead=ex,
             equity=118.0, rng=rng)
    w.buyout(bright, "2020-02-14", k("RB_F3"), advisors=[(adv_old, "sell_side_advisor")], seller_fund=k("NW_F2"),
             seller_lead=ex, buyer_lead=rb_lead, equity=205.0, rng=rng)

    # Kestrelmoor (owner of T_BANKER): IB_LEAD led the 2019 recap and left in 2021; OWN_B is the
    # current board designee and was not a lead person on the recap.
    ib = w.person("IB_LEAD", H["IB_LEAD"])
    w.role(ib, k("IRONBRIDGE"), "Deal Team", "2010-03-01", "2021-05-31", title="Partner")
    w.role(ib, k("T_BANKER"), "Board", "2019-04-15", "2021-05-31", title="Director")
    ob = w.person("OWN_B", H["OWN_B"])
    w.role(ob, k("IRONBRIDGE"), "Deal Team", "2012-01-09", title="Partner")
    w.role(ob, k("T_BANKER"), "Board", "2021-06-01", title="Director")
    w.buyout(k("T_BANKER"), "2019-04-15", k("KB_F1"), advisors=[(k("CEDAR"), "sell_side_advisor", b_bank)],
             structure="majority_recap", buyer_lead=ib, equity=96.0, rng=rng)

    # Coppervale (owner of T_COLD): OWN_C is the board designee and the lead on the 2020 buy.
    oc = w.person("OWN_C", H["OWN_C"])
    w.role(oc, k("COPPERLINE"), "Deal Team", "2014-06-02", title="Partner")
    w.role(oc, k("T_COLD"), "Board", "2020-09-01", title="Director")
    w.buyout(k("T_COLD"), "2020-09-01", k("CV_F2"), advisors=[(adv_old, "sell_side_advisor")],
             buyer_lead=oc, equity=74.0, rng=rng)

    sw_lead = w.person("SW_LEAD"); w.role(sw_lead, k("TAMARACK"), "Deal Team", "2009-03-02", title="Partner")
    w.role(sw_lead, k("T_6"), "Board", "2020-06-30", title="Director")
    w.buyout(k("T_6"), "2020-06-30", k("SW_F2"), advisors=[], buyer_lead=sw_lead, equity=41.0, rng=rng)


# ---------------------------------------------------------------------------------------
# Q-SCORE (rules, Act 1)
# ---------------------------------------------------------------------------------------
def plant_q_score(w: World):
    """Fund IV thesis tree, every cast signal row (v2 table), new directors, org-level CRM access,
    pipeline; decoys D_VET, D_SNF, D_BIG (near-miss), D_SHORT."""
    H, k = HERO_NAMES, w.k
    rng = random.Random(f"{w.seed}-qscore")
    f4 = k("NW_F4")
    for sector, mode, bench in [("Healthcare Services", "include", 14.0),
                                ("Tech-Enabled Business Services", "include", 18.0),
                                ("Testing, Inspection & Certification", "include", 17.0),
                                ("Specialty Distribution", "include", 9.0),
                                ("Skilled Nursing Facilities", "exclude", None)]:
        w.t["FUND_FOCUS"].append({"fund_id": f4, "sector_id": w.sector_id[sector], "mode": mode,
                                  "margin_benchmark_pct": bench})
    for sector, bench in [("Healthcare Services", 14.0), ("Specialty Distribution", 9.0)]:
        w.t["FUND_FOCUS"].append({"fund_id": k("NW_F3"), "sector_id": w.sector_id[sector], "mode": "include",
                                  "margin_benchmark_pct": bench})

    # Context boutiques for BANKER_ENGAGED rows without a named intermediary (never HL, CEDAR, BIGBANK).
    ctx = [w.intermediary(f"CTX{i}", f"{w.coined(rng)} {s}", t, st) for i, (s, t, st) in
           enumerate([("Capital Advisors", "boutique", "FL"), ("Securities", "regional_bank", "OH"),
                      ("Partners", "boutique", "WI")], start=1)]

    S = w.signal
    S(k("T_BANKER"), "BANKER_ENGAGED", "2026-08-10", interm=k("CEDAR"))
    S(k("T_BANKER"), "DEBT_MATURITY", "2026-02-15", event="2027-09-30", magnitude=85.0)
    S(k("T_WARM"), "BANKER_ENGAGED", "2026-05-15", interm=ctx[0])
    S(k("T_WARM"), "DEBT_MATURITY", "2026-01-20", event="2027-06-30", magnitude=60.0)
    S(k("T_COLD"), "BANKER_ENGAGED", "2026-07-14", interm=k("HL"))
    S(k("T_COLD"), "DEBT_MATURITY", "2026-03-10", event="2027-12-31", magnitude=70.0)
    S(k("T_5"), "DEBT_MATURITY", "2026-04-22", event="2027-03-31", magnitude=22.0)
    S(k("CONF"), "BANKER_ENGAGED", "2026-06-02", interm=k("CEDAR"))
    S(k("CONF"), "DEBT_MATURITY", "2025-11-05", event="2028-02-28", magnitude=40.0)
    S(k("T_6"), "BANKER_ENGAGED", "2026-09-08", interm=ctx[2])
    S(k("T_6"), "DEBT_MATURITY", "2026-02-02", event="2027-08-15", magnitude=35.0)
    S(k("NM_B"), "BANKER_ENGAGED", "2026-07-29", interm=ctx[1])
    S(k("NM_B"), "DEBT_MATURITY", "2026-05-06", event="2027-11-30", magnitude=45.0)

    # New independent directors (R_NEW_DIRECTOR).
    rafael = w.person("RAFAEL", H["RAFAEL"])
    w.role(rafael, k("ASHGROVE"), "Operating Partner", "2012-10-01", title="Operating Partner")
    w.role(rafael, k("T_5"), "Board", "2026-03-16", title="Director")
    p = w.person("ND_T6"); w.role(p, k("T_6"), "Board", "2026-01-20", title="Independent Director")
    p = w.person("DIR_CONF", H["DIR_CONF"]); w.role(p, k("CONF"), "Board", "2026-02-17", title="Independent Director")
    p = w.person("DIR_NMB", H["DIR_NMB"]); w.role(p, k("NM_B"), "Board", "2026-03-02", title="Independent Director")

    # Access: org-level CRM touches only (no Knows edge), pipeline rows.
    mp, vp, md, op = k("MP"), k("VP"), k("MD_MER"), k("OP")
    w.crm(vp, "2026-05-20", "meeting", "positive", org=k("T_BANKER"))
    w.crm(mp, "2026-03-12", "meeting", "positive", org=k("T_WARM"))
    w.crm(vp, "2025-12-04", "call", "positive", org=k("T_5"))
    w.crm(md, "2026-06-10", "meeting", "positive", org=k("CONF"))
    w.crm(op, "2023-02-10", "call", "neutral", org=k("NM_B"))
    w.pipe(k("T_BANKER"), "Contacted", "2024-06-18", vp, 70.0)
    w.pipe(k("T_WARM"), "Engaged", "2025-09-08", mp, 95.0)
    w.pipe(k("CONF"), "IOI prep", "2022-11-30", md, 55.0)
    w.pipe(k("T_5"), "Contacted", "2025-12-04", vp, 35.0)
    w.pipe(k("NM_B"), "Tracking", "2023-01-16", op, 60.0)

    # ---- Decoys ----
    dvet = w.company("D_VET", H["D_VET"], "Veterinary Pharmaceuticals", "NE", 88.0, 15.0, founded=1988, sites=["IA"])
    S(dvet, "BANKER_ENGAGED", "2026-06-20", interm=ctx[1])
    S(dvet, "DEBT_MATURITY", "2026-01-12", event="2027-10-31", magnitude=30.0)
    S(dvet, "PRESS_RELEASE", "2026-02-09")
    S(dvet, "AWARD", "2026-08-25")
    p = w.person(None); w.role(p, dvet, "CEO", "2004-02-02", title="Founder and CEO", founder=True)

    dsnf = w.company("D_SNF", H["D_SNF"], "Skilled Nursing Facilities", "PA", 150.0, 12.0, founded=2001, sites=["OH"])
    S(dsnf, "BANKER_ENGAGED", "2026-04-08", interm=ctx[1])
    S(dsnf, "DEBT_MATURITY", "2026-03-01", event="2027-05-31", magnitude=55.0)
    S(dsnf, "HIRING_SURGE", "2026-06-10")
    p = w.person(None); w.role(p, dsnf, "CEO", "2001-03-05", title="Founder and CEO", founder=True)

    dbig = w.company("D_BIG", H["D_BIG"], "Behavioral Health Clinics", "CO", 290.0, 44.0, founded=1997,
                     sites=["UT", "NM", "AZ"])
    S(dbig, "BANKER_ENGAGED", "2026-05-01", interm=ctx[0])
    S(dbig, "DEBT_MATURITY", "2026-02-20", event="2027-04-30", magnitude=150.0)
    S(dbig, "PRESS_RELEASE", "2026-03-15")
    S(dbig, "AWARD", "2026-07-01")
    p = w.person(None); w.role(p, dbig, "CEO", "1997-06-02", title="Founder and CEO", founder=True)
    prior = w.filler_company("Healthcare Staffing", rng, ebitda=18.0)
    w.own(prior, k("RB_F3"), "2021-03-01")
    p = w.person(None)
    w.role(p, prior, "CFO", "2019-01-07", "2025-12-19", title="Chief Financial Officer")
    w.role(p, dbig, "CFO", "2026-02-02", title="Chief Financial Officer")
    p = w.person(None); w.role(p, dbig, "Board", "2026-02-23", title="Independent Director")

    # D_SHORT: thesis niche, a sponsor fund (vintage 2021) bought it 2025-04-01; five unscored signals;
    # no PIPELINE row and no CRM interaction.
    sh_name = f"{w.coined(rng)} Capital"
    sh = w.sponsor("SHORT_SP", sh_name, "TX", 1400.0, "middle_market_buyout")
    shf = w.fund("SHORT_F", sh, f"{sh_name} Fund II", 2021, 650.0)
    dshort = w.company("D_SHORT", H["D_SHORT"], "Urgent Care Clinics", "TX", 125.0, 20.0, founded=2011, sites=["OK"])
    p = w.person(None); w.role(p, dshort, "CEO", "2025-05-12", title="Chief Executive Officer")
    adv_short = w.intermediary("ADV_SHORT", f"{w.coined(rng)} & Co.", "boutique", "TX")
    w.buyout(dshort, "2025-04-01", shf, advisors=[(adv_short, "sell_side_advisor")], equity=88.0, rng=rng)
    for stype, when in [("ADDON_ANNOUNCED", "2025-11-18"), ("ADDON_ANNOUNCED", "2026-03-03"),
                        ("ADDON_ANNOUNCED", "2026-07-21"), ("DEBT_REFINANCED", "2026-05-14"),
                        ("PRESS_RELEASE", "2026-08-05")]:
        S(dshort, stype, when)

    w.golden["Q-SCORE"] = {
        "question": "Which companies fit the Fund IV thesis and look ready to transact in the next 12-18 months, and why each one?",
        "tier_a_ranked": [
            {"rank": 1, "key": "T_BANKER", "score": 90, "fit": 30, "readiness": 50, "access": 10,
             "components": {"FIT_THESIS": 15, "FIT_EBITDA": 10, "FIT_MARGIN": 5, "R_CFO_FROM_PE": 15,
                            "R_EXIT_WINDOW": 15, "R_BANKER": 10, "R_DEBT": 10, "A_CRM": 10}},
            {"rank": 2, "key": "T_WARM", "score": 85, "fit": 30, "readiness": 45, "access": 10,
             "components": {"FIT_THESIS": 15, "FIT_EBITDA": 10, "FIT_MARGIN": 5, "R_CFO_FROM_PE": 15,
                            "R_BANKER": 10, "R_DEBT": 10, "R_SUCCESSION": 10, "A_CRM": 10}},
            {"rank": 3, "key": "T_COLD", "score": 80, "fit": 30, "readiness": 50, "access": 0,
             "components": {"FIT_THESIS": 15, "FIT_EBITDA": 10, "FIT_MARGIN": 5, "R_CFO_FROM_PE": 15,
                            "R_EXIT_WINDOW": 15, "R_BANKER": 10, "R_DEBT": 10}},
            {"rank": 4, "key": "T_5", "score": 75, "fit": 25, "readiness": 40, "access": 10,
             "components": {"FIT_THESIS": 15, "FIT_EBITDA": 5, "FIT_MARGIN": 5, "R_CFO_FROM_PE": 15,
                            "R_DEBT": 10, "R_SUCCESSION": 10, "R_NEW_DIRECTOR": 5, "A_CRM": 10}},
            {"rank": 5, "key": "CONF", "score": 75, "fit": 30, "readiness": 35, "access": 10,
             "components": {"FIT_THESIS": 15, "FIT_EBITDA": 10, "FIT_MARGIN": 5, "R_BANKER": 10,
                            "R_DEBT": 10, "R_SUCCESSION": 10, "R_NEW_DIRECTOR": 5, "A_CRM": 10}},
            {"rank": 6, "key": "T_6", "score": 70, "fit": 30, "readiness": 40, "access": 0,
             "components": {"FIT_THESIS": 15, "FIT_EBITDA": 10, "FIT_MARGIN": 5, "R_EXIT_WINDOW": 15,
                            "R_BANKER": 10, "R_DEBT": 10, "R_NEW_DIRECTOR": 5}},
        ],
        "not_in_crm": ["T_COLD", "T_6"],
        "tier_b_reference": [{"key": "NM_B", "score": 65, "fit": 30, "readiness": 35, "access": 0,
                              "components": {"FIT_THESIS": 15, "FIT_EBITDA": 10, "FIT_MARGIN": 5, "R_BANKER": 10,
                                             "R_DEBT": 10, "R_SUCCESSION": 10, "R_NEW_DIRECTOR": 5},
                              "near_misses": ["R_CFO_FROM_PE (prior employer founder-owned)",
                                              "A_CRM (last touch 2023-02-10 neutral)"]}],
        "ineligible_reference": [{"key": "D_BIG", "reason": "EBITDA 44.0 above the 40.0 band"},
                                 {"key": "BRIGHT", "reason": "EBITDA 45.0 above the 40.0 band"},
                                 {"key": "D_VET", "reason": "niche Veterinary Pharmaceuticals outside the Fund IV thesis tree"},
                                 {"key": "D_SNF", "reason": "niche Skilled Nursing Facilities is excluded from the Fund IV thesis"}],
        "d_short_reference": {"key": "D_SHORT", "score": 30, "tier": "C",
                              "why_not": "5 signals in the last 12 months, none a scored readiness type (ADDON_ANNOUNCED x3, DEBT_REFINANCED, PRESS_RELEASE); sponsor-owned since 2025-04-01 (1.5 years)"},
        "naive_screen": {
            "keywords": NAIVE_KEYWORDS,
            "cast_order_top8": ["D_SHORT", "D_VET", "D_SNF", "NM_B", "T_WARM", "T_6", "T_BANKER", "CONF"],
            "missed_tier_a": ["T_COLD", "T_5"],
            "excluded_by_band": ["D_BIG", "BRIGHT"],
            "note": "2-signal ties order by name asc; with the final names CONF (Tessmark) sorts after T_BANKER (Larkspur)",
        },
        "tie_break": "score desc, readiness desc, fit desc, name asc",
        "must_not_contain": ["D_VET", "D_SNF", "D_BIG", "D_SHORT", "NM_B", "D_SAME", "A1", "BRIGHT"],
    }


# ---------------------------------------------------------------------------------------
# Q-PATH (graph + rules, Act 2)
# ---------------------------------------------------------------------------------------
def plant_q_path(w: World):
    """Tenure overlaps, the 14 Cedar Row touchpoints, the Varnell decoy and the stale tie (v2)."""
    H, k = HERO_NAMES, w.k
    rng = random.Random(f"{w.seed}-qpath")
    # T_WARM: OP -[Cobbleton overlap]- CFO_W -[T_WARM overlap]- CEO_W  (CFO_W roles in shared cast)
    w.role(k("OP"), k("BRIGHT"), "Board", "2014-09-15", "2019-06-30", title="Director")
    # Stale alternate: MP and X_STALE at Oldmere 1998-2000; X_STALE on the T_WARM board since 2023.
    oldm = w.company("OLDHARBOR", H["OLDHARBOR"], "Community Hospitals", "MA", 610.0, 95.0, founded=1962,
                     sites=["NH", "RI"], is_public=True)
    w.role(k("MP"), oldm, "CFO", "1998-03-01", "2000-06-30", title="Chief Financial Officer")
    xs = w.person("X_STALE", H["X_STALE"])
    w.role(xs, oldm, "COO", "1997-01-06", "2001-12-14", title="Chief Operating Officer")
    w.role(xs, k("T_WARM"), "Board", "2023-01-15", title="Director")
    # T_BANKER: VP -[Kellbrook overlap + 7 positive meetings]- Y_BANK -[Cedar Row]- B_BANK -[2019 recap]- CEO_B
    w.role(k("VP"), k("LAKESHORE"), "Banker", "2011-07-01", "2016-06-30", title="Associate")
    # Cedar Row: all 14 touchpoints in [T-24m, T]. 10 person-level VP <-> Y_BANK (7 positive, 3 neutral),
    # 4 org-level neutral (2 MP coverage reviews, 2 MD_MER conferences).
    vp_dates = ["2024-11-14", "2025-01-22", "2025-03-18", "2025-05-07", "2025-06-26", "2025-09-10",
                "2025-11-19", "2026-02-04", "2026-05-13", "2026-09-02"]
    vp_sent = ["positive", "neutral", "positive", "positive", "neutral", "positive", "positive", "neutral",
               "positive", "positive"]
    for dd, sn in zip(vp_dates, vp_sent):
        w.crm(k("VP"), dd, "meeting", sn, person=k("Y_BANK"))
    w.crm(k("MP"), "2025-02-11", "meeting", "neutral", org=k("CEDAR"))
    w.crm(k("MP"), "2026-02-10", "meeting", "neutral", org=k("CEDAR"))
    w.crm(k("MD_MER"), "2025-04-29", "conference", "neutral", org=k("CEDAR"))
    w.crm(k("MD_MER"), "2026-04-28", "conference", "neutral", org=k("CEDAR"))
    # "We know the sponsor": one org-level neutral meeting with Coppervale.
    w.crm(k("MP"), "2025-03-04", "meeting", "neutral", org=k("COPPERLINE"))
    # Decoy: MD_MER and CEO_C both at Varnell Lab Services, never overlapping (613-day gap).
    mer = w.company("MERIDIAN", H["MERIDIAN"], "Clinical Laboratory Services", "OH", 330.0, 60.0, founded=1979,
                    sites=["IN", "PA"])
    w.role(k("MD_MER"), mer, "CFO", "2008-01-07", "2011-06-30", title="Chief Financial Officer")
    w.role(k("CEO_C"), mer, "COO", "2013-03-04", "2020-08-31", title="Chief Operating Officer")

    w.golden["Q-PATH"] = {
        "question": "For our top three, what is our warmest path to each CEO, and through whom? And if the company is sponsor-owned, do we know the owner's deal partner?",
        "rows": [
            {"target": "T_BANKER", "decision_maker": "CEO_B", "kind": "CEO", "hops": 3,
             "best_path": ["VP", "Y_BANK", "B_BANK", "CEO_B"],
             "hop_strengths": [1.0, 1.0, 0.7],
             "hop_evidence": ["K1 Kellbrook Securities 2012-06-04 to 2016-06-30 (0.70) and K3 7 positive meetings 2024-11 to 2026-09 (1.00); max 1.00",
                              "K1 Cedar Row Partners 2017-01-09 to present -> 1.00",
                              "K2 lead sell-side banker on the Larkspur majority recap closed 2019-04-15 while she was CEO -> 0.70"],
             "path_strength": 0.700, "alternates": []},
            {"target": "T_BANKER", "decision_maker": "OWN_B", "kind": "OWNER_DESIGNEE", "hops": None,
             "cold": True, "min_seed_distance": ">=4"},
            {"target": "T_WARM", "decision_maker": "CEO_W", "kind": "CEO", "hops": 2,
             "best_path": ["OP", "CFO_W", "CEO_W"], "hop_strengths": [1.0, 0.6],
             "hop_evidence": ["K1 tenure overlap Cobbleton Dental Group 2015-03-01 to 2019-06-30 -> 1.00",
                              "K1 tenure overlap Bayside Pediatric Therapy Group 2025-06-01 to present -> 0.60"],
             "path_strength": 0.600,
             "alternates": [{"path": ["MP", "X_STALE", "CEO_W"], "hop_strengths": [0.3, 0.956],
                             "path_strength": 0.287, "rank": 2}]},
            {"target": "T_COLD", "decision_maker": "CEO_C", "kind": "CEO", "hops": None, "cold": True,
             "min_seed_distance": ">=4"},
            {"target": "T_COLD", "decision_maker": "OWN_C", "kind": "OWNER_DESIGNEE", "hops": None, "cold": True,
             "min_seed_distance": ">=4"},
        ],
        "closest_intermediary": {"target": "T_COLD", "intermediary": "HL",
                                 "ties": ["BANKER_ENGAGED 2026-07-14", "debt_advisor on dividend recap 2023-05-18"]},
        "cedar_touchpoints_24m": {"total": 14, "person_level_vp_y_bank": 10, "positive": 7, "org_level": 4},
        "must_not_contain": ["MD_MER", "MERIDIAN"],
        "must_not_contain_note": "no path to CEO_C or OWN_C; no path via Varnell Lab Services; stale path never first; no T_BANKER alternate",
    }


# ---------------------------------------------------------------------------------------
# Portfolio context (Northwind holdings; used by Q-CONFLICT, Finale, Q-ADDON backup)
# ---------------------------------------------------------------------------------------
def plant_portfolio(w: World):
    """Fund III holdings (PINE, REDFERN, one exited) and the exact Fund IV holdings table (v2)."""
    H, k = HERO_NAMES, w.k
    rng = random.Random(f"{w.seed}-portfolio")
    f3, f4 = k("NW_F3"), k("NW_F4")
    pine = w.company("PINE", H["PINE"], "Dermatology Practices", "MO", 120.0, 17.5, founded=2001,
                     sites=["KS", "OK"])
    w.own(pine, f3, "2020-07-01", equity=88.0)
    p = w.person(None); w.role(p, pine, "CEO", "2016-05-02", title="Chief Executive Officer")
    w.role(k("MD_MER"), pine, "Board", "2020-07-01", title="Director")
    red = w.company("REDFERN", H["REDFERN"], "Diagnostic Imaging Centers", "KS", 78.0, 13.0, founded=2007,
                    sites=["MO"])
    w.own(red, f3, "2021-03-01", equity=64.0)
    p = w.person(None); w.role(p, red, "CEO", "2018-02-05", title="Chief Executive Officer")
    f3c = w.filler_company("Healthcare Staffing", rng, ebitda=11.0)
    w.own(f3c, f3, "2019-11-04", "2024-08-30", equity=52.0)
    # Fund IV: exactly five holdings, $645M deployed; Specialty Distribution 140 + 125 + 120 = 385 (32.1%).
    granite = w.company("GRANITE", H["GRANITE"], "Materials Testing", "TX", 96.0, 17.0, founded=2001,
                        sites=["OK", "LA", "AR"])
    p = w.person(None); w.role(p, granite, "CEO", "2001-06-01", title="Founder and CEO", founder=True)
    w.role(k("MP"), granite, "Board", "2024-03-15", title="Director")
    w.buyout(granite, "2024-03-15", f4, advisors=[(k("CEDAR"), "sell_side_advisor")], equity=150.0, rng=rng)
    for key, niche, eq, when, ebitda, rev, st in [
            ("MEADOW", "Physical Therapy Clinics", 110.0, "2023-09-12", 19.0, 128.0, "GA"),
            ("DIST1", "Specialty Chemicals Distribution", 140.0, "2023-11-01", 24.0, 260.0, "TX"),
            ("DIST2", "Industrial MRO Distribution", 125.0, "2024-08-20", 21.0, 245.0, "OH"),
            ("DIST3", "Specialty Food Ingredients Distribution", 120.0, "2025-06-02", 20.0, 230.0, "IL")]:
        c = w.company(key, H[key], niche, st, rev, ebitda, rng=rng)
        advs = [(k("CEDAR"), "sell_side_advisor")] if key == "DIST1" else []
        w.buyout(c, when, f4, advisors=advs, equity=eq, rng=rng)


# ---------------------------------------------------------------------------------------
# Q-CONFLICT (graph + rules, Act 4)
# ---------------------------------------------------------------------------------------
def plant_q_conflict(w: World):
    """CONF's commercial neighborhood: customers PINE, C07, H1, BRIGHT + 4 context; suppliers 2 context.
    PINE at 1 hop (Fund III conflict), GRANITE at 2 via C07, REDFERN at exactly 3, BRIGHT a former
    holding at 1. Needs PORTFOLIO and C07 (created here if Q-ADDON did not create it)."""
    H, k = HERO_NAMES, w.k
    rng = random.Random(f"{w.seed}-qconflict")
    conf = k("CONF")
    if "C07" not in w.key:
        w.company("C07", H["C07"], "Civil Engineering Services", "TX", 88.0, 9.5, founded=1991)
        w.link(k("GRANITE"), k("C07"), "1-5M", rng=rng)
    h1 = w.company("H1", H["H1"], "Community Hospitals", "IN", 420.0, 52.0, founded=1958)
    h2 = w.company("H2", H["H2"], "Healthcare Linen Services", "IN", 41.0, 6.0, founded=2004)
    w.link(conf, k("PINE"), "1-5M", since=2019)
    w.link(conf, k("C07"), "<1M", since=2021)
    w.link(conf, h1, "1-5M", since=2016)
    w.link(conf, k("BRIGHT"), "1-5M", since=2015)
    w.link(h2, h1, "<1M", since=2018)
    w.link(h2, k("REDFERN"), "<1M", since=2022)
    for niche in ["Dermatology Practices", "Urgent Care Clinics", "Contract Research Organizations", "Veterinary Clinics"]:
        c = w.filler_company(niche, rng, ebitda=round(rng.uniform(3.0, 4.8), 1))  # below band: no score
        w.link(conf, c, rng.choice(["<1M", "1-5M"]), rng=rng)
    for niche in ["Packaging Manufacturing", "Generic Pharmaceuticals"]:
        c = w.filler_company(niche, rng, ebitda=round(rng.uniform(8, 30), 1))
        w.link(c, conf, "5-20M", rng=rng)
    w.golden["Q-CONFLICT"] = {
        "question": "Before we bid on Tessmark Clinical Supply, does it conflict with anything we own, and would the deal push Fund IV over its sector concentration guideline?",
        "subject": "CONF",
        "exposure_rows": [
            {"row": 1, "key": "PINE", "fund": "NW_F3", "distance": 1, "kind": "CONFLICT - cross-fund review",
             "evidence": "Tessmark Clinical Supply supplies Pinewick Dermatology Partners"},
            {"row": 2, "key": "GRANITE", "fund": "NW_F4", "distance": 2, "kind": "SHARED COUNTERPARTY (informational)",
             "via": "C07", "evidence": "Tessmark Clinical Supply supplies Ravenholt Engineering Group; Ravenholt buys from Ironvale Testing Group"}],
        "fund_iv_holdings": [
            {"key": "GRANITE", "area": "Testing, Inspection & Certification", "since": "2024-03-15", "equity_musd": 150.0},
            {"key": "MEADOW", "area": "Healthcare Services", "since": "2023-09-12", "equity_musd": 110.0},
            {"key": "DIST1", "area": "Specialty Distribution", "since": "2023-11-01", "equity_musd": 140.0},
            {"key": "DIST2", "area": "Specialty Distribution", "since": "2024-08-20", "equity_musd": 125.0},
            {"key": "DIST3", "area": "Specialty Distribution", "since": "2025-06-02", "equity_musd": 120.0}],
        "concentration": {"fund": "NW_F4", "fund_size_musd": 1200.0, "guideline_pct": 35.0,
                          "areas": {"Specialty Distribution": {"before_musd": 385.0, "before_pct": 32.08,
                                                               "after_musd": 440.0, "after_pct": 36.67, "breach": True},
                                    "Testing, Inspection & Certification": {"before_pct": 12.5, "after_pct": 12.5},
                                    "Healthcare Services": {"before_pct": 9.17, "after_pct": 9.17},
                                    "Tech-Enabled Business Services": {"before_pct": 0.0, "after_pct": 0.0}},
                          "check_musd": 55.0, "headroom_musd": 35.0, "over_by_musd": 20.0},
        "bound_check": {"key": "REDFERN", "distance": 3, "path": ["CONF", "H1", "H2", "REDFERN"]},
        "former_holding_decoy": {"key": "BRIGHT", "distance": 1, "sold": "2020-02-14"},
        "naive_conflict_result": ["PINE", "BRIGHT"],
        "must_not_contain": ["REDFERN", "BRIGHT"],
    }


# ---------------------------------------------------------------------------------------
# Q-FLOW (graph + rules, Act 3)
# ---------------------------------------------------------------------------------------
def plant_q_flow(w: World):
    """Sector-scoped deal-flow network, last 5 years, 34 intermediaries in the graph (top decile = 4).
    CEDAR #1 bridge, HL #2 and the only coverage gap, BIGBANK tops the raw league table (40 deals)
    but ranks >= 11. 50 INTERMEDIARY rows in total with exactly 8 at 0 touchpoints."""
    k = w.k
    rng = random.Random(f"{w.seed}-qflow")
    hc_niches = ["Pediatric Therapy Clinics", "Physical Therapy Clinics", "Dental Service Organizations",
                 "Urgent Care Clinics", "Behavioral Health Clinics", "Dermatology Practices",
                 "Home Health Agencies", "Hospice Providers", "Veterinary Clinics", "Healthcare Staffing"]
    thesis_niches = hc_niches + ["Payroll & HR Outsourcing", "Insurance Claims Processing",
                                 "Compliance & Training Services", "Non-Destructive Testing",
                                 "Environmental Testing", "Calibration Services",
                                 "Specialty Chemicals Distribution", "Electrical Components Distribution"]
    non_thesis = ["Vertical SaaS", "Cybersecurity Software", "Managed IT Services", "Fitness Clubs",
                  "Car Wash Chains", "Specialty Foods", "Craft Beverages", "Precision Machining",
                  "Packaging Manufacturing", "Industrial Coatings", "Generic Pharmaceuticals",
                  "Commercial Janitorial Services", "Security Guard Services", "Pest Control Services",
                  "Digital Marketing Agencies", "Foodservice Distribution"]

    def uniq(make):
        n = make()
        while n in w.used_names:
            n = make()
        return n

    def mk_sponsor(key, state, aum, vintage, size, strategy="lower_mid_market_buyout"):
        name = uniq(lambda: f"{w.coined(rng)} {rng.choice(SPONSOR_SUFFIX)}")
        s = w.sponsor(key, name, state, aum, strategy)
        f = w.fund(key + "_F", s, f"{name} Fund {rng.choice(['II', 'III', 'IV', 'V'])}", vintage, size)
        return s, f

    def mk_interm(key, itype, state):
        name = uniq(lambda: f"{w.coined(rng)} {rng.choice(INTERMEDIARY_SUFFIX[itype])}")
        return w.intermediary(key, name, itype, state)

    def rdate(fund=None):
        y0 = max(2021, w.fund_vintage.get(fund, 2021))
        while True:
            dt = date(rng.randint(y0, 2026), rng.randint(1, 12), rng.randint(1, 28))
            if d("2021-11-01") <= dt <= d("2026-09-15"):
                return dt

    bs = {i: mk_sponsor(f"BS{i}", rng.choice(["NY", "IL", "MA", "CA", "TX"]), rng.uniform(3000, 6500), 2020 + (i % 2),
                        rng.uniform(1500, 2600), "middle_market_buyout") for i in range(1, 6)}
    hs = {1: (k("COPPERLINE"), k("CV_F3"))}
    for i in range(2, 6):
        hs[i] = mk_sponsor(f"HS{i}", rng.choice(["TN", "GA", "NC", "KY", "AL"]), rng.uniform(500, 1200), 2020,
                           rng.uniform(300, 600))
    ms = {i: mk_sponsor(f"MS{i}", rng.choice(["OH", "MI", "MN", "WI", "MO"]), rng.uniform(600, 1500), 2019,
                        rng.uniform(350, 700)) for i in range(1, 5)}
    rs = {i: mk_sponsor(f"RS{i}", rng.choice(["CO", "AZ", "UT", "OR", "WA", "NV"]), rng.uniform(250, 600), 2020,
                        rng.uniform(200, 400)) for i in range(1, 7)}
    adv = {i: mk_interm(f"ADV{i}", "boutique" if i % 3 else "regional_bank",
                        rng.choice(["NY", "IL", "TX", "GA", "CA", "OH", "MN", "NC"])) for i in range(1, 9)}
    radv = {i: mk_interm(f"RADV{i}", rng.choice(["boutique", "boutique", "regional_bank"]),
                         rng.choice(["CO", "AZ", "UT", "OR", "WA", "NV", "NM", "ID", "MT"])) for i in range(1, 23)}

    def deal(advisor, buyer, niche=None, when=None, seller=None, lead=None):
        niche = niche or rng.choice(thesis_niches)
        tgt = w.filler_company(niche, rng, ebitda=round(min(38.0, max(5.5, rng.lognormvariate(math.log(13), 0.5))), 1))
        if seller is not None:  # secondary buyout: seller fund bought it at or after its vintage
            w.own(tgt, seller[1], date(max(2019, w.fund_vintage[seller[1]]), rng.randint(1, 9), 1))
        advisors = [(advisor, "sell_side_advisor", lead)] if advisor else []
        return w.buyout(tgt, when or rdate(buyer[1]), buyer[1], advisors=advisors,
                        seller_fund=seller[1] if seller else None, rng=rng)

    # Core: well-connected middle-market sponsors and their regular advisors.
    core_plan = {1: [1, 1, 2, 3], 2: [2, 2, 4, 5], 3: [3, 3, 5, 1], 4: [4, 4, 1], 5: [5, 5, 2]}
    for a, buyers in core_plan.items():
        for b in buyers:
            deal(adv[a], bs[b])
    # BIGBANK: 8 in-thesis deals, all sell-side mandates sold to one large, well-connected sponsor
    # (BS1). Every BIGBANK neighbor already sits next to BS1, so it bridges almost nothing ...
    for i in range(8):
        tgt = w.filler_company(rng.choice(thesis_niches), rng, ebitda=round(rng.uniform(12, 36), 1))
        w.buyout(tgt, rdate(bs[1][1]), bs[1][1], advisors=[(k("BIGBANK"), "sell_side_advisor")], rng=rng)
    # ... and 32 deals outside the thesis sectors, so it tops a raw league table with 40.
    for i in range(32):
        tgt = w.filler_company(rng.choice(non_thesis), rng, ebitda=round(rng.uniform(6, 60), 1))
        buyer = bs[1 + i % 5] if i % 3 else ms[1 + i % 4]
        w.buyout(tgt, rdate(buyer[1]), buyer[1],
                 advisors=[(k("BIGBANK"), rng.choice(["sell_side_advisor", "buy_side_advisor"]))], rng=rng)
    # CEDAR: bridges mid-market sponsors, HL's sponsors and the core (plus Northwind deals in PORTFOLIO).
    for i in range(1, 5):
        deal(k("CEDAR"), ms[i])
        deal(k("CEDAR"), bs[1 + (i % 5)], seller=ms[i])
        deal(adv[6] if i <= 2 else adv[7], ms[i])
    deal(k("CEDAR"), hs[2]); deal(k("CEDAR"), hs[3])
    deal(k("CEDAR"), bs[4]); deal(k("CEDAR"), bs[5])
    # Regional advisors: each runs one deal for a regional sponsor and one for a core or mid sponsor.
    for i in range(1, 23):
        deal(radv[i], rs[1 + (i - 1) % 6])
        deal(radv[i], bs[1 + i % 5] if i % 2 else ms[1 + i % 4])
    # HL: 8 founder-owned healthcare sell-side mandates to 5 sponsors, plus the T_COLD dividend recap.
    hl_md = k("HL_MD")
    for hsi in [1, 1, 2, 2, 3, 3, 4, 5]:
        deal(k("HL"), hs[hsi], niche=rng.choice(hc_niches), lead=hl_md)
    deal(adv[8], hs[1]); deal(adv[6], hs[4]); deal(adv[8], hs[5])
    w.txn(k("T_COLD"), "2023-05-18", "platform", "sponsor", "dividend_recap",
          [(k("HL"), "debt_advisor", None, hl_md), (k("COPPERLINE"), "owner", k("CV_F2"), k("OWN_C"))], rng=rng)

    # Context intermediaries outside the deal graph (to 50 rows in total).
    others = []
    for i in range(1, 12):
        itype = "business_broker" if i % 3 == 0 else rng.choice(["boutique", "regional_bank"])
        others.append(mk_interm(f"OTH{i}", itype, rng.choice(list(US_STATES))))

    # Touchpoints in the last 24 months. Q1 over all 50 intermediaries pinned to 1:
    # exactly 8 at 0, 6 at 1 (HL included), every other graph intermediary >= 3.
    seeds = [k("MP"), k("MD_MER"), k("VP"), k("OP"), k("OP2")]
    zeros = [k("LAKESHORE"), k("ADV_OLD")] + others[:6]
    ones = others[6:10] + [k("CTX3")]
    twos = [others[10], k("CTX1"), k("CTX2")]
    plan = {i_: 0 for i_ in zeros}
    plan.update({i_: 1 for i_ in ones})
    plan.update({i_: 2 for i_ in twos})
    plan[k("BIGBANK")] = 9
    plan[k("ADV_SHORT")] = 3
    for i, a in adv.items():
        plan[a] = [7, 6, 5, 4, 5, 3, 3, 4][i - 1]
    for i, a in radv.items():
        plan[a] = 3 + (i % 3)
    for org, n in plan.items():
        for _ in range(n):
            when = d("2024-10-01") + timedelta(days=rng.randint(5, 725))
            w.crm(rng.choice(seeds), when, rng.choice(["call", "meeting", "email", "conference"]),
                  rng.choice(["neutral", "positive", "neutral"]), org=org)
        if n == 0 and rng.random() < 0.5:  # an old touch outside the window keeps zeros realistic
            w.crm(rng.choice(seeds), d("2022-06-01") + timedelta(days=rng.randint(0, 500)), "call", "neutral", org=org)
    w.crm(k("VP"), "2025-11-20", "conference", "neutral", org=k("HL"))  # HL's single touchpoint
    w.crm(k("MD_MER"), "2023-06-07", "call", "neutral", org=k("HL"))   # older, outside 24 months

    w.golden["Q-FLOW"] = {
        "question": "Which intermediaries actually bridge deal flow between founders and sponsors in our sectors, and where is our coverage weakest?",
        "betweenness_rank_intermediaries": [{"rank": 1, "key": "CEDAR"}, {"rank": 2, "key": "HL"}],
        "bigbank_min_rank": 11,
        "n_intermediaries_in_graph": "31-40 (top decile = 4)",
        "touchpoints_24m": {"CEDAR": 14, "HL": 1, "BIGBANK": 9},
        "hl_deals_in_window": 9,
        "coverage_gaps": ["HL"],
        "q1_touchpoints": 1,
        "bigbank_total_deals_5y": 40,
        "bigbank_thesis_deals_5y": 8,
        "hl_advised_t_cold_recap": {"date": "2023-05-18", "structure": "dividend_recap", "party_role": "debt_advisor",
                                    "lead": "HL_MD", "owner": "COPPERLINE"},
        "must_not_contain": ["CEDAR", "BIGBANK"],
        "tier1_must_not_appear": ["BIGBANK"],
    }


# ---------------------------------------------------------------------------------------
# Finale (rules composing graph output)
# ---------------------------------------------------------------------------------------
def plant_finale(w: World):
    """NM_B's 2-hop path (OP2 - Z - NM_B CEO). The CONF -> PINE link is planted by Q-CONFLICT."""
    H, k = HERO_NAMES, w.k
    lake = w.company("LAKEMONT", H["LAKEMONT"], "Dental Service Organizations", "AZ", 22.0, 3.5, founded=2004)
    w.role(k("OP2"), lake, "COO", "2016-02-01", "2020-05-31", title="Chief Operating Officer")
    z = w.person("Z", H["Z"])
    w.role(z, lake, "CEO", "2015-08-03", "2021-03-31", title="Chief Executive Officer")
    w.role(z, k("NM_B"), "Board", "2022-04-01", title="Director")
    w.golden["FINALE"] = {
        "prompt": "Add two rules and re-score. One: a target gets 10 access points if one of our deal team or operating partners can reach its CEO in two hops or fewer. Two: any target that is a customer or supplier of a current Fund III portfolio company is a conflict, so flag it and take it off the Tier A list.",
        "tier_a_ranked": [
            {"rank": 1, "key": "T_WARM", "score": 95}, {"rank": 2, "key": "T_BANKER", "score": 90},
            {"rank": 3, "key": "T_COLD", "score": 80}, {"rank": 4, "key": "T_5", "score": 75},
            {"rank": 5, "key": "NM_B", "score": 75}, {"rank": 6, "key": "T_6", "score": 70}],
        "warm_path_set": ["T_WARM", "NM_B"],
        "conflicts": [{"key": "CONF", "score": 75, "flag": "Conflict - cross-fund review", "with": "PINE",
                       "direction": "CONF supplies PINE"}],
        "nm_b_path": {"path": ["OP2", "Z", "CEO_NMB"], "hop_strengths": [1.0, 1.0], "path_strength": 1.0},
        "guards": ["F1: NM_B is the only scored company with an Act-1 score in [60, 69]",
                   "F2: every current role-holder of T_BANKER, T_COLD, T_5, T_6, CONF has seed-distance >= 3"],
        "must_not_contain": ["CONF"],
        "decoy_check": "row-based: CONF named as flagged, absent from Tier-A rows",
    }


# ---------------------------------------------------------------------------------------
# Q-ADDON (graph) - BACKUP in v2 (cheap: data shared with Q-CONFLICT through C07)
# ---------------------------------------------------------------------------------------
def plant_q_addon(w: World):
    """GRANITE's commercial neighborhood (15 customers incl. C07 + 3 suppliers), add-ons A1-A3, decoy D_SAME."""
    H, k = HERO_NAMES, w.k
    rng = random.Random(f"{w.seed}-qaddon")
    g = k("GRANITE")
    cust_niches = ["Civil Engineering Services", "General Contractors", "Aerospace Components",
                   "Precision Machining", "Commercial HVAC Contractors", "Packaging Manufacturing"]
    custs = []
    for i in range(1, 16):
        if i == 7:
            c = w.company("C07", H["C07"], "Civil Engineering Services", "TX", 88.0, 9.5, founded=1991)
        else:
            c = w.filler_company(cust_niches[i % len(cust_niches)], rng, key=f"C{i:02d}",
                                 state=rng.choice(["TX", "OK", "LA", "AR", "TX", "CO"]))
        custs.append(c)
        w.link(g, c, rng.choice(["<1M", "1-5M", "1-5M", "5-20M"]), rng=rng)
    for i in range(1, 4):
        s = w.filler_company(["Industrial MRO Distribution", "Specialty Chemicals Distribution",
                              "Industrial Coatings"][i - 1], rng, key=f"S{i}", state="TX",
                             ebitda=round(rng.uniform(4, 30), 1))
        w.link(s, g, "1-5M", rng=rng)
    a1 = w.company("A1", H["A1"], "Environmental Testing", "TX", 52.0, 9.5, founded=2003, sites=["CO", "UT", "NM"])
    a2 = w.company("A2", H["A2"], "Non-Destructive Testing", "TX", 41.0, 7.0, founded=2007, sites=["LA"])
    a3 = w.company("A3", H["A3"], "Calibration Services", "OK", 33.0, 5.5, founded=2010, sites=["KS"])
    dsame = w.company("D_SAME", H["D_SAME"], "Materials Testing", "TX", 55.0, 9.0, founded=1999, sites=["OK", "LA"])
    own_niches = ["General Contractors", "Civil Engineering Services", "Specialty Foods", "Generic Pharmaceuticals",
                  "Craft Beverages", "Data Center Services"]
    for comp, shared, n_own in [(a1, [1, 2, 3, 4, 5, 6], 4), (a2, [8, 9, 10], 5), (a3, [11, 12], 2), (dsame, [], 6)]:
        for i in shared:
            w.link(comp, custs[i - 1], "<1M", rng=rng)
        for _ in range(n_own):
            st = rng.choice(["CO", "UT", "NM", "KS", "MO", "MS"])
            c = w.filler_company(rng.choice(own_niches), rng, state=st)
            w.link(comp, c, rng.choice(["<1M", "1-5M"]), rng=rng)
    for key in ("A1", "A2", "A3", "D_SAME"):
        # R20: a founder CEO cannot start before the company was founded; clamp the drawn year to the
        # founding year (same RNG draws, so every other planted value is unchanged).
        yr, mo = rng.randint(2003, 2015), rng.randint(1, 9)
        yr = max(yr, w.company_row[k(key)]["founded_year"])
        p = w.person(None); w.role(p, k(key), "CEO", f"{yr}-0{mo}-01", title="Founder and CEO", founder=True)
    w.golden["Q-ADDON"] = {
        "status": "backup (v2)",
        "question": "Which add-ons best extend our Ironvale Testing Group platform, beyond the obvious same-niche names?",
        "platform": "GRANITE", "platform_neighbors": 18,
        "ranked": [
            {"rank": 1, "key": "A1", "shared": 6, "neighbors": 10, "jaccard": round(6 / 22, 4),
             "whitespace_states": ["CO", "NM", "UT"]},
            {"rank": 2, "key": "A2", "shared": 3, "neighbors": 8, "jaccard": round(3 / 23, 4), "whitespace_states": []},
            {"rank": 3, "key": "A3", "shared": 2, "neighbors": 4, "jaccard": round(2 / 20, 4), "whitespace_states": ["KS"]},
        ],
        "must_not_contain": ["D_SAME"],
    }


# Registry: question ID -> planting function. Order matters only for ID draws (deterministic).
# Dependencies: PORTFOLIO before Q-ADDON/Q-CONFLICT/FINALE; Q-ADDON before Q-CONFLICT (creates C07,
# else Q-CONFLICT creates it); Q-SCORE before Q-FLOW (context boutiques CTX1-3).
STORIES = {
    "Q-SCORE": plant_q_score,
    "Q-PATH": plant_q_path,
    "PORTFOLIO": plant_portfolio,
    "Q-ADDON": plant_q_addon,
    "Q-CONFLICT": plant_q_conflict,
    "Q-FLOW": plant_q_flow,
    "FINALE": plant_finale,
}


def right_size_funds(w: World):
    """R20: a fund cannot invest more equity than it raised. The Q-FLOW sponsors' fund sizes are drawn
    before their deals are planted, so a few ended at 141-157% deployed. Re-size every non-Northwind
    fund that is over 100% to 84-93% deployed (rounded to $10M) and keep its sponsor's AUM at least
    1.5x its fund commitments. Only FUND.size_musd and SPONSOR.aum_musd move; no deal, ownership or
    equity check changes, and Northwind's funds (Fund IV size is golden) are never touched."""
    rng = random.Random(f"{w.seed}-fundsize")
    deployed = defaultdict(float)
    for o in w.t["OWNERSHIP"]:
        deployed[o["fund_id"]] += float(o["equity_invested_musd"] or 0)
    nw = w.k("NW")
    resized = set()
    for f in sorted(w.t["FUND"], key=lambda r: r["fund_id"]):
        if f["sponsor_id"] == nw or deployed[f["fund_id"]] <= f["size_musd"]:
            continue
        f["size_musd"] = round(round(deployed[f["fund_id"]] / rng.uniform(0.84, 0.93), -1), 2)
        resized.add(f["sponsor_id"])
    for sp in sorted(w.t["SPONSOR"], key=lambda r: r["sponsor_id"]):
        if sp["sponsor_id"] in resized:
            commit = sum(f["size_musd"] for f in w.t["FUND"] if f["sponsor_id"] == sp["sponsor_id"])
            if sp["aum_musd"] < 1.5 * commit:
                sp["aum_musd"] = round(commit * rng.uniform(1.6, 1.9), 2)


# R20 (R19c M3): TEV/EBITDA by deal size. Platform medians follow GF Data 2025 (domain brief: $10-25M 5.9x,
# $25-50M 6.6x, $50-100M 8.7x, $100-250M 10.0x, $250-500M 9.8x) inside the brief's 6.0-12.5x clamp; add-ons
# price below a platform of the same size (buy-and-build arbitrage); sector spreads per the brief table.
EV_PLATFORM_ANCHORS = [(5.0, 6.4), (17.0, 6.7), (35.0, 7.3), (70.0, 8.9), (160.0, 10.1), (350.0, 10.0)]
EV_ADDON_DISCOUNT = [(5.0, 0.4), (35.0, 0.8), (70.0, 1.3), (160.0, 1.6), (350.0, 1.6)]
EV_SECTOR_PREMIUM = {"Healthcare Services": 0.3, "Tech-Enabled Business Services": 0.6,
                     "Testing, Inspection & Certification": 0.6, "Specialty Distribution": -0.6,
                     "Broadline Distribution": -0.8, "Technology": 0.8, "Life Sciences": 0.3, "Consumer": -0.3}
EV_EQUITY_MAX_SHARE = 0.70       # a sponsor's equity check is at most 70% of the purchase price


def _interp_log(anchors, ev):
    x = math.log(max(ev, 0.1))
    pts = [(math.log(a), b) for a, b in anchors]
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def reprice_deals(w: World):
    """R20 (R19c M3): redraw TRANSACTION.ev_ebitda by TEV band and deal role, keeping each deal's EBITDA at
    close (old ev_musd / old ev_ebitda) and recomputing ev_musd. Each deal draws from its own RNG seeded by
    its txn_id, so a signal deal gets the same price in the signal-only and the noise build. Only ev_musd and
    ev_ebitda move: no rule, query, oracle or golden field reads either. Where a sponsor's equity check would
    exceed EV_EQUITY_MAX_SHARE of the price, a noise check is trimmed; a signal check (fixed by the stories) instead
    floors the multiple."""
    sig_own = getattr(w, "signal_ownership_ids", set())
    own_at = {(o["company_id"], o["fund_id"], o["start_date"]): o for o in w.t["OWNERSHIP"]}
    buyer_fund = {}
    for p in w.t["TRANSACTION_PARTY"]:
        if p["party_role"] == "buyer" and p["fund_id"]:
            buyer_fund[p["txn_id"]] = p["fund_id"]
    for t in sorted(w.t["TRANSACTION"], key=lambda r: r["txn_id"]):
        if t["ev_musd"] is None or not t["ev_ebitda"]:
            continue
        rng = random.Random(f"{w.seed}-ev-{t['txn_id']}")
        e = t["ev_musd"] / t["ev_ebitda"]                    # EBITDA at close
        names = []
        sid = w.company_row[t["target_id"]]["sector_id"]
        while sid:
            names.append(w.sector_name[sid]); sid = w.sector_parent[sid]
        prem = next((EV_SECTOR_PREMIUM[n] for n in names if n in EV_SECTOR_PREMIUM), 0.0)
        addon = t["deal_role"] == "add_on"

        def med(ev):
            m = _interp_log(EV_PLATFORM_ANCHORS, ev) + prem * min(1.0, ev / 70.0)
            return m - (_interp_log(EV_ADDON_DISCOUNT, ev) if addon else 0.0)
        m = 8.0
        for _ in range(40):                                   # median multiple consistent with its own TEV
            m = 0.5 * m + 0.5 * med(e * m)
        m = m + rng.gauss(0.0, 0.07 * m)
        if m < 6.0:                                           # reflect off the brief's 6.0x floor (no pile-up)
            m = 6.0 + 0.6 * (6.0 - m)
        m = min(12.5, m)
        o = own_at.get((t["target_id"], buyer_fund.get(t["txn_id"]), t["close_date"]))
        if o is not None and o["equity_invested_musd"]:
            if o["ownership_id"] in sig_own:
                m = min(12.5, max(m, o["equity_invested_musd"] / (EV_EQUITY_MAX_SHARE * e)))
            elif o["equity_invested_musd"] > EV_EQUITY_MAX_SHARE * e * m:
                o["equity_invested_musd"] = round(EV_EQUITY_MAX_SHARE * e * m * rng.uniform(0.80, 0.95), 1)
        m = round(m, 1)
        t["ev_ebitda"] = m
        t["ev_musd"] = round(e * m, 1)


def realism_guards(w: World):
    """R20 generator-level guards, run after signal (and noise) so later edits are covered too:
    no role at a company starts before its founding year, and no fund has invested more than 100%
    of its size."""
    for r in w.t["ROLE_HISTORY"]:
        if r["org_type"] == "company":
            fy = w.company_row[r["org_id"]]["founded_year"]
            assert r["start_date"] >= date(fy, 1, 1), f"role {r['role_id']} at {r['org_id']} starts before founding {fy}"
    deployed = defaultdict(float)
    for o in w.t["OWNERSHIP"]:
        deployed[o["fund_id"]] += float(o["equity_invested_musd"] or 0)
    for f in w.t["FUND"]:
        assert deployed[f["fund_id"]] <= f["size_musd"] + 1e-6, \
            f"fund {f['fund_id']} invested {deployed[f['fund_id']]:.1f} of {f['size_musd']}"


def golden_extras(w: World):
    """Rehearsal name lists (section 9.3) and R04 attempt-2 clarifications, added to whichever
    questions are planted. Names are resolved from the final HERO_NAMES."""
    N = lambda key: w.name_of[w.key[key]]  # noqa: E731
    g = w.golden
    if "Q-SCORE" in g:
        g["Q-SCORE"]["rehearsal"] = {
            "must_appear": [N(x) for x in ("T_BANKER", "T_WARM", "T_COLD", "T_5", "CONF", "T_6")],
            "must_not_appear": [N(x) for x in ("D_VET", "D_SHORT", "D_SNF")]}
        g["Q-SCORE"]["naive_screen"]["other_cast_rows"] = (
            "every other cast company returned by the keyword screen has 0 signal rows in [T-12m, T] "
            "(A1, A2, D_SAME, H2 and any other keyword match); OLDHARBOR (EBITDA 95, public) and H1 (EBITDA 52) "
            "fall outside the band; Keel (Q-COMPETE) is not planted")
    if "Q-PATH" in g:
        g["Q-PATH"]["rehearsal"] = {
            "must_appear": [N(x) for x in ("CEO_B", "VP", "Y_BANK", "B_BANK", "CEO_W", "OP", "CFO_W", "CEO_C",
                                           "OWN_C", "OWN_B")],
            "must_not_appear": [N("MD_MER"), N("MERIDIAN")],
            "row_check": f"{N('X_STALE')} may appear only in the second-ranked {N('T_WARM')} alternate"}
        g["Q-PATH"]["naive_sql"] = {
            "q_path.sql": ("self-join ROLE_HISTORY on org_id, one side a current Northwind Deal Team/Operating Partner "
                           "role, the other the current CEO of a top-three target, ignoring dates. Returns exactly one "
                           f"row: {N('MD_MER')} - {N('CEO_C')} via {N('MERIDIAN')} (decoy: 613-day gap)."),
            "near_misses": [
                {"name": "stale tie", "label": "near_miss (not a SQL decoy)",
                 "detail": f"{N('MP')} - {N('X_STALE')} at {N('OLDHARBOR')} 1998-2000 is a real Knows edge; RAI ranks "
                           "it second (0.287). A count-of-connections ranking treats it as equal to the 0.600 path."},
                {"name": "we know the sponsor", "label": "near_miss (CRM search)",
                 "detail": f"SELECT * FROM CRM_INTERACTION WHERE counterparty_org_id = '{w.key['COPPERLINE']}' returns one "
                           f"neutral meeting by {N('MP')} on 2025-03-04, so a CRM search says 'we know "
                           f"{N('COPPERLINE')}'; the owner designee {N('OWN_C')} is more than 3 hops away."}]}
    if "Q-FLOW" in g:
        g["Q-FLOW"]["rehearsal"] = {"must_appear": [N("CEDAR"), N("HL")], "must_not_appear": [N("BIGBANK")]}
        g["Q-FLOW"]["hl_deal_roles"] = ("8 x deal_role=platform, structure=control_buyout, seller_type=founder_family, "
                                        "buyer = the sponsor fund (party org = sponsor, so HL-sponsor edges exist); "
                                        "1 x dividend_recap with HL debt_advisor and Coppervale Fund II owner")
    if "Q-CONFLICT" in g:
        g["Q-CONFLICT"]["rehearsal"] = {
            "must_appear": [N("CONF"), N("PINE"), N("GRANITE"), "Specialty Distribution"],
            "must_not_appear": [N("BRIGHT"), N("REDFERN")]}
    if "FINALE" in g:
        g["FINALE"]["rehearsal"] = {
            "must_appear": [N(x) for x in ("T_WARM", "T_BANKER", "T_COLD", "T_5", "NM_B", "T_6")] + [N("CONF") + " (as flagged)"],
            "row_check": f"{N('CONF')} is not among the Tier-A rows"}
        g["FINALE"]["guards"] += [
            "F2 also holds measured from former Northwind people (EX_NW): seed-distance and former-Northwind distance >= 3",
            "Conflict rule uses CURRENT Fund III holdings only; former Fund III holdings are excluded by design, and no "
            "Tier-A or NM_B company links to one anyway"]


# =====================================================================================
# 4. NOISE SECTION (R12, phase P5)
#    Opt-in: `python data/generate.py --noise --out data/csv_noise` (make data-noise).
#    Without --noise, add_noise() returns before drawing any ID or random number, so the
#    default `make data` output stays byte-identical to the signal-only layer.
#
#    Design (R12 a1, see DECISIONS.md):
#    * Noise only ADDS rows. It never edits or deletes a signal row, never targets a signal
#      company with a deal, link, signal, CRM touch or pipeline row, and never adds people to
#      an org that has signal-layer roles. The single exception is one CEO per signal company
#      that has none (R08 invariant "exactly one current CEO"); those CEOs start after every
#      earlier role at the org ended, are not founders and hold no other role, so they are
#      Knows leaves and change no distance and no score component.
#    * Knows safety: person-level CRM (K3) goes only to sponsor business-development people who
#      lead no deal and sit on no board, so nobody within 2 hops of a seed is a target CEO.
#    * Score safety: every eligible noise company is planned to score <= 55 (Guard F1 window
#      60-69 stays empty; +10 warm path can never reach 70).
#    * Q-FLOW safety: in-window thesis deals avoid HL, CEDAR, BIGBANK, the HL sponsors and the
#      cast sponsors, use only well-covered advisors, and are capped (NOISE_FLOW_THESIS_DEALS).
#    * Commercial safety: no noise link touches a keyed company or CONF's 2-hop ball
#      (one deliberate Q-ADDON near-miss links two GRANITE customers, never C07).
# =====================================================================================

import calendar as _calendar

NOISE_COMPANIES = 880            # bulk noise companies (plus a handful of crafted near-misses)
NOISE_FLOW_THESIS_DEALS = 34     # cap on new in-window (last 5y) deals with a Fund IV thesis target
NOISE_FLOW_PER_ADVISOR = 1       # at most this many of those per regional advisor (keeps HL #2 by a wide margin)
NOISE_LINKS = 1930
NOISE_SIGNAL_RATE = 1.6          # mean signals per noise company
NOISE_PIPELINE = 195
NOISE_SCORE_CAP = 55
NOISE_SPONSORS = 14
NOISE_PLATFORM_MUSD = 700.0     # R20: about one noise platform per $700M of fund commitments
NOISE_ADDON_COUNTS = [3, 3, 4, 4, 5]   # R20: in-window add-ons per platform (buy-and-build)
NOISE_RECAPS = 4                 # R20: dividend recaps on current non-thesis platforms
NOISE_MAX_CHECK_PCT = 0.25       # R20: no single noise equity check above 25% of its fund
# R20 (R19c M1): CEO tenure realism (domain brief: LMM founder CEOs 12-30 years, PE-appointed CEOs 3-6)
FOUNDER_TENURE_MED, FOUNDER_TENURE_SIG, FOUNDER_TENURE_MIN, FOUNDER_TENURE_MAX = 15.0, 0.32, 8.0, 34.0
NOISE_CEO_TENURE_MED, NOISE_CEO_TENURE_SIG = 6.0, 0.42

T5Y = date(2021, 10, 1)          # T-5y
T10Y = date(2016, 10, 1)         # T-10y (transactions table covers the last 10 years)
NOISE_L1_WEIGHT = {"Healthcare Services": 0.19, "Business Services": 0.15, "Industrials": 0.24,
                   "Distribution": 0.11, "Life Sciences": 0.08, "Technology": 0.13, "Consumer": 0.10}
NOISE_SUPPLY = {  # supplier level-2 (or level-1) -> customer level-1/level-2 names
    "Specialty Distribution": ["Healthcare Services", "Industrial Manufacturing", "Engineering & Construction",
                               "Aerospace & Defense", "Food & Beverage", "Life Sciences"],
    "Broadline Distribution": ["Consumer", "Acute Care", "Post-Acute Care", "Industrial Manufacturing"],
    "Testing, Inspection & Certification": ["Industrial Manufacturing", "Engineering & Construction",
                                            "Aerospace & Defense", "Food & Beverage", "Life Sciences"],
    "Tech-Enabled Business Services": ["Healthcare Services", "Business Services", "Industrials", "Distribution"],
    "Healthcare Support Services": ["Acute Care", "Post-Acute Care", "Outpatient Clinical Services"],
    "Facilities Services": ["Healthcare Services", "Industrials", "Consumer", "Technology"],
    "Marketing Services": ["Consumer", "Business Services", "Healthcare Services"],
    "Technology": ["Healthcare Services", "Business Services", "Industrials", "Distribution", "Consumer"],
    "Industrial Manufacturing": ["Industrials", "Food & Beverage", "Distribution"],
    "Life Sciences": ["Specialty Distribution", "Life Sciences", "Healthcare Services"],
    "Research & Lab Services": ["Life Sciences", "Healthcare Services"],
}
DT_TITLES = ["Managing Partner", "Partner", "Partner", "Principal", "Principal", "Vice President"]
BANKER_TITLES = ["Managing Director", "Managing Director", "Director", "Vice President"]


def _addm(dt: date, n: int) -> date:
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(dt.day, _calendar.monthrange(y, m)[1]))


T_6M, T_12M, T_18M, T_24M, T_15Y, T_P18M = (_addm(AS_OF, -6), _addm(AS_OF, -12), _addm(AS_OF, -18),
                                             _addm(AS_OF, -24), _addm(AS_OF, -180), _addm(AS_OF, 18))


def add_noise(w: World, enabled: bool = False):
    """Fill the market toward PROMPT.md 8.1 sizes without creating competing answers (opt-in)."""
    if not enabled:
        return
    Noise(w, random.Random(f"{w.seed}-noise")).run()


class Noise:
    def __init__(self, w: World, rng: random.Random):
        self.w, self.rng = w, rng
        k = w.k
        self.k = k
        self.sig_companies = sorted(r["company_id"] for r in w.t["COMPANY"])
        self.sig_role_orgs = {r["org_id"] for r in w.t["ROLE_HISTORY"]}
        self.keyed = set(w.key.values())
        self.nw = k("NW")
        self.nw_funds = [k("NW_F2"), k("NW_F3"), k("NW_F4")]
        self.cast_sponsors = {k(x) for x in ("NW", "IRONBRIDGE", "COPPERLINE", "TAMARACK", "RIDGEBACK", "ASHGROVE")}
        self.hl_sponsors = {k("COPPERLINE")} | {k(f"HS{i}") for i in range(2, 6)}
        self.seeds = [k(x) for x in ("MP", "MD_MER", "VP", "OP", "OP2")]
        self.no_touch_interm = {k("HL"), k("CEDAR"), k("BIGBANK")}
        self.covered_interm = [k(f"ADV{i}") for i in range(1, 9)] + [k(f"RADV{i}") for i in range(1, 23)]
        self.other_interm = sorted(r["intermediary_id"] for r in w.t["INTERMEDIARY"]
                                   if r["intermediary_id"] not in self.no_touch_interm
                                   and r["intermediary_id"] not in self.covered_interm)
        # commercial protection: keyed companies plus CONF's 2-hop ball
        adj = defaultdict(set)
        for l in w.t["COMMERCIAL_LINK"]:
            adj[l["supplier_id"]].add(l["customer_id"]); adj[l["customer_id"]].add(l["supplier_id"])
        ball, frontier = {k("CONF")}, {k("CONF")}
        for _ in range(2):
            frontier = {n for f in frontier for n in adj[f]} - ball
            ball |= frontier
        self.link_protected = self.keyed | ball
        self.f4_inc, self.f4_exc = {}, set()
        for r in w.t["FUND_FOCUS"]:
            if r["fund_id"] == k("NW_F4"):
                if r["mode"] == "include":
                    self.f4_inc[r["sector_id"]] = r["margin_benchmark_pct"]
                else:
                    self.f4_exc.add(r["sector_id"])
        self.noise_cos = []            # bulk noise companies (ordered)
        self.crafted = []              # crafted near-miss companies (excluded from bulk pools)
        self.no_career = set()         # companies nobody else may have worked at (seed-adjacent)
        self.sponsor_people = defaultdict(list)   # sponsor -> [(pid, start, end, kind)]
        self.bankers = defaultdict(list)          # intermediary -> [(pid, start, end)]
        self.bd_people = []
        self.flow_thesis_deals = 0
        self.flow_adv_use = defaultdict(int)
        self.funds = []                # noise-usable funds: (fid, sponsor, vintage, size, band, focus)
        self.sponsor_focus = {}
        self.platforms = []            # (company, fund, start, end)
        self.league = []
        self.near_miss = {}            # label -> company id (reported in the handoff only)
        self.addon_close = {}          # R20: add-on target -> (close date, buying platform)
        # R20: CEO-history draws use a side RNG so tenure realism does not depend on the main stream
        self.crng = random.Random(f"{w.seed}-noise-ceo")

    # ---------------------------------------------------------------- helpers
    def anc(self, sid):
        out = []
        while sid:
            out.append(sid); sid = self.w.sector_parent[sid]
        return out

    def names_up(self, cid):
        return [self.w.sector_name[s] for s in self.anc(self.w.company_row[cid]["sector_id"])]

    def in_thesis(self, cid):
        a = set(self.anc(self.w.company_row[cid]["sector_id"]))
        return bool(a & set(self.f4_inc)) and not (a & self.f4_exc)

    def nw_owned_now(self, cid):
        return any(o["company_id"] == cid and o["end_date"] is None and o["fund_id"] in self.nw_funds
                   for o in self.own_by_co.get(cid, []))

    def eligible(self, cid):
        r = self.w.company_row[cid]
        return (self.in_thesis(cid) and 5.0 <= r["ebitda_musd"] <= 40.0 and r["hq_region_id"].startswith("US-")
                and not r["is_public"] and not self.nw_owned_now(cid))

    def naive_row(self, cid):
        r = self.w.company_row[cid]
        txt = (r["name"] + " " + self.w.sector_name[r["sector_id"]]).lower()
        return (any(kw in txt for kw in NAIVE_KEYWORDS) and 5 <= r["ebitda_musd"] <= 40
                and r["hq_region_id"].startswith("US-") and not self.nw_owned_now(cid))

    def fit(self, cid):
        r = self.w.company_row[cid]
        e = r["ebitda_musd"]
        bench = [self.f4_inc[s] for s in self.anc(r["sector_id"]) if s in self.f4_inc][0]
        return 15 + (10 if 10.0 <= e <= 30.0 else 5) + (5 if e / r["revenue_musd"] * 100 >= bench else 0)

    def rdate(self, lo: date, hi: date) -> date:
        if hi <= lo:
            return lo
        return lo + timedelta(days=self.rng.randint(0, (hi - lo).days))

    def new_company(self, niche, ebitda, state=None, sites=None):
        w = self.w
        cid = w.filler_company(niche, self.rng, ebitda=ebitda, state=state, sites=sites)
        return cid

    # ---------------------------------------------------------------- 1. sponsors and funds
    def sponsors_and_funds(self):
        w, rng = self.w, self.rng
        focus_pool = [["Healthcare Services"], ["Business Services"], ["Industrials"], ["Distribution", "Industrials"],
                      ["Healthcare Services", "Life Sciences"], ["Technology", "Business Services"],
                      ["Consumer"], ["Industrials", "Business Services"], ["Healthcare Services", "Business Services"]]
        # R20 (R19c m5): a noise sponsor never shares its first word with a signal-layer org name (two
        # "Claywell ..." sponsors confuse a live name filter). Redraws use a side RNG, so the main noise
        # stream is unchanged.
        alt = random.Random(f"{w.seed}-noise-sponsor-names")
        sig_stems = {r["name"].split()[0] for t_ in ("SPONSOR", "INTERMEDIARY", "COMPANY") for r in w.t[t_]}
        for i in range(1, NOISE_SPONSORS + 1):
            mm = rng.random() < 0.3
            name = f"{w.coined(rng)} {rng.choice(SPONSOR_SUFFIX)}"
            while name in w.used_names:
                name = f"{w.coined(rng)} {rng.choice(SPONSOR_SUFFIX)}"
            while name in w.used_names or name.split()[0] in sig_stems:
                name = f"{w.coined(alt)} {alt.choice(SPONSOR_SUFFIX)}"
            states = list(US_STATES)
            st = rng.choices(states, weights=[STATE_WEIGHT[s] for s in states])[0]
            n_funds = rng.choice([2, 2, 3, 3, 3])
            first_v = rng.randint(2007, 2014)
            sizes, vint = [], []
            size = rng.uniform(900, 1500) if mm else rng.uniform(220, 520)
            v = first_v
            for _ in range(n_funds):
                if v > 2025:
                    break
                vint.append(v); sizes.append(size)
                v += rng.randint(3, 5); size *= rng.uniform(1.15, 1.5)
            aum = sum(sizes) * rng.uniform(0.8, 1.05)
            sid = w.sponsor(None, name, st, aum, "middle_market_buyout" if mm else "lower_mid_market_buyout")
            self.sponsor_focus[sid] = rng.choice(focus_pool)
            roman = ["I", "II", "III", "IV", "V", "VI"]
            start_num = rng.choice([1, 1, 2])
            for j, (v_, sz) in enumerate(zip(vint, sizes)):
                band = (10.0, 75.0) if mm else rng.choice([(3.0, 25.0), (5.0, 40.0), (4.0, 30.0)])
                fid = w.fund(None, sid, f"{name} Fund {roman[start_num - 1 + j]}", v_, round(sz, -1), band=band)
                self.funds.append((fid, sid, v_, sz, band))
        # Older predecessor funds for the Q-FLOW sponsors (no people today; they get noise people).
        flow_keys = [f"BS{i}" for i in range(1, 6)] + [f"MS{i}" for i in range(1, 5)] + [f"RS{i}" for i in range(1, 7)]
        for key in flow_keys:
            sid = self.k(key)
            cur_fid = self.k(key + "_F")
            row = next(r for r in w.t["FUND"] if r["fund_id"] == cur_fid)
            self.sponsor_focus[sid] = ["Healthcare Services", "Business Services", "Industrials", "Distribution",
                                       "Technology", "Consumer"] if key.startswith("BS") else \
                rng.choice(focus_pool)
            band = (row["ebitda_min_musd"], row["ebitda_max_musd"])
            self.funds.append((cur_fid, sid, row["vintage_year"], row["size_musd"], band))
            if len([f for f in w.t["FUND"]]) < 80:
                v_old = row["vintage_year"] - rng.randint(4, 6)
                base, cur_num = row["name"].rsplit(" Fund ", 1)
                # (the draw below is kept so the noise RNG stream does not move)
                _ = rng.choice(['I', 'Legacy I']) if not key.startswith("BS") else rng.choice(['II', 'III'])
                # R20 (R19c m3): the predecessor is the previous numeral of the current (cast) fund, with no
                # "Legacy" label, so numbering ascends with vintage (Fund IV 2015 -> Fund V 2020).
                roman = ["I", "II", "III", "IV", "V", "VI", "VII"]
                nm = f"{base} Fund {roman[roman.index(cur_num) - 1]}" if cur_num in roman[1:] else f"{base} Founders Fund"
                while nm in w.used_names:
                    nm += " A"
                fid = w.fund(None, sid, nm, v_old, round(row["size_musd"] * rng.uniform(0.55, 0.8), -1), band=band)
                self.funds.append((fid, sid, v_old, row["size_musd"] * 0.7, band))
        for hs in sorted(self.hl_sponsors - self.cast_sponsors):
            self.sponsor_focus[hs] = ["Healthcare Services"]

    # ---------------------------------------------------------------- 2. companies
    def companies(self):
        w, rng = self.w, self.rng
        l1s = list(NOISE_L1_WEIGHT)
        niches_by_l1 = defaultdict(list)
        for l1, subs in SECTOR_TREE.items():
            for l2, niches in subs.items():
                for n in niches:
                    wt = 0.35 if n == "Skilled Nursing Facilities" else 1.0
                    niches_by_l1[l1].append((n, wt))
        states = list(US_STATES)
        sw = [STATE_WEIGHT[s] for s in states]
        for i in range(NOISE_COMPANIES):
            l1 = rng.choices(l1s, weights=[NOISE_L1_WEIGHT[x] for x in l1s])[0]
            ns = niches_by_l1[l1]
            niche = rng.choices([n for n, _ in ns], weights=[x for _, x in ns])[0]
            ebitda = round(min(180.0, max(0.8, rng.lognormvariate(math.log(3.4), 1.0))), 1)
            st = rng.choices(states, weights=sw)[0]
            n_sites = 0 if ebitda < 5 else min(4, int(rng.expovariate(1.0 / (0.25 + ebitda / 40.0))))
            census = US_STATES[st][1]
            near = [s for s in states if US_STATES[s][1] == census and s != st]
            sites = rng.sample(near, min(n_sites, len(near)))
            cid = self.new_company(niche, ebitda, state=st, sites=sites)
            row = w.company_row[cid]
            if ebitda >= 60 and rng.random() < 0.35:
                row["is_public"] = True
            self.noise_cos.append(cid)
        # A few Canadian-headquartered companies (the US gate) - non-thesis market context.
        for niche in ["Precision Machining", "Specialty Foods", "Managed IT Services"]:
            cid = self.new_company(niche, round(rng.uniform(6, 25), 1), state="CA-ON")
            self._fix_canada(cid, "CA-ON")
            self.noise_cos.append(cid)

    def _fix_canada(self, cid, region):
        for s in self.w.t["COMPANY_SITE"]:
            if s["company_id"] == cid and s["region_id"] == f"US-{region}":
                s["region_id"] = region

    # ---------------------------------------------------------------- 3. people at sponsors and banks
    def sponsor_and_bank_people(self):
        w, rng = self.w, self.rng
        sponsors = [r["sponsor_id"] for r in w.t["SPONSOR"] if r["sponsor_id"] not in self.cast_sponsors
                    and r["sponsor_id"] not in self.sig_role_orgs]
        for sid in sponsors:
            first_v = min([f[2] for f in self.funds if f[1] == sid] or [2012])
            founded = date(first_v - 1, rng.randint(1, 12), 1)
            n_dt = rng.choice([3, 4, 4, 5, 5, 6])
            for j in range(n_dt):
                p = w.person(None, rng=rng)
                start = self.rdate(founded, date(2024, 6, 1)) if j else founded
                end = None
                if j and rng.random() < 0.2:
                    end = self.rdate(start + timedelta(days=500), date(2026, 6, 30))
                title = "Managing Partner" if j == 0 else rng.choice(DT_TITLES[1:])
                w.role(p, sid, "Deal Team", start, end, title=title)
                self.sponsor_people[sid].append((p, start, end, "dt"))
            p = w.person(None, rng=rng)
            start = self.rdate(founded, date(2023, 1, 1))
            w.role(p, sid, "Operating Partner", start, title="Operating Partner")
            self.sponsor_people[sid].append((p, start, None, "op"))
            # business development partner: our CRM counterpart; leads no deal, sits on no board
            p = w.person(None, rng=rng)
            start = self.rdate(max(founded, date(2010, 1, 1)), date(2023, 6, 1))
            w.role(p, sid, "Deal Team", start, title="Partner, Business Development")
            self.sponsor_people[sid].append((p, start, None, "bd"))
            self.bd_people.append((p, sid))
        banks = [r["intermediary_id"] for r in w.t["INTERMEDIARY"]
                 if r["intermediary_id"] not in self.no_touch_interm and r["intermediary_id"] not in self.sig_role_orgs]
        for iid in banks:
            for j in range(rng.choice([1, 1, 2, 2, 3])):
                p = w.person(None, rng=rng)
                start = self.rdate(date(2004, 1, 1), date(2020, 1, 1))
                w.role(p, iid, "Banker", start, title=BANKER_TITLES[min(j, 3)] if j else "Managing Director")
                self.bankers[iid].append((p, start, None))

    def sponsor_lead(self, sid, when):
        cands = [p for p, s, e, kind in self.sponsor_people.get(sid, []) if kind == "dt" and s <= when
                 and (e is None or e >= when)]
        return self.rng.choice(cands) if cands else None

    def banker_lead(self, iid, when):
        cands = [p for p, s, e in self.bankers.get(iid, []) if s <= when]
        return self.rng.choice(cands) if cands else None

    # ---------------------------------------------------------------- 4. ownership and deals
    def ownership_and_deals(self):
        w, rng = self.w, self.rng
        self.owned = set()
        self.fund_size = {r["fund_id"]: float(r["size_musd"]) for r in w.t["FUND"]}
        self.deployed = defaultdict(float)
        for o in w.t["OWNERSHIP"]:
            self.deployed[o["fund_id"]] += float(o["equity_invested_musd"] or 0)
        cos_by_l1 = defaultdict(list)
        for cid in self.noise_cos:
            cos_by_l1[self.names_up(cid)[-1]].append(cid)
        self.cos_by_l1 = cos_by_l1
        self.addon_targets_used = set()
        # league advisors for in-window non-thesis volume (HL lands around 10th in a raw league table)
        self.league = [self.k("ADV1"), self.k("ADV2"), self.k("ADV3"), self.k("ADV4")] + self.other_interm[:3]
        self.league_quota = {i: rng.randint(8, 11) if i in self.covered_interm else rng.randint(10, 13)
                             for i in self.league}

        def pick_target(focus, band, when, want_thesis=None):
            pool = [c for l1 in focus for c in cos_by_l1.get(l1, [])]
            pool = [c for c in pool if c not in self.owned and band[0] * 0.7 <= w.company_row[c]["ebitda_musd"] <= band[1] * 1.2
                    and not w.company_row[c]["is_public"] and w.company_row[c]["hq_region_id"].startswith("US-")
                    and w.company_row[c]["founded_year"] <= when.year - 3
                    and (want_thesis is None or self.in_thesis(c) == want_thesis)]
            return rng.choice(pool) if pool else None

        # Northwind noise: Fund II realized holdings, Fund III current and realized holdings.
        nw_plan = [("NW_F2", 2014, 2018, True)] * 7 + [("NW_F3", 2019, 2021, False)] * 6 + [("NW_F3", 2019, 2020, True)] * 2
        for fkey, y0, y1, exited in nw_plan:
            fid = self.k(fkey)
            when = self.rdate(date(y0, 3, 1), date(y1, 9, 1) if y1 < 2021 else date(2021, 8, 31))
            tgt = pick_target(["Healthcare Services", "Distribution"], (6.0, 30.0), when, want_thesis=True)
            if tgt is None:
                continue
            exit_d = self.rdate(date(max(2018, when.year + 4), 1, 15), date(2025, 6, 30)) if exited else None
            if fkey == "NW_F2" and exit_d is None:
                exit_d = self.rdate(date(when.year + 4, 1, 15), date(2024, 6, 30))
            self._platform(tgt, fid, self.nw, when, exit_d, allow_sbo=False, nw=True)

        # Competitor funds: platforms, exits (SBO or strategic). R20: fewer platforms per fund (about one
        # per NOISE_PLATFORM_MUSD of commitments) so that add-ons, not platforms, are the majority of deals.
        flow_funds = {self.k(f"{p}{i}_F") for p in ("BS", "MS", "RS") for i in range(1, 7) if f"{p}{i}_F" in w.key}
        for fid, sid, vint, size, band in list(self.funds):
            n = max(1, min(6, int(round(size / NOISE_PLATFORM_MUSD * rng.uniform(0.7, 1.2)))))
            if fid in flow_funds:
                n = rng.randint(1, 2)
            focus = self.sponsor_focus.get(sid, ["Industrials"])
            for _ in range(n):
                lo = date(vint, 4, 1)
                hi = min(date(vint + 5, 12, 31), date(2026, 8, 31))
                when = self.rdate(lo, hi)
                want = None
                if when >= T5Y and (sid in self.hl_sponsors or self.flow_thesis_deals >= NOISE_FLOW_THESIS_DEALS):
                    want = False
                tgt = pick_target(focus, band, when, want)
                if tgt is None:
                    continue
                hold = rng.lognormvariate(math.log(5.8), 0.28)
                exit_d = when + timedelta(days=int(hold * 365.25))
                if exit_d > date(2026, 9, 15):
                    exit_d = None
                self._platform(tgt, fid, sid, when, exit_d, allow_sbo=True)

        # Companies that are the target of an in-window Fund IV thesis deal are nodes of the Q-FLOW
        # graph. An unadvised add-on by a platform that is NOT such a node forms its own small
        # component (platform plus add-ons), which changes no intermediary's betweenness.
        self.flow_graph_cos = {t_["target_id"] for t_ in w.t["TRANSACTION"]
                               if T5Y <= t_["close_date"] <= AS_OF and self.in_thesis(t_["target_id"])}

        # In-window non-thesis volume for the league advisors (not in the Q-FLOW graph). R20: run as
        # add-ons by sponsor-owned platforms (buy-and-build), falling back to a platform deal only when
        # no platform can buy a suitable target.
        for iid in self.league:
            have = sum(1 for t_ in w.t["TRANSACTION"] if t_["close_date"] >= T5Y and any(
                p["txn_id"] == t_["txn_id"] and p["org_id"] == iid for p in self._parties_of(t_["txn_id"])))
            need = self.league_quota[iid] - have
            for _ in range(max(0, need)):
                when = self.rdate(date(2021, 11, 1), date(2026, 8, 31))
                buyers = [x for x in self.platforms if x[2] + timedelta(days=120) <= when
                          and (x[3] is None or when <= x[3]) and x[4] not in self.hl_sponsors]
                done = False
                for cid, fid, s, e, sid in rng.sample(buyers, min(6, len(buyers))):
                    if self._addon(cid, sid, when, forced_adv=iid, want_thesis=False):
                        done = True
                        break
                if done:
                    continue
                funds = [f for f in self.funds if f[2] <= when.year <= f[2] + 5 and f[1] not in self.hl_sponsors
                         and self.deployed[f[0]] < 0.85 * self.fund_size[f[0]]]
                if not funds:
                    continue
                fid, sid, vint, size, band = rng.choice(funds)
                tgt = pick_target(["Technology", "Consumer", "Industrials", "Life Sciences", "Business Services",
                                   "Distribution"], band, when, want_thesis=False)
                if tgt is None:
                    continue
                self._platform(tgt, fid, sid, when, None, allow_sbo=False, forced_adv=iid)

        # Add-ons by platform companies during their hold (only the ones inside the 10-year window are
        # drawn; earlier history is not in the TRANSACTION table). R20: buy-and-build platforms do
        # several add-ons each (NOISE_ADDON_COUNTS), so add-ons are the majority of deals.
        for cid, fid, s, e, sid in list(self.platforms):
            for _ in range(rng.choice(NOISE_ADDON_COUNTS)):
                lo = max(s + timedelta(days=120), T10Y)
                hi = min(e or date(2026, 8, 31), date(2026, 8, 31))
                if (hi - lo).days < 120:
                    break
                self._addon(cid, sid, self.rdate(lo, hi))

        # A few dividend recaps (owner + debt advisor) on current platforms, outside the Q-FLOW scope.
        cur = [(c, f, s, sid) for c, f, s, e, sid in self.platforms if e is None and s < date(2023, 1, 1)
               and not self.in_thesis(c) and sid not in self.cast_sponsors]
        for c, f, s, sid in rng.sample(cur, min(NOISE_RECAPS, len(cur))):
            when = self.rdate(s + timedelta(days=500), date(2026, 6, 30))
            if when < T10Y:
                continue
            iid = self._pick_adv(when, False)
            parties = [(sid, "owner", f, self.sponsor_lead(sid, when))]
            if iid:
                parties.append((iid, "debt_advisor", None, self.banker_lead(iid, when)))
            w.txn(c, when, "platform", "sponsor", "dividend_recap", parties, rng=rng)

    def _addon(self, cid, sid, when, forced_adv=None, want_thesis=None):
        """R20: platform `cid` (owned by sponsor `sid`) buys a smaller company: same level-2 niche when
        possible, else the same level-1 sector; founded at least 2 years before the deal; never owned by a
        fund and never bought before. In-window Fund IV thesis add-ons are unadvised and only by platforms
        outside the Q-FLOW graph, so the graph's intermediary betweenness cannot move.
        Returns True if a deal was written."""
        w, rng = self.w, self.rng
        up = self.names_up(cid)
        cap = min(6.0, w.company_row[cid]["ebitda_musd"])

        def ok(c):
            r = w.company_row[c]
            if c in self.owned or c in self.addon_targets_used or c == cid or r["ebitda_musd"] >= cap \
                    or r["founded_year"] > when.year - 2 or not r["hq_region_id"].startswith("US-"):
                return False
            th = when >= T5Y and self.in_thesis(c)
            if want_thesis is not None and self.in_thesis(c) != want_thesis:
                return False
            if th and (forced_adv or cid in self.flow_graph_cos):
                return False
            return True
        pool = [c for c in self.cos_by_l1.get(up[-1], []) if self.names_up(c)[1] == up[1] and ok(c)]
        if not pool:
            pool = [c for c in self.cos_by_l1.get(up[-1], []) if ok(c)]
        if not pool:
            return False
        tgt = rng.choice(pool)
        thesis_win = when >= T5Y and self.in_thesis(tgt)
        advs = []
        if forced_adv:
            advs.append((forced_adv, "sell_side_advisor", self.banker_lead(forced_adv, when)))
        elif not thesis_win and rng.random() < (0.3 if when >= T5Y else 0.45):
            iid = self._pick_adv(when, False)
            if iid:
                advs.append((iid, "sell_side_advisor", self.banker_lead(iid, when)))
        w.buyout(tgt, when, None, advisors=advs, deal_role="add_on", platform_id=cid, buyer_lead=None, rng=rng)
        self.addon_targets_used.add(tgt)
        self.addon_close[tgt] = (when, cid)
        return True

    def _parties_of(self, tid):
        if not hasattr(self, "_pcache") or self._pcache_n != len(self.w.t["TRANSACTION_PARTY"]):
            self._pcache = defaultdict(list)
            for p in self.w.t["TRANSACTION_PARTY"]:
                self._pcache[p["txn_id"]].append(p)
            self._pcache_n = len(self.w.t["TRANSACTION_PARTY"])
        return self._pcache[tid]

    def _pick_adv(self, when, thesis_win, forced=None):
        rng = self.rng
        if forced:
            return forced
        if thesis_win:
            # regional advisors only, at most two new thesis deals each, so no one advisor becomes a new hub
            pool = [i for i in self.covered_interm[8:] if self.flow_adv_use[i] < NOISE_FLOW_PER_ADVISOR]
            if not pool:
                return None
            i = rng.choice(pool)
            self.flow_adv_use[i] += 1
            return i
        if when >= T5Y:
            pool = self.covered_interm + self.other_interm
            return rng.choice(pool)
        return rng.choice(self.covered_interm + self.other_interm + [self.k("CEDAR"), self.k("BIGBANK")])

    def _platform(self, tgt, fid, sid, when, exit_d, allow_sbo=True, nw=False, forced_adv=None, seller=None):
        """Record a platform buyout (transaction if in the last 10 years), ownership, and its exit."""
        w, rng = self.w, self.rng
        thesis_win = when >= T5Y and self.in_thesis(tgt)
        if thesis_win and (nw or sid in self.hl_sponsors or sid in self.cast_sponsors or seller and (
                seller[1] in self.hl_sponsors or seller[1] in self.cast_sponsors)):
            return False
        if thesis_win and self.flow_thesis_deals >= NOISE_FLOW_THESIS_DEALS:
            return False
        equity = round(w.company_row[tgt]["ebitda_musd"] * rng.uniform(0.75, 0.95) * w.multiple(
            w.sector_name[w.company_row[tgt]["sector_id"]], w.company_row[tgt]["ebitda_musd"], rng) * rng.uniform(0.4, 0.55), 1)
        if self.deployed[fid] + equity > self.fund_size[fid] or equity > NOISE_MAX_CHECK_PCT * self.fund_size[fid]:
            return False   # the fund is fully invested (or the check is too large for it): no new platform
        self.deployed[fid] += equity
        self.owned.add(tgt)
        stake = "minority" if (not nw and rng.random() < 0.05 and seller is None) else "majority"
        structure = "minority" if stake == "minority" else rng.choices(["control_buyout", "majority_recap"], [0.82, 0.18])[0]
        if when >= T10Y:
            advs = []
            if forced_adv or rng.random() < (0.85 if when >= T5Y else 0.75):
                iid = self._pick_adv(when, thesis_win, forced_adv)
                if iid:
                    advs.append((iid, "sell_side_advisor", self.banker_lead(iid, when)))
                    if rng.random() < 0.18 and not thesis_win:
                        iid2 = self._pick_adv(when, False)
                        if iid2 and iid2 != iid:
                            advs.append((iid2, "buy_side_advisor", self.banker_lead(iid2, when)))
            buyer_lead = None if nw else self.sponsor_lead(sid, when)
            seller_lead = self.sponsor_lead(seller[1], when) if seller else None
            parties = [(sid, "buyer", fid, buyer_lead)]
            seller_type = "founder_family" if rng.random() < 0.88 else "corporate"
            if seller:
                parties.append((seller[1], "seller", seller[0], seller_lead))
                seller_type = "sponsor"
            for a in advs:
                parties.append((a[0], a[1], None, a[2]))
            if stake == "minority":
                structure = "minority"
            w.txn(tgt, when, "platform", seller_type, structure, parties, rng=rng)
            if thesis_win:
                self.flow_thesis_deals += 1
        oid_row = {"ownership_id": w.ids.next("O"), "company_id": tgt, "fund_id": fid, "start_date": when,
                   "end_date": exit_d, "stake_type": stake, "equity_invested_musd": round(equity, 2)}
        w.t["OWNERSHIP"].append(oid_row)
        self.platforms.append((tgt, fid, when, exit_d, sid))
        if exit_d is not None and allow_sbo and exit_d < date(2026, 9, 1) and rng.random() < 0.38:
            buyers = [f for f in self.funds if f[2] <= exit_d.year <= f[2] + 5 and f[1] != sid
                      and f[4][0] * 0.7 <= w.company_row[tgt]["ebitda_musd"] <= f[4][1] * 1.3]
            if buyers:
                bf = rng.choice(buyers)
                hold = rng.lognormvariate(math.log(5.5), 0.28)
                ex2 = exit_d + timedelta(days=int(hold * 365.25))
                ok = self._platform(tgt, bf[0], bf[1], exit_d, ex2 if ex2 <= date(2026, 9, 15) else None,
                                    allow_sbo=False, seller=(fid, sid))
                if ok:
                    return True
        return True

    # ---------------------------------------------------------------- 5. company people
    def _ceo_history(self, founded, start0, founder_ceo, sponsor_owned, want_pred):
        """R20 (R19c M1): the recorded CEO history of a noise company, oldest first, as
        (start, end, is_founder); the last entry is the current CEO (end None).
        * A founder serves FOUNDER_TENURE_* years (lognormal, median 15, capped 34). A founder whose
          tenure reaches AS_OF (within a year) is still in seat; otherwise a non-founder successor is.
        * Successors serve NOISE_CEO_TENURE_* years (lognormal, median 6, p5 about 3, p95 about 12).
        * A non-founder never starts within 2 years of founding (the first CEO is the founder).
        * At most one predecessor is recorded; history before it is simply not in the data."""
        crng = self.crng
        yrs = lambda x: timedelta(days=int(round(x * 365.25)))  # noqa: E731
        clamp = lambda x, lo, hi: min(hi, max(lo, x))  # noqa: E731
        succ_len = lambda: clamp(crng.lognormvariate(math.log(NOISE_CEO_TENURE_MED), NOISE_CEO_TENURE_SIG), 2.0, 15.0)  # noqa: E731
        tf = clamp(crng.lognormvariate(math.log(FOUNDER_TENURE_MED), FOUNDER_TENURE_SIG),
                   FOUNDER_TENURE_MIN, FOUNDER_TENURE_MAX)
        if founder_ceo:
            f_end = start0 + yrs(tf)
            if f_end >= AS_OF - timedelta(days=365):
                return [(start0, None, True)]
            cur_len = clamp(crng.lognormvariate(math.log(5.0), 0.6), 0.5, 14.0)
            s_cur = min(max(AS_OF - yrs(cur_len), f_end + timedelta(days=crng.randint(20, 150))), date(2026, 6, 1))
            p_end = s_cur - timedelta(days=crng.randint(1, 60))
            if p_end <= f_end + yrs(1.0):                     # the founder handed over directly
                return [(start0, p_end, True), (s_cur, None, False)]
            if crng.random() < 0.55:
                p_start = p_end - yrs(succ_len())
                if p_start <= f_end + yrs(1.0):               # the predecessor followed the founder
                    return [(start0, f_end, True), (f_end + timedelta(days=crng.randint(20, 120)), p_end, False),
                            (s_cur, None, False)]
                return [(p_start, p_end, False), (s_cur, None, False)]
            return [(s_cur, None, False)]
        s_cur = start0
        if not sponsor_owned:                                  # independent company: professional CEO
            s_cur = AS_OF - yrs(clamp(crng.lognormvariate(math.log(6.0), 0.6), 0.5, 20.0))
        s_cur = min(max(s_cur, founded + yrs(2.0)), date(2026, 6, 1))
        if want_pred and s_cur > founded + yrs(4.0):
            p_end = s_cur - timedelta(days=crng.randint(1, 60))
            p_start = p_end - yrs(succ_len())
            if p_start > founded + yrs(2.0):
                return [(p_start, p_end, False), (s_cur, None, False)]
            fs = founded + timedelta(days=crng.randint(0, 400))
            if (p_end - fs).days / 365.25 <= FOUNDER_TENURE_MAX:  # reaches back to founding: the founder
                return [(fs, p_end, True), (s_cur, None, False)]
        return [(s_cur, None, False)]

    def company_people(self):
        w, rng = self.w, self.rng
        own_by = defaultdict(list)
        for o in w.t["OWNERSHIP"]:
            own_by[o["company_id"]].append(o)
        self.own_by_co = own_by
        f3 = self.k("NW_F3")
        career_pool = []   # (person, current company, current start) eligible to have a prior role
        for cid in self.noise_cos:
            row = w.company_row[cid]
            rev = row["revenue_musd"]
            owners = sorted(own_by.get(cid, []), key=lambda o: o["start_date"])
            cur = [o for o in owners if o["end_date"] is None]
            nw_f3_now = any(o["fund_id"] == f3 for o in cur)
            founded = date(row["founded_year"], rng.randint(1, 12), 1)
            sponsor_ever = bool(owners)
            # CEO (exactly one current)
            founder_ceo = (not sponsor_ever or rng.random() < 0.25) and rng.random() < 0.5 and founded >= date(1975, 1, 1)
            if founder_ceo:
                start = founded + timedelta(days=rng.randint(0, 400))
            elif cur:
                start = self.rdate(cur[0]["start_date"] - timedelta(days=400), min(cur[0]["start_date"] + timedelta(days=900), date(2026, 6, 1)))
            else:
                start = self.rdate(max(founded, date(2004, 1, 1)), date(2025, 6, 1))
            start = max(start, founded)
            # R20 (R19c M1): realistic CEO history. Founders serve FOUNDER_TENURE_* years, successors
            # NOISE_CEO_TENURE_*; at most the current CEO and one predecessor are recorded.
            hist = self._ceo_history(founded, start, founder_ceo, bool(cur), rng.random() < 0.3)
            ceo = w.person(None, rng=rng)
            for j, (s_, e_, fnd) in enumerate(hist[:-1]):
                prev = w.person(None, rng=self.crng)
                w.role(prev, cid, "CEO", s_, e_, title="Founder and CEO" if fnd else "Chief Executive Officer",
                       founder=fnd)
            s_, _e, fnd = hist[-1]
            title = "Founder and CEO" if fnd else "Chief Executive Officer"
            acq = self.addon_close.get(cid)
            if acq:
                # R20 (R19c M2): an acquired add-on is a division of its buyer. Its top executive keeps the
                # CEO role type (R08 invariant: one current CEO per company) but, from the close, runs it
                # as division president; the pre-close tenure (a founder's included) ends at the close.
                close, plat = acq
                div = f"President, {w.name_of[plat]} division"
                if s_ < close - timedelta(days=365):
                    w.role(ceo, cid, "CEO", s_, close, title=title, founder=fnd)
                    w.role(ceo, cid, "CEO", close, title=div)
                else:   # appointed at (or after) the acquisition: no sub-year stub tenure before it
                    w.role(ceo, cid, "CEO", max(s_, close), title=div)
                    s_ = max(s_, close)
            else:
                w.role(ceo, cid, "CEO", s_, title=title, founder=fnd)
            if len(hist) == 1 and not nw_f3_now:
                career_pool.append((ceo, cid, s_))
            # CFO
            if rng.random() < (0.85 if rev >= 40 else 0.4):
                cstart = self.rdate(max(founded, date(2012, 1, 1)), date(2026, 7, 1))
                if rng.random() < 0.5:
                    cstart = self.rdate(max(founded, date(2018, 1, 1)), date(2024, 12, 31))
                cfo = w.person(None, rng=rng)
                w.role(cfo, cid, "CFO", cstart, title="Chief Financial Officer")
                if not nw_f3_now:
                    career_pool.append((cfo, cid, cstart))
            # COO / President
            if rev >= 50 and rng.random() < 0.32:
                rt = rng.choice(["COO", "COO", "President"])
                cstart = self.rdate(max(founded, date(2014, 1, 1)), date(2025, 12, 1))
                p = w.person(None, rng=rng)
                w.role(p, cid, rt, cstart, title="Chief Operating Officer" if rt == "COO" else "President")
                if not nw_f3_now:
                    career_pool.append((p, cid, cstart))
            # Board: owner designees and independents
            for o in cur:
                sid = w.fund_sponsor[o["fund_id"]]
                if sid == self.nw:
                    if o["fund_id"] == f3:
                        w.role(rng.choice(self.seeds[:4]), cid, "Board", o["start_date"], title="Director")
                        self.no_career.add(cid)
                    continue
                lead = self.sponsor_lead(sid, o["start_date"])
                if lead:
                    w.role(lead, cid, "Board", o["start_date"], title="Director")
            for o in owners:
                if o["end_date"] is not None and w.fund_sponsor[o["fund_id"]] != self.nw:
                    lead = self.sponsor_lead(w.fund_sponsor[o["fund_id"]], o["start_date"])
                    if lead and o["end_date"] > o["start_date"]:
                        w.role(lead, cid, "Board", o["start_date"], o["end_date"], title="Director")
            if not nw_f3_now and rng.random() < (0.35 if sponsor_ever else 0.15):
                bstart = self.rdate(max(founded, date(2015, 1, 1)), date(2025, 6, 30))
                acq = self.addon_close.get(cid)
                # R20 (R19c M2): an acquired add-on has no board of its own after the close
                if acq is None or bstart < acq[0] - timedelta(days=365):
                    p = w.person(None, rng=rng)
                    w.role(p, cid, "Board", bstart, acq[0] if acq else None, title="Independent Director")
        # prior careers: a role at another noise company that ended before the current one started
        pool_cos = [c for c in self.noise_cos if c not in self.no_career]
        for p, cid, start in career_pool:
            if rng.random() > 0.33 or start < date(2008, 1, 1):
                continue
            other = rng.choice(pool_cos)
            if other == cid:
                continue
            end = start - timedelta(days=rng.randint(15, 300))
            pstart = end - timedelta(days=rng.randint(700, 2900))
            founded = date(w.company_row[other]["founded_year"], 1, 1)
            if pstart < founded:
                continue
            rt = rng.choice(["CFO", "COO", "President", "CFO"])
            w.role(p, other, rt, pstart, end, title={"CFO": "Chief Financial Officer", "COO": "Chief Operating Officer",
                                                      "President": "President"}[rt])
        # signal companies without a current CEO: one non-founder CEO, a Knows leaf
        roles_by_org = defaultdict(list)
        for r in w.t["ROLE_HISTORY"]:
            roles_by_org[r["org_id"]].append(r)
        for cid in self.sig_companies:
            rs = roles_by_org.get(cid, [])
            if any(r["role_type"] == "CEO" and r["end_date"] is None for r in rs):
                continue
            row = w.company_row[cid]
            lo = date(max(row["founded_year"], 2004), 1, 1)
            ends = [r["end_date"] for r in rs if r["end_date"] is not None]
            assert all(r["end_date"] is not None for r in rs), cid
            if ends:
                lo = max(lo, max(ends) + timedelta(days=rng.randint(20, 120)))
            start = self.rdate(lo, max(lo, date(2024, 6, 1)))
            p = w.person(None, rng=rng)
            w.role(p, cid, "CEO", start, title="Chief Executive Officer")

    # ---------------------------------------------------------------- 6. crafted near-misses
    def near_misses(self):
        """Entities one condition away from qualifying, so the rules visibly do the work (8.3)."""
        w, rng, k = self.w, self.rng, self.k
        ctx = [k("ADV2"), k("RADV5"), k("ADV6")]

        def mk(label, niche, ebitda, revenue, state, founded, sites=None, public=False, region=None):
            name = w.company_name(niche, rng)
            cid = w.company(None, name, niche, state if region is None else region, revenue, ebitda, founded=founded,
                            sites=sites, rng=rng, is_public=public)
            if region:
                self._fix_canada(cid, region)
            self.crafted.append(cid); self.no_career.add(cid); self.near_miss[label] = cid
            return cid

        def founder_team(cid, ceo_start, director_start=None):
            p = w.person(None, rng=rng); w.role(p, cid, "CEO", ceo_start, title="Founder and CEO", founder=True)
            p = w.person(None, rng=rng); w.role(p, cid, "CFO", "2017-03-06", title="Chief Financial Officer")
            if director_start:
                p = w.person(None, rng=rng); w.role(p, cid, "Board", director_start, title="Independent Director")

        # (a) EBITDA just over the band: would score 70 (Tier A) at EBITDA <= 40.0
        c = mk("EBITDA_40_6", "Hospice Providers", 40.6, 268.0, "GA", 2003, sites=["SC", "AL"])
        founder_team(c, "2003-05-01", "2026-01-12")
        w.signal(c, "BANKER_ENGAGED", "2026-07-02", interm=ctx[0])
        w.signal(c, "DEBT_MATURITY", "2025-08-14", event="2027-09-30", magnitude=160.0)
        w.crm(k("MD_MER"), "2026-04-09", "meeting", "positive", org=c)
        # (b) US gate: Ontario HQ, would score 75
        c = mk("CANADA_HQ", "Payroll & HR Outsourcing", 18.0, 88.0, None, 2004, region="CA-ON")
        founder_team(c, "2004-02-02", "2025-12-01")
        w.signal(c, "BANKER_ENGAGED", "2026-05-27", interm=ctx[1])
        w.signal(c, "DEBT_MATURITY", "2025-09-18", event="2027-06-30", magnitude=70.0)
        w.crm(k("VP"), "2026-02-19", "call", "positive", org=c)
        # (c) public company: would score 70
        c = mk("PUBLIC", "Environmental Testing", 28.0, 152.0, "CO", 1996, sites=["UT"], public=True)
        founder_team(c, "1996-09-03")
        w.signal(c, "BANKER_ENGAGED", "2026-08-03", interm=ctx[2])
        w.signal(c, "DEBT_MATURITY", "2025-06-12", event="2027-11-30", magnitude=110.0)
        w.crm(k("OP"), "2026-01-28", "meeting", "positive", org=c)
        # (d) exit window: held 4.9 years by a 2016-vintage fund (needs 5+). Act-1 score 50.
        old = sorted([f for f in self.funds if 2015 <= f[2] <= 2018 and f[1] not in self.hl_sponsors
                      and f[1] not in self.cast_sponsors], key=lambda f: (abs(f[2] - 2016), f[0]))[0]
        c = mk("EXIT_4_9Y", "Insurance Claims Processing", 14.0, 70.0, "OH", 2001)
        p = w.person(None, rng=rng); w.role(p, c, "CEO", "2015-04-06", title="Chief Executive Officer")
        p = w.person(None, rng=rng); w.role(p, c, "President", "2019-01-07", title="President")
        lead = self.sponsor_lead(old[1], date(2021, 11, 15))
        w.txn(c, "2021-11-15", "platform", "founder_family", "control_buyout", [(old[1], "buyer", old[0], lead)], rng=rng)
        self.flow_thesis_deals += 1
        w.t["OWNERSHIP"].append({"ownership_id": w.ids.next("O"), "company_id": c, "fund_id": old[0],
                                 "start_date": date(2021, 11, 15), "end_date": None, "stake_type": "majority",
                                 "equity_invested_musd": 61.0})
        if lead:
            w.role(lead, c, "Board", "2021-11-15", title="Director")
        w.signal(c, "BANKER_ENGAGED", "2026-06-15", interm=ctx[0])
        w.signal(c, "DEBT_MATURITY", "2025-12-03", event="2027-05-31", magnitude=55.0)
        # (e) CFO from a company that became PE-backed only after she left (temporal join rejects). Score 50.
        prior = mk("CFO_PRIOR_EMPLOYER", "Precision Machining", 11.0, 78.0, "MI", 1988)
        p0 = w.person(None, rng=rng); w.role(p0, prior, "CEO", "2012-05-07", title="Chief Executive Officer")
        nfund = sorted([f for f in self.funds if f[2] >= 2021 and f[1] not in self.hl_sponsors
                        and f[1] not in self.cast_sponsors], key=lambda f: f[0])[0]
        w.txn(prior, "2025-09-15", "platform", "founder_family", "control_buyout",
              [(nfund[1], "buyer", nfund[0], self.sponsor_lead(nfund[1], date(2025, 9, 15)))], rng=rng)
        w.t["OWNERSHIP"].append({"ownership_id": w.ids.next("O"), "company_id": prior, "fund_id": nfund[0],
                                 "start_date": date(2025, 9, 15), "end_date": None, "stake_type": "majority",
                                 "equity_invested_musd": 42.0})
        c = mk("CFO_NOT_PE", "Compliance & Training Services", 12.5, 64.0, "IN", 2006)
        p = w.person(None, rng=rng); w.role(p, c, "CEO", "2014-10-06", title="Chief Executive Officer")
        cfo = w.person(None, rng=rng)
        w.role(cfo, prior, "CFO", "2019-02-04", "2025-06-27", title="Chief Financial Officer")
        w.role(cfo, c, "CFO", "2025-08-04", title="Chief Financial Officer")
        w.signal(c, "DEBT_MATURITY", "2026-02-10", event="2027-08-31", magnitude=30.0)
        w.crm(k("VP"), "2026-03-03", "meeting", "positive", org=c)
        # (f) 11-month tenure overlap with a seed: Marcus Whitfield and this CEO overlapped 333 days.
        c = mk("OVERLAP_11M", "Healthcare Revenue Cycle Services", 15.0, 82.0, "KY", 2002)
        w.role(k("OP"), c, "COO", "2009-03-02", "2014-08-15", title="Chief Operating Officer")
        p = w.person(None, rng=rng); w.role(p, c, "CEO", "2013-09-16", title="Chief Executive Officer")
        p = w.person(None, rng=rng); w.role(p, c, "CFO", "2016-01-11", title="Chief Financial Officer")
        w.signal(c, "BANKER_ENGAGED", "2026-05-06", interm=ctx[1])
        w.signal(c, "DEBT_MATURITY", "2026-01-15", event="2027-10-31", magnitude=40.0)
        # (g) similarity just under the Q-ADDON cutoff: 2 shared of 21 = 0.0952 < 0.10
        c = mk("JACCARD_0_095", "Calibration Services", 7.5, 41.0, "TX", 2008, sites=["NM"])
        p = w.person(None, rng=rng); w.role(p, c, "CEO", "2008-06-02", title="Founder and CEO", founder=True)
        p = w.person(None, rng=rng); w.role(p, c, "COO", "2018-04-02", title="Chief Operating Officer")
        for key in ("C02", "C05"):
            w.link(c, k(key), "<1M", rng=rng)
        self.jaccard_nm = c
        # (h) supplies a FORMER Fund III holding (exited 2024): the conflict rule is current-only
        self.former_f3_nm = mk("SUPPLIES_FORMER_F3", "Medical & Lab Supply Distribution", 9.0, 105.0, "MO", 1999)
        p = w.person(None, rng=rng); w.role(p, self.former_f3_nm, "CEO", "2011-11-07", title="Chief Executive Officer")
        p = w.person(None, rng=rng); w.role(p, self.former_f3_nm, "COO", "2019-08-05", title="Chief Operating Officer")

    # ---------------------------------------------------------------- 7. commercial links
    def links(self):
        w, rng = self.w, self.rng
        pool = [c for c in self.noise_cos] + [c for c in self.sig_companies if c not in self.link_protected]
        by_group = defaultdict(list)
        for c in pool:
            for n in self.names_up(c):
                by_group[n].append(c)
        sup_classes = []
        for c in pool:
            names = self.names_up(c)
            cls = next((n for n in names if n in NOISE_SUPPLY), None)
            if cls:
                sup_classes.append((c, cls))
        sw = [w.company_row[c]["revenue_musd"] ** 0.75 for c, _ in sup_classes]
        existing = {(l["supplier_id"], l["customer_id"]) for l in w.t["COMMERCIAL_LINK"]}
        made, tries = 0, 0
        while made < NOISE_LINKS and tries < NOISE_LINKS * 20:
            tries += 1
            s, cls = rng.choices(sup_classes, weights=sw)[0]
            grp = rng.choice(NOISE_SUPPLY[cls])
            cands = by_group.get(grp, [])
            if not cands:
                continue
            c = cands[rng.randrange(len(cands))]
            if c == s or (s, c) in existing or (c, s) in existing:
                continue
            if w.company_row[c]["revenue_musd"] < 8 and rng.random() < 0.7:
                continue
            rev = w.company_row[s]["revenue_musd"]
            band = "<1M" if rev < 30 else rng.choice(["<1M", "1-5M"]) if rev < 120 else rng.choice(["1-5M", "1-5M", "5-20M", "20M+"])
            w.link(s, c, band, since=rng.randint(2008, 2025), rng=rng)
            existing.add((s, c)); made += 1
        # crafted: the Q-ADDON near-miss gets 3 own customers; the former-F3 near-miss supplies the exited holding
        own3 = [c for c in self.noise_cos if "Industrials" in self.names_up(c) and not self.in_thesis(c)][:3]
        for c in own3:
            w.link(self.jaccard_nm, c, "<1M", rng=rng)
        f3 = self.k("NW_F3")
        exited = sorted(o["company_id"] for o in w.t["OWNERSHIP"] if o["fund_id"] == f3 and o["end_date"] is not None
                        and o["company_id"] in set(self.noise_cos))
        if exited:
            w.link(self.former_f3_nm, exited[0], "1-5M", since=2018, rng=rng)

    # ---------------------------------------------------------------- 8. score plan, signals, CRM, pipeline
    def _index(self):
        w = self.w
        self.roles_by_org, self.roles_by_person = defaultdict(list), defaultdict(list)
        for r in w.t["ROLE_HISTORY"]:
            self.roles_by_org[r["org_id"]].append(r); self.roles_by_person[r["person_id"]].append(r)
        self.own_by_co = defaultdict(list)
        for o in w.t["OWNERSHIP"]:
            self.own_by_co[o["company_id"]].append(o)

    def structural(self, cid):
        """Readiness components that come from roles and ownership (mirrors QUESTIONS.md v2)."""
        w = self.w
        comps = {}
        rs = self.roles_by_org.get(cid, [])
        cur_own = [o for o in self.own_by_co.get(cid, []) if o["end_date"] is None]
        for cf in rs:
            if cf["role_type"] == "CFO" and cf["end_date"] is None and T_18M <= cf["start_date"] <= AS_OF:
                for pr in self.roles_by_person[cf["person_id"]]:
                    if pr["org_id"] == cid or pr["end_date"] is None:
                        continue
                    if _addm(cf["start_date"], -12) <= pr["end_date"] <= cf["start_date"]:
                        for o in self.own_by_co.get(pr["org_id"], []):
                            if min(pr["end_date"], o["end_date"] or AS_OF) >= max(pr["start_date"], o["start_date"]):
                                comps["R_CFO_FROM_PE"] = 15
        for o in cur_own:
            if o["start_date"] <= T5Y and w.fund_vintage[o["fund_id"]] <= AS_OF.year - 8:
                comps["R_EXIT_WINDOW"] = 15
        ceo_f = [r for r in rs if r["role_type"] == "CEO" and r["end_date"] is None and r["is_founder"]
                 and r["start_date"] <= T_15Y]
        if ceo_f and not [r for r in rs if r["role_type"] in ("President", "COO") and r["end_date"] is None]:
            comps["R_SUCCESSION"] = 10
        owner_sp = {w.fund_sponsor[o["fund_id"]] for o in cur_own}
        for b in rs:
            if b["role_type"] == "Board" and T_12M <= b["start_date"] <= AS_OF:
                pr = self.roles_by_person[b["person_id"]]
                if not any(x["org_id"] == cid and x["role_type"] != "Board" for x in pr) and \
                        not any(x["org_id"] in owner_sp and x["end_date"] is None for x in pr):
                    comps["R_NEW_DIRECTOR"] = 5
        return comps

    def plan_scores(self):
        """Every eligible bulk noise company ends at <= NOISE_SCORE_CAP; fix structure if needed."""
        w, rng = self.w, self.rng
        self._index()
        self.budget = {}
        for cid in self.noise_cos:
            if not self.eligible(cid):
                continue
            for _ in range(4):
                comps = self.structural(cid)
                total = self.fit(cid) + sum(comps.values())
                if total <= NOISE_SCORE_CAP:
                    break
                rs = self.roles_by_org[cid]
                if "R_NEW_DIRECTOR" in comps:
                    for b in rs:
                        if b["role_type"] == "Board" and b["start_date"] >= T_12M:
                            b["start_date"] = self.rdate(date(2022, 1, 1), date(2025, 3, 1))
                elif "R_CFO_FROM_PE" in comps:
                    for cf in rs:
                        if cf["role_type"] == "CFO" and cf["end_date"] is None and cf["start_date"] >= T_18M:
                            cf["start_date"] = self.rdate(date(2023, 1, 1), date(2024, 12, 1))
                            for pr in self.roles_by_person[cf["person_id"]]:
                                if pr is not cf and pr["end_date"] and pr["end_date"] > cf["start_date"]:
                                    pr["end_date"] = cf["start_date"] - timedelta(days=30)
                                    pr["start_date"] = min(pr["start_date"], pr["end_date"] - timedelta(days=400))
                elif "R_SUCCESSION" in comps:
                    p = w.person(None, rng=rng)
                    w.role(p, cid, "COO", self.rdate(date(2016, 1, 1), date(2024, 6, 1)), title="Chief Operating Officer")
                    self._index()
                else:
                    break
            comps = self.structural(cid)
            used = self.fit(cid) + sum(comps.values())
            assert used <= NOISE_SCORE_CAP, (cid, used, comps)
            self.budget[cid] = NOISE_SCORE_CAP - used

    def signals_crm(self):
        w, rng, k = self.w, self.rng, self.k
        types = ["PRESS_RELEASE", "HIRING_SURGE", "AWARD", "ADDON_ANNOUNCED", "DEBT_REFINANCED", "BANKER_ENGAGED",
                 "DEBT_MATURITY"]
        tw = [24, 15, 9, 12, 10, 13, 17]
        banks = self.covered_interm + self.other_interm
        sponsor_owned = {c for c in self.noise_cos if any(o["end_date"] is None for o in self.own_by_co.get(c, []))}
        addon_buyers = {plat for _c, plat in self.addon_close.values()}
        # R20: a noise company linked to a CURRENT Fund III holding is flagged by the Finale conflict rule, and a
        # flagged extra must stay Tier C (< 50), so its scored-signal budget stops at 45 instead of 55
        f3_now = {o["company_id"] for o in w.t["OWNERSHIP"] if o["fund_id"] == k("NW_F3") and o["end_date"] is None}
        f3_touch = {l_["supplier_id"] for l_ in w.t["COMMERCIAL_LINK"] if l_["customer_id"] in f3_now} | \
                   {l_["customer_id"] for l_ in w.t["COMMERCIAL_LINK"] if l_["supplier_id"] in f3_now}
        self.active = {}
        for cid in self.noise_cos:
            size = w.company_row[cid]["ebitda_musd"]
            lam = NOISE_SIGNAL_RATE * (0.55 + min(1.6, size / 18.0))
            n = min(7, int(rng.expovariate(1.0 / lam) + 0.5)) if rng.random() < 0.82 else 0
            acq = self.addon_close.get(cid)
            elig = cid in self.budget
            budget = self.budget.get(cid, 99)
            if cid in f3_touch:
                budget -= NOISE_SCORE_CAP - 45
            # choose which scored components may fire (each 10 points); R20 (R19c M2): none on an acquired add-on
            want = set()
            if elig and acq is None:
                for comp, p in (("R_BANKER", 0.35), ("R_DEBT", 0.45), ("A_CRM", 0.3)):
                    if budget >= 10 and rng.random() < p:
                        want.add(comp); budget -= 10
            self.active[cid] = want
            rows = []
            for _ in range(n):
                t_ = rng.choices(types, weights=tw)[0]
                if t_ == "ADDON_ANNOUNCED" and (cid not in sponsor_owned or cid not in addon_buyers):
                    t_ = "PRESS_RELEASE"
                sd = self.rdate(date(2022, 7, 1), date(2026, 9, 28))
                if rng.random() < 0.4:
                    sd = self.rdate(date(2025, 4, 1), date(2026, 9, 28))
                rows.append([t_, sd, None])
            if elig:
                for r in rows:
                    if r[0] == "BANKER_ENGAGED" and T_6M <= r[1] <= AS_OF and "R_BANKER" not in want:
                        r[1] = self.rdate(_addm(AS_OF, -12), _addm(AS_OF, -7))   # engaged 7-12 months ago
                    if r[0] == "DEBT_MATURITY":
                        r[2] = self.rdate(_addm(T_P18M, 1), _addm(AS_OF, 48)) if "R_DEBT" not in want else \
                            self.rdate(AS_OF + timedelta(days=30), T_P18M - timedelta(days=10))
                        if "R_DEBT" not in want and rng.random() < 0.3:
                            r[2] = self.rdate(_addm(AS_OF, 19), _addm(AS_OF, 20))   # just past 18 months
                if "R_BANKER" in want and not any(r[0] == "BANKER_ENGAGED" and T_6M <= r[1] for r in rows):
                    rows.append(["BANKER_ENGAGED", self.rdate(T_6M + timedelta(days=5), date(2026, 9, 25)), None])
                if "R_DEBT" in want and not any(r[0] == "DEBT_MATURITY" and r[2] and AS_OF < r[2] <= T_P18M for r in rows):
                    rows.append(["DEBT_MATURITY", self.rdate(date(2025, 3, 1), date(2026, 8, 31)),
                                 self.rdate(AS_OF + timedelta(days=30), T_P18M - timedelta(days=10))])
            for r in rows:
                if r[0] == "DEBT_MATURITY" and r[2] is None:
                    r[2] = r[1] + timedelta(days=rng.randint(200, 1500))
            if acq:
                # R20 (R19c M2): after the close the target reports through its buyer: no signal of its own
                # dated after the close, and its debt was repaid at the close (no maturity past it)
                rows = [r for r in rows if r[1] <= acq[0] and not (r[0] == "DEBT_MATURITY" and r[2] and r[2] > acq[0])]
            # naive keyword screen: at most 2 rows in [T-12m, T] for any keyword match in band
            if self.naive_row(cid):
                win = [r for r in rows if T_12M <= r[1] <= AS_OF]
                keep = [r for r in win if (r[0] == "BANKER_ENGAGED" and "R_BANKER" in want)][:1]
                keep += [r for r in win if r not in keep][:max(0, 2 - len(keep))]
                for r in win:
                    if r not in keep:
                        r[1] = self.rdate(date(2023, 1, 1), date(2025, 8, 31))
                        if r[0] == "DEBT_MATURITY" and r[2] and r[2] <= r[1]:
                            r[2] = r[1] + timedelta(days=500)
            rows.sort(key=lambda r: (r[1], r[0]))
            for t_, sd, ev in rows:
                mag = None
                if t_ in ("DEBT_MATURITY", "DEBT_REFINANCED"):
                    mag = round(size * rng.uniform(2.5, 4.5), 1)
                interm = rng.choice(banks) if t_ == "BANKER_ENGAGED" else None
                w.signal(cid, t_, sd.isoformat(), event=ev.isoformat() if ev else None, interm=interm, magnitude=mag)

        # ---- CRM
        seeds = self.seeds
        sw_ = [0.2, 0.25, 0.3, 0.12, 0.13]
        # R20 (R19c M2): a company already bought as an add-on is never an independent pipeline target
        pipe_pool = [c for c in self.noise_cos if self.in_thesis(c) and not self.nw_owned_now(c)
                     and 3.0 <= w.company_row[c]["ebitda_musd"] <= 60 and c not in self.addon_close]
        rng.shuffle(pipe_pool)
        elig_first = [c for c in pipe_pool if c in self.budget] + [c for c in pipe_pool if c not in self.budget]
        self.pipe = elig_first[:int(NOISE_PIPELINE * 0.8)]
        rest = [c for c in self.noise_cos if c not in set(self.pipe) and not self.nw_owned_now(c)
                and not self.in_thesis(c) and w.company_row[c]["ebitda_musd"] >= 5 and c not in self.addon_close]
        self.pipe += rest[:NOISE_PIPELINE - len(self.pipe)]
        for cid in self.noise_cos:
            in_pipe = cid in set(self.pipe)
            want_crm = "A_CRM" in self.active.get(cid, set())
            elig = cid in self.budget
            acq = self.addon_close.get(cid)
            n = rng.choice([1, 2, 3, 3, 4, 5, 6]) if in_pipe else (1 if rng.random() < 0.18 else 0)
            if want_crm:
                n = max(n, 1)
            got_pos = False
            for j in range(n):
                when = self.rdate(date(2020, 1, 1), date(2026, 9, 25))
                sent = rng.choices(["positive", "neutral", "negative"], [0.35, 0.55, 0.10])[0]
                if elig and T_24M <= when <= AS_OF and sent == "positive" and not want_crm:
                    sent = "neutral"
                if want_crm and not got_pos and j == n - 1:
                    when, sent = self.rdate(T_24M + timedelta(days=10), date(2026, 9, 20)), "positive"
                if sent == "positive" and T_24M <= when <= AS_OF:
                    got_pos = True
                if acq and when > acq[0]:
                    continue   # R20 (R19c M2): no company-level touch with an add-on after it was acquired
                w.crm(rng.choices(seeds, sw_)[0], when, rng.choice(["meeting", "call", "email", "conference"]),
                      sent, org=cid)
            # occasional person-level touch with an exec: never positive (no Knows edge, no access point)
            if in_pipe and rng.random() < 0.25:
                execs = sorted(r["person_id"] for r in self.roles_by_org.get(cid, []) if r["end_date"] is None
                               and r["role_type"] in ("CEO", "CFO"))
                if execs:
                    w.crm(rng.choices(seeds, sw_)[0], self.rdate(date(2021, 1, 1), date(2026, 9, 20)), "call",
                          rng.choice(["neutral", "neutral", "negative"]), person=rng.choice(execs))
        # sponsors (never the cast sponsors) and their business-development partners (the only K3 edges)
        sponsors = sorted(r["sponsor_id"] for r in w.t["SPONSOR"] if r["sponsor_id"] not in self.cast_sponsors)
        for sid in sponsors:
            for _ in range(rng.choice([3, 4, 5, 6, 8, 10])):
                w.crm(rng.choices(seeds, sw_)[0], self.rdate(date(2020, 6, 1), date(2026, 9, 25)),
                      rng.choice(["meeting", "call", "conference", "email"]),
                      rng.choices(["positive", "neutral", "negative"], [0.3, 0.62, 0.08])[0], org=sid)
        for p, sid in self.bd_people:
            for _ in range(rng.choice([1, 2, 3, 4, 5])):
                w.crm(rng.choices(seeds, sw_)[0], self.rdate(date(2022, 1, 1), date(2026, 9, 25)),
                      rng.choice(["meeting", "call", "email"]),
                      rng.choices(["positive", "neutral"], [0.55, 0.45])[0], person=p)
        # older intermediary coverage (before the 24-month window, so Q1 and the gap rule are unchanged)
        cov = sorted(r["intermediary_id"] for r in w.t["INTERMEDIARY"] if r["intermediary_id"] not in self.no_touch_interm)
        for _ in range(45):
            w.crm(rng.choices(seeds, sw_)[0], self.rdate(date(2019, 1, 1), date(2024, 9, 15)),
                  rng.choice(["meeting", "call", "conference"]), rng.choice(["neutral", "positive"]), org=rng.choice(cov))
        # ---- PIPELINE (never stage "IOI prep": that is Tessmark's alone)
        stages = ["Tracking", "Contacted", "Engaged", "IOI Submitted", "Passed"]
        for cid in self.pipe:
            st = rng.choices(stages, [0.45, 0.25, 0.09, 0.03, 0.18])[0]
            e = w.company_row[cid]["ebitda_musd"]
            check = None if st == "Tracking" and rng.random() < 0.6 else round(e * rng.uniform(3.0, 5.5) / 5) * 5.0
            w.pipe(cid, st, self.rdate(date(2019, 1, 1), date(2026, 8, 31)).isoformat(),
                   rng.choices(seeds, sw_)[0], check)

    # ---------------------------------------------------------------- run
    def run(self):
        self.sponsors_and_funds()
        self.companies()
        self.sponsor_and_bank_people()
        self.own_by_co = {}
        self.ownership_and_deals()
        self.company_people()
        self.near_misses()
        self.links()
        self.plan_scores()
        self.signals_crm()
        # bookkeeping for the handoff (not written to CSV)
        self.w.noise_info = {"near_miss": {kk: (v, self.w.name_of.get(v)) for kk, v in self.near_miss.items()},
                             "flow_thesis_deals": self.flow_thesis_deals}


def noise_check(csv_dir: Path) -> int:
    """R12 checks on a noise build, on top of the R05 self-check (`--check --out DIR`):
    R08 invariants, caps, decoys still returned by their naive screens, near-misses present,
    no noise company in the 60-69 riser window, realism ranges, and the SQL-vs-KG numbers for G5."""
    import pandas as pd
    ok = True

    def report(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}{('  ' + str(detail)) if detail else ''}")

    tb = {n: pd.read_csv(csv_dir / f"{n}.csv", dtype=str, keep_default_na=False) for n in TABLES}
    gold = json.loads((GOLDEN_DIR / "expected.json").read_text())
    cast = {key: v["id"] for key, v in gold["cast"].items()}
    tot = sum(len(v) for v in tb.values())
    report("caps (<= 4000 per table, <= 16000 total)", tot <= 16000 and all(len(v) <= 4000 for v in tb.values()),
           f"total={tot}; " + ", ".join(f"{n}={len(v)}" for n, v in tb.items()))
    # R08 invariants
    pipe = tb["PIPELINE"]
    report("R08: Tessmark is the only IOI prep pipeline row",
           list(pipe[pipe.stage == "IOI prep"].company_id) == [cast["CONF"]])
    own = tb["OWNERSHIP"]
    cm = own[(own.end_date == "") & (own.stake_type == "majority")].groupby("company_id").size()
    report("R08: at most one current majority owner per company (founder-owned have none)", (cm <= 1).all(),
           f"{int((cm == 1).sum())} companies with one, {len(tb['COMPANY']) - int((cm == 1).sum())} with none")
    r = tb["ROLE_HISTORY"]
    ceo = r[(r.end_date == "") & (r.role_type == "CEO")].groupby("org_id").size()
    comp_ids = set(tb["COMPANY"].company_id)
    report("R08: every company has exactly one current CEO",
           set(ceo.index) >= comp_ids and (ceo[ceo.index.isin(comp_ids)] == 1).all(),
           f"missing={len(comp_ids - set(ceo.index))}, multi={int((ceo > 1).sum())}")
    report("roles end after they start", (r[r.end_date != ""].end_date > r[r.end_date != ""].start_date).all())
    report("ownership ends after it starts", (own[own.end_date != ""].end_date > own[own.end_date != ""].start_date).all())
    # realism ranges
    c = tb["COMPANY"].copy()
    c["m"] = c.ebitda_musd.astype(float) / c.revenue_musd.astype(float)
    report("EBITDA margins within 4-30%", c.m.between(0.04, 0.30).all(), f"min={c.m.min():.3f} max={c.m.max():.3f}")
    tx = tb["TRANSACTION"]
    mult = tx[tx.ev_ebitda != ""].ev_ebitda.astype(float)
    report("EV/EBITDA within 6.0-12.5x", mult.between(6.0, 12.5).all(), f"{mult.min()}-{mult.max()}")
    tp = tb["TRANSACTION_PARTY"]
    _share = (tx.deal_role == "add_on").mean()
    report("add-ons are the majority of deals: 60-70% of TRANSACTION, at most 640 rows (R20)",
           0.60 <= _share <= 0.70 and len(tx) <= 640, f"{_share:.1%} add-ons of {len(tx)} deals")
    # decoys
    win = tx[tx.close_date >= "2021-10-01"]
    lt = tp[tp.txn_id.isin(win.txn_id) & (tp.org_type == "intermediary")].groupby("org_id").txn_id.nunique() \
        .sort_values(ascending=False)
    im = tb["INTERMEDIARY"].set_index("intermediary_id")["name"]
    ranks = list(lt.index)
    report("Q-FLOW decoy: Brayford tops the raw league table", ranks[0] == cast["BIGBANK"],
           f"top 12: {[(im[i], int(n)) for i, n in lt.head(12).items()]}; HL rank {ranks.index(cast['HL']) + 1}")
    # signal layer preserved: every signal row appears unchanged; new rows never touch the cast
    sw = build(noise=False)
    keyed = set(sw.key.values())
    seeds = {cast[x] for x in ("MP", "MD_MER", "VP", "OP", "OP2")}
    new_rows = {}
    for n, (pk, cols) in TABLES.items():
        sig_lines = {tuple(fmt(r[c_]) for c_ in cols) for r in sw.t[n]}
        got = {tuple(x) for x in tb[n][cols].itertuples(index=False)}
        report(f"signal rows preserved {n}", sig_lines <= got, len(sig_lines - got))
        new_rows[n] = pd.DataFrame(sorted(got - sig_lines), columns=cols)
    nl = new_rows["COMMERCIAL_LINK"]
    bad = nl[nl.supplier_id.isin(keyed) | nl.customer_id.isin(keyed)]
    report("new links touch no cast company except the Q-ADDON near-miss (2 GRANITE customers)",
           len(bad) == 2 and set(bad.customer_id) <= {cast["C02"], cast["C05"]}, len(bad))
    for n, cols_ in [("COMPANY_SIGNAL", ["company_id"]), ("PIPELINE", ["company_id"]), ("TRANSACTION", ["target_id"]),
                     ("OWNERSHIP", ["company_id"])]:
        hit = new_rows[n][new_rows[n][cols_].isin(set(sw.company_row)).any(axis=1)]
        report(f"new {n} rows touch no signal company", hit.empty, len(hit))
    cast_sp = {cast[x] for x in ("NW", "IRONBRIDGE", "COPPERLINE", "TAMARACK", "RIDGEBACK", "ASHGROVE")}
    nc = new_rows["CRM_INTERACTION"]
    hit = nc[nc.counterparty_org_id.isin(set(sw.company_row) | cast_sp) |
             nc.counterparty_person_id.isin({r_["person_id"] for r_ in sw.t["PERSON"]})]
    report("new CRM rows touch no signal company, cast sponsor or signal person", hit.empty, len(hit))
    nr = new_rows["ROLE_HISTORY"]
    sig_people = {r["person_id"] for r in sw.t["PERSON"]}
    on_sig = nr[nr.org_id.isin(set(sw.company_row) | set(r["sponsor_id"] for r in sw.t["SPONSOR"] if r["sponsor_id"] in {r2["org_id"] for r2 in sw.t["ROLE_HISTORY"]}))]
    report("new roles at signal orgs are only the filler CEOs (non-founder, new people)",
           (on_sig.role_type == "CEO").all() and (on_sig.is_founder == "FALSE").all() and not on_sig.person_id.isin(sig_people).any(),
           f"{len(on_sig)} filler CEOs")
    seed_new = nr[nr.person_id.isin(seeds)]
    report("new seed roles: one 11-month near-miss COO role plus Fund III board seats", len(seed_new) >= 1
           and set(seed_new.role_type) <= {"COO", "Board"} and (seed_new.role_type == "COO").sum() == 1, len(seed_new))
    nx_ = new_rows["CRM_INTERACTION"]
    report("no new CRM touch with an intermediary inside the 24-month window",
           nx_[(nx_.counterparty_org_type == "intermediary") & (nx_.interaction_date >= "2024-10-01")].empty)
    # near-misses, found by rule (not by name)
    comp = tb["COMPANY"].set_index("company_id")
    sec = tb["SECTOR"].set_index("sector_id")
    foc = tb["FUND_FOCUS"][tb["FUND_FOCUS"].fund_id == cast["NW_F4"]]
    inc, exc = set(foc[foc["mode"] == "include"].sector_id), set(foc[foc["mode"] == "exclude"].sector_id)

    def thesis(cid):
        a, x = [], comp.at[cid, "sector_id"]
        while x:
            a.append(x); x = sec.at[x, "parent_id"]
        return bool(set(a) & inc) and not set(a) & exc
    sig = tb["COMPANY_SIGNAL"]
    sig_win = sig[(sig.signal_date >= "2026-04-01") & (sig.signal_type == "BANKER_ENGAGED")].company_id
    th = [c_ for c_ in comp.index if thesis(c_)]
    over = [c_ for c_ in th if 40.0 < float(comp.at[c_, "ebitda_musd"]) <= 41.0 and c_ in set(sig_win)]
    report("near-miss: thesis company with EBITDA just over $40M and a live banker", len(over) >= 1, comp.loc[over, "name"].tolist())
    ca = [c_ for c_ in th if not comp.at[c_, "hq_region_id"].startswith("US-") and c_ in set(sig_win)]
    report("near-miss: thesis company outside the US gate with a live banker", len(ca) >= 1, comp.loc[ca, "name"].tolist())
    pub = [c_ for c_ in th if comp.at[c_, "is_public"] == "TRUE" and 5 <= float(comp.at[c_, "ebitda_musd"]) <= 40]
    report("near-miss: public thesis company in band", len(pub) >= 1, comp.loc[pub, "name"].tolist())
    rr = r.copy()
    rr["e2"] = rr.end_date.where(rr.end_date != "", "2026-10-01")
    sr = rr[rr.person_id.isin(seeds)]
    ceos = rr[(rr.role_type == "CEO") & (rr.end_date == "")]
    m11 = sr.merge(ceos, on="org_id")
    m11["ov"] = (pd.to_datetime(m11[["e2_x", "e2_y"]].min(axis=1)) - pd.to_datetime(m11[["start_date_x", "start_date_y"]].max(axis=1))).dt.days
    near = m11[(m11.ov >= 300) & (m11.ov < 365)]
    report("near-miss: a seed overlapped a current CEO 300-364 days (no Knows edge)", len(near) >= 1,
           [(comp.at[o_, "name"], int(v)) for o_, v in zip(near.org_id, near.ov)])
    cl = tb["COMMERCIAL_LINK"]
    nb = defaultdict(set)
    for a_, b_ in zip(cl.supplier_id, cl.customer_id):
        nb[a_].add(b_); nb[b_].add(a_)
    g_ = cast["GRANITE"]
    jac = sorted((round(len(nb[g_] & nb[c_]) / len(nb[g_] | nb[c_]), 4), comp.at[c_, "name"]) for c_ in list(nb)
                 if c_ != g_ and c_ not in nb[g_] and nb[g_] & nb[c_])
    report("near-miss: an add-on candidate just under the 0.10 Jaccard cutoff", any(0.09 <= j < 0.10 for j, _ in jac),
           [x for x in jac if 0.09 <= x[0] < 0.10])
    # SQL-vs-KG contrast numbers for G5 (the naive screens as QUESTIONS.md v2 states them)
    nw_f = set(tb["FUND"][tb["FUND"].sponsor_id == cast["NW"]].fund_id)
    nw_now = set(own[(own.end_date == "") & own.fund_id.isin(nw_f)].company_id)
    cnt = sig[(sig.signal_date >= "2025-10-01") & (sig.signal_date <= "2026-10-01")].groupby("company_id").size()
    naive = []
    for cid_, row in comp.iterrows():
        txt = (row["name"] + " " + sec.at[row.sector_id, "name"]).lower()
        if any(k_ in txt for k_ in NAIVE_KEYWORDS) and 5 <= float(row.ebitda_musd) <= 40 and row.hq_region_id.startswith("US-") \
                and cid_ not in nw_now:
            naive.append((-int(cnt.get(cid_, 0)), row["name"]))
    naive.sort()
    report("G5 contrast Q-SCORE", True, f"keyword screen returns {len(naive)} companies, top 3 {[n_ for _, n_ in naive[:3]]}; "
           f"KG Tier A = 6, 2 not in CRM, 2 missed by the screen")
    report("G5 contrast Q-FLOW", True, f"league table #1 {im[ranks[0]]} ({int(lt.iloc[0])} deals), Harbor Lane #{ranks.index(cast['HL']) + 1} "
           f"({int(lt[cast['HL']])}); KG betweenness: Cedar Row #1, Harbor Lane #2, the only coverage gap")
    pl = tb["PIPELINE"]
    report("G5 context", True, f"pipeline {len(pl)} companies; market {len(comp)} companies, {len(th)} in Fund IV thesis sectors")
    print("NOISE-CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# =====================================================================================
# 5. WRITERS
# =====================================================================================

def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{v:.1f}"
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def write_csvs(w: World):
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"random_seed": RANDOM_SEED, "as_of_date": AS_OF.isoformat(), "tables": {}}
    total = 0
    for name, (pk, cols) in TABLES.items():
        rows = sorted(w.t[name], key=lambda r: tuple(str(r[c]) for c in pk))
        path = CSV_DIR / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh, lineterminator="\n")
            wr.writerow(cols)
            for r in rows:
                wr.writerow([fmt(r[c]) for c in cols])
        total += len(rows)
        manifest["tables"][name] = {"file": f"{name}.csv", "rows": len(rows),
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        assert len(rows) <= DATA_CAPS["max_rows_per_table"], f"{name} exceeds per-table cap"
    assert total <= DATA_CAPS["max_rows_total"], "total rows exceed cap"
    manifest["total_rows"] = total
    (CSV_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def resolve(w: World, obj):
    """Replace role keys with {key, id, name} in golden structures."""
    if isinstance(obj, dict):
        return {kk: resolve(w, vv) for kk, vv in obj.items()}
    if isinstance(obj, list):
        if obj and all(isinstance(x, str) and x in w.key for x in obj):
            return [{"key": x, "id": w.key[x], "name": w.name_of.get(w.key[x])} for x in obj]
        return [resolve(w, x) for x in obj]
    if isinstance(obj, str) and obj in w.key:
        return {"key": obj, "id": w.key[obj], "name": w.name_of.get(w.key[obj])}
    return obj


def write_golden(w: World):
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    out = {"as_of_date": AS_OF.isoformat(), "random_seed": RANDOM_SEED, "spec": "QUESTIONS.md v2 (R20 a1)",
           "note": "Generator intent. Never loaded to Snowflake. Keys are story role keys, ids are CSV ids.",
           "questions": {q: resolve(w, g) for q, g in w.golden.items()},
           "cast": {key: {"id": eid, "name": w.name_of.get(eid)} for key, eid in sorted(w.key.items())}}
    (GOLDEN_DIR / "expected.json").write_text(json.dumps(out, indent=2, sort_keys=False) + "\n")


# =====================================================================================
# 5b. STORY CARDS (golden/stories.md)
# =====================================================================================

def write_stories(w: World):
    N = lambda key: w.name_of[w.key[key]]  # noqa: E731
    cards = [
        ("Q-SCORE", "Act 1. Six names to call on Monday, two of them with no coverage", [
            f"**Who.** The Fund IV Tier A list is {N('T_BANKER')} (90), {N('T_WARM')} (85), {N('T_COLD')} (80), "
            f"{N('T_5')} (75), {N('CONF')} (75) and {N('T_6')} (70). {N('T_COLD')} and {N('T_6')} have no pipeline "
            "row and no CRM touch at all: no coverage, so nobody here owns the relationship.",
            f"**What.** Each score is Fit plus Readiness plus Access. Fit means a thesis node, the EBITDA band and margin "
            f"against the focus-area benchmark. Readiness means a CFO hired from a PE-backed company, an exit window, a "
            f"banker engaged, debt maturing within 18 months, founder succession, or a new independent director. Access "
            f"means a positive CRM touch in the last 24 months. Example: {N('T_BANKER')} has been held by "
            f"{N('IRONBRIDGE')} Fund I (2016 vintage) since April 2019, has {N('CEDAR')} engaged, has debt due "
            f"September 2027, and hired a CFO from a sponsor-backed company in July 2025.",
            f"**Near miss.** {N('NM_B')} scores 65 (Tier B). Its CFO came from a founder-owned company, so the PE-CFO "
            "point is correctly not awarded, and the last CRM touch was in 2023.",
            f"**Decoys.** A keyword screen ranks {N('D_SHORT')}, {N('D_VET')} and {N('D_SNF')} as its top three, and all "
            f"three are wrong. {N('D_SHORT')} has five signals but none is a scored type, and its sponsor bought it in "
            f"April 2025. {N('D_VET')} is a veterinary drug maker outside the thesis tree. {N('D_SNF')} is in Skilled "
            f"Nursing, which Fund IV excludes inside Healthcare Services. The screen also misses {N('T_COLD')} and "
            f"{N('T_5')}. {N('D_BIG')} has every signal, but its EBITDA of $44.0M is above the band.",
            "**Why it matters to a partner.** The list is explainable point by point and reaches past the CRM, and the "
            "near misses show their reason, so nobody has to trust a black box."]),
        ("Q-PATH", "Act 2. Who gets us an edge", [
            f"**{N('T_BANKER')} (3 hops, 0.700).** Partner {N('VP')} worked with {N('Y_BANK')} at {N('LAKESHORE')} "
            f"from 2012 to 2016 and has met her seven times in the last two years. {N('Y_BANK')} and {N('B_BANK')} have "
            f"worked together at {N('CEDAR')} since 2017. {N('B_BANK')} led the 2019 majority recap of "
            f"{N('T_BANKER')} with founder-CEO {N('CEO_B')}. The owner's board designee, {N('OWN_B')} of "
            f"{N('IRONBRIDGE')}, is more than 3 hops away.",
            f"**{N('T_WARM')} (2 hops, 0.600).** Operating Partner {N('OP')} sat on the {N('BRIGHT')} board from "
            f"2014 to 2019 while {N('CFO_W')} was its CFO. She became CFO of {N('T_WARM')} in June 2025 and works for "
            f"founder-CEO {N('CEO_W')}. The alternate path, through {N('MP')} and board member {N('X_STALE')}, rests "
            f"on a 1998-2000 overlap at {N('OLDHARBOR')} and scores 0.287.",
            f"**{N('T_COLD')} (cold).** There is no path within 3 hops to CEO {N('CEO_C')} or to {N('COPPERLINE')}'s "
            f"board designee {N('OWN_C')}, even though the CRM shows a meeting with {N('COPPERLINE')} in March 2025. A "
            f"shared-employer join claims {N('MD_MER')} knows {N('CEO_C')} through {N('MERIDIAN')}. In fact "
            f"{N('MD_MER')} left in June 2011 and {N('CEO_C')} arrived in March 2013. The closest intermediary is "
            f"{N('HL')}: it was engaged in July 2026 and advised the 2023 dividend recap.",
            "**Why it matters to a partner.** Every hop shows when and where two people actually worked together. Stale "
            f"ties rank below fresh ones, and false intros are rejected before they embarrass the deal team. On {N('T_BANKER')} "
            "the path ends at the banker running the sale, so the play is an early look, not a back-channel to the CEO."]),
        ("Q-FLOW", "Act 3. Who bridges deal flow, and the coverage gap", [
            f"**Who.** Over the last five years in Fund IV sectors, {N('CEDAR')} is the top bridge by betweenness. "
            f"{N('HL')} is second with only 9 deals: 8 founder-owned healthcare sell-side mandates to buyers from five "
            f"sponsors, plus the 2023 dividend recap of {N('T_COLD')}, led by {N('HL_MD')}.",
            f"**Gap.** We touched {N('HL')} once in 24 months, a neutral conference meeting in November 2025. That "
            f"makes it the only top-decile bridge in our bottom quartile of coverage. {N('CEDAR')} has 14 "
            "touchpoints.",
            f"**Decoy.** {N('BIGBANK')} tops a raw league table with 40 deals. Only 8 are in our sectors, all sold to "
            "one large sponsor that already uses many advisors, so it ranks below 10th as a bridge.",
            f"**Why it matters to a partner.** Volume is not control. The coverage call list changes, and {N('HL')} "
            f"is also the way into the cold {N('T_COLD')}."]),
        ("Q-CONFLICT", "Act 4. Before we bid", [
            f"**What.** {N('CEDAR')} is engaged on {N('CONF')}, and Northwind is preparing an IOI with a $55M check. "
            f"{N('CONF')} supplies {N('PINE')}, a Fund III dermatology practice group since July 2020, one hop away, which triggers a "
            f"cross-fund review. It also supplies {N('C07')}, which buys from Fund IV's {N('GRANITE')}; that "
            "two-hop link is informational only.",
            f"**Concentration.** Fund IV holds {N('DIST1')} ($140M), {N('DIST2')} ($125M) and {N('DIST3')} ($120M) in "
            "Specialty Distribution: $385M, or 32.1% of $1,200M. The $55M check takes the area to $440M, 36.7%, over "
            "the 35% IC guideline by $20M. The headroom is $35M.",
            f"**Decoys.** A one-hop join against every Northwind ownership row ever recorded flags {N('BRIGHT')}, which "
            f"Northwind sold in February 2020, and misses {N('GRANITE')}. A per-niche GROUP BY sees no concentration "
            f"issue. {N('REDFERN')} (Fund III) sits exactly 3 hops out, beyond the 2-hop check.",
            "**Why it matters to a partner.** Cross-fund conflicts and guideline headroom are checked by rule before "
            "the IOI, not remembered at IC."]),
        ("FINALE", "Two sentences of new rules reshuffle the list", [
            f"**What.** A warm-path rule (our people within two hops of the CEO) adds 10 access points. It lifts "
            f"{N('T_WARM')} to 95 and first place. It also lifts {N('NM_B')} from 65 into Tier A at 75, through "
            f"Operating Partner {N('OP2')}, who worked with {N('Z')} at {N('LAKEMONT')} from 2016 to 2020; {N('Z')} "
            f"now sits on the board with founder-CEO {N('CEO_NMB')}.",
            f"**Conflict.** {N('CONF')} supplies {N('PINE')}, a current Fund III holding and a dermatology practice group, "
            f"so it is not a competitor of {N('NM_B')}. {N('CONF')} keeps its score of 75 but is flagged for cross-fund "
            "review: hold until cross-fund clearance, off the Tier A call list until it is cleared. The other Tier A "
            "names come back clear.",
            "**Why it matters to a partner.** Graph output feeds a governed rule, and every target is checked for "
            "cross-fund conflicts before the bid, not in the IC memo; a flagged name is on hold, not dropped."]),
        ("Q-ADDON", "Backup. What the platform should buy next", [
            f"**Who.** {N('A1')} shares 6 of {N('GRANITE')}'s 15 customers (Jaccard 0.2727) and adds Colorado, Utah "
            f"and New Mexico. {N('A2')} (0.1304) and {N('A3')} (0.1000) follow.",
            f"**Decoy.** {N('D_SAME')} is in the platform's own niche and states, and shares no customer or supplier "
            "with it.",
            "**Why it matters to a partner.** It reuses the same commercial graph as the conflict check."]),
    ]
    lines = ["# Story cards (golden, never loaded to Snowflake)", "",
             f"All data is synthetic and fictional, as of {AS_OF.isoformat()}. Spec: QUESTIONS.md v2. Hero order: "
             "Q-SCORE, Q-PATH, Q-FLOW, Q-CONFLICT, Finale (Q-ADDON is a backup). Names are final after the R05 "
             "collision check; R14 and R16 should use these names in prompts and the script.", "",
             "## Name map (QUESTIONS.md placeholder -> final)", ""]
    renames = [("Ironbridge Capital", "IRONBRIDGE"), ("Copperline Partners", "COPPERLINE"), ("Tamarack Equity", "TAMARACK"),
               ("Ashgrove Partners", "ASHGROVE"), ("Continental Capital Markets", "BIGBANK"),
               ("Lakeshore Securities", "LAKESHORE"), ("Keystone Clinical Supply", "CONF"),
               ("Alder Creek Dental Partners", "NM_B"), ("Brightwater Dental", "BRIGHT"),
               ("Pinecrest Dental Partners", "PINE"), ("Granite Testing Group", "GRANITE"),
               ("Meadowbrook Physical Therapy", "MEADOW"), ("Tidewater Chemical Distribution", "DIST1"),
               ("Juniper Industrial Supply", "DIST2"), ("Sable Ingredients Co", "DIST3"),
               ("Bluestem Engineering Group", "C07"), ("Ashby Community Hospital", "H1"),
               ("Fairmont Medical Linen", "H2"), ("Meridian Lab Services", "MERIDIAN"),
               ("Old Harbor Health", "OLDHARBOR"), ("Lakemont Orthodontics", "LAKEMONT"),
               ("Clearwater Environmental Labs", "A1"), ("Ridgeline NDT Services", "A2"),
               ("Summit Calibration Co", "A3"), ("Bedrock Materials Testing", "D_SAME"), ("Tom Brennan", "MD_MER")]
    lines += [f"- {old} -> **{N(key)}**" for old, key in renames if key in w.key]
    lines += ["- Unchanged: " + ", ".join(N(k_) for k_ in ("T_BANKER", "T_WARM", "T_COLD", "T_5", "T_6", "D_VET",
                                                           "D_BIG", "D_SHORT", "D_SNF", "REDFERN", "HL", "CEDAR",
                                                           "RIDGEBACK")) + ", and all other people.", ""]
    for qid, title, paras in cards:
        if qid not in w.golden:
            continue
        lines += [f"## {qid}: {title}", ""]
        for p_ in paras:
            lines += [p_, ""]
    (GOLDEN_DIR / "stories.md").write_text("\n".join(lines))


# =====================================================================================
# 6. SELF-CHECK (R05 sanity, not the oracle)
# =====================================================================================

def selfcheck() -> int:
    import itertools

    import networkx as nx
    import pandas as pd

    T = pd.Timestamp(AS_OF)
    ok = True

    def report(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}{('  ' + str(detail)) if detail and not cond else ''}")

    tb = {n: pd.read_csv(CSV_DIR / f"{n}.csv", dtype=str, keep_default_na=False) for n in TABLES}
    gold = json.loads((GOLDEN_DIR / "expected.json").read_text())
    cast = {key: v["id"] for key, v in gold["cast"].items()}
    gq = gold["questions"]
    man = json.loads((CSV_DIR / "MANIFEST.json").read_text())

    # ---- integrity ----
    for n, (pk, _) in TABLES.items():
        report(f"PK unique {n}", not tb[n].duplicated(pk).any())
        report(f"manifest rows {n}", man["tables"][n]["rows"] == len(tb[n]))
    report("caps", man["total_rows"] <= DATA_CAPS["max_rows_total"]
           and all(v["rows"] <= DATA_CAPS["max_rows_per_table"] for v in man["tables"].values()))
    # ---- realism guards (R20) ----
    _rh, _co = tb["ROLE_HISTORY"], tb["COMPANY"].set_index("company_id")
    _rc = _rh[_rh.org_type == "company"]
    _early = _rc[_rc.start_date.str[:4].astype(int) < _rc.org_id.map(_co.founded_year).astype(int)]
    report("no role at a company starts before its founding year", _early.empty, _early.role_id.tolist()[:5])
    _own, _fund = tb["OWNERSHIP"], tb["FUND"].set_index("fund_id")
    _dep = _own.equity_invested_musd.replace("", "0").astype(float).groupby(_own.fund_id).sum()
    _pct = (100 * _dep / _fund.size_musd.astype(float).reindex(_dep.index))
    report("no fund has invested more than 100% of its size", (_pct <= 100.0 + 1e-6).all(),
           f"max {_pct.max():.1f}% ({_pct.idxmax()})")
    ids = {"company": set(tb["COMPANY"].company_id), "sponsor": set(tb["SPONSOR"].sponsor_id),
           "intermediary": set(tb["INTERMEDIARY"].intermediary_id)}
    single_fks = [("SECTOR", "parent_id", "SECTOR", "sector_id"), ("REGION", "parent_id", "REGION", "region_id"),
                  ("SPONSOR", "hq_region_id", "REGION", "region_id"), ("FUND", "sponsor_id", "SPONSOR", "sponsor_id"),
                  ("FUND_FOCUS", "fund_id", "FUND", "fund_id"), ("FUND_FOCUS", "sector_id", "SECTOR", "sector_id"),
                  ("INTERMEDIARY", "hq_region_id", "REGION", "region_id"),
                  ("COMPANY", "sector_id", "SECTOR", "sector_id"), ("COMPANY", "hq_region_id", "REGION", "region_id"),
                  ("COMPANY_SITE", "company_id", "COMPANY", "company_id"),
                  ("COMPANY_SITE", "region_id", "REGION", "region_id"),
                  ("ROLE_HISTORY", "person_id", "PERSON", "person_id"),
                  ("OWNERSHIP", "company_id", "COMPANY", "company_id"), ("OWNERSHIP", "fund_id", "FUND", "fund_id"),
                  ("TRANSACTION", "target_id", "COMPANY", "company_id"),
                  ("TRANSACTION_PARTY", "txn_id", "TRANSACTION", "txn_id"),
                  ("TRANSACTION_PARTY", "fund_id", "FUND", "fund_id"),
                  ("TRANSACTION_PARTY", "lead_person_id", "PERSON", "person_id"),
                  ("COMMERCIAL_LINK", "supplier_id", "COMPANY", "company_id"),
                  ("COMMERCIAL_LINK", "customer_id", "COMPANY", "company_id"),
                  ("CRM_INTERACTION", "our_person_id", "PERSON", "person_id"),
                  ("CRM_INTERACTION", "counterparty_person_id", "PERSON", "person_id"),
                  ("PIPELINE", "company_id", "COMPANY", "company_id"),
                  ("PIPELINE", "owner_person_id", "PERSON", "person_id"),
                  ("COMPANY_SIGNAL", "company_id", "COMPANY", "company_id"),
                  ("COMPANY_SIGNAL", "intermediary_id", "INTERMEDIARY", "intermediary_id")]
    for t, c, rt, rc in single_fks:
        vals = set(tb[t][c]) - {""}
        bad = vals - set(tb[rt][rc])
        report(f"FK {t}.{c} -> {rt}.{rc}", not bad, sorted(bad)[:5])
    for t, c, tc in [("ROLE_HISTORY", "org_id", "org_type"), ("TRANSACTION_PARTY", "org_id", "org_type"),
                     ("CRM_INTERACTION", "counterparty_org_id", "counterparty_org_type")]:
        df = tb[t][tb[t][c] != ""]
        bad = [r for r in df[[c, tc]].itertuples(index=False) if r[0] not in ids.get(r[1], set())]
        report(f"FK {t}.{c} (polymorphic)", not bad, bad[:5])
    report("no ground-truth columns", not any(any(x in col.lower() for x in ("planted", "golden", "key", "decoy"))
                                               for n in TABLES for col in tb[n].columns))

    # ---- shared helpers ----
    dt = lambda s: pd.Timestamp(s) if s else None  # noqa: E731
    sec = tb["SECTOR"].set_index("sector_id")
    def anc(sid):
        out = []
        while sid:
            out.append(sid); sid = sec.at[sid, "parent_id"]
        return out
    reg = tb["REGION"].set_index("region_id")
    def ranc(rid):
        out = []
        while rid:
            out.append(rid); rid = reg.at[rid, "parent_id"]
        return out
    comp = tb["COMPANY"].set_index("company_id")
    fund = tb["FUND"].set_index("fund_id")
    nw = cast["NW"]
    nw_funds = set(fund.index[fund.sponsor_id == nw])
    roles = tb["ROLE_HISTORY"].copy()
    roles["s"] = roles.start_date.map(dt); roles["e"] = roles.end_date.map(dt)
    roles["cur"] = roles.end_date == ""
    own = tb["OWNERSHIP"].copy()
    own["s"] = own.start_date.map(dt); own["e"] = own.end_date.map(dt)
    own["cur"] = own.end_date == ""
    sig = tb["COMPANY_SIGNAL"].copy()
    sig["s"] = sig.signal_date.map(dt); sig["ev"] = sig.event_date.map(dt)
    crm = tb["CRM_INTERACTION"].copy(); crm["dd"] = crm.interaction_date.map(dt)
    f4 = cast["NW_F4"]
    foc = tb["FUND_FOCUS"][tb["FUND_FOCUS"].fund_id == f4]
    inc = dict(zip(foc[foc["mode"] == "include"].sector_id, foc[foc["mode"] == "include"].margin_benchmark_pct))
    exc = set(foc[foc["mode"] == "exclude"].sector_id)
    def mb(m): return T - pd.DateOffset(months=m)

    def score(warm=None, conflict=None):
        res = {}
        for cid, c in comp.iterrows():
            a = anc(c.sector_id)
            if not (set(a) & set(inc)) or set(a) & exc:
                continue
            e = float(c.ebitda_musd)
            cur_owner = own[(own.company_id == cid) & own.cur]
            if not (5.0 <= e <= 40.0) or "US" not in ranc(c.hq_region_id) or c.is_public == "TRUE" \
                    or set(cur_owner.fund_id) & nw_funds:
                continue
            comps = {"FIT_THESIS": 15, "FIT_EBITDA": 10 if 10.0 <= e <= 30.0 else 5}
            bench = float([inc[x] for x in a if x in inc][0])
            if e / float(c.revenue_musd) * 100 >= bench:
                comps["FIT_MARGIN"] = 5
            r = roles[roles.org_id == cid]
            for _, cf in r[(r.role_type == "CFO") & r.cur].iterrows():
                if not (mb(18) <= cf.s <= T):
                    continue
                prior = roles[(roles.person_id == cf.person_id) & (roles.org_id != cid) & roles.e.notna()]
                for _, pr in prior.iterrows():
                    if cf.s - pd.DateOffset(months=12) <= pr.e <= cf.s:
                        o = own[own.company_id == pr.org_id]
                        if any(min(pr.e, oe if oe is not None and not pd.isna(oe) else T) >= max(pr.s, os_)
                               for os_, oe in zip(o.s, o.e)):
                            comps["R_CFO_FROM_PE"] = 15
            for _, o in cur_owner.iterrows():
                if o.s <= mb(60) and int(fund.at[o.fund_id, "vintage_year"]) <= AS_OF.year - 8:
                    comps["R_EXIT_WINDOW"] = 15
            s_ = sig[sig.company_id == cid]
            if ((s_.signal_type == "BANKER_ENGAGED") & (s_.s >= mb(6)) & (s_.s <= T)).any():
                comps["R_BANKER"] = 10
            if ((s_.signal_type == "DEBT_MATURITY") & (s_.s <= T) & (s_.ev > T) & (s_.ev <= T + pd.DateOffset(months=18))).any():
                comps["R_DEBT"] = 10
            ceo = r[(r.role_type == "CEO") & r.cur]
            if ((ceo.is_founder == "TRUE") & (ceo.s <= mb(180))).any() and not \
                    r[r.role_type.isin(["President", "COO"]) & r.cur].shape[0]:
                comps["R_SUCCESSION"] = 10
            owner_sponsors = {fund.at[f, "sponsor_id"] for f in cur_owner.fund_id}
            for _, b in r[(r.role_type == "Board") & (r.s >= mb(12)) & (r.s <= T)].iterrows():
                pr = roles[roles.person_id == b.person_id]
                if not ((pr.org_id == cid) & (pr.role_type != "Board")).any() and \
                        not (pr.org_id.isin(owner_sponsors) & pr.cur).any():
                    comps["R_NEW_DIRECTOR"] = 5
            cur_people = set(r[r.cur].person_id)
            cx = crm[(crm.sentiment == "positive") & (crm.dd >= mb(24)) & (crm.dd <= T)]
            if ((cx.counterparty_org_id == cid) | cx.counterparty_person_id.isin(cur_people)).any():
                comps["A_CRM"] = 10
            if warm is not None and cid in warm:
                comps["A_WARM_PATH"] = 10
            fit = sum(v for k_, v in comps.items() if k_.startswith("FIT"))
            rd = min(50, sum(v for k_, v in comps.items() if k_.startswith("R_")))
            ac = sum(v for k_, v in comps.items() if k_.startswith("A_"))
            tot = fit + rd + ac
            tier = "A" if tot >= 70 else "B" if tot >= 50 else "C"
            if conflict and cid in conflict:
                tier = "Conflict"
            res[cid] = dict(score=tot, fit=fit, readiness=rd, access=ac, tier=tier, comps=comps, name=c["name"])
        return res

    def ranked(res):
        a = [(cid, v) for cid, v in res.items() if v["tier"] == "A"]
        a.sort(key=lambda x: (-x[1]["score"], -x[1]["readiness"], -x[1]["fit"], x[1]["name"]))
        return a

    sc = score()
    ta = ranked(sc)
    K_ = lambda key: cast[key]  # noqa: E731
    if "Q-SCORE" in gq:
        g = gq["Q-SCORE"]
        exp = [(x["key"]["id"], x["score"]) for x in g["tier_a_ranked"]]
        report("Q-SCORE Tier A order and scores", [(c, v["score"]) for c, v in ta] == exp,
               [(v["name"], v["score"]) for c, v in ta])
        for x in g["tier_a_ranked"] + g["tier_b_reference"]:
            got = sc.get(x["key"]["id"], {}).get("comps")
            report(f"Q-SCORE components {x['key']['key']}", got == x["components"], got)
        report("Q-SCORE D_SHORT = 30", sc.get(K_("D_SHORT"), {}).get("score") == 30, sc.get(K_("D_SHORT")))
        for key in ("D_BIG", "D_VET", "D_SNF", "BRIGHT"):
            report(f"Q-SCORE {key} ineligible", K_(key) not in sc)
        pip = set(tb["PIPELINE"].company_id)
        def in_crm(cid):
            ppl = set(roles[roles.org_id == cid].person_id)
            return cid in pip or (crm.counterparty_org_id == cid).any() or crm.counterparty_person_id.isin(ppl).any()
        nic = {c for c, _ in ta if not in_crm(c)}
        report("Q-SCORE not-in-CRM set", nic == {x["id"] for x in g["not_in_crm"]}, nic)
        # naive screen
        nw_owned = set(own[own.cur & own.fund_id.isin(nw_funds)].company_id)
        cnt = sig[(sig.s >= mb(12)) & (sig.s <= T)].groupby("company_id").size()
        rows_ = []
        for cid, c in comp.iterrows():
            txt = (c["name"] + " " + sec.at[c.sector_id, "name"]).lower()
            if any(k_ in txt for k_ in NAIVE_KEYWORDS) and 5 <= float(c.ebitda_musd) <= 40 \
                    and c.hq_region_id.startswith("US-") and cid not in nw_owned:
                rows_.append((-int(cnt.get(cid, 0)), c["name"], cid))
        rows_.sort()
        inv = {v: k_ for k_, v in cast.items()}
        cast_order = [inv[cid] for _, _, cid in rows_ if cid in inv]
        report("Q-SCORE naive cast top 8", cast_order[:8] == [x["key"] for x in g["naive_screen"]["cast_order_top8"]],
               cast_order[:10])
        naive_ids = {cid for _, _, cid in rows_}
        report("Q-SCORE naive misses T_COLD, T_5", not ({K_("T_COLD"), K_("T_5")} & naive_ids))
        report("Q-SCORE naive top 3 = D_SHORT, D_VET, D_SNF", [cid for _, _, cid in rows_[:3]] ==
               [K_("D_SHORT"), K_("D_VET"), K_("D_SNF")])
        top8 = {x["key"] for x in g["naive_screen"]["cast_order_top8"]}
        rest = [inv[cid] for n_, _, cid in rows_ if cid in inv and inv[cid] not in top8 and n_ != 0]
        report("Q-SCORE other naive cast rows have 0 signals", not rest, rest)
        noncast3 = [cid for n_, _, cid in rows_ if -n_ >= 3 and cid not in inv]
        report("Q-SCORE no non-cast naive row with >= 3 signals", not noncast3, noncast3)

    # ---- Knows ----
    seeds = set(roles[(roles.org_id == nw) & roles.cur & roles.role_type.isin(["Deal Team", "Operating Partner"])].person_id)
    former_nw = set(roles[(roles.org_id == nw)].person_id) - seeds
    def rec(x):
        return 1.0 if x >= mb(120) else 0.7 if x >= mb(240) else 0.4
    K = defaultdict(float); EV = {}
    def addk(a, b, s, why):
        if a == b:
            return
        key = tuple(sorted((a, b)))
        if s > K[key]:
            K[key] = s; EV[key] = why
    for org, grp in roles.groupby("org_id"):
        rows = list(grp.itertuples())
        for x, y in itertools.combinations(rows, 2):
            if x.person_id == y.person_id:
                continue
            xe = x.e if x.e is not None and not pd.isna(x.e) else T
            ye = y.e if y.e is not None and not pd.isna(y.e) else T
            ov_e, ov_s = min(xe, ye), max(x.s, y.s)
            days = (ov_e - ov_s).days
            if days >= 365:
                addk(x.person_id, y.person_id, rec(ov_e) * min(1.0, 0.4 + 0.15 * days / 365.25), f"K1 {org}")
    txp = tb["TRANSACTION_PARTY"]; txn = tb["TRANSACTION"].set_index("txn_id")
    for tid, grp in txp[txp.lead_person_id != ""].groupby("txn_id"):
        cd = pd.Timestamp(txn.at[tid, "close_date"]); tgt = txn.at[tid, "target_id"]
        leads = list(grp.lead_person_id)
        for a, b in itertools.combinations(leads, 2):
            addk(a, b, 0.7 * rec(cd), f"K2 co-lead {tid}")
        execs = roles[(roles.org_id == tgt) & roles.role_type.isin(["CEO", "CFO"]) & (roles.s <= cd)
                      & (roles.e.isna() | (roles.e >= cd))]
        for a in leads:
            for b in execs.person_id:
                addk(a, b, 0.7 * rec(cd), f"K2 lead/exec {tid}")
    pos = crm[(crm.sentiment == "positive") & (crm.counterparty_person_id != "") & (crm.dd >= mb(24)) & (crm.dd <= T)
              & crm.our_person_id.isin(seeds)]
    for (a, b), n in pos.groupby(["our_person_id", "counterparty_person_id"]).size().items():
        addk(a, b, {1: 0.6, 2: 0.8}.get(n, 1.0), "K3 crm")
    G = nx.Graph()
    for (a, b), s in K.items():
        G.add_edge(a, b, w=s)
    def msd(sources):
        out = {}
        for s in sources:
            if s in G:
                for n_, l in nx.single_source_shortest_path_length(G, s).items():
                    out[n_] = min(out.get(n_, 99), l)
        return out
    dist = msd(seeds)
    dist_any_nw = msd(seeds | former_nw)

    def best_paths(dm, L):
        out = []
        for s in seeds:
            if s in G and dm in G:
                for p in nx.all_simple_paths(G, s, dm, cutoff=L):
                    if len(p) - 1 == L and not (set(p[1:]) & seeds):
                        out.append((round(math.prod(G[a][b]["w"] for a, b in zip(p, p[1:])), 3), p))
        return sorted(out, key=lambda x: -x[0])

    if "Q-PATH" in gq:
        for r_ in gq["Q-PATH"]["rows"]:
            dm = r_["decision_maker"]["id"]; tag = f"{r_['target']['key']}/{r_['decision_maker']['key']}"
            L = dist.get(dm)
            if r_.get("cold"):
                report(f"Q-PATH {tag} cold (d>=4)", L is None or L >= 4, L)
                continue
            report(f"Q-PATH {tag} hops", L == r_["hops"], L)
            bp = best_paths(dm, r_["hops"])
            report(f"Q-PATH {tag} best path", bool(bp) and bp[0][1] == [x["id"] for x in r_["best_path"]]
                   and abs(bp[0][0] - r_["path_strength"]) < 1e-3, bp[:3])
            report(f"Q-PATH {tag} alternates", [(a_[0], a_[1]) for a_ in bp[1:]] ==
                   [(a["path_strength"], [x["id"] for x in a["path"]]) for a in r_["alternates"]], bp[1:])
        top3 = [K_("T_BANKER"), K_("T_WARM"), K_("T_COLD")]
        ceo_ids = set(roles[roles.org_id.isin(top3) & (roles.role_type == "CEO") & roles.cur].person_id)
        ceos = roles[roles.person_id.isin(ceo_ids)]
        sr = roles[roles.person_id.isin(seeds)]
        naive_pairs = {(a.person_id, b.person_id, a.org_id) for a in sr.itertuples() for b in ceos.itertuples()
                       if a.org_id == b.org_id and a.person_id != b.person_id}
        report("Q-PATH naive shared-employer join == {MD_MER-CEO_C via MERIDIAN}",
               naive_pairs == {(K_("MD_MER"), K_("CEO_C"), K_("MERIDIAN"))}, naive_pairs)
        report("Q-PATH Varnell decoy: no Knows edge MD_MER-CEO_C", not G.has_edge(K_("MD_MER"), K_("CEO_C")))
        k3 = [(a, b) for (a, b), why in EV.items() if why == "K3 crm"]
        report("Q-PATH only K3 edge to a Cedar Row person is VP-Y_BANK",
               all({a, b} == {K_("VP"), K_("Y_BANK")} for a, b in k3 if {a, b} & set(roles[roles.org_id == K_("CEDAR")].person_id)))
        bad = set(crm.counterparty_person_id) & {K_(x) for x in ("B_BANK", "HL_MD", "OWN_B", "OWN_C", "CEO_B", "CEO_W", "CEO_C")}
        report("Q-PATH no CRM with B_BANK/HL_MD/OWN_B/OWN_C/target CEOs", not bad, bad)
        cx = crm[(crm.dd >= mb(24)) & (crm.dd <= T)]
        ced = cx[(cx.counterparty_org_id == K_("CEDAR")) | cx.counterparty_person_id.isin(set(roles[(roles.org_id == K_("CEDAR")) & roles.cur].person_id))]
        report("Q-PATH Cedar touchpoints 14 (10 VP-Y_BANK, 7 positive)", len(ced) == 14 and
               (ced.counterparty_person_id == K_("Y_BANK")).sum() == 10 and
               ((ced.counterparty_person_id == K_("Y_BANK")) & (ced.sentiment == "positive")).sum() == 7, len(ced))
        # ClosestIntermediary(T_COLD)
        tc = K_("T_COLD"); ties = []
        for _, r in sig[(sig.company_id == tc) & (sig.intermediary_id != "") & (sig.s >= mb(60))].iterrows():
            ties.append((r.s, r.intermediary_id))
        for _, r in txp[txp.party_role.isin(["sell_side_advisor", "buy_side_advisor", "debt_advisor"])].iterrows():
            if txn.at[r.txn_id, "target_id"] == tc and pd.Timestamp(txn.at[r.txn_id, "close_date"]) >= mb(60):
                ties.append((pd.Timestamp(txn.at[r.txn_id, "close_date"]), r.org_id))
        report("Q-PATH ClosestIntermediary(T_COLD) = HL, only HL", {i_ for _, i_ in ties} == {K_("HL")}, ties)

    # ---- Finale ----
    if "FINALE" in gq:
        warm = set()
        for cid in sc:
            for p in roles[(roles.org_id == cid) & (roles.role_type == "CEO") & roles.cur].person_id:
                if dist.get(p, 99) <= 2:
                    warm.add(cid)
        f3 = cast["NW_F3"]
        f3cur = set(own[(own.fund_id == f3) & own.cur].company_id)
        f3all = set(own[own.fund_id == f3].company_id)
        cl = tb["COMMERCIAL_LINK"]
        def touching(cos):
            return set(cl[cl.customer_id.isin(cos)].supplier_id) | set(cl[cl.supplier_id.isin(cos)].customer_id)
        conflict = touching(f3cur)
        sc2 = score(warm=warm, conflict=conflict)
        ta2 = ranked(sc2)
        exp = [(x["key"]["id"], x["score"]) for x in gq["FINALE"]["tier_a_ranked"]]
        report("FINALE Tier A order and scores", [(c, v["score"]) for c, v in ta2] == exp,
               [(v["name"], v["score"]) for c, v in ta2])
        report("FINALE warm set == {T_WARM, NM_B}", warm == {K_("T_WARM"), K_("NM_B")}, [sc[c]["name"] for c in warm])
        report("FINALE CONF flagged conflict", sc2[K_("CONF")]["tier"] == "Conflict")
        f1 = [sc[c]["name"] for c in sc if 60 <= sc[c]["score"] < 70 and c != K_("NM_B")]
        report("FINALE Guard F1 (NM_B only scorer in 60-69)", not f1, f1)
        for key in ("T_BANKER", "T_COLD", "T_5", "T_6", "CONF"):
            holders = set(roles[(roles.org_id == K_(key)) & roles.cur].person_id)
            md = min([dist_any_nw.get(p, 99) for p in holders] or [99])
            report(f"FINALE Guard F2 {key}: any current role-holder >= 3 from seeds and former Northwind people", md >= 3, md)
        tier_cos = {c for c, _ in ta} | {K_("NM_B")}
        report("FINALE conflict guard: only CONF touches current Fund III", touching(f3cur) & tier_cos == {K_("CONF")})
        report("FINALE conflict guard: no Tier-A/NM_B link to former Fund III holdings",
               not (touching(f3all - f3cur) & tier_cos))

    # ---- commercial graph ----
    cl = tb["COMMERCIAL_LINK"]
    CG = nx.Graph(); CG.add_edges_from(zip(cl.supplier_id, cl.customer_id))
    if "Q-ADDON" in gq:
        gid = K_("GRANITE"); Ng = set(CG[gid])
        report("Q-ADDON platform neighbors = 18", len(Ng) == 18, len(Ng))
        tic_id = [s_ for s_, r in sec.iterrows() if r["name"] == "Testing, Inspection & Certification"][0]
        jac = []
        for cid in CG.nodes:
            if cid == gid or cid in Ng:
                continue
            Nc = set(CG[cid]); sh = Ng & Nc
            if not sh:
                continue
            elig = tic_id in anc(comp.at[cid, "sector_id"]) and float(comp.at[cid, "ebitda_musd"]) <= 15.0 \
                and own[(own.company_id == cid) & own.cur].empty
            jac.append((round(len(sh) / len(Ng | Nc), 4), comp.at[cid, "name"], cid, elig))
        jac.sort(reverse=True)
        elig = [(j, cid) for j, _, cid, e in jac if e]
        exp = [(x["jaccard"], x["key"]["id"]) for x in gq["Q-ADDON"]["ranked"]]
        report("Q-ADDON ranking", elig[:3] == exp and all(j < 0.10 for j, _ in elig[3:]), jac[:6])
        report("Q-ADDON D_SAME absent", K_("D_SAME") not in [c for _, _, c, _ in jac])

    if "Q-CONFLICT" in gq:
        g = gq["Q-CONFLICT"]
        f3, f4_ = cast["NW_F3"], cast["NW_F4"]
        port = {c: f for c, f in zip(own[own.fund_id.isin(nw_funds) & own.cur].company_id,
                                     own[own.fund_id.isin(nw_funds) & own.cur].fund_id)}
        dd = nx.single_source_shortest_path_length(CG, K_("CONF"))
        near = {c: dd[c] for c in port if c in dd and dd[c] <= 2}
        report("Q-CONFLICT holdings within 2 hops == {PINE:1, GRANITE:2}", near == {K_("PINE"): 1, K_("GRANITE"): 2}, near)
        report("Q-CONFLICT REDFERN at distance 3", dd.get(K_("REDFERN")) == 3, dd.get(K_("REDFERN")))
        report("Q-CONFLICT BRIGHT distance 1, not current holding", dd.get(K_("BRIGHT")) == 1 and K_("BRIGHT") not in port)
        report("Q-CONFLICT PINE is Fund III, GRANITE Fund IV", port.get(K_("PINE")) == f3 and port.get(K_("GRANITE")) == f4_)
        allnw = set(own[own.fund_id.isin(nw_funds)].company_id)
        naive = {c for c in CG[K_("CONF")] if c in allnw}
        report("Q-CONFLICT naive 1-hop ever-owned = {PINE, BRIGHT}", naive == {K_("PINE"), K_("BRIGHT")}, naive)
        f4hold = own[(own.fund_id == f4_) & own.cur]
        report("Q-CONFLICT Fund IV holds exactly 5 companies, 645 deployed",
               len(f4hold) == 5 and abs(f4hold.equity_invested_musd.astype(float).sum() - 645) < 1e-6)
        def area(cid):
            return next((sec.at[x, "name"] for x in anc(comp.at[cid, "sector_id"]) if x in inc), None)
        size = float(fund.at[f4_, "size_musd"]); guide = float(fund.at[f4_, "area_guideline_pct"])
        expo = defaultdict(float)
        for _, o in f4hold.iterrows():
            expo[area(o.company_id)] += float(o.equity_invested_musd)
        chk = float(tb["PIPELINE"].set_index("company_id").at[K_("CONF"), "est_equity_check_musd"])
        before = expo["Specialty Distribution"] / size * 100
        after = (expo["Specialty Distribution"] + chk) / size * 100
        report("Q-CONFLICT Specialty Distribution 32.08% -> 36.67% > 35%",
               abs(before - 32.08) < 0.01 and abs(after - 36.67) < 0.01 and after > guide and area(K_("CONF")) == "Specialty Distribution",
               (before, after, guide))

    # ---- Q-FLOW ----
    if "Q-FLOW" in gq:
        thesis = {cid for cid, c in comp.iterrows() if set(anc(c.sector_id)) & set(inc) and not set(anc(c.sector_id)) & exc}
        tx = tb["TRANSACTION"]
        win = tx[(tx.close_date >= mb(60).date().isoformat()) & (tx.close_date <= AS_OF.isoformat()) & tx.target_id.isin(thesis)]
        FG = nx.Graph()
        for _, t_ in win.iterrows():
            ps = txp[txp.txn_id == t_.txn_id]
            advs = list(ps[ps.party_role.isin(["sell_side_advisor", "buy_side_advisor", "debt_advisor"])].org_id)
            buyers = list(ps[ps.party_role == "buyer"].org_id)
            others_ = list(ps[ps.party_role.isin(["seller", "owner"])].org_id)
            for a in advs:
                FG.add_edge(a, t_.target_id)
                for b in buyers + others_:
                    FG.add_edge(a, b)
            for b in buyers:
                FG.add_edge(b, t_.target_id)
        bc = nx.betweenness_centrality(FG, normalized=False)
        ints = sorted([n_ for n_ in FG if n_ in ids["intermediary"]], key=lambda n_: (-bc[n_], n_))
        iname = tb["INTERMEDIARY"].set_index("intermediary_id")["name"]
        print("INFO  Q-FLOW graph", FG.number_of_nodes(), "nodes", FG.number_of_edges(), "edges;", len(ints),
              "intermediaries; top 12:", [(iname[n_], round(bc[n_], 1)) for n_ in ints[:12]])
        report("Q-FLOW intermediaries in graph 31-40", 31 <= len(ints) <= 40, len(ints))
        report("Q-FLOW CEDAR #1, HL #2", ints[:2] == [K_("CEDAR"), K_("HL")])
        report("Q-FLOW BIGBANK rank >= 11", ints.index(K_("BIGBANK")) + 1 >= 11, ints.index(K_("BIGBANK")) + 1)
        tp = {}
        cx = crm[(crm.dd >= mb(24)) & (crm.dd <= T)]
        for i_ in ids["intermediary"]:
            ppl = set(roles[(roles.org_id == i_) & roles.cur].person_id)
            tp[i_] = int(((cx.counterparty_org_id == i_) | cx.counterparty_person_id.isin(ppl)).sum())
        vals = sorted(tp.values())
        q1 = vals[math.ceil(0.25 * len(vals)) - 1]
        topn = math.ceil(0.10 * len(ints))
        gaps = [i_ for i_ in ints[:topn] if tp[i_] <= q1]
        report("Q-FLOW 50 intermediaries, 8 at zero, >= 5 at one", len(vals) == 50 and vals.count(0) == 8 and vals.count(1) >= 5,
               (len(vals), vals.count(0), vals.count(1)))
        report("Q-FLOW Q1 == 1", q1 == 1, q1)
        report("Q-FLOW top decile == 4 and ranks 3-4 have >= 3 touchpoints", topn == 4 and all(tp[i_] >= 3 for i_ in ints[2:4]),
               [(iname[i_], tp[i_]) for i_ in ints[:4]])
        report("Q-FLOW gaps == [HL]", gaps == [K_("HL")], [iname[g_] for g_ in gaps])
        report("Q-FLOW touchpoints CEDAR 14, HL 1, BIGBANK 9",
               (tp[K_("CEDAR")], tp[K_("HL")], tp[K_("BIGBANK")]) == (14, 1, 9), (tp[K_("CEDAR")], tp[K_("HL")], tp[K_("BIGBANK")]))
        hl_deals = win[win.txn_id.isin(txp[txp.org_id == K_("HL")].txn_id)]
        report("Q-FLOW HL in-window thesis deals == 9", len(hl_deals) == 9, len(hl_deals))
        hl_sp = set()
        for tid in hl_deals.txn_id:
            ps = txp[(txp.txn_id == tid) & txp.party_role.isin(["buyer", "owner"])]
            hl_sp |= set(ps.org_id)
        report("Q-FLOW HL deals reach 5 distinct sponsors", len(hl_sp & ids["sponsor"]) == 5, len(hl_sp))
        allwin = tx[(tx.close_date >= mb(60).date().isoformat()) & (tx.close_date <= AS_OF.isoformat())]
        lt = txp[txp.txn_id.isin(allwin.txn_id) & (txp.org_type == "intermediary")].groupby("org_id").txn_id.nunique()
        report("Q-FLOW league table: BIGBANK first with 40", lt.idxmax() == K_("BIGBANK") and lt.max() == 40, lt.max())
        report("Q-FLOW BIGBANK thesis deals == 8", win.txn_id.isin(txp[txp.org_id == K_("BIGBANK")].txn_id).sum() == 8)

    # ---- hygiene ----
    blob = "".join((CSV_DIR / f"{n}.csv").read_text() for n in TABLES) + (GOLDEN_DIR / "stories.md").read_text() \
        + (GOLDEN_DIR / "expected.json").read_text()
    report("no em dash", "—" not in blob)
    print("SELF-CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# =====================================================================================
# Build
# =====================================================================================

def build(noise: bool = False) -> World:
    w = World(RANDOM_SEED)
    build_reference(w)
    plant_shared_cast(w)
    for _q, fn in STORIES.items():
        fn(w)
    right_size_funds(w)
    golden_extras(w)
    w.signal_ownership_ids = {o["ownership_id"] for o in w.t["OWNERSHIP"]}
    add_noise(w, enabled=noise)
    reprice_deals(w)
    realism_guards(w)
    return w


def main(argv):
    # CLI plumbing (R12): --out DIR redirects CSVs (and --check / --noise-check) to DIR;
    # --noise adds the P5 noise layer and requires --out (data/csv/ stays signal-only until P5).
    global CSV_DIR, GOLDEN_DIR
    if "--out" in argv:
        CSV_DIR = Path(argv[argv.index("--out") + 1]).resolve()
    if "--noise-check" in argv:
        sys.exit(noise_check(CSV_DIR))
    if "--check" in argv:
        sys.exit(selfcheck())
    noise = "--noise" in argv
    if noise and "--out" not in argv:
        sys.exit("--noise needs an explicit --out DIR (data/csv/ stays signal-only until the orchestrator flips the default; "
                 "the P5 flip is: --noise --out data/csv)")
    w = build(noise)
    m = write_csvs(w)
    if noise:
        # golden is generator intent and must not move with noise: rebuild it in a temp dir and compare bytes
        import tempfile
        real = GOLDEN_DIR
        with tempfile.TemporaryDirectory() as td:
            GOLDEN_DIR = Path(td)
            write_golden(w)
            write_stories(w)
            same = all((Path(td) / f).read_bytes() == (real / f).read_bytes() for f in ("expected.json", "stories.md"))
        GOLDEN_DIR = real
        print(f"golden unchanged by noise: {same}")
        if not same:
            sys.exit("noise changed the golden intent; fix the noise, never golden")
    else:
        write_golden(w)
        write_stories(w)
    print(f"wrote {len(m['tables'])} tables, {m['total_rows']} rows to {CSV_DIR}")


if __name__ == "__main__":
    main(sys.argv[1:])
