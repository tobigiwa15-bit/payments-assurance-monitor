"""
Step 5: build the triage sample and the hand-labelling sheet.

Creates the view triage_sample (100 exceptions, 25 per check, with evidence)
and exports it to labels/to_label.csv with two empty columns, my_label and
my_note, for blind hand-labelling. See labels/LABELLING_GUIDE.md.

Run from the project folder, with .venv active, after 03_create_checks.py:
    python scripts/05_build_triage_sample.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"
LABELS = ROOT / "labels"

client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

# Create or refresh the sample view.
sql = (ROOT / "sql" / "triage" / "01_triage_sample.sql").read_text()
client.query(sql.replace("{dataset}", DATASET)).result()

sample = client.query(
    f"SELECT * FROM `{DATASET}.triage_sample` ORDER BY sample_id"
).to_dataframe(create_bqstorage_client=False)

# Show money as plain 2-decimal numbers in Excel (BigQuery sends 9 decimals).
money = ["expected_value", "actual_value", "difference", "amount", "oldbalanceOrg",
         "newbalanceOrig", "oldbalanceDest", "newbalanceDest", "fee_charged",
         "fixed_fee", "fee_cap", "net_settled"]
for column in money:
    sample[column] = sample[column].astype(float).round(2)

# Empty columns for the labeller to fill in.
sample["my_label"] = ""
sample["my_note"] = ""

LABELS.mkdir(exist_ok=True)
sample.to_csv(LABELS / "to_label.csv", index=False)

print(f"Sample: {len(sample)} exceptions")
print(sample["check_name"].value_counts().to_string())
print(f"\nWritten to labels/to_label.csv. Label it, then save as labels/hand_labels.csv.")
if (LABELS / "hand_labels.csv").exists():
    print("Note: labels/hand_labels.csv already exists and was not touched.")
