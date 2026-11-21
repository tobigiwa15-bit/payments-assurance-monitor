-- The triage sample: 100 exceptions, 25 from each check, with their evidence.
--
-- Sampling: within each check, exceptions are sorted by a fingerprint (hash) of
-- the transaction ID and the first 25 are taken. That's as good as random, but
-- repeatable: anyone who reruns this gets the same 100.
--
-- The evidence is what an analyst would see in an exception queue. It leaves
-- out isFraud, isFlaggedFraud and the answer key on purpose: those are the
-- answers, and neither the human labeller nor the AI may see them.

CREATE OR REPLACE VIEW `{dataset}.triage_sample` AS

WITH exceptions AS (
  SELECT * FROM `{dataset}.check_fee_recompute`
  UNION ALL SELECT * FROM `{dataset}.check_settlement_recon`
  UNION ALL SELECT * FROM `{dataset}.check_duplicate_settlement`
  UNION ALL SELECT * FROM `{dataset}.check_fraud_account_drain`
),

-- Number the exceptions within each check in fingerprint order; keep 25 each.
sampled AS (
  SELECT *
  FROM exceptions
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY check_name
    ORDER BY FARM_FINGERPRINT(CAST(txn_id AS STRING))
  ) <= 25
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
  -- Shuffle the 100 across checks (again by fingerprint), so the labeller doesn't
  -- see 25 of the same kind in a row.
  ROW_NUMBER() OVER (
    ORDER BY FARM_FINGERPRINT(CONCAT(s.check_name, CAST(s.txn_id AS STRING)))
  )                    AS sample_id,
  s.check_name,
  s.txn_id,
  s.expected_value,
  s.actual_value,
  s.difference,
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
FROM sampled AS s
JOIN `{dataset}.transactions` AS t USING (txn_id)
LEFT JOIN `{dataset}.fee_schedule` AS b
  ON  b.type = t.type
  AND t.amount >= b.min_amount
  AND (b.max_amount IS NULL OR t.amount <= b.max_amount)
LEFT JOIN settlement_summary AS st USING (txn_id)
