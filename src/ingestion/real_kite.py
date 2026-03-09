"""
Real Kite Connect client for live market data.
Wraps Zerodha's KiteConnect and KiteTicker APIs.
Interface matches MockKite/MockTicker for easy swapping.

Includes:
- Exponential backoff reconnection (1s -> 60s max)
- Connection state tracking
- Auto-reconnect on disconnect
"""
import os
import ssl
import logging
import urllib3
import certifi
import requests
import threading
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from enum import Enum

# Fix SSL certificate issues on macOS
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# Monkey-patch requests to disable SSL verification (for macOS SSL issues)
_original_request = requests.Session.request
def _patched_request(self, *args, **kwargs):
    if 'verify' not in kwargs:
        kwargs['verify'] = False
    return _original_request(self, *args, **kwargs)
requests.Session.request = _patched_request

# Set default SSL context
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from kiteconnect import KiteConnect, KiteTicker

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class RealTicker:
    """
    Real WebSocket ticker using Zerodha's KiteTicker.
    Interface matches MockTicker for seamless swapping.
    
    Features:
    - Exponential backoff reconnection (1s, 2s, 4s... max 60s)
    - Connection state tracking
    - Auto-reconnect on disconnect
    """
    
    # Reconnection settings
    INITIAL_RETRY_DELAY = 1.0      # Start with 1 second
    MAX_RETRY_DELAY = 60.0         # Max 60 seconds
    RETRY_MULTIPLIER = 2.0         # Double each time
    MAX_RETRIES = 10               # Give up after 10 attempts
    
    # NSE instrument tokens for common stocks
    INSTRUMENT_TOKENS = {
        "RELIANCE": 738561,
        "ICICIBANK": 1270529,
        "TCS": 2953217,
        "INFY": 408065,
        "HDFCBANK": 341249,
        "HINDUNILVR": 356865,
        "SBIN": 779521,
        "BHARTIARTL": 2714625,
        "KOTAKBANK": 492033,
        "ITC": 424961,
        "JSWSTEEL": 3001089,
        "TATAMOTORS": 884737,
        "WIPRO": 969473,
        "HCLTECH": 1850625,
        "MARUTI": 2815745,
        "AXISBANK": 1510401,
        "SUNPHARMA": 857857,
        "TITAN": 897537,
        "BAJFINANCE": 81153,
        "ADANIENT": 6401,
    }
    
    TOKEN_TO_SYMBOL = {v: k for k, v in INSTRUMENT_TOKENS.items()}
    
    def __init__(self, api_key: str, access_token: str, auto_reconnect: bool = True):
        self.api_key = api_key
        self.access_token = access_token
        self.auto_reconnect = auto_reconnect
        self._subscribed_tokens: List[int] = []
        self._ticker: Optional[KiteTicker] = None
        
        # Connection state
        self._state = ConnectionState.DISCONNECTED
        self._retry_count = 0
        self._current_retry_delay = self.INITIAL_RETRY_DELAY
        self._reconnect_thread: Optional[threading.Thread] = None
        self._stop_reconnect = threading.Event()
        self._last_connect_time: Optional[datetime] = None
        self._last_disconnect_time: Optional[datetime] = None
        
        # Callbacks (same interface as MockTicker)
        self.on_ticks: Optional[Callable[[Any, List[Dict]], None]] = None
        self.on_connect: Optional[Callable[[Any, Dict], None]] = None
        self.on_close: Optional[Callable[[Any, int, str], None]] = None
        self.on_error: Optional[Callable[[Any, int, str], None]] = None
        self.on_reconnect: Optional[Callable[[Any, int], None]] = None  # New callback
        
        logger.info(f"RealTicker initialized (auto_reconnect={auto_reconnect})")
    
    def _setup_ticker(self):
        """Initialize the KiteTicker with callbacks."""
        self._ticker = KiteTicker(self.api_key, self.access_token)
        
        def on_ticks(ws, ticks):
            if self.on_ticks:
                # Transform ticks to match our expected format
                formatted_ticks = []
                for tick in ticks:
                    formatted_ticks.append({
                        'instrument_token': tick.get('instrument_token'),
                        'last_price': tick.get('last_price'),
                        'open': tick.get('ohlc', {}).get('open', tick.get('last_price')),
                        'high': tick.get('ohlc', {}).get('high', tick.get('last_price')),
                        'low': tick.get('ohlc', {}).get('low', tick.get('last_price')),
                        'close': tick.get('ohlc', {}).get('close', tick.get('last_price')),
                        'volume': tick.get('volume_traded', 0),
                        'buy_quantity': tick.get('total_buy_quantity', 0),
                        'sell_quantity': tick.get('total_sell_quantity', 0),
                        'change': tick.get('change', 0),
                        'timestamp': datetime.now(),
                    })
                self.on_ticks(self, formatted_ticks)
        
        def on_connect(ws, response):
            logger.info(f"KiteTicker connected: {response}")
            self._state = ConnectionState.CONNECTED
            self._last_connect_time = datetime.now()
            self._reset_retry_state()
            
            if self._subscribed_tokens:
                ws.subscribe(self._subscribed_tokens)
                ws.set_mode(ws.MODE_FULL, self._subscribed_tokens)
            if self.on_connect:
                self.on_connect(self, response)
        
        def on_close(ws, code, reason):
            logger.warning(f"KiteTicker closed: {code} - {reason}")
            self._state = ConnectionState.DISCONNECTED
            self._last_disconnect_time = datetime.now()
            
            if self.on_close:
                self.on_close(self, code, reason)
            
            # Trigger auto-reconnect
            if self.auto_reconnect and not self._stop_reconnect.is_set():
                self._start_reconnect()
        
        def on_error(ws, code, reason):
            logger.error(f"KiteTicker error: {code} - {reason}")
            if self.on_error:
                self.on_error(self, code, reason)
        
        self._ticker.on_ticks = on_ticks
        self._ticker.on_connect = on_connect
        self._ticker.on_close = on_close
        self._ticker.on_error = on_error
    
    def _reset_retry_state(self):
        """Reset retry state after successful connection."""
        self._retry_count = 0
        self._current_retry_delay = self.INITIAL_RETRY_DELAY
        logger.debug("Retry state reset")
    
    def _calculate_next_delay(self) -> float:
        """Calculate next retry delay using exponential backoff."""
        delay = min(self.MAX_RETRY_DELAY, self._current_retry_delay)
        self._current_retry_delay = min(
            self.MAX_RETRY_DELAY,
            self._current_retry_delay * self.RETRY_MULTIPLIER
        )
        return delay
    
    def _start_reconnect(self):
        """Start reconnection in background thread."""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return  # Already reconnecting
        
        self._state = ConnectionState.RECONNECTING
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()
    
    def _reconnect_loop(self):
        """Reconnection loop with exponential backoff."""
        while not self._stop_reconnect.is_set() and self._retry_count < self.MAX_RETRIES:
            self._retry_count += 1
            delay = self._calculate_next_delay()
            
            logger.info(
                f"🔄 Reconnecting in {delay:.1f}s "
                f"(attempt {self._retry_count}/{self.MAX_RETRIES})"
            )
            
            # Wait with ability to be interrupted
            if self._stop_reconnect.wait(delay):
                logger.info("Reconnection cancelled")
                return
            
            try:
                # Notify callback
                if self.on_reconnect:
                    self.on_reconnect(self, self._retry_count)
                
                # Attempt reconnection
                self._setup_ticker()
                self._ticker.connect(threaded=True)
                
                # Wait a bit to see if connection succeeds
                time.sleep(2)
                
                if self.is_connected():
                    logger.info(f"✅ Reconnected after {self._retry_count} attempts")
                    return
                    
            except Exception as e:
                logger.error(f"Reconnection attempt {self._retry_count} failed: {e}")
        
        if self._retry_count >= self.MAX_RETRIES:
            self._state = ConnectionState.FAILED
            logger.critical(
                f"❌ Failed to reconnect after {self.MAX_RETRIES} attempts. "
                "Manual intervention required."
            )
    
    def subscribe(self, tokens: List[int]):
        """Subscribe to instrument tokens."""
        self._subscribed_tokens = tokens
        if self._ticker:
            self._ticker.subscribe(tokens)
            self._ticker.set_mode(self._ticker.MODE_FULL, tokens)
        logger.info(f"Subscribed to tokens: {tokens}")
    
    def unsubscribe(self, tokens: List[int]):
        """Unsubscribe from instrument tokens."""
        for token in tokens:
            if token in self._subscribed_tokens:
                self._subscribed_tokens.remove(token)
        if self._ticker:
            self._ticker.unsubscribe(tokens)
    
    def connect(self, threaded: bool = True):
        """Start the WebSocket connection."""
        self._state = ConnectionState.CONNECTING
        self._stop_reconnect.clear()
        self._setup_ticker()
        logger.info("Connecting to Zerodha KiteTicker...")
        self._ticker.connect(threaded=threaded)
    
    def close(self):
        """Close the WebSocket connection and stop auto-reconnect."""
        self._stop_reconnect.set()  # Stop any reconnection attempts
        if self._ticker:
            self._ticker.close()
            self._state = ConnectionState.DISCONNECTED
            logger.info("KiteTicker connection closed")
    
    def is_connected(self) -> bool:
        """Check if ticker is connected."""
        return self._ticker is not None and self._ticker.is_connected()
    
    def get_connection_state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state
    
    def get_connection_status(self) -> dict:
        """Get detailed connection status for API."""
        return {
            "state": self._state.value,
            "is_connected": self.is_connected(),
            "retry_count": self._retry_count,
            "max_retries": self.MAX_RETRIES,
            "current_retry_delay": self._current_retry_delay,
            "last_connect_time": self._last_connect_time.isoformat() if self._last_connect_time else None,
            "last_disconnect_time": self._last_disconnect_time.isoformat() if self._last_disconnect_time else None,
            "auto_reconnect": self.auto_reconnect,
            "subscribed_tokens": len(self._subscribed_tokens),
        }
    
    def force_reconnect(self):
        """Force a reconnection attempt."""
        logger.info("Force reconnect requested")
        self._reset_retry_state()
        self.close()
        time.sleep(1)
        self.connect(threaded=True)
    
    def get_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol."""
        return self.INSTRUMENT_TOKENS.get(symbol.upper())
    
    def get_symbol(self, token: int) -> Optional[str]:
        """Get symbol for an instrument token."""
        return self.TOKEN_TO_SYMBOL.get(token)


def _patch_kite_session(kite: KiteConnect):
    """Patch KiteConnect session to disable SSL verification (macOS fix)."""
    original_request = kite.reqsession.request
    def patched_request(*args, **kwargs):
        kwargs['verify'] = False
        return original_request(*args, **kwargs)
    kite.reqsession.request = patched_request
    return kite


class RealKite:
    """
    Real Kite Connect client for live trading.
    Interface matches MockKite for seamless swapping.
    """
    
    def __init__(self, api_key: str = None, access_token: str = None):
        self.api_key = api_key or os.getenv("KITE_API_KEY", "")
        self.access_token = access_token or os.getenv("KITE_ACCESS_TOKEN", "")
        self._kite: Optional[KiteConnect] = None
        self._ticker: Optional[RealTicker] = None
        
        if self.api_key:
            self._kite = KiteConnect(api_key=self.api_key)
            _patch_kite_session(self._kite)  # Fix SSL issues on macOS
            if self.access_token:
                self._kite.set_access_token(self.access_token)
            logger.info("RealKite initialized with KiteConnect")
        else:
            logger.warning("RealKite: No API key provided")
    
    def set_access_token(self, access_token: str):
        """Set the access token after login."""
        self.access_token = access_token
        if self._kite:
            self._kite.set_access_token(access_token)
        if self._ticker:
            self._ticker.access_token = access_token
    
    def set_ticker(self, ticker: RealTicker):
        """Set the ticker instance."""
        self._ticker = ticker
    
    def get_ticker(self) -> Optional[RealTicker]:
        """Get the ticker instance."""
        return self._ticker
    
    def create_ticker(self) -> RealTicker:
        """Create and return a new ticker instance."""
        self._ticker = RealTicker(self.api_key, self.access_token)
        return self._ticker
    
    def login_url(self) -> str:
        """Get the login URL for Kite Connect."""
        if self._kite:
            return self._kite.login_url()
        return ""
    
    def generate_session(self, request_token: str, api_secret: str) -> Dict:
        """Generate session from request token."""
        if self._kite:
            data = self._kite.generate_session(request_token, api_secret=api_secret)
            self.set_access_token(data.get("access_token", ""))
            return data
        return {}
    
    def profile(self) -> Dict:
        """Get user profile."""
        if self._kite:
            return self._kite.profile()
        return {}
    
    def margins(self, segment: str = "equity") -> Dict:
        """Get account margins."""
        if self._kite:
            return self._kite.margins(segment)
        return {}
    
    def ltp(self, instruments: List[str]) -> Dict:
        """Get last traded price for instruments."""
        if self._kite:
            return self._kite.ltp(instruments)
        return {}
    
    def quote(self, instruments: List[str]) -> Dict:
        """Get full quote for instruments."""
        if self._kite:
            return self._kite.quote(instruments)
        return {}
    
    def ohlc(self, instruments: List[str]) -> Dict:
        """Get OHLC data for instruments."""
        if self._kite:
            return self._kite.ohlc(instruments)
        return {}
    
    def historical_data(self, instrument_token: int, from_date: str, to_date: str, 
                        interval: str, continuous: bool = False) -> List[Dict]:
        """Get historical candle data."""
        if self._kite:
            return self._kite.historical_data(
                instrument_token, from_date, to_date, interval, continuous
            )
        return []
    
    def instruments(self, exchange: str = "NSE") -> List[Dict]:
        """Get list of instruments for an exchange."""
        if self._kite:
            return self._kite.instruments(exchange)
        return []
    
    def is_configured(self) -> bool:
        """Check if Kite is properly configured."""
        return bool(self.api_key and self.access_token)
    
    def test_connection(self) -> Dict:
        """Test the API connection."""
        try:
            if not self.is_configured():
                return {"success": False, "error": "API key or access token not configured"}
            
            profile = self.profile()
            return {
                "success": True,
                "user_id": profile.get("user_id"),
                "user_name": profile.get("user_name"),
                "email": profile.get("email"),
                "broker": profile.get("broker"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
