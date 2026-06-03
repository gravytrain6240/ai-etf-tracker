"""
DWS / Xtrackers holdings scraper — covers XAIX.
"""

import io
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

FUND_PAGE = "https://etf.dws.com/en-us/XAIX-artificial-intelligence-and-big-data-etf/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; etf-tracker/1.0)"}


def fetch(fund: str = "XAIX") -> list[dict]:
    resp = requests.get(FUND_PAGE, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for a holdings CSV/Excel download link
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "holding" in href.lower() and (href.endswith(".csv") or href.endswith(".xlsx")):
            file_url = href if href.startswith("http") else f"https://etf.dws.com{href}"
            file_resp = requests.get(file_url, headers=HEADERS, timeout=30)
            file_resp.raise_for_status()
            if href.endswith(".xlsx"):
                df = pd.read_excel(io.BytesIO(file_resp.content))
            else:
                df = pd.read_csv(io.StringIO(file_resp.text))
            return _parse_df(df, fund)

    # Fall back to HTML table
    tables = pd.read_html(resp.text)
    if not tables:
        raise ValueError("No holdings data found on DWS XAIX page")

    df = max(tables, key=len)
    return _parse_df(df, fund)


def _parse_df(df: pd.DataFrame, fund: str) -> list[dict]:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    today = date.today().strftime("%Y-%m-%d")
    rows = []

    for _, r in df.iterrows():
        symbol = str(r.get("ticker", r.get("sedol", r.get("isin", "")))).strip()
        if not symbol or symbol in ("-", "nan", ""):
            continue

        try:
            weight = float(str(r.get("weight_(%)", r.get("weight", r.get("index_weight", 0)))).replace("%", "").replace(",", ""))
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
            "name":         str(r.get("name", r.get("security_name", r.get("component", "")))).strip(),
            "weight":       weight,
            "shares":       shares,
            "market_value": market_value,
        })

    return rows
