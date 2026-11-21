-- Accuracy of every check, scored against the answer key (planted errors) and
-- PaySim's fraud labels.
--
-- Scoring rules, fixed on 2026-11-21 before any results were seen:
--   true positive        a flagged transaction that genuinely has a problem.
--                        Planted-error checks: any planted error counts, so a
--                        double payment flagged by the reconciliation is a real
--                        catch. Fraud rule: isFraud = 1.
--   precision            true positives / everything flagged
--   recall               the check's own targets caught / all its targets
--   false-positive rate  clean items flagged / clean items examined
--   population           the records each check examines
--
-- "all_planted_error_checks" combines checks 1-3. The fraud rule is reported on
-- its own, next to PaySim's built-in rule (isFlaggedFraud) as a baseline.

CREATE OR REPLACE VIEW `{dataset}.accuracy_by_check` AS

WITH
-- Every flag raised by the three planted-error checks.
flags AS (
  SELECT check_name, txn_id FROM `{dataset}.check_fee_recompute`
  UNION ALL
  SELECT check_name, txn_id FROM `{dataset}.check_settlement_recon`
  UNION ALL
  SELECT check_name, txn_id FROM `{dataset}.check_duplicate_settlement`
),

-- The records each check examines.
populations AS (
  SELECT 'fee_recompute' AS check_name, txn_id
  FROM `{dataset}.transactions`
  UNION ALL
  SELECT 'settlement_recon', txn_id
  FROM `{dataset}.transactions`
  WHERE type = 'PAYMENT' AND day + 1 <= 30
  UNION ALL
  SELECT DISTINCT 'duplicate_settlement', txn_id
  FROM `{dataset}.settlements`
),

-- Per check: records examined, its own targets, and records with any problem.
population_counts AS (
  SELECT
    p.check_name,
    COUNT(*)                             AS examined,
    COUNTIF(a.check_name = p.check_name) AS targets,
    COUNTIF(a.txn_id IS NOT NULL)        AS with_problem
  FROM populations AS p
  LEFT JOIN `{dataset}.eval_answer_key` AS a USING (txn_id)
  GROUP BY p.check_name
),

-- Per check: what it flagged, how many were real, how many were its targets.
flag_counts AS (
  SELECT
    f.check_name,
    COUNT(*)                             AS flagged,
    COUNTIF(a.txn_id IS NOT NULL)        AS true_positives,
    COUNTIF(a.check_name = f.check_name) AS targets_caught
  FROM flags AS f
  LEFT JOIN `{dataset}.eval_answer_key` AS a USING (txn_id)
  GROUP BY f.check_name
),

planted_checks AS (
  SELECT
    p.check_name, p.examined, p.targets, p.with_problem,
    IFNULL(f.flagged, 0)        AS flagged,
    IFNULL(f.true_positives, 0) AS true_positives,
    IFNULL(f.targets_caught, 0) AS targets_caught
  FROM population_counts AS p
  LEFT JOIN flag_counts AS f USING (check_name)
),

-- Checks 1-3 combined: each transaction counted once, however many checks flag it.
planted_overall AS (
  SELECT
    'all_planted_error_checks'                                AS check_name,
    (SELECT COUNT(*) FROM `{dataset}.transactions`)           AS examined,
    (SELECT COUNT(*) FROM `{dataset}.eval_answer_key`)        AS targets,
    (SELECT COUNT(*) FROM `{dataset}.eval_answer_key`)        AS with_problem,
    COUNT(*)                                                  AS flagged,
    COUNTIF(a.txn_id IS NOT NULL)                             AS true_positives,
    COUNTIF(a.txn_id IS NOT NULL)                             AS targets_caught
  FROM (SELECT DISTINCT txn_id FROM flags) AS f
  LEFT JOIN `{dataset}.eval_answer_key` AS a USING (txn_id)
),

-- The fraud rule, and PaySim's own rule as the baseline to beat.
fraud AS (
  SELECT
    'fraud_account_drain'                             AS check_name,
    COUNT(*)                                          AS examined,
    COUNTIF(t.isFraud = 1)                            AS targets,
    COUNTIF(t.isFraud = 1)                            AS with_problem,
    COUNTIF(f.txn_id IS NOT NULL)                     AS flagged,
    COUNTIF(f.txn_id IS NOT NULL AND t.isFraud = 1)   AS true_positives,
    COUNTIF(f.txn_id IS NOT NULL AND t.isFraud = 1)   AS targets_caught
  FROM `{dataset}.transactions` AS t
  LEFT JOIN `{dataset}.check_fraud_account_drain` AS f USING (txn_id)

  UNION ALL

  SELECT
    'baseline_paysim_isFlaggedFraud',
    COUNT(*),
    COUNTIF(isFraud = 1),
    COUNTIF(isFraud = 1),
    COUNTIF(isFlaggedFraud = 1),
    COUNTIF(isFlaggedFraud = 1 AND isFraud = 1),
    COUNTIF(isFlaggedFraud = 1 AND isFraud = 1)
  FROM `{dataset}.transactions`
),

all_rows AS (
  SELECT * FROM planted_checks
  UNION ALL SELECT * FROM planted_overall
  UNION ALL SELECT * FROM fraud
)

SELECT
  check_name,
  examined,
  targets,
  flagged,
  true_positives,
  flagged - true_positives                                      AS false_positives,
  targets - targets_caught                                      AS missed,
  ROUND(SAFE_DIVIDE(true_positives, flagged), 4)                AS precision,
  ROUND(SAFE_DIVIDE(targets_caught, targets), 4)                AS recall,
  ROUND(SAFE_DIVIDE(flagged - true_positives, examined - with_problem), 6) AS false_positive_rate
FROM all_rows
