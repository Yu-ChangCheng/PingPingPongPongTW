# RF daily stock signals — panel model + static dashboard

Train a **Random Forest** on a **daily cross-section** of **Taiwan-listed** stocks (default: bundled Taiwan 50–style universe), score every name for **next-day excess return vs `0050.TW`**, and ship a **self-contained report** under `docs/` (works with **GitHub Pages**).

**Educational only — not investment advice.**

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
python scripts/run_daily.py
```

Then open **`docs/index.html`** in a browser (double-click on Windows, or `start docs\index.html`).

**First run** downloads years of daily prices (cached under `data_cache/`, gitignored). Later runs are faster.

---

## What you get

| Output | Purpose |
|--------|---------|
| **`docs/index.html`** | Live dashboard + **Day-by-day backtesting** tab (equity, tables, charts). |
| **`docs/data/predictions.csv`** | Latest scores per ticker. |
| **`docs/data/orders_today.csv`** | Suggested **BUY/SELL** rows for the **next** session (see below). |
| **`docs/data/holdings.csv`** | Simulated positions + risk hints for the live tracker. |
| **`docs/data/portfolio_history.csv`** | Backtest equity path (from walk-forward predictions). |
| **`docs/data/portfolio_trades.csv`** | Every simulated fill in the backtest. |
| **`docs/data/daily_views.json`** | Precomputed per-day replay (margin + T+1 cash). |
| **`docs/data/tracker.csv`** | Prediction vs realised returns as dates mature. |

Enable **GitHub Pages** with source = **`/docs`** on the `main` branch (the repo includes **`docs/.nojekyll`** so GitHub does not run Jekyll on static assets). Your site URL will be:

`https://<your-username>.github.io/<your-repo-name>/`

The included **Actions** workflow runs `python scripts/run_daily.py` on a schedule (**~13:35 Mon–Fri, Taiwan time**, a few minutes after TWSE’s 13:30 close so signals land near the closing price), wipes `data_cache/` on each run for a clean yfinance pull, and can commit updated `docs/` for you.

### Deploy checklist (GitHub Pages + Actions)

1. **Create a new repository** on GitHub (empty or push this folder as `main`).
2. **Push your code** so `.github/workflows/daily.yml`, `docs/.nojekyll`, and the rest of the tree are on **`main`**.
3. **Allow Actions to write commits:** **Settings → Actions → General → Workflow permissions** → choose **Read and write permissions**, and allow GitHub Actions to create and approve pull requests (or your workflow’s `git push` step will fail).
4. **Enable Pages:** **Settings → Pages → Build and deployment → Source:** **Deploy from a branch**, branch **`main`**, folder **`/docs`** (not “GitHub Actions” unless you add a separate Pages workflow).
5. **Run once manually:** **Actions → Daily prediction → Run workflow** so `docs/` is regenerated and committed; wait for the green check, then refresh your Pages URL (first load can take a minute).
6. **Optional repo variables** (**Settings → Secrets and variables → Actions → Variables**): `LIVE_PORTFOLIO_START`, `STARTING_CAPITAL` (e.g. `100000`), `UNIVERSE` (`core` for a smaller universe).

If you change **`starting_capital`** after you already have a live book, delete **`docs/data/live_portfolio.json`** and **`docs/data/live_portfolio_history.csv`** (or reset via git) so cash and positions match the new notional.

---

## How the “trading” rules work (simulator + orders)

The code assumes: **decision at today’s close** using features and prices through that close; the **simulator fills at that same close** (no look-ahead into the next bar’s return for the decision). The **HTML playbook** describes how *you* might execute at the **next open** — that part is human workflow, not additional simulation logic.

### Target portfolio (backtest + order math)

- **Long-only** by default: **`long_n = 5`** names get **equal weight** (~20% of equity each when fully invested).  
- Each day the model ranks the universe by predicted **next-day excess return**; the **top 5** are the target basket.  
- **Target shares** ≈ `floor(equity × weight / price)` using that day’s **adjusted close**.

### Buy, sell, hold, rebalance

| Idea | What happens |
|------|----------------|
| **New name enters top 5** | Simulator **BUYs** shares to reach the target weight. |
| **Name drops out of top 5** | Simulator **SELLs** the position (full exit). |
| **Still in top 5, size drifts** | Small gaps (rounding, PnL, partial cash) show as **ADD** (buy more) or **TRIM** (sell some) in the **backtest replay table** so each line stays near **1/5** of equity. |
| **Already at target** | **HOLD** — no trade row for that name that day. |
| **Dust trades** | Trades smaller than **`min_trade_dollars`** (~$25) are skipped unless you must **fully exit** (target weight 0). |

**`orders_today.csv`** is simpler: only **BUY** and **SELL** deltas vs your **persisted live state** (`live_portfolio.json`) so you can line up with a broker.

### Cash vs margin (settlement)

