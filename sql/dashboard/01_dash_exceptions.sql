-- Dashboard feed: one row per exception, with its money impact and triage status.
--
-- Money impact, defined once here so the dashboard never invents its own maths:
--   leakage_amount        money lost: fees not collected, plus money paid to
--                         merchants that wasn't due
--   owed_to_merchant      money merchants are still owed (missing or short settlements)
--   fraud_amount_at_risk  the amount moved out in a suspected account drain
--
-- Duplicates show leakage 0 on purpose: every duplicate also fails the
-- reconciliation, which already counts the overpayment. Counting it twice
-- would overstate leakage.
--
-- AI triage comes from Claude Opus 5.5, the model validated against the hand labels.

CREATE OR REPLACE VIEW `{dataset}.dash_exceptions` AS

WITH exceptions AS (
  SELECT * FROM `{dataset}.check_fee_recompute`
  UNION ALL SELECT * FROM `{dataset}.check_settlement_recon`
  UNION ALL SELECT * FROM `{dataset}.check_duplicate_settlement`
  UNION ALL SELECT * FROM `{dataset}.check_fraud_account_drain`
),

-- The latest successful Opus answer for each exception, if it has one.
ai AS (
  SELECT txn_id, check_name, ai_category, ai_note
  FROM `{dataset}.triage_results`
  WHERE model_requested = 'claude-opus-5-5'
    AND ai_category IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY txn_id, check_name ORDER BY triaged_at DESC
  ) = 1
)

SELECT
  e.check_name,
  CASE e.check_name
    WHEN 'fee_recompute'        THEN 'Wrong fee charged'
    WHEN 'settlement_recon'     THEN 'Settlement mismatch'
    WHEN 'duplicate_settlement' THEN 'Duplicate settlement'
    WHEN 'fraud_account_drain'  THEN 'Possible fraud: account drained'
  END                                    AS exception_type,
  e.txn_id,
  t.type                                 AS transaction_type,
  t.day,
  t.amount,
  e.expected_value,
  e.actual_value,
  e.difference,

  CASE
    WHEN e.check_name = 'fee_recompute'    THEN GREATEST(e.expected_value - e.actual_value, 0)
    WHEN e.check_name = 'settlement_recon' THEN GREATEST(e.difference, 0)   -- overpaid
    ELSE 0
  END                                    AS leakage_amount,

  IF(e.check_name = 'settlement_recon', GREATEST(-e.difference, 0), 0)
                                         AS owed_to_merchant,

  IF(e.check_name = 'fraud_account_drain', t.amount, 0)
                                         AS fraud_amount_at_risk,

  IF(ai.ai_category IS NULL, 'Awaiting triage', 'Triaged by AI')
                                         AS triage_status,
  ai.ai_category,
  ai.ai_note
FROM exceptions AS e
JOIN `{dataset}.transactions` AS t USING (txn_id)
LEFT JOIN ai USING (txn_id, check_name)
