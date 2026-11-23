"""
Step 6: triage exceptions with Claude.

Send each exception's evidence to Claude with the prompt in
prompts/triage_v1.txt, and get back a category and a short investigation note.

Two sources:
  --source sample  the 100 hand-labelled exceptions (view triage_sample), used
                   to benchmark the AI against human labels (step 7)
  --source queue   every exception from the four checks (view triage_queue),
                   worked through 20 a day by the scheduled run

Every result is logged with the prompt version and a fingerprint of the exact
prompt text, the model asked for and the model that answered, the settings,
the time, and the tokens used. Results are saved to results/ and appended to
the BigQuery table triage_results.

The evidence comes from the views, never from the hand-labels file, so the AI
cannot see the human labels.

Incremental, with a cost cap: an exception already triaged successfully by the
same model and prompt version is skipped, and at most --max exceptions are sent
per run. Rerunning never pays twice for the same answer. To re-triage on
purpose, change the prompt and give it a new version (triage_v2).

Run from the project folder, with .venv active, after 05_build_triage_sample.py:
    python scripts/06_triage_with_llm.py                              (sample, Claude Opus 5.5, max 20)
    python scripts/06_triage_with_llm.py --model claude-haiku-5-5 --max 100
    python scripts/06_triage_with_llm.py --source queue --max 20      (what the daily run does)
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import pandas as pd
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="claude-opus-5-5")
parser.add_argument("--max", type=int, default=20, help="most exceptions to send in one run")
parser.add_argument("--source", choices=["sample", "queue"], default="sample",
                    help="sample = the 100 hand-labelled exceptions; queue = all exceptions")
args = parser.parse_args()

# --- Settings, all logged with every result -------------------------------------
MODEL = args.model
EFFORT = "low"  # classification against a fixed rubric doesn't need deep reasoning
PROMPT_VERSION = "triage_v1"
PROMPT = (ROOT / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
# A fingerprint of the exact prompt text: if one word changes, this changes.
PROMPT_SHA256 = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()[:12]
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

# The answer must be one of the four categories plus a note. The API enforces
# this shape, so there's no free text to parse and no misspelt categories.
ANSWER_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["fee_error", "data_error", "likely_fraud", "needs_investigation"],
            },
            "note": {"type": "string"},
        },
        "required": ["category", "note"],
        "additionalProperties": False,
    },
}

bq = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
claude = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

if args.source == "queue":
    # Create or refresh the queue view first, so it always matches the checks.
    queue_sql = (ROOT / "sql" / "triage" / "02_triage_queue.sql").read_text()
    bq.query(queue_sql.replace("{dataset}", DATASET)).result()
    # Take turns across the checks, largest amount first (see the SQL file).
    source_sql = f"SELECT * FROM `{DATASET}.triage_queue` ORDER BY queue_rank, check_name"
else:
    source_sql = f"SELECT * FROM `{DATASET}.triage_sample` ORDER BY sample_id"

sample = bq.query(source_sql).to_dataframe(create_bqstorage_client=False)

# --- Skip what's already done -----------------------------------------------------
# Exceptions this model already answered under this prompt version. Failed or
# refused attempts don't count, so they're retried on the next run.
# @model and @prompt_version are query parameters (like bind variables in
# Oracle): the values are passed separately, never pasted into the SQL text.
done_sql = f"""
    SELECT DISTINCT txn_id, check_name
    FROM `{DATASET}.triage_results`
    WHERE model_requested = @model
      AND prompt_version = @prompt_version
      AND ai_category IS NOT NULL
