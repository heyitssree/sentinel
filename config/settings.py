"""
Configuration settings for The Sentinel trading engine.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# API Keys
# =============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
KITE_API_KEY = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "")
TRADING_MODE = os.getenv("TRADING_MODE", "paper")

# =============================================================================
# Watchlist - High liquidity Nifty 50 stocks
# =============================================================================
WATCHLIST = [
    "RELIANCE",
    "ICICIBANK", 
    "TCS",
    "INFY",
    "HDFCBANK"
]

# Base prices for mock data generation (approximate real prices as of 2026)
BASE_PRICES = {
    "RELIANCE": 2950.0,
    "ICICIBANK": 1280.0,
    "TCS": 4150.0,
    "INFY": 1890.0,
    "HDFCBANK": 1720.0
}

# =============================================================================
# Trading Parameters
# =============================================================================
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", 0.0005))  # 0.05%
MTM_LOSS_LIMIT = float(os.getenv("MTM_LOSS_LIMIT", 5000))  # ₹5,000 kill switch
MAX_ORDERS_PER_SECOND = 10  # SEBI 2026 compliance
DEFAULT_QUANTITY = 10  # Shares per trade

# =============================================================================
# Signal Thresholds (Legacy - kept for backward compatibility)
# =============================================================================
RSI_ENTRY_THRESHOLD = 60  # RSI > 60 for bullish entry (legacy, replaced by VWAP pullback)
RSI_OVERBOUGHT = 80  # Chart is "overextended"
EMA_PERIOD = 20
RSI_PERIOD = 14

# =============================================================================
# Mean Reversion Filter (New Trading Logic)
# =============================================================================
# VWAP Pullback Entry: Price within this % of VWAP while above it
VWAP_PULLBACK_THRESHOLD = float(os.getenv("VWAP_PULLBACK_THRESHOLD", 0.005))  # 0.5% default

# Volume Confirmation: Current volume must be >= this multiple of 20-period avg
VOLUME_CONFIRMATION_MULTIPLIER = float(os.getenv("VOLUME_CONFIRMATION_MULTIPLIER", 1.5))  # 1.5x default

# Per-stock volume overrides (optional, format: "RELIANCE:1.2,TCS:2.0")
VOLUME_OVERRIDES_RAW = os.getenv("VOLUME_OVERRIDES", "")
VOLUME_OVERRIDES = {}
if VOLUME_OVERRIDES_RAW:
    for item in VOLUME_OVERRIDES_RAW.split(","):
        if ":" in item:
            ticker, mult = item.split(":")
            VOLUME_OVERRIDES[ticker.strip()] = float(mult)

# =============================================================================
# Dynamic ATR-Based Stops
# =============================================================================
ATR_STOP_LOSS_MULTIPLIER = float(os.getenv("ATR_STOP_LOSS_MULTIPLIER", 2.0))  # SL = 2x ATR
ATR_TAKE_PROFIT_MULTIPLIER = float(os.getenv("ATR_TAKE_PROFIT_MULTIPLIER", 4.0))  # TP = 4x ATR
ATR_PERIOD = int(os.getenv("ATR_PERIOD", 14))  # ATR calculation period

# =============================================================================
# Market Hours (IST)
# =============================================================================
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30
CANDLE_INTERVAL_SECONDS = 300  # 5-minute candles

# =============================================================================
# Gemini Settings
# =============================================================================
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_SENTIMENT_THRESHOLD = 0.0  # Sentiment must be > 0 to proceed

# =============================================================================
# Database
# =============================================================================
DATABASE_PATH = "data/sentinel.duckdb"
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", 7))  # Days to keep tick/1min data

# =============================================================================
# News Sources (RSS Feeds)
# =============================================================================
NEWS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/marketreports.xml",
]

# =============================================================================
# Logging
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
