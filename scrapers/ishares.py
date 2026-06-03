"""
iShares (BlackRock) holdings scraper — covers BAI and ARTY.
iShares publishes a daily holdings CSV at a predictable URL.
"""

import io
from datetime import date

import pandas as pd
import requests

from config import ISHARES_PRODUCT_IDS

BASE_URL = "https://www.ishares.com/us/products/{product_id}/{slug}/1467271812596.ajax"
PARAMS = {
    "fileType": "csv",
    "dataType": "fund",
}

SLUG_MAP = {
    "BAI":  "ishares-a-i-innovation-and-tech-active-etf",
    "ARTY": "ishares-future-ai-tech-etf",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; etf-tracker/1.0)",
}


def fetch(fund: str) -> list[dict]:
    product_id = ISHARES_PRODUCT_IDS[fund]
    slug = SLUG_MAP[fund]
    url = BASE_URL.format(product_id=product_id, slug=slug)

    resp = requests.get(url, params=PARAMS, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    # iShares CSV has metadata rows at the top before the actual header row.
    # We find the row that starts with "Ticker" or "Name" to locate the real header.
    lines = resp.text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("Ticker,") or line.startswith('"Ticker",')),
        None,
    )
    if header_idx is None:
        raise ValueError(f"Could not find header row in iShares CSV for {fund}")

    csv_body = "\n".join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(csv_body))
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    today = date.today().strftime("%Y-%m-%d")
    rows = []
    for _, r in df.iterrows():
        symbol = str(r.get("ticker", "")).strip()
        if not symbol or symbol in ("-", "nan", ""):
            continue

        weight_raw = r.get("weight_(%)", r.get("weight_(%)_of_fund", None))
        try:
            weight = float(str(weight_raw).replace(",", "").replace("%", ""))
        except (ValueError, TypeError):
            weight = None

        market_val_raw = r.get("market_value", None)
        try:
            market_value = float(str(market_val_raw).replace(",", ""))
        except (ValueError, TypeError):
            market_value = None

        shares_raw = r.get("shares", r.get("quantity", None))
        try:
            shares = float(str(shares_raw).replace(",", ""))
        except (ValueError, TypeError):
            shares = None

        rows.append({
            "date":         today,
            "fund":         fund,
            "symbol":       symbol,
            "name":         str(r.get("name", "")).strip(),
            "weight":       weight,
            "shares":       shares,
            "market_value": market_value,
        })

    return rows
