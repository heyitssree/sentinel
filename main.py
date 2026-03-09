"""
The Sentinel: Multimodal Alpha Engine
Main orchestrator with heartbeat loop.

This is the primary entry point for the trading engine.
Run during market hours: 9:15 AM - 3:30 PM IST
"""
import sys
import time
import signal
import logging
import threading
import asyncio
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import (
    GEMINI_API_KEY, WATCHLIST, DATABASE_PATH,
    MTM_LOSS_LIMIT, SLIPPAGE_PCT, DEFAULT_QUANTITY,
    CANDLE_INTERVAL_SECONDS, LOG_LEVEL, LOG_FORMAT
)
from src.storage.db import SentinelDB, get_db
from src.ingestion.mock_kite import MockKite, MockTicker
from src.ingestion.news_scraper import NewsScraper, MockNewsScraper
from src.signals.indicators import TechnicalIndicators
from src.trading.signals import ConfluentSignalEngine, SmartTrailingStop
from src.gemini.regime_detector import RegimeDetector, MockRegimeDetector
from src.charts.generator import ChartGenerator
from src.gemini.sentiment import SentimentAnalyzer, MockSentimentAnalyzer
from src.gemini.vision import VisualAuditor, MockVisualAuditor
from src.gemini.autopsy import PostTradeAutopsy, MockPostTradeAutopsy
from src.trading.executor import PaperTradeExecutor
from src.trading.risk import RiskManager

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('sentinel.log')
    ]
)
logger = logging.getLogger(__name__)


