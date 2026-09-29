"""
reconciliation.py
=================
A source-to-target reconciliation layer for ETL loads.

An ETL pipeline that reports "loaded successfully" has said nothing. The
question a reconciliation answers is narrower and harder: *does what landed in
the target account for everything that left the source?* Row counts must tie or
the difference must be explained record by record; control totals on the numeric
columns must tie; every key in the target must exist in the source and be
unique in both.

The unit of evidence is the **variance log**: one row per source record that did
not reach the target, naming the record and the rule that rejected it. A drop
that is logged is a documented exclusion. A drop that is not logged is data
loss, and the two are indistinguishable from a row count alone.

Checks
------
REC-01  ROW_COUNT            source rows = target rows + logged rejects
REC-02  KEY_UNIQUE           the business key is unique in source and in target
REC-03  KEY_COMPLETENESS     every target key exists in the source (no orphans)
REC-04  NO_SILENT_DROP       every source key absent from the target is logged
REC-05  CONTROL_TOTAL        summed numeric columns tie between source and target
REC-06  COLUMN_COMPLETENESS  null counts per column, source vs target
REC-07  ROUND_TRIP           rows read back from the target equal rows written

Every check returns PASS or FAIL with the observed and expected values, so the
whole reconciliation is a table an auditor can read without running anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

CHECK_COLUMNS = ["check_id", "check_name", "scope", "expected", "observed",
                 "variance", "result", "note"]


@dataclass
class RejectRule:
    """A named reason a source record may legitimately not reach the target."""
    code: str
    description: str
    predicate: object          # Callable[[pd.DataFrame], pd.Series[bool]]


def _row(check_id, name, scope, expected, observed, note="") -> dict:
    try:
        variance = round(float(observed) - float(expected), 6)
    except (TypeError, ValueError):
        variance = 0 if observed == expected else None
    result = "PASS" if (variance == 0 or observed == expected) else "FAIL"
    return dict(check_id=check_id, check_name=name, scope=scope,
                expected=expected, observed=observed, variance=variance,
                result=result, note=note)


# --------------------------------------------------------------------------- #
# Variance log
# --------------------------------------------------------------------------- #
def build_variance_log(source: pd.DataFrame, key: str,
                       rules: Iterable[RejectRule]) -> pd.DataFrame:
    """
    Apply each reject rule in order and record every excluded source record with
    the rule that excluded it. First matching rule wins, so a record appears
    once and its reason is unambiguous.
    """
    remaining = source.copy()
    rows = []
    for rule in rules:
        mask = rule.predicate(remaining)
        for _, rec in remaining[mask].iterrows():
            rows.append(dict(
                key_value=rec[key], reject_code=rule.code,
                reject_reason=rule.description,
            ))
        remaining = remaining[~mask]
    log = pd.DataFrame(rows, columns=["key_value", "reject_code", "reject_reason"])
    return log, remaining


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def reconcile(source: pd.DataFrame, target: pd.DataFrame, key: str,
              variance_log: pd.DataFrame,
              control_columns: list[str],
              target_key: str | None = None,
              round_trip: pd.DataFrame | None = None) -> pd.DataFrame:
    tkey = target_key or key
    checks: list[dict] = []

    # REC-01 -----------------------------------------------------------------
    checks.append(_row(
        "REC-01", "ROW_COUNT", "table",
        len(source), len(target) + len(variance_log),
        f"{len(source)} source = {len(target)} target + {len(variance_log)} logged rejects",
    ))

    # REC-02 -----------------------------------------------------------------
    checks.append(_row("REC-02", "KEY_UNIQUE", f"source.{key}",
                       len(source), source[key].nunique(),
                       "business key must be unique in the source"))
    checks.append(_row("REC-02", "KEY_UNIQUE", f"target.{tkey}",
                       len(target), target[tkey].nunique(),
                       "business key must be unique in the target"))

    # REC-03 -----------------------------------------------------------------
    orphans = set(target[tkey]) - set(source[key])
    checks.append(_row("REC-03", "KEY_COMPLETENESS", "target -> source", 0, len(orphans),
                       "target keys with no matching source record"
                       + (f": {sorted(orphans)[:5]}" if orphans else "")))

    # REC-04 -----------------------------------------------------------------
    dropped = set(source[key]) - set(target[tkey])
    logged = set(variance_log["key_value"])
    unexplained = dropped - logged
    checks.append(_row("REC-04", "NO_SILENT_DROP", "source -> target", 0, len(unexplained),
                       "source records absent from the target and absent from the log"
                       + (f": {sorted(unexplained)[:5]}" if unexplained else "")))

    # REC-05 -----------------------------------------------------------------
    kept = source[source[key].isin(set(target[tkey]))]
    for col in control_columns:
        if col not in source.columns or col not in target.columns:
            continue
        s_total = round(float(pd.to_numeric(kept[col], errors="coerce").sum()), 3)
        t_total = round(float(pd.to_numeric(target[col], errors="coerce").sum()), 3)
        checks.append(_row("REC-05", "CONTROL_TOTAL", col, s_total, t_total,
                           "sum over retained records must tie"))

    # REC-06 -----------------------------------------------------------------
    for col in control_columns:
        if col not in target.columns:
            continue
        checks.append(_row("REC-06", "COLUMN_COMPLETENESS", col,
                           0, int(target[col].isna().sum()),
                           "the target must carry no nulls in a control column"))

    # REC-07 -----------------------------------------------------------------
    if round_trip is not None:
        checks.append(_row("REC-07", "ROUND_TRIP", "row count",
                           len(target), len(round_trip),
                           "rows read back from the target"))
        common = [c for c in control_columns if c in round_trip.columns]
        for col in common:
            a = round(float(pd.to_numeric(target[col], errors="coerce").sum()), 3)
            b = round(float(pd.to_numeric(round_trip[col], errors="coerce").sum()), 3)
            checks.append(_row("REC-07", "ROUND_TRIP", col, a, b,
                               "value written must equal value read back"))

    return pd.DataFrame(checks, columns=CHECK_COLUMNS)


def summarize(checks: pd.DataFrame) -> str:
    failed = checks[checks["result"] == "FAIL"]
    lines = [f"{len(checks)} checks, {len(checks) - len(failed)} passed, {len(failed)} failed"]
    if len(failed):
        for r in failed.itertuples():
            lines.append(f"  FAIL {r.check_id} {r.check_name} [{r.scope}] "
                         f"expected {r.expected}, observed {r.observed}")
    return "\n".join(lines)
