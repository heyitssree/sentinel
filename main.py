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
from datetime import datetime
from pathlib import Path

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
from src.signals.indicators import SignalEngine, TechnicalIndicators
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
        
        # Candle aggregation
        self._candle_data = {ticker: [] for ticker in WATCHLIST}
        self._last_candle_time = {ticker: None for ticker in WATCHLIST}
        
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
        # Signal engine
        self.signal_engine = SignalEngine()
        self.indicators = TechnicalIndicators()
        
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
        """Aggregate tick data into candles."""
        now = datetime.now()
        candle_start = now.replace(
            minute=(now.minute // 5) * 5,
            second=0,
            microsecond=0
        )
        
        if self._last_candle_time.get(symbol) != candle_start:
            # New candle period
            if self._candle_data[symbol]:
                # Save previous candle
                self._save_candle(symbol)
            
            # Start new candle
            self._candle_data[symbol] = []
            self._last_candle_time[symbol] = candle_start
        
        # Add tick to current candle
        self._candle_data[symbol].append({
            'price': tick['last_price'],
            'volume': tick.get('last_traded_quantity', 0),
            'timestamp': now
        })
    
    def _save_candle(self, symbol: str):
        """Save aggregated candle to database."""
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
        
        # Run signal analysis
        should_audit, analysis = self.signal_engine.should_trigger_audit(candles)
        
        if not should_audit:
            logger.debug(f"{ticker}: No signal | {analysis.get('reason', '')}")
            return False
        
        logger.info(f"🔔 {ticker}: Signal detected! Running Gemini audit...")
        
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
        
        # Calculate stop loss using ATR
        atr = self.indicators.calculate_atr(candles, 14)
        latest_atr = atr.iloc[-1] if not atr.empty else candles['close'].iloc[-1] * 0.02
        entry_price = candles['close'].iloc[-1]
        stop_loss = self.signal_engine.get_stop_loss(entry_price, latest_atr)
        take_profit = self.signal_engine.get_take_profit(entry_price, latest_atr)
        
        trade = self.executor.execute_entry(
            ticker=ticker,
            side="BUY",
            reason=analysis.get('reason', 'Signal triggered'),
            sentiment_score=sentiment_result.score,
            chart_safety=vision_result.safety,
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        
        if trade:
            self.risk_manager.post_order_record()
            logger.info(f"🚀 TRADE EXECUTED: {ticker} @ ₹{trade.entry_price:.2f}")
            logger.info(f"   SL: ₹{stop_loss:.2f} | TP: ₹{take_profit:.2f}")
            return True
        
        return False
    
    def _run_heartbeat(self):
        """Main heartbeat loop - runs every candle interval."""
        logger.info(f"Heartbeat: {datetime.now().strftime('%H:%M:%S')}")
        
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
        
        # Process each ticker
        for ticker in WATCHLIST:
            try:
                # Fetch news
                self._fetch_news(ticker)
                
                # Run analysis
                self._analyze_ticker(ticker)
                
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
        
        # Check stop loss / take profit for all positions
        self.executor.check_stop_loss_take_profit()
        
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
