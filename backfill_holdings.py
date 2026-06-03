"""
Backfills historical holdings from SEC EDGAR NPORT-EX filings (monthly, free).
Uses the EDGAR EFTS full-text search to locate each fund's specific filing,
then parses the HTML holdings table.

NPORT-P filings are submitted monthly, typically ~60 days after period end.
This gives us monthly snapshots going back 12+ months as a historical foundation;
the daily scraper builds forward from today.

Usage:
  python backfill_holdings.py              # all funds
  python backfill_holdings.py --fund ARTY  # single fund
"""

import argparse
import io
import re
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from config import TICKERS
from db import get_conn, init_db, upsert_holdings

NPORT_NS = "http://www.sec.gov/edgar/nport"

HEADERS = {"User-Agent": "etf-tracker contact@example.com"}
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_BASE = "https://www.sec.gov"

# (keyword, cik) per fund — CIK scopes search to the correct filer
FUND_EDGAR = {
    "ARTY": ("iShares Future AI",                          "0001100663"),  # iShares Trust
    "BAI":  ("A.I. Innovation and Tech Active",            "0001761055"),  # iShares Active ETF Trust
    "CHAT": ("Roundhill Generative AI",                    None),
    "AIPI": ("REX AI Equity Premium Income ETF",           "0001771146"),
    "XAIX": ("Xtrackers Artificial Intelligence and Big",  "0001503123"),
    "AIFD": ("TCW Artificial Intelligence ETF",            None),
    "TSPA": ("T. Rowe Price U.S. Equity Research ETF",      "0001795351"),
}


