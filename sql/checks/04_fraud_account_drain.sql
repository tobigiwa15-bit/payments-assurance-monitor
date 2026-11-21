-- Check 4: fraud rule, account drained in one transaction
--
-- Typology: account takeover. A fraudster who gains control of an account
-- moves the whole balance out in one go, by transfer to a mule account or by
-- cash-out, leaving it at zero.
--
-- Rule (v1, written before looking at any fraud labels): flag a TRANSFER or
-- CASH_OUT that moves the account's entire, non-zero balance out, leaving zero.
--
-- Why not "drain, then an immediate cash-out from the receiving account", as
-- first planned? PaySim doesn't let us follow the money: of 532,909 transfer
-- recipients, only 1,661 ever send anything, so the receiving account's next
-- move can't be traced. The rule therefore looks at single transactions.
--
-- This is the one check scored against labels we didn't create (PaySim's
-- isFraud), so its accuracy is genuinely unknown until we measure it.

CREATE OR REPLACE VIEW `{dataset}.check_fraud_account_drain` AS

SELECT
  'fraud_account_drain'        AS check_name,
  txn_id,
  oldbalanceOrg                AS expected_value,   -- balance before
  amount                       AS actual_value,     -- amount moved out
  newbalanceOrig               AS difference        -- balance left (zero when flagged)
FROM `{dataset}.transactions`
WHERE type IN ('TRANSFER', 'CASH_OUT')
  AND oldbalanceOrg > 0            -- there was money in the account
  AND amount = oldbalanceOrg       -- all of it was moved out
  AND newbalanceOrig = 0           -- leaving nothing behind
