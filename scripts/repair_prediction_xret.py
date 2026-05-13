"""One-off: fill missing actual_xret from actual_ret (TW vs US benchmark calendar gap).

Run after upgrading tracker logic, or anytime predictions.csv has actual_ret but
blank actual_xret. Re-run `python scripts/run_daily.py` afterward to regenerate
`docs/index.html` and other artifacts.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from pipeline.tracker import build_daily_summary, load_tracker


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=ROOT / "docs" / "data")
    args = ap.parse_args()
    dd: Path = args.data_dir
    df = load_tracker(dd)
    if df.empty:
        print("No predictions.csv — nothing to repair.")
        return
    m = df["actual_ret"].notna() & df["actual_xret"].isna()
    n = int(m.sum())
    if n:
        df.loc[m, "actual_xret"] = df.loc[m, "actual_ret"]
        df.to_csv(dd / "predictions.csv", index=False)
        print(f"Repaired actual_xret on {n} row(s).")
    else:
        print("No rows needed repair.")
    summary = build_daily_summary(df)
    summary.to_csv(dd / "tracker.csv", index=False)
    print(f"Wrote tracker.csv ({len(summary)} summary rows).")


if __name__ == "__main__":
    main()
