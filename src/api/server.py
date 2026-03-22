"""
FastAPI server for The Sentinel Web Dashboard.
Provides REST API and WebSocket for real-time updates.

SSL Security:
- Uses certifi certificates by default (secure)
- SSL bypass only enabled in development mode via SENTINEL_DEV_MODE=true
- Production deployments should NEVER set SENTINEL_DEV_MODE=true
"""
import os
import ssl
import certifi

# Configure SSL certificates properly (secure by default)
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# ONLY bypass SSL verification in explicit development mode
# WARNING: Never enable this in production - vulnerable to MITM attacks
_DEV_MODE = os.getenv('SENTINEL_DEV_MODE', 'false').lower() == 'true'
if _DEV_MODE:
    try:
        ssl._create_default_https_context = ssl._create_unverified_context
        import warnings
        warnings.warn(
            "SSL verification disabled (SENTINEL_DEV_MODE=true). "
            "DO NOT use in production!", 
            UserWarning
        )
    except AttributeError:
        pass

import asyncio
import json
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/sentinel.log', mode='a')
    ]
)
logger = logging.getLogger('sentinel')

# Ensure logs directory exists
Path('logs').mkdir(exist_ok=True)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import WATCHLIST, MTM_LOSS_LIMIT, DATABASE_PATH, GEMINI_API_KEY, KITE_API_KEY, KITE_API_SECRET
import os
from dotenv import load_dotenv, set_key
from src.storage.db import get_db
from src.ingestion.mock_kite import MockKite, MockTicker
from src.ingestion.real_kite import RealKite, RealTicker
from src.trading.executor import PaperTradeExecutor, LiveTradeExecutor
from src.trading.risk import RiskManager
from src.trading.portfolio import PortfolioManager
from src.trading.signals import ConfluentSignalEngine, SmartTrailingStop, calculate_atr_position_size
from src.signals.indicators import TechnicalIndicators
from src.gemini.sentiment import SentimentAnalyzer, MockSentimentAnalyzer
from src.gemini.vision import MockVisualAuditor
from src.gemini.technical_analyst import TechnicalAnalyst, MockTechnicalAnalyst
from src.charts.generator import ChartGenerator
from src.ingestion.news_scraper import NewsScraper, MockNewsScraper
import numpy as np
import pandas as pd

# Environment file path - defined early as it's used in multiple endpoints
ENV_FILE = Path(__file__).parent.parent.parent / ".env"


import re

# Ticker validation pattern - uppercase letters only, 1-20 chars
_TICKER_PATTERN = re.compile(r'^[A-Z]{1,20}$')

def validate_ticker(ticker: str) -> str:
    """Validate and normalize ticker symbol. Raises HTTPException if invalid."""
    ticker = ticker.upper().strip()
    if not _TICKER_PATTERN.match(ticker):
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid ticker symbol: {ticker}. Must be 1-20 uppercase letters."
        )
    return ticker


def sanitize_for_json(obj):
    """
    Recursively convert numpy/pandas types to native Python types for JSON serialization.
    Prevents 'numpy.bool is not JSON serializable' errors.
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj) if not np.isnan(obj) else None
    elif isinstance(obj, np.ndarray):
        return sanitize_for_json(obj.tolist())
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, (pd.Series, pd.DataFrame)):
        return sanitize_for_json(obj.to_dict())
    elif pd.isna(obj):
        return None
    return obj


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients, removing dead connections."""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except WebSocketDisconnect:
                dead_connections.append(connection)
            except Exception as e:
                logger.warning(f"WebSocket broadcast error: {e}")
                dead_connections.append(connection)
        
        # Clean up dead connections
        for conn in dead_connections:
            self.disconnect(conn)


