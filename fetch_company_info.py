"""
Fetches company summaries via yfinance for newly added holdings.
Only fetches symbols not already cached in company_info, or stale (>30 days old).
"""

from datetime import date, timedelta

import yfinance as yf

from db import get_company_info, get_conn, init_db, upsert_company_info

STALE_DAYS = 30


def _needs_fetch(symbol: str, cached: dict[str, dict]) -> bool:
    if symbol not in cached:
        return True
    entry = cached[symbol]
    # Re-fetch if summary is blank (previous lookup failed silently)
    if not entry.get("summary"):
        return True
    fetched = entry.get("fetched_date")
    if not fetched:
        return True
    try:
        age = (date.today() - date.fromisoformat(fetched)).days
        return age > STALE_DAYS
    except ValueError:
        return True


def fetch_symbols(symbols: list[str]) -> list[dict]:
    if not symbols:
        return []

    cached = get_company_info(symbols)
    to_fetch = [s for s in symbols if _needs_fetch(s, cached)]

    if not to_fetch:
        print(f"  company_info: all {len(symbols)} symbol(s) already cached")
        return []

    from ticker_resolver import normalize
    print(f"  company_info: fetching {len(to_fetch)} symbol(s): {', '.join(to_fetch)}")

    rows = []
    today = date.today().strftime("%Y-%m-%d")

    for symbol in to_fetch:
        yf_ticker = normalize(symbol)
        try:
            info = yf.Ticker(yf_ticker).info
            summary = info.get("longBusinessSummary", "")
            rows.append({
                "symbol":       symbol,
                "long_name":    info.get("longName") or info.get("shortName", ""),
                "sector":       info.get("sector", ""),
                "industry":     info.get("industry", ""),
                "market_cap":   info.get("marketCap"),
                "summary":      summary,
                "website":      info.get("website", ""),
                "fetched_date": today,
            })
            label = f"{symbol}" + (f" -> {yf_ticker}" if yf_ticker != symbol else "")
            sector = info.get('sector', 'N/A') or 'N/A'
            print(f"    {label}: {sector}")
        except Exception as e:
            print(f"    {symbol} (yf: {yf_ticker}): failed - {e}")

    return rows


def run_for_new_additions(date_str: str | None = None):
    """Fetch company info for all 'added' changes on a given date (defaults to today)."""
    init_db()
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")

    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT symbol FROM holdings_changes
        WHERE date = ? AND change_type = 'added'
    """, (date_str,)).fetchall()
    conn.close()

    symbols = [r["symbol"] for r in rows]
    if not symbols:
        print("  company_info: no new additions today")
        return

    info_rows = fetch_symbols(symbols)
    if info_rows:
        upsert_company_info(info_rows)
        print(f"  company_info: saved {len(info_rows)} record(s)")


def run_for_all_current_holdings():
    """Fetch company info for every symbol in the latest holdings snapshot."""
    init_db()
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT h.symbol FROM holdings h
        INNER JOIN (
            SELECT fund, MAX(date) AS max_date FROM holdings GROUP BY fund
        ) latest ON h.fund = latest.fund AND h.date = latest.max_date
        WHERE h.symbol NOT LIKE '__edgar__%' AND h.symbol != ''
    """).fetchall()
    conn.close()

    symbols = [r["symbol"] for r in rows]
    print(f"  company_info: backfilling {len(symbols)} current holding symbols …")
    info_rows = fetch_symbols(symbols)
    if info_rows:
        upsert_company_info(info_rows)
        print(f"  company_info: saved {len(info_rows)} record(s)")
    else:
        print("  company_info: all already cached")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        run_for_all_current_holdings()
    else:
        d = sys.argv[1] if len(sys.argv) > 1 else None
        run_for_new_additions(d)
