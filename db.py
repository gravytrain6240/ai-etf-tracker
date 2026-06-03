import sqlite3
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            date        TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            adj_close   REAL,
            volume      INTEGER,
            nav_return  REAL,   -- daily % return based on adj_close
            PRIMARY KEY (date, ticker)
        );

        CREATE TABLE IF NOT EXISTS holdings (
            date          TEXT NOT NULL,
            fund          TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            name          TEXT,
            weight        REAL,   -- % of portfolio
            shares        REAL,
            market_value  REAL,
            PRIMARY KEY (date, fund, symbol)
        );

        CREATE TABLE IF NOT EXISTS holdings_changes (
            date          TEXT NOT NULL,
            fund          TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            name          TEXT,
            change_type   TEXT NOT NULL,  -- 'added', 'removed', 'trimmed', 'added_to'
            weight_prev   REAL,
            weight_curr   REAL,
            weight_delta  REAL,
            PRIMARY KEY (date, fund, symbol)
        );

        CREATE TABLE IF NOT EXISTS company_info (
            symbol        TEXT PRIMARY KEY,
            long_name     TEXT,
            sector        TEXT,
            industry      TEXT,
            market_cap    INTEGER,
            summary       TEXT,
            website       TEXT,
            fetched_date  TEXT
        );
    """)

    conn.commit()
    conn.close()


def upsert_prices(rows: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO daily_prices
            (date, ticker, open, high, low, close, adj_close, volume, nav_return)
        VALUES
            (:date, :ticker, :open, :high, :low, :close, :adj_close, :volume, :nav_return)
    """, rows)
    conn.commit()
    conn.close()


def upsert_holdings(rows: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO holdings
            (date, fund, symbol, name, weight, shares, market_value)
        VALUES
            (:date, :fund, :symbol, :name, :weight, :shares, :market_value)
    """, rows)
    conn.commit()
    conn.close()


def upsert_changes(rows: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO holdings_changes
            (date, fund, symbol, name, change_type, weight_prev, weight_curr, weight_delta)
        VALUES
            (:date, :fund, :symbol, :name, :change_type, :weight_prev, :weight_curr, :weight_delta)
    """, rows)
    conn.commit()
    conn.close()


def get_latest_prices(n_days: int = 30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM daily_prices
        WHERE date >= date('now', ? || ' days')
        ORDER BY date DESC, ticker
    """, (f"-{n_days}",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_holdings(date: str, fund: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM holdings WHERE date = ? AND fund = ?
        ORDER BY weight DESC
    """, (date, fund)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_holdings_date(fund: str) -> str | None:
    conn = get_conn()
    row = conn.execute("""
        SELECT MAX(date) AS d FROM holdings WHERE fund = ?
    """, (fund,)).fetchone()
    conn.close()
    return row["d"] if row else None


def upsert_company_info(rows: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO company_info
            (symbol, long_name, sector, industry, market_cap, summary, website, fetched_date)
        VALUES
            (:symbol, :long_name, :sector, :industry, :market_cap, :summary, :website, :fetched_date)
    """, rows)
    conn.commit()
    conn.close()


def get_company_info(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"SELECT * FROM company_info WHERE symbol IN ({placeholders})", symbols
    ).fetchall()
    conn.close()
    return {r["symbol"]: dict(r) for r in rows}


def get_changes(date: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM holdings_changes WHERE date = ?
        ORDER BY fund, change_type, ABS(weight_delta) DESC
    """, (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
