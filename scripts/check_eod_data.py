"""Print Yahoo's latest daily bar vs the expected completed session; exit non-zero if behind.

Uses the same ``Config`` / cache paths as ``run_daily.py`` (env ``UNIVERSE``, etc.).

Examples::

    python scripts/check_eod_data.py
    python scripts/check_eod_data.py --json

Exit codes:
    0 — probed symbols include the required session date (data looks ready).
    1 — data not ready or probe failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.config import DEFAULT_CONFIG
from pipeline.eod_ready import assess_eod_readiness


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--no-refresh",
        action="store_true",
        help="Allow reading a cached probe file if it exists (default: refresh=True).",
    )
    p.add_argument(
        "--probe-extra",
        type=int,
        default=5,
        metavar="N",
        help="How many universe names to probe in addition to the benchmark (default: 5).",
    )
    p.add_argument("--json", action="store_true", help="Print a JSON object instead of text.")
    p.add_argument(
        "--data-as-of",
        metavar="YYYY-MM-DD",
        default=None,
        help="Pin EOD requirement to this session (same as env DATA_AS_OF).",
    )
    args = p.parse_args()

    cfg = replace(DEFAULT_CONFIG, sectors=dict(DEFAULT_CONFIG.sectors))
    if args.data_as_of:
        d = args.data_as_of.strip()
        cfg = replace(cfg, data_as_of=d if d else None)
    st = assess_eod_readiness(
        cfg, refresh=not args.no_refresh, probe_extra=max(1, args.probe_extra)
    )
    if args.json:
        payload = {
            "ready": st.ready,
            "required_session_date": st.required_session_date.isoformat(),
            "per_ticker_max": {k: v.isoformat() for k, v in st.per_ticker_max.items()},
            "probe_tickers": list(st.probe_tickers),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(st.message)

    sys.exit(0 if st.ready else 1)


if __name__ == "__main__":
    main()
