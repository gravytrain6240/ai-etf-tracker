"""
Compares today's holdings snapshot against the previous trading day's snapshot
and writes flagged changes to holdings_changes.
"""

from datetime import date

from config import TICKERS as FUNDS, WEIGHT_CHANGE_THRESHOLD
from db import get_conn, get_changes, upsert_changes


def _get_two_latest_dates(fund: str) -> tuple[str | None, str | None]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT date FROM holdings
        WHERE fund = ?
        ORDER BY date DESC
        LIMIT 2
    """, (fund,)).fetchall()
    conn.close()
    dates = [r["date"] for r in rows]
    if len(dates) == 2:
        return dates[0], dates[1]   # (today, yesterday)
    if len(dates) == 1:
        return dates[0], None
    return None, None


def _load_holdings_map(date_str: str, fund: str) -> dict[str, dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM holdings WHERE date = ? AND fund = ?
    """, (date_str, fund)).fetchall()
    conn.close()
    return {r["symbol"]: dict(r) for r in rows}


def diff_fund(fund: str, today: str) -> list[dict]:
    today_date, prev_date = _get_two_latest_dates(fund)

    if today_date != today:
        # No data for today yet
        return []
    if prev_date is None:
        # First day — nothing to compare
        return []

    curr = _load_holdings_map(today_date, fund)
    prev = _load_holdings_map(prev_date, fund)

    changes = []
    all_symbols = set(curr) | set(prev)

    for symbol in all_symbols:
        in_curr = symbol in curr
        in_prev = symbol in prev

        curr_weight = curr[symbol]["weight"] if in_curr else None
        prev_weight = prev[symbol]["weight"] if in_prev else None
        name = (curr.get(symbol) or prev.get(symbol) or {}).get("name", "")

        if in_curr and not in_prev:
            changes.append({
                "date":         today,
                "fund":         fund,
                "symbol":       symbol,
                "name":         name,
                "change_type":  "added",
                "weight_prev":  None,
                "weight_curr":  curr_weight,
                "weight_delta": curr_weight,
            })

        elif in_prev and not in_curr:
            changes.append({
                "date":         today,
                "fund":         fund,
                "symbol":       symbol,
                "name":         name,
                "change_type":  "removed",
                "weight_prev":  prev_weight,
                "weight_curr":  None,
                "weight_delta": -(prev_weight or 0),
            })

        elif in_curr and in_prev and curr_weight is not None and prev_weight is not None:
            delta = curr_weight - prev_weight
            if abs(delta) >= WEIGHT_CHANGE_THRESHOLD:
                changes.append({
                    "date":         today,
                    "fund":         fund,
                    "symbol":       symbol,
                    "name":         name,
                    "change_type":  "added_to" if delta > 0 else "trimmed",
                    "weight_prev":  prev_weight,
                    "weight_curr":  curr_weight,
                    "weight_delta": round(delta, 4),
                })

    return changes


def run():
    today = date.today().strftime("%Y-%m-%d")
    all_changes = []
    for fund in FUNDS:
        changes = diff_fund(fund, today)
        all_changes.extend(changes)
        if changes:
            print(f"  {fund}: {len(changes)} change(s) flagged")
        else:
            print(f"  {fund}: no significant changes")

    if all_changes:
        upsert_changes(all_changes)

    return all_changes


if __name__ == "__main__":
    run()
