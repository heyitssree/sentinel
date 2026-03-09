#!/usr/bin/env python3
"""
Sentinel Watchdog - Independent MTM Monitor

CRITICAL SAFETY SCRIPT:
This script runs INDEPENDENTLY of the main SentinelEngine.
It monitors MTM using REST API (not WebSocket) and can:
1. Kill the main process if MTM loss exceeds ceiling
2. Force-close all positions as a last resort

WHY INDEPENDENT:
- If the main engine freezes/crashes, this watchdog still runs
- Uses REST API which is more reliable than WebSocket
- Can terminate the main process externally

USAGE:
    python scripts/watchdog.py &
    # Then start the main engine
    python main.py
"""
import os
import sys
import time
import signal
import logging
import argparse
from datetime import datetime, time as dt_time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WATCHDOG] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/watchdog.log')
    ]
)
logger = logging.getLogger(__name__)

# Safety ceiling from environment (default 3%)
MTM_LOSS_CEILING = float(os.getenv("MTM_LOSS_CEILING", "0.03"))
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "100000"))
POLL_INTERVAL = int(os.getenv("WATCHDOG_POLL_INTERVAL", "10"))  # seconds

# Calculate absolute limit
MTM_LOSS_LIMIT = STARTING_CAPITAL * MTM_LOSS_CEILING


