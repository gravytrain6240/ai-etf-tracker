"""
Fetches daily holdings for all ETFs and writes to SQLite.
Primary source: stockanalysis.com (reliable, uniform format for all funds).
PWRD exception: TCW does not publish daily holdings publicly; uses most recent
EDGAR monthly filing as a proxy (promoted to today's date).
"""

from config import TICKERS
from db import init_db, upsert_holdings
from scrapers.stockanalysis import fetch as fetch_stockanalysis
from scrapers.tcw_pwrd import fetch as fetch_pwrd

# Funds that are not on stockanalysis.com and need a dedicated scraper
CUSTOM_SCRAPERS = {
    "PWRD": fetch_pwrd,
}


def run():
    init_db()
    for fund in TICKERS:
        try:
            if fund in CUSTOM_SCRAPERS:
                result = CUSTOM_SCRAPERS[fund]()
                if isinstance(result, tuple):
                    rows, source_date = result
                    if rows:
                        upsert_holdings(rows)
                        print(f"  {fund}: {len(rows)} holdings (EDGAR snapshot from {source_date})")
                    else:
                        print(f"  {fund}: WARNING — no EDGAR data yet, run backfill_holdings.py first")
                else:
                    rows = result or []
                    if rows:
                        upsert_holdings(rows)
                        print(f"  {fund}: {len(rows)} holdings")
                    else:
                        print(f"  {fund}: WARNING — 0 rows returned")
            else:
                rows = fetch_stockanalysis(fund)
                if rows:
                    upsert_holdings(rows)
                    print(f"  {fund}: {len(rows)} holdings")
                else:
                    print(f"  {fund}: WARNING — 0 rows returned")
        except Exception as e:
            print(f"  {fund}: ERROR — {e}")


if __name__ == "__main__":
    run()
