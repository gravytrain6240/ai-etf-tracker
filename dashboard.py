import os
import sys
import sqlite3
from datetime import date, timedelta

# Ensure project directory is on path regardless of how Streamlit was launched
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import DB_PATH, FUND_META, TICKERS
from consensus_alerts import get_alerts, init_consensus_table
from db import get_changes, get_conn


def get_company_info(symbols: list) -> dict:
    if not symbols:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"SELECT * FROM company_info WHERE symbol IN ({placeholders})", symbols
    ).fetchall()
    conn.close()
    return {r["symbol"]: dict(r) for r in rows}

st.set_page_config(page_title="AI ETF Tracker", layout="wide", page_icon="🤖")
st.title("AI ETF Tracker")

# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_prices(n_days: int = 60) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("""
        SELECT date, ticker, adj_close, nav_return
        FROM daily_prices
        WHERE date >= date('now', ? || ' days')
        ORDER BY date ASC
    """, conn, params=(f"-{n_days}",))
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def load_changes(n_days: int = 7) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("""
        SELECT * FROM holdings_changes
        WHERE date >= date('now', ? || ' days')
        ORDER BY date DESC, fund, change_type, ABS(weight_delta) DESC
    """, conn, params=(f"-{n_days}",))
    conn.close()
    return df


@st.cache_data(ttl=300)
def load_holdings_latest(fund: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("""
        SELECT h.* FROM holdings h
        INNER JOIN (
            SELECT fund, MAX(date) AS max_date FROM holdings WHERE fund = ? GROUP BY fund
        ) latest ON h.fund = latest.fund AND h.date = latest.max_date
        ORDER BY weight DESC
    """, conn, params=(fund,))
    conn.close()
    return df


def latest_trading_date() -> str:
    conn = get_conn()
    row = conn.execute("SELECT MAX(date) AS d FROM daily_prices").fetchone()
    conn.close()
    return row["d"] or date.today().strftime("%Y-%m-%d")


@st.cache_data(ttl=600)
def load_resolved_tickers(symbols: tuple) -> dict:
    """Resolve stockanalysis symbols to yfinance tickers (cached 10 min)."""
    from ticker_resolver import normalize_batch
    return normalize_batch([s for s in symbols if s and not s.startswith("__edgar__")])


def _fetch_prices(yf_tickers: list, **kwargs) -> dict:
    """Download prices for a list of yfinance tickers. Returns {ticker: Series}."""
    import yfinance as yf
    if not yf_tickers:
        return {}
    try:
        raw = yf.download(yf_tickers, progress=False, auto_adjust=True,
                          group_by="ticker", **kwargs)
        result = {}
        for t in yf_tickers:
            try:
                s = raw["Close"].dropna() if len(yf_tickers) == 1 else raw[t]["Close"].dropna()
                if not s.empty:
                    result[t] = s
            except Exception:
                pass
        return result
    except Exception:
        return {}


@st.cache_data(ttl=300)
def load_prior_day_returns(symbols: tuple) -> dict:
    """Prior-day return for each symbol. Returns {original_symbol: daily_%}."""
    resolved = load_resolved_tickers(symbols)
    yf_tickers = list(set(resolved.values()))
    price_series = _fetch_prices(yf_tickers, period="5d")

    result = {}
    for orig, yft in resolved.items():
        s = price_series.get(yft)
        if s is not None and len(s) >= 2:
            result[orig] = round((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2)
    return result


@st.cache_data(ttl=3600)
def load_ytd_returns(symbols: tuple) -> dict:
    """YTD return for each symbol. Returns {original_symbol: ytd_%}."""
    resolved = load_resolved_tickers(symbols)
    yf_tickers = list(set(resolved.values()))
    year_start = f"{date.today().year}-01-01"
    price_series = _fetch_prices(yf_tickers, start=year_start)

    result = {}
    for orig, yft in resolved.items():
        s = price_series.get(yft)
        if s is not None and len(s) >= 2:
            result[orig] = round((s.iloc[-1] / s.iloc[0] - 1) * 100, 2)
    return result


@st.cache_data(ttl=300)
def load_consensus(n_days: int = 30) -> pd.DataFrame:
    init_consensus_table()
    alerts = get_alerts(n_days)
    return pd.DataFrame(alerts) if alerts else pd.DataFrame()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Settings")
    lookback = st.slider("Return lookback (days)", 5, 252, 30)
    changes_window = st.slider("Holdings changes window (days)", 1, 30, 7)
    selected_funds = st.multiselect("Funds", TICKERS, default=TICKERS)

# ── Section 1: Daily Returns ──────────────────────────────────────────────────

st.header("Daily NAV Returns")

prices_df = load_prices(lookback + 5)
if prices_df.empty:
    st.warning("No price data yet — run `python run_daily.py` first.")
else:
    prices_filtered = prices_df[prices_df["ticker"].isin(selected_funds)]
    latest_date = latest_trading_date()

    # Today's return cards
    today_returns = prices_df[prices_df["date"] == prices_df["date"].max()]
    cols = st.columns(len(selected_funds))
    for i, ticker in enumerate(selected_funds):
        row = today_returns[today_returns["ticker"] == ticker]
        with cols[i]:
            if not row.empty and row.iloc[0]["nav_return"] is not None:
                ret = row.iloc[0]["nav_return"]
                st.metric(
                    label=ticker,
                    value=f"{ret:+.2f}%",
                    delta=f"{ret:+.2f}%",
                    delta_color="normal",
                )
            else:
                st.metric(label=ticker, value="—")

    st.divider()

    # Indexed performance chart (rebased to 100)
    pivot = prices_filtered.pivot(index="date", columns="ticker", values="adj_close")
    pivot = pivot[selected_funds] if all(f in pivot.columns for f in selected_funds) else pivot
    rebased = pivot.divide(pivot.iloc[0]) * 100

    fig = px.line(
        rebased.reset_index().melt(id_vars="date", var_name="Fund", value_name="Indexed Price"),
        x="date", y="Indexed Price", color="Fund",
        title=f"Performance (rebased to 100, last {lookback} days)",
        template="plotly_dark",
    )
    fig.update_layout(hovermode="x unified", legend_title_text="")
    st.plotly_chart(fig, use_container_width=True)

    # Daily return heatmap
    ret_pivot = prices_filtered.pivot(index="date", columns="ticker", values="nav_return").tail(lookback)
    fig2 = go.Figure(data=go.Heatmap(
        z=ret_pivot.values,
        x=ret_pivot.columns.tolist(),
        y=[d.strftime("%b %d") for d in ret_pivot.index],
        colorscale="RdYlGn",
        zmid=0,
        text=[[f"{v:.2f}%" if v == v else "" for v in row] for row in ret_pivot.values],
        texttemplate="%{text}",
        hovertemplate="%{y} | %{x}: %{z:.2f}%<extra></extra>",
    ))
    fig2.update_layout(title="Daily Return Heatmap (%)", template="plotly_dark", height=500)
    st.plotly_chart(fig2, use_container_width=True)

# ── Section 2: Holdings Changes ───────────────────────────────────────────────

st.header("Holdings Changes")

# New additions always show rolling 30 days; resizes/removals use sidebar window
NEW_ADDITIONS_DAYS = 30
additions_df = load_changes(NEW_ADDITIONS_DAYS)
changes_df   = load_changes(changes_window)

all_changes_empty = changes_df.empty and additions_df.empty
if all_changes_empty:
    st.info(f"No holdings changes detected in the last {max(changes_window, NEW_ADDITIONS_DAYS)} day(s).")
else:
    changes_df   = changes_df[changes_df["fund"].isin(selected_funds)]
    additions_df = additions_df[additions_df["fund"].isin(selected_funds)]

    CHANGE_COLORS = {
        "added":    "🟢",
        "removed":  "🔴",
        "added_to": "🔼",
        "trimmed":  "🔽",
    }

    # Pre-load company info for all new additions in the 30-day window
    new_symbols = additions_df.loc[additions_df["change_type"] == "added", "symbol"].unique().tolist()
    company_info = get_company_info(new_symbols) if new_symbols else {}

    for fund in selected_funds:
        fund_additions = additions_df[(additions_df["fund"] == fund) & (additions_df["change_type"] == "added")]
        fund_other     = changes_df[(changes_df["fund"] == fund) & (changes_df["change_type"] != "added")]
        if fund_additions.empty and fund_other.empty:
            continue

        n_added   = len(fund_additions)
        n_removed = (fund_other["change_type"] == "removed").sum()
        n_resized = (fund_other["change_type"].isin(["added_to", "trimmed"])).sum()
        badge = f"{fund}"
        if n_added:   badge += f"  🟢 {n_added} new (30d)"
        if n_removed: badge += f"  🔴 {n_removed} exited"
        if n_resized: badge += f"  ↕ {n_resized} resized"

        with st.expander(badge, expanded=True):
            # ── New additions with company summary cards (rolling 30 days) ────
            if not fund_additions.empty:
                st.markdown(f"**New Positions — last 30 days**")
                for _, row in fund_additions.sort_values("date", ascending=False).iterrows():
                    sym  = row["symbol"]
                    info = company_info.get(sym, {})
                    added_date = row["date"]
                    with st.container(border=True):
                        col1, col2 = st.columns([1, 4])
                        with col1:
                            st.markdown(f"### {sym}")
                            st.caption(info.get("long_name") or row.get("name", ""))
                            sector   = info.get("sector", "")
                            industry = info.get("industry", "")
                            if sector:
                                st.caption(f"**{sector}**" + (f" · {industry}" if industry else ""))
                            mcap = info.get("market_cap")
                            if mcap:
                                st.caption(f"Mkt Cap: **${mcap/1e9:.1f}B**")
                            st.caption(f"Added: **{added_date}**")
                            st.metric("Initial Weight", f"{row['weight_curr']:.2f}%" if row['weight_curr'] else "—")
                        with col2:
                            summary = info.get("summary", "")
                            if summary:
                                st.markdown(summary[:600] + ("…" if len(summary) > 600 else ""))
                            else:
                                st.caption("No company summary available.")
                            website = info.get("website", "")
                            if website:
                                st.markdown(f"[{website}]({website})")

                st.divider()

            # ── Removals + resizes table (uses sidebar window) ───────────────
            if not fund_other.empty:
                st.markdown(f"**Position Changes — last {changes_window} day(s)**")
                display = fund_other[["date", "symbol", "name", "change_type", "weight_prev", "weight_curr", "weight_delta"]].copy()
                display["change_type"] = display["change_type"].map(lambda x: f"{CHANGE_COLORS.get(x, '')} {x}")
                display.columns = ["Date", "Symbol", "Name", "Change", "Prev Weight %", "Curr Weight %", "Delta %"]
                st.dataframe(
                    display.style.format({
                        "Prev Weight %": lambda v: f"{v:.2f}%" if pd.notna(v) else "—",
                        "Curr Weight %": lambda v: f"{v:.2f}%" if pd.notna(v) else "—",
                        "Delta %":       lambda v: f"{v:+.2f}%" if pd.notna(v) else "—",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

# ── Section 3: Consensus Alerts ──────────────────────────────────────────────

st.header("Consensus Signals")
st.caption("Stocks added to or removed from 2+ funds on the same day")

consensus_df = load_consensus(changes_window)
if consensus_df.empty:
    st.info(f"No consensus signals in the last {changes_window} day(s).")
else:
    buys  = consensus_df[consensus_df["change_type"] == "added"]
    sells = consensus_df[consensus_df["change_type"] == "removed"]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Consensus Buys")
        if buys.empty:
            st.caption("None")
        else:
            buy_symbols = buys["symbol"].tolist()
            buy_info = get_company_info(buy_symbols)
            for _, row in buys.iterrows():
                sym  = row["symbol"]
                info = buy_info.get(sym, {})
                with st.container(border=True):
                    funds_list = row["funds"].split(",")
                    st.markdown(f"**{sym}** — added to {row['fund_count']} funds")
                    st.caption(" · ".join(f"`{f}`" for f in funds_list))
                    if info.get("sector"):
                        st.caption(f"{info['sector']} · {info.get('industry', '')}")
                    summary = info.get("summary", "")
                    if summary:
                        st.markdown(summary[:300] + ("…" if len(summary) > 300 else ""))

    with c2:
        st.markdown("#### Consensus Sells")
        if sells.empty:
            st.caption("None")
        else:
            for _, row in sells.iterrows():
                funds_list = row["funds"].split(",")
                with st.container(border=True):
                    st.markdown(f"**{row['symbol']}** — removed from {row['fund_count']} funds")
                    st.caption(" · ".join(f"`{f}`" for f in funds_list))

st.divider()

# ── Section 4: Current Holdings ───────────────────────────────────────────────

st.header("Current Holdings")

fund_tabs = st.tabs(selected_funds)
for tab, fund in zip(fund_tabs, selected_funds):
    with tab:
        h = load_holdings_latest(fund)
        if h.empty:
            st.info("No holdings data yet.")
        else:
            meta = FUND_META[fund]
            holdings_date = h["date"].iloc[0]
            st.caption(f"{meta['name']} | {meta['provider']} | {len(h)} holdings | as of {holdings_date}")

            # Filter out EDGAR placeholder rows (historical backfill only)
            display_h = h[~h["symbol"].str.startswith("__edgar__", na=False)].copy()

            fig = px.bar(
                display_h.head(20),
                x="symbol", y="weight",
                title=f"Top 20 Holdings — {fund}",
                template="plotly_dark",
                labels={"weight": "Weight (%)", "symbol": ""},
            )
            st.plotly_chart(fig, use_container_width=True)

            syms_tuple = tuple(display_h["symbol"].tolist())
            ytd_map    = load_ytd_returns(syms_tuple)
            prior_map  = load_prior_day_returns(syms_tuple)

            display_h["ytd"]          = display_h["symbol"].map(ytd_map)
            display_h["prior_ret"]    = display_h["symbol"].map(prior_map)
            display_h["contribution"] = (display_h["weight"] / 100) * display_h["prior_ret"]

            st.dataframe(
                display_h[["symbol", "name", "weight", "shares", "ytd", "prior_ret", "contribution"]].style.format({
                    "weight":       lambda v: f"{v:.2f}%" if v is not None and v == v else "—",
                    "shares":       lambda v: f"{v:,.0f}" if v is not None and v == v else "—",
                    "ytd":          lambda v: f"{v:+.2f}%" if v is not None and v == v else "—",
                    "prior_ret":    lambda v: f"{v:+.2f}%" if v is not None and v == v else "—",
                    "contribution": lambda v: f"{v:+.3f}pp" if v is not None and v == v else "—",
                }),
                column_config={
                    "symbol":       "Symbol",
                    "name":         "Name",
                    "weight":       "Weight",
                    "shares":       "Shares",
                    "ytd":          "YTD Return",
                    "prior_ret":    "Prior Day Ret",
                    "contribution": "Prior Day CTR",
                },
                use_container_width=True,
                hide_index=True,
            )
