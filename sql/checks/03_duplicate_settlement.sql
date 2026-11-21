-- Check 3: duplicate settlements
--
-- A merchant should be paid once per payment. Flag any transaction that the
-- ledger settled more than once.
--
-- Reversals count against settlements: a payout that bounced, was reversed and
-- was sent again has 2 settlements - 1 reversal = 1 effective settlement. That's
-- legitimate, so it must not be flagged. Counting settlement rows alone would
-- flag it.
--
-- Limitation: this matches on txn_id. A duplicate sent under a different
-- reference would need a fuzzy match (same merchant, amount and day).

CREATE OR REPLACE VIEW `{dataset}.check_duplicate_settlement` AS

-- Summarise the ledger per transaction.
WITH per_txn AS (
  SELECT
    txn_id,
    COUNTIF(record_type = 'SETTLEMENT')
      - COUNTIF(record_type = 'REVERSAL')                    AS effective_settlements,
    MAX(IF(record_type = 'SETTLEMENT', settled_amount, NULL)) AS one_settlement,
    SUM(settled_amount)                                      AS net_settled
  FROM `{dataset}.settlements`
  GROUP BY txn_id
)

SELECT
  'duplicate_settlement'          AS check_name,
  txn_id,
  one_settlement                  AS expected_value,   -- paid once
  net_settled                     AS actual_value,     -- actually paid in total
  net_settled - one_settlement    AS difference        -- the overpayment
FROM per_txn
WHERE effective_settlements > 1