class Sentinel:
    """
    The Sentinel: Multimodal Alpha Engine
    
    A high-availability paper trading pipeline that integrates:
    - Mock Zerodha WebSocket for tick data
    - DuckDB for time-series storage
    - Gemini 2.0 Flash for sentiment and vision analysis
    - Technical indicators (VWAP, RSI, EMA)
    - Risk management with hard-coded kill switch
    """
    
    def __init__(self, use_mock_gemini: bool = False):
        """
        Initialize The Sentinel.
        
        Args:
            use_mock_gemini: Use mock Gemini analyzers (for testing without API)
        """
        logger.info("=" * 60)
        logger.info("🛡️  THE SENTINEL - Multimodal Alpha Engine")
        logger.info("=" * 60)
        
        self.use_mock_gemini = use_mock_gemini
        self._running = False
        self._shutdown_requested = False
        
        # Initialize components
        self._init_database()
        self._init_kite()
        self._init_analyzers()
        self._init_trading()
        
        # Candle aggregation with thread-safe access
        self._candle_data = {ticker: [] for ticker in WATCHLIST}
        self._last_candle_time = {ticker: None for ticker in WATCHLIST}
        self._candle_lock = threading.Lock()  # Protects _candle_data and _last_candle_time
        
        # ThreadPoolExecutor for parallel ticker analysis
        self._executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="sentinel_analysis")
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("Sentinel initialized successfully")
    
    def _init_database(self):
        """Initialize DuckDB connection."""
        self.db = get_db(DATABASE_PATH)
        logger.info(f"Database initialized: {DATABASE_PATH}")
    
    def _init_kite(self):
        """Initialize Mock Kite components."""
        self.ticker = MockTicker()
        self.kite = MockKite()
        self.kite.set_ticker(self.ticker)
        
        # Setup tick handler
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_connect = lambda ws, resp: logger.info("Ticker connected")
        self.ticker.on_close = lambda ws, code, reason: logger.info(f"Ticker closed: {reason}")
        
        logger.info("Mock Kite initialized")
    
    def _init_analyzers(self):
        """Initialize analysis components."""
        # Signal engine - using new ConfluentSignalEngine with VWAP pullback logic
        self.signal_engine = ConfluentSignalEngine()
        self.indicators = TechnicalIndicators()
        
        # Regime detector for market condition awareness
        if self.use_mock_gemini or not GEMINI_API_KEY:
            self.regime_detector = MockRegimeDetector()
        else:
            self.regime_detector = RegimeDetector(GEMINI_API_KEY)
        
        # Chart generator
        self.chart_gen = ChartGenerator(output_dir="charts")
        
        # News scraper
        self.news_scraper = MockNewsScraper(watchlist=WATCHLIST)
        
        # Gemini components
        if self.use_mock_gemini or not GEMINI_API_KEY:
            logger.warning("Using mock Gemini analyzers")
            self.sentiment = MockSentimentAnalyzer()
            self.vision = MockVisualAuditor()
            self.autopsy = MockPostTradeAutopsy()
        else:
            self.sentiment = SentimentAnalyzer(GEMINI_API_KEY)
            self.vision = VisualAuditor(GEMINI_API_KEY)
            self.autopsy = PostTradeAutopsy(GEMINI_API_KEY)
        
        logger.info("Analyzers initialized")
    
    def _init_trading(self):
        """Initialize trading components."""
        # Risk manager with kill switch callback
        self.risk_manager = RiskManager(
            mtm_loss_limit=MTM_LOSS_LIMIT,
            on_kill_switch=self._on_kill_switch
        )
        
        # Paper trade executor
        self.executor = PaperTradeExecutor(
            kite=self.kite,
            db=self.db,
            slippage_pct=SLIPPAGE_PCT,
            default_quantity=DEFAULT_QUANTITY
        )
        
        # Smart trailing stop manager for dynamic stop loss management
        self.trailing_stop = SmartTrailingStop()
        
        logger.info(f"Trading initialized | Kill switch: ₹{MTM_LOSS_LIMIT}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self._shutdown_requested = True
    
    def _on_kill_switch(self, reason: str):
        """Handle kill switch trigger."""
        logger.critical(f"Kill switch triggered: {reason}")
        logger.critical("Closing all positions...")
        
        try:
            self.executor.close_all_trades("Kill Switch")
            self.ticker.close()
        except Exception as e:
            logger.error(f"Error during emergency shutdown: {e}")
        
        self._running = False
    
    def _on_ticks(self, ws, ticks):
        """Handle incoming ticks from WebSocket."""
        for tick in ticks:
            token = tick['instrument_token']
            symbol = self.ticker.get_symbol(token)
            
            if symbol not in WATCHLIST:
                continue
            
            # Aggregate tick into candle
            self._aggregate_tick(symbol, tick)
    
    def _aggregate_tick(self, symbol: str, tick: dict):
        """Aggregate tick data into candles. Thread-safe."""
        now = datetime.now()
        candle_start = now.replace(
            minute=(now.minute // 5) * 5,
            second=0,
            microsecond=0
        )
        
        with self._candle_lock:
            if self._last_candle_time.get(symbol) != candle_start:
                # New candle period
                if self._candle_data[symbol]:
                    # Save previous candle (lock already held)
                    self._save_candle_locked(symbol)
                
                # Start new candle
                self._candle_data[symbol] = []
                self._last_candle_time[symbol] = candle_start
            
            # Add tick to current candle
            self._candle_data[symbol].append({
                'price': tick['last_price'],
                'volume': tick.get('last_traded_quantity', 0),
                'timestamp': now
            })
    
    def _save_candle_locked(self, symbol: str):
        """Save aggregated candle to database. Must be called with _candle_lock held."""
        ticks = self._candle_data[symbol]
        if not ticks:
            return
        
        prices = [t['price'] for t in ticks]
        volumes = [t['volume'] for t in ticks]
        
        candle = {
            'ticker': symbol,
            'timestamp': self._last_candle_time[symbol],
            'open': prices[0],
            'high': max(prices),
            'low': min(prices),
            'close': prices[-1],
            'volume': sum(volumes)
        }
        
        # Calculate VWAP
        total_pv = sum(p * v for p, v in zip(prices, volumes))
        total_vol = sum(volumes)
        candle['vwap'] = total_pv / total_vol if total_vol > 0 else prices[-1]
        
        self.db.insert_candle(**candle)
    
    def _save_candle(self, symbol: str):
        """Save aggregated candle to database. Thread-safe wrapper."""
        with self._candle_lock:
            self._save_candle_locked(symbol)
    
    def _fetch_news(self, ticker: str):
        """Fetch and store news for a ticker."""
        try:
            news_items = self.news_scraper.fetch_news_for_ticker(ticker)
            for item in news_items[:5]:
                self.db.insert_news(
                    ticker=item.ticker,
                    timestamp=item.timestamp,
                    headline=item.headline,
                    source=item.source
                )
        except Exception as e:
            logger.warning(f"News fetch failed for {ticker}: {e}")
    
    def _analyze_ticker(self, ticker: str) -> bool:
        """
        Run full analysis pipeline for a ticker.
        
        Returns:
            True if a trade was executed
        """
        # Get candle data
        candles = self.db.get_candles(ticker, limit=50)
        if candles.empty or len(candles) < 20:
            logger.debug(f"Insufficient data for {ticker}: {len(candles)} candles")
            return False
        
        # Check if already in position
        if self.executor.has_position(ticker):
            # Check stop loss / take profit
            self.executor.check_stop_loss_take_profit()
            return False
        
        # Run signal analysis with new ConfluentSignalEngine
        should_audit, analysis = self.signal_engine.should_trigger_audit(candles, ticker)
        
        if not should_audit:
            logger.debug(f"{ticker}: No signal | {analysis.reason}")
            return False
        
        # Determine trade side from signal type
        side = "BUY" if analysis.signal_type.name == "LONG_ENTRY" else "SELL"
        
        logger.info(f"🔔 {ticker}: {side} Signal detected! Running Gemini audit...")
        
        # Feature A: Sentiment Analysis
        headlines = self.db.get_recent_news(ticker, limit=10)
        headline_list = headlines['headline'].tolist() if not headlines.empty else []
        
        proceed_sentiment, sentiment_result = self.sentiment.should_proceed_with_trade(
            ticker, headline_list
        )
        
        if not proceed_sentiment:
            logger.info(f"❌ {ticker}: Blocked by sentiment ({sentiment_result.score:.2f})")
            return False
        
        logger.info(f"✅ {ticker}: Sentiment OK ({sentiment_result.score:.2f})")
        
        # Feature B: Visual Analysis
        # Generate chart
        vwap = self.indicators.calculate_vwap(candles)
        ema = self.indicators.calculate_ema(candles, 20)
        rsi = self.indicators.calculate_rsi(candles, 14)
        
        chart_path = self.chart_gen.generate_chart(
            candles, ticker, vwap=vwap, ema=ema, rsi=rsi
        )
        
        is_safe, vision_result = self.vision.is_safe_to_enter(ticker, chart_path)
        
        if not is_safe:
            logger.info(f"❌ {ticker}: Blocked by visual audit ({vision_result.safety})")
            return False
        
        logger.info(f"✅ {ticker}: Visual audit SAFE ({vision_result.pattern_detected})")
        
        # Execute trade
        if not self.risk_manager.pre_order_check(self.executor.get_mtm_pnl()):
            logger.warning(f"Trade blocked by risk manager")
            return False
        
        # Calculate dynamic ATR-based stops
        atr = self.indicators.calculate_atr(candles, 14)
        latest_atr = atr.iloc[-1] if not atr.empty else candles['close'].iloc[-1] * 0.02
        entry_price = candles['close'].iloc[-1]
        stop_loss, take_profit = self.signal_engine.calculate_dynamic_stops(
            entry_price=entry_price, atr=latest_atr, side=side
        )
        
        trade = self.executor.execute_entry(
            ticker=ticker,
            side=side,
            reason=analysis.reason,
            sentiment_score=sentiment_result.score,
            chart_safety=vision_result.safety,
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        
        if trade:
            self.risk_manager.post_order_record()
            # Register position with smart trailing stop manager
            self.trailing_stop.register_position(
                ticker=ticker,
                entry_price=trade.entry_price,
                entry_time=trade.entry_time,
                quantity=trade.quantity,
                side=trade.side,
                atr=latest_atr
            )
            logger.info(f"🚀 TRADE EXECUTED: {side} {ticker} @ ₹{trade.entry_price:.2f}")
            logger.info(f"   SL: ₹{stop_loss:.2f} | TP: ₹{take_profit:.2f}")
            return True
        
        return False
    
    def _process_tickers_parallel(self, tickers: List[str]) -> List[Tuple[str, bool, any]]:
        """
        Process tickers in parallel using ThreadPoolExecutor.
        Async-ready: Can be replaced with asyncio.gather for full WebSocket integration.
        
        Args:
            tickers: List of ticker symbols to process
            
        Returns:
            List of (ticker, success, result) tuples
        """
        def process_ticker(ticker: str) -> Tuple[str, bool, any]:
            """Process a single ticker (news + analysis)."""
            try:
                self._fetch_news(ticker)
                trade_executed = self._analyze_ticker(ticker)
                return (ticker, True, trade_executed)
            except Exception as e:
                return (ticker, False, str(e))
        
        results = []
        futures = {self._executor.submit(process_ticker, ticker): ticker for ticker in tickers}
        
        for future in as_completed(futures, timeout=60):
            ticker = futures[future]
            try:
                result = future.result(timeout=10)
                results.append(result)
            except Exception as e:
                results.append((ticker, False, str(e)))
        
        return results
    
    async def _process_tickers_async(self, tickers: List[str]) -> List[Tuple[str, bool, any]]:
        """
        Async version of ticker processing for WebSocket-driven execution.
        Paves the way for full async architecture with real-time data feeds.
        
        Args:
            tickers: List of ticker symbols to process
            
        Returns:
            List of (ticker, success, result) tuples
        """
        async def process_ticker_async(ticker: str) -> Tuple[str, bool, any]:
            """Process a single ticker asynchronously."""
            try:
                # Run blocking operations in thread pool
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(self._executor, self._fetch_news, ticker)
                trade_executed = await loop.run_in_executor(
                    self._executor, self._analyze_ticker, ticker
                )
                return (ticker, True, trade_executed)
            except Exception as e:
                return (ticker, False, str(e))
        
        # Process all tickers concurrently
        tasks = [process_ticker_async(ticker) for ticker in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions from gather
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append((tickers[i], False, str(result)))
            else:
                processed_results.append(result)
        
        return processed_results
    
    def _get_nifty_data(self) -> dict:
        """Fetch NIFTY 50 index data for regime detection."""
        try:
            # Use NIFTY 50 index or a proxy (e.g., NIFTYBEES ETF)
            nifty_ticker = "NIFTY 50"  # Or use actual index ticker
            candles = self.db.get_candles(nifty_ticker, limit=100)
            
            if candles.empty or len(candles) < 50:
                # Fallback: use aggregate of watchlist
                return self._get_aggregate_market_data()
            
            ema_50 = self.indicators.calculate_ema(candles, 50)
            ema_200 = self.indicators.calculate_ema_200(candles)
            
            return {
                'current_price': float(candles['close'].iloc[-1]),
                'ema_50': float(ema_50.iloc[-1]) if not ema_50.empty else 0,
                'ema_200': float(ema_200.iloc[-1]) if not ema_200.empty else 0,
                'high_24h': float(candles['high'].max()),
                'low_24h': float(candles['low'].min()),
                'range_pct': float((candles['high'].max() - candles['low'].min()) / candles['close'].iloc[-1] * 100),
                'volume_ratio': float(candles['volume'].iloc[-1] / candles['volume'].mean()) if candles['volume'].mean() > 0 else 1.0,
                'recent_candles': candles.tail(6).to_dict('records')
            }
        except Exception as e:
            logger.warning(f"Failed to get NIFTY data: {e}")
            return self._get_aggregate_market_data()
    
    def _get_aggregate_market_data(self) -> dict:
        """Get aggregate market data from watchlist as fallback."""
        prices = []
        for ticker in WATCHLIST[:5]:
            candles = self.db.get_candles(ticker, limit=10)
            if not candles.empty:
                prices.append(candles['close'].iloc[-1])
        
        avg_price = sum(prices) / len(prices) if prices else 100
        return {
            'current_price': avg_price,
            'ema_50': avg_price,
            'ema_200': avg_price,
            'high_24h': avg_price * 1.01,
            'low_24h': avg_price * 0.99,
            'range_pct': 2.0,
            'volume_ratio': 1.0,
            'recent_candles': []
        }
    
    def _run_heartbeat(self):
        """Main heartbeat loop - runs every candle interval."""
        logger.info(f"Heartbeat: {datetime.now().strftime('%H:%M:%S')}")
        
        # Check regime and adjust risk limits if needed
        if self.regime_detector.should_check_regime():
            logger.info("🔍 Checking market regime...")
            nifty_data = self._get_nifty_data()
            regime_state = self.regime_detector.analyze_regime(nifty_data)
            
            if regime_state.kill_switch_multiplier < 1.0:
                self.risk_manager.kill_switch.apply_regime_multiplier(
                    regime_state.kill_switch_multiplier,
                    regime_state.regime.value
                )
                logger.warning(f"⚠️ CHOPPY regime detected - risk limit reduced to {regime_state.kill_switch_multiplier:.0%}")
            else:
                # Reset to full limit for trending markets
                self.risk_manager.kill_switch.reset_regime_multiplier()
        
        # Check risk state
        mtm_loss = self.db.get_mtm_loss()
        risk_state = self.risk_manager.get_state(mtm_loss)
        
        if risk_state.kill_switch_triggered:
            logger.error("Kill switch is triggered - halting")
            return False
        
        # Check if should close positions (end of day)
        if self.risk_manager.should_close_positions():
            logger.info("🕒 Market closing soon - squaring off positions")
            self.executor.close_all_trades("End of Day Square Off")
            return False
        
        # Process tickers in parallel - async-ready architecture
        # Uses ThreadPoolExecutor for CPU-bound work, preparing for full async with WebSockets
        results = self._process_tickers_parallel(WATCHLIST)
        
        for ticker, success, result in results:
            if not success:
                logger.error(f"Error processing {ticker}: {result}")
        
        # Check stop loss / take profit for all positions
        self.executor.check_stop_loss_take_profit()
        
        # Update smart trailing stops for all active positions
        positions_to_remove = []
        for ticker, position in self.trailing_stop.get_all_positions().items():
            try:
                candles = self.db.get_candles(ticker, limit=20)
                if candles.empty:
                    continue
                    
                current_price = candles['close'].iloc[-1]
                ema_9 = self.indicators.calculate_ema_9(candles)
                current_ema_9 = ema_9.iloc[-1] if not ema_9.empty else current_price
                
                new_sl, stage, exit_signal = self.trailing_stop.update_stop(
                    ticker, current_price, current_ema_9
                )
                
                if exit_signal:
                    logger.info(f"🛑 {ticker}: Trailing/Time stop triggered at ₹{current_price:.2f}")
                    self.executor.exit_by_ticker(ticker, reason="Trailing/Time Stop Hit")
                    positions_to_remove.append(ticker)
            except Exception as e:
                logger.warning(f"Trailing stop update failed for {ticker}: {e}")
        
        # Clean up exited positions from trailing stop manager
        for ticker in positions_to_remove:
            self.trailing_stop.remove_position(ticker)
        
        # Log stats
        stats = self.executor.get_stats()
        logger.info(f"📊 Stats: Trades={stats['trades_executed']} | "
                   f"PnL=₹{stats['total_pnl']:.2f} | "
                   f"MTM=₹{stats['unrealized_pnl']:.2f}")
        
        return True
    
    def _run_autopsy(self):
        """Run post-trade autopsy at end of day."""
        logger.info("📋 Running post-trade autopsy...")
        
        trades = self.db.get_todays_trades()
        if trades.empty:
            logger.info("No trades to analyze today")
            return
        
        trades_list = trades.to_dict('records')
        
        # Get tick data summary
        tick_data = {}
        for ticker in WATCHLIST:
            latest = self.db.get_latest_candle(ticker)
            if latest:
                tick_data[ticker] = latest
        
        result = self.autopsy.analyze(trades_list, tick_data)
        report = self.autopsy.format_report(result)
        
        # Save report
        report_path = Path(f"reports/autopsy_{datetime.now().strftime('%Y%m%d')}.txt")
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(report)
        
        logger.info(f"Autopsy report saved: {report_path}")
        print(report)
    
    def run(self):
        """Main entry point - run The Sentinel."""
        logger.info("🚀 Starting The Sentinel...")
        
        # Check if market is open
        if not self.risk_manager.market_hours.is_market_open():
            time_to_open = self.risk_manager.market_hours.time_to_open()
            if time_to_open > 0:
                logger.info(f"Market closed. Opens in {time_to_open // 60} minutes")
                logger.info("Starting in simulation mode (market hours ignored)...")
        
        # Start ticker
        self.ticker.subscribe([
            self.ticker.get_token(symbol) for symbol in WATCHLIST
        ])
        self.ticker.connect(threaded=True)
        
        self._running = True
        logger.info(f"📡 Monitoring: {', '.join(WATCHLIST)}")
        logger.info(f"⏱️  Heartbeat interval: {CANDLE_INTERVAL_SECONDS}s")
        
        try:
            while self._running and not self._shutdown_requested:
                # Run heartbeat
                should_continue = self._run_heartbeat()
                
                if not should_continue:
                    break
                
                # Wait for next interval
                time.sleep(CANDLE_INTERVAL_SECONDS)
                
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            self._shutdown()
    
    def _shutdown(self):
        """Graceful shutdown procedure."""
        logger.info("🛑 Initiating shutdown...")
        
        self._running = False
        
        # Shutdown thread pool executor
        logger.info("Shutting down thread pool...")
        self._executor.shutdown(wait=True, cancel_futures=True)
        
        # Close all positions
        if self.executor.get_active_trades():
            logger.info("Closing active positions...")
            self.executor.close_all_trades("Shutdown")
        
        # Run autopsy
        self._run_autopsy()
        
        # Close connections
        self.ticker.close()
        self.db.close()
        
        # Final stats
        stats = self.executor.get_stats()
        logger.info("=" * 60)
        logger.info("📊 FINAL SESSION STATS")
        logger.info(f"   Trades Executed: {stats['trades_executed']}")
        logger.info(f"   Trades Closed: {stats['trades_closed']}")
        logger.info(f"   Total PnL: ₹{stats['total_pnl']:.2f}")
        logger.info(f"   Win Rate: {stats['win_rate']:.1f}%")
        logger.info("=" * 60)
        logger.info("🛡️  The Sentinel has shut down gracefully")


def main():
    """Entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="The Sentinel: Multimodal Alpha Engine")
    parser.add_argument('--mock', action='store_true', 
                       help='Use mock Gemini (no API calls)')
    parser.add_argument('--test', action='store_true',
                       help='Run a quick test cycle')
    args = parser.parse_args()
    
    sentinel = Sentinel(use_mock_gemini=args.mock)
    
    if args.test:
        # Quick test - run one heartbeat
        logger.info("Running test cycle...")
        sentinel.ticker.subscribe([
            sentinel.ticker.get_token(symbol) for symbol in WATCHLIST
        ])
        sentinel.ticker.connect(threaded=True)
        time.sleep(5)  # Let some ticks come in
        sentinel._run_heartbeat()
        sentinel._shutdown()
    else:
        sentinel.run()


if __name__ == "__main__":
    main()
