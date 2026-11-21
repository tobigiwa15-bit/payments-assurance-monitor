"""
Step 1: generate the fee and settlement data, with known errors planted.

PaySim gives us transactions but no fees or settlements. This script adds them,
plants a known set of errors, and writes an answer key. Later we score the
checks against that key: how many planted errors they catch (recall), and how
many of their flags are real errors (precision).

Built in four parts:
  Part 1: transaction IDs and the fee schedule
  Part 2: fees charged, with planted fee errors
  Part 3: settlement ledger, with planted errors and legitimate look-alikes
  Part 4: save everything to data/

Run from the project folder, with .venv active:
    python scripts/01_generate_data.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

# The data folder sits next to the scripts folder, so this works from any directory.
DATA = Path(__file__).resolve().parent.parent / "data"

# Fixed seed: every random choice below is repeatable, so anyone who reruns
# this script gets exactly the same planted errors and the same answer key.
rng = np.random.default_rng(42)

# Show money with thousands separators and 2 decimals in printed summaries.
pd.options.display.float_format = "{:,.2f}".format


# === Part 1a: load PaySim and give every transaction an ID ===================
print("Loading PaySim (takes a few seconds)...")
txns = pd.read_csv(DATA / "paysim.csv")

# PaySim has no transaction ID, so number the rows in file order: 1, 2, 3, ...
# Every other table links back to this ID.
txns.insert(0, "txn_id", np.arange(1, len(txns) + 1))

# PaySim's 'step' is the hour of the simulation (1 to 743). Convert it to a day
# number (1 to 31), because merchants are settled the day after a payment.
txns["day"] = (txns["step"] - 1) // 24 + 1


# === Part 1b: the fee schedule ===============================================
# One row per fee band. Every fee follows the same formula:
#     fee = amount x rate + fixed_fee, rounded half up to the cent, capped at fee_cap
# Rates are in basis points, as payment fees usually are: 150 bps = 1.5%.
# Bands include both ends (amounts have 2 decimals, so 5,000.00 then 5,000.01).
# A blank max_amount means "no upper limit"; a blank fee_cap means "no cap".
# The rates are invented for this project, for illustration only.
fee_schedule = pd.DataFrame(
    [
        # type,     min_amount, max_amount, fee_rate_bps, fixed_fee, fee_cap
        ("PAYMENT",       0.00,       None,          150,         0,    2000),
        ("TRANSFER",      0.00,    5000.00,            0,        10,    None),
        ("TRANSFER",   5000.01,   50000.00,            0,        25,    None),
        ("TRANSFER",  50000.01,       None,            0,        50,    None),
        ("CASH_OUT",      0.00,       None,           50,         0,    2500),
        ("DEBIT",         0.00,       None,            0,        50,    None),
        ("CASH_IN",       0.00,       None,            0,         0,    None),
    ],
    columns=["type", "min_amount", "max_amount", "fee_rate_bps", "fixed_fee", "fee_cap"],
)


# === Part 1c: work out the correct fee for every transaction =================
# Pair each transaction with the bands for its type, then keep the one band
# its amount falls in.
matched = txns[["txn_id", "type", "amount"]].merge(fee_schedule, on="type")
in_band = (matched["amount"] >= matched["min_amount"]) & (
    (matched["amount"] <= matched["max_amount"]) | matched["max_amount"].isna()
)
matched = matched[in_band].copy()

# Control: every transaction must land in exactly one band. A gap or overlap in
# the schedule would silently give some transactions no fee, or two fees.
assert len(matched) == len(txns), "Some transactions matched no fee band, or more than one"
assert matched["txn_id"].is_unique, "A transaction matched more than one fee band"

# Do the arithmetic in whole cents, as payment systems do. Computers store a
# decimal like 0.905 inexactly (as 0.90499999...), so rounding it can go the
# wrong way; whole numbers are stored exactly.
amount_cents = (matched["amount"] * 100).round().astype("int64")
fixed_cents = (matched["fixed_fee"] * 100).round().astype("int64")
cap_cents = (matched["fee_cap"] * 100).fillna(np.inf)  # "no cap" = infinitely high cap

# Percentage part: amount x bps / 10,000. Adding 5,000 (half of 10,000) before the
# whole-number division rounds half a cent up, e.g. 90.5 cents becomes 91 cents.
rate_cents = (amount_cents * matched["fee_rate_bps"] + 5000) // 10000

fee_cents = np.minimum(rate_cents + fixed_cents, cap_cents)
matched["expected_fee"] = fee_cents / 100  # back to currency units

# Attach the correct fee to each transaction (a lookup, like VLOOKUP on txn_id).
txns = txns.merge(matched[["txn_id", "expected_fee"]], on="txn_id", how="left")


# === Part 1 summary: check before moving on ==================================
print(f"\nTransactions loaded: {len(txns):,}")
print(f"Transaction IDs unique: {txns['txn_id'].is_unique}")
print("\nFee schedule (NaN = no limit / no cap):")
print(fee_schedule.to_string(index=False))
print("\nFirst 5 transactions (recompute one by hand as a spot check):")
print(txns[["txn_id", "type", "amount", "expected_fee"]].head(5).to_string(index=False))
print("\nCorrect fees by transaction type:")
print(txns.groupby("type")["expected_fee"].agg(["count", "sum", "min", "max"]))


# === Part 2a: fees charged, starting from a clean world ======================
# Begin with every transaction charged exactly the correct fee. Then plant the
# errors on top, so we know precisely which ones are wrong.
txns["fee_charged"] = txns["expected_fee"]

# Pick 2,000 transactions at random for fee errors. Only those with a correct
# fee of at least 1.00 qualify, so every planted error is a real difference:
# 20% off a 0.02 fee would round straight back to 0.02.
eligible = txns.index[txns["expected_fee"] >= 1.00].to_numpy()
picked = rng.choice(eligible, size=2000, replace=False)
not_charged = picked[:1000]
stale_rate = picked[1000:]


# === Part 2b: plant the two kinds of fee error ===============================
# Error 1: fee not charged at all. Pure revenue leakage.
txns.loc[not_charged, "fee_charged"] = 0.0

# Error 2: fee taken from an old price list where every fee was 20% lower.
# Worked in whole cents and rounded half up, as in Part 1.
correct_cents = (txns.loc[stale_rate, "expected_fee"] * 100).round().astype("int64")
stale_cents = (correct_cents * 8 + 5) // 10
txns.loc[stale_rate, "fee_charged"] = stale_cents / 100


# === Part 2c: record every planted fee error in the answer key ===============
# The answer key gets one table per error type; Part 4 combines and saves them.
answer_key_parts = []
for rows, error_type in [(not_charged, "FEE_NOT_CHARGED"), (stale_rate, "FEE_STALE_RATE")]:
    answer_key_parts.append(
        pd.DataFrame(
            {
                "txn_id": txns.loc[rows, "txn_id"].to_numpy(),
                "check_name": "fee_recompute",  # the check that should catch it
                "error_type": error_type,
                "expected_value": txns.loc[rows, "expected_fee"].to_numpy(),
                "actual_value": txns.loc[rows, "fee_charged"].to_numpy(),
            }
        )
    )
fee_errors = pd.concat(answer_key_parts)


# === Part 2 summary: check before moving on ==================================
# Control: exactly the 2,000 planted transactions differ from the correct fee.
wrong = txns["fee_charged"] != txns["expected_fee"]
print(f"\nTransactions charged the wrong fee: {wrong.sum():,} (should be 2,000)")
assert wrong.sum() == 2000, "Fee errors don't match what was planted"

fee_errors["shortfall"] = fee_errors["expected_value"] - fee_errors["actual_value"]
print("\nPlanted fee errors (shortfall = revenue lost):")
print(fee_errors.groupby("error_type")["shortfall"].agg(["count", "sum", "min", "median", "max"]))
print("\nWhich transaction types they landed on:")
print(txns.loc[picked, "type"].value_counts().to_string())
print("\nSample from the answer key:")
print(fee_errors.head(3).to_string(index=False))


# === Part 3a: the clean settlement ledger ====================================
# Merchants are paid for each PAYMENT the next day (T+1). The processor keeps
# its fee, so the merchant receives: amount - fee_charged.
# We reconcile as at the end of day 30, so the ledger only holds settlements
# made by then. Day-30 payments are not due until day 31: pending, not missing.
REPORT_DAY = 30

payments = txns[txns["type"] == "PAYMENT"].copy()
amount_cents = (payments["amount"] * 100).round().astype("int64")
fee_cents = (payments["fee_charged"] * 100).round().astype("int64")
payments["net_due"] = (amount_cents - fee_cents) / 100  # whole cents again
payments["settlement_day"] = payments["day"] + 1

ledger = pd.DataFrame(
    {
        "txn_id": payments["txn_id"],
        "merchant_id": payments["nameDest"],
        "settlement_day": payments["settlement_day"],
        "settled_amount": payments["net_due"],
        "record_type": "SETTLEMENT",
    }
)
ledger = ledger[ledger["settlement_day"] <= REPORT_DAY]
ledger = ledger.set_index("txn_id", drop=False)  # look rows up by txn_id below
pending = payments[payments["settlement_day"] > REPORT_DAY]


# === Part 3b: pick transactions for settlement errors and look-alikes =======
# Pool: payments that were due to settle by the report date, of at least 100
# (so a 0.1% error is still at least 0.10), and not already carrying a fee error.
pool = payments[
    (payments["settlement_day"] <= REPORT_DAY)
    & (payments["amount"] >= 100)
    & ~payments["txn_id"].isin(fee_errors["txn_id"])
]["txn_id"].to_numpy()
picked = rng.choice(pool, size=3500, replace=False)
missing = picked[:1000]
duplicated = picked[1000:2000]
wrong_amount = picked[2000:3000]
reversed_resent = picked[3000:3500]  # look-alikes, not errors

# Keep the correct amounts before changing anything, for the answer key.
net_due = payments.set_index("txn_id")["net_due"]


# === Part 3c: plant the three settlement errors ==============================
# Error 1: never settled. The settlement row simply isn't there.
ledger = ledger.drop(missing)

# Error 2: settled at the wrong amount, over or under by 0.1% to 5%.
size = rng.uniform(0.001, 0.05, size=1000)
direction = rng.choice([-1, 1], size=1000)
correct_cents = (net_due[wrong_amount] * 100).round().to_numpy()
wrong_cents = np.round(correct_cents * (1 + size * direction))
ledger.loc[wrong_amount, "settled_amount"] = wrong_cents / 100

# Error 3: settled twice. An exact copy of the settlement row, as if the
# settlement batch was run a second time.
duplicate_rows = ledger.loc[duplicated].copy()


# === Part 3d: the legitimate look-alike ======================================
# Reversed and resent: the first payment bounced (say, wrong bank details), was
# reversed, and was sent again. Three rows that net to exactly one payment.
# A naive duplicate check sees two settlements and flags it. A good one nets
# off the reversal and doesn't.
reversal_rows = ledger.loc[reversed_resent].copy()
reversal_rows["settled_amount"] = -reversal_rows["settled_amount"]
reversal_rows["record_type"] = "REVERSAL"
resent_rows = ledger.loc[reversed_resent].copy()

# Combine, sort by day and transaction (originals stay first within a
# transaction), and number every ledger row.
ledger = pd.concat([ledger, duplicate_rows, reversal_rows, resent_rows])
ledger = ledger.reset_index(drop=True)
ledger = ledger.sort_values(["settlement_day", "txn_id"], kind="stable").reset_index(drop=True)
ledger.insert(0, "settlement_id", np.arange(1, len(ledger) + 1))


# === Part 3e: record the settlement errors and the look-alikes ==============
# Answer key: expected = what the merchant should have received in total;
# actual = what the ledger shows in total.
for rows, check_name, error_type, actual in [
    (missing, "settlement_recon", "SETTLEMENT_MISSING", 0.0),
    (wrong_amount, "settlement_recon", "SETTLEMENT_WRONG_AMOUNT", wrong_cents / 100),
    (duplicated, "duplicate_settlement", "SETTLEMENT_DUPLICATE", net_due[duplicated].to_numpy() * 2),
]:
    answer_key_parts.append(
        pd.DataFrame(
            {
                "txn_id": rows,
                "check_name": check_name,
                "error_type": error_type,
                "expected_value": net_due[rows].to_numpy(),
                "actual_value": actual,
            }
        )
    )

# Look-alikes are NOT errors, so they stay out of the answer key. We list them
# separately, so that when a check flags one we can explain the false positive.
lookalikes = pd.concat(
    [
        pd.DataFrame({"txn_id": reversed_resent, "lookalike_type": "REVERSED_AND_RESENT"}),
        pd.DataFrame({"txn_id": pending["txn_id"].to_numpy(), "lookalike_type": "PENDING_SETTLEMENT"}),
    ]
)


# === Part 3 summary: check before moving on ==================================
# Control: reconcile every payment due by the report date against the ledger.
# Exactly the 3,000 planted errors should fail. The 500 reversed-and-resent
# payments net to the right amount, so they should pass.
due = payments[payments["settlement_day"] <= REPORT_DAY].set_index("txn_id")["net_due"]
settled = ledger.groupby("txn_id")["settled_amount"].sum().reindex(due.index, fill_value=0)
mismatches = ((settled - due).abs() > 0.005).sum()
print(f"\nPayments due by day {REPORT_DAY}: {len(due):,}")
print(f"Payments pending (day 30, due day 31): {len(pending):,}")
print(f"Payments that don't reconcile: {mismatches:,} (should be 3,000)")
assert mismatches == 3000, "Settlement errors don't match what was planted"

print("\nLedger rows by record type:")
print(ledger["record_type"].value_counts().to_string())

# The trap for the duplicate check: counting SETTLEMENT rows alone finds 1,500
# transactions, but only 1,000 are real duplicates.
settlement_rows = ledger[ledger["record_type"] == "SETTLEMENT"]
repeat_count = (settlement_rows["txn_id"].value_counts() > 1).sum()
print(f"\nTransactions with 2+ SETTLEMENT rows: {repeat_count:,} (1,000 duplicates + 500 look-alikes)")

wrong_diff = np.abs(wrong_cents - correct_cents) / 100
print(f"Wrong-amount errors: smallest {wrong_diff.min():,.2f}, median {np.median(wrong_diff):,.2f}, "
      f"largest {wrong_diff.max():,.2f}")
print("\nExample of a reversed-and-resent payment (3 rows, nets to one payment):")
example = ledger[ledger["txn_id"] == reversed_resent[0]]
print(example.to_string(index=False))


# === Part 4a: assemble the answer key ========================================
answer_key = pd.concat(answer_key_parts).sort_values("txn_id").reset_index(drop=True)
answer_key["expected_value"] = answer_key["expected_value"].round(2)
answer_key["actual_value"] = answer_key["actual_value"].round(2)

# Control: 5,000 planted errors, each on a different transaction.
assert len(answer_key) == 5000, "Answer key should hold 5,000 planted errors"
assert answer_key["txn_id"].is_unique, "A transaction carries more than one planted error"


# === Part 4b: save everything to data/ =======================================
# Drop expected_fee before saving the transactions. It's our private working
# column; a real system only records the fee it charged. The fee check must
# recompute the correct fee from the schedule, not read it from the data.
txns_out = txns.drop(columns=["expected_fee"])

# Big tables as Parquet: compact, fast to load, and it remembers column types.
# Small tables as CSV, so they open in Excel.
txns_out.to_parquet(DATA / "transactions.parquet", index=False)
ledger.to_parquet(DATA / "settlements.parquet", index=False)
fee_schedule.to_csv(DATA / "fee_schedule.csv", index=False)
answer_key.to_csv(DATA / "answer_key.csv", index=False)
lookalikes.to_csv(DATA / "lookalikes.csv", index=False)


# === Part 4 summary: what was written ========================================
print("\nFiles written to data/:")
for name, table in [
    ("transactions.parquet", txns_out),
    ("settlements.parquet", ledger),
    ("fee_schedule.csv", fee_schedule),
    ("answer_key.csv", answer_key),
    ("lookalikes.csv", lookalikes),
]:
    size_mb = (DATA / name).stat().st_size / 1_000_000
    print(f"  {name:<22} {len(table):>10,} rows  {size_mb:>7.1f} MB")

print("\nAnswer key by check and error type:")
print(answer_key.groupby(["check_name", "error_type"]).size().to_string())
print("\nDone.")