class SentinelEngine:
    """Singleton engine managing the trading system."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def initialize(self):
        if self._initialized:
            return
        
        logger.info("Initializing Sentinel Engine...")
        
        self.db = get_db(DATABASE_PATH)
        self.portfolio = PortfolioManager(data_dir="data")
        
        # Market data source - check if real Kite credentials are available
        # Note: Can use real market data even in paper trading mode
        self.use_real_kite = bool(
            os.getenv("KITE_API_KEY") and 
            os.getenv("KITE_ACCESS_TOKEN")
        )
        
        if self.use_real_kite:
            logger.info("Using REAL Zerodha Kite for market data")
            self.kite = RealKite()
            self.ticker = self.kite.create_ticker()
        else:
            logger.info("Using MOCK Kite for market data (paper trading)")
            self.kite = MockKite()
            self.ticker = MockTicker()
            self.kite.set_ticker(self.ticker)
        
        self.trading_mode = os.getenv("TRADING_MODE", "paper")  # "paper" or "live"
        self.executor = PaperTradeExecutor(
            kite=self.kite,
            db=self.db,
            slippage_pct=0.0005,
            default_quantity=10,
        )

        self.risk_manager = RiskManager(mtm_loss_limit=MTM_LOSS_LIMIT)
        # Use the full ConfluentSignalEngine (200 EMA + RSI crossover + VWAP)
        self.confluence_engine = ConfluentSignalEngine()
        # Smart ATR-based trailing stop (3-stage: initial → breakeven → trailing)
        self.trailing_stop = SmartTrailingStop(
            breakeven_threshold=float(os.getenv("STOP_LOSS_PCT", 0.01)),
            trailing_threshold=float(os.getenv("TAKE_PROFIT_PCT", 0.02)),
        )
        self.indicators = TechnicalIndicators()
        self.chart_gen = ChartGenerator(output_dir="charts")
        # Use real Gemini sentiment if API key available, else mock
        if GEMINI_API_KEY:
            self.sentiment = SentimentAnalyzer(api_key=GEMINI_API_KEY)
        else:
            self.sentiment = MockSentimentAnalyzer()
        self.vision = MockVisualAuditor()  # Optional - for external charts
        # Use real Gemini TechnicalAnalyst if API key available, else mock
        if GEMINI_API_KEY:
            self.technical_analyst = TechnicalAnalyst(api_key=GEMINI_API_KEY)
        else:
            self.technical_analyst = MockTechnicalAnalyst()
        self.use_vision = False  # Set True to use vision instead of direct analysis
        # Cache for watchlist suggestions (ticker -> suggestion dict)
        self._suggestions_cache: Optional[Dict] = None
        self._suggestions_cache_time: Optional[datetime] = None
        self._suggestions_ttl_minutes = 30
        
        # News scraper - use real feeds or mock for testing
        self.use_real_news = True  # Set False for mock news
        if self.use_real_news:
            self.news_scraper = NewsScraper(watchlist=self.portfolio.get_watchlist())
        else:
            self.news_scraper = MockNewsScraper(watchlist=self.portfolio.get_watchlist())
        self._news_cache: Dict[str, List] = {}  # Cache news per ticker
        
        self.running = False
        self.prices = {ticker: 0.0 for ticker in self.portfolio.get_watchlist()}
        self._trading_task = None
        self._last_analysis = {}

        # Per-ticker trading permission (True = engine may trade it, False = skip)
        self._permissions_file = Path("data/trading_permissions.json")
        self._trading_permissions: Dict[str, bool] = self._load_permissions()

        self._initialized = True

        logger.info(f"Engine initialized. Watchlist: {self.portfolio.get_watchlist()}")

    def _load_permissions(self) -> Dict[str, bool]:
        """Load trading permissions from file."""
        if self._permissions_file.exists():
            try:
                return json.loads(self._permissions_file.read_text())
            except Exception:
                pass
        return {}

    def _save_permissions(self):
        """Persist trading permissions to file."""
        self._permissions_file.parent.mkdir(exist_ok=True)
        self._permissions_file.write_text(json.dumps(self._trading_permissions))

    def is_trading_allowed(self, ticker: str) -> bool:
        """Return True if the engine is permitted to trade this ticker (default True)."""
        return self._trading_permissions.get(ticker, True)

    def set_trading_permission(self, ticker: str, allowed: bool):
        """Enable or disable trading for a ticker."""
        self._trading_permissions[ticker] = allowed
        self._save_permissions()
        logger.info(f"Trading {'enabled' if allowed else 'disabled'} for {ticker}")
    
    def get_watchlist(self) -> list:
        """Get current watchlist."""
        return self.portfolio.get_watchlist()
    
    def start(self):
        if not self.running:
            logger.info("Starting Sentinel Engine...")
            watchlist = self.get_watchlist()
            self.prices = {ticker: 0.0 for ticker in watchlist}
            self.ticker.subscribe([self.ticker.get_token(s) for s in watchlist])
            self.ticker.on_ticks = self._on_ticks
            self.ticker.connect(threaded=True)
            self.running = True
            # Start trading loop
            self._trading_task = asyncio.create_task(self._trading_loop())
            # Start news refresh loop
            self._news_task = asyncio.create_task(self._news_refresh_loop())
            logger.info(f"Engine started. Monitoring: {watchlist}")
    
    def stop(self):
        if self.running:
            logger.info("Stopping Sentinel Engine...")
            if self._trading_task:
                self._trading_task.cancel()
            if hasattr(self, '_news_task') and self._news_task:
                self._news_task.cancel()
            self.ticker.close()
            self.running = False
            logger.info("Engine stopped.")
    
    def _on_ticks(self, ws, ticks):
        for tick in ticks:
            token = tick['instrument_token']
            symbol = self.ticker.get_symbol(token)
            
            if symbol not in self.get_watchlist():
                continue
            
            price = tick['last_price']
            self.prices[symbol] = price
            self.portfolio.update_prices(self.prices)
            
            # Store candle data for analysis
            self._store_tick(symbol, tick)
    
    def _store_tick(self, symbol: str, tick: dict):
        """Store tick as candle data for indicator calculation."""
        try:
            self.db.insert_candle(
                ticker=symbol,
                timestamp=datetime.now(),
                open_=tick['last_price'],
                high=tick['last_price'],
                low=tick['last_price'],
                close=tick['last_price'],
                volume=tick.get('volume', 100)
            )
        except Exception as e:
            logger.warning(f"Tick store error for {symbol}: {e}")
    
    async def _trading_loop(self):
        """Main trading loop - analyzes signals and executes trades."""
        logger.info("Trading loop started - analyzing every 10 seconds")
        candle_count = 0
        _suggestions_triggered_today = False

        while self.running:
            try:
                await asyncio.sleep(10)  # Analyze every 10 seconds

                if not self.running:
                    break

                candle_count += 1
                now = datetime.now()
                logger.info(f"=== Trading Cycle #{candle_count} ===")

                # Auto-trigger suggestions scan at market open (9:15-9:20 AM)
                if (now.hour == 9 and 15 <= now.minute <= 20
                        and not _suggestions_triggered_today):
                    logger.info("Market open — triggering auto suggestions scan...")
                    asyncio.create_task(self._build_suggestions(force=True))
                    _suggestions_triggered_today = True
                # Reset daily flag after market close
                if now.hour >= 15 and now.minute >= 30:
                    _suggestions_triggered_today = False

                # Check risk limits first
                mtm_loss = self.db.get_mtm_loss()
                risk_state = self.risk_manager.get_state(mtm_loss)

                if risk_state.kill_switch_triggered:
                    logger.warning(f"KILL SWITCH ACTIVE! MTM Loss: ₹{mtm_loss:.2f}")
                    continue

                # Analyze each ticker in watchlist
                for ticker in self.get_watchlist():
                    await self._analyze_and_trade(ticker)

            except asyncio.CancelledError:
                logger.info("Trading loop cancelled")
                break
            except Exception as e:
                logger.error(f"Trading loop error: {e}", exc_info=True)
    
    async def _news_refresh_loop(self):
        """Background loop to periodically refresh news for all stocks."""
        logger.info("News refresh loop started - refreshing every 5 minutes")
        
        while self.running:
            try:
                # Refresh news immediately on first run, then every 5 minutes
                logger.info("Refreshing news feeds for all Nifty 50 stocks...")
                news_items = self.news_scraper.fetch_news(force=True)
                logger.info(f"News refresh complete: {len(news_items)} items fetched")
                
                await asyncio.sleep(300)  # 5 minutes
                
            except asyncio.CancelledError:
                logger.info("News refresh loop cancelled")
                break
            except Exception as e:
                logger.error(f"News refresh error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error before retry
    
    async def _analyze_and_trade(self, ticker: str):
        """Analyze a single ticker and execute trade if conditions met."""
        try:
            # Skip if user has disabled trading for this ticker
            if not self.is_trading_allowed(ticker):
                logger.debug(f"{ticker}: trading disabled by user — skipping")
                return

            # Need 210+ candles for EMA-200 to be reliable
            candles = self.db.get_candles(ticker, limit=250)

            if candles.empty or len(candles) < 20:
                logger.debug(f"{ticker}: Insufficient data ({len(candles)} candles)")
                return

            # Run confluence analysis (ConfluentSignalEngine)
            should_audit, confluence_result = self.confluence_engine.should_trigger_audit(candles, ticker)
            self._last_analysis[ticker] = {
                'signal': confluence_result.signal_type.value,
                'reason': confluence_result.reason,
                'confidence': confluence_result.confidence,
                'indicators': confluence_result.indicators,
                'conditions': confluence_result.conditions,
            }

            current_price = self.prices.get(ticker, 0)
            ind = confluence_result.indicators

            logger.info(
                f"{ticker}: Price=₹{current_price:.2f} | "
                f"RSI={ind.get('rsi', 0):.1f} | "
                f"Signal={confluence_result.signal_type.value} | "
                f"Conf={confluence_result.confidence:.2f} | "
                f"Reason={confluence_result.reason[:60]}"
            )

            # Check if we already have a position
            positions = self.db.get_all_positions()
            has_position = not positions.empty and ticker in positions['ticker'].values

            if has_position:
                await self._check_exit(ticker, current_price, confluence_result)
            elif should_audit:
                await self._execute_entry(ticker, current_price, confluence_result)

        except Exception as e:
            logger.error(f"Analysis error for {ticker}: {e}")
    
    async def _execute_entry(self, ticker: str, price: float, confluence_result):
        """Execute a new trade entry after Gemini audit."""
        logger.info(f">>> ENTRY SIGNAL for {ticker} at ₹{price:.2f}")

        # Sentiment check using real news headlines
        headlines = self.news_scraper.get_recent_headlines(ticker, limit=5)
        if not headlines:
            headlines = [f"No recent news for {ticker}"]
            logger.debug(f"{ticker}: No news found, using placeholder")
        else:
            logger.info(f"{ticker}: Found {len(headlines)} news headlines for sentiment analysis")

        sentiment = self.sentiment.analyze(ticker, headlines)
        logger.info(f"{ticker}: Sentiment score = {sentiment.score:.2f} ({sentiment.recommendation})")

        if sentiment.score < 0:
            logger.info(f"{ticker}: Skipping - negative sentiment")
            return

        # Technical analysis via Gemini TechnicalAnalyst
        candles = self.db.get_candles(ticker, limit=20)
        ind = confluence_result.indicators
        indicators_for_analyst = {**ind, 'current_price': price}

        tech_result = self.technical_analyst.analyze(ticker, candles, indicators_for_analyst)
        logger.info(f"{ticker}: Technical analysis = {tech_result.recommendation} "
                    f"(conf={tech_result.confidence:.2f}, pattern={tech_result.pattern_detected})")
        chart_safety = "SAFE" if tech_result.recommendation == "BUY" else "RISKY"
        pattern = tech_result.pattern_detected
        if tech_result.recommendation == "SELL":
            logger.info(f"{ticker}: Skipping - technical analysis says SELL")
            return
        if tech_result.recommendation == "HOLD" and tech_result.confidence < 0.5:
            logger.info(f"{ticker}: Skipping - low confidence HOLD")
            return

        # ATR-based position sizing
        atr = ind.get('atr', 0)
        portfolio = self.portfolio.get_portfolio()
        risk_per_trade = float(os.getenv("RISK_PER_TRADE", 500))
        if atr > 0:
            quantity = calculate_atr_position_size(
                total_capital=portfolio.get('total_value', 100000),
                risk_per_trade=risk_per_trade,
                atr=atr,
                price=price,
            )
        else:
            quantity = 10  # fallback
        quantity = max(1, quantity)

        cost = price * quantity
        if portfolio['available_cash'] < cost:
            logger.warning(f"{ticker}: Insufficient funds. Need ₹{cost:.2f}, have ₹{portfolio['available_cash']:.2f}")
            return

        # Determine trade side from confluence signal
        from src.trading.signals import SignalType
        side = "BUY" if confluence_result.signal_type == SignalType.LONG_ENTRY else "SELL"

        # Execute trade
        trade = self.executor.execute_entry(
            ticker=ticker,
            side=side,
            quantity=quantity,
            reason=f"{confluence_result.reason} | Pattern: {pattern}",
            sentiment_score=sentiment.score,
            chart_safety=chart_safety,
        )

        if trade:
            logger.info(f"✓ TRADE EXECUTED: {side} {quantity} {ticker} @ ₹{trade.entry_price:.2f}")
            self.portfolio.execute_buy(ticker, quantity, trade.entry_price)
            # Register with SmartTrailingStop
            self.trailing_stop.register_position(
                ticker=ticker,
                entry_price=trade.entry_price,
                entry_time=trade.entry_time,
                quantity=quantity,
                side=side,
                atr=atr if atr > 0 else trade.entry_price * 0.01,
            )
            await manager.broadcast({
                "type": "trade_executed",
                "data": {
                    "ticker": ticker, "side": side,
                    "price": trade.entry_price, "quantity": quantity,
                    "mode": self.trading_mode,
                }
            })
        else:
            logger.error(f"✗ Trade execution failed for {ticker}")

    async def _build_suggestions(self, force: bool = False) -> List[Dict]:
        """
        Scan Nifty 50 stocks and return AI-ranked suggestions.
        Uses Kite LTP/quote for live prices; enriches with candle-based indicators
        when local data exists. Results are cached for _suggestions_ttl_minutes.
        """
        from src.trading.portfolio import NIFTY_50 as _nifty_tickers

        # Check cache
        if not force and self._suggestions_cache is not None and self._suggestions_cache_time:
            age_min = (datetime.now() - self._suggestions_cache_time).total_seconds() / 60
            if age_min < self._suggestions_ttl_minutes:
                return self._suggestions_cache

        logger.info("Building watchlist suggestions — fetching live quotes for Nifty 50...")

        # ── Step 1: fetch live prices in bulk ──────────────────────────────────
        instruments = [f"NSE:{t}" for t in _nifty_tickers]
        quotes: Dict = {}
        try:
            if self.use_real_kite:
                raw_quotes = self.kite.quote(instruments)
                quotes = {k.replace("NSE:", ""): v for k, v in raw_quotes.items()}
            else:
                # Mock: use whatever prices are cached locally
                for t in _nifty_tickers:
                    if t in self.prices and self.prices[t] > 0:
                        quotes[t] = {"last_price": self.prices[t], "ohlc": {}, "volume": 0, "average_price": self.prices[t]}
        except Exception as e:
            logger.warning(f"Suggestions: could not fetch live quotes: {e}")

        scored = []
        for ticker in _nifty_tickers:
            try:
                q = quotes.get(ticker, {})
                price = float(q.get("last_price") or q.get("close") or 0)
                if price <= 0:
                    # Try local candle last close
                    candles_fb = self.db.get_candles(ticker, limit=5)
                    if not candles_fb.empty:
                        price = float(candles_fb['close'].iloc[-1])
                if price <= 0:
                    continue  # no price data at all, skip

                # ── Candle-based indicators (best-effort) ──────────────────
                rsi = 50.0
                vwap = price
                ema20 = price
                vol_ratio = 1.0
                vwap_score = 0.5
                ema_score = 0.5

                candles = self.db.get_candles(ticker, limit=50)
                if not candles.empty and len(candles) >= 14:
                    rsi_series = self.indicators.calculate_rsi(candles, 14)
                    ema20_series = self.indicators.calculate_ema(candles, 20)
                    vwap_series = self.indicators.calculate_vwap(candles)
                    vol_info = self.indicators.get_volume_spike_info(candles)

                    if not rsi_series.empty:
                        rsi = float(rsi_series.iloc[-1])
                    if not ema20_series.empty:
                        ema20 = float(ema20_series.iloc[-1])
                    if not vwap_series.empty:
                        vwap = float(vwap_series.iloc[-1])
                    vol_ratio = float(vol_info.get('ratio', 1.0))

                    vwap_score = 1.0 if price > vwap > 0 else 0.0
                    ema_score = 1.0 if price > ema20 > 0 else 0.0
                elif q:
                    # Use intraday OHLC for rough momentum
                    ohlc = q.get("ohlc", {})
                    day_open = float(ohlc.get("open") or price)
                    if day_open > 0:
                        vwap_score = 1.0 if price > day_open else 0.0
                        ema_score = vwap_score

                # Technical score
                rsi_score = min(max((rsi - 40) / 40, 0), 1)
                vol_score = min(vol_ratio / 3.0, 1.0)
                tech_score = rsi_score * 0.4 + vwap_score * 0.3 + ema_score * 0.3

                # Fast keyword sentiment (no API call — Gemini runs on top-10 only)
                headlines = self.news_scraper.get_recent_headlines(ticker, limit=5)
                sentiment_score = 0.5
                if headlines:
                    _pos = {'surge', 'rally', 'gain', 'rise', 'beat', 'strong', 'growth',
                            'profit', 'bullish', 'upgrade', 'buy', 'record', 'high', 'boost'}
                    _neg = {'fall', 'drop', 'loss', 'weak', 'miss', 'decline', 'cut',
                            'bearish', 'downgrade', 'sell', 'low', 'crash', 'concern', 'risk'}
                    combined_text = ' '.join(headlines).lower()
                    pos = sum(1 for w in _pos if w in combined_text)
                    neg = sum(1 for w in _neg if w in combined_text)
                    total = pos + neg
                    sentiment_score = (pos / total) if total > 0 else 0.5

                combined = tech_score * 0.4 + sentiment_score * 0.4 + vol_score * 0.2

                scored.append({
                    'ticker': ticker,
                    'name': ticker,
                    'sector': 'Nifty 50',
                    'price': round(price, 2),
                    'combined_score': round(combined, 3),
                    'technical_score': round(tech_score, 3),
                    'sentiment_score': round(sentiment_score, 3),
                    'volume_score': round(vol_score, 3),
                    'rsi': round(rsi, 1),
                    'pattern': None,
                    'reasoning': None,
                    'recommendation': None,
                })
            except Exception as e:
                logger.warning(f"Suggestions: error scoring {ticker}: {e}")

        # Sort by combined score, take top 10 for Gemini deep-analysis
        scored.sort(key=lambda x: x['combined_score'], reverse=True)
        top10 = scored[:10]

        logger.info(f"Top 10 candidates for Gemini analysis: {[s['ticker'] for s in top10]}")

        # Run TechnicalAnalyst on top 10
        for item in top10:
            try:
                candles = self.db.get_candles(item['ticker'], limit=20)
                ind = {
                    'rsi': item['rsi'],
                    'vwap': 0,
                    'ema20': 0,
                    'ema50': 0,
                    'current_price': item['price'],
                }
                result = self.technical_analyst.analyze(item['ticker'], candles, ind)
                item['pattern'] = result.pattern_detected
                item['reasoning'] = result.reasoning
                item['recommendation'] = result.recommendation
            except Exception as e:
                logger.warning(f"Suggestions: Gemini analysis failed for {item['ticker']}: {e}")
                item['pattern'] = 'N/A'
                item['reasoning'] = 'Analysis unavailable'
                item['recommendation'] = 'HOLD'

        # Broadcast to WebSocket clients
        await manager.broadcast({
            "type": "suggestions_ready",
            "count": len(top10),
            "timestamp": datetime.now().isoformat(),
        })

        self._suggestions_cache = top10
        self._suggestions_cache_time = datetime.now()
        logger.info(f"Suggestions built: {len(top10)} stocks scored and ranked")
        return top10

    async def _check_exit(self, ticker: str, current_price: float, confluence_result):
        """Check if we should exit an existing position using SmartTrailingStop."""
        positions = self.db.get_all_positions()
        pos = positions[positions['ticker'] == ticker].iloc[0]
        quantity = int(pos['quantity'])

        # Get EMA-9 for trailing stop
        candles = self.db.get_candles(ticker, limit=30)
        ema_9_series = self.indicators.calculate_ema_9(candles)
        ema_9 = float(ema_9_series.iloc[-1]) if not ema_9_series.empty else current_price

        # Update trailing stop (3-stage: initial ATR → breakeven → trailing EMA-9)
        new_sl, stop_stage, exit_signal = self.trailing_stop.update_stop(
            ticker=ticker,
            current_price=current_price,
            ema_9=ema_9,
            current_time=datetime.now(),
        )

        # Also check if candle closed below EMA-9 (trailing stage exit)
        if exit_signal is None and not candles.empty:
            candle_close = float(candles['close'].iloc[-1])
            exit_signal = self.trailing_stop.check_ema_exit(ticker, candle_close, ema_9)

        # Fallback: if position not registered with trailing stop, use percentage exits
        pos_state = self.trailing_stop.get_position(ticker)
        if pos_state is None:
            avg_price = float(pos['avg_price'])
            pnl_pct = ((current_price - avg_price) / avg_price) * 100
            from src.trading.signals import SignalType
            if pnl_pct >= float(os.getenv("TAKE_PROFIT_PCT", 0.02)) * 100:
                exit_signal = SignalType.EXIT_PROFIT
            elif pnl_pct <= -float(os.getenv("STOP_LOSS_PCT", 0.01)) * 100:
                exit_signal = SignalType.EXIT_STOP

        if exit_signal is not None:
            exit_reason = f"SmartStop: {exit_signal.value} (stage={stop_stage.value if hasattr(stop_stage,'value') else stop_stage})"
            logger.info(f"<<< EXIT SIGNAL for {ticker}: {exit_reason}")

            exits = self.executor.exit_by_ticker(ticker, reason=exit_reason)
            if exits:
                avg_price = float(pos['avg_price'])
                pnl = (current_price - avg_price) * quantity
                success, _ = self.portfolio.execute_sell(ticker, quantity, current_price)
                self.trailing_stop.remove_position(ticker)

                if success:
                    logger.info(f"✓ POSITION CLOSED: {ticker} P&L=₹{pnl:.2f}")
                    await manager.broadcast({
                        "type": "position_closed",
                        "data": {"ticker": ticker, "pnl": pnl, "reason": exit_reason}
                    })


# Global instances
manager = ConnectionManager()
engine = SentinelEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    engine.initialize()
    # Initial news fetch for all Nifty 50 stocks on startup
    try:
        logger.info("Initial news fetch on startup...")
        news_items = engine.news_scraper.fetch_news(force=True)
        logger.info(f"Startup news fetch complete: {len(news_items)} items")
    except Exception as e:
        logger.warning(f"Initial news fetch failed: {e}")
    yield
    engine.stop()


app = FastAPI(
    title="The Sentinel Dashboard API",
    description="Real-time trading dashboard for The Sentinel",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration - use environment variable for production
# Default allows all for development; set ALLOWED_ORIGINS in production
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
if _allowed_origins == ["*"]:
    logger.warning("CORS: Allowing all origins (set ALLOWED_ORIGINS env var for production)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Models
class TradeRequest(BaseModel):
    ticker: str
    side: str = "BUY"
    quantity: Optional[int] = None


class EngineControl(BaseModel):
    action: str  # start, stop, emergency_stop


# Pydantic Models for new endpoints
class WatchlistAction(BaseModel):
    ticker: str
    action: str  # add, remove


class CapitalRequest(BaseModel):
    amount: float


class CredentialUpdate(BaseModel):
    credential_type: str  # gemini, zerodha
    api_key: str
    api_secret: Optional[str] = None


def sanitize_floats(obj):
    """Replace NaN/Inf float values with 0 for JSON serialization."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(v) for v in obj]
    return obj


