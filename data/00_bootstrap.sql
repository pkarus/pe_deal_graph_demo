-- =============================================================================
-- 00_bootstrap.sql - one-time Snowflake bootstrap for the PE deal-graph demo
-- Owner: R01 Platform Engineer. Status: DRAFT, awaiting user approval (Phase 0).
-- Account ajb85638, user "piotr.kraus@relational.ai" (from SELECT CURRENT_USER()).
-- RelationalAI Native App: RELATIONALAI, version V4 label 2026.10.10-d139e47 patch 106.
--
-- Scope (nothing else is touched): role RAI_DEMO_PE, warehouse RAI_DEMO_PE_WH,
-- database RAI_DEMO_PE_DEALS, schema RAI_DEMO_PE_DEALS.DEAL_GRAPH, and one RAI
-- application-role grant. Idempotent: every CREATE uses IF NOT EXISTS and every
-- GRANT is a no-op when already held, so the file can be re-run safely.
--
-- Sources cited below:
--   [SF-AC]   Snowflake access-control best practices (SECURITYADMIN creates roles and
--             manages grants; SYSADMIN creates warehouses/databases; custom roles roll up to SYSADMIN).
--   [RAI-UA]  https://docs.relational.ai/manage/app/user-access  ("CREATE ROLE ...;
--             GRANT APPLICATION ROLE RELATIONALAI.<application_role_name> TO ROLE ...;
--             GRANT ROLE ... TO USER ..."; rai_user = minimum set to run PyRel, bundles
--             app_user, eng_user, eng_admin, cdc_admin, all_schema_cdc).
--   [RAI-SKILL] rai-setup skill: "Custom Snowflake roles also work if granted the
--             rai_user application role".
--   [RAI-CDS] https://docs.relational.ai/api/sql/api/create_data_stream  (caller needs
--             SELECT on the source + change tracking + cdc_admin; no grant to the app).
--   [RAI-PREP] https://docs.relational.ai/manage/data/prepare  (CHANGE_TRACKING needs
--             ownership of the table).
--   [OBS]     Read-only observation in this account on 2026-10-21 (see gates/G0-draft.md).
-- =============================================================================

-- 1. Roles and user access ----------------------------------------------------

-- SECURITYADMIN holds CREATE ROLE and MANAGE GRANTS; user reaches it via ACCOUNTADMIN [SF-AC][OBS: SHOW GRANTS OF ROLE SECURITYADMIN -> ACCOUNTADMIN].
USE ROLE SECURITYADMIN;

-- The single working role for the whole build; every agent connects as it [RAI-UA][CONFIG SNOWFLAKE_ROLE].
CREATE ROLE IF NOT EXISTS RAI_DEMO_PE COMMENT = 'PE deal-graph demo working role. Safe to drop.';

-- Lets the build user assume the role (raiconfig.yaml connects with role RAI_DEMO_PE). Username is lowercase with '@', so it must be double-quoted [RAI-UA][OBS: unquoted form fails with "does not exist"].
GRANT ROLE RAI_DEMO_PE TO USER "piotr.kraus@relational.ai";

-- Rolls the custom role up to SYSADMIN so admins keep control of objects it owns (and SYSADMIN can re-run the ownership grant below) [SF-AC].
GRANT ROLE RAI_DEMO_PE TO ROLE SYSADMIN;

-- 2. Warehouse ----------------------------------------------------------------

-- SYSADMIN holds CREATE WAREHOUSE and CREATE DATABASE [SF-AC][OBS: SHOW GRANTS TO ROLE SYSADMIN].
USE ROLE SYSADMIN;

-- Cost guardrail from CONFIG: XSMALL, 60 s auto-suspend, starts suspended; PyRel runs its SQL on the session warehouse [CONFIG][PROMPT section 3 Cost].
CREATE WAREHOUSE IF NOT EXISTS RAI_DEMO_PE_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'PE deal-graph demo warehouse. Safe to drop.';

-- USAGE is enough to run queries and to auto-resume; OPERATE was struck (no manual resume/suspend is needed, PyRel never issues one) [SF-AC][OBS: no warehouse resume calls in relationalai 1.27.1].
GRANT USAGE ON WAREHOUSE RAI_DEMO_PE_WH TO ROLE RAI_DEMO_PE;

-- 3. Database and schema ------------------------------------------------------

-- The only database this build may write to (blast radius) [CONFIG SNOWFLAKE_DATABASE][PROMPT section 3].
CREATE DATABASE IF NOT EXISTS RAI_DEMO_PE_DEALS COMMENT = 'Synthetic PE deal-graph demo. Safe to drop.';

-- Role owns the database so it owns every table it creates, which ALTER TABLE ... SET CHANGE_TRACKING requires; matches existing demo roles in this account (RAI_DEMO_CARS owns CARS_DEMO) [RAI-PREP][OBS].
GRANT OWNERSHIP ON DATABASE RAI_DEMO_PE_DEALS TO ROLE RAI_DEMO_PE COPY CURRENT GRANTS;

-- Create the schema as the working role so RAI_DEMO_PE owns it outright [SF-AC].
USE ROLE RAI_DEMO_PE;

-- Target schema from CONFIG; source tables (R07) and any PyRel deploy objects live here [CONFIG SNOWFLAKE_SCHEMA].
CREATE SCHEMA IF NOT EXISTS RAI_DEMO_PE_DEALS.DEAL_GRAPH COMMENT = 'PE deal-graph demo tables. Safe to drop.';

-- 4. RelationalAI Native App access -------------------------------------------

-- The RELATIONALAI app is owned by ACCOUNTADMIN, so only ACCOUNTADMIN can grant its application roles [OBS: SHOW APPLICATIONS owner = ACCOUNTADMIN].
USE ROLE ACCOUNTADMIN;

-- rai_user is the documented minimum for PyRel (app use, reasoner create/use, data streams); RAI_USER exists in the installed app [RAI-UA][RAI-SKILL][OBS: SHOW APPLICATION ROLES IN APPLICATION RELATIONALAI].
GRANT APPLICATION ROLE RELATIONALAI.RAI_USER TO ROLE RAI_DEMO_PE;

-- STRUCK from skeleton: GRANT USAGE ON DATABASE RAI_DEMO_PE_DEALS TO APPLICATION RELATIONALAI;
--   Not required: create_data_stream needs SELECT + change tracking on the caller side and binds the
--   source through an app reference (DATA_STREAM_TABLE). In this account 36 streams over PK_REGULATORY,
--   CARS_DEMO and PK_NESTLE_DIET are CREATED with zero grants on those databases to the app [RAI-CDS][OBS].
-- STRUCK from skeleton: GRANT USAGE ON SCHEMA RAI_DEMO_PE_DEALS.DEAL_GRAPH TO APPLICATION RELATIONALAI;
--   Same reason as above.
-- No table-level grants to the app are needed. R07 must create every source table with
--   CHANGE_TRACKING = TRUE while connected as RAI_DEMO_PE (owner) [RAI-PREP].

-- 5. Read-only verification (safe to run any time) ----------------------------

-- Confirms the role holds: USAGE on RAI_DEMO_PE_WH, OWNERSHIP on RAI_DEMO_PE_DEALS and DEAL_GRAPH, application role RELATIONALAI.RAI_USER [RAI-UA].
SHOW GRANTS TO ROLE RAI_DEMO_PE;
