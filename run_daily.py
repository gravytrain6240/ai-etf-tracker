"""
Cron entry point. Run this nightly after market close (~7pm ET).

Example crontab:
  0 19 * * 1-5  /usr/bin/python3 /path/to/ai-etf-tracker/run_daily.py >> /path/to/logs/etf.log 2>&1
"""

import sys
from datetime import datetime

from fetch_returns import run as fetch_returns
from fetch_holdings import run as fetch_holdings
from diff_holdings import run as diff_holdings
from fetch_company_info import run_for_new_additions
from consensus_alerts import run as run_consensus


def main():
    print(f"\n{'='*50}")
    print(f"AI ETF Tracker — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    print("\n[1/5] Fetching daily prices …")
    fetch_returns()

    print("\n[2/5] Fetching fund holdings …")
    fetch_holdings()

    print("\n[3/5] Computing holdings changes …")
    changes = diff_holdings()

    print("\n[4/5] Fetching company summaries for new additions …")
    run_for_new_additions()

    print("\n[5/5] Checking for consensus signals …")
    run_consensus()

    print(f"\nDone. {len(changes)} total holding change(s) recorded today.")


if __name__ == "__main__":
    main()