def search_edgar(keyword: str, cik_filter: str | None = None) -> list[dict]:
    """Find NPORT-EX filings for a fund using EFTS full-text search."""
    params = {
        "q":         f'"{keyword}"',
        "forms":     "NPORT-P",
        "dateRange": "custom",
        "startdt":   "2024-01-01",
    }
    if cik_filter:
        params["entity"] = cik_filter

    for attempt in range(3):
        r = requests.get(EFTS_URL, params=params, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            break
        wait = 5 * (attempt + 1)
        print(f"    EDGAR returned {r.status_code}, retrying in {wait}s ...")
        time.sleep(wait)
    r.raise_for_status()

    hits = r.json().get("hits", {}).get("hits", [])
    results = []
    for h in hits:
        src    = h["_source"]
        adsh   = src.get("adsh", "")
        fname  = h["_id"].split(":", 1)[1] if ":" in h["_id"] else ""
        period = src.get("period_ending", "")[:10]
        ciks   = src.get("ciks", [])

        if not (adsh and fname and period and ciks):
            continue

        # If we have a CIK filter, skip hits from other filers
        if cik_filter and cik_filter not in ciks and cik_filter.lstrip("0") not in [c.lstrip("0") for c in ciks]:
            continue

        cik = ciks[0].lstrip("0")
        acc = adsh.replace("-", "")
        results.append({
            "period": period,
            "url":    f"{SEC_BASE}/Archives/edgar/data/{cik}/{acc}/{fname}",
        })

    # Deduplicate by period (take first/best match per period)
    seen = {}
    for r in results:
        if r["period"] not in seen:
            seen[r["period"]] = r
    return list(seen.values())


def parse_nport_abs_div(html: str, period: str, fund: str) -> list[dict]:
    """
    Parse holdings from absolute-positioned div HTML (XAIX / DWS format).
    Extracts div text + top/left coords, groups into rows by Y position,
    then identifies name/shares/value columns by X position.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Collect (top, left, text) for all positioned divs with real text
    items = []
    for div in soup.find_all("div", style=True):
        style = div.get("style", "")
        top_m  = re.search(r"top:\s*([\d.]+)px", style)
        left_m = re.search(r"left:\s*([\d.]+)px", style)
        text   = div.get_text(strip=True)
        if top_m and left_m and text and len(text) > 1:
            items.append((float(top_m.group(1)), float(left_m.group(1)), text))

    if not items:
        return []

    # Sort by top then left
    items.sort(key=lambda x: (x[0], x[1]))

    # Group into rows (items within 30px of same top)
    rows_grouped = []
    cur_row, cur_top = [], None
    for top, left, text in items:
        if cur_top is None or abs(top - cur_top) > 30:
            if cur_row:
                rows_grouped.append(cur_row)
            cur_row  = [(left, text)]
            cur_top  = top
        else:
            cur_row.append((left, text))
    if cur_row:
        rows_grouped.append(cur_row)

    # Identify the header row to find column positions for Name/Shares/Value
    name_x = shares_x = value_x = None
    for row in rows_grouped[:30]:
        texts = [t.lower() for _, t in row]
        if any("shares" in t for t in texts) and any("value" in t for t in texts):
            for left, t in row:
                tl = t.lower()
                if "name" in tl or "security" in tl or "description" in tl:
                    name_x = left
                elif "shares" in tl:
                    shares_x = left
                elif "value" in tl:
                    value_x = left
            break

    if not shares_x or not value_x:
        # Heuristic: name=leftmost col, shares=2nd-to-last col, value=last col
        all_lefts = sorted(set(left for row in rows_grouped for left, _ in row))
        if len(all_lefts) >= 3:
            name_x   = all_lefts[0]
            shares_x = all_lefts[-2]
            value_x  = all_lefts[-1]

    def find_col(row_items, target_x, tolerance=200):
        candidates = [(abs(left - target_x), text) for left, text in row_items if target_x]
        if not candidates:
            return None
        best = min(candidates, key=lambda x: x[0])
        return best[1] if best[0] < tolerance else None

    holdings = []
    for row in rows_grouped:
        name_text = find_col(row, name_x)
        if not name_text or len(name_text) < 3:
            continue
        # Skip headers and section lines
        if re.search(r"(schedule|investment|portfolio|unaudited|name|security|shares|value|total|january|"
                     r"february|march|april|may|june|july|august|september|october|november|december)",
                     name_text, re.IGNORECASE) and len(name_text) < 50:
            continue

        shares_text = find_col(row, shares_x)
        value_text  = find_col(row, value_x)

        try:
            shares = float(re.sub(r"[^0-9.]", "", shares_text)) if shares_text else None
        except ValueError:
            shares = None
        try:
            mv = float(re.sub(r"[^0-9.]", "", value_text)) if value_text else None
        except ValueError:
            mv = None

        if shares is None and mv is None:
            continue

        holdings.append({
            "date": period, "fund": fund, "symbol": f"__edgar__{name_text[:60]}",
            "name": name_text, "weight": None,
            "shares": shares, "market_value": mv,
        })

    total_mv = sum(r["market_value"] for r in holdings if r["market_value"])
    if total_mv > 0:
        for r in holdings:
            if r["market_value"]:
                r["weight"] = round(r["market_value"] / total_mv * 100, 4)

    return holdings


def _parse_ncol_soi(df: pd.DataFrame, period: str, fund: str,
                    name_col: int, shares_col: int, val_col: int) -> list[dict]:
    """Generic N-column schedule-of-investments parser given column indices."""
    rows = []
    for _, r in df.iterrows():
        name_raw = str(r.iloc[name_col]).replace("​", "").strip()
        if not name_raw or name_raw in ("nan", "") or len(name_raw) < 3:
            continue
        if re.search(r"(common stock|preferred|total|schedule|unaudited|shares|value|"
                     r"options|written|january|february|march|april|may|june|july|august|"
                     r"september|october|november|december|communication|technology|"
                     r"consumer|industrial|financial|health|energy|utility|material|"
                     r"real estate)", name_raw, re.IGNORECASE) and len(name_raw) < 60:
            continue
        if re.match(r".*(—|\-|%)\s*\d", name_raw):
            continue

        def clean(v):
            return str(v).replace(",", "").replace("$", "").replace("​", "").strip()

        try:
            shares = float(clean(r.iloc[shares_col])) if clean(r.iloc[shares_col]) not in ("nan", "") else None
        except (ValueError, IndexError):
            shares = None
        try:
            mv = float(clean(r.iloc[val_col])) if clean(r.iloc[val_col]) not in ("nan", "") else None
        except (ValueError, IndexError):
            mv = None

        if shares is None and mv is None:
            continue

        rows.append({"date": period, "fund": fund, "symbol": f"__edgar__{name_raw[:60]}",
                     "name": name_raw, "weight": None, "shares": shares, "market_value": mv})

    total_mv = sum(r["market_value"] for r in rows if r["market_value"])
    if total_mv > 0:
        for r in rows:
            if r["market_value"]:
                r["weight"] = round(r["market_value"] / total_mv * 100, 4)
    return rows


def _parse_8col_soi(df: pd.DataFrame, period: str, fund: str) -> list[dict]:
    """8-col SOI (REX Shares AIPI, TSPA): col 2 = name, col 4 = shares, col 6 = value."""
    return _parse_ncol_soi(df, period, fund, name_col=2, shares_col=4, val_col=6)


def _parse_schedule_of_investments(df: pd.DataFrame, period: str, fund: str) -> list[dict]:
    """
    Parse the Roundhill / multi-column schedule-of-investments HTML format.
    Layout: col 0 = name, col 3 = shares, col 7 = market value (approx).
    """
    rows = []
    for _, r in df.iterrows():
        name_raw = str(r.iloc[0]).strip()
        if not name_raw or name_raw in ("nan", "") or len(name_raw) < 3:
            continue
        # Skip section headers / title rows
        if re.search(r"(schedule of investments|january|february|march|april|may|june|july|"
                     r"august|september|october|november|december|common stock|fund name|"
                     r"unaudited|ETF$)", name_raw, re.IGNORECASE):
            continue
        if re.match(r".*(—|\-)\s*\d+(\.\d+)?%", name_raw):
            continue

        # Shares in col 3, value in col 7 (or last non-null numeric)
        shares_raw = str(r.iloc[3]).replace(",", "").strip() if len(r) > 3 else ""
        val_raw    = str(r.iloc[7]).replace(",", "").replace("$", "").strip() if len(r) > 7 else ""

        try:
            shares = float(shares_raw) if shares_raw not in ("nan", "") else None
        except ValueError:
            shares = None
        try:
            market_value = float(val_raw) if val_raw not in ("nan", "") else None
        except ValueError:
            market_value = None

        if shares is None and market_value is None:
            continue

        rows.append({
            "date": period, "fund": fund, "symbol": f"__edgar__{name_raw[:60]}",
            "name": name_raw, "weight": None,
            "shares": shares, "market_value": market_value,
        })

    total_mv = sum(r["market_value"] for r in rows if r["market_value"])
    if total_mv > 0:
        for r in rows:
            if r["market_value"]:
                r["weight"] = round(r["market_value"] / total_mv * 100, 4)
    return rows


def parse_nport_html(html: str, period: str, fund: str) -> list[dict]:
    """Parse holdings rows from NPORT-EX HTML."""
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return []
    if not tables:
        return []

    # Find the holdings table: 3 columns where first row has Security / Shares / Value
    holdings_df = None
    for t in tables:
        if len(t.columns) < 2 or len(t) < 5:
            continue
        first_cell = str(t.iloc[0, 0]).strip().lower()
        if first_cell in ("security", "name", "description"):
            holdings_df = t
            break

    if holdings_df is None:
        # Try 9-col schedule-of-investments format (Roundhill)
        nine_col = [t for t in tables if len(t.columns) == 9 and len(t) > 10]
        if nine_col:
            result = _parse_schedule_of_investments(max(nine_col, key=len), period, fund)
            if result:
                return result

        # Try 12/13-col format (REX Shares AIPI semiannual - name col4, shares col7, val col11)
        for ncols in (13, 12):
            n_col = [t for t in tables if len(t.columns) == ncols and len(t) > 10]
            if n_col:
                result = _parse_ncol_soi(max(n_col, key=len), period, fund,
                                         name_col=4, shares_col=7, val_col=11)
                if result:
                    return result

        # Try 8-col format (REX Shares AIPI, TSPA)
        eight_col = [t for t in tables if len(t.columns) == 8 and len(t) > 10]
        if eight_col:
            result = _parse_8col_soi(max(eight_col, key=len), period, fund)
            if result:
                return result

        # Fall back: largest table with 3 cols
        candidates = [t for t in tables if len(t.columns) == 3 and len(t) > 10]
        if candidates:
            holdings_df = max(candidates, key=len)

    if holdings_df is None:
        return []

    rows = []
    for _, r in holdings_df.iterrows():
        name_raw = str(r.iloc[0]).strip()

        # Skip headers, section labels, footnotes, blanks
        if not name_raw or name_raw in ("Security", "Name", "Description", "nan"):
            continue
        if name_raw.startswith("(") or name_raw.startswith("*"):
            continue
        # Skip section headers like "United States — 85.4%" or "Common Stocks"
        if re.match(r"^[A-Z][a-z].*(—|—|–)\s*\d+\.\d+%", name_raw):
            continue
        if re.search(r"(common stock|preferred stock|continued|total)", name_raw, re.IGNORECASE) and len(name_raw) < 40:
            continue

        val_raw = str(r.iloc[-1]).replace(",", "").replace("$", "").strip() if len(r) > 1 else ""
        shares_raw = str(r.iloc[1]).replace(",", "").strip() if len(r) > 2 else ""

        try:
            market_value = float(val_raw)
        except ValueError:
            market_value = None

        try:
            shares = float(shares_raw)
        except ValueError:
            shares = None

        if market_value is None and shares is None:
            continue

        rows.append({
            "date":         period,
            "fund":         fund,
            "symbol":       f"__edgar__{name_raw[:60]}",
            "name":         name_raw,
            "weight":       None,
            "shares":       shares,
            "market_value": market_value,
        })

    # Compute weights from market values
    total_mv = sum(r["market_value"] for r in rows if r["market_value"])
    if total_mv > 0:
        for r in rows:
            if r["market_value"]:
                r["weight"] = round(r["market_value"] / total_mv * 100, 4)

    return rows


def parse_nport_xml(xml_text: str, period: str, fund: str) -> list[dict]:
    """Parse holdings from raw NPORT-P XML (used when HTML version not available)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    ns = NPORT_NS
    invests = root.findall(f".//{{{ns}}}invstOrSec")
    if not invests:
        return []

    rows = []
    for inv in invests:
        def txt(tag):
            el = inv.find(f"{{{ns}}}{tag}")
            return el.text.strip() if el is not None and el.text else ""

        name = txt("name") or txt("title")
        if not name:
            continue

        try:
            market_value = float(txt("valUSD")) if txt("valUSD") else None
        except ValueError:
            market_value = None

        try:
            shares = float(txt("balance")) if txt("balance") else None
        except ValueError:
            shares = None

        try:
            weight = float(txt("pctVal")) if txt("pctVal") else None
        except ValueError:
            weight = None

        rows.append({
            "date":         period,
            "fund":         fund,
            "symbol":       f"__edgar__{name[:60]}",
            "name":         name,
            "weight":       weight,
            "shares":       shares,
            "market_value": market_value,
        })

    return rows


def already_have(fund: str, period: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM holdings WHERE fund=? AND date=? LIMIT 1", (fund, period)
    ).fetchone()
    conn.close()
    return row is not None


def backfill_fund(fund: str) -> int:
    cfg = FUND_EDGAR.get(fund)
    if not cfg:
        print(f"  {fund}: no EDGAR config")
        return 0
    keyword, cik_filter = cfg

    print(f"  {fund}: searching EDGAR for '{keyword}' ...")
    try:
        filings = search_edgar(keyword, cik_filter)
    except Exception as e:
        print(f"  {fund}: EDGAR search failed — {e}")
        return 0

    if not filings:
        print(f"  {fund}: no NPORT-EX filings found")
        return 0

    saved = 0
    for filing in filings:
        period = filing["period"]
        url    = filing["url"]

        if already_have(fund, period):
            continue

        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()

            if url.endswith(".xml"):
                rows = parse_nport_xml(r.text, period, fund)
            else:
                rows = parse_nport_html(r.text, period, fund)
                if not rows:
                    # Try XML (some .htm files are actually XML)
                    rows = parse_nport_xml(r.text, period, fund)
                if not rows and "position:absolute" in r.text:
                    # Absolute-positioned div format (XAIX/DWS)
                    rows = parse_nport_abs_div(r.text, period, fund)

            if rows:
                upsert_holdings(rows)
                saved += len(rows)
                fmt = "XML" if url.endswith(".xml") else "HTML"
                print(f"    {fund} {period}: {len(rows)} holdings saved ({fmt})")
            else:
                print(f"    {fund} {period}: parsed 0 rows from {url}")

            time.sleep(0.4)

        except Exception as e:
            print(f"    {fund} {period}: ERROR — {e}")

    return saved


def run(funds: list[str] | None = None):
    init_db()
    funds = funds or TICKERS
    total = 0
    for i, fund in enumerate(funds):
        if i > 0:
            time.sleep(3)   # pause between funds to avoid EDGAR rate limits
        n = backfill_fund(fund)
        total += n
    print(f"\nBackfill complete. {total} total rows saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fund", type=str, help="Single fund ticker (e.g. ARTY)")
    args = parser.parse_args()
    run([args.fund.upper()] if args.fund else None)
