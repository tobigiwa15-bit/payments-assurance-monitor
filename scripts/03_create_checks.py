"""
Step 3: create the assurance checks as views in BigQuery.

Each file in sql/checks/ defines one check as a view. A view is a saved query:
it reruns over the current data every time it's read, so the checks never go
stale. This script creates or refreshes every view, then counts its exceptions.

File naming: sql/checks/01_fee_recompute.sql creates the view check_fee_recompute.

Run from the project folder, with .venv active, after 02_load_to_bigquery.py:
    python scripts/03_create_checks.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
CHECKS = Path(__file__).resolve().parent.parent / "sql" / "checks"
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"

client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

# Run the files in number order, so the checks are always created the same way.
for sql_file in sorted(CHECKS.glob("*.sql")):
    # The SQL files say {dataset} instead of a hard-coded project, so anyone can
    # run them against their own project. Fill it in here.
    sql = sql_file.read_text().replace("{dataset}", DATASET)
    client.query(sql).result()

    # Count the exceptions the check finds on the current data.
    view = "check_" + sql_file.stem.split("_", 1)[1]  # 01_fee_recompute -> check_fee_recompute
    count_sql = f"SELECT COUNT(*) AS exceptions FROM `{DATASET}.{view}`"
    for row in client.query(count_sql).result():
        print(f"{view:<30} {row.exceptions:>8,} exceptions")
