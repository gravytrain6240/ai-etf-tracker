"""
Detects consensus signals: stocks added to 2+ funds on the same day.
Also surfaces stocks that appear as 'added' across multiple funds within a rolling window.

Results are stored in consensus_alerts and surfaced on the dashboard.
"""

from datetime import date, timedelta

from db import get_conn, init_db


def init_consensus_table():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS consensus_alerts (
            date         TEXT NOT NULL,
            symbol       TEXT NOT NULL,
            name         TEXT,
            funds        TEXT NOT NULL,   -- comma-separated list of funds
            fund_count   INTEGER NOT NULL,
            change_type  TEXT NOT NULL,
            PRIMARY KEY (date, symbol, change_type)
        );
    """)
    conn.commit()
    conn.close()


def compute(target_date: str | None = None, window_days: int = 1) -> list[dict]:
    """
    Find symbols appearing as the same change_type in 2+ funds within window_days.
    window_days=1 means same-day only; >1 means rolling window ending on target_date.
    """
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    start_date = (date.fromisoformat(target_date) - timedelta(days=window_days - 1)).strftime("%Y-%m-%d")

    conn = get_conn()
    rows = conn.execute("""
        SELECT
            ? AS date,
            symbol,
            MAX(name) AS name,
            change_type,
            GROUP_CONCAT(DISTINCT fund ORDER BY fund) AS funds,
            COUNT(DISTINCT fund) AS fund_count
        FROM holdings_changes
        WHERE date BETWEEN ? AND ?
          AND change_type IN ('added', 'removed')
        GROUP BY symbol, change_type
        HAVING COUNT(DISTINCT fund) >= 2
        ORDER BY fund_count DESC, symbol
    """, (target_date, start_date, target_date)).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def upsert_alerts(alerts: list[dict]):
    if not alerts:
        return
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO consensus_alerts
            (date, symbol, name, funds, fund_count, change_type)
        VALUES
            (:date, :symbol, :name, :funds, :fund_count, :change_type)
    """, alerts)
    conn.commit()
    conn.close()


def get_alerts(n_days: int = 30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM consensus_alerts
        WHERE date >= date('now', ? || ' days')
        ORDER BY date DESC, fund_count DESC, symbol
    """, (f"-{n_days}",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def run(target_date: str | None = None):
    init_db()
    init_consensus_table()

    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    alerts = compute(target_date)
    if alerts:
        upsert_alerts(alerts)
        for a in alerts:
            tag = "CONSENSUS BUY" if a["change_type"] == "added" else "CONSENSUS SELL"
            print(f"  [{tag}] {a['symbol']} added to {a['fund_count']} funds: {a['funds']}")
    else:
        print("  No consensus signals today")

    return alerts


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    run(d)