# REST API Endpoints
@app.get("/api/status")
async def get_status():
    """Get current engine status."""
    stats = engine.executor.get_stats()
    risk_state = engine.risk_manager.get_state(engine.db.get_mtm_loss())
    portfolio = engine.portfolio.get_portfolio()
    
    return sanitize_floats({
        "running": engine.running,
        "timestamp": datetime.now().isoformat(),
        "watchlist": engine.get_watchlist(),
        "prices": engine.prices,
        "stats": stats,
        "portfolio": portfolio,
        "trading_mode": engine.trading_mode,
        "risk": {
            "mtm_loss": risk_state.current_mtm_loss,
            "limit": MTM_LOSS_LIMIT,
            "kill_switch_triggered": risk_state.kill_switch_triggered,
            "market_open": engine.risk_manager.market_hours.is_market_open()
        }
    })


@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio details."""
    return engine.portfolio.get_portfolio()


@app.get("/api/holdings")
async def get_holdings():
    """Get current holdings — real Zerodha demat holdings when connected, else paper portfolio."""
    permissions = engine._trading_permissions

    if engine.use_real_kite:
        try:
            raw = engine.kite.holdings()
            holdings = []
            for h in raw:
                ticker = h.get("tradingsymbol", "")
                qty = h.get("quantity", 0) + h.get("t1_quantity", 0)
                avg = h.get("average_price", 0.0)
                ltp = h.get("last_price", avg)
                invested = qty * avg
                current = qty * ltp
                holdings.append({
                    "ticker": ticker,
                    "exchange": h.get("exchange", "NSE"),
                    "quantity": qty,
                    "avg_price": round(avg, 2),
                    "current_price": round(ltp, 2),
                    "invested_value": round(invested, 2),
                    "current_value": round(current, 2),
                    "pnl": round(current - invested, 2),
                    "pnl_percent": round(((ltp - avg) / avg * 100) if avg else 0, 2),
                    "day_change": round(h.get("day_change", 0.0), 2),
                    "day_change_percentage": round(h.get("day_change_percentage", 0.0), 2),
                    "product": h.get("product", "CNC"),
                    "isin": h.get("isin", ""),
                    "trading_allowed": permissions.get(ticker, True),
                })
            return {"holdings": holdings, "source": "zerodha", "count": len(holdings)}
        except Exception as e:
            logger.warning(f"Could not fetch Zerodha holdings: {e}")
            # fall through to paper

    # Paper portfolio holdings
    paper = engine.portfolio.get_holdings()
    for h in paper:
        h["trading_allowed"] = permissions.get(h["ticker"], True)
        h["source"] = "paper"
        h.setdefault("day_change", 0.0)
        h.setdefault("day_change_percentage", 0.0)
        h.setdefault("exchange", "NSE")
        h.setdefault("product", "PAPER")
        h.setdefault("isin", "")
    return {"holdings": paper, "source": "paper", "count": len(paper)}


class TradingPermissionRequest(BaseModel):
    allowed: bool = True


@app.post("/api/holdings/{ticker}/trading-permission")
async def set_holding_trading_permission(ticker: str, body: TradingPermissionRequest):
    """Enable or disable automated trading for a specific ticker."""
    allowed = body.allowed
    engine.set_trading_permission(ticker.upper(), allowed)
    await manager.broadcast({
        "type": "trading_permission_changed",
        "ticker": ticker.upper(),
        "allowed": allowed,
    })
    return {"success": True, "ticker": ticker.upper(), "trading_allowed": allowed}


@app.post("/api/portfolio/capital")
async def set_capital(request: CapitalRequest):
    """Set starting capital (resets portfolio)."""
    if request.amount < 10000:
        raise HTTPException(status_code=400, detail="Minimum capital is ₹10,000")
    
    success = engine.portfolio.set_capital(request.amount)
    if success:
        return {"success": True, "capital": request.amount}
    raise HTTPException(status_code=400, detail="Failed to set capital")


@app.post("/api/portfolio/reset")
async def reset_portfolio():
    """Reset portfolio to starting capital."""
    engine.portfolio.reset_portfolio()
    return {"success": True, "message": "Portfolio reset"}


@app.get("/api/watchlist")
async def get_watchlist():
    """Get current watchlist."""
    return {
        "watchlist": engine.get_watchlist(),
        "available": engine.portfolio.get_available_stocks()
    }


@app.post("/api/watchlist")
async def modify_watchlist(request: WatchlistAction):
    """Add or remove stock from watchlist."""
    ticker = request.ticker.upper()
    
    if request.action == "add":
        success = engine.portfolio.add_to_watchlist(ticker)
        if success:
            engine.prices[ticker] = 0.0
            await manager.broadcast({"type": "watchlist_updated", "watchlist": engine.get_watchlist()})
            return {"success": True, "action": "added", "ticker": ticker}
        raise HTTPException(status_code=400, detail=f"Cannot add {ticker}")
    
    elif request.action == "remove":
        success = engine.portfolio.remove_from_watchlist(ticker)
        if success:
            if ticker in engine.prices:
                del engine.prices[ticker]
            await manager.broadcast({"type": "watchlist_updated", "watchlist": engine.get_watchlist()})
            return {"success": True, "action": "removed", "ticker": ticker}
        raise HTTPException(status_code=400, detail=f"Cannot remove {ticker}")
    
    raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")


@app.get("/api/positions")
async def get_positions():
    """Get current positions."""
    positions = engine.db.get_all_positions()
    return {
        "positions": positions.to_dict('records') if not positions.empty else [],
        "count": len(positions)
    }


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    """Get recent trades."""
    trades = engine.db.get_todays_trades()
    if trades.empty:
        return {"trades": [], "count": 0}
    
    trades_list = trades.head(limit).to_dict('records')
    return {"trades": trades_list, "count": len(trades_list)}


@app.get("/api/pnl-history")
async def get_pnl_history(days: int = 30):
    """
    Return daily PnL, cumulative equity curve, and max drawdown data.

    Response shape:
    {
      "daily": [{"date": "2026-03-21", "pnl": 1200.0, "trades": 4, "win_rate": 75.0}],
      "equity": [{"date": "...", "equity": 101200.0}],
      "max_drawdown": 3.5,       # percentage
      "total_pnl": 4500.0,
      "starting_capital": 100000.0
    }
    """
    try:
        db = engine.db
        # Fetch all closed trades within the window
        cutoff = datetime.now() - timedelta(days=days)
        query = """
            SELECT
                CAST(exit_time AS DATE) AS trade_date,
                SUM(pnl)               AS daily_pnl,
                COUNT(*)               AS num_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins
            FROM trades
            WHERE status = 'CLOSED'
              AND exit_time >= ?
            GROUP BY trade_date
            ORDER BY trade_date ASC
        """
        try:
            df = db.conn.execute(query, [cutoff]).df()
        except Exception:
            return {"daily": [], "equity": [], "max_drawdown": 0.0,
                    "total_pnl": 0.0, "starting_capital": 100000.0}

        if df.empty:
            return {"daily": [], "equity": [], "max_drawdown": 0.0,
                    "total_pnl": 0.0, "starting_capital": 100000.0}

        from config.settings import STARTING_CAPITAL as BASE_CAP
        capital = BASE_CAP
        peak = capital
        max_dd = 0.0
        daily_rows = []
        equity_rows = []

        for _, row in df.iterrows():
            date_str = str(row['trade_date'])
            pnl = float(row['daily_pnl'])
            n = int(row['num_trades'])
            wins = int(row['wins'])
            capital += pnl
            peak = max(peak, capital)
            drawdown = (peak - capital) / peak * 100 if peak > 0 else 0.0
            max_dd = max(max_dd, drawdown)
            daily_rows.append({
                "date": date_str,
                "pnl": round(pnl, 2),
                "trades": n,
                "win_rate": round(wins / n * 100, 1) if n > 0 else 0.0,
            })
            equity_rows.append({"date": date_str, "equity": round(capital, 2)})

        total_pnl = capital - BASE_CAP
        return {
            "daily": daily_rows,
            "equity": equity_rows,
            "max_drawdown": round(max_dd, 2),
            "total_pnl": round(total_pnl, 2),
            "starting_capital": BASE_CAP,
        }
    except Exception as e:
        logger.error(f"pnl-history error: {e}")
        return {"daily": [], "equity": [], "max_drawdown": 0.0,
                "total_pnl": 0.0, "starting_capital": 100000.0}


@app.get("/api/candles/{ticker}")
async def get_candles(ticker: str, limit: int = 100):
    """Get candle data for a ticker."""
    if ticker not in WATCHLIST:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not in watchlist")
    
    candles = engine.db.get_candles(ticker, limit=limit)
    return {
        "ticker": ticker,
        "candles": candles.to_dict('records') if not candles.empty else [],
        "count": len(candles)
    }


@app.get("/api/news/sources")
async def get_news_sources():
    """Get list of configured news sources."""
    return {
        "sources": [
            {"name": name, "url": url}
            for name, url in engine.news_scraper.feeds
        ],
        "using_real_feeds": engine.use_real_news
    }


@app.get("/api/news/{ticker}")
async def get_news(ticker: str, limit: int = 10, refresh: bool = False):
    """Get news for a ticker from RSS feeds."""
    ticker = ticker.upper()
    
    try:
        # Fetch news from scraper (force refresh if requested)
        news_items = engine.news_scraper.fetch_news_for_ticker(ticker, force=refresh)[:limit]
        
        # Format for response
        news_list = [
            {
                "headline": item.headline,
                "source": item.source,
                "timestamp": item.timestamp.isoformat(),
                "link": item.link,
                "summary": item.summary[:200] if item.summary else "",
                "ticker": item.ticker
            }
            for item in news_items
        ]
        
        # Cache for sentiment analysis
        engine._news_cache[ticker] = news_items
        
        return {
            "ticker": ticker,
            "news": news_list,
            "count": len(news_list),
            "source_type": "real" if engine.use_real_news else "mock",
            "refreshed": refresh
        }
    except Exception as e:
        logger.error(f"Error fetching news for {ticker}: {e}")
        return {
            "ticker": ticker,
            "news": [],
            "count": 0,
            "error": str(e)
        }


@app.post("/api/news/{ticker}/refresh")
async def refresh_news(ticker: str):
    """Force refresh news for a ticker."""
    ticker = ticker.upper()
    return await get_news(ticker, limit=10, refresh=True)


@app.post("/api/news/toggle-source")
async def toggle_news_source():
    """Toggle between real RSS feeds and mock news."""
    engine.use_real_news = not engine.use_real_news
    watchlist = engine.portfolio.get_watchlist()
    if engine.use_real_news:
        engine.news_scraper = NewsScraper(watchlist=watchlist)
    else:
        engine.news_scraper = MockNewsScraper(watchlist=watchlist)
    return {
        "using_real_feeds": engine.use_real_news,
        "message": f"Switched to {'real RSS feeds' if engine.use_real_news else 'mock news'}"
    }


@app.get("/api/signals/{ticker}")
async def get_signals(ticker: str):
    """Get current signals for a ticker."""
    candles = engine.db.get_candles(ticker, limit=50)
    
    if candles.empty or len(candles) < 20:
        return {
            "ticker": ticker,
            "has_signal": False,
            "reason": "Insufficient data"
        }
    
    should_audit, analysis = engine.signal_engine.should_trigger_audit(candles)
    
    # Calculate indicators
    vwap = engine.indicators.calculate_vwap(candles)
    rsi = engine.indicators.calculate_rsi(candles, 14)
    ema = engine.indicators.calculate_ema(candles, 20)
    
    return {
        "ticker": ticker,
        "has_signal": should_audit,
        "analysis": analysis,
        "indicators": {
            "price": float(candles['close'].iloc[-1]),
            "vwap": float(vwap.iloc[-1]) if not vwap.empty else None,
            "rsi": float(rsi.iloc[-1]) if not rsi.empty else None,
            "ema20": float(ema.iloc[-1]) if not ema.empty else None
        }
    }


# =============================================================================
# Phase 2 Endpoints: Confluence, Heatmap, Schedule, Autopsy
# =============================================================================

@app.get("/api/signals/{ticker}/confluence")
async def get_confluence_status(ticker: str):
    """Get detailed multi-factor confluence status for a ticker."""
    from src.trading.signals import ConfluentSignalEngine
    
    ticker = ticker.upper()
    candles = engine.db.get_candles_by_interval(ticker, interval="5min", limit=250)
    
    if candles.empty or len(candles) < 50:
        return {
            "ticker": ticker,
            "confluence_met": False,
            "error": "Insufficient data for confluence analysis",
            "candle_count": len(candles) if not candles.empty else 0
        }
    
    # Use ConfluentSignalEngine for detailed analysis
    signal_engine = ConfluentSignalEngine()
    result = signal_engine.check_confluence(candles, ticker)
    
    # Calculate individual indicators
    ema_200 = engine.indicators.calculate_ema_200(candles)
    ema_9 = engine.indicators.calculate_ema_9(candles)
    rsi = engine.indicators.calculate_rsi(candles, 14)
    vwap = engine.indicators.calculate_vwap(candles)
    
    latest_price = float(candles['close'].iloc[-1])
    latest_ema_200 = float(ema_200.iloc[-1]) if not ema_200.empty and len(ema_200) > 0 else None
    latest_ema_9 = float(ema_9.iloc[-1]) if not ema_9.empty and len(ema_9) > 0 else None
    latest_rsi = float(rsi.iloc[-1]) if not rsi.empty and len(rsi) > 0 else None
    latest_vwap = float(vwap.iloc[-1]) if not vwap.empty and len(vwap) > 0 else None
    
    # Volume spike detection - convert numpy types to Python types
    volume_info = engine.indicators.get_volume_spike_info(candles)
    volume_data = {
        "is_spike": bool(volume_info.get('is_spike', False)),
        "current_volume": float(volume_info.get('current_volume', 0)) if volume_info.get('current_volume') else 0,
        "average_volume": float(volume_info.get('average_volume', 0)) if volume_info.get('average_volume') else 0,
        "ratio": float(volume_info.get('ratio', 0)) if volume_info.get('ratio') else 0
    }
    
    # Convert bools to native Python (avoid numpy.bool issues)
    ema_check = bool(latest_ema_200 is not None and latest_price > latest_ema_200)
    rsi_check = bool(latest_rsi is not None and latest_rsi > 60)
    vwap_check = bool(latest_vwap is not None and latest_price > latest_vwap)
    
    return sanitize_for_json({
        "ticker": ticker,
        "confluence_met": bool(result.is_valid),
        "signal_type": result.signal_type.value if result.signal_type else None,
        "confidence": float(result.confidence),
        "checks": {
            "ema_200": {
                "status": "✓" if ema_check else "✗",
                "value": latest_ema_200,
                "condition": "Price > 200 EMA",
                "met": ema_check
            },
            "rsi": {
                "status": "✓" if rsi_check else "✗",
                "value": latest_rsi,
                "condition": "RSI > 60 (Long)",
                "met": rsi_check
            },
            "vwap": {
                "status": "✓" if vwap_check else "✗",
                "value": latest_vwap,
                "condition": "Price > VWAP",
                "met": vwap_check
            }
        },
        "indicators": {
            "price": latest_price,
            "ema_200": latest_ema_200,
            "ema_9": latest_ema_9,
            "rsi": latest_rsi,
            "vwap": latest_vwap
        },
        "volume": volume_data,
        "timestamp": datetime.now().isoformat()
    })


@app.get("/api/sentiment/{ticker}")
async def get_sentiment(ticker: str):
    """Get Gemini sentiment analysis for a ticker based on recent news."""
    ticker = ticker.upper()
    
    try:
        # Fetch recent news for the ticker; auto-refresh if cache is stale or empty
        news_items = engine.news_scraper.fetch_news_for_ticker(ticker)
        headlines = [item.headline for item in news_items[:10] if item.headline]

        if not headlines:
            # Cache miss — force a full refresh and retry once
            logger.info(f"No cached news for {ticker}, triggering fresh fetch...")
            engine.news_scraper.fetch_news(force=True)
            news_items = engine.news_scraper.fetch_news_for_ticker(ticker, force=True)
            headlines = [item.headline for item in news_items[:10] if item.headline]

        if not headlines:
            return {
                "ticker": ticker,
                "score": 0.0,
                "confidence": 0.0,
                "reasoning": "No recent news headlines available for analysis",
                "recommendation": "NEUTRAL",
                "headlines_analyzed": 0,
                "source": "no_data"
            }
        
        # Call sentiment analyzer
        result = engine.sentiment.analyze(ticker, headlines)
        
        return {
            "ticker": ticker,
            "score": float(result.score),
            "confidence": float(result.confidence),
            "reasoning": result.reasoning,
            "key_factors": result.key_factors,
            "recommendation": result.recommendation,
            "headlines_analyzed": result.headlines_analyzed,
            "source": "mock" if "Mock" in type(engine.sentiment).__name__ else "gemini"
        }
    except Exception as e:
        logger.error(f"Sentiment analysis failed for {ticker}: {e}")
        return {
            "ticker": ticker,
            "score": 0.0,
            "confidence": 0.0,
            "reasoning": f"Analysis failed: {str(e)}",
            "recommendation": "NEUTRAL",
            "headlines_analyzed": 0,
            "source": "error"
        }


@app.get("/api/chart-data/{ticker}")
async def get_chart_data(ticker: str, interval: str = "5min", limit: int = 100):
    """Get OHLCV data with indicators for lightweight-charts."""
    ticker = ticker.upper()
    candles = engine.db.get_candles_by_interval(ticker, interval=interval, limit=limit)
    
    if candles.empty:
        return {
            "ticker": ticker,
            "candles": [],
            "indicators": {},
            "error": "No data available"
        }
    
    # Calculate indicators
    ema_200 = engine.indicators.calculate_ema_200(candles)
    ema_20 = engine.indicators.calculate_ema(candles, 20)
    ema_9 = engine.indicators.calculate_ema_9(candles)
    vwap = engine.indicators.calculate_vwap(candles)
    rsi = engine.indicators.calculate_rsi(candles, 14)
    
    # Format candles for lightweight-charts
    formatted_candles = []
    for _, row in candles.iterrows():
        formatted_candles.append({
            "time": int(row['timestamp'].timestamp()) if hasattr(row['timestamp'], 'timestamp') else int(row['timestamp']),
            "open": float(row['open']),
            "high": float(row['high']),
            "low": float(row['low']),
            "close": float(row['close']),
            "volume": int(row['volume']) if 'volume' in row else 0
        })
    
    # Format indicator series
    def format_series(series, candles_df):
        result = []
        for i, val in enumerate(series):
            if i < len(candles_df) and not pd.isna(val):
                ts = candles_df.iloc[i]['timestamp']
                result.append({
                    "time": int(ts.timestamp()) if hasattr(ts, 'timestamp') else int(ts),
                    "value": float(val)
                })
        return result
    
    return sanitize_for_json({
        "ticker": ticker,
        "interval": interval,
        "candles": formatted_candles,
        "indicators": {
            "ema_200": format_series(ema_200, candles),
            "ema_20": format_series(ema_20, candles),
            "ema_9": format_series(ema_9, candles),
            "vwap": format_series(vwap, candles),
            "rsi": format_series(rsi, candles)
        },
        "count": len(formatted_candles)
    })


@app.get("/api/schedule/phase")
async def get_trading_phase():
    """Get current trading phase and schedule info."""
    from src.trading.schedule import get_phase_manager
    
    phase_manager = get_phase_manager()
    return phase_manager.get_phase_info()


@app.get("/api/heatmap/nifty50")
async def get_nifty50_heatmap():
    """Get RSI and volume spike data for all Nifty 50 stocks."""
    from config.nifty50 import NIFTY_50, STOCKS_BY_SECTOR, SECTOR_ORDER
    
    heatmap_data = []
    sectors_data = {}
    
    for ticker, stock in NIFTY_50.items():
        candles = engine.db.get_candles(ticker, limit=30)
        
        if candles.empty or len(candles) < 20:
            rsi_value = None
            volume_spike = False
            price = 0.0
            ema_200_value = None
            vwap_value = None
        else:
            rsi = engine.indicators.calculate_rsi(candles, 14)
            rsi_value = float(rsi.iloc[-1]) if not rsi.empty and len(rsi) > 0 else None
            volume_info = engine.indicators.get_volume_spike_info(candles)
            volume_spike = bool(volume_info['is_spike'])  # Convert numpy.bool to Python bool
            price = float(candles['close'].iloc[-1])
            
            # Calculate 200 EMA and VWAP for new heatmap indicators
            ema_200 = engine.indicators.calculate_ema_200(candles)
            ema_200_value = float(ema_200.iloc[-1]) if not ema_200.empty and len(ema_200) > 0 else None
            
            vwap = engine.indicators.calculate_vwap(candles)
            vwap_value = float(vwap.iloc[-1]) if not vwap.empty and len(vwap) > 0 else None
        
        # Calculate distance percentages for heatmap coloring
        ema_200_distance_pct = None
        vwap_distance_pct = None
        in_vwap_pullback_zone = False
        above_ema_200 = None
        
        if price > 0 and ema_200_value and ema_200_value > 0:
            ema_200_distance_pct = ((price - ema_200_value) / ema_200_value) * 100
            above_ema_200 = price > ema_200_value
        
        if price > 0 and vwap_value and vwap_value > 0:
            vwap_distance_pct = ((price - vwap_value) / vwap_value) * 100
            # VWAP pullback zone: within 0.5% of VWAP (either side)
            in_vwap_pullback_zone = abs(vwap_distance_pct) <= 0.5
        
        # Determine RSI status
        if rsi_value is None:
            rsi_status = "neutral"
        elif rsi_value > 60:
            rsi_status = "bullish"
        elif rsi_value < 40:
            rsi_status = "bearish"
        else:
            rsi_status = "neutral"
        
        # Check if in active watchlist
        in_watchlist = ticker in engine.portfolio.get_watchlist()
        
        stock_data = {
            "ticker": ticker,
            "name": stock.name,
            "sector": stock.sector,
            "price": price,
            "rsi": rsi_value,
            "rsi_status": rsi_status,
            "volume_spike": volume_spike,
            "in_watchlist": in_watchlist,
            "weight": stock.weight,
            # New fields for enhanced heatmap
            "ema_200": ema_200_value,
            "ema_200_distance_pct": ema_200_distance_pct,
            "above_ema_200": above_ema_200,
            "vwap": vwap_value,
            "vwap_distance_pct": vwap_distance_pct,
            "in_vwap_pullback_zone": in_vwap_pullback_zone
        }
        
        heatmap_data.append(stock_data)
        
        # Group by sector
        if stock.sector not in sectors_data:
            sectors_data[stock.sector] = []
        sectors_data[stock.sector].append(stock_data)
    
    # Order sectors
    ordered_sectors = []
    for sector in SECTOR_ORDER:
        if sector in sectors_data:
            ordered_sectors.append({
                "name": sector,
                "stocks": sectors_data[sector]
            })
    
    return sanitize_for_json({
        "stocks": heatmap_data,
        "sectors": ordered_sectors,
        "timestamp": datetime.now().isoformat(),
        "total_stocks": len(heatmap_data)
    })


@app.get("/api/autopsy/daily")
async def get_daily_autopsy():
    """Get Gemini-generated daily autopsy report as Markdown."""
    from src.gemini.autopsy import PostTradeAutopsy
    
    api_key = os.getenv("GEMINI_API_KEY", "")
    
    if not api_key or api_key == "your_gemini_api_key_here":
        # Return mock report if no API key
        return {
            "markdown": _get_mock_autopsy_markdown(),
            "source": "mock",
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        autopsy = PostTradeAutopsy(api_key=api_key)
        
        # Try to get cached report first
        cached = autopsy.get_cached_markdown()
        if cached:
            return {
                "markdown": cached,
                "source": "cached",
                "timestamp": datetime.now().isoformat()
            }
        
        # Generate new report
        markdown = autopsy.generate_daily_markdown(engine.db)
        return {
            "markdown": markdown,
            "source": "generated",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Autopsy generation failed: {e}")
        return {
            "markdown": _get_mock_autopsy_markdown(),
            "source": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


def _get_mock_autopsy_markdown() -> str:
    """Return mock autopsy markdown when Gemini is unavailable."""
    today = datetime.now().strftime('%A, %B %d, %Y')
    return f"""# 📊 Daily Autopsy Report

