-- description: League table: distinct deals per advisor (sell-side, buy-side or debt advisor) over all transactions in the last 5 years, any sector, most deals first.
-- metric_label: Deals advised in 5 years (all sectors)
-- kg_label: Top bridges
-- Q-FLOW naive baseline (owner R11). QUESTIONS.md v2 Q-FLOW "Decoy spec". AS_OF = 2026-10-01, T-5y = 2021-10-01.
-- Expected decoy: Brayford Capital Markets tops it with about 40 deals; Harbor Lane Advisors sits around 10th with 9.
-- The league table cannot see betweenness or that we touched Harbor Lane once in 24 months.
SELECT i.intermediary_id AS entity_id,
       i.name AS name,
       COUNT(DISTINCT t.txn_id) AS metric
FROM INTERMEDIARY i
JOIN TRANSACTION_PARTY p ON p.org_id = i.intermediary_id
                        AND p.party_role IN ('sell_side_advisor', 'buy_side_advisor', 'debt_advisor')
JOIN TRANSACTION t ON t.txn_id = p.txn_id
WHERE t.close_date BETWEEN '2021-10-01'::DATE AND '2026-10-01'::DATE
GROUP BY i.intermediary_id, i.name
ORDER BY metric DESC, name ASC
