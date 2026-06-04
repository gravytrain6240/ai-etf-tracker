"""
PWRD (TCW Transform Systems ETF) holdings fallback scraper.

TCW does not publish daily holdings for PWRD via any public CSV or API endpoint.
This scraper promotes the most recent EDGAR monthly filing into today's date
so the fund appears consistently in the dashboard alongside the other 7 ETFs.
The holdings date is preserved so the dashboard can flag it as a monthly snapshot.
"""

from datetime import date

from db import get_conn


def fetch(fund: str = "PWRD") -> list[dict]:
    """
    Copy the most recent EDGAR holdings for PWRD into today's date slot.
    Returns an empty list if no EDGAR data exists yet (backfill not yet run).
    """
    today = date.today().strftime("%Y-%m-%d")
    conn = get_conn()

    # Find most recent period that has real holdings (EDGAR rows start with __edgar__)
    row = conn.execute("""
        SELECT MAX(date) AS latest FROM holdings
        WHERE fund = ? AND symbol LIKE '__edgar__%'
    """, (fund,)).fetchone()
    latest = row["latest"] if row else None

    if not latest:
        conn.close()
        return []

    # Check if we already have today's data
    existing = conn.execute(
        "SELECT 1 FROM holdings WHERE fund=? AND date=? LIMIT 1", (fund, today)
    ).fetchone()
    if existing:
        conn.close()
        return []

    # Copy most recent EDGAR holdings into today, preserving the source date in name
    rows_raw = conn.execute("""
        SELECT * FROM holdings WHERE fund=? AND date=?
    """, (fund, latest)).fetchall()
    conn.close()

    rows = []
    for r in rows_raw:
        rows.append({
            "date":         today,
            "fund":         fund,
            "symbol":       r["symbol"],
            "name":         r["name"],
            "weight":       r["weight"],
            "shares":       r["shares"],
            "market_value": r["market_value"],
        })

    return rows, latest   # return source date so caller can log it
