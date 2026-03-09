"""
Mock Kite Connect class for paper trading.
Simulates Zerodha's KiteConnect API with realistic tick data generation.
Interface is designed to be swappable with the real KiteConnect class.
"""
import random
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
import threading
import time
import logging

logger = logging.getLogger(__name__)


class MockTicker:
    """
    Mock WebSocket ticker that simulates Zerodha's KiteTicker.
    Generates realistic price movements using geometric Brownian motion.
    """
    
    def __init__(self, api_key: str = "mock_api_key", access_token: str = "mock_token"):
        self.api_key = api_key
        self.access_token = access_token
        self._subscribed_tokens: List[int] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Callbacks
        self.on_ticks: Optional[Callable[[Any, List[Dict]], None]] = None
        self.on_connect: Optional[Callable[[Any, Dict], None]] = None
        self.on_close: Optional[Callable[[Any, int, str], None]] = None
        self.on_error: Optional[Callable[[Any, int, str], None]] = None
        
        # Mock instrument tokens (simulating Zerodha's instrument tokens)
        self.INSTRUMENT_TOKENS = {
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
            "JSWSTEEL": 3001089
        }
        
        self.TOKEN_TO_SYMBOL = {v: k for k, v in self.INSTRUMENT_TOKENS.items()}
        
        # Current prices (will be updated dynamically)
        self._prices: Dict[int, Dict[str, float]] = {}
        self._initialize_prices()
        
        # Volatility parameters (annualized, converted to per-tick)
        self._volatility = {
            738561: 0.25,    # RELIANCE
            1270529: 0.28,   # ICICIBANK
            2953217: 0.22,   # TCS
            408065: 0.26,    # INFY
            341249: 0.24,    # HDFCBANK
            356865: 0.20,    # HINDUNILVR
            779521: 0.30,    # SBIN
            2714625: 0.26,   # BHARTIARTL
            492033: 0.25,    # KOTAKBANK
            424961: 0.18,    # ITC
            3001089: 0.35    # JSWSTEEL
        }
    
    def _initialize_prices(self):
        """Initialize with realistic base prices."""
        base_prices = {
            738561: 2950.0,   # RELIANCE
            1270529: 1280.0,  # ICICIBANK
            2953217: 4150.0,  # TCS
            408065: 1890.0,   # INFY
            341249: 1720.0,   # HDFCBANK
            356865: 2450.0,   # HINDUNILVR
            779521: 780.0,    # SBIN
            2714625: 1650.0,  # BHARTIARTL
            492033: 1780.0,   # KOTAKBANK
            424961: 460.0,    # ITC
            3001089: 920.0    # JSWSTEEL
        }
        
        for token, price in base_prices.items():
            self._prices[token] = {
                'last_price': price,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0,
                'buy_quantity': random.randint(1000, 10000),
                'sell_quantity': random.randint(1000, 10000),
            }
    
    def _generate_tick(self, token: int) -> Dict:
        """Generate a realistic tick using geometric Brownian motion."""
        current = self._prices[token]
        
        # GBM parameters
        dt = 1 / (252 * 6.25 * 60)  # ~1 second in trading year terms
        sigma = self._volatility.get(token, 0.25)
        mu = 0.0001  # Small positive drift
        
        # Generate price change
        random_shock = random.gauss(0, 1)
        price_change = current['last_price'] * (mu * dt + sigma * math.sqrt(dt) * random_shock)
        new_price = max(current['last_price'] + price_change, 1.0)
        
        # Round to tick size (0.05 for NSE)
        new_price = round(new_price / 0.05) * 0.05
        
        # Update OHLC
        current['last_price'] = new_price
        current['high'] = max(current['high'], new_price)
        current['low'] = min(current['low'], new_price)
        current['volume'] += random.randint(100, 1000)
        
        # Simulate order book
        spread = new_price * 0.0005  # 0.05% spread
        
        return {
            'instrument_token': token,
            'tradable': True,
            'mode': 'full',
            'last_price': new_price,
            'last_traded_quantity': random.randint(1, 100),
            'average_traded_price': (current['open'] + new_price) / 2,
            'volume_traded': current['volume'],
            'total_buy_quantity': current['buy_quantity'],
            'total_sell_quantity': current['sell_quantity'],
            'ohlc': {
                'open': current['open'],
                'high': current['high'],
                'low': current['low'],
                'close': current['close']
            },
            'change': new_price - current['close'],
            'last_trade_time': datetime.now(),
            'timestamp': datetime.now(),
            'oi': 0,
            'depth': {
                'buy': [
                    {'price': new_price - spread, 'quantity': random.randint(100, 1000), 'orders': random.randint(1, 10)},
                    {'price': new_price - spread * 2, 'quantity': random.randint(100, 1000), 'orders': random.randint(1, 10)},
                ],
                'sell': [
                    {'price': new_price + spread, 'quantity': random.randint(100, 1000), 'orders': random.randint(1, 10)},
                    {'price': new_price + spread * 2, 'quantity': random.randint(100, 1000), 'orders': random.randint(1, 10)},
                ]
            }
        }
    
    def _tick_loop(self):
        """Main tick generation loop."""
        while self._running:
            if self._subscribed_tokens and self.on_ticks:
                ticks = [self._generate_tick(token) for token in self._subscribed_tokens]
                try:
                    self.on_ticks(self, ticks)
                except Exception as e:
                    logger.error(f"Error in on_ticks callback: {e}")
                    if self.on_error:
                        self.on_error(self, -1, str(e))
            
            # Simulate ~1 tick per second
            time.sleep(1)
    
    def connect(self, threaded: bool = True):
        """Start the mock WebSocket connection."""
        self._running = True
        
        if self.on_connect:
            self.on_connect(self, {"status": "connected"})
        
        if threaded:
            self._thread = threading.Thread(target=self._tick_loop, daemon=True)
            self._thread.start()
        else:
            self._tick_loop()
    
    def close(self):
        """Close the mock connection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self.on_close:
            self.on_close(self, 1000, "Connection closed")
    
    def subscribe(self, tokens: List[int]):
        """Subscribe to instrument tokens."""
        self._subscribed_tokens = list(set(self._subscribed_tokens + tokens))
        logger.info(f"Subscribed to tokens: {tokens}")
    
    def unsubscribe(self, tokens: List[int]):
        """Unsubscribe from instrument tokens."""
        self._subscribed_tokens = [t for t in self._subscribed_tokens if t not in tokens]
    
    def set_mode(self, mode: str, tokens: List[int]):
        """Set subscription mode (ltp, quote, full). Mock implementation."""
        pass
    
    def get_token(self, symbol: str) -> int:
        """Get instrument token for a symbol."""
        return self.INSTRUMENT_TOKENS.get(symbol, 0)
    
    def get_symbol(self, token: int) -> str:
        """Get symbol for an instrument token."""
        return self.TOKEN_TO_SYMBOL.get(token, "UNKNOWN")
    
    def reset_day(self):
        """Reset OHLC for a new trading day."""
        for token in self._prices:
            price = self._prices[token]['last_price']
            self._prices[token] = {
                'last_price': price,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0,
                'buy_quantity': random.randint(1000, 10000),
                'sell_quantity': random.randint(1000, 10000),
            }


class MockKite:
    """
    Mock KiteConnect class for paper trading.
    Simulates order placement, positions, and holdings.
    """
    
    def __init__(self, api_key: str = "mock_api_key"):
        self.api_key = api_key
        self._access_token: Optional[str] = None
        self._orders: Dict[str, Dict] = {}
        self._positions: Dict[str, Dict] = {}
        self._order_counter = 0
        
        # Reference to ticker for price lookup
        self._ticker: Optional[MockTicker] = None
        
        # Order types
        self.VARIETY_REGULAR = "regular"
        self.PRODUCT_MIS = "MIS"
        self.PRODUCT_CNC = "CNC"
        self.ORDER_TYPE_MARKET = "MARKET"
        self.ORDER_TYPE_LIMIT = "LIMIT"
        self.TRANSACTION_TYPE_BUY = "BUY"
        self.TRANSACTION_TYPE_SELL = "SELL"
        self.EXCHANGE_NSE = "NSE"
    
    def set_access_token(self, access_token: str):
        """Set access token (mock implementation)."""
        self._access_token = access_token
    
    def set_ticker(self, ticker: MockTicker):
        """Link ticker for price lookups."""
        self._ticker = ticker
    
    def _get_current_price(self, tradingsymbol: str) -> float:
        """Get current price from ticker."""
        if self._ticker:
            token = self._ticker.get_token(tradingsymbol)
            if token in self._ticker._prices:
                return self._ticker._prices[token]['last_price']
        return 0.0
    
    def _apply_slippage(self, price: float, transaction_type: str, 
                         slippage_pct: float = 0.0005) -> float:
        """Apply slippage to simulate realistic execution."""
        if transaction_type == "BUY":
            return price * (1 + slippage_pct)
        else:
            return price * (1 - slippage_pct)
    
    def place_order(self, variety: str, exchange: str, tradingsymbol: str,
                    transaction_type: str, quantity: int, product: str,
                    order_type: str, price: float = None, 
                    trigger_price: float = None, validity: str = "DAY",
                    **kwargs) -> str:
        """Place a mock order."""
        self._order_counter += 1
        order_id = f"MOCK{self._order_counter:010d}"
        
        # Get execution price
        if order_type == "MARKET":
            exec_price = self._get_current_price(tradingsymbol)
            exec_price = self._apply_slippage(exec_price, transaction_type)
        else:
            exec_price = price
        
        order = {
            'order_id': order_id,
            'exchange': exchange,
            'tradingsymbol': tradingsymbol,
            'transaction_type': transaction_type,
            'quantity': quantity,
            'product': product,
            'order_type': order_type,
            'price': price,
            'trigger_price': trigger_price,
            'average_price': exec_price,
            'filled_quantity': quantity,
            'pending_quantity': 0,
            'status': 'COMPLETE',
            'status_message': None,
            'order_timestamp': datetime.now(),
            'exchange_timestamp': datetime.now(),
            'variety': variety,
        }
        
        self._orders[order_id] = order
        
        # Update positions
        self._update_position(tradingsymbol, transaction_type, quantity, exec_price, product)
        
        logger.info(f"Order placed: {order_id} | {transaction_type} {quantity} {tradingsymbol} @ {exec_price:.2f}")
        
        return order_id
    
    def _update_position(self, tradingsymbol: str, transaction_type: str, 
                         quantity: int, price: float, product: str):
        """Update position after order execution."""
        if tradingsymbol not in self._positions:
            self._positions[tradingsymbol] = {
                'tradingsymbol': tradingsymbol,
                'quantity': 0,
                'average_price': 0,
                'last_price': price,
                'pnl': 0,
                'product': product,
                'm2m': 0,
                'buy_quantity': 0,
                'sell_quantity': 0,
                'buy_price': 0,
                'sell_price': 0,
            }
        
        pos = self._positions[tradingsymbol]
        
        if transaction_type == "BUY":
            # Adding to long or covering short
            if pos['quantity'] >= 0:
                # Adding to long
                total_value = pos['average_price'] * pos['quantity'] + price * quantity
                new_qty = pos['quantity'] + quantity
                pos['average_price'] = total_value / new_qty if new_qty > 0 else 0
                pos['quantity'] = new_qty
            else:
                # Covering short
                pos['quantity'] += quantity
                if pos['quantity'] >= 0:
                    pos['average_price'] = price
            pos['buy_quantity'] += quantity
            pos['buy_price'] = price
        else:
            # Adding to short or closing long
            if pos['quantity'] <= 0:
                # Adding to short
                total_value = abs(pos['average_price'] * pos['quantity']) + price * quantity
                new_qty = pos['quantity'] - quantity
                pos['average_price'] = total_value / abs(new_qty) if new_qty != 0 else 0
                pos['quantity'] = new_qty
            else:
                # Closing long
                pos['quantity'] -= quantity
                if pos['quantity'] <= 0:
                    pos['average_price'] = price
            pos['sell_quantity'] += quantity
            pos['sell_price'] = price
        
        pos['last_price'] = price
    
    def modify_order(self, variety: str, order_id: str, **kwargs) -> str:
        """Modify an existing order (mock)."""
        if order_id in self._orders:
            self._orders[order_id].update(kwargs)
        return order_id
    
    def cancel_order(self, variety: str, order_id: str) -> str:
        """Cancel an order (mock)."""
        if order_id in self._orders:
            self._orders[order_id]['status'] = 'CANCELLED'
        return order_id
    
    def orders(self) -> List[Dict]:
        """Get all orders."""
        return list(self._orders.values())
    
    def order_history(self, order_id: str) -> List[Dict]:
        """Get order history."""
        if order_id in self._orders:
            return [self._orders[order_id]]
        return []
    
    def positions(self) -> Dict[str, List[Dict]]:
        """Get positions."""
        day_positions = []
        net_positions = []
        
        for pos in self._positions.values():
            if pos['quantity'] != 0:
                # Update last price
                pos['last_price'] = self._get_current_price(pos['tradingsymbol'])
                pos['pnl'] = (pos['last_price'] - pos['average_price']) * pos['quantity']
                pos['m2m'] = pos['pnl']
                
                day_positions.append(pos.copy())
                net_positions.append(pos.copy())
        
        return {
            'day': day_positions,
            'net': net_positions
        }
    
    def holdings(self) -> List[Dict]:
        """Get holdings (empty for intraday)."""
        return []
    
    def margins(self, segment: str = "equity") -> Dict:
        """Get margin details (mock)."""
        return {
            'available': {
                'cash': 100000.0,
                'collateral': 0,
                'intraday_payin': 0
            },
            'utilised': {
                'exposure': 0,
                'span': 0,
                'option_premium': 0
            },
            'net': 100000.0
        }
    
    def quote(self, instruments: List[str]) -> Dict[str, Dict]:
        """Get quotes for instruments."""
        result = {}
        for inst in instruments:
            # Parse "NSE:RELIANCE" format
            parts = inst.split(':')
            symbol = parts[1] if len(parts) > 1 else parts[0]
            
            price = self._get_current_price(symbol)
            result[inst] = {
                'instrument_token': self._ticker.get_token(symbol) if self._ticker else 0,
                'last_price': price,
                'ohlc': {
                    'open': price,
                    'high': price * 1.01,
                    'low': price * 0.99,
                    'close': price
                },
                'volume': random.randint(100000, 1000000)
            }
        
        return result
    
    def ltp(self, instruments: List[str]) -> Dict[str, Dict]:
        """Get last traded price."""
        result = {}
        for inst in instruments:
            parts = inst.split(':')
            symbol = parts[1] if len(parts) > 1 else parts[0]
            result[inst] = {
                'last_price': self._get_current_price(symbol)
            }
        return result
    
    def close_all_positions(self):
        """Close all open positions (square off)."""
        for symbol, pos in list(self._positions.items()):
            if pos['quantity'] != 0:
                transaction_type = "SELL" if pos['quantity'] > 0 else "BUY"
                self.place_order(
                    variety=self.VARIETY_REGULAR,
                    exchange=self.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=transaction_type,
                    quantity=abs(pos['quantity']),
                    product=pos['product'],
                    order_type=self.ORDER_TYPE_MARKET
                )
        logger.info("All positions closed")
    
    def reset_day(self):
        """Reset for a new trading day."""
        self._orders.clear()
        self._positions.clear()
        self._order_counter = 0
