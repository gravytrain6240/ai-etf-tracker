"""
REX Shares holdings scraper — covers AIPI.
REX Shares publishes holdings as an HTML table on the fund page.
"""

from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

FUND_PAGE = "https://www.rexshares.com/aipi/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; etf-tracker/1.0)"}


def fetch(fund: str = "AIPI") -> list[dict]:
    resp = requests.get(FUND_PAGE, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try to find a holdings CSV download link first
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "holdings" in href.lower() and href.endswith(".csv"):
            csv_url = href if href.startswith("http") else f"https://www.rexshares.com{href}"
            import io
            csv_resp = requests.get(csv_url, headers=HEADERS, timeout=30)
            csv_resp.raise_for_status()
            df = pd.read_csv(io.StringIO(csv_resp.text))
            return _parse_df(df, fund)

    # Fall back to HTML table
    tables = pd.read_html(resp.text)
    if not tables:
        raise ValueError("No holdings table found on REX Shares AIPI page")

    # Pick the table with the most rows that looks like a holdings table
    df = max(tables, key=len)
    return _parse_df(df, fund)


def _parse_df(df: pd.DataFrame, fund: str) -> list[dict]:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    today = date.today().strftime("%Y-%m-%d")
    rows = []

    for _, r in df.iterrows():
        symbol = str(r.get("ticker", r.get("symbol", ""))).strip()
        if not symbol or symbol in ("-", "nan", ""):
            continue

        try:
            weight = float(str(r.get("weight", r.get("weight_(%)", r.get("% of_portfolio", 0)))).replace("%", "").replace(",", ""))
        except (ValueError, TypeError):
            weight = None

        try:
            market_value = float(str(r.get("market_value", r.get("value", 0))).replace(",", ""))
        except (ValueError, TypeError):
            market_value = None

        try:
            shares = float(str(r.get("shares", r.get("quantity", 0))).replace(",", ""))
        except (ValueError, TypeError):
            shares = None

        rows.append({
            "date":         today,
            "fund":         fund,
            "symbol":       symbol,
            "name":         str(r.get("name", r.get("security_name", r.get("holding_name", "")))).strip(),
            "weight":       weight,
            "shares":       shares,
            "market_value": market_value,
        })

    return rows
