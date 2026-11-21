"""
Step 8: keep the BigQuery tables from expiring.

The BigQuery sandbox deletes a table 60 days after it's created. This script
pushes the expiry date of every table and view in the dataset forward to 59
days from now. The daily GitHub Actions run calls it, so as long as the
schedule keeps running, nothing expires.

Run from the project folder, with .venv active:
    python scripts/08_keep_tables_alive.py
"""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"

# The sandbox allows at most 60 days; 59 leaves a day's margin.
NEW_EXPIRY = datetime.now(timezone.utc) + timedelta(days=59)

client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

for item in client.list_tables(DATASET):
    table = client.get_table(item)
    table.expires = NEW_EXPIRY
    client.update_table(table, ["expires"])  # change only the expiry, nothing else
    print(f"{table.table_id:<36} now expires {NEW_EXPIRY:%Y-%m-%d}")
