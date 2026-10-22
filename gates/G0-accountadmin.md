# G0-accountadmin - ACCOUNTADMIN access to the demo (R01, read-only)

All checks via `snow sql -c rai` (warehouse only, no RAI engine, no PyRel). No grants were applied.

| Check | Result |
|---|---|
| CURRENT_ROLE() | ACCOUNTADMIN |
| GRANTS OF ROLE RAI_DEMO_PE | to ROLE SYSADMIN (by ACCOUNTADMIN) and to USER piotr.kraus@relational.ai (created 2026-10-21 23:16, so the user-level gap from a3 is now closed) |
| GRANTS OF ROLE SYSADMIN | granted to ROLE ACCOUNTADMIN. Chain ACCOUNTADMIN > SYSADMIN > RAI_DEMO_PE holds. |
| GRANTS ON DATABASE RAI_DEMO_PE_DEALS | OWNERSHIP to RAI_DEMO_PE |
| GRANTS ON SCHEMA DEAL_GRAPH | OWNERSHIP to RAI_DEMO_PE |
| Row counts | COMPANY 1096, PERSON 2506, TRANSACTION 635 |
| Tables in DEAL_GRAPH | 18 base tables: the 17 demo tables plus SMOKE_TEST (all visible) |
| Warehouse RAI_DEMO_PE_WH | USAGE to RAI_DEMO_PE; OWNERSHIP to SYSADMIN. ACCOUNTADMIN inherits both. |
| Application RELATIONALAI | V4, 2026.10.10-d139e47, patch 106, owned by ACCOUNTADMIN |
| GRANTS TO ROLE RAI_DEMO_PE | RELATIONALAI.RAI_USER, DB and schema OWNERSHIP, table OWNERSHIP (all demo tables) |

Inheritance means ACCOUNTADMIN reaches everything through the role hierarchy. Tables are owned by RAI_DEMO_PE, which is inherited, so no direct grant to ACCOUNTADMIN is needed.

VERDICT: ACCESS OK (no gap, no change made). data/01_accountadmin_access.sql was not needed.
