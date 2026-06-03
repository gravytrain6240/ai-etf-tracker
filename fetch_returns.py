"""
Fetches daily EOD prices for all ETFs via yfinance and writes to SQLite.
Pulls the last 2 days by default (enough to compute today's return).
Pass --backfill to pull 1 year of history on first run.
"""

import argparse
from datetime import date, timedelta

import yfinance as yf

from config import TICKERS
from db import init_db, upsert_prices


def fetch(start: str, end: str) -> list[dict]:
    raw = yf.download(
        tickers=TICKERS,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
    )

    rows = []
    for ticker in TICKERS:
        try:
            df = raw[ticker].dropna(how="all")
        except KeyError:
            print(f"  WARNING: no data returned for {ticker}")
            continue

        prev_adj = None
        for dt, row in df.iterrows():
            adj = row.get("Adj Close")
            nav_return = None
            if prev_adj and prev_adj != 0 and adj:
                nav_return = round((adj / prev_adj - 1) * 100, 4)
            prev_adj = adj

            rows.append({
                "date":      dt.strftime("%Y-%m-%d"),
                "ticker":    ticker,
                "open":      round(float(row["Open"]), 4)      if row.get("Open")      else None,
                "high":      round(float(row["High"]), 4)      if row.get("High")      else None,
                "low":       round(float(row["Low"]), 4)       if row.get("Low")       else None,
                "close":     round(float(row["Close"]), 4)     if row.get("Close")     else None,
                "adj_close": round(float(adj), 4)              if adj                  else None,
                "volume":    int(row["Volume"])                 if row.get("Volume")    else None,
                "nav_return": nav_return,
            })

    return rows


def run(backfill: bool = False):
    init_db()
    today = date.today()

    if backfill:
        start = (today - timedelta(days=365)).strftime("%Y-%m-%d")
        print(f"Backfilling prices from {start} …")
    else:
        # Fetch last 5 calendar days to ensure we catch the most recent trading day
        start = (today - timedelta(days=5)).strftime("%Y-%m-%d")

    end = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    rows = fetch(start, end)
    if rows:
        upsert_prices(rows)
        print(f"  Saved {len(rows)} price rows ({len(TICKERS)} tickers)")
    else:
        print("  No price data returned.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="Pull 1 year of history")
    args = parser.parse_args()
    run(backfill=args.backfill)
