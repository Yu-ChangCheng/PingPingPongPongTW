"""Daily OHLCV downloader with disk cache."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import yfinance as yf


def _extract_ticker_frame(raw: pd.DataFrame, tkr: str) -> pd.DataFrame | None:
    """Normalize yfinance output for one symbol (batch MultiIndex vs single flat columns)."""
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw[tkr].copy()
        else:
            sub = raw.copy()
    except (KeyError, TypeError):
        return None
    sub = sub.rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Adj Close": "adj_close", "Volume": "volume",
    }).dropna(subset=["close"])
    if sub.empty:
        return None
    sub["ticker"] = tkr
    sub = sub.reset_index().rename(columns={"Date": "date"})
    return sub[["date", "ticker", "open", "high", "low",
                "close", "adj_close", "volume"]]


def download_prices(tickers: Iterable[str], start: str, end: str | None,
                    cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    """Download daily OHLCV for `tickers`. Returns a long-format frame:
    columns = [date, ticker, open, high, low, close, adj_close, volume].

    `refresh=True` forces re-download (used by the daily run to pick up new bars).
    Cached file is keyed by start date + ticker count, so adding/removing tickers
    invalidates the cache automatically.

    Yahoo/yfinance treats ``end`` as an *exclusive* calendar bound. ``end=None``
    often omits the newest session bar (especially vs UTC day boundaries). When
    ``end`` is omitted we therefore pass an explicit date a few days ahead so the
    latest completed local session (e.g. TWSE close same calendar day) is included.
    """
    tickers = list(tickers)
    if end is None:
        end = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"prices_{start}_{end or 'now'}_{len(tickers)}.pkl"
    if cache_file.exists() and not refresh:
        df = pd.read_pickle(cache_file)
        if set(df["ticker"].unique()) >= set(tickers):
            return df[df["ticker"].isin(tickers)].reset_index(drop=True)

    # threads=False: parallel batch hits SQLite cache "database is locked" on CI runners.
    raw = yf.download(
        tickers, start=start, end=end,
        auto_adjust=False, progress=False, group_by="ticker",
        threads=False,
    )

    rows: list[pd.DataFrame] = []
    ok: set[str] = set()
    for tkr in tickers:
        got = _extract_ticker_frame(raw, tkr)
        if got is not None and not got.empty:
            rows.append(got)
            ok.add(tkr)

    # Retry missing tickers one-by-one (handles intermittent failures / locks).
    for tkr in tickers:
        if tkr in ok:
            continue
        try:
            one = yf.download(
                [tkr], start=start, end=end,
                auto_adjust=False, progress=False, group_by="ticker",
                threads=False,
            )
        except Exception:
            continue
        got = _extract_ticker_frame(one, tkr)
        if got is not None and not got.empty:
            rows.append(got)
            ok.add(tkr)

    if not rows:
        raise RuntimeError("yfinance returned no data — check internet/tickers.")
    df = pd.concat(rows, ignore_index=True).sort_values(["date", "ticker"])
    df.to_pickle(cache_file)
    return df


def _listing_session_calendar_days(s: pd.Series) -> pd.Series:
    """Session **calendar date** per row (TWSE: Asia/Taipei) for ``DATA_AS_OF`` logic.

    Yahoo batch downloads can mix naive dates with tz-aware timestamps across
    tickers; comparing naive ``Timestamp('YYYY-MM-DD')`` cutoffs to those values
    can drop the last in-range session for ``0050.TW`` while other names still
    pass. Using **local listing calendar day** avoids that.
    """
    d = pd.to_datetime(s, utc=False)
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_convert("Asia/Taipei")
    return pd.Series(d.dt.date, index=s.index, dtype=object)


def clip_prices_to_as_of(prices: pd.DataFrame, as_of: str | None) -> pd.DataFrame:
    """Drop rows whose **listing session calendar day** is after ``as_of``.

    ``as_of`` is inclusive (ISO ``YYYY-MM-DD``). Uses Taipei calendar day for
    tz-aware timestamps so the clip matches Yahoo's TW session labels.

    Use with env ``DATA_AS_OF=YYYY-MM-DD`` to freeze the pipeline as-of a past
    session (e.g. publish predictions for the *next* open while a later session
    is still trading).
    """
    if not as_of or not str(as_of).strip():
        return prices
    if prices.empty:
        return prices
    co: date = pd.Timestamp(str(as_of).strip()).date()
    days = _listing_session_calendar_days(prices["date"])
    return prices.loc[days <= co].copy()


def ffill_index_missing_sessions(
    prices: pd.DataFrame,
    index_tickers: Iterable[str],
) -> pd.DataFrame:
    """Fill calendar gaps in index/ETF daily rows (e.g. ``0050.TW``) from Yahoo.

    Yahoo sometimes omits a session for ``0050.TW`` while constituents have that
    day, which breaks ``DATA_AS_OF`` clipping (last 0050 bar can sit *before* the
    clip date). For each missing session we duplicate the **previous** OHLCV row
    for that index ticker and assign the same ``date`` stamp as any other row on
    that session day so ``build_panel`` bench merges stay aligned.
    """
    if prices.empty:
        return prices
    tks = [t for t in index_tickers if t]
    if not tks:
        return prices
    cols = list(prices.columns)
    out = prices.copy()
    for _ in range(8):
        tmp = out.assign(_sess=_listing_session_calendar_days(out["date"]))
        all_days = sorted(set(tmp["_sess"].tolist()))
        extras: list[dict] = []
        for tkr in tks:
            if tkr not in tmp["ticker"].values:
                continue
            have = set(tmp.loc[tmp["ticker"] == tkr, "_sess"].tolist())
            for d in all_days:
                if d in have:
                    continue
                prior = tmp[(tmp["ticker"] == tkr) & (tmp["_sess"] < d)].sort_values(
                    "date"
                )
                if prior.empty:
                    continue
                stamp = tmp.loc[tmp["_sess"] == d, "date"]
                if stamp.empty:
                    continue
                last = prior.iloc[-1]
                row = {c: last[c] for c in cols}
                row["date"] = stamp.iloc[0]
                extras.append(row)
                have.add(d)
        if not extras:
            return out
        out = pd.concat([out, pd.DataFrame(extras)], ignore_index=True)
        out = out.drop_duplicates(["date", "ticker"], keep="last").sort_values(
            ["date", "ticker"]
        ).reset_index(drop=True)
    return out


def validate_prices_cover_as_of(
    prices: pd.DataFrame,
    as_of: str,
    tickers: Iterable[str],
) -> None:
    """Raise if any ``tickers`` lacks a row on or after session calendar day ``as_of``."""
    co: date = pd.Timestamp(str(as_of).strip()).date()
    need = {t for t in tickers if t}
    if not need:
        return
    if prices.empty:
        raise ValueError(f"DATA_AS_OF={as_of} but price frame is empty after clip.")
    tmp = prices.assign(_day=_listing_session_calendar_days(prices["date"]))
    by_t = tmp.groupby("ticker")["_day"].max()
    missing = sorted(t for t in need if t not in by_t.index)
    if missing:
        raise ValueError(
            f"DATA_AS_OF={as_of} but no price rows for tickers: {missing[:12]}"
            f"{'...' if len(missing) > 12 else ''}"
        )
    late = sorted(t for t in need if by_t.loc[t] < co)
    if late:
        raise ValueError(
            f"DATA_AS_OF={as_of} requires Yahoo data through at least that session; "
            f"these tickers end earlier: {late[:15]}{'...' if len(late) > 15 else ''}"
        )
