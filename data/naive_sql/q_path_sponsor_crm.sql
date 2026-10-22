-- description: CRM search for the sponsor that owns a cold target: "do we know Saltmarsh's owner?"
-- metric_label: CRM interactions with the owner sponsor
-- Q-PATH near miss "we know the sponsor" (golden expected.json Q-PATH naive_sql.near_misses, label near_miss (CRM search)).
-- Not read by the exporter (it reads q_path.sql only). Expected: one neutral org-level meeting by Dana Okafor with
-- Coppervale Partners on 2025-03-04, so a CRM search says "we know Coppervale", while RAI shows the owner designee
-- Graham Pike is more than 3 hops from every Northwind seed.
SELECT x.interaction_id AS entity_id,
       sp.name AS name,
       1 AS metric,
       me.full_name AS our_person,
       x.interaction_date,
       x.channel,
       x.sentiment
FROM COMPANY t
JOIN OWNERSHIP o ON o.company_id = t.company_id AND o.stake_type = 'majority'
                AND o.start_date <= '2026-10-01'::DATE AND (o.end_date IS NULL OR o.end_date > '2026-10-01'::DATE)
JOIN FUND f ON f.fund_id = o.fund_id
JOIN SPONSOR sp ON sp.sponsor_id = f.sponsor_id
JOIN CRM_INTERACTION x ON x.counterparty_org_id = sp.sponsor_id
JOIN PERSON me ON me.person_id = x.our_person_id
WHERE t.name = 'Saltmarsh Home Infusion'
ORDER BY x.interaction_date, entity_id
