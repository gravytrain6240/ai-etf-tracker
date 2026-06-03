"""
Roundhill Investments holdings scraper — covers CHAT.
Roundhill publishes a daily holdings CSV linked from the fund page.
"""

import io
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

FUND_PAGE = "https://www.roundhillinvestments.com/etf/chat/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; etf-tracker/1.0)"}


def _find_csv_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "holdings" in href.lower() and href.endswith(".csv"):
            return href if href.startswith("http") else f"https://www.roundhillinvestments.com{href}"
    return None


def fetch(fund: str = "CHAT") -> list[dict]:
    resp = requests.get(FUND_PAGE, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    csv_url = _find_csv_url(resp.text)
    if not csv_url:
        raise ValueError("Could not find holdings CSV link on Roundhill CHAT page")

    csv_resp = requests.get(csv_url, headers=HEADERS, timeout=30)
    csv_resp.raise_for_status()

    df = pd.read_csv(io.StringIO(csv_resp.text))
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    today = date.today().strftime("%Y-%m-%d")
    rows = []
    for _, r in df.iterrows():
        symbol = str(r.get("ticker", r.get("symbol", ""))).strip()
        if not symbol or symbol in ("-", "nan", ""):
            continue

        try:
            weight = float(str(r.get("weight", r.get("weight_(%)", 0))).replace("%", "").replace(",", ""))
        except (ValueError, TypeError):
            weight = None

        try:
            market_value = float(str(r.get("market_value", 0)).replace(",", ""))
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
            "name":         str(r.get("name", r.get("security_name", ""))).strip(),
            "weight":       weight,
            "shares":       shares,
            "market_value": market_value,
        })

    return rows