**Date:** {today}

---

## Summary

*Gemini API not configured. This is a placeholder report.*

The trading engine monitored the configured watchlist but detailed AI analysis requires a valid Gemini API key.

---

## Quick Stats

| Metric | Value |
|--------|-------|
| **Trading Status** | Paper Trading |
| **API Status** | Mock Mode |

---

## Next Steps

1. Configure `GEMINI_API_KEY` in Settings
2. Test connection via the Settings panel
3. Run the engine during market hours for real analysis

---

*Report generated at {datetime.now().strftime('%H:%M:%S')} IST*
"""


class MTMLimitRequest(BaseModel):
    """Request model for MTM limit update."""
    limit: float


@app.get("/api/risk/mtm-limit")
async def get_mtm_limit():
    """Get current MTM loss limit configuration."""
    # Hardcoded ceiling from env
    mtm_ceiling_pct = float(os.getenv("MTM_LOSS_CEILING", "0.03"))
    starting_capital = float(os.getenv("STARTING_CAPITAL", "100000"))
    mtm_ceiling = mtm_ceiling_pct * starting_capital
    
    # User-configurable limit (can be lower than ceiling)
    user_limit = float(os.getenv("USER_MTM_LIMIT", str(mtm_ceiling)))
    
    # Effective limit is the lower of the two
    effective_limit = min(mtm_ceiling, user_limit)
    
    return {
        "ceiling_pct": mtm_ceiling_pct,
        "ceiling_amount": mtm_ceiling,
        "user_limit": user_limit,
        "effective_limit": effective_limit,
        "starting_capital": starting_capital,
        "current_mtm_loss": engine.db.get_mtm_loss()
    }


@app.post("/api/risk/mtm-limit")
async def set_mtm_limit(request: MTMLimitRequest):
    """Set user-configurable MTM loss limit."""
    # Get ceiling
    mtm_ceiling_pct = float(os.getenv("MTM_LOSS_CEILING", "0.03"))
    starting_capital = float(os.getenv("STARTING_CAPITAL", "100000"))
    mtm_ceiling = mtm_ceiling_pct * starting_capital
    
    # Validate: user limit cannot exceed ceiling
    if request.limit > mtm_ceiling:
        raise HTTPException(
            status_code=400,
            detail=f"User limit cannot exceed safety ceiling of ₹{mtm_ceiling:.2f}"
        )
    
    if request.limit < 500:
        raise HTTPException(
            status_code=400,
            detail="Minimum MTM limit is ₹500"
        )
    
    # Save to env
    set_key(str(ENV_FILE), "USER_MTM_LIMIT", str(request.limit))
    os.environ["USER_MTM_LIMIT"] = str(request.limit)
    
    # Update risk manager
    engine.risk_manager = RiskManager(mtm_loss_limit=request.limit)
    
    return {
        "success": True,
        "user_limit": request.limit,
        "effective_limit": min(mtm_ceiling, request.limit),
        "message": f"MTM limit set to ₹{request.limit:.2f}"
    }


@app.post("/api/trade")
async def execute_trade(request: TradeRequest):
    """Execute a manual trade."""
    if request.ticker not in WATCHLIST:
        raise HTTPException(status_code=400, detail=f"Ticker {request.ticker} not in watchlist")
    
    if not engine.running:
        raise HTTPException(status_code=400, detail="Engine not running")
    
    # Check risk
    if not engine.risk_manager.pre_order_check(engine.executor.get_mtm_pnl()):
        raise HTTPException(status_code=400, detail="Risk check failed")
    
    trade = engine.executor.execute_entry(
        ticker=request.ticker,
        side=request.side,
        reason="Manual trade from dashboard",
        quantity=request.quantity
    )
    
    if trade:
        await manager.broadcast({
            "type": "trade_executed",
            "data": {
                "ticker": trade.ticker,
                "side": trade.side,
                "entry_price": trade.entry_price,
                "quantity": trade.quantity
            }
        })
        return {"success": True, "trade_id": trade.trade_id}
    
    raise HTTPException(status_code=500, detail="Trade execution failed")


@app.post("/api/close/{ticker}")
async def close_position(ticker: str):
    """Close position for a ticker."""
    if ticker not in engine.get_watchlist():
        raise HTTPException(status_code=400, detail=f"Ticker {ticker} not in watchlist")
    
    # Use correct method name: exit_by_ticker instead of close_trade
    exits = engine.executor.exit_by_ticker(ticker, reason="Manual close from dashboard")
    
    if exits:
        await manager.broadcast({
            "type": "position_closed",
            "data": {"ticker": ticker, "exits": len(exits)}
        })
        return {"success": True, "ticker": ticker, "trades_closed": len(exits)}
    
    raise HTTPException(status_code=404, detail=f"No open position for {ticker}")


@app.post("/api/control")
async def control_engine(request: EngineControl):
    """Control the trading engine."""
    if request.action == "start":
        engine.start()
        await manager.broadcast({"type": "engine_started"})
        return {"success": True, "status": "running"}
    
    elif request.action == "stop":
        engine.stop()
        await manager.broadcast({"type": "engine_stopped"})
        return {"success": True, "status": "stopped"}
    
    elif request.action == "emergency_stop":
        engine.executor.close_all_trades("Emergency Stop")
        engine.stop()
        await manager.broadcast({"type": "emergency_stop"})
        return {"success": True, "status": "emergency_stopped"}
    
    raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")


@app.get("/api/chart/{ticker}")
async def get_chart(ticker: str):
    """Generate and return chart for a ticker."""
    if ticker not in WATCHLIST:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not in watchlist")
    
    candles = engine.db.get_candles(ticker, limit=50)
    if candles.empty:
        raise HTTPException(status_code=404, detail="No candle data available")
    
    vwap = engine.indicators.calculate_vwap(candles)
    ema = engine.indicators.calculate_ema(candles, 20)
    rsi = engine.indicators.calculate_rsi(candles, 14)
    
    chart_path = engine.chart_gen.generate_chart(
        candles, ticker, vwap=vwap, ema=ema, rsi=rsi
    )
    
    return FileResponse(chart_path, media_type="image/png")


# Connection Testing & Credential Management
# (ENV_FILE is defined at top of file)


@app.get("/api/credentials/status")
async def get_credentials_status():
    """Get current credentials status (masked)."""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    kite_key = os.getenv("KITE_API_KEY", "")
    kite_secret = os.getenv("KITE_API_SECRET", "")
    
    return {
        "gemini": {
            "configured": bool(gemini_key and gemini_key != "your_gemini_api_key_here"),
            "masked": f"***{gemini_key[-4:]}" if len(gemini_key) > 4 else "Not set"
        },
        "zerodha": {
            "configured": bool(kite_key and kite_key != "your_kite_api_key"),
            "api_key_masked": f"***{kite_key[-4:]}" if len(kite_key) > 4 else "Not set",
            "secret_masked": f"***{kite_secret[-4:]}" if len(kite_secret) > 4 else "Not set"
        }
    }


@app.post("/api/credentials/test/gemini")
async def test_gemini_connection():
    """Test Gemini API connection."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    
    if not api_key or api_key == "your_gemini_api_key_here":
        return {"success": False, "error": "Gemini API key not configured", "use_mock": True}
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content("Say 'OK' in one word.")
        return {
            "success": True,
            "message": "Gemini API connected successfully",
            "response": response.text[:50] if response.text else "OK"
        }
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "quota" in error_msg.lower():
            return {
                "success": False, 
                "error": "Rate limit exceeded. Using Mock mode for now.",
                "quota_exceeded": True,
                "use_mock": True
            }
        return {"success": False, "error": error_msg}