| Mode | How to run | Effect |
|------|------------|--------|
| **T+0 (margin-style)** | Default; `SETTLE_DAYS` unset or `0` | Sell proceeds can fund **same-day** buys in the sim. |
| **T+1 cash (Reg T)** | `SETTLE_DAYS=1` | Sale proceeds sit in **unsettled** until the **next** trading day; buys can be **delayed or scaled** if settled cash is tight. |

The **backtest tab** can flip **T+0 / T+1** in the browser (both paths are precomputed). The **live** banner follows the mode used in the **last** run (`SETTLE_DAYS`).

**Examples:**

```powershell
# Windows PowerShell — cash account behaviour for the live sim
$env:SETTLE_DAYS = "1"
python scripts/run_daily.py
```

```bash
export SETTLE_DAYS=1
python scripts/run_daily.py
```

### Live portfolio start date

Until the model’s prediction date is **on or after** this day, the live state stays **all cash** (backtest still runs).

- Config: `live_portfolio_start` in **`pipeline/config.py`**, or  
- Env: **`LIVE_PORTFOLIO_START=YYYY-MM-DD`**

Example:

```powershell
$env:LIVE_PORTFOLIO_START = "2026-05-13"
python scripts/run_daily.py
```

State is stored in **`docs/data/live_portfolio.json`** (and history in **`live_portfolio_history.csv`**).

---

## How backtesting works

1. **Walk-forward RF** trains on older years, validates, steps forward (**`refit_every_days`** ≈ one year). That produces **out-of-sample** predictions for historical dates — **`preds_oos`** — used only where each prediction was truly known **before** the trade date.  
2. **`simulate_portfolio`** replays those **OOS** predictions day by day against **adjusted closes**: same targeting and settlement rules as above.  
3. The **`docs/index.html`** backtest pane reads **`daily_views.json`**: pick any date to see holdings, recommendations, fills, and PnL to the **next** close.

So the equity curve is **not** “fit on full history then pretend we knew”; it’s **frozen walk-forward simulated performance** plus today’s fresh full-history fit only for **tomorrow’s** ranks and orders.

Limit sell overlays in the **table** are **reference only** — the simulator rotation is driven by **next-day rankings / exits**, not by those limit prices.

---

## Universe and optional “hot” names

| Piece | Details |
|-------|---------|
| **Core list** | Default **`UNIVERSE=tw`**: **`pipeline/taiwan50_constituents.csv`** (`.TW` symbols) + **`0050.TW`** benchmark. Use **`UNIVERSE=sp500`** for the bundled S&P CSV, or **`UNIVERSE=core`** for the US mega-cap sleeve. |
| **Smaller sleeve** | **`UNIVERSE=core`** — fixed **~60** US names in **`pipeline/universe.py`**. **`UNIVERSE=sp500`** uses **`pipeline/sp500_constituents.csv`**. |
| **Refresh S&P names** | `python scripts/refresh_sp500.py` |
| **Hot watchlist** | If **`enable_hot_stocks`** is on, a momentum/volume screen can add up to **`hot_max_to_add`** extra tickers **for that run only** (see **`pipeline/hotstocks.py`**). |

---

## Configuration reference

Edit **`pipeline/config.py`** (or override with environment variables where noted):

- **`long_n` / `short_n`** — basket size; default is **5 long**, **0 short** (long-only).  
- **`cost_bps_per_side`** — model / panel cost; the live sim in `run_daily.py` uses **`0` bps** (treat as manual, zero-commission execution).  
- **`starting_capital`** — default **100,000** (same units as your prices, e.g. **NTD** for `.TW`). Override with **`STARTING_CAPITAL`** (env or GitHub Actions variable **`STARTING_CAPITAL`**).  
- **`currency_prefix`** — default **`NT$`** for labels in **`docs/index.html`**.  
- **`indices`** / **`benchmark`** — default **`0050.TW`** (Yuanta Taiwan 50 ETF): same trading calendar as Taiwan listings for excess returns and realised **`actual_xret`**. For a US-only universe, set **`benchmark`** to **`SPY`** (or similar) and include that ticker in **`indices`** in **`pipeline/config.py`**.  
- **`enable_hot_stocks`** — off by default (avoids scanning the US-heavy watchlist). Turn on in **`pipeline/config.py`** if you add a Taiwan-only watchlist later.  
- **`live_portfolio_start`** — when the persisted live book starts trading.  

---

## Project layout

```
scripts/run_daily.py       # Main entry: download → features → model → portfolio → site
pipeline/config.py         # Defaults and knobs
pipeline/taiwan50_constituents.csv   # Default Taiwan universe (edit / replace)
pipeline/sp500_constituents.csv      # Used when UNIVERSE=sp500
pipeline/universe.py       # Universe loaders (tw / sp500 / core)
pipeline/features.py       # Signals + cross-sectional ranks
pipeline/model.py          # Walk-forward + full-history fit
pipeline/portfolio.py      # Simulation, orders, daily_views
pipeline/report.py         # HTML report
docs/                      # GitHub Pages output (generated)
```

---

## GitHub contributors

**Insights → Contributors** uses **commit author email**. Set your identity before committing:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

Scheduled doc updates from Actions use the **`github-actions[bot]`** identity — that’s normal.
