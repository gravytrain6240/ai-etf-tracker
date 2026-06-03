"""
Resolves stockanalysis.com ticker formats to yfinance-compatible tickers.

Strategy:
  1. If already a plain US ticker — use as-is.
  2. If a known exchange prefix (KRX:, HKG:, etc.) — convert to yfinance suffix format.
  3. If dot-suffix foreign format (9984.JP) — remap to yfinance suffix.
  4. If conversion still yields no data — search Yahoo Finance for a US ADR/OTC.

Results are cached in SQLite so lookups only happen once per symbol.
"""

import re
import time
from functools import lru_cache

import yfinance as yf

from db import get_conn

# ── Exchange prefix → yfinance suffix ─────────────────────────────────────────

PREFIX_MAP = {
    "KRX":  ".KS",   # Korea Exchange
    "HKG":  ".HK",   # Hong Kong
    "EPA":  ".PA",   # Euronext Paris
    "ETR":  ".DE",   # XETRA Germany
    "LON":  ".L",    # London
    "TLV":  ".TA",   # Tel Aviv
    "TPE":  ".TW",   # Taiwan
    "TYO":  ".T",    # Tokyo
    "ASX":  ".AX",   # Australia
    "TSX":  ".TO",   # Toronto
    "AMS":  ".AS",   # Amsterdam
    "STO":  ".ST",   # Stockholm
    "SWX":  ".SW",   # Switzerland
    "BOM":  ".BO",   # Bombay / BSE India
    "NSE":  ".NS",   # National Stock Exchange India
}

# Dot-suffix remaps (stockanalysis → yfinance)
DOT_SUFFIX_MAP = {
    "JP": "T",    # 9984.JP  → 9984.T
    "TT": "TW",   # 2330.TT  → 2330.TW
}


def _init_cache_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_cache (
            symbol       TEXT PRIMARY KEY,
            yf_ticker    TEXT,
            is_adr       INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


_init_cache_table()


def _get_cached(symbol: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT yf_ticker FROM ticker_cache WHERE symbol=?", (symbol,)
    ).fetchone()
    conn.close()
    return row["yf_ticker"] if row else None


def _set_cached(symbol: str, yf_ticker: str, is_adr: bool = False):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO ticker_cache (symbol, yf_ticker, is_adr) VALUES (?,?,?)",
        (symbol, yf_ticker, int(is_adr)),
    )
    conn.commit()
    conn.close()


def _has_data(ticker: str) -> bool:
    """Quick check: does yfinance return price data for this ticker?"""
    try:
        df = yf.download(ticker, period="5d", progress=False, auto_adjust=True)
        return not df.empty and df["Close"].dropna().shape[0] > 0
    except Exception:
        return False


def _search_us_adr(company_name: str) -> str | None:
    """Search Yahoo Finance for a US-listed ADR or OTC for the company."""
    try:
        results = yf.Search(company_name, max_results=8, enable_fuzzy_query=True)
        quotes = results.quotes if hasattr(results, "quotes") else []
        us_exchanges = {"NYQ", "NMS", "PCX", "NGM", "OTC", "PNK", "PINK"}
        for q in quotes:
            exch = q.get("exchange", "")
            sym  = q.get("symbol", "")
            if exch in us_exchanges and sym and "." not in sym:
                return sym
    except Exception:
        pass
    return None


def normalize(symbol: str) -> str:
    """
    Convert a stockanalysis.com symbol to a yfinance ticker.
    Returns the original symbol unchanged if it's already a standard US ticker.
    Skips EDGAR placeholders.
    """
    if not symbol or symbol.startswith("__edgar__"):
        return symbol

    cached = _get_cached(symbol)
    if cached is not None:
        return cached

    result = _resolve(symbol)
    _set_cached(symbol, result, is_adr=(result != symbol and "." not in result))
    return result


def _resolve(symbol: str) -> str:
    s = symbol.strip()

    # Already a clean US ticker (letters only, or with . like BRK.B)
    if re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', s):
        return s

    # Exchange prefix format: "KRX: 000660"
    m = re.match(r'^([A-Z]+):\s*(.+)$', s)
    if m:
        prefix, local = m.group(1), m.group(2).strip()
        if prefix in PREFIX_MAP:
            converted = local + PREFIX_MAP[prefix]
            if _has_data(converted):
                return converted

        # Prefix known but data not found — try US ADR by company name
        adr = _search_us_adr(local)
        if adr and _has_data(adr):
            return adr

        # Return converted anyway (best guess)
        if prefix in PREFIX_MAP:
            return local + PREFIX_MAP[prefix]
        return s

    # Dot-suffix format: "9984.JP" or "2330.TT"
    m2 = re.match(r'^(.+)\.([A-Z]{1,2})$', s)
    if m2:
        base, suffix = m2.group(1), m2.group(2)
        yf_suffix = DOT_SUFFIX_MAP.get(suffix, suffix)
        converted = f"{base}.{yf_suffix}"
        if _has_data(converted):
            return converted
        # Try ADR
        adr = _search_us_adr(base)
        if adr and _has_data(adr):
            return adr
        return converted

    return s


def normalize_batch(symbols: list[str]) -> dict[str, str]:
    """Resolve a list of symbols, returning {original: yf_ticker}."""
    result = {}
    for sym in symbols:
        if sym and not sym.startswith("__edgar__"):
            result[sym] = normalize(sym)
            time.sleep(0.05)  # light throttle for yfinance calls
    return result
