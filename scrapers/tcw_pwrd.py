"""
PWRD (TCW Transform Systems ETF) holdings scraper.
TCW publishes a daily holdings CSV via Vercel blob storage.
"""

import io
from datetime import date

import pandas as pd
import requests

HOLDINGS_URL = "https://mz8ltx6wqoefgvkh.public.blob.vercel-storage.com/data/portfolio/holdings/PWRD_hold.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; etf-tracker/1.0)"}


def fetch(fund: str = "PWRD") -> list[dict]:
    resp = requests.get(HOLDINGS_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text))

    today = date.today().strftime("%Y-%m-%d")
    rows = []
    for _, r in df.iterrows():
        symbol = str(r.get("Ticker", "")).strip()
        if not symbol or symbol in ("-", "nan", ""):
            continue

        try:
            weight_raw = str(r.get("Market Value Weight", "")).replace("%", "").strip()
            weight = float(weight_raw)
        except (ValueError, TypeError):
            weight = None

        try:
            shares = float(r.get("Shares", 0))
        except (ValueError, TypeError):
            shares = None

        try:
            market_value = float(r.get("Market Value", 0))
        except (ValueError, TypeError):
            market_value = None

        rows.append({
            "date":         today,
            "fund":         fund,
            "symbol":       symbol,
            "name":         str(r.get("Description", "")).strip().title(),
            "weight":       weight,
            "shares":       shares,
            "market_value": market_value,
        })

    return rows
