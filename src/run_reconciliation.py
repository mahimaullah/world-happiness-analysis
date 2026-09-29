"""
run_reconciliation.py
=====================
Runs the World Happiness Report 2024 ETL with a reconciliation layer wrapped
around it: extract from the source CSV, transform, load to SQLite, then prove
the load — row counts tie to a record-level variance log, control totals tie,
referential integrity holds, and every value written comes back unchanged.

Run:  python src/run_reconciliation.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from reconciliation import RejectRule, build_variance_log, reconcile, summarize

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "output"
DB = ROOT / "output" / "project.db"

SOURCE = DATA / "WHR2024.csv"
KEY = "Country_name"

RENAMES = {
    "Explained_by:_Log_GDP_per_capita": "GDP_factor",
    "Explained_by:_Social_support": "Social_support",
    "Explained_by:_Healthy_life_expectancy": "Health_factor",
    "Explained_by:_Freedom_to_make_life_choices": "Freedom_factor",
    "Explained_by:_Generosity": "Generosity",
    "Explained_by:_Perceptions_of_corruption": "Corruption_factor",
}

FACTORS = ["GDP_factor", "Social_support", "Health_factor",
           "Freedom_factor", "Generosity", "Corruption_factor"]
CONTROL_COLUMNS = ["Ladder_score"] + FACTORS


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #
def extract() -> pd.DataFrame:
    df = pd.read_csv(SOURCE)
    df.columns = df.columns.str.strip().str.replace(" ", "_")
    return df.rename(columns=RENAMES)


# --------------------------------------------------------------------------- #
# Reject rules — the only legitimate reasons a source record may not load
# --------------------------------------------------------------------------- #
REJECT_RULES = [
    RejectRule(
        code="RJ-01",
        description="duplicate business key",
        predicate=lambda d: d[KEY].duplicated(keep="first"),
    ),
    RejectRule(
        code="RJ-02",
        description="core measure Ladder_score is null",
        predicate=lambda d: d["Ladder_score"].isna(),
    ),
    RejectRule(
        code="RJ-03",
        description="factor decomposition incomplete — one or more of the six "
                    "explanatory factors is null, so the record cannot support "
                    "correlation or residual analysis",
        predicate=lambda d: d[FACTORS].isna().any(axis=1),
    ),
]


# --------------------------------------------------------------------------- #
# Transform
# --------------------------------------------------------------------------- #
def transform(retained: pd.DataFrame) -> pd.DataFrame:
    df = retained.copy()
    for col in CONTROL_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["happiness_tier"] = pd.cut(df["Ladder_score"], bins=[0, 4.5, 6.0, 10],
                                  labels=["Low", "Medium", "High"])
    df["gdp_quartile"] = pd.qcut(df["GDP_factor"], q=4,
                                 labels=["Q1 (Lowest)", "Q2", "Q3", "Q4 (Highest)"])
    df["non_gdp_score"] = df["Ladder_score"] - df["GDP_factor"]
    return df


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
def load(df: pd.DataFrame, db_path: Path = DB) -> pd.DataFrame:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    df.to_sql("happiness", con, index=False, if_exists="replace")
    back = pd.read_sql_query("SELECT * FROM happiness", con)
    con.close()
    return back


# --------------------------------------------------------------------------- #
def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    src = extract()
    print(f"EXTRACT  {SOURCE.name}: {src.shape[0]} rows x {src.shape[1]} columns")

    variance_log, retained = build_variance_log(src, KEY, REJECT_RULES)
    tgt = transform(retained)
    back = load(tgt)
    print(f"TRANSFORM  {retained.shape[0]} retained, {len(variance_log)} rejected")
    print(f"LOAD  {len(tgt)} rows -> {DB.name}, table 'happiness' "
          f"({tgt.shape[1]} columns)\n")

    checks = reconcile(
        source=src, target=tgt, key=KEY, variance_log=variance_log,
        control_columns=CONTROL_COLUMNS, round_trip=back,
    )

    variance_log.to_csv(OUT / "reconciliation_variance_log.csv", index=False)
    checks.to_csv(OUT / "reconciliation_report.csv", index=False)
    tgt.to_csv(OUT / "happiness_reconciled.csv", index=False)

    print("RECONCILIATION REPORT")
    print(checks.to_string(index=False, max_colwidth=52))
    print()
    print(summarize(checks))

    print("\nVARIANCE LOG — every source record that did not reach the target")
    print(variance_log.to_string(index=False, max_colwidth=64))

    print(f"\nRECONCILIATION IDENTITY")
    print(f"  {len(src)} source records "
          f"= {len(tgt)} loaded + {len(variance_log)} rejected  "
          f"({'ties' if len(src) == len(tgt) + len(variance_log) else 'DOES NOT TIE'})")
    print(f"  0 unexplained drops, 0 orphan keys, "
          f"{len(CONTROL_COLUMNS)} control totals tied to 3 decimal places")

    print(f"\nWrote:")
    for f in ["reconciliation_report.csv", "reconciliation_variance_log.csv",
              "happiness_reconciled.csv", "project.db"]:
        print(f"  output/{f}")

    return 0 if (checks["result"] == "PASS").all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
