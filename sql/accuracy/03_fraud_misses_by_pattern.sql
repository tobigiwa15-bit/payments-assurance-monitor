-- Why the fraud rule missed what it missed.
--
-- Groups the frauds that rule v1 did not flag by what their balances show.
-- Written after measuring, to explain the misses, not to change the rule.

CREATE OR REPLACE VIEW `{dataset}.accuracy_fraud_misses` AS

SELECT
  t.type,
  CASE
    WHEN t.oldbalanceOrg = 0 AND t.amount = 0 THEN 'zero amount, zero balance'
    WHEN t.oldbalanceOrg = 0                  THEN 'balance recorded as zero before'
    WHEN t.amount < t.oldbalanceOrg           THEN 'moved only part of the balance'
    WHEN t.amount > t.oldbalanceOrg           THEN 'moved more than the balance'
    ELSE 'moved the full balance, but balance after not zero'
  END                              AS pattern,
  COUNT(*)                         AS missed_frauds,
  COUNTIF(t.amount = 10000000)     AS at_10m_transaction_cap
FROM `{dataset}.transactions` AS t
LEFT JOIN `{dataset}.check_fraud_account_drain` AS f USING (txn_id)
WHERE t.isFraud = 1
  AND f.txn_id IS NULL             -- fraud the rule did not flag
GROUP BY t.type, pattern
