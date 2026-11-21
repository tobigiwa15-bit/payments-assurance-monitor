"""
Step 2: load the generated data into BigQuery.

Loads five tables into the BigQuery dataset 'payments_assurance':
  transactions      PaySim plus txn_id, day and fee_charged
  settlements       the merchant settlement ledger
  fee_schedule      the fee bands
  eval_answer_key   the planted errors (for scoring the checks; not operational data)
  eval_lookalikes   legitimate look-alikes (for explaining false positives)

Every run replaces the tables completely, so running it twice never doubles the data.
Money is stored as NUMERIC (exact decimals), never as floating-point numbers.

Run from the project folder, with .venv active, after 01_generate_data.py:
    python scripts/02_load_to_bigquery.py
"""

import io
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
DATA = Path(__file__).resolve().parent.parent / "data"
PROJECT = os.getenv("GCP_PROJECT_ID")
DATASET = f"{PROJECT}.payments_assurance"

# Which file goes into which table, and which of its columns hold money.
TABLES = [
    ("transactions.parquet", "transactions",
     ["amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest", "fee_charged"]),
    ("settlements.parquet", "settlements", ["settled_amount"]),
    ("fee_schedule.csv", "fee_schedule", ["min_amount", "max_amount", "fixed_fee", "fee_cap"]),
    ("answer_key.csv", "eval_answer_key", ["expected_value", "actual_value"]),
    ("lookalikes.csv", "eval_lookalikes", []),
]

client = bigquery.Client(project=PROJECT)

# A dataset is BigQuery's version of a database schema: a container for tables.
# US multi-region: free in the sandbox, and where Google's public data lives.
# With real customer data, data residency rules would decide the location.
dataset = bigquery.Dataset(DATASET)
dataset.location = "US"
client.create_dataset(dataset, exists_ok=True)


for file_name, table_name, money_columns in TABLES:
    # --- Read the file -------------------------------------------------------
    path = DATA / file_name
    if file_name.endswith(".parquet"):
        table = pq.read_table(path)
    else:
        table = pa.Table.from_pandas(pd.read_csv(path), preserve_index=False)

    # --- Convert money to exact decimals --------------------------------------
    # BigQuery's NUMERIC is an exact decimal with 9 decimal places. Converting
    # a float can leave a tiny leftover (92,445,516.64 becomes ...640000001), so
    # we round back to whole cents straight after converting.
    for column in money_columns:
        exact = pc.round(table[column].cast(pa.decimal128(38, 9)), 2)
        table = table.set_column(table.schema.get_field_index(column), column, exact)

    if table_name == "transactions":
        source_rows = table.num_rows
        source_amount = pc.sum(table["amount"]).as_py()  # for the load control below

    # --- Load it ---------------------------------------------------------------
    # The sandbox doesn't allow INSERT statements, so data goes in through a
    # load job: we hand BigQuery a whole file (built here in memory as Parquet).
    # WRITE_TRUNCATE replaces whatever was in the table before.
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    buffer.seek(0)

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    table_id = f"{DATASET}.{table_name}"
    print(f"Loading {file_name} into {table_name} ({table.num_rows:,} rows)...")
    client.load_table_from_file(buffer, table_id, job_config=job_config).result()

    # Control: the row count in BigQuery must match the file exactly.
    loaded = client.get_table(table_id)
    assert loaded.num_rows == table.num_rows, f"{table_name}: row count doesn't match the file"
    expires = loaded.expires.strftime("%Y-%m-%d") if loaded.expires else "never"
    print(f"   done: {loaded.num_rows:,} rows in BigQuery, table expires {expires}")


# --- Load control: reconcile BigQuery against the source file ---------------
# The classic data-transfer check: record count plus a control total of the
# amounts. Because money is NUMERIC, the totals must match to the cent.
sql = f"SELECT COUNT(*) AS row_count, SUM(amount) AS total_amount FROM `{DATASET}.transactions`"
for row in client.query(sql).result():
    print(f"\nLoad control for transactions:")
    print(f"   rows:   file {source_rows:,}   BigQuery {row.row_count:,}")
    print(f"   amount: file {source_amount:,.2f}   BigQuery {row.total_amount:,.2f}")
    assert row.row_count == source_rows and row.total_amount == source_amount, "Load control failed"
print("\nLoad control passed: BigQuery matches the source files.")
