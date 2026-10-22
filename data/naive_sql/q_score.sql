-- description: Keyword sector screen (no hierarchy): niche or company name matches a sector keyword, EBITDA $5-40M, HQ in a hard-coded US state list, not a current Northwind holding, ranked by the count of any signal in the last 12 months.
-- metric_label: Signals in the last 12 months (any type)
-- kg_label: Tier A
-- Q-SCORE naive baseline (owner R11). QUESTIONS.md v2 Q-SCORE "Decoy spec". AS_OF = 2026-10-01, T-12m = 2025-10-01.
-- Expected decoys: Cobalt Urgent Care Partners (5), Pembrook Veterinary Pharmaceuticals (4), Linden Hollow Senior Care (3) on top;
-- misses Saltmarsh Home Infusion and Quarry Records Retrieval; Ashby Vale Dental Partners (Tier B) outranks every Tier-A name.
SELECT c.company_id AS entity_id,
       c.name AS name,
       COUNT(s.signal_id) AS metric
FROM COMPANY c
JOIN SECTOR n ON n.sector_id = c.sector_id
LEFT JOIN COMPANY_SIGNAL s
       ON s.company_id = c.company_id
      AND s.signal_date BETWEEN '2025-10-01'::DATE AND '2026-10-01'::DATE
WHERE (n.name ILIKE ANY ('%health%', '%medical%', '%clinic%', '%dental%', '%veterinar%', '%care%', '%testing%', '%inspection%', '%distribution%')
       OR c.name ILIKE ANY ('%health%', '%medical%', '%clinic%', '%dental%', '%veterinar%', '%care%', '%testing%', '%inspection%', '%distribution%'))
  AND c.ebitda_musd BETWEEN 5 AND 40
  AND c.hq_region_id IN ('US-AK','US-AL','US-AR','US-AZ','US-CA','US-CO','US-CT','US-DC','US-DE','US-FL','US-GA','US-HI',
                         'US-IA','US-ID','US-IL','US-IN','US-KS','US-KY','US-LA','US-MA','US-MD','US-ME','US-MI','US-MN',
                         'US-MO','US-MS','US-MT','US-NC','US-ND','US-NE','US-NH','US-NJ','US-NM','US-NV','US-NY','US-OH',
                         'US-OK','US-OR','US-PA','US-RI','US-SC','US-SD','US-TN','US-TX','US-UT','US-VA','US-VT','US-WA',
                         'US-WI','US-WV','US-WY')
  AND c.company_id NOT IN (
        SELECT o.company_id
        FROM OWNERSHIP o
        JOIN FUND f ON f.fund_id = o.fund_id
        JOIN SPONSOR sp ON sp.sponsor_id = f.sponsor_id
        WHERE sp.name = 'Northwind Equity Partners'
          AND o.start_date <= '2026-10-01'::DATE
          AND (o.end_date IS NULL OR o.end_date > '2026-10-01'::DATE))
GROUP BY c.company_id, c.name
ORDER BY metric DESC, name ASC
