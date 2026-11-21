-- Why the fraud rule raised no false positives.
--
-- Looks at legitimate TRANSFER and CASH_OUT transactions: how close do they
-- come to the rule? And compares balance arithmetic (old - amount = new) for
-- legitimate and fraud rows. Written after measuring, to explain the result.

CREATE OR REPLACE VIEW `{dataset}.accuracy_fraud_no_false_positives` AS

SELECT
  COUNTIF(isFraud = 0)                                              AS legit_rows,
  COUNTIF(isFraud = 0 AND oldbalanceOrg > 0 AND newbalanceOrig = 0) AS legit_had_money_left_at_zero,
  COUNTIF(isFraud = 0 AND oldbalanceOrg > 0 AND newbalanceOrig = 0
          AND amount > oldbalanceOrg)                               AS legit_asked_for_more_than_balance,
  COUNTIF(isFraud = 0 AND oldbalanceOrg > 0
          AND amount = oldbalanceOrg)                               AS legit_moved_exactly_full_balance,
  ROUND(SAFE_DIVIDE(COUNTIF(isFraud = 0 AND oldbalanceOrg - amount = newbalanceOrig),
                    COUNTIF(isFraud = 0)), 3)                       AS legit_share_balances_add_up,
  ROUND(SAFE_DIVIDE(COUNTIF(isFraud = 1 AND oldbalanceOrg - amount = newbalanceOrig),
                    COUNTIF(isFraud = 1)), 3)                       AS fraud_share_balances_add_up
FROM `{dataset}.transactions`
WHERE type IN ('TRANSFER', 'CASH_OUT')
