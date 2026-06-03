TICKERS = ["CHAT", "BAI", "TSPA", "AIPI", "XAIX", "AIFD", "ARTY"]

FUND_META = {
    "CHAT": {"name": "Roundhill Generative AI & Technology ETF", "provider": "Roundhill"},
    "BAI":  {"name": "iShares A.I. Innovation and Tech Active ETF", "provider": "iShares"},
    "TSPA": {"name": "T. Rowe Price U.S. Equity Research ETF", "provider": "T. Rowe Price"},
    "AIPI": {"name": "REX AI Equity Premium Income ETF", "provider": "REX Shares"},
    "XAIX": {"name": "Xtrackers Artificial Intelligence & Big Data ETF", "provider": "DWS"},
    "AIFD": {"name": "TCW Artificial Intelligence ETF", "provider": "TCW"},
    "ARTY": {"name": "iShares Future AI & Tech ETF", "provider": "iShares"},
}

DB_PATH = "etf_tracker.db"

# iShares product IDs for direct CSV download
ISHARES_PRODUCT_IDS = {
    "BAI":  "339081",
    "ARTY": "297905",
}

# Holdings change thresholds
WEIGHT_CHANGE_THRESHOLD = 1.5  # percent
