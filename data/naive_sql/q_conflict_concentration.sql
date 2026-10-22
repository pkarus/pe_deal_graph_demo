-- description: Concentration by GROUP BY on each company's own niche: Fund IV current equity per niche, plus the bid subject's estimated check added to its own niche, as a share of Fund IV size.
-- metric_label: Pro forma share of Fund IV (percent, by niche)
-- Q-CONFLICT naive baseline, part 2 (owner R11). QUESTIONS.md v2 Q-CONFLICT "Decoy spec" step 2. Not read by the exporter.
-- Expected: the largest niche is Specialty Chemicals Distribution at 11.7% and the subject's niche goes to 4.6%, so every
-- row is under the 35% guideline: "no concentration issue". It misses the Specialty Distribution breach (36.7%), which
-- needs the roll-up from niche to the mixed-level thesis area.
WITH fund4 AS (
    SELECT f.fund_id, f.size_musd, f.area_guideline_pct
    FROM FUND f JOIN SPONSOR sp ON sp.sponsor_id = f.sponsor_id
    WHERE sp.name = 'Northwind Equity Partners' AND f.name LIKE '%Fund IV'
), held AS (
    SELECT c.sector_id, SUM(o.equity_invested_musd) AS musd
    FROM OWNERSHIP o JOIN fund4 ON fund4.fund_id = o.fund_id JOIN COMPANY c ON c.company_id = o.company_id
    WHERE o.start_date <= '2026-10-01'::DATE AND (o.end_date IS NULL OR o.end_date > '2026-10-01'::DATE)
    GROUP BY c.sector_id
), bid AS (
    SELECT c.sector_id, SUM(pl.est_equity_check_musd) AS musd
    FROM PIPELINE pl JOIN COMPANY c ON c.company_id = pl.company_id
    WHERE pl.stage = 'IOI prep'
    GROUP BY c.sector_id
)
SELECT n.sector_id AS entity_id,
       n.name AS name,
       ROUND(100 * (COALESCE(h.musd, 0) + COALESCE(b.musd, 0)) / fund4.size_musd, 1) AS metric,
       IFF(100 * (COALESCE(h.musd, 0) + COALESCE(b.musd, 0)) / fund4.size_musd > fund4.area_guideline_pct,
           'breach', 'under guideline') AS verdict
FROM SECTOR n
LEFT JOIN held h ON h.sector_id = n.sector_id
LEFT JOIN bid b ON b.sector_id = n.sector_id
CROSS JOIN fund4
WHERE h.sector_id IS NOT NULL OR b.sector_id IS NOT NULL
ORDER BY metric DESC, name ASC
