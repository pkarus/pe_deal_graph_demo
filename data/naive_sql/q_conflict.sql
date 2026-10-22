-- description: One-hop conflict join: companies linked to the bid subject (pipeline stage IOI prep) by a commercial link in either direction that appear in any Northwind ownership row ever recorded (no current-ownership filter).
-- metric_label: Commercial links to the bid subject
-- kg_label: Conflicts
-- Q-CONFLICT naive baseline, part 1 (owner R11). QUESTIONS.md v2 Q-CONFLICT "Decoy spec" step 1.
-- Expected: Pinewick Dermatology Partners (real conflict) and Cobbleton Dental Group (false alarm: Northwind sold it 2020-02-14).
-- It misses Ironvale Testing Group, two links away. Part 2 (concentration by niche) is q_conflict_concentration.sql.
SELECT c.company_id AS entity_id,
       c.name AS name,
       COUNT(DISTINCT l.link_id) AS metric,
       LISTAGG(DISTINCT f.name || ' ' || TO_VARCHAR(o.start_date) || ' to ' || COALESCE(TO_VARCHAR(o.end_date), 'present'), '; ')
         WITHIN GROUP (ORDER BY f.name || ' ' || TO_VARCHAR(o.start_date) || ' to ' || COALESCE(TO_VARCHAR(o.end_date), 'present')) AS note
FROM PIPELINE pl
JOIN COMMERCIAL_LINK l ON pl.company_id IN (l.supplier_id, l.customer_id)
JOIN COMPANY c ON c.company_id = IFF(l.supplier_id = pl.company_id, l.customer_id, l.supplier_id)
JOIN OWNERSHIP o ON o.company_id = c.company_id
JOIN FUND f ON f.fund_id = o.fund_id
JOIN SPONSOR sp ON sp.sponsor_id = f.sponsor_id AND sp.name = 'Northwind Equity Partners'
WHERE pl.stage = 'IOI prep'
GROUP BY c.company_id, c.name
ORDER BY name ASC
