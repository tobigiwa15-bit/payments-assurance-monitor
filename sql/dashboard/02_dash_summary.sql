-- Dashboard totals: one row per exception type, plus a grand total.
--
-- The dashboard's headline numbers should match this view exactly. It's also
-- where the README's figures for exceptions and leakage come from.

CREATE OR REPLACE VIEW `{dataset}.dash_summary` AS

WITH by_type AS (
  SELECT
    exception_type,
    COUNT(*)                                  AS exceptions,
    SUM(leakage_amount)                       AS leakage_amount,
    SUM(owed_to_merchant)                     AS owed_to_merchant,
    SUM(fraud_amount_at_risk)                 AS fraud_amount_at_risk,
    COUNTIF(triage_status = 'Triaged by AI')  AS triaged_by_ai,
    COUNTIF(triage_status = 'Awaiting triage') AS awaiting_triage
  FROM `{dataset}.dash_exceptions`
  GROUP BY exception_type
)

SELECT * FROM by_type
UNION ALL
SELECT
  'All exceptions',
  SUM(exceptions), SUM(leakage_amount), SUM(owed_to_merchant),
  SUM(fraud_amount_at_risk), SUM(triaged_by_ai), SUM(awaiting_triage)
FROM by_type
