"""
DuckDB operations for The Sentinel trading engine.
Handles all database interactions for candles, news, and trades.

Includes:
- Historical data bootstrap from Zerodha API
- Tick-to-OHLC aggregation
- Daily cleanup to parquet migration
"""
import duckdb
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import logging
import os

logger = logging.getLogger(__name__)


class SentinelDB:
    """DuckDB wrapper for The Sentinel's data storage."""
    
    def __init__(self, db_path: str = "data/sentinel.duckdb"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(db_path)
        self._init_schema()
    
    def _init_schema(self):
        """Initialize database tables if they don't exist."""
        # Candles table - check if interval column exists and add if missing
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                ticker VARCHAR NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                vwap DOUBLE,
                PRIMARY KEY (ticker, timestamp)
            )
        """)
        
        # Add interval column if it doesn't exist (migration for existing DBs)
        try:
            self.conn.execute("SELECT interval FROM candles LIMIT 1")
        except duckdb.BinderException:
            logger.info("Adding interval column to candles table...")
            self.conn.execute("ALTER TABLE candles ADD COLUMN interval VARCHAR DEFAULT '1min'")
        
        # Ticks table for raw tick data before aggregation
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                ticker VARCHAR NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                price DOUBLE NOT NULL,
                volume BIGINT DEFAULT 0,
                PRIMARY KEY (ticker, timestamp)
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY,
                ticker VARCHAR NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                headline TEXT NOT NULL,
                source VARCHAR NOT NULL,
                processed BOOLEAN DEFAULT FALSE
            )
        """)
        
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS news_id_seq START 1
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                ticker VARCHAR NOT NULL,
                entry_time TIMESTAMP NOT NULL,
                exit_time TIMESTAMP,
                entry_price DOUBLE NOT NULL,
                exit_price DOUBLE,
                quantity INTEGER NOT NULL,
                side VARCHAR NOT NULL,
                pnl DOUBLE,
                status VARCHAR DEFAULT 'OPEN',
                entry_reason TEXT,
                exit_reason TEXT,
                sentiment_score DOUBLE,
                chart_safety VARCHAR
            )
        """)
        
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS trades_id_seq START 1
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                ticker VARCHAR PRIMARY KEY,
                quantity INTEGER NOT NULL,
                avg_price DOUBLE NOT NULL,
                side VARCHAR NOT NULL,
                entry_time TIMESTAMP NOT NULL
            )
        """)
        
        logger.info("Database schema initialized")
    
    # =========================================================================
    # Candle Operations
    # =========================================================================
    
    def insert_candle(self, ticker: str, timestamp: datetime, 
                      open_: float, high: float, low: float, 
                      close: float, volume: int, vwap: Optional[float] = None):
        """Insert or update a candle."""
        self.conn.execute("""
            INSERT OR REPLACE INTO candles 
            (ticker, timestamp, open, high, low, close, volume, vwap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [ticker, timestamp, open_, high, low, close, volume, vwap])
    
    def insert_candles_batch(self, candles: List[Dict[str, Any]]):
        """Batch insert candles from list of dicts."""
        if not candles:
            return
        df = pd.DataFrame(candles)
        self.conn.execute("""
            INSERT OR REPLACE INTO candles 
            SELECT * FROM df
        """)
    
    def get_candles(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        """Get recent candles for a ticker."""
        return self.conn.execute("""
            SELECT * FROM candles 
            WHERE ticker = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, [ticker, limit]).df()
    
    def get_candles_since(self, ticker: str, since: datetime) -> pd.DataFrame:
        """Get candles since a specific timestamp."""
        return self.conn.execute("""
            SELECT * FROM candles 
            WHERE ticker = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, [ticker, since]).df()
    
    def get_latest_candle(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get the most recent candle for a ticker."""
        result = self.conn.execute("""
            SELECT * FROM candles 
            WHERE ticker = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, [ticker]).df()
        if result.empty:
            return None
        return result.iloc[0].to_dict()
    
    def get_intraday_candles(self, ticker: str, date: datetime = None) -> pd.DataFrame:
        """Get all candles for a specific trading day."""
        if date is None:
            date = datetime.now()
        start = date.replace(hour=9, minute=15, second=0, microsecond=0)
        end = date.replace(hour=15, minute=30, second=0, microsecond=0)
        return self.conn.execute("""
            SELECT * FROM candles 
            WHERE ticker = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, [ticker, start, end]).df()
    
    # =========================================================================
    # News Operations
    # =========================================================================
    
    def insert_news(self, ticker: str, timestamp: datetime, 
                    headline: str, source: str) -> int:
        """Insert a news headline. Returns the new ID."""
        result = self.conn.execute("""
            INSERT INTO news (id, ticker, timestamp, headline, source)
            VALUES (nextval('news_id_seq'), ?, ?, ?, ?)
            RETURNING id
        """, [ticker, timestamp, headline, source]).fetchone()
        return result[0]
    
    def get_recent_news(self, ticker: str, limit: int = 10) -> pd.DataFrame:
        """Get recent news headlines for a ticker."""
        return self.conn.execute("""
            SELECT * FROM news 
            WHERE ticker = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, [ticker, limit]).df()
    
    def get_unprocessed_news(self, ticker: str) -> pd.DataFrame:
        """Get news that hasn't been analyzed yet."""
        return self.conn.execute("""
            SELECT * FROM news 
            WHERE ticker = ? AND processed = FALSE
            ORDER BY timestamp DESC
        """, [ticker]).df()
    
    def mark_news_processed(self, news_ids: List[int]):
        """Mark news items as processed."""
        if not news_ids:
            return
        self.conn.execute("""
            UPDATE news SET processed = TRUE
            WHERE id IN (SELECT unnest(?::INTEGER[]))
        """, [news_ids])
    
    # =========================================================================
    # Trade Operations
    # =========================================================================
    
    def insert_trade(self, ticker: str, entry_time: datetime, 
                     entry_price: float, quantity: int, side: str,
                     entry_reason: str = None, sentiment_score: float = None,
                     chart_safety: str = None) -> int:
        """Record a new trade entry. Returns trade ID."""
        result = self.conn.execute("""
            INSERT INTO trades 
            (id, ticker, entry_time, entry_price, quantity, side, 
             status, entry_reason, sentiment_score, chart_safety)
            VALUES (nextval('trades_id_seq'), ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            RETURNING id
        """, [ticker, entry_time, entry_price, quantity, side, 
              entry_reason, sentiment_score, chart_safety]).fetchone()
        return result[0]
    
    def close_trade(self, trade_id: int, exit_time: datetime, 
                    exit_price: float, exit_reason: str = None):
        """Close an open trade and calculate PnL."""
        trade = self.get_trade(trade_id)
        if trade is None:
            raise ValueError(f"Trade {trade_id} not found")
        
        if trade['side'] == 'BUY':
            pnl = (exit_price - trade['entry_price']) * trade['quantity']
        else:
            pnl = (trade['entry_price'] - exit_price) * trade['quantity']
        
        self.conn.execute("""
            UPDATE trades 
            SET exit_time = ?, exit_price = ?, pnl = ?, 
                status = 'CLOSED', exit_reason = ?
            WHERE id = ?
        """, [exit_time, exit_price, pnl, exit_reason, trade_id])
        
        return pnl
    
    def get_trade(self, trade_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific trade by ID."""
        result = self.conn.execute("""
            SELECT * FROM trades WHERE id = ?
        """, [trade_id]).df()
        if result.empty:
            return None
        return result.iloc[0].to_dict()
    
    def get_open_trades(self) -> pd.DataFrame:
        """Get all open trades."""
        return self.conn.execute("""
            SELECT * FROM trades WHERE status = 'OPEN'
        """).df()
    
    def get_todays_trades(self) -> pd.DataFrame:
        """Get all trades from today."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.conn.execute("""
            SELECT * FROM trades 
            WHERE entry_time >= ?
            ORDER BY entry_time ASC
        """, [today]).df()
    
    def get_todays_pnl(self) -> float:
        """Calculate total PnL for today (closed trades only)."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = self.conn.execute("""
            SELECT COALESCE(SUM(pnl), 0) as total_pnl
            FROM trades 
            WHERE entry_time >= ? AND status = 'CLOSED'
        """, [today]).fetchone()
        return result[0]
    
    # =========================================================================
    # Position Operations
    # =========================================================================
    
    def update_position(self, ticker: str, quantity: int, 
                        avg_price: float, side: str, entry_time: datetime):
        """Update or create a position."""
        self.conn.execute("""
            INSERT OR REPLACE INTO positions 
            (ticker, quantity, avg_price, side, entry_time)
            VALUES (?, ?, ?, ?, ?)
        """, [ticker, quantity, avg_price, side, entry_time])
    
    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get current position for a ticker."""
        result = self.conn.execute("""
            SELECT * FROM positions WHERE ticker = ?
        """, [ticker]).df()
        if result.empty:
            return None
        return result.iloc[0].to_dict()
    
    def get_all_positions(self) -> pd.DataFrame:
        """Get all open positions."""
        return self.conn.execute("SELECT * FROM positions").df()
    
    def close_position(self, ticker: str):
        """Remove a position (after closing)."""
        self.conn.execute("DELETE FROM positions WHERE ticker = ?", [ticker])
    
    def close_all_positions(self):
        """Remove all positions."""
        self.conn.execute("DELETE FROM positions")
    
    # =========================================================================
    # Analytics Queries
    # =========================================================================
    
    def get_volatility(self, ticker: str, window_minutes: int = 5) -> float:
        """Calculate recent volatility (std dev of returns)."""
        since = datetime.now() - timedelta(minutes=window_minutes * 20)
        result = self.conn.execute("""
            WITH returns AS (
                SELECT 
                    (close - LAG(close) OVER (ORDER BY timestamp)) / 
                    LAG(close) OVER (ORDER BY timestamp) as ret
                FROM candles 
                WHERE ticker = ? AND timestamp >= ?
            )
            SELECT COALESCE(STDDEV(ret), 0) as volatility FROM returns
        """, [ticker, since]).fetchone()
        return result[0]
    
    def get_mtm_loss(self) -> float:
        """Calculate current Mark-to-Market loss across all positions."""
        positions = self.get_all_positions()
        if positions.empty:
            return 0.0
        
        total_mtm = 0.0
        for _, pos in positions.iterrows():
            latest = self.get_latest_candle(pos['ticker'])
            if latest:
                if pos['side'] == 'BUY':
                    unrealized = (latest['close'] - pos['avg_price']) * pos['quantity']
                else:
                    unrealized = (pos['avg_price'] - latest['close']) * pos['quantity']
                total_mtm += unrealized
        
        realized = self.get_todays_pnl()
        return -(total_mtm + realized) if (total_mtm + realized) < 0 else 0.0
    
    # =========================================================================
    # Historical Data Bootstrap (for 200 EMA calculation)
    # =========================================================================
    
    def bootstrap_historical_data(
        self,
        kite,
        watchlist: List[str],
        days: int = 2,
        interval: str = "5minute"
    ) -> Dict[str, int]:
        """
        Fetch historical candle data from Zerodha for 200 EMA calculation.
        
        IMPORTANT: Call this BEFORE market opens (e.g., 9:00 AM) to ensure
        sufficient data for 200-period EMA on 5-minute timeframe.
        
        Args:
            kite: KiteConnect instance with valid access token
            watchlist: List of stock tickers to fetch
            days: Number of trading days to fetch (default 2)
            interval: Candle interval (default "5minute")
            
        Returns:
            Dict mapping ticker to number of candles fetched
        """
        from src.ingestion.real_kite import RealTicker
        
        results = {}
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days + 1)  # Extra day buffer
        
        logger.info(f"Bootstrapping historical data for {len(watchlist)} stocks, {days} days")
        
        for ticker in watchlist:
            try:
                # Get instrument token
                token = RealTicker.INSTRUMENT_TOKENS.get(ticker)
                if not token:
                    logger.warning(f"No instrument token for {ticker}")
                    continue
                
                # Fetch historical data from Zerodha
                candles = kite.historical_data(
                    instrument_token=token,
                    from_date=from_date.strftime("%Y-%m-%d"),
                    to_date=to_date.strftime("%Y-%m-%d"),
                    interval=interval,
                    continuous=False
                )
                
                if not candles:
                    logger.warning(f"No historical data returned for {ticker}")
                    continue
                
                # Convert interval format for storage
                interval_map = {
                    "minute": "1min",
                    "5minute": "5min",
                    "15minute": "15min",
                    "30minute": "30min",
                    "60minute": "1hour",
                    "day": "1day"
                }
                db_interval = interval_map.get(interval, interval)
                
                # Insert candles into database
                count = 0
                for candle in candles:
                    self.insert_candle_with_interval(
                        ticker=ticker,
                        timestamp=candle['date'],
                        open_=candle['open'],
                        high=candle['high'],
                        low=candle['low'],
                        close=candle['close'],
                        volume=candle['volume'],
                        interval=db_interval
                    )
                    count += 1
                
                results[ticker] = count
                logger.info(f"Bootstrapped {count} candles for {ticker}")
                
            except Exception as e:
                logger.error(f"Failed to bootstrap {ticker}: {e}")
                results[ticker] = 0
        
        logger.info(f"Bootstrap complete: {sum(results.values())} total candles")
        return results
    
    def insert_candle_with_interval(
        self,
        ticker: str,
        timestamp: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: int,
        interval: str = "1min",
        vwap: Optional[float] = None
    ):
        """Insert or update a candle with interval specification."""
        self.conn.execute("""
            INSERT OR REPLACE INTO candles 
            (ticker, timestamp, open, high, low, close, volume, vwap, interval)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [ticker, timestamp, open_, high, low, close, volume, vwap, interval])
    
    def get_candles_by_interval(
        self,
        ticker: str,
        interval: str = "5min",
        limit: int = 250
    ) -> pd.DataFrame:
        """
        Get candles for a specific interval.
        
        Args:
            ticker: Stock ticker
            interval: Candle interval (1min, 5min, 15min, etc.)
            limit: Maximum number of candles (default 250 for 200 EMA + buffer)
            
        Returns:
            DataFrame with candles sorted by timestamp ascending
        """
        # Handle both legacy data (no interval) and new data with interval
        result = self.conn.execute("""
            SELECT ticker, timestamp, open, high, low, close, volume, vwap
            FROM candles 
            WHERE ticker = ? AND (interval = ? OR interval IS NULL OR interval = '1min')
            ORDER BY timestamp DESC
            LIMIT ?
        """, [ticker, interval, limit]).df()
        
        # Return sorted ascending for indicator calculations
        if not result.empty:
            result = result.sort_values('timestamp').reset_index(drop=True)
        return result
    
    # =========================================================================
    # Tick Aggregation (convert live ticks to OHLC candles)
    # =========================================================================
    
    def insert_tick(self, ticker: str, timestamp: datetime, price: float, volume: int = 0):
        """Insert a raw tick."""
        self.conn.execute("""
            INSERT OR REPLACE INTO ticks (ticker, timestamp, price, volume)
            VALUES (?, ?, ?, ?)
        """, [ticker, timestamp, price, volume])
    
    def aggregate_ticks_to_candles(
        self,
        ticker: str,
        interval_minutes: int = 5,
        since: datetime = None
    ) -> int:
        """
        Aggregate raw ticks into OHLC candles.
        
        Args:
            ticker: Stock ticker
            interval_minutes: Candle interval in minutes (default 5)
            since: Start time for aggregation (default: last 2 hours)
            
        Returns:
            Number of candles created
        """
        if since is None:
            since = datetime.now() - timedelta(hours=2)
        
        interval_str = f"{interval_minutes}min"
        
        # Aggregate ticks using DuckDB's time_bucket
        result = self.conn.execute("""
            WITH bucketed AS (
                SELECT 
                    ticker,
                    time_bucket(INTERVAL ? MINUTE, timestamp) as bucket,
                    FIRST(price ORDER BY timestamp) as open,
                    MAX(price) as high,
                    MIN(price) as low,
                    LAST(price ORDER BY timestamp) as close,
                    SUM(volume) as volume
                FROM ticks
                WHERE ticker = ? AND timestamp >= ?
                GROUP BY ticker, bucket
            )
            SELECT * FROM bucketed ORDER BY bucket
        """, [interval_minutes, ticker, since]).df()
        
        if result.empty:
            return 0
        
        # Insert aggregated candles
        count = 0
        for _, row in result.iterrows():
            self.insert_candle_with_interval(
                ticker=row['ticker'],
                timestamp=row['bucket'],
                open_=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=int(row['volume']),
                interval=interval_str
            )
            count += 1
        
        logger.debug(f"Aggregated {count} {interval_str} candles for {ticker}")
        return count
    
    def aggregate_all_watchlist(
        self,
        watchlist: List[str],
        interval_minutes: int = 5
    ) -> Dict[str, int]:
        """Aggregate ticks for all stocks in watchlist."""
        results = {}
        for ticker in watchlist:
            results[ticker] = self.aggregate_ticks_to_candles(ticker, interval_minutes)
        return results
    
    # =========================================================================
    # Daily Cleanup (migrate old data to parquet)
    # =========================================================================
    
    def cleanup_old_data(self, days_to_keep: int = 1) -> Dict[str, int]:
        """
        Migrate old tick and candle data to parquet files.
        
        Args:
            days_to_keep: Number of days to keep in primary DB (default 1)
            
        Returns:
            Dict with counts of exported records
        """
        cutoff = datetime.now() - timedelta(days=days_to_keep)
        cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
        
        history_dir = Path("history")
        history_dir.mkdir(exist_ok=True)
        
        date_str = cutoff.strftime("%Y%m%d")
        results = {'ticks': 0, 'candles': 0}
        
        # Export old ticks
        old_ticks = self.conn.execute("""
            SELECT * FROM ticks WHERE timestamp < ?
        """, [cutoff]).df()
        
        if not old_ticks.empty:
            parquet_path = history_dir / f"ticks_{date_str}.parquet"
            old_ticks.to_parquet(parquet_path, index=False)
            results['ticks'] = len(old_ticks)
            
            # Delete exported ticks
            self.conn.execute("DELETE FROM ticks WHERE timestamp < ?", [cutoff])
            logger.info(f"Exported {len(old_ticks)} ticks to {parquet_path}")
        
        # Export old candles (keep 5min candles for longer historical analysis)
        old_candles = self.conn.execute("""
            SELECT * FROM candles 
            WHERE timestamp < ? AND interval = '1min'
        """, [cutoff]).df()
        
        if not old_candles.empty:
            parquet_path = history_dir / f"candles_1min_{date_str}.parquet"
            old_candles.to_parquet(parquet_path, index=False)
            results['candles'] = len(old_candles)
            
            # Delete exported 1min candles only
            self.conn.execute("""
                DELETE FROM candles WHERE timestamp < ? AND interval = '1min'
            """, [cutoff])
            logger.info(f"Exported {len(old_candles)} 1min candles to {parquet_path}")
        
        return results
    
    def get_candle_count(self, ticker: str, interval: str = "5min") -> int:
        """Get count of candles for a ticker and interval."""
        result = self.conn.execute("""
            SELECT COUNT(*) FROM candles 
            WHERE ticker = ? AND interval = ?
        """, [ticker, interval]).fetchone()
        return result[0] if result else 0
    
    def close(self):
        """Close database connection."""
        self.conn.close()


# Singleton instance
_db_instance: Optional[SentinelDB] = None

def get_db(db_path: str = "data/sentinel.duckdb") -> SentinelDB:
    """Get or create the database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = SentinelDB(db_path)
    return _db_instance
