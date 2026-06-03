"""
Fetches daily holdings for all ETFs and writes to SQLite.
Primary source: stockanalysis.com (reliable, uniform format for all funds).
Official fund-site scrapers are available in scrapers/ for manual runs or future enrichment.
"""

from config import TICKERS
from db import init_db, upsert_holdings
from scrapers.stockanalysis import fetch


def run():
    init_db()
    for fund in TICKERS:
        try:
            rows = fetch(fund)
            if rows:
                upsert_holdings(rows)
                print(f"  {fund}: {len(rows)} holdings")
            else:
                print(f"  {fund}: WARNING — 0 rows returned")
        except Exception as e:
            print(f"  {fund}: ERROR — {e}")


if __name__ == "__main__":
    run()
