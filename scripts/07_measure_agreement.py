"""
Step 7: measure how often the AI agrees with the human labels.

Compares labels/hand_labels.csv with the latest triage run for each model in
results/. Agreement = the share of exceptions where the AI chose the same
category as the human. A missing AI answer counts as a disagreement.

Every disagreement goes to a review queue: a human decides, not the AI.

Outputs (in results/, and copied to BigQuery for the dashboard):
  agreement_summary.csv          agreement rate per model, overall and per check
  review_queue_<model>.csv       every disagreement, with both notes side by side

Written before any AI results were seen, so the scoring can't be bent to fit.

Run from the project folder, with .venv active, after 06_triage_with_llm.py:
    python scripts/07_measure_agreement.py
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
DATASET = f"{os.getenv('GCP_PROJECT_ID')}.payments_assurance"

# --- The human labels ---------------------------------------------------------
human = pd.read_csv(ROOT / "labels" / "hand_labels.csv", encoding="utf-8-sig")
human = human[["sample_id", "check_name", "txn_id", "my_label", "my_note"]]
human["my_label"] = human["my_label"].str.strip()

# --- The latest AI run for each model -------------------------------------------
runs = pd.concat(pd.read_csv(f) for f in RESULTS.glob("triage_*.csv"))
# Benchmark rows only: queue runs (06 --source queue) have no sample_id and no
# human label to compare with, so they must never count as the "latest run".
runs = runs[runs["sample_id"].notna()]
latest = runs.groupby("model_requested")["run_id"].transform("max")
runs = runs[runs["run_id"] == latest]

summary_rows = []
for model, ai in runs.groupby("model_requested"):
    both = human.merge(ai, on="sample_id", suffixes=("", "_ai"))

    # Control: the two files must describe the same 100 exceptions.
    assert len(both) == len(human), f"{model}: AI results don't cover every labelled exception"
    assert (both["txn_id"] == both["txn_id_ai"]).all(), f"{model}: transaction IDs don't line up"

    both["agree"] = both["ai_category"] == both["my_label"]  # missing answer = disagree

    print(f"\n=== {model} (run {ai['run_id'].iloc[0]}, prompt {ai['prompt_version'].iloc[0]}) ===")
    print(f"Agreement: {both['agree'].sum()} of {len(both)} = {both['agree'].mean():.0%}")

    by_check = both.groupby("check_name")["agree"].agg(["sum", "count", "mean"])
    by_check.columns = ["agreed", "labelled", "agreement_rate"]
    print("\nBy check:")
    print(by_check.to_string(formatters={"agreement_rate": "{:.0%}".format}))

    # Rows = what the human said, columns = what the AI said.
    # Everything off the diagonal is a disagreement.
    print("\nHuman label (rows) vs AI category (columns):")
    print(pd.crosstab(both["my_label"], both["ai_category"].fillna("(no answer)")).to_string())

    # Every disagreement goes to human review, with both views side by side.
    queue = both.loc[~both["agree"], ["sample_id", "check_name", "txn_id", "my_label",
                                      "ai_category", "my_note", "ai_note"]]
    queue.to_csv(RESULTS / f"review_queue_{model}.csv", index=False)
    print(f"\nDisagreements sent to review: {len(queue)} (results/review_queue_{model}.csv)")

    summary_rows.append({"model": model, "run_id": ai["run_id"].iloc[0],
                         "prompt_version": ai["prompt_version"].iloc[0], "check_name": "ALL",
                         "labelled": len(both), "agreed": int(both["agree"].sum()),
                         "agreement_rate": round(both["agree"].mean(), 4)})
    for check, r in by_check.iterrows():
        summary_rows.append({"model": model, "run_id": ai["run_id"].iloc[0],
                             "prompt_version": ai["prompt_version"].iloc[0], "check_name": check,
                             "labelled": int(r["labelled"]), "agreed": int(r["agreed"]),
                             "agreement_rate": round(r["agreement_rate"], 4)})

# --- Save --------------------------------------------------------------------
summary = pd.DataFrame(summary_rows)
summary.to_csv(RESULTS / "agreement_summary.csv", index=False)

bq = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
bq.load_table_from_dataframe(
    summary, f"{DATASET}.ai_agreement",
    job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
).result()
print(f"\nSaved results/agreement_summary.csv and {DATASET}.ai_agreement")