@app.post("/api/credentials/test/zerodha")
async def test_zerodha_connection():
    """Test Zerodha Kite API connection."""
    api_key = os.getenv("KITE_API_KEY", "")
    access_token = os.getenv("KITE_ACCESS_TOKEN", "")
    
    if not api_key or api_key == "your_kite_api_key":
        return {"success": False, "error": "Zerodha API key not configured"}
    
    # Show actual Kite type being used
    kite_type = type(engine.kite).__name__
    is_real = engine.use_real_kite
    
    if not access_token:
        return {
            "success": False,
            "error": "Access token not configured. Complete Zerodha login first.",
            "kite_type": kite_type
        }
    
    try:
        # Test actual connection using RealKite with SSL fix
        test_kite = RealKite(api_key=api_key, access_token=access_token)
        result = test_kite.test_connection()
        
        if result.get("success"):
            return {
                "success": True,
                "message": f"Connected as {result.get('user_name', 'Unknown')}",
                "kite_type": kite_type,
                "using_real_data": is_real,
                "mode": "paper" if os.getenv("TRADING_MODE", "paper") == "paper" else "live"
            }
        return {"success": False, "error": result.get("error", "Unknown error"), "kite_type": kite_type}
    except Exception as e:
        return {"success": False, "error": str(e), "kite_type": kite_type}


