-- Check 2: transaction-to-settlement reconciliation
--
-- Every merchant PAYMENT should be settled to the merchant for exactly
-- amount - fee_charged. Match each payment to what the ledger actually paid
-- out, in both directions:
--   - payments with no settlement, or the wrong amount settled
--   - settlements with no payment behind them
--
-- As at: end of day 30. Payments settle the next day, so only payments made up
-- to day 29 are due by then. Day-30 payments are pending, not missing (cut-off).
--
-- Tolerance: 0.01. Settlement amounts are exact, so a cent or more is an error.

CREATE OR REPLACE VIEW `{dataset}.check_settlement_recon` AS

-- Side 1: what each merchant should have received, for payments due by day 30.
WITH due AS (
  SELECT
    txn_id,
    amount - fee_charged AS net_due
  FROM `{dataset}.transactions`
  WHERE type = 'PAYMENT'
    AND day + 1 <= 30          -- settlement due date on or before the as-at date
),

-- Side 2: what the ledger actually paid per transaction, up to day 30.
-- Summing all rows nets reversals (negative) off against settlements.
settled AS (
  SELECT
    txn_id,
    SUM(settled_amount) AS net_settled
  FROM `{dataset}.settlements`
  WHERE settlement_day <= 30
  GROUP BY txn_id
),

-- Match the two sides. FULL OUTER JOIN keeps unmatched rows from either side;
-- a missing side counts as zero.
matched AS (
  SELECT
    COALESCE(d.txn_id, s.txn_id) AS txn_id,
    IFNULL(d.net_due, 0)         AS net_due,
    IFNULL(s.net_settled, 0)     AS net_settled
  FROM due AS d
  FULL OUTER JOIN settled AS s
    ON s.txn_id = d.txn_id
)

SELECT
  'settlement_recon'         AS check_name,
  txn_id,
  net_due                    AS expected_value,
  net_settled                AS actual_value,
  net_settled - net_due      AS difference   -- negative = merchant underpaid
FROM matched
WHERE ABS(net_settled - net_due) >= 0.01