"""
job_config = bigquery.QueryJobConfig(query_parameters=[
    bigquery.ScalarQueryParameter("model", "STRING", MODEL),
    bigquery.ScalarQueryParameter("prompt_version", "STRING", PROMPT_VERSION),
])
try:
    done = bq.query(done_sql, job_config=job_config).to_dataframe(create_bqstorage_client=False)
except NotFound:  # very first run: the results table doesn't exist yet
    done = pd.DataFrame(columns=["txn_id", "check_name"])

todo = sample.merge(done, on=["txn_id", "check_name"], how="left", indicator=True)
todo = todo[todo["_merge"] == "left_only"].drop(columns="_merge")
print(f"{len(sample)} exceptions in the {args.source}, {len(done)} already triaged by {MODEL} "
      f"with {PROMPT_VERSION}, {len(todo)} to do.")

if todo.empty:
    print("Nothing new to triage. No API calls made.")
    sys.exit(0)

todo = todo.head(args.max)  # the cost cap
print(f"Triaging {len(todo)} exceptions with {MODEL} (run {RUN_ID}, cap {args.max})...")

results = []
for _, row in todo.iterrows():
    # Evidence as "field: value" lines. sample_id and queue_rank are our
    # bookkeeping, not evidence.
    evidence = "\n".join(
        f"{field}: {'' if pd.isna(value) else value}"
        for field, value in row.items()
        if field not in ("sample_id", "queue_rank")
    )
    # Queue rows have no sample_id; they aren't part of the labelled benchmark.
    sample_id = int(row["sample_id"]) if "sample_id" in row else None

    request = dict(
        model=MODEL,
        max_tokens=4000,
        system=PROMPT,
        messages=[{"role": "user", "content": f"Exception evidence:\n{evidence}"}],
        output_config={"effort": EFFORT, "format": ANSWER_FORMAT},
    )
    if not MODEL.startswith("claude-haiku"):
        # If the model declines on safety grounds, the API reruns the request on
        # a fallback model. model_served below records which model answered.
        request.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")

    category, note, model_served, stop_reason = None, None, None, None
    input_tokens = output_tokens = 0
    try:
        response = claude.beta.messages.create(**request)
        stop_reason = response.stop_reason
        model_served = response.model
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        if stop_reason == "end_turn":
            answer = json.loads(next(b.text for b in response.content if b.type == "text"))
            category, note = answer["category"], answer["note"]
    except anthropic.AuthenticationError:
        # A rejected or expired key affects every request, so stop loudly (the
        # GitHub run turns red) instead of recording 20 identical failures.
        sys.exit("Claude API key rejected or expired. Create a new key and update "
                 ".env (local) or the ANTHROPIC_API_KEY secret (GitHub).")
    except anthropic.APIError as error:
        # Record the failure and carry on; a missing answer goes to human review.
        stop_reason = f"api_error: {type(error).__name__}"

    results.append({
        "run_id": RUN_ID,
        "sample_id": sample_id,
        "check_name": row["check_name"],
        "txn_id": int(row["txn_id"]),
        "ai_category": category,
        "ai_note": note,
        "stop_reason": stop_reason,
        "model_requested": MODEL,
        "model_served": model_served,
        "effort": EFFORT,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
        "triaged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    })
    print(f"  {row['txn_id']:>8}  {row['check_name']:<22} -> {category or stop_reason}")

# --- Save ---------------------------------------------------------------------
table = pd.DataFrame(results)
# Whole numbers that may be blank (queue rows): keeps the column an INTEGER in
# BigQuery instead of turning into decimals.
table["sample_id"] = table["sample_id"].astype("Int64")
out_file = ROOT / "results" / f"triage_{RUN_ID}_{MODEL}.csv"
table.to_csv(out_file, index=False)

# Append to BigQuery with a load job (no INSERT in the sandbox). Earlier runs
# stay in the table: the run_id tells them apart.
bq.load_table_from_dataframe(
    table,
    f"{DATASET}.triage_results",
    job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"),
).result()

answered = table["ai_category"].notna().sum()
print(f"\nAnswered: {answered} of {len(table)}")
print(f"Tokens used: {table['input_tokens'].sum():,} in, {table['output_tokens'].sum():,} out")
print(f"Saved to {out_file.relative_to(ROOT)} and {DATASET}.triage_results")
