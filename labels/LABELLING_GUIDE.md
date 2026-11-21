# Hand-labelling guide

These labels are the benchmark for the AI triage. The AI gets the same rubric
and the same evidence, so its agreement with these labels can be measured.

## Rules

1. **Label before seeing any AI output.** The AI hasn't run on this sample yet,
   and its results aren't opened until every row is labelled.
2. **Judge only from the evidence in the row.** Don't look up the transaction's
   fraud label or the answer key.
3. **One category per row**, typed exactly as written below.
4. **A short note** (one line): what you see and what you would check next.

## Categories

| Category | Use when |
|---|---|
| `fee_error` | The fee charged doesn't match the tariff. |
| `data_error` | A processing or recording mistake: a settlement missing, duplicated or at the wrong amount, or records that don't add up. No sign of intent. |
| `likely_fraud` | The pattern fits a known fraud typology, such as an account emptied in one move. |
| `needs_investigation` | The evidence isn't enough to choose. |

## Columns

| Column | Meaning |
|---|---|
| sample_id | Row number in this sample (1-100) |
| check_name | The check that raised the exception |
| txn_id | Transaction ID |
| expected_value, actual_value, difference | What the check expected, what it found, and actual minus expected. For `fraud_account_drain`: balance before, amount moved out, balance left. |
| type, day, amount | Transaction type, day of the month (1-31), amount |
| oldbalanceOrg, newbalanceOrig | Sender's balance before and after |
| nameDest, oldbalanceDest, newbalanceDest | Recipient (M = merchant, C = customer) and their balance before and after |
| fee_charged | Fee actually charged |
| fee_rate_bps, fixed_fee, fee_cap | The tariff band for this transaction (150 bps = 1.5%; blank cap = no cap) |
| settlement_rows, reversal_rows, net_settled | Merchant payments only: settlement and reversal rows in the ledger, and the net amount paid out |

## Steps

1. Open `labels/to_label.csv` in Excel.
2. Fill in `my_label` and `my_note` for every row. Don't change other columns.
3. Save as **CSV UTF-8** with the name `labels/hand_labels.csv`.
