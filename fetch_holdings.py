"""
Fetches daily holdings for all ETFs and writes to SQLite.
Primary source: stockanalysis.com (reliable, uniform format for most funds).
PWRD exception: uses TCW's Vercel blob CSV (daily, official source).
"""

from config import TICKERS
from db import init_db, upsert_holdings
from scrapers.stockanalysis import fetch as fetch_stockanalysis
from scrapers.tcw_pwrd import fetch as fetch_pwrd

CUSTOM_SCRAPERS = {
    "PWRD": fetch_pwrd,
}


def run():
    init_db()
    for fund in TICKERS:
        try:
            scraper = CUSTOM_SCRAPERS.get(fund, lambda: fetch_stockanalysis(fund))
            rows = scraper()
            if rows:
                upsert_holdings(rows)
                print(f"  {fund}: {len(rows)} holdings")
            else:
                print(f"  {fund}: WARNING — 0 rows returned")
        except Exception as e:
            print(f"  {fund}: ERROR — {e}")


if __name__ == "__main__":
    run()
