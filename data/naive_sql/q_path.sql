-- description: Shared-employer join: any current Northwind deal-team or operating-partner person who ever worked at the same organization as the current CEO of a top-three target, ignoring dates.
-- metric_label: Claimed hops (shared employer)
-- kg_label: Warm targets
-- Q-PATH naive baseline (owner R11). QUESTIONS.md v2 Q-PATH "Decoy spec" and golden Q-PATH naive_sql.
-- The analyst types the top three from the Act 1 list. One row per claimed introduction; entity_id is the target company.
-- Expected: exactly one row, Tom Harlowe -> Victor Hale (Saltmarsh Home Infusion) via Varnell Lab Services.
-- It is false: Tom Harlowe left Varnell 2011-06-30, Victor Hale joined 2013-03-04 (613-day gap). RAI calls Saltmarsh cold.
-- Near misses (golden expected.json Q-PATH naive_sql.near_misses), not SQL decoys:
--   stale tie (Dana Okafor - Walter Kim, Oldmere Health System 1998-2000): a real Knows edge that RAI ranks second (0.287);
--     no shared-employer join to a CEO returns it (Walter Kim is a board member), so it has no SQL route here.
--   "we know the sponsor": see q_path_sponsor_crm.sql (a CRM search for the owner sponsor of Saltmarsh).
SELECT t.company_id AS entity_id,
       t.name AS name,
       1 AS metric,
       sp.full_name AS our_person,
       cp.full_name AS ceo,
       org.org_name AS shared_employer,
       'claims ' || sp.full_name || ' knows ' || cp.full_name || ' via ' || org.org_name
         || ' (' || TO_VARCHAR(rs.start_date) || ' to ' || COALESCE(TO_VARCHAR(rs.end_date), 'present')
         || ' vs ' || TO_VARCHAR(rc.start_date) || ' to ' || COALESCE(TO_VARCHAR(rc.end_date), 'present') || ')' AS note
FROM COMPANY t
JOIN ROLE_HISTORY ceo ON ceo.org_id = t.company_id AND ceo.role_type = 'CEO' AND ceo.end_date IS NULL
JOIN ROLE_HISTORY rc ON rc.person_id = ceo.person_id AND rc.org_id <> t.company_id
JOIN ROLE_HISTORY rs ON rs.org_id = rc.org_id
JOIN ROLE_HISTORY nw ON nw.person_id = rs.person_id AND nw.role_type IN ('Deal Team', 'Operating Partner') AND nw.end_date IS NULL
JOIN SPONSOR nws ON nws.sponsor_id = nw.org_id AND nws.name = 'Northwind Equity Partners'
JOIN PERSON sp ON sp.person_id = rs.person_id
JOIN PERSON cp ON cp.person_id = ceo.person_id
JOIN (SELECT company_id AS org_id, name AS org_name FROM COMPANY
      UNION ALL SELECT sponsor_id, name FROM SPONSOR
      UNION ALL SELECT intermediary_id, name FROM INTERMEDIARY) org ON org.org_id = rc.org_id
WHERE t.name IN ('Larkspur Revenue Partners', 'Bayside Pediatric Therapy Group', 'Saltmarsh Home Infusion')
  AND rc.org_id <> nws.sponsor_id
  AND rs.person_id <> ceo.person_id
ORDER BY name ASC, our_person ASC, ceo ASC