class SentinelWatchdog:
    """
    Independent MTM monitor that uses REST API.
    
    Runs as a separate process and monitors:
    - MTM loss via kite.margins()
    - Main process health
    
    Can kill main process and close positions if needed.
    """
    
    def __init__(
        self,
        api_key: str = None,
        access_token: str = None,
        main_pid: int = None,
        poll_interval: int = POLL_INTERVAL,
        mtm_limit: float = MTM_LOSS_LIMIT
    ):
        self.api_key = api_key or os.getenv("KITE_API_KEY")
        self.access_token = access_token or os.getenv("KITE_ACCESS_TOKEN")
        self.main_pid = main_pid
        self.poll_interval = poll_interval
        self.mtm_limit = mtm_limit
        
        self.kite = None
        self.running = False
        self.triggered = False
        self.trigger_time = None
        
        # Market hours
        self.market_open = dt_time(9, 15)
        self.market_close = dt_time(15, 30)
        
        logger.info(f"Watchdog initialized: MTM limit=₹{mtm_limit:,.0f}, poll={poll_interval}s")
    
    def _setup_kite(self) -> bool:
        """Initialize KiteConnect for REST API calls."""
        try:
            from kiteconnect import KiteConnect
            
            if not self.api_key or not self.access_token:
                logger.error("Missing KITE_API_KEY or KITE_ACCESS_TOKEN")
                return False
            
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(self.access_token)
            
            # Verify connection
            profile = self.kite.profile()
            logger.info(f"Connected to Zerodha as: {profile.get('user_name', 'Unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup Kite: {e}")
            return False
    
    def _is_market_hours(self) -> bool:
        """Check if market is open."""
        now = datetime.now()
        if now.weekday() >= 5:  # Weekend
            return False
        current_time = now.time()
        return self.market_open <= current_time <= self.market_close
    
    def get_mtm_loss(self) -> float:
        """
        Get current MTM loss using REST API (kite.margins()).
        
        Returns:
            Current MTM loss (positive = loss)
        """
        if not self.kite:
            return 0.0
        
        try:
            margins = self.kite.margins(segment="equity")
            
            # Calculate available margin vs used
            available = margins.get("available", {}).get("cash", 0)
            used = margins.get("utilised", {}).get("m2m_unrealised", 0)
            
            # M2M unrealised is negative when losing
            mtm_loss = -used if used < 0 else 0
            
            logger.debug(f"MTM check: available=₹{available:,.0f}, m2m=₹{used:,.0f}, loss=₹{mtm_loss:,.0f}")
            return mtm_loss
            
        except Exception as e:
            logger.error(f"Failed to get margins: {e}")
            return 0.0
    
    def get_positions(self) -> list:
        """Get all open positions."""
        if not self.kite:
            return []
        
        try:
            positions = self.kite.positions()
            return positions.get("day", []) + positions.get("net", [])
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def force_close_all_positions(self) -> int:
        """
        Emergency: Close all open positions at market price.
        
        Returns:
            Number of positions closed
        """
        if not self.kite:
            logger.error("Cannot close positions - Kite not connected")
            return 0
        
        positions = self.get_positions()
        closed = 0
        
        for pos in positions:
            if pos.get("quantity", 0) == 0:
                continue
            
            try:
                symbol = pos["tradingsymbol"]
                qty = abs(pos["quantity"])
                side = "SELL" if pos["quantity"] > 0 else "BUY"
                
                logger.warning(f"Force closing: {side} {qty} {symbol}")
                
                self.kite.place_order(
                    variety="regular",
                    exchange="NSE",
                    tradingsymbol=symbol,
                    transaction_type=side,
                    quantity=qty,
                    product="CNC",
                    order_type="MARKET"
                )
                closed += 1
                
            except Exception as e:
                logger.error(f"Failed to close {pos.get('tradingsymbol')}: {e}")
        
        return closed
    
    def kill_main_process(self) -> bool:
        """
        Kill the main SentinelEngine process.
        
        Returns:
            True if process was killed
        """
        if not self.main_pid:
            # Try to find uvicorn process
            try:
                import subprocess
                result = subprocess.run(
                    ["pgrep", "-f", "uvicorn.*main:app"],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    self.main_pid = int(result.stdout.strip().split()[0])
                    logger.info(f"Found main process PID: {self.main_pid}")
            except Exception as e:
                logger.warning(f"Could not find main process: {e}")
                return False
        
        if not self.main_pid:
            logger.warning("No main PID to kill")
            return False
        
        try:
            os.kill(self.main_pid, signal.SIGTERM)
            logger.critical(f"🛑 KILLED main process (PID {self.main_pid})")
            return True
        except ProcessLookupError:
            logger.info("Main process already terminated")
            return True
        except Exception as e:
            logger.error(f"Failed to kill main process: {e}")
            return False
    
    def trigger_emergency_stop(self, reason: str):
        """Execute emergency stop procedure."""
        if self.triggered:
            return
        
        self.triggered = True
        self.trigger_time = datetime.now()
        
        logger.critical("=" * 60)
        logger.critical("🚨 WATCHDOG EMERGENCY STOP TRIGGERED 🚨")
        logger.critical(f"Reason: {reason}")
        logger.critical(f"Time: {self.trigger_time}")
        logger.critical("=" * 60)
        
        # Step 1: Kill main process
        self.kill_main_process()
        
        # Step 2: Force close positions (optional, uncomment if needed)
        # closed = self.force_close_all_positions()
        # logger.critical(f"Force-closed {closed} positions")
        
        # Write trigger file for other processes to detect
        trigger_file = Path("data/watchdog_triggered.txt")
        trigger_file.parent.mkdir(exist_ok=True)
        trigger_file.write_text(f"{self.trigger_time}\n{reason}")
        
        logger.critical("Emergency stop complete - manual intervention required")
    
    def run(self):
        """Main watchdog loop."""
        logger.info("=" * 50)
        logger.info("SENTINEL WATCHDOG STARTING")
        logger.info(f"MTM Limit: ₹{self.mtm_limit:,.0f} ({MTM_LOSS_CEILING*100:.1f}%)")
        logger.info(f"Poll Interval: {self.poll_interval}s")
        logger.info("=" * 50)
        
        # Setup Kite connection
        if not self._setup_kite():
            logger.warning("Running in offline mode - Kite not connected")
        
        self.running = True
        check_count = 0
        
        # Handle graceful shutdown
        def shutdown_handler(signum, frame):
            logger.info("Watchdog shutting down...")
            self.running = False
        
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)
        
        while self.running:
            try:
                check_count += 1
                
                # Only check during market hours
                if not self._is_market_hours():
                    if check_count % 30 == 0:  # Log every 5 minutes
                        logger.debug("Market closed - watchdog idle")
                    time.sleep(self.poll_interval)
                    continue
                
                # Get MTM loss
                mtm_loss = self.get_mtm_loss()
                
                # Log status periodically
                if check_count % 6 == 0:  # Every minute
                    logger.info(f"MTM Check #{check_count}: loss=₹{mtm_loss:,.0f}, limit=₹{self.mtm_limit:,.0f}")
                
                # Check if limit exceeded
                if mtm_loss >= self.mtm_limit:
                    self.trigger_emergency_stop(
                        f"MTM loss ₹{mtm_loss:,.0f} exceeded limit ₹{self.mtm_limit:,.0f}"
                    )
                    break
                
                time.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                time.sleep(self.poll_interval)
        
        logger.info("Watchdog stopped")


def main():
    parser = argparse.ArgumentParser(description="Sentinel Watchdog - Independent MTM Monitor")
    parser.add_argument("--pid", type=int, help="PID of main process to monitor")
    parser.add_argument("--limit", type=float, default=MTM_LOSS_LIMIT, 
                        help=f"MTM loss limit in INR (default: {MTM_LOSS_LIMIT})")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL,
                        help=f"Poll interval in seconds (default: {POLL_INTERVAL})")
    parser.add_argument("--test", action="store_true", help="Run a single test check")
    
    args = parser.parse_args()
    
    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)
    
    watchdog = SentinelWatchdog(
        main_pid=args.pid,
        poll_interval=args.interval,
        mtm_limit=args.limit
    )
    
    if args.test:
        logger.info("Running single test check...")
        if watchdog._setup_kite():
            mtm = watchdog.get_mtm_loss()
            logger.info(f"Current MTM loss: ₹{mtm:,.0f}")
            positions = watchdog.get_positions()
            logger.info(f"Open positions: {len(positions)}")
        else:
            logger.error("Could not connect to Kite for test")
        return
    
    watchdog.run()


if __name__ == "__main__":
    main()