@app.get("/api/market-data/status")
async def get_market_data_status():
    """Get current market data source status."""
    return {
        "source": "real" if engine.use_real_kite else "mock",
        "kite_type": type(engine.kite).__name__,
        "ticker_type": type(engine.ticker).__name__,
        "is_connected": getattr(engine.ticker, 'is_connected', lambda: False)() if hasattr(engine.ticker, 'is_connected') else engine.running,
        "api_key_configured": bool(os.getenv("KITE_API_KEY")),
        "access_token_configured": bool(os.getenv("KITE_ACCESS_TOKEN")),
        "trading_mode": os.getenv("TRADING_MODE", "paper"),
    }


@app.post("/api/market-data/toggle")
async def toggle_market_data_source():
    """Toggle between Real and Mock Kite for market data."""
    if engine.running:
        return {
            "success": False,
            "error": "Cannot switch while engine is running. Stop the engine first."
        }
    
    # Check if we can switch to real Kite
    api_key = os.getenv("KITE_API_KEY")
    access_token = os.getenv("KITE_ACCESS_TOKEN")
    
    if not engine.use_real_kite:
        # Switching to Real Kite
        if not api_key or not access_token:
            return {
                "success": False,
                "error": "Cannot switch to Real Kite: API key or access token not configured"
            }
        
        engine.use_real_kite = True
        engine.kite = RealKite()
        engine.ticker = engine.kite.create_ticker()
        logger.info("Switched to REAL Zerodha Kite for market data")
    else:
        # Switching to Mock Kite
        engine.use_real_kite = False
        engine.kite = MockKite()
        engine.ticker = MockTicker()
        engine.kite.set_ticker(engine.ticker)
        logger.info("Switched to MOCK Kite for market data")
    
    # Update executor with new kite instance
    engine.executor = PaperTradeExecutor(
        kite=engine.kite,
        db=engine.db,
        slippage_pct=0.0005,
        default_quantity=10
    )
    
    return {
        "success": True,
        "source": "real" if engine.use_real_kite else "mock",
        "message": f"Switched to {'Real Zerodha Kite' if engine.use_real_kite else 'Mock Kite'}"
    }


