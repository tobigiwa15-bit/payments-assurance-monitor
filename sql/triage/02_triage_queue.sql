-- The triage queue: every exception from the four checks, with the same
-- evidence the benchmark sample shows (see 01_triage_sample.sql).
--
-- The daily run sends the next 20 that the AI hasn't answered yet. The order
-- takes turns across the four checks, largest amount first within each check,
-- so every type of exception gets worked on, biggest money first, instead of
-- the 8,008 fraud flags crowding out everything else.
--
-- Like the sample, the evidence leaves out isFraud, isFlaggedFraud and the
-- answer key: those are the answers.

CREATE OR REPLACE VIEW `{dataset}.triage_queue` AS

WITH exceptions AS (
  SELECT * FROM `{dataset}.check_fee_recompute`
  UNION ALL SELECT * FROM `{dataset}.check_settlement_recon`
  UNION ALL SELECT * FROM `{dataset}.check_duplicate_settlement`
  UNION ALL SELECT * FROM `{dataset}.check_fraud_account_drain`
),

-- What the ledger shows for each transaction.
settlement_summary AS (
  SELECT
    txn_id,
    COUNTIF(record_type = 'SETTLEMENT') AS settlement_rows,
    COUNTIF(record_type = 'REVERSAL')   AS reversal_rows,
    SUM(settled_amount)                 AS net_settled
  FROM `{dataset}.settlements`
  GROUP BY txn_id
)

SELECT
  -- 1 = the largest exception in its check, 2 = the next largest, and so on.
  -- Sorting by this rank alternates between the checks.
  ROW_NUMBER() OVER (
    PARTITION BY e.check_name ORDER BY t.amount DESC, e.txn_id
  )                    AS queue_rank,
  e.check_name,
  e.txn_id,
  e.expected_value,
  e.actual_value,
  e.difference,
  t.type,
  t.day,
  t.amount,
  t.oldbalanceOrg,
  t.newbalanceOrig,
  t.nameDest,
  t.oldbalanceDest,
  t.newbalanceDest,
  t.fee_charged,
  b.fee_rate_bps,
  b.fixed_fee,
  b.fee_cap,
  st.settlement_rows,
  st.reversal_rows,
  st.net_settled
FROM exceptions AS e
JOIN `{dataset}.transactions` AS t USING (txn_id)
LEFT JOIN `{dataset}.fee_schedule` AS b
  ON  b.type = t.type
  AND t.amount >= b.min_amount
  AND (b.max_amount IS NULL OR t.amount <= b.max_amount)
LEFT JOIN settlement_summary AS st USING (txn_id)
