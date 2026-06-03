"""
StockAnalysis.com holdings scraper — reliable fallback for all funds.
Used as the primary source for funds whose official sites block direct scraping.
"""

import io
from datetime import date

import pandas as pd
import requests

BASE_URL = "https://stockanalysis.com/etf/{ticker}/holdings/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


def fetch(fund: str) -> list[dict]:
    url = BASE_URL.format(ticker=fund.lower())
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    tables = pd.read_html(io.StringIO(resp.text))
    if not tables:
        raise ValueError(f"No tables found on stockanalysis.com for {fund}")

    # Pick the largest table — it's the holdings table
    df = max(tables, key=len)
    df.columns = [c.strip().lower().replace(" ", "_").replace("%_", "") for c in df.columns]

    today = date.today().strftime("%Y-%m-%d")
    rows = []

    for _, r in df.iterrows():
        symbol = str(r.get("symbol", r.get("ticker", ""))).strip()
        if not symbol or symbol in ("-", "nan", ""):
            continue

        try:
            weight = float(str(r.get("weight", r.get("weight_(%)", r.get("_weight", 0)))).replace("%", "").replace(",", ""))
        except (ValueError, TypeError):
            weight = None

        try:
            shares = float(str(r.get("shares", 0)).replace(",", ""))
        except (ValueError, TypeError):
            shares = None

        try:
            market_value = float(str(r.get("market_value", r.get("value", 0))).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            market_value = None

        rows.append({
            "date":         today,
            "fund":         fund,
            "symbol":       symbol,
            "name":         str(r.get("name", r.get("company", ""))).strip(),
            "weight":       weight,
            "shares":       shares,
            "market_value": market_value,
        })

    return rows