# =============================================================================
# Trading Mode Toggle (Paper ↔ Live)
# =============================================================================

class TradingModeRequest(BaseModel):
    mode: str  # "paper" or "live"


@app.post("/api/trading-mode")
async def set_trading_mode(request: TradingModeRequest):
    """Switch order execution between paper and live mode at runtime."""
    mode = request.mode.lower()
    if mode not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'paper' or 'live'")

    if mode == "live":
        api_key = os.getenv("KITE_API_KEY")
        access_token = os.getenv("KITE_ACCESS_TOKEN")
        if not api_key or not access_token:
            raise HTTPException(
                status_code=400,
                detail="Cannot switch to Live mode: KITE_API_KEY and KITE_ACCESS_TOKEN must be set"
            )
        engine.executor = LiveTradeExecutor(kite=engine.kite, db=engine.db)
        logger.info("Switched to LIVE order execution (real Zerodha orders)")
    else:
        engine.executor = PaperTradeExecutor(
            kite=engine.kite, db=engine.db, slippage_pct=0.0005, default_quantity=10
        )
        logger.info("Switched to PAPER order execution (simulated)")

    engine.trading_mode = mode
    set_key(str(ENV_FILE), "TRADING_MODE", mode)
    os.environ["TRADING_MODE"] = mode

    await manager.broadcast({"type": "mode_changed", "mode": mode})
    return {"success": True, "mode": mode}


@app.get("/api/trading-mode")
async def get_trading_mode():
    """Get current trading mode."""
    return {
        "mode": engine.trading_mode,
        "live_ready": bool(os.getenv("KITE_API_KEY") and os.getenv("KITE_ACCESS_TOKEN")),
    }


# =============================================================================
# AI Watchlist Suggestions
# =============================================================================

