"""
Shared test fixtures for The Sentinel test suite.
"""
import sys
import os
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import SentinelDB
from src.ingestion.mock_kite import MockKite, MockTicker
from src.trading.executor import PaperTradeExecutor


@pytest.fixture
def temp_db():
    """Create a temporary DuckDB database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_sentinel.duckdb")
        db = SentinelDB(db_path)
        yield db
        db.close()


@pytest.fixture
def mock_kite():
    """Create a MockKite instance with linked ticker."""
    ticker = MockTicker()
    kite = MockKite()
    kite.set_ticker(ticker)
    return kite, ticker


@pytest.fixture
def paper_executor(temp_db, mock_kite):
    """Create a PaperTradeExecutor with temp db and mock kite."""
    kite, ticker = mock_kite
    executor = PaperTradeExecutor(
        kite=kite,
        db=temp_db,
        slippage_pct=0.0005,
        default_quantity=10
    )
    return executor


@pytest.fixture
def sample_trades():
    """Generate 5 sample trades (3 wins, 2 losses) for testing."""
    now = datetime.now()
    trades = [
        {
            'ticker': 'RELIANCE',
            'entry_price': 2950.0,
            'exit_price': 2980.0,
            'entry_time': (now - timedelta(hours=4)).isoformat(),
            'exit_time': (now - timedelta(hours=3)).isoformat(),
            'side': 'BUY',
            'quantity': 10,
            'pnl': 300.0,
            'entry_reason': 'VWAP Pullback + RSI Confluence',
            'exit_reason': 'Take Profit Hit',
            'sentiment_score': 0.7,
            'chart_safety': 'SAFE',
        },
        {
            'ticker': 'TCS',
            'entry_price': 4150.0,
            'exit_price': 4180.0,
            'entry_time': (now - timedelta(hours=3, minutes=30)).isoformat(),
            'exit_time': (now - timedelta(hours=2, minutes=30)).isoformat(),
            'side': 'BUY',
            'quantity': 10,
            'pnl': 300.0,
            'entry_reason': 'EMA Crossover',
            'exit_reason': 'Take Profit Hit',
            'sentiment_score': 0.5,
            'chart_safety': 'SAFE',
        },
        {
            'ticker': 'INFY',
            'entry_price': 1890.0,
            'exit_price': 1910.0,
            'entry_time': (now - timedelta(hours=3)).isoformat(),
            'exit_time': (now - timedelta(hours=2)).isoformat(),
            'side': 'BUY',
            'quantity': 10,
            'pnl': 200.0,
            'entry_reason': 'VWAP Pullback',
            'exit_reason': 'Trailing Stop',
            'sentiment_score': 0.6,
            'chart_safety': 'SAFE',
        },
        {
            'ticker': 'ICICIBANK',
            'entry_price': 1280.0,
            'exit_price': 1260.0,
            'entry_time': (now - timedelta(hours=2, minutes=30)).isoformat(),
            'exit_time': (now - timedelta(hours=1, minutes=30)).isoformat(),
            'side': 'BUY',
            'quantity': 10,
            'pnl': -200.0,
            'entry_reason': 'RSI Bounce',
            'exit_reason': 'Stop Loss Hit',
            'sentiment_score': 0.3,
            'chart_safety': 'RISKY',
        },
        {
            'ticker': 'HDFCBANK',
            'entry_price': 1720.0,
            'exit_price': 1700.0,
            'entry_time': (now - timedelta(hours=2)).isoformat(),
            'exit_time': (now - timedelta(hours=1)).isoformat(),
            'side': 'BUY',
            'quantity': 10,
            'pnl': -200.0,
            'entry_reason': 'EMA Crossover',
            'exit_reason': 'Stop Loss Hit',
            'sentiment_score': 0.2,
            'chart_safety': 'NEUTRAL',
        },
    ]
    return trades
