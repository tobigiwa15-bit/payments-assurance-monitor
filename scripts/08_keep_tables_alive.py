"""
Step 8: stop the BigQuery sandbox from deleting our tables.

The sandbox deletes every table and view about 60 days after it was CREATED,
and it won't accept an expiry date beyond that. Pushing the expiry forward
therefore stops working once an object is about two months old. (The first
version of this script did that, and failed on 2026-11-23.)

What works instead: rebuild the object as a fresh copy of itself. A rebuilt
object counts as newly created, so the 60-day clock starts again.

    table:  CREATE OR REPLACE TABLE x AS SELECT * FROM x
    view:   CREATE OR REPLACE VIEW  x AS <the view's own saved query>

Each rebuild is one statement: it either completes in full or leaves the
original untouched. Only objects due to expire within --within-days (default
7) are rebuilt, so on most days this script changes nothing. A full rebuild
scans about 1.2 GB, well inside the free 1 TB of queries a month.

Run daily by GitHub Actions. To test it by hand, forcing a rebuild of everything:
    python scripts/08_keep_tables_alive.py --within-days 60
"""

import argparse
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"

parser = argparse.ArgumentParser()
parser.add_argument("--within-days", type=int, default=7,
                    help="rebuild anything due to expire within this many days")
args = parser.parse_args()

cutoff = datetime.now(timezone.utc) + timedelta(days=args.within_days)
client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

for item in client.list_tables(DATASET):
    before = client.get_table(item)
    name = f"`{DATASET}.{before.table_id}`"

    # Not expiring soon (or never): leave it alone.
    if before.expires is None or before.expires > cutoff:
        expiry = f"{before.expires:%Y-%m-%d}" if before.expires else "never"
        print(f"{before.table_id:<36} ok, expires {expiry}")
        continue

    if before.table_type == "VIEW":
        client.query(f"CREATE OR REPLACE VIEW {name} AS {before.view_query}").result()
    else:
        client.query(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {name}").result()

    after = client.get_table(item)

    # Control: a rebuilt table must have exactly the rows it had before.
    if before.table_type != "VIEW" and after.num_rows != before.num_rows:
        raise SystemExit(f"{before.table_id}: {before.num_rows:,} rows before the rebuild, "
                         f"{after.num_rows:,} after. Investigate before rerunning.")

    new_expiry = f"{after.expires:%Y-%m-%d}" if after.expires else "never"
    print(f"{before.table_id:<36} rebuilt ({after.num_rows or 0:,} rows), "
          f"now expires {new_expiry}")
