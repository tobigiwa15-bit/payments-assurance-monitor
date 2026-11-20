"""
Step 0: check the setup before building anything.

Confirms three things, without spending any Claude credit:
  1. The .env file is found and holds the settings we need.
  2. Python can log in to BigQuery as the service account and run a query.
  3. Python can log in to the Claude API with the key.

Run from the project folder, with .venv active:
    python scripts/00_check_setup.py
"""

import os

import anthropic
import google.auth
from dotenv import load_dotenv
from google.cloud import bigquery

# Copy the settings from .env into the environment, where both libraries look for them.
load_dotenv()


# --- 1. Settings ------------------------------------------------------------
# Check that each setting is present, but never print the values: two are secrets.
required = ["GCP_PROJECT_ID", "GOOGLE_APPLICATION_CREDENTIALS", "ANTHROPIC_API_KEY"]
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit(f"Missing from .env: {', '.join(missing)}")
print("1. Settings: all three found in .env")


# --- 2. BigQuery ------------------------------------------------------------
# Google's library reads the key file named in GOOGLE_APPLICATION_CREDENTIALS.
# Printing the identity proves the code runs as the robot account, not as you.
credentials, _ = google.auth.default()
print(f"2. BigQuery: logged in as {credentials.service_account_email}")

bq = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"), credentials=credentials)
sql = "SELECT COUNT(*) AS row_count FROM `bigquery-public-data.samples.shakespeare`"
for row in bq.query(sql).result():
    print(f"   test query returned {row.row_count:,} rows")


# --- 3. Claude API ----------------------------------------------------------
# Asking for a model's details checks the key but uses no tokens, so it costs nothing.
claude = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
try:
    model = claude.models.retrieve("claude-opus-5-5")
except anthropic.AuthenticationError:
    raise SystemExit("3. Claude API: key rejected. Check ANTHROPIC_API_KEY in .env")
print(f"3. Claude API: key accepted, {model.display_name} is available")

print("\nSetup check passed.")
