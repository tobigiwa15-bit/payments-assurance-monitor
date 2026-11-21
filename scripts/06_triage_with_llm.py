"""
Step 6: triage the sampled exceptions with Claude.

For each of the 100 exceptions in the view triage_sample, send the evidence to
Claude with the prompt in prompts/triage_v1.txt, and get back a category and a
short investigation note.

Every result is logged with the prompt version and a fingerprint of the exact
prompt text, the model asked for and the model that answered, the settings,
the time, and the tokens used. Results are saved to results/ and appended to
the BigQuery table triage_results.

The evidence comes from the triage_sample view, never from the hand-labels file,
so the AI cannot see the human labels.

Run from the project folder, with .venv active, after 05_build_triage_sample.py:
    python scripts/06_triage_with_llm.py                     (Claude Opus 5.5)
    python scripts/06_triage_with_llm.py claude-haiku-5-5    (another model)
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"

# --- Settings, all logged with every result -------------------------------------
MODEL = sys.argv[1] if len(sys.argv) > 1 else "claude-opus-5-5"
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

sample = bq.query(
    f"SELECT * FROM `{DATASET}.triage_sample` ORDER BY sample_id"
).to_dataframe(create_bqstorage_client=False)
print(f"Triaging {len(sample)} exceptions with {MODEL} (run {RUN_ID})...")

results = []
for _, row in sample.iterrows():
    # Evidence as "field: value" lines. sample_id is our bookkeeping, not evidence.
    evidence = "\n".join(
        f"{field}: {'' if pd.isna(value) else value}"
        for field, value in row.items()
        if field != "sample_id"
    )

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
    except anthropic.APIError as error:
        # Record the failure and carry on; a missing answer goes to human review.
        stop_reason = f"api_error: {type(error).__name__}"

    results.append({
        "run_id": RUN_ID,
        "sample_id": int(row["sample_id"]),
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
    print(f"  {row['sample_id']:>3}  {row['check_name']:<22} -> {category or stop_reason}")

# --- Save ---------------------------------------------------------------------
table = pd.DataFrame(results)
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