@app.get("/api/watchlist/suggestions")
async def get_watchlist_suggestions(force: bool = False):
    """
    Return Gemini-ranked Nifty 50 stock suggestions.
    Runs a fresh scan when force=true or cache is expired (30 min TTL).
    """
    try:
        suggestions = await engine._build_suggestions(force=force)
        cache_age_min = None
        if engine._suggestions_cache_time:
            cache_age_min = round((datetime.now() - engine._suggestions_cache_time).total_seconds() / 60, 1)
        return {
            "suggestions": suggestions,
            "count": len(suggestions),
            "cached": not force and cache_age_min is not None and cache_age_min < engine._suggestions_ttl_minutes,
            "cache_age_minutes": cache_age_min,
            "last_scan": engine._suggestions_cache_time.isoformat() if engine._suggestions_cache_time else None,
            "watchlist": engine.get_watchlist(),
        }
    except Exception as e:
        logger.error(f"Suggestions endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Risk Settings
# =============================================================================

class RiskSettingsRequest(BaseModel):
    take_profit_pct: Optional[float] = None   # e.g. 0.02 = 2%
    stop_loss_pct: Optional[float] = None     # e.g. 0.01 = 1%
    risk_per_trade: Optional[float] = None    # e.g. 500 (INR)
    mtm_limit: Optional[float] = None        # kill-switch threshold


@app.post("/api/settings/risk")
async def update_risk_settings(request: RiskSettingsRequest):
    """Update runtime risk parameters."""
    updated = {}

    if request.take_profit_pct is not None:
        if not 0.005 <= request.take_profit_pct <= 0.20:
            raise HTTPException(status_code=400, detail="take_profit_pct must be 0.5%–20%")
        set_key(str(ENV_FILE), "TAKE_PROFIT_PCT", str(request.take_profit_pct))
        os.environ["TAKE_PROFIT_PCT"] = str(request.take_profit_pct)
        engine.trailing_stop.trailing_threshold = request.take_profit_pct
        updated["take_profit_pct"] = request.take_profit_pct

    if request.stop_loss_pct is not None:
        if not 0.002 <= request.stop_loss_pct <= 0.10:
            raise HTTPException(status_code=400, detail="stop_loss_pct must be 0.2%–10%")
        set_key(str(ENV_FILE), "STOP_LOSS_PCT", str(request.stop_loss_pct))
        os.environ["STOP_LOSS_PCT"] = str(request.stop_loss_pct)
        engine.trailing_stop.breakeven_threshold = request.stop_loss_pct
        updated["stop_loss_pct"] = request.stop_loss_pct

    if request.risk_per_trade is not None:
        if not 100 <= request.risk_per_trade <= 50000:
            raise HTTPException(status_code=400, detail="risk_per_trade must be ₹100–₹50,000")
        set_key(str(ENV_FILE), "RISK_PER_TRADE", str(request.risk_per_trade))
        os.environ["RISK_PER_TRADE"] = str(request.risk_per_trade)
        updated["risk_per_trade"] = request.risk_per_trade

    if request.mtm_limit is not None:
        ceiling = float(os.getenv("MTM_LOSS_CEILING", "0.03")) * float(os.getenv("STARTING_CAPITAL", "100000"))
        if request.mtm_limit > ceiling:
            raise HTTPException(status_code=400, detail=f"mtm_limit cannot exceed ceiling ₹{ceiling:.0f}")
        engine.risk_manager = RiskManager(mtm_loss_limit=request.mtm_limit)
        set_key(str(ENV_FILE), "MTM_LOSS_LIMIT", str(request.mtm_limit))
        os.environ["MTM_LOSS_LIMIT"] = str(request.mtm_limit)
        updated["mtm_limit"] = request.mtm_limit

    return {"success": True, "updated": updated}


@app.get("/api/settings/risk")
async def get_risk_settings():
    """Get current risk parameter values."""
    return {
        "take_profit_pct": float(os.getenv("TAKE_PROFIT_PCT", 0.02)),
        "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", 0.01)),
        "risk_per_trade": float(os.getenv("RISK_PER_TRADE", 500)),
        "mtm_limit": float(os.getenv("MTM_LOSS_LIMIT", 5000)),
        "trailing_stop_stage": {
            ticker: state.stop_stage.value
            for ticker, state in engine.trailing_stop.get_all_positions().items()
        },
    }


@app.post("/api/market-data/test-connection")
async def test_real_kite_connection():
    """Test the real Kite API connection."""
    api_key = os.getenv("KITE_API_KEY")
    access_token = os.getenv("KITE_ACCESS_TOKEN")
    
    if not api_key:
        return {"success": False, "error": "KITE_API_KEY not configured"}
    
    if not access_token:
        return {"success": False, "error": "KITE_ACCESS_TOKEN not configured. Need to complete Zerodha login flow."}
    
    try:
        test_kite = RealKite(api_key=api_key, access_token=access_token)
        result = test_kite.test_connection()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/zerodha/login-url")
async def get_zerodha_login_url():
    """Get the Zerodha Kite login URL."""
    api_key = os.getenv("KITE_API_KEY")
    
    if not api_key:
        return {"success": False, "error": "KITE_API_KEY not configured"}
    
    try:
        # Use RealKite which has SSL fix
        kite = RealKite(api_key=api_key)
        login_url = kite.login_url()
        return {
            "success": True,
            "login_url": login_url,
            "instructions": "Open this URL in browser, login with Zerodha credentials, and copy the request_token from the redirect URL"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/zerodha/generate-session")
async def generate_zerodha_session(request_token: str):
    """Generate access token from request token after login."""
    api_key = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")
    
    if not api_key or not api_secret:
        return {"success": False, "error": "KITE_API_KEY or KITE_API_SECRET not configured"}
    
    try:
        # Use RealKite which has SSL fix
        kite = RealKite(api_key=api_key)
        data = kite.generate_session(request_token, api_secret)
        
        access_token = data.get("access_token")
        if access_token:
            # Save to .env file
            set_key(str(ENV_FILE), "KITE_ACCESS_TOKEN", access_token)
            os.environ["KITE_ACCESS_TOKEN"] = access_token
            
            return {
                "success": True,
                "message": "Access token generated and saved",
                "user_id": data.get("user_id"),
                "user_name": data.get("user_name"),
                "email": data.get("email"),
            }
        return {"success": False, "error": "No access token in response"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/credentials/update")
async def update_credentials(request: CredentialUpdate):
    """Update API credentials in .env file."""
    if not ENV_FILE.exists():
        # Create .env from template
        ENV_FILE.write_text("""# The Sentinel Configuration
GEMINI_API_KEY=your_gemini_api_key_here
KITE_API_KEY=your_kite_api_key
KITE_API_SECRET=your_kite_api_secret
KITE_ACCESS_TOKEN=
TRADING_MODE=paper
""")
    
    try:
        if request.credential_type == "gemini":
            set_key(str(ENV_FILE), "GEMINI_API_KEY", request.api_key)
            os.environ["GEMINI_API_KEY"] = request.api_key
            return {"success": True, "message": "Gemini API key updated"}
        
        elif request.credential_type == "zerodha":
            set_key(str(ENV_FILE), "KITE_API_KEY", request.api_key)
            os.environ["KITE_API_KEY"] = request.api_key
            if request.api_secret:
                set_key(str(ENV_FILE), "KITE_API_SECRET", request.api_secret)
                os.environ["KITE_API_SECRET"] = request.api_secret
            return {"success": True, "message": "Zerodha credentials updated"}
        
        raise HTTPException(status_code=400, detail=f"Unknown credential type: {request.credential_type}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update credentials: {str(e)}")


# Zerodha OAuth Endpoints
@app.get("/api/zerodha/login")
async def zerodha_login():
    """Generate Zerodha login URL."""
    api_key = os.getenv("KITE_API_KEY", "")
    if not api_key or api_key == "your_kite_api_key":
        raise HTTPException(status_code=400, detail="Zerodha API key not configured")
    
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    return {"login_url": login_url}


@app.get("/api/zerodha/callback")
async def zerodha_callback(request_token: str = None, status: str = None):
    """Handle Zerodha OAuth callback after login. Returns an HTML page so the user
    sees a clear result and the tab can be closed."""
    from fastapi.responses import HTMLResponse

    def _html(title: str, colour: str, heading: str, body: str) -> HTMLResponse:
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>{title}</title>
  <style>
    body{{margin:0;background:#111827;color:#f9fafb;font-family:sans-serif;
         display:flex;align-items:center;justify-content:center;height:100vh}}
    .card{{background:#1f2937;border:1px solid #374151;border-radius:12px;
           padding:2rem 2.5rem;max-width:420px;text-align:center}}
    .icon{{font-size:3rem;margin-bottom:1rem}}
    h1{{margin:0 0 .5rem;font-size:1.4rem;color:{colour}}}
    p{{color:#9ca3af;margin:.5rem 0}}
    .close{{margin-top:1.5rem;font-size:.85rem;color:#6b7280}}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{heading}</div>
    <h1>{title}</h1>
    {body}
    <p class="close">You can close this tab and return to Sentinel.</p>
  </div>
  <script>
    // Auto-close after 4 seconds if opened by script
    if (window.opener) {{
      setTimeout(() => window.close(), 4000);
    }}
  </script>
</body>
</html>"""
        return HTMLResponse(content=html)

    if status == "error" or not request_token:
        return _html(
            "Login Failed", "#ef4444", "✗",
            "<p>Zerodha login was cancelled or failed.</p><p>Please try again from Sentinel.</p>"
        )

    api_key = os.getenv("KITE_API_KEY", "")
    api_secret = os.getenv("KITE_API_SECRET", "")

    if not api_key or not api_secret:
        return _html(
            "Not Configured", "#f59e0b", "⚠️",
            "<p>KITE_API_KEY or KITE_API_SECRET is not saved.</p><p>Save them in Sentinel Settings first.</p>"
        )

    try:
        kite = RealKite(api_key=api_key)
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]

        set_key(str(ENV_FILE), "KITE_ACCESS_TOKEN", access_token)
        os.environ["KITE_ACCESS_TOKEN"] = access_token

        user_name = data.get("user_name", "Unknown")
        return _html(
            "Connected!", "#22c55e", "✓",
            f"<p>Logged in as <strong style='color:#f9fafb'>{user_name}</strong></p>"
            f"<p>Access token saved to Sentinel.</p>"
        )
    except Exception as e:
        return _html(
            "Token Exchange Failed", "#ef4444", "✗",
            f"<p>{str(e)}</p><p>Check your API Secret in Sentinel Settings and try again.</p>"
        )


@app.post("/api/zerodha/postback")
async def zerodha_postback(request: Dict[str, Any]):
    """Handle Zerodha order postback webhooks."""
    # Log postback for debugging
    import logging
    logging.info(f"Zerodha postback: {request}")
    return {"status": "received"}


# WebSocket for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    
    try:
        while True:
            # Send periodic updates
            stats = engine.executor.get_stats()
            
            await websocket.send_json({
                "type": "tick",
                "timestamp": datetime.now().isoformat(),
                "prices": engine.prices,
                "stats": stats,
                "running": engine.running
            })
            
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# Serve frontend (if exists)
frontend_path = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    # Security: Default to localhost, allow override via environment for production
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
