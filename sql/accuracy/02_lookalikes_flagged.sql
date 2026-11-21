-- Look-alikes flagged by the settlement checks.
--
-- The look-alikes are legitimate: payments reversed and resent (they net to one
-- payment) and day-30 payments not yet due (cut-off). A well-built settlement
-- check flags none of them. Any count above zero here is a false positive that
-- the check's logic should have avoided.
--
-- Only checks 2 and 3 are tested here: they are the checks these traps target.
-- (A pending payment can still carry a genuine fee error, which check 1 rightly flags.)

CREATE OR REPLACE VIEW `{dataset}.accuracy_lookalikes_flagged` AS

WITH settlement_flags AS (
  SELECT txn_id FROM `{dataset}.check_settlement_recon`
  UNION DISTINCT
  SELECT txn_id FROM `{dataset}.check_duplicate_settlement`
)

SELECT
  l.lookalike_type,
  COUNT(*)                       AS lookalikes,
  COUNTIF(f.txn_id IS NOT NULL)  AS flagged_by_settlement_checks
FROM `{dataset}.eval_lookalikes` AS l
LEFT JOIN settlement_flags AS f USING (txn_id)
GROUP BY l.lookalike_type
