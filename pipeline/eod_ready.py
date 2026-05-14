"""Pre-flight: Yahoo/yfinance daily bar vs last *expected* completed local session.

Taiwan and US rules use **local calendar weekdays + regular close time** only
(no exchange holiday calendar). On TWSE/NYSE holidays, use ``--skip-eod-check``
if you still want a run, or wait until Yahoo shows a bar for the next session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from .config import Config
from .data import download_prices


TWSE_REGULAR_END = dtime(13, 30)
NYSE_REGULAR_END = dtime(16, 0)


def _previous_weekday(d: date) -> date:
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def taipei_latest_completed_session_date(now: datetime | None = None) -> date:
    """Calendar date of the last TWSE *regular* session we treat as complete.

    Mon–Fri before 13:30 Taipei: previous weekday (Fri if Monday morning).
    Mon–Fri at/after 13:30: today's local date (TW holidays not modeled).
    Sat/Sun: previous Friday.
    """
    tz = ZoneInfo("Asia/Taipei")
    if now is None:
        now = datetime.now(timezone.utc)
    now = now.astimezone(tz)
    d, t = now.date(), now.time()
    wd = d.weekday()
    if wd == 5:
        return d - timedelta(days=1)
    if wd == 6:
        return d - timedelta(days=2)
    if t < TWSE_REGULAR_END:
        return _previous_weekday(d)
    return d


def nyse_latest_completed_session_date(now: datetime | None = None) -> date:
    """Same idea in America/New_York (16:00 regular close, weekdays only)."""
    tz = ZoneInfo("America/New_York")
    if now is None:
        now = datetime.now(timezone.utc)
    now = now.astimezone(tz)
    d, t = now.date(), now.time()
    wd = d.weekday()
    if wd == 5:
        return d - timedelta(days=1)
    if wd == 6:
        return d - timedelta(days=2)
    if t < NYSE_REGULAR_END:
        return _previous_weekday(d)
    return d


def _use_taipei_session_clock(cfg: Config) -> bool:
    return any(t.endswith(".TW") for t in cfg.all_tickers)


def probe_per_ticker_max_dates(
    tickers: Sequence[str],
    *,
    cfg: Config,
    refresh: bool = True,
) -> dict[str, date]:
    """Max daily ``date`` from Yahoo for each symbol (small probe download)."""
    tks = tuple(sorted({t for t in tickers if t}))
    if not tks:
        return {}
    df = download_prices(tks, cfg.start, cfg.end, cfg.cache_dir, refresh=refresh)
    if df.empty:
        return {t: date.min for t in tks}
    out: dict[str, date] = {}
    for tkr, g in df.groupby("ticker"):
        mx = pd.to_datetime(g["date"]).max()
        out[str(tkr)] = mx.date() if pd.notna(mx) else date.min
    for t in tks:
        out.setdefault(t, date.min)
    return out


@dataclass(frozen=True)
class EodReadiness:
    ready: bool
    required_session_date: date
    per_ticker_max: dict[str, date]
    probe_tickers: tuple[str, ...]
    message: str


def assess_eod_readiness(
    cfg: Config,
    *,
    refresh: bool = True,
    probe_extra: int = 5,
) -> EodReadiness:
    """Probe Yahoo for a few symbols; ``ready`` if all probed bars cover ``required``.

    If ``cfg.data_as_of`` is set (env ``DATA_AS_OF``), ``required`` is that session
    date only — use this to publish an as-of snapshot (e.g. 5/13 EOD) while a
    later calendar day is still open.
    """
    if _use_taipei_session_clock(cfg):
        clock = "Asia/Taipei (TWSE regular close 13:30)"
        clock_required = taipei_latest_completed_session_date()
    else:
        clock = "America/New_York (regular close 16:00)"
        clock_required = nyse_latest_completed_session_date()

    if cfg.data_as_of:
        raw = str(cfg.data_as_of).strip()
        required = pd.Timestamp(raw).date()
        clock = f"{clock}; DATA_AS_OF pinned to {required} (not live clock {clock_required})"
    else:
        required = clock_required

    probe: list[str] = [cfg.benchmark]
    for t in cfg.universe:
        if t in probe:
            continue
        probe.append(t)
        if len(probe) >= 1 + probe_extra:
            break
    probe_tickers = tuple(probe)

    per = probe_per_ticker_max_dates(probe_tickers, cfg=cfg, refresh=refresh)
    if not per:
        return EodReadiness(
            ready=False,
            required_session_date=required,
            per_ticker_max={},
            probe_tickers=probe_tickers,
            message=f"EOD probe: Yahoo returned no rows (required session date {required}).",
        )

    mins = min(per.values())
    maxs = max(per.values())
    ready = mins >= required
    parts = [
        f"EOD check ({clock}).",
        f"Required session date (min bar date each ticker must reach): {required}.",
        f"Probed {len(probe_tickers)} tickers: min(max date)={mins}, max(max date)={maxs}.",
    ]
    for t in sorted(per):
        parts.append(f"  {t}: last bar {per[t]}")
    if not ready:
        parts.append(
            f"Not ready: at least one probed symbol is still before {required} "
            f"(Yahoo daily often lags for .TW). Re-run later or use --skip-eod-check."
        )
    else:
        parts.append("OK: probed symbols include the required session.")
    return EodReadiness(
        ready=ready,
        required_session_date=required,
        per_ticker_max=per,
        probe_tickers=probe_tickers,
        message="\n".join(parts),
    )
