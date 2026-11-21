"""
Step 4: measure how accurate the checks are.

Creates the views in sql/accuracy/ and prints them:
  accuracy_by_check                 precision, recall and false-positive rate per check
  accuracy_lookalikes_flagged       legitimate look-alikes the settlement checks flagged
  accuracy_fraud_misses             why the fraud rule missed what it missed
  accuracy_fraud_no_false_positives why the fraud rule raised no false positives

The scoring rules are written at the top of sql/accuracy/01_accuracy_by_check.sql.
Results are also saved to results/, so every number in the README traces to a file
this script produced.

Run from the project folder, with .venv active, after 03_create_checks.py:
    python scripts/04_measure_accuracy.py
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))


def read_view(name):
    """Read a whole view into a table. (No BigQuery Storage add-on: results are small.)"""
    return client.query(f"SELECT * FROM `{DATASET}.{name}`").to_dataframe(create_bqstorage_client=False)


# Create or refresh the accuracy views.
for sql_file in sorted((ROOT / "sql" / "accuracy").glob("*.sql")):
    client.query(sql_file.read_text().replace("{dataset}", DATASET)).result()

# --- Accuracy per check ---------------------------------------------------------
accuracy = read_view("accuracy_by_check")
accuracy.to_csv(RESULTS / "accuracy_by_check.csv", index=False)

# Print it readably: counts with commas, rates as percentages.
shown = accuracy.copy()
for col in ["examined", "targets", "flagged", "true_positives", "false_positives", "missed"]:
    shown[col] = shown[col].map("{:,}".format)
for col in ["precision", "recall"]:
    shown[col] = shown[col].map(lambda v: "-" if pd.isna(v) else f"{v:.1%}")
shown["false_positive_rate"] = shown["false_positive_rate"].map(lambda v: f"{v:.4%}")
print("Accuracy by check:\n")
print(shown.to_string(index=False))

# --- Supporting evidence --------------------------------------------------------
for view, title in [
    ("accuracy_lookalikes_flagged", "Legitimate look-alikes flagged by the settlement checks (should be 0)"),
    ("accuracy_fraud_misses", "Frauds the rule missed, by what their balances show"),
    ("accuracy_fraud_no_false_positives", "Why the fraud rule raised no false positives (TRANSFER and CASH_OUT)"),
]:
    table = read_view(view)
    table.to_csv(RESULTS / f"{view.removeprefix('accuracy_')}.csv", index=False)
    print(f"\n{title}:\n")
    print(table.to_string(index=False))

print(f"\nSaved to {RESULTS.relative_to(ROOT)}/")
