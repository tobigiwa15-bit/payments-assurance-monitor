"""
Step 9: create the views the Looker Studio dashboard reads.

  dash_exceptions  one row per exception, with money impact and triage status
  dash_summary     totals per exception type (the dashboard's headline numbers)

The dashboard does no maths of its own: every figure on it comes from these
views, which are defined in sql/dashboard/ in this repo.

Run from the project folder, with .venv active, after 06_triage_with_llm.py:
    python scripts/09_create_dashboard_views.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"

client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

for sql_file in sorted((ROOT / "sql" / "dashboard").glob("*.sql")):
    client.query(sql_file.read_text().replace("{dataset}", DATASET)).result()
    print(f"Created view from {sql_file.name}")

# Print the headline numbers, so they can be checked against the dashboard.
summary = client.query(
    f"SELECT * FROM `{DATASET}.dash_summary` ORDER BY exceptions DESC"
).to_dataframe(create_bqstorage_client=False)
for column in ["leakage_amount", "owed_to_merchant", "fraud_amount_at_risk"]:
    summary[column] = summary[column].astype(float).map("{:,.2f}".format)
print("\nDashboard totals:\n")
print(summary.to_string(index=False))
