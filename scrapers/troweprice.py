"""
T. Rowe Price holdings scraper — covers TSPA.
T. Rowe Price publishes a daily portfolio composition file (PCF) for semi-transparent ETFs.
"""

import io
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

FUND_PAGE = "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/equity-research-etf.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; etf-tracker/1.0)"}


def fetch(fund: str = "TSPA") -> list[dict]:
    resp = requests.get(FUND_PAGE, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "holding" in href.lower() and (href.endswith(".csv") or href.endswith(".xlsx")):
            file_url = href if href.startswith("http") else f"https://www.troweprice.com{href}"
            file_resp = requests.get(file_url, headers=HEADERS, timeout=30)
            file_resp.raise_for_status()
            if href.endswith(".xlsx"):
                df = pd.read_excel(io.BytesIO(file_resp.content))
            else:
                df = pd.read_csv(io.StringIO(file_resp.text))
            return _parse_df(df, fund)

    tables = pd.read_html(resp.text)
    if not tables:
        raise ValueError("No holdings data found on T. Rowe Price TSPA page")

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
            weight = float(str(r.get("weight", r.get("weight_(%)", r.get("% of_net_assets", 0)))).replace("%", "").replace(",", ""))
        except (ValueError, TypeError):
            weight = None

        try:
            market_value = float(str(r.get("market_value", r.get("fair_value", 0))).replace(",", ""))
        except (ValueError, TypeError):
            market_value = None

        try:
            shares = float(str(r.get("shares", r.get("quantity", r.get("number_of_shares", 0)))).replace(",", ""))
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
