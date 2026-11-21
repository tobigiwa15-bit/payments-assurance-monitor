-- Check 1: fee recomputation
--
-- Recompute the correct fee for every transaction from the fee schedule, and
-- compare it with the fee actually charged. Every difference is an exception:
-- undercharging is revenue leakage, overcharging is customer harm.
--
-- Tolerance: 0.01. Fees are calculated by a fixed formula, so the correct fee
-- is exact and any difference of a cent or more is a genuine error.
--
-- {dataset} is filled in by scripts/03_create_checks.py with your project and dataset.

CREATE OR REPLACE VIEW `{dataset}.check_fee_recompute` AS

-- Step 1: find each transaction's fee band and apply the rate and fixed fee.
WITH banded AS (
  SELECT
    t.txn_id,
    t.fee_charged,
    ROUND(t.amount * s.fee_rate_bps / 10000, 2) + s.fixed_fee AS uncapped_fee,
    s.fee_cap
  FROM `{dataset}.transactions` AS t
  -- LEFT JOIN, not JOIN: a transaction with no matching fee band must show up
  -- as an exception, not silently drop out of the check.
  LEFT JOIN `{dataset}.fee_schedule` AS s
    ON  s.type = t.type
    AND t.amount >= s.min_amount
    AND (s.max_amount IS NULL OR t.amount <= s.max_amount)
),

-- Step 2: apply the cap, where the band has one.
recomputed AS (
  SELECT
    txn_id,
    fee_charged,
    IF(fee_cap IS NULL, uncapped_fee, LEAST(uncapped_fee, fee_cap)) AS expected_fee
  FROM banded
)

-- Step 3: keep only the transactions where the fee charged is wrong.
SELECT
  'fee_recompute'              AS check_name,
  txn_id,
  expected_fee                 AS expected_value,
  fee_charged                  AS actual_value,
  fee_charged - expected_fee   AS difference   -- negative = undercharged
FROM recomputed
WHERE expected_fee IS NULL                     -- no fee band matched
   OR ABS(fee_charged - expected_fee) >= 0.01
